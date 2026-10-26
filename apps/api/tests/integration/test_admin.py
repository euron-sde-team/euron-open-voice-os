"""Dashboard API: sign-in, roles, users, SDK keys and their scopes (AC13)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from tests.integration.conftest import CSRF, OWNER, Stack, Voice, login, make_voice
from tests.integration.support import ADMIN, VIEWER, add_user, as_user, scalar, sdk

pytestmark = pytest.mark.asyncio


# ── Sign-in ──────────────────────────────────────────────────────────────────────────


async def test_login_failures_and_lockout(stack: Stack) -> None:
    async with stack.anonymous() as c:
        bad = await c.post("/api/v1/auth/login", json={**OWNER, "password": "wrong"})
        assert bad.status_code == 401
        assert bad.json()["error"]["code"] == "invalid_credentials"
        for _ in range(5):
            await c.post("/api/v1/auth/login", json={**OWNER, "password": "wrong"})
        locked = await c.post("/api/v1/auth/login", json=OWNER)
        assert locked.status_code == 401
        assert locked.json()["error"]["code"] == "account_locked"
        assert (await c.get("/api/v1/auth/me")).status_code == 401


async def test_parallel_wrong_passwords_still_lock_the_account(stack: Stack) -> None:
    async with stack.anonymous() as c:
        await asyncio.gather(
            *(
                c.post("/api/v1/auth/login", json={**OWNER, "password": "nope-nope"})
                for _ in range(8)
            )
        )
        locked = await c.post("/api/v1/auth/login", json=OWNER)
    assert locked.json()["error"]["code"] == "account_locked"
    failures = await scalar(
        stack, "select count(*) from audit_log where action = 'auth.login_failed'"
    )
    assert failures == 8


async def test_cookie_session_requires_csrf_header(stack: Stack) -> None:
    async with stack.anonymous() as c:
        assert (await c.post("/api/v1/auth/login", json=OWNER)).status_code == 200
        assert (await c.get("/api/v1/auth/me")).status_code == 200
        resp = await c.post("/api/v1/keys", json={"name": "x"})
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "csrf_required"
        resp = await c.post("/api/v1/keys", json={"name": "x"}, headers=CSRF)
        assert resp.status_code == 201


async def test_logout_ends_the_session_server_side(stack: Stack) -> None:
    client = await login(stack.api_url)
    try:
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        assert (await client.post("/api/v1/auth/logout")).status_code == 200
        again = await client.get("/api/v1/auth/me")
        assert again.status_code == 401
        assert again.json()["error"]["code"] == "session_expired"
    finally:
        await client.aclose()
    # Other sessions of the same user keep working.
    assert (await stack.client.get("/api/v1/auth/me")).status_code == 200
    actions = {e["action"] for e in (await stack.ok("GET", "/api/v1/audit"))["items"]}
    assert "auth.logout" in actions


async def test_login_response_is_not_cached(stack: Stack) -> None:
    async with stack.anonymous() as c:
        resp = await c.post("/api/v1/auth/login", json=OWNER)
    assert resp.headers["cache-control"] == "no-store"


async def test_password_change_signs_other_sessions_out(stack: Stack) -> None:
    other = await login(stack.api_url)
    try:
        new = "Brand-New-Pass-456"
        resp = await stack.client.post(
            "/api/v1/auth/password",
            json={"current_password": OWNER["password"], "new_password": new},
        )
        assert resp.status_code == 200, resp.text
        assert (await other.get("/api/v1/auth/me")).status_code == 401
        # The response carries a fresh session for the person who changed it.
        fresh = httpx.AsyncClient(
            base_url=stack.api_url,
            headers={"authorization": f"Bearer {resp.json()['session_token']}"},
        )
        async with fresh:
            assert (await fresh.get("/api/v1/auth/me")).status_code == 200
        wrong = await stack.client.post(
            "/api/v1/auth/password",
            json={"current_password": "not-the-password", "new_password": "Another-Pass-789"},
        )
        assert wrong.status_code in (400, 401)
    finally:
        await other.aclose()


async def test_forwarded_for_cannot_dodge_the_login_throttle(stack: Stack) -> None:
    """The test client connects from 127.0.0.1, which uvicorn trusts as a proxy, so this is
    the production shape: the caller forges an X-Forwarded-For value and the trusted proxy
    appends the real address. Only the right-most untrusted hop counts.

    The throttle counts per one-minute window, so 41 attempts put at least 21 in one window
    even when the burst straddles a minute boundary."""
    async with stack.anonymous() as c:
        codes = []
        for i in range(41):
            r = await c.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.test", "password": "wrong-password"},
                headers={"x-forwarded-for": f"203.0.113.{i}, 198.51.100.7"},
            )
            codes.append(r.status_code)
    assert 429 in codes


# ── Roles ────────────────────────────────────────────────────────────────────────────


async def test_viewer_can_read_but_never_mutate(stack: Stack, voice: Voice) -> None:
    await add_user(stack, VIEWER, "viewer")
    key = await stack.ok("POST", "/api/v1/keys", {"name": "k"})
    async with as_user(stack, VIEWER) as viewer:
        for path in ("/api/v1/providers", "/api/v1/agents", "/api/v1/keys", "/api/v1/sessions"):
            assert (await viewer.get(path)).status_code == 200, path
        session_id = "00000000-0000-0000-0000-000000000001"
        for method, path, body in (
            (
                "POST",
                "/api/v1/providers",
                {"name": "x", "stage": "llm", "adapter": "mock", "base_url": "http://x/v1"},
            ),
            ("PATCH", f"/api/v1/providers/{voice.llm}", {"name": "y"}),
            ("DELETE", f"/api/v1/providers/{voice.stt}", None),
            ("POST", f"/api/v1/providers/{voice.llm}/test", None),
            ("POST", "/api/v1/agents/from-template", {"template": "receptionist"}),
            ("PATCH", f"/api/v1/agents/{voice.agent}", {"name": "y"}),
            ("DELETE", f"/api/v1/agents/{voice.agent}", None),
            ("POST", "/api/v1/keys", {"name": "x"}),
            ("PATCH", f"/api/v1/keys/{key['id']}", {"name": "y"}),
            ("POST", f"/api/v1/keys/{key['id']}/revoke", None),
            (
                "POST",
                "/api/v1/users",
                {"email": "a@example.test", "name": "A", "password": "Password-12345"},
            ),
            ("DELETE", f"/api/v1/sessions/{session_id}/transcript", None),
            ("POST", "/api/v1/benchmarks", {"agent_ids": [voice.agent]}),
            ("GET", "/api/v1/audit", None),
            ("GET", "/api/v1/users", None),
        ):
            resp = await viewer.request(method, path, json=body)
            assert resp.status_code == 403, (method, path, resp.text)
            assert resp.json()["error"]["code"] == "insufficient_role"


async def test_admins_cannot_manage_users(stack: Stack) -> None:
    await add_user(stack, ADMIN, "admin")
    async with as_user(stack, ADMIN) as admin:
        assert (await admin.get("/api/v1/users")).status_code == 200
        resp = await admin.post(
            "/api/v1/users",
            json={"email": "b@example.test", "name": "B", "password": "Password-12345"},
        )
        assert resp.status_code == 403
        assert (await admin.post("/api/v1/keys", json={"name": "ok"})).status_code == 201


async def test_owners_cannot_demote_or_disable_themselves(stack: Stack) -> None:
    me = await stack.ok("GET", "/api/v1/auth/me")
    for change in ({"role": "admin"}, {"disabled": True}):
        resp = await stack.client.patch(f"/api/v1/users/{me['id']}", json=change)
        assert resp.status_code == 403, resp.text
    assert (await stack.ok("GET", "/api/v1/auth/me"))["role"] == "owner"


async def test_two_owners_demoting_each_other_keep_an_owner(stack: Stack) -> None:
    other = {"email": "second-owner@example.test", "password": "Second-Owner-123"}
    created = await add_user(stack, other, "owner")
    me = await stack.ok("GET", "/api/v1/auth/me")
    async with as_user(stack, other) as second:
        results = await asyncio.gather(
            stack.client.patch(f"/api/v1/users/{created['id']}", json={"role": "viewer"}),
            second.patch(f"/api/v1/users/{me['id']}", json={"role": "viewer"}),
        )
    assert sorted(r.status_code for r in results)[0] == 200
    owners = await scalar(stack, "select count(*) from users where role = 'owner' and not disabled")
    assert owners == 1


async def test_racing_user_creates_conflict(stack: Stack) -> None:
    body = {
        "email": "race@example.test",
        "name": "Race",
        "role": "viewer",
        "password": "Race-Pass-12345",
    }
    results = await asyncio.gather(
        *(stack.client.post("/api/v1/users", json=body) for _ in range(4))
    )
    codes = sorted(r.status_code for r in results)
    assert codes[0] == 201 and set(codes[1:]) <= {409}
    assert all("argon2" not in r.text for r in results)


# ── SDK keys ─────────────────────────────────────────────────────────────────────────


async def test_sdk_key_lifecycle(stack: Stack, voice: Voice) -> None:
    created = await stack.ok("POST", "/api/v1/keys", {"name": "backend"}, status=201)
    key = created["key"]
    assert key.startswith("vos_")
    listed = await stack.ok("GET", "/api/v1/keys")
    assert all(k["display"].endswith("_****") and "key" not in k for k in listed)
    assert key not in str(listed)
    assert (await sdk(stack, key, voice.agent)).status_code == 201

    updated = await stack.ok(
        "PATCH", f"/api/v1/keys/{created['id']}", {"name": "renamed", "rpm_limit": 50}
    )
    assert updated["name"] == "renamed" and updated["rpm_limit"] == 50

    await stack.ok("POST", f"/api/v1/keys/{created['id']}/revoke")
    resp = await sdk(stack, key, voice.agent)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "revoked_api_key"
    assert (await stack.ok("GET", "/api/v1/keys?include_revoked=true"))[0]["revoked_at"]
    assert await scalar(stack, "select count(*) from audit_log where action like 'api_key.%'") == 3


async def test_malformed_and_unknown_keys_are_refused_cheaply(stack: Stack, voice: Voice) -> None:
    missing = await sdk(stack, None, voice.agent)
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "missing_api_key"
    for raw in ("sk-not-ours", "vos_zz_secret", "vos__x", "vos_000000000000_nope"):
        resp = await sdk(stack, raw, voice.agent)
        assert resp.status_code == 401, raw
        assert resp.json()["error"]["code"] == "invalid_api_key"


async def test_rate_limit_per_key(stack: Stack, voice: Voice) -> None:
    key = (await stack.ok("POST", "/api/v1/keys", {"name": "tiny", "rpm_limit": 3}))["key"]
    codes = [(await sdk(stack, key, voice.agent)).status_code for _ in range(5)]
    assert codes[:3] == [201, 201, 201] and codes[3:] == [429, 429]
    resp = await sdk(stack, key, voice.agent)
    assert int(resp.headers["retry-after"]) >= 1
    assert resp.json()["error"]["details"]["limit_rpm"] == 3


async def test_key_agent_scope(stack: Stack, voice: Voice) -> None:
    other = await stack.ok(
        "POST",
        "/api/v1/agents",
        {
            "name": "Other",
            "system_prompt": "x",
            "stt_provider_id": voice.stt,
            "llm_provider_id": voice.llm,
            "tts_provider_id": voice.tts,
        },
    )
    key = await stack.ok("POST", "/api/v1/keys", {"name": "s", "agent_ids": [voice.agent]})
    assert (await sdk(stack, key["key"], voice.agent)).status_code == 201
    denied = await sdk(stack, key["key"], other["id"])
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "agent_not_allowed"


async def test_key_origin_scope(stack: Stack, voice: Voice) -> None:
    site = "https://shop.example.com"
    key = (await stack.ok("POST", "/api/v1/keys", {"name": "embed", "allowed_origins": [site]}))[
        "key"
    ]
    for origin in (None, "https://evil.example"):
        resp = await sdk(stack, key, voice.agent, origin=origin)
        assert resp.status_code == 403, origin
        assert resp.json()["error"]["code"] == "origin_not_allowed"
    ok = await sdk(stack, key, voice.agent, origin=site)
    assert ok.status_code == 201
    assert ok.json()["websocket_url"].startswith("ws://")


async def test_a_key_cannot_scope_an_unknown_agent(stack: Stack) -> None:
    resp = await stack.client.post(
        "/api/v1/keys",
        json={"name": "bad", "agent_ids": ["00000000-0000-0000-0000-00000000beef"]},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unknown_agent"
    bad_origin = await stack.client.post(
        "/api/v1/keys", json={"name": "bad", "allowed_origins": ["https://x.example/path"]}
    )
    assert bad_origin.status_code == 422


async def test_deleting_an_agent_removes_it_from_key_scopes(stack: Stack) -> None:
    first = await make_voice(stack)
    second = await stack.ok(
        "POST",
        "/api/v1/agents",
        {
            "name": "Second",
            "system_prompt": "x",
            "stt_provider_id": first.stt,
            "llm_provider_id": first.llm,
            "tts_provider_id": first.tts,
        },
    )
    key = await stack.ok(
        "POST", "/api/v1/keys", {"name": "two", "agent_ids": [first.agent, second["id"]]}
    )
    await stack.ok("DELETE", f"/api/v1/agents/{second['id']}", status=204)
    [row] = await stack.ok("GET", "/api/v1/keys")
    assert row["id"] == key["id"] and row["agent_ids"] == [first.agent]
