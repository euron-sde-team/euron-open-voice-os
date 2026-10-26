"""A headless voice client for tests, benchmarks and the demo seed.

It connects to the runtime's WebSocket like a browser would, streams a WAV file as
microphone audio in real time (20 ms frames, then silence), and records what came back:
agent audio (with timestamps), RTVI events (transcripts, speaking state, errors).
"""

from __future__ import annotations

import asyncio
import json
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import websockets
from pipecat.frames.protobufs import frames_pb2

SAMPLE_RATE = 16_000
FRAME_MS = 20


def load_pcm16k(path: str | Path) -> bytes:
    """Mono 16 kHz PCM16 from a 16-bit WAV of any rate."""
    with wave.open(str(path)) as w:
        rate, channels = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        n = int(len(data) * SAMPLE_RATE / rate)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data)
    return np.clip(data, -32768, 32767).astype("<i2").tobytes()


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(seconds * SAMPLE_RATE)


@dataclass
class Result:
    audio_frames: list[tuple[float, int]] = field(default_factory=list)  # (t, bytes)
    events: list[dict[str, Any]] = field(default_factory=list)
    closed_code: int | None = None
    first_audio_after_speech: float | None = None

    def texts(self, kind: str) -> list[str]:
        out = []
        for e in self.events:
            if e.get("type") == kind:
                data = e.get("data") or {}
                out.append(str(data.get("text", "")))
        return out

    @property
    def agent_audio_seconds(self) -> float:
        return sum(n for _, n in self.audio_frames) / 2 / 24_000


def _audio_message(pcm: bytes) -> bytes:
    frame = frames_pb2.Frame()
    frame.audio.audio = pcm
    frame.audio.sample_rate = SAMPLE_RATE
    frame.audio.num_channels = 1
    return frame.SerializeToString()


async def converse(
    url: str,
    utterances: list[bytes],
    *,
    gap_s: float = 2.5,
    tail_s: float = 6.0,
    origin: str | None = "http://localhost:4510",
) -> Result:
    """Speak each utterance after the previous answer had time to start, then listen."""
    result = Result()
    headers = {"Origin": origin} if origin else {}
    async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
        speech_ended: list[float] = []

        async def receive() -> None:
            try:
                async for raw in ws:
                    if isinstance(raw, str):
                        continue
                    frame = frames_pb2.Frame()
                    frame.ParseFromString(raw)
                    which = frame.WhichOneof("frame")
                    now = time.monotonic()
                    if which == "audio":
                        result.audio_frames.append((now, len(frame.audio.audio)))
                        if speech_ended and result.first_audio_after_speech is None and now > speech_ended[-1]:
                            result.first_audio_after_speech = now - speech_ended[-1]
                    elif which == "message":
                        try:
                            result.events.append(json.loads(frame.message.data))
                        except ValueError:
                            pass
            except websockets.ConnectionClosed as exc:
                result.closed_code = exc.code

        receiver = asyncio.create_task(receive())
        await ws.send(_audio_message(silence(0.2)))
        await asyncio.sleep(gap_s)
        step = SAMPLE_RATE * 2 * FRAME_MS // 1000
        for pcm in utterances:
            started = time.monotonic()
            for i in range(0, len(pcm), step):
                await ws.send(_audio_message(pcm[i : i + step]))
                # Real time: the runtime's VAD and turn detection see natural pacing.
                await asyncio.sleep(max(0.0, started + (i + step) / (SAMPLE_RATE * 2) - time.monotonic()))
            speech_ended.append(time.monotonic())
            quiet = silence(gap_s)
            for i in range(0, len(quiet), step):
                await ws.send(_audio_message(quiet[i : i + step]))
                await asyncio.sleep(FRAME_MS / 1000)
        deadline = time.monotonic() + tail_s
        quiet_frame = _audio_message(silence(FRAME_MS / 1000))
        while time.monotonic() < deadline and not receiver.done():
            await ws.send(quiet_frame)
            await asyncio.sleep(FRAME_MS / 1000)
        await ws.close()
        await asyncio.wait_for(receiver, timeout=5)
    return result
