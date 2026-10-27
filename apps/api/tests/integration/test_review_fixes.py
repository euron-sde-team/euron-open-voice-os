"""Regression tests for the issues an independent review found: each one reproduces the
failure scenario the review described and proves it can no longer happen."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.integration.conftest import (
    Served,
    Stack,
    Voice,
    make_voice,
    runtime_settings,
    ticket,
    utterance,
)
from tests.integration.support import file_report, report, sdk
from tests.integration.test_voice_sessions import refused
from voiceos.benchmarks.client import converse

pytestmark = pytest.mark.asyncio


async def test_a_ticket_is_single_use_across_runtime_replicas(stack: Stack, voice: Voice) -> None:
    """Two runtime replicas behind one load balancer: the ticket works once, not once each."""
    from voiceos.runtime.app import create_app as create_runtime

    other = Served(create_runtime(runtime_settings(stack.api_url))).start()
    try:
        t = await ticket(stack, voice.agent)
        await converse(t["websocket_url"], [], gap_s=0.2, greeting_timeout_s=0.5, tail_s=0.2)
        replay = t["websocket_url"].replace(
            stack.runtime_url.removeprefix("http://"), other.url.removeprefix("http://")
        )
        assert replay != t["websocket_url"]
        assert await refused(replay) in (409, 4409)
    finally:
        other.stop()


async def test_deleting_the_only_agent_of_a_key_revokes_it(stack: Stack, voice: Voice) -> None:
    """An empty scope means every agent, so deleting must never widen a key."""
    other = await second_agent(stack, voice)
    key = await stack.ok("POST", "/api/v1/keys", {"name": "embed", "agent_ids": [voice.agent]})
    await stack.ok("DELETE", f"/api/v1/agents/{voice.agent}", status=204)
    keys = await stack.ok("GET", "/api/v1/keys?include_revoked=true")
    row = next(k for k in keys if k["id"] == key["id"])
    assert row["revoked_at"] is not None
    assert (await sdk(stack, key["key"], other)).status_code == 401
    audit = await stack.ok("GET", "/api/v1/audit?action=api_key.revoked")
    assert audit["items"], "the revocation was not audited"


async def test_a_key_keeps_its_other_agents_when_one_is_deleted(stack: Stack, voice: Voice) -> None:
    other = await second_agent(stack, voice)
    key = await stack.ok("POST", "/api/v1/keys", {"name": "two", "agent_ids": [voice.agent, other]})
    await stack.ok("DELETE", f"/api/v1/agents/{voice.agent}", status=204)
    keys = await stack.ok("GET", "/api/v1/keys")
    row = next(k for k in keys if k["id"] == key["id"])
    assert row["agent_ids"] == [other] and row["revoked_at"] is None


async def test_a_key_rate_limit_can_be_cleared_back_to_the_default(stack: Stack) -> None:
    key = await stack.ok("POST", "/api/v1/keys", {"name": "limited", "rpm_limit": 30})
    updated = await stack.ok("PATCH", f"/api/v1/keys/{key['id']}", {"rpm_limit": None})
    assert updated["rpm_limit"] is None


async def test_a_disabled_provider_receives_no_calls(stack: Stack, voice: Voice) -> None:
    await stack.ok("PATCH", f"/api/v1/providers/{voice.llm}", {"enabled": False})
    resp = await stack.client.post("/api/v1/sessions", json={"agent_id": voice.agent})
    assert resp.status_code == 404, resp.text


async def test_a_report_is_costed_with_the_configuration_the_call_ran_with(
    stack: Stack, voice: Voice
) -> None:
    """The agent is disabled before the report lands; the snapshot in the report still
    names it, prices it and keeps the transcript per its retention."""
    agent = await stack.ok("GET", f"/api/v1/agents/{voice.agent}")
    async with httpx_internal(stack) as c:
        resolved = (await c.get(f"/internal/agents/{voice.agent}")).json()
    for stage in ("stt", "llm", "tts"):
        resolved[stage].pop("api_key", None)
    await stack.ok("PATCH", f"/api/v1/agents/{voice.agent}", {"enabled": False})
    body = report(voice.agent)
    body["agent"] = resolved
    await file_report(stack, body)
    row = await stack.session_row(body["session_id"])
    assert row["agent_name"] == agent["name"]
    assert row["cost_llm_usd"] is not None and row["cost_llm_usd"] > 0
    assert row["transcript_stored"] is True


async def test_webhook_urls_cannot_target_instance_metadata(stack: Stack, voice: Voice) -> None:
    for url in ("http://169.254.169.254/latest", "http://2852039166/", "http://0xa9fea9fe/"):
        resp = await stack.client.patch(
            f"/api/v1/agents/{voice.agent}", json={"tools": [{"name": "http_webhook", "url": url}]}
        )
        assert resp.status_code == 422, (url, resp.text)
    resp = await stack.client.patch(
        f"/api/v1/agents/{voice.agent}", json={"tools": [{"name": "http_webhook"}]}
    )
    assert resp.status_code in (400, 422), resp.text


async def test_a_runtime_shutdown_still_reports_what_was_measured(stack: Stack) -> None:
    """The replica stops mid-call (a deploy); the call's turns and usage are not lost."""
    from voiceos.runtime.app import create_app as create_runtime

    v = await make_voice(stack)
    replica = Served(create_runtime(runtime_settings(stack.api_url))).start()
    t = await ticket(stack, v.agent)
    url = t["websocket_url"].replace(
        stack.runtime_url.removeprefix("http://"), replica.url.removeprefix("http://")
    )
    await stack.mock("/admin/script", {"transcripts": ["Book a table please."]})
    call = asyncio.create_task(converse(url, [utterance()], gap_s=0.5, tail_s=60))
    for _ in range(200):  # wait until the answer has been generated
        if (await stack.mock("/stats"))["chat"]:
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(1.5)
    await asyncio.to_thread(replica.stop)
    # The server went away; the client may see a clean close or an error.
    await asyncio.gather(asyncio.wait_for(call, timeout=60), return_exceptions=True)
    row = await stack.session_row(t["session_id"])
    said = [x for x in row["turns"] if x["user_text"]]
    assert said and said[0]["user_text"] == "Book a table please."
    assert row["usage"]["llm_input_tokens"] > 0


async def second_agent(stack: Stack, voice: Voice) -> str:
    """Another agent on the same providers."""
    body = {
        "name": "Other agent",
        "system_prompt": "Another test agent.",
        "stt_provider_id": voice.stt,
        "llm_provider_id": voice.llm,
        "tts_provider_id": voice.tts,
    }
    created: dict[str, Any] = await stack.ok("POST", "/api/v1/agents", body)
    return str(created["id"])


def httpx_internal(stack: Stack) -> Any:
    from tests.integration.support import internal

    return internal(stack)
