"""Local speech models: Whisper (faster-whisper) for recognition, Kokoro for synthesis.

Both are CPU-friendly ONNX/CTranslate2 models that also use a GPU when one is present.
Models load lazily on first use (or eagerly at startup for the configured defaults) and
inference runs on a small dedicated thread pool, so a long synthesis never blocks the
event loop or starves other requests.

Kokoro turns text into phonemes with espeak-ng. The speech container image installs the
distribution's ``espeak-ng`` package; nothing here bundles or links it at build time.
"""

from __future__ import annotations

import ctypes.util
import logging
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("voiceos.speech")

KOKORO_SAMPLE_RATE = 24_000
WHISPER_SAMPLE_RATE = 16_000

# Whisper sizes faster-whisper downloads by name. "whisper-1" (the OpenAI model name many
# clients send) maps to the configured default.
WHISPER_SIZES = ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo")

# Kokoro voice ids start with a language letter. Hindi voices are hf_* and hm_*.
_VOICE_LANG = {
    "a": "en-us",
    "b": "en-gb",
    "e": "es",
    "f": "fr-fr",
    "h": "hi",
    "i": "it",
    "j": "ja",
    "p": "pt-br",
    "z": "cmn",
}

_SENTENCE_END = re.compile(r"(?<=[.!?।॥])\s+")


class SpeechError(Exception):
    """A request the models cannot serve (unknown voice, unsupported audio)."""


@dataclass(frozen=True, slots=True)
class Transcript:
    text: str
    language: str
    duration_s: float
    segments: list[dict[str, Any]]
    elapsed_ms: float


def whisper_size(model: str, default: str) -> str:
    name = model.strip().lower().removeprefix("whisper-").removeprefix("faster-whisper-")
    if name in ("", "1", "default"):
        return default
    if name not in WHISPER_SIZES:
        raise SpeechError(f"Unknown Whisper model {model!r}. Use one of: {', '.join(WHISPER_SIZES)}")
    return name


def voice_language(voice: str) -> str:
    lang = _VOICE_LANG.get(voice[:1].lower())
    if lang is None or len(voice) < 3 or voice[2] != "_":
        raise SpeechError(f"Unknown voice {voice!r}. List voices at GET /v1/voices")
    return lang


def split_sentences(text: str, max_chars: int = 300) -> list[str]:
    """Sentences, so the first audio is ready after the first sentence, not the whole reply.

    Very long sentences are cut at commas, then at word boundaries, to keep each synthesis
    call short.
    """
    out: list[str] = []
    for sentence in _SENTENCE_END.split(text.strip()):
        sentence = sentence.strip()
        while len(sentence) > max_chars:
            cut = sentence.rfind(",", 0, max_chars)
            if cut < max_chars // 3:
                cut = sentence.rfind(" ", 0, max_chars)
            if cut <= 0:
                cut = max_chars
            out.append(sentence[: cut + 1].strip())
            sentence = sentence[cut + 1 :].strip()
        if sentence:
            out.append(sentence)
    return out


def to_pcm16(samples: np.ndarray) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767).astype("<i2").tobytes()


class SpeechModels:
    """Holds loaded models; safe to share across threads (one lock per model kind)."""

    def __init__(
        self,
        models_dir: Path,
        *,
        whisper_default: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        kokoro_model: str = "kokoro-v1.0.int8.onnx",
        kokoro_voices: str = "voices-v1.0.bin",
    ) -> None:
        self.models_dir = models_dir
        self.whisper_default = whisper_default
        self.device = device
        self.compute_type = compute_type
        self.kokoro_model = kokoro_model
        self.kokoro_voices = kokoro_voices
        self._whisper: dict[str, Any] = {}
        self._kokoro: Any = None
        self._whisper_lock = threading.Lock()
        self._kokoro_lock = threading.Lock()

    # ── Whisper ─────────────────────────────────────────────────────────────────────
    def whisper(self, size: str) -> Any:
        with self._whisper_lock:
            model = self._whisper.get(size)
            if model is None:
                from faster_whisper import WhisperModel

                started = time.perf_counter()
                model = WhisperModel(
                    size,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=str(self.models_dir / "whisper"),
                )
                self._whisper[size] = model
                log.info(
                    "whisper model loaded",
                    extra={"size": size, "s": round(time.perf_counter() - started, 1)},
                )
            return model

    def transcribe(
        self, audio: np.ndarray, *, size: str, language: str | None, prompt: str | None = None
    ) -> Transcript:
        model = self.whisper(size)
        started = time.perf_counter()
        segments, info = model.transcribe(
            audio,
            language=language or None,
            beam_size=1,
            vad_filter=False,  # the runtime already sends one detected utterance
            initial_prompt=prompt or None,
            condition_on_previous_text=False,
        )
        parts = [
            {"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()}
            for s in segments
        ]
        return Transcript(
            text=" ".join(p["text"] for p in parts).strip(),
            language=info.language,
            duration_s=len(audio) / WHISPER_SAMPLE_RATE,
            segments=parts,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    # ── Kokoro ──────────────────────────────────────────────────────────────────────
    def kokoro(self) -> Any:
        with self._kokoro_lock:
            if self._kokoro is None:
                from kokoro_onnx import EspeakConfig, Kokoro

                model = self.models_dir / "kokoro" / self.kokoro_model
                voices = self.models_dir / "kokoro" / self.kokoro_voices
                if not model.exists() or not voices.exists():
                    raise SpeechError(
                        f"Kokoro files are missing in {model.parent}. Run `make models`"
                    )
                lib = ctypes.util.find_library("espeak-ng")
                espeak = EspeakConfig(lib_path=lib, data_path=_espeak_data_dir())
                started = time.perf_counter()
                self._kokoro = Kokoro(str(model), str(voices), espeak_config=espeak)
                log.info("kokoro loaded", extra={"s": round(time.perf_counter() - started, 1)})
            return self._kokoro

    def voices(self) -> list[str]:
        return sorted(self.kokoro().get_voices())

    def synthesize(self, text: str, *, voice: str, speed: float = 1.0) -> Iterator[bytes]:
        """PCM16 mono at 24 kHz, one chunk per sentence."""
        lang = voice_language(voice)
        kokoro = self.kokoro()
        if voice not in kokoro.get_voices():
            raise SpeechError(f"Unknown voice {voice!r}. List voices at GET /v1/voices")
        for sentence in split_sentences(text):
            samples, _ = kokoro.create(sentence, voice=voice, speed=speed, lang=lang)
            yield to_pcm16(samples)


def _espeak_data_dir() -> str | None:
    """The distribution's espeak-ng data directory (Debian: under the multiarch lib dir)."""
    for candidate in (
        Path("/usr/lib/aarch64-linux-gnu/espeak-ng-data"),
        Path("/usr/lib/x86_64-linux-gnu/espeak-ng-data"),
        Path("/usr/share/espeak-ng-data"),
    ):
        if (candidate / "phontab").exists():
            return str(candidate)
    return None
