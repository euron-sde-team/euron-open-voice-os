"""How a live conversation behaves: barge-in (AC2), turn taking (AC3), provider switching
(AC4), disclosure (AC6), no stored audio (AC7), provider failures (AC10), a dropped client
(AC11), isolation and the session cap (AC12), and the cost optimizer (AC15).

Every test holds a real session through the real runtime: speech files streamed in real
time over the WebSocket, VAD and turn detection running, the mock providers answering.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
import websockets

from tests.integration.conftest import Stack, Voice, make_voice, ticket, utterance
from voiceos.benchmarks.client import converse, silence

pytestmark = pytest.mark.asyncio


async def answered_turns(stack: Stack, session_id: str) -> list[dict[str, Any]]:
    row = await stack.session_row(session_id)
    return [t for t in row["turns"] if t["user_text"]]


async def test_barge_in_stops_the_agent_and_cancels_its_answer(stack: Stack, voice: Voice) -> None:
    """AC2: the caller speaks over a long answer; the agent's audio stops within a moment
    and the interrupted turn is recorded as such."""
    await stack.mock("/admin/script", {"transcripts": ["Tell me a long story.", "Stop please."]})
    t = await ticket(stack, voice.agent)
    result = await converse(
        t["websocket_url"], [utterance(), utterance("en-02-hours.wav")], gap_s=2.5
    )
    assert len(result.speech_started) == 2
    # The long answer was playing when the caller started speaking again ...
    second = result.speech_started[1]
    assert result.audio_between(second - 1.5, second) > 0.5
    # ... and stopped: after VAD caught the interruption, no more of that answer arrived
    # while the caller kept talking.
    assert result.audio_between(second + 1.2, result.speech_ended[1]) == 0
    types = [e.get("type") for e in result.events]
    assert "bot-interrupted" in types or "user-started-speaking" in types

    row = await stack.session_row(t["session_id"])
    assert row["interruptions"] >= 1
    story = next(x for x in row["turns"] if x["user_text"] == "Tell me a long story.")
    assert story["interrupted"] is True
    # The caller's next words were heard and answered as a new turn.
    assert any(x["user_text"] == "Stop please." for x in row["turns"])


async def test_a_pause_inside_a_sentence_does_not_end_the_turn(stack: Stack) -> None:
    """AC3: with a 0.8 s end-of-turn silence, a 0.35 s pause mid-sentence keeps the caller's
    turn open: one transcription, one answer."""
    v = await make_voice(stack, turn={"mode": "vad", "vad_stop_secs": 0.8})
    await stack.mock("/admin/script", {"transcripts": ["Book a table for two, tonight."]})
    words = utterance()
    half = len(words) // 2 & ~1
    paused = words[:half] + silence(0.35) + words[half:]
    t = await ticket(stack, v.agent)
    await converse(t["websocket_url"], [paused], gap_s=0.5)
    stats = await stack.mock("/stats")
    assert stats["stt"] == 1
    turns = await answered_turns(stack, t["session_id"])
    assert len(turns) == 1
    assert turns[0]["agent_text"]


async def test_providers_switch_by_configuration_only(stack: Stack, voice: Voice) -> None:
    """AC4: the same agent, its LLM swapped through the API, answers with the new model."""
    t = await ticket(stack, voice.agent)
    await stack.mock("/admin/script", {"transcripts": ["Book a table please."]})
    await converse(t["websocket_url"], [utterance()], gap_s=0.5)
    first = await answered_turns(stack, t["session_id"])
    assert first[0]["llm_model"] == "mock-llm"

    other = await stack.ok(
        "POST",
        "/api/v1/providers",
        {
            "name": "Second LLM",
            "stage": "llm",
            "adapter": "openai_compatible",
            "base_url": f"{stack.mock_url}/v1",
            "model": "mock-llm-large",
        },
    )
    agent = await stack.ok(
        "PATCH", f"/api/v1/agents/{voice.agent}", {"llm_provider_id": other["id"]}
    )
    assert agent["version"] == 2
    t2 = await ticket(stack, voice.agent)
    await stack.mock("/admin/script", {"transcripts": ["Book a table please."]})
    await converse(t2["websocket_url"], [utterance()], gap_s=0.5)
    second = await answered_turns(stack, t2["session_id"])
    assert second[0]["llm_model"] == "mock-llm-large"
    row = await stack.session_row(t2["session_id"])
    assert row["agent_version"] == 2
    # The new LLM is self-hosted (private URL), the old one was external.
    assert row["external_providers"] == []


async def test_external_processing_is_disclosed_before_and_recorded_after(
    stack: Stack, voice: Voice
) -> None:
    """AC6: the ticket carries the disclosure before connecting; the stored session names
    every provider that received the caller's audio or text."""
    t = await ticket(stack, voice.agent)
    assert t["disclosure"]["external"] is True
    assert t["disclosure"]["providers"] == ["Mock LLM"]
    assert "Mock LLM" in t["disclosure"]["message"]
    await converse(t["websocket_url"], [utterance()], gap_s=0.5)
    row = await stack.session_row(t["session_id"])
    assert row["external_providers"] == ["Mock LLM"]

    agent = await stack.ok("GET", f"/api/v1/agents/{voice.agent}")
    assert agent["external_providers"] == ["Mock LLM"]


