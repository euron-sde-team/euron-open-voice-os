"""A headless voice client: the benchmark, the demo seed and the tests use it.

It connects to the runtime's WebSocket like a browser would, streams a WAV file as
microphone audio in real time (20 ms frames, then silence), and records what came back:
agent audio (with timestamps), RTVI events (transcripts, speaking state, errors).
"""

from __future__ import annotations

import asyncio
import contextlib
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
        data: np.ndarray[Any, Any] = np.frombuffer(
            w.readframes(w.getnframes()), dtype="<i2"
        ).astype(np.float32)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        n = int(len(data) * SAMPLE_RATE / rate)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data)
    return bytes(np.clip(data, -32768, 32767).astype("<i2").tobytes())


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(seconds * SAMPLE_RATE)


@dataclass
class Result:
    audio_frames: list[tuple[float, int]] = field(default_factory=list)  # (t, bytes)
    events: list[dict[str, Any]] = field(default_factory=list)
    closed_code: int | None = None
    first_audio_after_speech: float | None = None
    # Monotonic times each utterance started and finished streaming.
    speech_started: list[float] = field(default_factory=list)
    speech_ended: list[float] = field(default_factory=list)

    def audio_between(self, start: float, end: float) -> float:
        """Seconds of agent audio received between two monotonic times."""
        return sum(n for t, n in self.audio_frames if start <= t <= end) / 2 / 24_000

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
    frame = frames_pb2.Frame()  # type: ignore[attr-defined]  # generated protobuf module
    frame.audio.audio = pcm
    frame.audio.sample_rate = SAMPLE_RATE
    frame.audio.num_channels = 1
    return bytes(frame.SerializeToString())


async def converse(
    url: str,
    utterances: list[bytes],
    *,
    gap_s: float = 2.5,
    tail_s: float = 1.0,
    reply_timeout_s: float = 45.0,
    greeting_timeout_s: float = 20.0,
    wait_each: bool = False,
    origin: str | None = "http://localhost:4510",
) -> Result:
    """Speak each utterance, then stay on the line until the agent has finished answering.

    After the last utterance the client keeps sending silence (as an open microphone would)
    until the agent stops speaking after it, or ``reply_timeout_s`` passes, then listens for
    ``tail_s`` more. Waiting for the answer rather than a fixed time keeps the sessions
    complete on a slow or busy machine. With ``wait_each`` it also waits for the answer to
    every earlier utterance before the next, like a caller who lets the agent finish;
    without it, the next utterance follows ``gap_s`` later (and may interrupt).
    """
    result = Result()
    headers = {"Origin": origin} if origin else {}
    async with websockets.connect(url, additional_headers=headers, max_size=None) as ws:
        speech_ended: list[float] = []
        # The agent answered the latest utterance: audio arrived after it ended, then the
        # agent stopped speaking.
        answered = asyncio.Event()
        heard_since_end = [False]
        greeted = asyncio.Event()

        async def receive() -> None:
            try:
                async for raw in ws:
                    if isinstance(raw, str):
                        continue
                    frame = frames_pb2.Frame()  # type: ignore[attr-defined]
                    frame.ParseFromString(raw)
                    which = frame.WhichOneof("frame")
                    now = time.monotonic()
                    if which == "audio":
                        result.audio_frames.append((now, len(frame.audio.audio)))
                        if speech_ended and now > speech_ended[-1]:
                            heard_since_end[0] = True
                        if (
                            speech_ended
                            and result.first_audio_after_speech is None
                            and now > speech_ended[-1]
                        ):
                            result.first_audio_after_speech = now - speech_ended[-1]
                    elif which == "message":
                        with contextlib.suppress(ValueError):
                            event = json.loads(frame.message.data)
                            result.events.append(event)
                            if event.get("type") == "bot-stopped-speaking" and not speech_ended:
                                greeted.set()
                            if (
                                event.get("type") == "bot-stopped-speaking"
                                and speech_ended
                                and heard_since_end[0]
                            ):
                                answered.set()
            except websockets.ConnectionClosed as exc:
                result.closed_code = exc.code

        receiver = asyncio.create_task(receive())
        # The agent may hang up first (its end_conversation tool): that ends the call.
        with contextlib.suppress(websockets.ConnectionClosed):
            # Let the greeting finish first (as a polite caller would), so its audio is never
            # mistaken for the answer. Agents without a greeting just wait greeting_timeout_s.
            quiet_frame = _audio_message(silence(FRAME_MS / 1000))
            deadline = time.monotonic() + greeting_timeout_s
            while time.monotonic() < deadline and not greeted.is_set() and not receiver.done():
                await ws.send(quiet_frame)
                await asyncio.sleep(FRAME_MS / 1000)
            await asyncio.sleep(0.3)
            step = SAMPLE_RATE * 2 * FRAME_MS // 1000
            for n, pcm in enumerate(utterances):
                started = time.monotonic()
                result.speech_started.append(started)
                for i in range(0, len(pcm), step):
                    await ws.send(_audio_message(pcm[i : i + step]))
                    # Real time: the runtime's VAD and turn detection see natural pacing.
                    await asyncio.sleep(
                        max(0.0, started + (i + step) / (SAMPLE_RATE * 2) - time.monotonic())
                    )
                answered.clear()
                heard_since_end[0] = False
                speech_ended.append(time.monotonic())
                result.speech_ended.append(speech_ended[-1])
                quiet = silence(gap_s)
                for i in range(0, len(quiet), step):
                    await ws.send(_audio_message(quiet[i : i + step]))
                    await asyncio.sleep(FRAME_MS / 1000)
                if wait_each or n == len(utterances) - 1:
                    deadline = time.monotonic() + reply_timeout_s
                    while (
                        time.monotonic() < deadline
                        and not answered.is_set()
                        and not receiver.done()
                    ):
                        await ws.send(quiet_frame)
                        await asyncio.sleep(FRAME_MS / 1000)
            deadline = time.monotonic() + tail_s
            while time.monotonic() < deadline and not receiver.done():
                await ws.send(quiet_frame)
                await asyncio.sleep(FRAME_MS / 1000)
        await ws.close()
        await asyncio.wait_for(receiver, timeout=5)
    return result
