"""System endpoints, the audit trail, request hardening and races."""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import Stack, Voice
from tests.integration.support import db, file_report, report, scalar

pytestmark = pytest.mark.asyncio


async def test_health_readiness_and_system_info(stack: Stack, voice: Voice) -> None:
    async with stack.anonymous() as c:
        assert (await c.get("/healthz")).json() == {"status": "ok"}
        assert (await c.get("/health")).json()["status"] == "ok"
        ready = await c.get("/readyz")
        assert ready.status_code == 200 and ready.json()["checks"]["postgres"]["ok"] is True
        assert (await c.get("/api/v1/system")).status_code == 401
    info = await stack.ok("GET", "/api/v1/system")
    assert info["runtime"]["ok"] is True
    assert info["runtime"]["status"] == "ready" and info["runtime"]["capacity"] == 4
    assert info["runtime_url"] == stack.runtime_url
    assert info["providers"] == {"stt": 1, "llm": 1, "tts": 1}
    assert info["external_providers"] == 1
    assert info["agents"] == 1 and info["active_keys"] == 0
    assert info["checks"]["postgres"]["ok"] is True


async def test_system_info_reports_an_unreachable_runtime(
    stack: Stack, voice: Voice, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The settings object is shared with the server thread; point it at a closed port.
    monkeypatch.setattr(stack.settings, "runtime_internal_url", "http://127.0.0.1:9")
    info = await stack.ok("GET", "/api/v1/system")
    assert info["runtime"]["ok"] is False and info["runtime"]["error"]


async def test_metrics_expose_voiceos_counters(stack: Stack, voice: Voice) -> None:
    await stack.ok("POST", "/api/v1/sessions", {"agent_id": voice.agent}, status=201)
    await file_report(stack, report(voice.agent))
    async with stack.anonymous() as c:
        body = (await c.get("/metrics")).text
    assert 'voiceos_sessions_started_total{source="dashboard"}' in body
    assert 'voiceos_sessions_reported_total{end_reason="client_left",transport="websocket"}' in body


async def test_responses_carry_request_ids_and_security_headers(stack: Stack) -> None:
    resp = await stack.client.get("/api/v1/auth/me", headers={"x-request-id": "trace-abc"})
    assert resp.headers["x-request-id"] == "trace-abc"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    other = await stack.client.get("/api/v1/auth/me")
    assert other.headers["x-request-id"] and other.headers["x-request-id"] != "trace-abc"


async def test_errors_use_one_envelope_and_never_leak_internals(stack: Stack) -> None:
    for resp in (
        await stack.client.get(f"/api/v1/agents/{uuid.uuid4()}"),
        await stack.client.get("/api/v1/agents/not-a-uuid"),
        await stack.client.post(
            "/api/v1/keys", content=b"{not json", headers={"content-type": "application/json"}
        ),
        await stack.client.post("/api/v1/sessions", json={"agent_id": str(uuid.uuid4())}),
    ):
        err = resp.json()["error"]
        assert set(err) >= {"code", "message", "type"}, resp.text
        assert "Traceback" not in resp.text and "sqlalchemy" not in resp.text.lower()
        assert resp.status_code in (404, 422), resp.text


async def _status_for_upload(stack: Stack, head: bytes, body: bytes) -> int:
    """The status line the API answers with while the client is still uploading. Over real
    TCP the server refuses early and closes, so read the answer at the socket level."""
    host, port = stack.api_url.removeprefix("http://").split(":")
    reader, writer = await asyncio.open_connection(host, int(port))
    try:
        writer.write(head + body)
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=10)
    finally:
        writer.close()
    return int(line.split()[1])


