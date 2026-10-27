"""The dashboard side of sessions: reports filed by the runtime, stored once, redacted and
retained per agent (AC7), listed, erased, purged, and rolled up into the overview (AC8, AC9).

Reports are filed through ``/internal/sessions`` exactly as the runtime sends them; the
voice path that produces them is covered in test_voice_sessions.py."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from tests.integration.conftest import Stack, Voice
from tests.integration.support import (
    VIEWER,
    add_user,
    as_user,
    file_report,
    report,
    scalar,
    turn,
)

pytestmark = pytest.mark.asyncio

PII = (
    "Mail me at a.b@example.com or call 98765 43210, card 4111 1111 1111 1111, "
    "aadhaar 2341 2341 2346, PAN ABCDE1234F, order 4111 1111 1111 1112"
)


async def test_a_duplicate_report_is_stored_once(stack: Stack, voice: Voice) -> None:
    body = report(voice.agent)
    assert await file_report(stack, body) == {"stored": True}
    assert await file_report(stack, body) == {"stored": False}
    count = await scalar(
        stack, "select count(*) from sessions where id = :id", id=body["session_id"]
    )
    assert count == 1
    hourly = await scalar(stack, "select sum(sessions) from usage_hourly")
    assert hourly == 1


async def test_list_pages_with_a_keyset_cursor_and_filters(stack: Stack, voice: Voice) -> None:
    other = await stack.ok(
        "POST",
        "/api/v1/agents",
        {
            "name": "Second",
            "system_prompt": "x",
            "stt_provider_id": voice.stt,
            "llm_provider_id": voice.llm,
            "tts_provider_id": voice.tts,
        },
    )
    base = datetime.now(UTC) - timedelta(hours=1)
    ids = []
    for i in range(5):
        body = report(
            voice.agent if i % 2 == 0 else other["id"],
            started=base + timedelta(minutes=i),
            errors=["LLM timed out"] if i == 3 else None,
        )
        ids.append(body["session_id"])
        await file_report(stack, body)

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        query = "/api/v1/sessions?limit=2" + (f"&cursor={cursor}" if cursor else "")
        page = await stack.ok("GET", query)
        seen += [s["id"] for s in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert pages == 3
    assert seen == list(reversed(ids)), "newest first, no repeats, nothing missed"

    mine = await stack.ok("GET", f"/api/v1/sessions?agent_id={voice.agent}")
    assert [s["id"] for s in mine["items"]] == [ids[4], ids[2], ids[0]]
    errored = await stack.ok("GET", "/api/v1/sessions?errors_only=true")
    assert [s["id"] for s in errored["items"]] == [ids[3]]
    assert errored["items"][0]["error_count"] == 1

    bad = await stack.client.get("/api/v1/sessions?cursor=bm90LWEtY3Vyc29y")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_cursor"


async def test_detail_shows_turns_cost_and_disclosure(stack: Stack, voice: Voice) -> None:
    body = report(voice.agent)
    await file_report(stack, body)
    d = await stack.ok("GET", f"/api/v1/sessions/{body['session_id']}")
    assert d["agent_name"] == "Test agent"
    assert d["duration_s"] == pytest.approx(30.0)
    assert d["external_providers"] == ["Mock LLM"]
    assert d["self_hosted_stages"] == ["stt", "tts"]
    [t] = d["turns"]
    assert t["response_ms"] == 900.0 and t["user_text"] == "Book a table for two"
    # 1000 input and 200 output tokens at 0.15 and 0.60 USD per million.
    assert d["cost_llm_usd"] == pytest.approx(0.00027)
    assert d["cost_total_usd"] == pytest.approx(0.00027)
    assert d["cost_status"] == "complete"
    assert d["transcript_stored"] is True and d["transcript_expires_at"] is not None
    missing = await stack.client.get(f"/api/v1/sessions/{uuid.uuid4()}")
    assert missing.status_code == 404


async def test_an_unpriced_external_stage_is_not_reported_never_zero(
    stack: Stack, voice: Voice
) -> None:
    await stack.ok("PATCH", f"/api/v1/providers/{voice.llm}", {"price": {}})
    body = report(voice.agent)
    await file_report(stack, body)
    d = await stack.ok("GET", f"/api/v1/sessions/{body['session_id']}")
    assert d["cost_llm_usd"] is None
    assert d["cost_status"] == "partial"
    no_usage = report(voice.agent, usage={"stt_audio_seconds": 2.0})
    await stack.ok(
        "PATCH",
        f"/api/v1/providers/{voice.llm}",
        {"price": {"per_million_input_tokens": 0.15, "per_million_output_tokens": 0.6}},
    )
    await file_report(stack, no_usage)
    d = await stack.ok("GET", f"/api/v1/sessions/{no_usage['session_id']}")
    assert d["cost_llm_usd"] is None, "usage the provider did not report is not costed as 0"


async def test_transcripts_are_redacted_before_storage(stack: Stack, voice: Voice) -> None:
    body = report(voice.agent, turns=[{**turn(0, 800.0), "user_text": PII, "agent_text": PII}])
    await file_report(stack, body)
    stored = await scalar(
        stack, "select user_text from session_turns where session_id = :id", id=body["session_id"]
    )
    assert stored == (
        "Mail me at [email] or call [phone], card [card], aadhaar [aadhaar], PAN [pan], "
        "order [number]"
    )
    raw = await scalar(
        stack,
        "select count(*) from session_turns where agent_text like '%98765%' "
        "or agent_text like '%a.b@example.com%' or agent_text like '%ABCDE1234F%'",
    )
    assert raw == 0


async def test_redaction_can_be_turned_off_per_agent(stack: Stack, voice: Voice) -> None:
    await stack.ok(
        "PATCH",
        f"/api/v1/agents/{voice.agent}",
        {"privacy": {"transcript_retention_days": 7, "redact_pii": False}},
    )
    body = report(voice.agent, turns=[{**turn(0, 800.0), "user_text": "call 98765 43210"}])
    await file_report(stack, body)
    d = await stack.ok("GET", f"/api/v1/sessions/{body['session_id']}")
    assert d["turns"][0]["user_text"] == "call 98765 43210"


async def test_retention_zero_stores_no_words(stack: Stack, voice: Voice) -> None:
    await stack.ok(
        "PATCH",
        f"/api/v1/agents/{voice.agent}",
        {"privacy": {"transcript_retention_days": 0}},
    )
    body = report(voice.agent)
    await file_report(stack, body)
    d = await stack.ok("GET", f"/api/v1/sessions/{body['session_id']}")
    assert d["transcript_stored"] is False and d["transcript_expires_at"] is None
    [t] = d["turns"]
    assert t["user_text"] is None and t["agent_text"] is None
    assert t["response_ms"] == 900.0, "timings stay for analytics"
    words = await scalar(
        stack,
        "select count(*) from session_turns where user_text is not null or agent_text is not null",
    )
    assert words == 0


async def test_erasing_a_transcript_keeps_timings_and_is_audited(
    stack: Stack, voice: Voice
) -> None:
    body = report(voice.agent)
    await file_report(stack, body)
    sid = body["session_id"]
    await add_user(stack, VIEWER, "viewer")
    async with as_user(stack, VIEWER) as viewer:
        assert (await viewer.delete(f"/api/v1/sessions/{sid}/transcript")).status_code == 403
    resp = await stack.client.delete(f"/api/v1/sessions/{sid}/transcript")
    assert resp.status_code == 204
    d = await stack.ok("GET", f"/api/v1/sessions/{sid}")
    assert d["transcript_stored"] is False
    [t] = d["turns"]
    assert t["user_text"] is None and t["agent_text"] is None and t["response_ms"] == 900.0
    assert d["cost_llm_usd"] == pytest.approx(0.00027)
    audit = await stack.ok("GET", "/api/v1/audit?action=session.transcript_erased")
    assert [e["target_id"] for e in audit["items"]] == [sid]
    missing = await stack.client.delete(f"/api/v1/sessions/{uuid.uuid4()}/transcript")
    assert missing.status_code == 404


async def test_the_worker_purges_expired_transcripts(stack: Stack, voice: Voice) -> None:
    from voiceos.core.container import Container
    from voiceos.worker import tick

    await stack.ok(
        "PATCH", f"/api/v1/agents/{voice.agent}", {"privacy": {"transcript_retention_days": 1}}
    )
    old = report(voice.agent, started=datetime.now(UTC) - timedelta(days=3))
    fresh = report(voice.agent)
    await file_report(stack, old)
    await file_report(stack, fresh)

    container = Container.build(stack.settings)
    try:
        assert await tick(container) is True
        assert await tick(container) is False, "nothing left to purge"
    finally:
        await container.close()
    gone = await stack.ok("GET", f"/api/v1/sessions/{old['session_id']}")
    assert gone["transcript_stored"] is False
    assert gone["turns"][0]["user_text"] is None and gone["turns"][0]["response_ms"] == 900.0
    kept = await stack.ok("GET", f"/api/v1/sessions/{fresh['session_id']}")
    assert kept["transcript_stored"] is True
    assert kept["turns"][0]["user_text"] == "Book a table for two"


async def test_a_report_for_a_deleted_agent_is_still_stored(stack: Stack, voice: Voice) -> None:
    body = report(str(uuid.uuid4()))
    assert await file_report(stack, body) == {"stored": True}
    d = await stack.ok("GET", f"/api/v1/sessions/{body['session_id']}")
    assert d["agent_id"] is None and d["agent_name"] == "Deleted agent"
    assert d["cost_status"] == "not_reported"
    assert d["turns"][0]["user_text"] is None, "no agent, no retention: words are not kept"


async def test_overview_matches_the_reports_filed(stack: Stack, voice: Voice) -> None:
    other = await stack.ok(
        "POST",
        "/api/v1/agents",
        {
            "name": "Second",
            "system_prompt": "x",
            "stt_provider_id": voice.stt,
            "llm_provider_id": voice.llm,
            "tts_provider_id": voice.tts,
        },
    )
    filed = [
        report(voice.agent, seconds=30, turns=[turn(0, 900.0)]),
        report(voice.agent, seconds=60, turns=[turn(0, 500.0), turn(1, 1500.0)]),
        report(
            other["id"],
            seconds=90,
            turns=[{**turn(0, 2000.0), "interrupted": True}],
            errors=["TTS timed out"],
        ),
    ]
    for body in filed:
        await file_report(stack, body)
    o = await stack.ok("GET", "/api/v1/analytics/overview?days=7")
    assert o["sessions"] == 3
    assert o["minutes"] == 3.0
    assert o["turns"] == 4
    assert o["interruption_rate"] == 0.25
    assert o["error_sessions"] == 1
    assert o["external_sessions"] == 3
    # percentile_cont over the four turns 500, 900, 1500, 2000.
    assert o["response_ms_p50"] == 1200.0
    assert o["response_ms_p95"] == 1925.0
    assert o["response_ms_avg"] == 1225.0
    assert o["stages"]["llm_first_token_ms"] == 100.0
    assert o["cost_usd"] == pytest.approx(0.00081)
    assert o["costed_sessions"] == 3
    assert o["cost_per_session_usd"] == pytest.approx(0.00027)
    assert o["llm_tokens"] == 3600
    by_agent = {b["agent_name"]: b for b in o["by_agent"]}
    assert by_agent["Test agent"]["sessions"] == 2
    assert by_agent["Test agent"]["minutes"] == 1.5
    assert by_agent["Second"]["sessions"] == 1
    assert sum(p["sessions"] for p in o["series"]) == 3
    assert o["previous"]["sessions"] == 0
    bad = await stack.client.get("/api/v1/analytics/overview?days=0")
    assert bad.status_code == 422
