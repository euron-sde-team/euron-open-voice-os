"""The worker runs real benchmarks and purges, and the agent's tools work in a live call."""

from __future__ import annotations

import pytest

from tests.integration.conftest import Stack, Voice, make_voice, ticket, utterance
from voiceos.benchmarks.client import converse
from voiceos.core.container import Container
from voiceos.worker import tick

pytestmark = pytest.mark.asyncio


async def test_the_worker_runs_a_queued_benchmark_through_the_runtime(
    stack: Stack, voice: Voice
) -> None:
    queued = await stack.ok(
        "POST", "/api/v1/benchmarks", {"agent_ids": [voice.agent], "sessions": 2}, status=202
    )
    assert queued["status"] == "queued"
    container = Container.build(stack.settings)
    try:
        assert await tick(container) is True  # it ran the benchmark
        assert await tick(container) is False  # nothing left to do
    finally:
        await container.close()
    run = await stack.ok("GET", f"/api/v1/benchmarks/{queued['id']}")
    assert run["status"] == "succeeded", run
    [result] = run["results"]["agents"].values()
    assert result["sessions"] == 2
    assert result["turns"] >= 2
    assert result["response_ms_p50"] is not None
    assert result["client_first_audio_ms_p50"] is not None
    assert set(result["stages_ms_avg"]) >= {"endpoint_ms", "llm_first_token_ms"}
    assert run["hardware"]["cpus"]


async def test_tools_answer_the_time_look_up_the_faq_and_end_the_call(stack: Stack) -> None:
    v = await make_voice(
        stack,
        tools=[{"name": "get_current_time"}, {"name": "faq_lookup"}, {"name": "end_conversation"}],
        faq=["Refunds are issued within five working days.", "Parking is free after six."],
    )
    await stack.mock(
        "/admin/script",
        {"transcripts": ["What time is it?", "What is your refund policy?", "Goodbye."]},
    )
    t = await ticket(stack, v.agent)
    await converse(
        t["websocket_url"],
        [
            utterance("en-02-hours.wav"),
            utterance("en-03-order.wav"),
            utterance("en-01-booking.wav"),
        ],
        gap_s=6.0,
    )
    row = await stack.session_row(t["session_id"])
    answers = {x["user_text"]: x["agent_text"] or "" for x in row["turns"] if x["user_text"]}
    assert answers["What time is it?"].startswith("It is ") and "UTC" in answers["What time is it?"]
    assert "five working days" in answers["What is your refund policy?"]
    assert row["end_reason"] == "agent_ended"
