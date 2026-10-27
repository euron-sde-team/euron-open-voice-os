"""Turn recorder: measures every turn from the frames that actually flowed.

Each user turn gets a record with what was said, what the agent answered, whether the user
interrupted, and four latencies measured on this process's monotonic clock:

    speech ends ──► turn declared over ──► first LLM token ──► first TTS audio ──► agent audio
      (VAD)          endpoint_ms          llm_first_token_ms    tts_first_audio_ms
      └──► transcript: stt_ms (runs in parallel with turn detection)
    └──────────────────────────────── response_ms ─────────────────────────────────┘

``response_ms`` is the number a caller feels: from the moment they stopped talking (the
last voice-activity stop before the turn ended) to the agent's audio starting. It includes
the wait while the turn detector decides the user is done. Nothing is estimated; a stage
that did not run stays ``None``.
Usage (tokens, audio seconds, characters) comes from the services' own usage metrics.
"""

from __future__ import annotations

import time
from collections import deque
from datetime import UTC, datetime

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    InterruptionFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import (
    LLMUsageMetricsData,
    STTUsageMetricsData,
    TTSUsageMetricsData,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed

from voiceos.core.contract import TurnReport, UsageReport


def _ms(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or end < start:
        return None
    return round((end - start) * 1000, 1)


def _latest(*times: float | None) -> float | None:
    """The LLM starts once the turn is over and the transcript is in, whichever is later."""
    present = [t for t in times if t is not None]
    return max(present) if present else None


class _Turn:
    def __init__(self, index: int, *, greeting: bool = False) -> None:
        self.index = index
        self.started_at = datetime.now(UTC)
        self.greeting = greeting
        self.user_started: float | None = None
        self.user_stopped: float | None = None
        self.speech_end: float | None = None
        self.transcript_at: float | None = None
        self.llm_first: float | None = None
        self.tts_first: float | None = None
        self.bot_started: float | None = None
        self.user_text: list[str] = []
        self.agent_text: list[str] = []
        self.interrupted = False
        self.error: str | None = None
        self.llm_model: str | None = None
        self.routed_small = False
        self.response_cache_hit = False

    def report(self) -> TurnReport:
        return TurnReport(
            index=self.index,
            started_at=self.started_at,
            user_text=" ".join(self.user_text).strip() or None,
            agent_text="".join(self.agent_text).strip() or None,
            interrupted=self.interrupted,
            user_speech_ms=_ms(self.user_started, self.speech_end),
            endpoint_ms=_ms(self.speech_end, self.user_stopped),
            stt_ms=_ms(self.speech_end, self.transcript_at),
            llm_first_token_ms=_ms(_latest(self.user_stopped, self.transcript_at), self.llm_first),
            tts_first_audio_ms=_ms(self.llm_first, self.tts_first),
            response_ms=_ms(self.speech_end or self.user_stopped, self.bot_started),
            llm_model=self.llm_model,
            llm_routed_small=self.routed_small,
            response_cache_hit=self.response_cache_hit,
            error=self.error,
        )


class TurnRecorder(BaseObserver):
    """Observes a session's pipeline and builds its turn and usage reports."""

    def __init__(self) -> None:
        super().__init__()
        self._now = time.monotonic
        self._seen: deque[int] = deque(maxlen=4096)
        self._seen_set: set[int] = set()
        self._turns: list[_Turn] = []
        self._current: _Turn | None = None
        self._bot_speaking = False
        self.usage = UsageReport()
        self.errors: list[str] = []
        self.interruptions = 0
        # Name of the small-model processor, so its tokens are counted (and priced) apart.
        self.small_processor: str | None = None

    # ── public ──────────────────────────────────────────────────────────────────────
    def start_greeting(self, text: str) -> None:
        """The agent speaks first: a turn with no user speech, its text known up front."""
        turn = self._open(greeting=True)
        turn.agent_text.append(text)

    def mark_current(
        self, *, model: str | None = None, routed_small: bool = False, cache_hit: bool = False
    ) -> None:
        if self._current is not None:
            if model:
                self._current.llm_model = model
            self._current.routed_small = self._current.routed_small or routed_small
            self._current.response_cache_hit = self._current.response_cache_hit or cache_hit

    def turns(self) -> list[TurnReport]:
        """Turns that carried speech or an error, numbered from 0 in order."""
        kept = [t for t in self._turns if t.user_text or t.agent_text or t.error]
        return [t.report().model_copy(update={"index": i}) for i, t in enumerate(kept)]

    @property
    def bot_speaking(self) -> bool:
        return self._bot_speaking

    # ── observer ────────────────────────────────────────────────────────────────────
    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if frame.id in self._seen_set:
            return
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(frame.id)
        self._seen_set.add(frame.id)
        now = self._now()

        if isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
            turn = self._user_turn()
            if turn.user_started is None:
                turn.user_started = now
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            # The last pause before the turn ends is the real end of speech.
            turn = self._user_turn()
            if turn.user_stopped is None:
                turn.speech_end = now
        elif isinstance(frame, UserStoppedSpeakingFrame):
            turn = self._user_turn()
            if turn.user_stopped is None:
                turn.user_stopped = now
            if turn.speech_end is None:
                turn.speech_end = now
        elif isinstance(frame, InterruptionFrame):
            self.interruptions += 1
            if self._bot_speaking and self._turns:
                # The turn being answered is the one before the newly opened turn.
                target = self._turns[-2] if len(self._turns) > 1 else self._turns[-1]
                target.interrupted = True
        elif isinstance(frame, TranscriptionFrame):
            if frame.text.strip():
                turn = self._user_turn()
                turn.user_text.append(frame.text.strip())
                turn.transcript_at = now
        elif isinstance(frame, LLMFullResponseStartFrame):
            pass
        elif isinstance(frame, LLMTextFrame):
            turn = self._current or self._open()
            if turn.llm_first is None:
                turn.llm_first = now
            turn.agent_text.append(frame.text)
        elif isinstance(frame, TTSAudioRawFrame):
            if self._current is not None and self._current.tts_first is None:
                self._current.tts_first = now
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            if self._current is not None and self._current.bot_started is None:
                self._current.bot_started = now
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
        elif isinstance(frame, MetricsFrame):
            self._metrics(frame)
        elif isinstance(frame, ErrorFrame):
            message = str(frame.error)[:300]
            self.errors.append(message)
            if self._current is not None:
                self._current.error = message

    # ── internals ───────────────────────────────────────────────────────────────────
    def _user_turn(self) -> _Turn:
        """The turn the caller is speaking in, opening one when needed.

        Pipecat's turn strategies may emit the turn-start frame before or after the VAD
        events and the transcript, so any of them opens the turn: a new one starts when
        there is none, when the current one is the greeting, or when the agent already
        began answering it. Speaking over the agent marks the answered turn interrupted.
        """
        cur = self._current
        answering = cur is not None and (cur.llm_first is not None or cur.bot_started is not None)
        if cur is not None and not cur.greeting and not answering:
            return cur
        if cur is not None and self._bot_speaking:
            cur.interrupted = True
        return self._open()

    def _open(self, *, greeting: bool = False) -> _Turn:
        turn = _Turn(len(self._turns), greeting=greeting)
        self._turns.append(turn)
        self._current = turn
        return turn

    def _metrics(self, frame: MetricsFrame) -> None:
        for item in frame.data:
            if isinstance(item, LLMUsageMetricsData):
                if self.small_processor and item.processor == self.small_processor:
                    self.usage.llm_small_input_tokens += item.value.prompt_tokens
                    self.usage.llm_small_output_tokens += item.value.completion_tokens
                else:
                    self.usage.llm_input_tokens += item.value.prompt_tokens
                    self.usage.llm_output_tokens += item.value.completion_tokens
                self.usage.llm_usage_reported = True
                if self._current is not None and item.model:
                    self._current.llm_model = item.model
            elif isinstance(item, TTSUsageMetricsData):
                self.usage.tts_characters += int(item.value)
            elif isinstance(item, STTUsageMetricsData):
                seconds = getattr(item.value, "audio_seconds", None)
                if seconds:
                    self.usage.stt_audio_seconds += float(seconds)
