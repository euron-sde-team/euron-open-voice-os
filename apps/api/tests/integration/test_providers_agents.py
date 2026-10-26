"""Providers (AC5: secrets sealed and never returned; external classification for AC6) and
agents (templates, versions, the runtime's view of an agent), plus the internal endpoints."""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.conftest import Stack, Voice
from tests.integration.support import internal, scalar

pytestmark = pytest.mark.asyncio

SECRET = "sk-provider-secret-value-1234"


def provider(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "Hosted LLM",
        "stage": "llm",
        "adapter": "openai_compatible",
        "base_url": "https://llm.example.com/v1",
        "model": "big-model",
    }
    body.update(over)
    return body


# ── Providers ────────────────────────────────────────────────────────────────────────


async def test_provider_keys_are_sealed_and_never_returned(stack: Stack) -> None:
    created = await stack.ok("POST", "/api/v1/providers", provider(api_key=SECRET), status=201)
    assert created["has_api_key"] is True and created["key_hint"] == "...1234"
    listed = await stack.ok("GET", "/api/v1/providers")
    one = await stack.ok("GET", "/api/v1/providers?stage=llm")
    audit = await stack.ok("GET", "/api/v1/audit")
    for body in (created, listed, one, audit):
        assert SECRET not in str(body)
    sealed = await scalar(
        stack, "select sealed_key from providers where id = :id", id=created["id"]
    )
    assert sealed is not None and SECRET.encode() not in bytes(sealed)
    if stack.settings.key_mode == "local":
        from voiceos.core.sealing import LocalSealer

        sealer = LocalSealer(stack.settings.local_master_key)
        assert await sealer.open(bytes(sealed), created["id"]) == SECRET
        # Bound to its row: the same ciphertext pasted onto another provider does not open.
        with pytest.raises(Exception):  # noqa: B017 (any refusal is the point)
            await sealer.open(bytes(sealed), "00000000-0000-0000-0000-000000000001")


async def test_moving_a_provider_to_another_host_needs_its_key_again(stack: Stack) -> None:
    p = await stack.ok("POST", "/api/v1/providers", provider(api_key=SECRET))
    moved = await stack.client.patch(
        f"/api/v1/providers/{p['id']}", json={"base_url": "https://attacker.example.net/v1"}
    )
    assert moved.status_code == 400
    assert moved.json()["error"]["code"] == "api_key_required"
    # Same host, new path: the key stays.
    same = await stack.ok(
        "PATCH", f"/api/v1/providers/{p['id']}", {"base_url": "https://llm.example.com/v2"}
    )
    assert same["has_api_key"] is True
    # With the key again, or clearing it, the move is allowed and audited with both hosts.
    ok = await stack.ok(
        "PATCH",
        f"/api/v1/providers/{p['id']}",
        {"base_url": "https://other.example.org/v1", "api_key": "sk-new-key-5678"},
    )
    assert ok["key_hint"] == "...5678"
    cleared = await stack.ok(
        "PATCH",
        f"/api/v1/providers/{p['id']}",
        {"base_url": "https://third.example.org/v1", "clear_api_key": True},
    )
    assert cleared["has_api_key"] is False and cleared["key_hint"] is None
    audit = await stack.ok("GET", "/api/v1/audit?action=provider.updated")
    hosts = [e["details"].get("to_host") for e in audit["items"]]
    assert "https://other.example.org" in hosts


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://[fd00:ec2::254]/v1",
        "http://metadata.google.internal/v1",
        "http://0.0.0.0:8080/v1",
        "file:///etc/passwd",
        "ftp://llm.example.com/v1",
        "gopher://llm.example.com",
        "http:///v1",
    ],
)
async def test_providers_cannot_target_metadata_or_odd_schemes(stack: Stack, url: str) -> None:
    resp = await stack.client.post("/api/v1/providers", json=provider(base_url=url))
    assert resp.status_code == 422, (url, resp.text)


async def test_provider_validation(stack: Stack) -> None:
    wrong_stage = await stack.client.post(
        "/api/v1/providers", json=provider(stage="llm", adapter="deepgram")
    )
    assert wrong_stage.status_code == 422
    assert "not a llm adapter" in wrong_stage.text
    no_url = await stack.client.post("/api/v1/providers", json=provider(stage="stt", base_url=None))
    assert no_url.status_code == 422
    await stack.ok("POST", "/api/v1/providers", provider())
    dup = await stack.client.post("/api/v1/providers", json=provider())
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "provider_exists"


