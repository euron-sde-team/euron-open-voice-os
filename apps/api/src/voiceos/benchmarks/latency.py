"""Latency benchmark: real sessions through the real runtime, measured two ways.

For each agent it holds ``sessions`` conversations, each speaking the committed test
utterances in the agent's language, and records per turn:

* the runtime's own measurement (end of speech by VAD to first agent audio, with the
  stage breakdown), read from the session report the runtime filed, and
* the client-perceived delay (the client's last speech frame to the first agent audio
  frame it received), which adds transport and buffering.

The utterances are synthesized with Kokoro and committed, so every run hears the same
audio; the report says so, and names the machine it ran on.
"""

from __future__ import annotations

import asyncio
import os
import platform
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from voiceos.benchmarks.client import converse, load_pcm16k

AUDIO = Path(__file__).parent / "audio"


def utterances(language: str) -> list[Path]:
    prefix = "hi" if language.startswith("hi") else "en"
    files = sorted(AUDIO.glob(f"{prefix}-*.wav"))
    if not files:
        raise FileNotFoundError(f"No test utterances for {language} in {AUDIO}")
    return files


def hardware() -> dict[str, Any]:
    info: dict[str, Any] = {
        "machine": platform.machine(),
        "system": platform.system(),
        "cpus": os.cpu_count(),
        "python": platform.python_version(),
    }
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith(("model name", "cpu model", "hardware")):
                info["cpu"] = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    info["gpu"] = os.environ.get("BENCH_GPU", "none detected (CPU only)")
    return info


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 1)


@dataclass
class Conversation:
    client_first_audio_ms: float | None
    transcripts: list[str]


async def converse_once(ws_url: str, file: Path) -> Conversation:
    """One session, one utterance: sessions stay independent of each other."""
    result = await converse(ws_url, [load_pcm16k(file)], gap_s=4.0, tail_s=4.0)
    first = result.first_audio_after_speech
    return Conversation(
        round(first * 1000, 1) if first is not None else None,
        [t for t in result.texts("user-transcription") if t],
    )


def summarize(turns: list[dict[str, Any]], client_ms: list[float]) -> dict[str, Any]:
    def field(name: str) -> list[float]:
        return [float(t[name]) for t in turns if t.get(name) is not None]

    response = field("response_ms")
    return {
        "turns": len(turns),
        "response_ms_p50": percentile(response, 0.5),
        "response_ms_p95": percentile(response, 0.95),
        "client_first_audio_ms_p50": percentile(client_ms, 0.5),
        "client_first_audio_ms_p95": percentile(client_ms, 0.95),
        "stages_ms_avg": {
            name: (round(statistics.mean(v), 1) if (v := field(name)) else None)
            for name in ("endpoint_ms", "stt_ms", "llm_first_token_ms", "tts_first_audio_ms")
        },
    }


async def gather(tasks: list[Any], concurrency: int) -> list[Any]:
    slots = asyncio.Semaphore(concurrency)

    async def guarded(coro: Any) -> Any:
        async with slots:
            return await coro

    return await asyncio.gather(*(guarded(t) for t in tasks))