async def test_no_audio_is_stored_by_default(stack: Stack, voice: Voice, tmp_path: Path) -> None:
    """AC7: a default session leaves no audio anywhere in object storage."""
    t = await ticket(stack, voice.agent)
    await converse(t["websocket_url"], [utterance()], gap_s=0.5)
    await stack.session_row(t["session_id"])
    objects = Path(stack.settings.local_storage_dir)

    def files() -> list[Path]:
        return [p for p in objects.rglob("*") if p.is_file()] if objects.exists() else []

    assert await asyncio.to_thread(files) == []


@pytest.mark.parametrize(
    ("fault", "spoken"),
    [
        # Persistent failures: a single 500 is retried by the provider client and succeeds,
        # which is the right behaviour but not the path under test.
        ({"llm": {"status": 500, "times": 20}}, "having trouble answering"),
        ({"stt": {"status": 500, "times": 20}}, "did not catch that"),
    ],
)
async def test_a_failing_provider_gets_a_spoken_fallback_not_a_hung_session(
    stack: Stack, voice: Voice, fault: dict[str, Any], spoken: str
) -> None:
    """AC10: a provider error is said out loud, reported as an event and recorded, and the
    session ends normally when the caller leaves."""
    await stack.mock("/admin/faults", fault)
    t = await ticket(stack, voice.agent)
    result = await asyncio.wait_for(
        converse(t["websocket_url"], [utterance()], gap_s=0.5, reply_timeout_s=20), timeout=60
    )
    assert result.agent_audio_seconds > 0.2
    spoken_text = " ".join(result.texts("bot-output") + result.texts("bot-tts-text"))
    assert spoken in spoken_text, (spoken_text, [e.get("type") for e in result.events])
    row = await stack.session_row(t["session_id"])
    assert row["errors"], "the provider failure was not recorded"
    assert row["end_reason"] in ("client_left", "agent_ended")


async def test_a_slow_llm_times_out_into_the_fallback(stack: Stack) -> None:
    """AC10: an LLM slower than its provider timeout is retried once, then the caller hears
    the fallback; the turn never hangs."""
    v = await make_voice(stack)
    await stack.ok("PATCH", f"/api/v1/providers/{v.llm}", {"timeout_s": 1})
    await stack.mock("/admin/faults", {"llm": {"delay_s": 8, "times": 10}})
    t = await ticket(stack, v.agent)
    result = await asyncio.wait_for(
        converse(t["websocket_url"], [utterance()], gap_s=0.5, reply_timeout_s=20), timeout=60
    )
    assert "having trouble answering" in " ".join(result.texts("bot-output"))
    row = await stack.session_row(t["session_id"])
    assert any("timed out" in e.lower() or "timeout" in e.lower() for e in row["errors"]), row[
        "errors"
    ]


async def test_a_dropped_client_ends_the_session_cleanly(stack: Stack, voice: Voice) -> None:
    """AC11: the caller vanishes mid-answer; the pipeline is cancelled, the slot freed and
    the session finalized."""
    await stack.mock("/admin/script", {"transcripts": ["Tell me a long story."]})
    t = await ticket(stack, voice.agent)
    async with websockets.connect(
        t["websocket_url"], additional_headers={"Origin": "http://localhost:4510"}
    ) as ws:
        from voiceos.benchmarks.client import _audio_message

        words = utterance()
        step = 640
        for i in range(0, len(words), step):
            await ws.send(_audio_message(words[i : i + step]))
            await asyncio.sleep(0.02)
        for _ in range(100):
            await ws.send(_audio_message(silence(0.02)))
            await asyncio.sleep(0.02)
        # Gone without a goodbye while the long answer plays.
        ws.transport.abort() if hasattr(ws, "transport") else None
    row = await stack.session_row(t["session_id"])
    assert row["end_reason"] == "client_left"
    async with httpx.AsyncClient() as c:
        ready = (await c.get(f"{stack.runtime_url}/readyz")).json()
    assert ready["sessions"] == 0