async def test_external_classification_can_only_be_raised(stack: Stack) -> None:
    public = await stack.ok("POST", "/api/v1/providers", provider(external=False))
    assert public["external"] is True and public["self_hosted"] is False
    private = await stack.ok(
        "POST",
        "/api/v1/providers",
        provider(name="Ollama", base_url="http://ollama:11434/v1"),
    )
    assert private["external"] is False and private["self_hosted"] is True
    marked = await stack.ok(
        "POST",
        "/api/v1/providers",
        provider(name="Proxy", base_url="http://10.0.3.7/v1", external=True),
    )
    assert marked["external"] is True and marked["self_hosted"] is False
    cloud = await stack.ok(
        "POST",
        "/api/v1/providers",
        {"name": "Deepgram", "stage": "stt", "adapter": "deepgram", "api_key": SECRET},
    )
    assert cloud["external"] is True
    # Lowering the flag on a public URL changes nothing.
    still = await stack.ok("PATCH", f"/api/v1/providers/{public['id']}", {"external": False})
    assert still["external"] is True
    # Raising it on a private one sticks; dropping it again returns to self-hosted.
    raised = await stack.ok("PATCH", f"/api/v1/providers/{private['id']}", {"external": True})
    assert raised["external"] is True
    lowered = await stack.ok("PATCH", f"/api/v1/providers/{private['id']}", {"external": False})
    assert lowered["self_hosted"] is True


