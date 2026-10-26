"""Cost optimizer, per turn: answer from cache, or pick the cheaper model when it suffices.

Sits between the user aggregator and the LLM. For each finished user turn it:

1. **Response cache** (agent opt-in, agents without tools only): an exact repeat of a
   normalized question replays the stored answer as if the LLM had produced it, so no LLM
   call is made and no tokens are billed. Answers are stored only from turns the user did
   not interrupt.
2. **Routing**: with a small model configured, short turns (at most
   ``small_model_max_words`` words) go to it and everything else to the main model.

Speculative contexts (an eager start before the turn is confirmed) pass through untouched.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import OrderedDict
from typing import Any

from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    ManuallySwitchServiceFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voiceos.core.contract import ResolvedAgent
from voiceos.runtime.turns import TurnRecorder

# Indic vowel signs are not \w; keep them so Hindi words stay whole.
_NON_WORD = re.compile(r"[^\w\s\u0900-\u0963\u0966-\u0dff]", re.UNICODE)


def normalize(text: str) -> str:
    return " ".join(_NON_WORD.sub(" ", text.lower()).split())


class ResponseCache:
    """Process-wide, bounded, with expiry. Keys bind the agent and its config version."""

    def __init__(self, max_entries: int = 5000, ttl_s: float = 24 * 3600) -> None:
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._max = max_entries
        self._ttl = ttl_s
        self._lock = threading.Lock()

    @staticmethod
    def key(agent: ResolvedAgent, question: str) -> str:
        raw = f"{agent.agent_id}:{agent.version}:{normalize(question)}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> str | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None or hit[0] < time.monotonic():
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return hit[1]

    def put(self, key: str, answer: str) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + self._ttl, answer)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


def last_user_text(frame: LLMContextFrame) -> str:
    for message in reversed(frame.context.get_messages()):
        if isinstance(message, dict) and message.get("role") == "user":
            content: Any = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


class TurnRouter(FrameProcessor):
    def __init__(
        self,
        agent: ResolvedAgent,
        recorder: TurnRecorder,
        cache: ResponseCache | None,
        *,
        main_llm: FrameProcessor | None = None,
        small_llm: FrameProcessor | None = None,
    ) -> None:
        super().__init__(name="TurnRouter")
        self._agent = agent
        self._recorder = recorder
        self._cache = cache if agent.cache.response_cache and not agent.tools else None
        self._main = main_llm
        self._small = small_llm
        self.pending_key: str | None = None
        self.cache_hits = 0
        self.routed_small = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if not isinstance(frame, LLMContextFrame) or getattr(frame, "speculation", False):
            await self.push_frame(frame, direction)
            return
        question = last_user_text(frame)
        if self._cache is not None and question.strip():
            key = ResponseCache.key(self._agent, question)
            answer = self._cache.get(key)
            if answer is not None:
                self.cache_hits += 1
                self._recorder.mark_current(cache_hit=True, model="response-cache")
                # Replay as an LLM response, so TTS, transcripts and context behave normally.
                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(LLMTextFrame(answer))
                await self.push_frame(LLMFullResponseEndFrame())
                return
            self.pending_key = key
        if self._small is not None and self._main is not None:
            small = len(question.split()) <= self._agent.small_model_max_words
            target = self._small if small else self._main
            if small:
                self.routed_small += 1
            await self.push_frame(ManuallySwitchServiceFrame(service=target))
            self._recorder.mark_current(
                routed_small=small,
                model=(self._agent.llm_small if small else self._agent.llm).model,  # type: ignore[union-attr]
            )
        await self.push_frame(frame, direction)

    def store_answer(self, answer: str) -> None:
        """Called when a turn's answer finished playing without interruption."""
        if self._cache is not None and self.pending_key and answer.strip():
            self._cache.put(self.pending_key, answer.strip())
        self.pending_key = None
