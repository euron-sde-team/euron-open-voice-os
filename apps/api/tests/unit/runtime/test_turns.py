"""The turn recorder: words, answers and latencies land on the right turn whatever order
Pipecat's turn strategies emit their frames in."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

pytest.importorskip("pipecat")

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    Frame,
    LLMTextFrame,
    MetricsFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMTokenUsage, LLMUsageMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import FramePushed

from voiceos.runtime.turns import TurnRecorder


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def rec() -> tuple[TurnRecorder, Clock]:
    r = TurnRecorder()
    clock = Clock()
    r._now = clock  # type: ignore[method-assign]
    return r, clock


async def push(r: TurnRecorder, clock: Clock, at: float, frame: Frame) -> None:
    clock.t = 100.0 + at
    await r.on_push_frame(cast(FramePushed, SimpleNamespace(frame=frame)))


def transcript(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text, "caller", "2026-10-26T10:00:00Z")


def audio() -> TTSAudioRawFrame:
    return TTSAudioRawFrame(audio=b"\0\0" * 240, sample_rate=24_000, num_channels=1)


async def answer(r: TurnRecorder, c: Clock, at: float, text: str = "Sure.") -> None:
    await push(r, c, at, LLMTextFrame(text))
    await push(r, c, at + 0.2, audio())
    await push(r, c, at + 0.25, BotStartedSpeakingFrame())


async def test_measures_each_stage_from_the_end_of_speech(rec: Any) -> None:
    r, c = rec
    await push(r, c, 0.0, VADUserStartedSpeakingFrame())
    await push(r, c, 0.05, UserStartedSpeakingFrame())
    await push(r, c, 2.0, VADUserStoppedSpeakingFrame())
    await push(r, c, 2.4, transcript("Book a table"))
    await push(r, c, 2.5, UserStoppedSpeakingFrame())
    await answer(r, c, 2.8)
    [t] = r.turns()
    assert t.user_text == "Book a table"
    assert t.agent_text == "Sure."
    assert t.endpoint_ms == pytest.approx(500)
    assert t.stt_ms == pytest.approx(400)
    assert t.llm_first_token_ms == pytest.approx(300)
    assert t.tts_first_audio_ms == pytest.approx(200)
    assert t.response_ms == pytest.approx(1050)


async def test_late_turn_start_does_not_split_the_turn(rec: Any) -> None:
    """The transcript and VAD stop arrive before the turn-start frame (transcription start
    strategy): the words, the answer and the timing still belong to one turn."""
    r, c = rec
    r.start_greeting("Hello, how can I help?")
    await push(r, c, 0.0, BotStartedSpeakingFrame())
    await push(r, c, 2.0, BotStoppedSpeakingFrame())
    await push(r, c, 3.0, VADUserStoppedSpeakingFrame())
    await push(r, c, 3.5, transcript("Where is my order?"))
    await push(r, c, 3.6, UserStartedSpeakingFrame())
    await push(r, c, 3.7, UserStoppedSpeakingFrame())
    await answer(r, c, 4.0)
    greeting, turn = r.turns()
    assert greeting.user_text is None
    assert greeting.agent_text == "Hello, how can I help?"
    assert turn.user_text == "Where is my order?"
    assert turn.agent_text == "Sure."
    assert turn.response_ms == pytest.approx(1250)


async def test_speaking_over_the_agent_interrupts_and_opens_a_turn(rec: Any) -> None:
    r, c = rec
    await push(r, c, 0.0, VADUserStartedSpeakingFrame())
    await push(r, c, 1.0, VADUserStoppedSpeakingFrame())
    await push(r, c, 1.1, transcript("Tell me a story"))
    await push(r, c, 1.2, UserStoppedSpeakingFrame())
    await answer(r, c, 1.5, "Once upon a time")
    await push(r, c, 3.0, VADUserStartedSpeakingFrame())
    await push(r, c, 4.0, VADUserStoppedSpeakingFrame())
    await push(r, c, 4.2, transcript("Stop"))
    first, second = r.turns()
    assert first.interrupted is True
    assert second.user_text == "Stop"
    assert second.response_ms is None


async def test_a_turn_with_no_words_and_no_answer_is_dropped(rec: Any) -> None:
    r, c = rec
    await push(r, c, 0.0, VADUserStartedSpeakingFrame())
    await push(r, c, 0.3, VADUserStoppedSpeakingFrame())
    assert r.turns() == []


async def test_usage_and_errors_are_collected(rec: Any) -> None:
    r, c = rec
    await push(r, c, 0.0, transcript("Hi"))
    await push(
        r,
        c,
        0.1,
        MetricsFrame(
            data=[
                LLMUsageMetricsData(
                    processor="llm",
                    model="mock-llm",
                    value=LLMTokenUsage(prompt_tokens=40, completion_tokens=8, total_tokens=48),
                ),
                TTSUsageMetricsData(processor="tts", value=12),
            ]
        ),
    )
    await push(r, c, 0.2, ErrorFrame("LLM timed out"))
    [t] = r.turns()
    assert (r.usage.llm_input_tokens, r.usage.llm_output_tokens) == (40, 8)
    assert r.usage.llm_usage_reported is True
    assert r.usage.tts_characters == 12
    assert t.llm_model == "mock-llm"
    assert t.error == "LLM timed out"
    assert r.errors == ["LLM timed out"]