@pytest.mark.parametrize("runtime_overrides", [{"max_sessions": 1}])
async def test_sessions_past_the_cap_are_refused_with_a_reason(
    stack: Stack, voice: Voice, runtime_overrides: dict[str, Any]
) -> None:
    """AC12: one slot; a second caller gets 503 busy while the first is talking."""
    first = await ticket(stack, voice.agent)
    second = await ticket(stack, voice.agent)
    origin = {"Origin": "http://localhost:4510"}
    async with websockets.connect(first["websocket_url"], additional_headers=origin):
        await asyncio.sleep(1.0)
        with pytest.raises((websockets.InvalidStatus, websockets.ConnectionClosed)) as refused:
            async with websockets.connect(second["websocket_url"], additional_headers=origin) as c:
                await c.recv()
        err = refused.value
        status = (
            err.response.status_code
            if isinstance(err, websockets.InvalidStatus)
            else (err.rcvd.code if err.rcvd else 0)
        )
        assert status in (503, 4503)
        async with httpx.AsyncClient() as c:
            busy = await c.get(f"{stack.runtime_url}/readyz")
        assert busy.status_code == 503
        assert busy.json()["status"] == "busy"


async def test_concurrent_sessions_are_isolated(stack: Stack, voice: Voice) -> None:
    """AC12: two callers at once each get their own pipeline, answer and report."""
    a, b = await ticket(stack, voice.agent), await ticket(stack, voice.agent)
    ra, rb = await asyncio.gather(
        converse(a["websocket_url"], [utterance()], gap_s=0.5),
        converse(b["websocket_url"], [utterance("en-02-hours.wav")], gap_s=0.5),
    )
    assert ra.agent_audio_seconds > 0.2 and rb.agent_audio_seconds > 0.2
    row_a, row_b = (
        await stack.session_row(a["session_id"]),
        await stack.session_row(b["session_id"]),
    )
    assert row_a["id"] != row_b["id"]
    assert len([t for t in row_a["turns"] if t["user_text"]]) == 1
    assert len([t for t in row_b["turns"] if t["user_text"]]) == 1


async def test_repeated_phrases_and_questions_are_served_from_cache(stack: Stack) -> None:
    """AC15: the greeting is synthesized once and replayed; an exact repeat of a question
    is answered from the response cache with no LLM call; both show up as savings."""
    v = await make_voice(
        stack, greeting="Hello, thanks for calling.", cache={"response_cache": True}
    )
    await stack.ok(
        "PATCH",
        f"/api/v1/providers/{v.tts}",
        {"price": {"per_million_characters": 15.0}, "external": True},
    )
    sessions = []
    for _ in range(2):
        await stack.mock("/admin/script", {"transcripts": ["What time do you open?"]})
        t = await ticket(stack, v.agent)
        await converse(t["websocket_url"], [utterance("en-02-hours.wav")], gap_s=0.5)
        sessions.append(await stack.session_row(t["session_id"]))
    first, second = sessions
    assert first["usage"]["tts_characters_cached"] == 0
    assert second["usage"]["tts_characters_cached"] >= len("Hello, thanks for calling.")
    assert second["usage"]["response_cache_hits"] == 1
    cached = next(t for t in second["turns"] if t["user_text"])
    assert cached["response_cache_hit"] is True
    assert second["savings_usd"] > 0
    chats = (await stack.mock("/stats"))["chat"]
    assert len(chats) == 1, "the repeated question reached the LLM again"


async def test_short_turns_route_to_the_small_model(stack: Stack) -> None:
    """AC15: with a small model configured, a short question goes to it."""
    v = await make_voice(stack)
    small = await stack.ok(
        "POST",
        "/api/v1/providers",
        {
            "name": "Small LLM",
            "stage": "llm",
            "adapter": "openai_compatible",
            "base_url": f"{stack.mock_url}/v1",
            "model": "mock-llm-small",
        },
    )
    await stack.ok(
        "PATCH",
        f"/api/v1/agents/{v.agent}",
        {"llm_small_provider_id": small["id"], "small_model_max_words": 6},
    )
    await stack.mock("/admin/script", {"transcripts": ["Open on Sunday?"]})
    t = await ticket(stack, v.agent)
    await converse(t["websocket_url"], [utterance("en-02-hours.wav")], gap_s=0.5)
    [turn] = await answered_turns(stack, t["session_id"])
    assert turn["llm_model"] == "mock-llm-small"
    assert turn["llm_routed_small"] is True
    row = await stack.session_row(t["session_id"])
    assert row["usage"]["llm_turns_routed_small"] == 1