async def test_oversized_bodies_are_refused(stack: Stack) -> None:
    token = stack.client.headers["authorization"]
    common = (
        b"POST /api/v1/keys HTTP/1.1\r\nhost: test\r\ncontent-type: application/json\r\n"
        + f"authorization: {token}\r\nx-voiceos-csrf: 1\r\n".encode()
    )
    declared = common + b"content-length: 5000000\r\n\r\n"
    assert await _status_for_upload(stack, declared, b'{"name": "' + b"x" * 1000) == 413
    # No content-length (chunked): counted as it streams in.
    chunked = common + b"transfer-encoding: chunked\r\n\r\n"
    chunk = b"x" * 100_000
    body = b"".join(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n" for _ in range(30))
    assert await _status_for_upload(stack, chunked, body) == 413


async def test_the_audit_log_is_append_only(stack: Stack) -> None:
    await stack.ok("POST", "/api/v1/keys", {"name": "audited"}, status=201)
    assert await scalar(stack, "select count(*) from audit_log") >= 1
    for sql in ("update audit_log set action = 'forged'", "delete from audit_log"):
        with pytest.raises(DBAPIError, match="append-only"):
            async with db(stack) as conn:
                await conn.execute(text(sql))
    entries = (await stack.ok("GET", "/api/v1/audit"))["items"]
    assert "forged" not in {e["action"] for e in entries}
    keyed = await stack.ok("GET", "/api/v1/audit?action=api_key.created")
    assert [e["action"] for e in keyed["items"]] == ["api_key.created"]


async def test_audit_pages_with_a_cursor(stack: Stack) -> None:
    for i in range(5):
        await stack.ok("POST", "/api/v1/keys", {"name": f"k{i}"}, status=201)
    first = await stack.ok("GET", "/api/v1/audit?limit=3")
    assert len(first["items"]) == 3 and first["next_cursor"]
    rest = await stack.ok("GET", f"/api/v1/audit?limit=3&cursor={first['next_cursor']}")
    ids = [e["id"] for e in first["items"] + rest["items"]]
    assert len(ids) == len(set(ids)) >= 5


async def test_parallel_benchmark_requests_queue_one(stack: Stack, voice: Voice) -> None:
    results = await asyncio.gather(
        *(
            stack.client.post("/api/v1/benchmarks", json={"agent_ids": [voice.agent]})
            for _ in range(4)
        )
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [202, 409, 409, 409]
    assert {r.json()["error"]["code"] for r in results if r.status_code == 409} == {
        "benchmark_running"
    }
    runs = await stack.ok("GET", "/api/v1/benchmarks")
    assert len(runs) == 1 and runs[0]["status"] == "queued"
    assert runs[0]["config"] == {"agent_ids": [voice.agent], "sessions": 5}
    one = await stack.ok("GET", f"/api/v1/benchmarks/{runs[0]['id']}")
    assert one["id"] == runs[0]["id"]
    assert (await stack.client.get(f"/api/v1/benchmarks/{uuid.uuid4()}")).status_code == 404
    unknown = await stack.client.post("/api/v1/benchmarks", json={"agent_ids": [str(uuid.uuid4())]})
    assert unknown.status_code == 400 and unknown.json()["error"]["code"] == "unknown_agent"


async def test_parallel_duplicate_reports_store_one_session(stack: Stack, voice: Voice) -> None:
    body = report(voice.agent)
    async with httpx.AsyncClient(
        base_url=stack.api_url,
        headers={"authorization": f"Bearer {stack.settings.internal_api_token}"},
    ) as c:
        results = await asyncio.gather(*(c.post("/internal/sessions", json=body) for _ in range(5)))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert sum(r.json()["stored"] for r in results) == 1
    assert await scalar(stack, "select count(*) from sessions") == 1
    assert await scalar(stack, "select sum(sessions) from usage_hourly") == 1


async def test_a_signed_out_session_stays_refused(stack: Stack) -> None:
    from tests.integration.conftest import login

    client = await login(stack.api_url)
    try:
        await client.post("/api/v1/auth/logout")
        # Revocation lives in Postgres, not a cache that could evict it.
        assert await scalar(stack, "select count(*) from revoked_sessions") == 1
        assert (await client.get("/api/v1/auth/me")).status_code == 401
    finally:
        await client.aclose()
