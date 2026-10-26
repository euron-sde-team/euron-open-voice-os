"""TTS phrase cache: the same sentence in the same voice is synthesized once.

Greetings, confirmations and fixed phrases ("Is there anything else?") repeat across
sessions. ``cached(service_cls)`` subclasses any TTS service whose ``run_tts`` yields audio
frames (HTTP-based services, including VoiceOS's own speech server) so a repeated phrase
is replayed from memory: no provider call, no characters billed, and its first audio is
immediate. Hits and the characters they saved are counted for the session's cost report.

The cache is per runtime process and bounded in bytes. Keys include the provider, model,
voice and exact text, so a voice change never replays the wrong audio.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService

T = TypeVar("T", bound=type[TTSService])

# Long sentences rarely repeat; caching them only churns the cache.
MAX_CACHED_CHARS = 200


@dataclass
class CacheStats:
    hits: int = 0
    characters_saved: int = 0


class PhraseCache:
    def __init__(self, max_bytes: int = 64_000_000) -> None:
        self._data: OrderedDict[str, tuple[bytes, int]] = OrderedDict()
        self._bytes = 0
        self._max = max_bytes
        self._lock = threading.Lock()

    @staticmethod
    def key(namespace: str, text: str) -> str:
        return hashlib.sha256(f"{namespace}\x00{text.strip()}".encode()).hexdigest()

    def get(self, key: str) -> tuple[bytes, int] | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is not None:
                self._data.move_to_end(key)
            return hit

    def put(self, key: str, audio: bytes, sample_rate: int) -> None:
        if not audio or len(audio) > self._max // 8:
            return
        with self._lock:
            old = self._data.pop(key, None)
            if old is not None:
                self._bytes -= len(old[0])
            self._data[key] = (audio, sample_rate)
            self._bytes += len(audio)
            while self._bytes > self._max:
                _, (dropped, _) = self._data.popitem(last=False)
                self._bytes -= len(dropped)


@dataclass
class _Wiring:
    cache: PhraseCache
    namespace: str
    stats: CacheStats = field(default_factory=CacheStats)


def cached(service_cls: T) -> T:
    """A subclass of ``service_cls`` whose ``run_tts`` consults a ``PhraseCache``."""

    class Cached(service_cls):  # type: ignore[valid-type, misc]
        def __init__(self, *args: Any, phrase_cache: _Wiring, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._phrase = phrase_cache

        async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
            wiring: _Wiring = self._phrase
            cacheable = 0 < len(text.strip()) <= MAX_CACHED_CHARS
            key = PhraseCache.key(wiring.namespace, text)
            hit = wiring.cache.get(key) if cacheable else None
            if hit is not None:
                audio, rate = hit
                wiring.stats.hits += 1
                wiring.stats.characters_saved += len(text)
                await self.stop_ttfb_metrics()
                step = rate * 2 // 10  # 100 ms per frame
                for i in range(0, len(audio), step):
                    yield TTSAudioRawFrame(audio[i : i + step], rate, 1, context_id=context_id)
                return
            collected: list[bytes] = []
            rate = 0
            failed = False
            async for frame in super().run_tts(text, context_id):
                if isinstance(frame, TTSAudioRawFrame):
                    collected.append(frame.audio)
                    rate = frame.sample_rate
                elif isinstance(frame, ErrorFrame):
                    failed = True
                yield frame
            if cacheable and collected and not failed:
                wiring.cache.put(key, b"".join(collected), rate)

    Cached.__name__ = f"Cached{service_cls.__name__}"
    Cached.__qualname__ = Cached.__name__
    return Cached  # type: ignore[return-value]


def wiring(cache: PhraseCache, namespace: str) -> _Wiring:
    return _Wiring(cache, namespace)


Factory = Callable[..., TTSService]
