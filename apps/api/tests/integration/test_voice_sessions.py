"""Voice sessions end to end through the real runtime: speech in, answer out, report filed
with real timings, usage and cost (AC8, AC9), and access to the runtime (AC13)."""

from __future__ import annotations

import pytest
import websockets

from tests.integration.conftest import Stack, Voice, ticket, utterance
from voiceos.benchmarks.client import converse
from voiceos.core.tokens import issue

pytestmark = pytest.mark.asyncio


async def test_a_spoken_question_gets_a_spoken_answer_and_a_full_report(
    stack: Stack, voice: Voice
) -> None:
    await stack.mock("/admin/script", {"transcripts": ["I would like to book a table."]})
    t = await ticket(stack, voice.agent)
    result = await converse(t["websocket_url"], [utterance()], gap_s=0.5)

    assert result.agent_audio_seconds > 0.2, "the agent's answer was not heard"
    assert result.first_audio_after_speech is not None
    assert "I would like to book a table." in result.texts("user-transcription")

    row = await stack.session_row(t["session_id"])
    assert row["transport"] == "websocket"
    assert row["subject"].startswith("user:")
    [turn] = [x for x in row["turns"] if x["user_text"]]
    assert turn["user_text"] == "I would like to book a table."
    assert turn["agent_text"].startswith("Sure. I have booked that")
    # Every stage was measured, and the response covers the stages that ran in sequence.
    for stage in ("endpoint_ms", "stt_ms", "llm_first_token_ms", "tts_first_audio_ms"):
        assert turn[stage] is not None and turn[stage] >= 0, stage
    assert turn["response_ms"] >= turn["llm_first_token_ms"] + turn["tts_first_audio_ms"]
    assert turn["llm_model"] == "mock-llm"
    # Usage reported by the providers, costed where a price exists: the LLM is external and
    # priced, STT and TTS run on our own servers and cost nothing per call.
    assert row["usage"]["llm_input_tokens"] > 0
    assert row["usage"]["llm_output_tokens"] > 0
    assert row["usage"]["tts_characters"] >= len(turn["agent_text"])
    assert row["cost_llm_usd"] > 0
    assert row["cost_stt_usd"] == 0 and row["cost_tts_usd"] == 0
    assert row["self_hosted_stages"] == ["stt", "tts"]
    assert row["cost_status"] == "complete"
    assert row["cost_total_usd"] == pytest.approx(row["cost_llm_usd"])
    assert row["external_providers"] == ["Mock LLM"]


async def refused(url: str, origin: str = "http://localhost:4510") -> int:
    """How the runtime turned a connection away: the HTTP status of a rejected handshake,
    or the close code if it accepted and closed at once. Fails if it let the client in."""
    try:
        async with websockets.connect(url, additional_headers={"Origin": origin}) as conn:
            await conn.recv()
    except websockets.InvalidStatus as exc:
        return int(exc.response.status_code)
    except websockets.ConnectionClosed as exc:
        return int(exc.rcvd.code) if exc.rcvd is not None else 0
    raise AssertionError(f"the runtime accepted {url}")


async def test_the_runtime_refuses_connections_without_a_valid_token(
    stack: Stack, voice: Voice
) -> None:
    ws = stack.runtime_url.replace("http://", "ws://")
    assert await refused(f"{ws}/ws") in (401, 403, 4401, 4403)
    assert await refused(f"{ws}/ws?token=not-a-token") in (401, 403, 4401, 4403)
    forged, _ = issue(voice.agent, "another-secret-that-is-long-enough-32b", subject="x")
    assert await refused(f"{ws}/ws?token={forged}") in (401, 403, 4401, 4403)

    # A valid token works once: replaying it is refused.
    t = await ticket(stack, voice.agent)
    await converse(t["websocket_url"], [], gap_s=0.2, greeting_timeout_s=0.5, tail_s=0.2)
    assert await refused(t["websocket_url"]) in (401, 403, 409, 4401, 4403, 4409)


async def test_a_browser_from_another_site_is_refused(stack: Stack, voice: Voice) -> None:
    t = await ticket(stack, voice.agent)
    assert await refused(t["websocket_url"], origin="https://evil.example") in (403, 4403)