async def test_a_provider_in_use_cannot_be_deleted(stack: Stack, voice: Voice) -> None:
    resp = await stack.client.delete(f"/api/v1/providers/{voice.llm}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "provider_in_use"
    listed = {p["id"]: p for p in await stack.ok("GET", "/api/v1/providers")}
    assert listed[voice.llm]["used_by"] == 1
    spare = await stack.ok("POST", "/api/v1/providers", provider(name="Spare"))
    await stack.ok("DELETE", f"/api/v1/providers/{spare['id']}", status=204)
    missing = await stack.client.delete(f"/api/v1/providers/{spare['id']}")
    assert missing.status_code == 404


async def test_the_test_button_reports_reachability(stack: Stack, voice: Voice) -> None:
    ok = await stack.ok("POST", f"/api/v1/providers/{voice.llm}/test")
    assert ok["ok"] is True and ok["latency_ms"] is not None
    down = await stack.ok(
        "POST", "/api/v1/providers", provider(name="Down", base_url="http://127.0.0.1:9/v1")
    )
    failed = await stack.ok("POST", f"/api/v1/providers/{down['id']}/test")
    assert failed["ok"] is False and "Could not reach" in failed["message"]
    broken = await stack.ok(
        "POST",
        "/api/v1/providers",
        provider(name="Wrong path", base_url=f"{stack.mock_url}/nothing-here"),
    )
    answered = await stack.ok("POST", f"/api/v1/providers/{broken['id']}/test")
    assert answered["ok"] is False and "HTTP 404" in answered["message"]
    cloud = await stack.ok(
        "POST",
        "/api/v1/providers",
        {"name": "Cartesia", "stage": "tts", "adapter": "cartesia", "api_key": SECRET},
    )
    skipped = await stack.ok("POST", f"/api/v1/providers/{cloud['id']}/test")
    assert skipped["ok"] is True and "no test call" in skipped["message"]


# ── Agents ───────────────────────────────────────────────────────────────────────────


async def test_templates_and_self_hosted_defaults(stack: Stack) -> None:
    templates = await stack.ok("GET", "/api/v1/agents/templates")
    ids = {t["id"] for t in templates}
    assert {"receptionist", "support", "tutor", "meeting", "hindi-tutor"} <= ids
    none = await stack.client.post("/api/v1/agents/from-template", json={"template": "tutor"})
    assert none.status_code == 400 and none.json()["error"]["code"] == "no_provider"

    hosted = {}
    for stage in ("stt", "llm", "tts"):
        hosted[stage] = await stack.ok(
            "POST",
            "/api/v1/providers",
            provider(name=f"Cloud {stage}", stage=stage, base_url="https://api.example.com/v1"),
        )
    local = {}
    for stage in ("stt", "llm", "tts"):
        local[stage] = await stack.ok(
            "POST",
            "/api/v1/providers",
            provider(name=f"Local {stage}", stage=stage, base_url="http://speech:8080/v1"),
        )
    agent = await stack.ok(
        "POST", "/api/v1/agents/from-template", {"template": "receptionist"}, status=201
    )
    for stage in ("stt", "llm", "tts"):
        assert agent[stage]["id"] == local[stage]["id"], stage
    assert agent["external_providers"] == []
    picked = await stack.ok(
        "POST",
        "/api/v1/agents/from-template",
        {"template": "support", "name": "Cloud support", "llm_provider_id": hosted["llm"]["id"]},
    )
    assert picked["name"] == "Cloud support"
    assert picked["external_providers"] == ["Cloud llm"]
    unknown = await stack.client.post("/api/v1/agents/from-template", json={"template": "nope"})
    assert unknown.status_code == 404


async def test_updates_bump_the_version_and_reach_the_runtime(stack: Stack, voice: Voice) -> None:
    async with internal(stack) as c:
        before = (await c.get(f"/internal/agents/{voice.agent}")).json()
        updated = await stack.ok(
            "PATCH",
            f"/api/v1/agents/{voice.agent}",
            {"system_prompt": "You are the new prompt.", "voice": "nova"},
        )
        assert updated["version"] == before["version"] + 1
        after = (await c.get(f"/internal/agents/{voice.agent}")).json()
    assert after["version"] == updated["version"]
    assert after["system_prompt"] == "You are the new prompt."
    assert after["tts"]["voice"] == "nova"
    got = await stack.ok("GET", f"/api/v1/agents/{voice.agent}")
    assert got["version"] == updated["version"]
    audit = await stack.ok("GET", "/api/v1/audit?action=agent.updated")
    assert audit["items"][0]["details"]["version"] == updated["version"]


async def test_the_runtime_gets_provider_secrets_only_over_the_internal_hop(
    stack: Stack, voice: Voice
) -> None:
    await stack.ok("PATCH", f"/api/v1/providers/{voice.llm}", {"api_key": SECRET})
    async with internal(stack) as c:
        body = (await c.get(f"/internal/agents/{voice.agent}")).json()
    assert body["llm"]["api_key"] == SECRET
    public = await stack.ok("GET", f"/api/v1/agents/{voice.agent}")
    assert SECRET not in str(public)


async def test_agent_validation(stack: Stack, voice: Voice) -> None:
    base = {
        "name": "V",
        "system_prompt": "x",
        "stt_provider_id": voice.stt,
        "llm_provider_id": voice.llm,
        "tts_provider_id": voice.tts,
    }
    webhook = await stack.client.post(
        "/api/v1/agents", json={**base, "tools": [{"name": "http_webhook"}]}
    )
    assert webhook.status_code == 400
    assert webhook.json()["error"]["code"] == "webhook_url_required"
    swapped = await stack.client.post("/api/v1/agents", json={**base, "stt_provider_id": voice.llm})
    assert swapped.status_code == 400
    assert swapped.json()["error"]["code"] == "wrong_provider_stage"
    ghost = await stack.client.post(
        "/api/v1/agents",
        json={**base, "llm_provider_id": "00000000-0000-0000-0000-000000000009"},
    )
    assert ghost.status_code == 400 and ghost.json()["error"]["code"] == "unknown_provider"
    bad_lang = await stack.client.post("/api/v1/agents", json={**base, "language": "english"})
    assert bad_lang.status_code == 422
    await stack.ok("PATCH", f"/api/v1/providers/{voice.tts}", {"enabled": False})
    disabled = await stack.client.post("/api/v1/agents", json=base)
    assert disabled.status_code == 400
    assert disabled.json()["error"]["code"] == "provider_disabled"


async def test_deleting_and_disabling_agents(stack: Stack, voice: Voice) -> None:
    await stack.ok("PATCH", f"/api/v1/agents/{voice.agent}", {"enabled": False})
    async with internal(stack) as c:
        assert (await c.get(f"/internal/agents/{voice.agent}")).status_code == 404
    start = await stack.client.post("/api/v1/sessions", json={"agent_id": voice.agent})
    assert start.status_code == 404
    await stack.ok("DELETE", f"/api/v1/agents/{voice.agent}", status=204)
    assert (await stack.client.get(f"/api/v1/agents/{voice.agent}")).status_code == 404
    assert await stack.ok("GET", "/api/v1/agents") == []
    # Its providers are free again.
    await stack.ok("DELETE", f"/api/v1/providers/{voice.llm}", status=204)


# ── Internal endpoints ───────────────────────────────────────────────────────────────


async def test_internal_endpoints_refuse_without_the_internal_token(
    stack: Stack, voice: Voice
) -> None:
    for token in (None, "wrong-token", "Bearer"):
        async with internal(stack, token) as c:
            agent = await c.get(f"/internal/agents/{voice.agent}")
            report = await c.post("/internal/sessions", json={})
        assert agent.status_code == 401, token
        assert agent.json()["error"]["code"] == "internal_only"
        assert report.status_code in (401, 422), token
    # A dashboard session is not an internal caller either.
    resp = await stack.client.get(f"/internal/agents/{voice.agent}")
    assert resp.status_code == 401
