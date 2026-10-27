"""OpenAI-compatible speech endpoints over the local models.

    POST /v1/audio/transcriptions   multipart WAV (16-bit PCM) -> {"text", ...}
    POST /v1/audio/speech           JSON -> streamed PCM16 24 kHz (or one WAV)
    GET  /v1/voices, /v1/models, /healthz, /readyz

Any client that speaks the OpenAI audio API (Pipecat's OpenAI STT service, the OpenAI
SDKs) works against it, and so does any other server with the same API in its place. It
accepts any Kokoro voice id, unlike OpenAI's fixed list, and reports how long the model
took in ``x-voiceos-*`` headers so the runtime can attribute latency honestly.
"""

from __future__ import annotations

import asyncio
import io
import logging
import struct
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from scipy.io import wavfile
from scipy.signal import resample_poly
from starlette.background import BackgroundTask

from voiceos import __version__
from voiceos.core.config import SpeechSettings, get_speech_settings
from voiceos.core.logs import configure_logging
from voiceos.speech.models import (
    KOKORO_SAMPLE_RATE,
    WHISPER_SAMPLE_RATE,
    SpeechError,
    SpeechModels,
    whisper_size,
)

log = logging.getLogger("voiceos.speech")


class SpeechRequest(BaseModel):
    model: str = "kokoro"
    input: str = Field(min_length=1)
    voice: str = "af_heart"
    response_format: Literal["pcm", "wav"] = "pcm"
    speed: float = Field(1.0, ge=0.5, le=2.0)


_WAV_FORMATS = "Send WAV audio: 16-bit or 32-bit PCM, or 32-bit float"

# Whisper often writes Hindi in Urdu script and Marathi in Latin letters, even with the
# language set. A short prompt in the right script steers it back to Devanagari (measured on
# FLEURS: docs/benchmarks/wer.md). Used only when the caller sends no prompt of its own.
SCRIPT_PROMPTS = {
    "hi": "नमस्ते, आप कैसे हैं? मैं ठीक हूँ।",
    "mr": "नमस्कार, तुम्ही कसे आहात? मी ठीक आहे.",
}


def _error(status: int, message: str, code: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"message": message, "type": "invalid_request_error", "code": code}},
        status_code=status,
    )


def decode_wav(data: bytes, max_s: float) -> np.ndarray:
    """16 kHz mono float32 from a 16-bit, 32-bit or float WAV of any rate and channel count."""
    try:
        rate, raw = wavfile.read(io.BytesIO(data))
    except (ValueError, EOFError) as exc:
        raise SpeechError(_WAV_FORMATS) from exc
    if raw.dtype == np.int16:
        pcm = raw.astype(np.float32) / 32768
    elif raw.dtype == np.int32:
        pcm = raw.astype(np.float32) / 2147483648
    elif raw.dtype == np.float32:
        pcm = raw
    else:
        raise SpeechError(_WAV_FORMATS)
    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1)
    if len(pcm) / rate > max_s:
        raise SpeechError(f"Audio longer than {max_s:g} s; send one utterance at a time")
    if rate != WHISPER_SAMPLE_RATE:
        pcm = resample_poly(pcm, WHISPER_SAMPLE_RATE, rate)
    return np.asarray(pcm, dtype=np.float32)


def wav_header(sample_rate: int, data_len: int = 0xFFFFFFFF - 36) -> bytes:
    """A WAV header for 16-bit mono PCM (length unknown when streaming)."""
    return b"RIFF" + struct.pack(
        "<I4s4sIHHIIHH4sI",
        36 + data_len,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * 2,
        2,
        16,
        b"data",
        data_len,
    )


def create_app(settings: SpeechSettings | None = None) -> FastAPI:
    settings = settings or get_speech_settings()
    configure_logging(settings.log_level)
    models = SpeechModels(
        Path(settings.speech_models_dir),
        whisper_default=settings.whisper_default,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        kokoro_model=settings.kokoro_model,
        kokoro_voices=settings.kokoro_voices,
        threads=settings.speech_threads,
    )
    # Separate limits: a transcription (on the user's critical path) never queues behind
    # the agent's own sentences being synthesized, and the other way round.
    stt_slots = asyncio.Semaphore(settings.speech_concurrency)
    tts_slots = asyncio.Semaphore(settings.speech_concurrency)
    ready: dict[str, Any] = {"whisper": [], "kokoro": False}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for size in settings.whisper_preload:
            await asyncio.to_thread(models.whisper, whisper_size(size, settings.whisper_default))
            ready["whisper"].append(size)
        if settings.kokoro_preload:
            await asyncio.to_thread(models.kokoro)
            ready["kokoro"] = True
        yield

    app = FastAPI(
        title="Euron Open VoiceOS speech",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.models = models

    @app.middleware("http")
    async def _auth(request: Request, call_next: Any) -> Response:
        open_paths = ("/healthz", "/readyz")
        if settings.speech_api_key and request.url.path not in open_paths:
            token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if token != settings.speech_api_key:
                return _error(401, "Missing or wrong speech API key", "unauthenticated")
        response: Response = await call_next(request)
        return response

    @app.exception_handler(SpeechError)
    async def _speech_error(_: Request, exc: SpeechError) -> JSONResponse:
        return _error(400, str(exc), "speech_error")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        ok = len(ready["whisper"]) == len(settings.whisper_preload) and (
            ready["kokoro"] or not settings.kokoro_preload
        )
        return JSONResponse({"status": "ready" if ok else "loading", **ready}, 200 if ok else 503)

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        data = [{"id": f"whisper-{s}", "object": "model"} for s in ("tiny", "base", "small")]
        return {"object": "list", "data": [*data, {"id": "kokoro", "object": "model"}]}

    @app.get("/v1/voices")
    async def list_voices() -> dict[str, Any]:
        voices = await asyncio.to_thread(models.voices)
        return {"voices": voices}

    @app.post("/v1/audio/transcriptions")
    async def transcriptions(
        file: Annotated[UploadFile, File()],
        model: Annotated[str, Form()] = "whisper-1",
        language: Annotated[str | None, Form()] = None,
        prompt: Annotated[str | None, Form()] = None,
        response_format: Annotated[str, Form()] = "json",
    ) -> Response:
        size = whisper_size(model, settings.whisper_default)
        audio = decode_wav(await file.read(), settings.speech_max_audio_s)
        async with stt_slots:
            result = await asyncio.to_thread(
                models.transcribe,
                audio,
                size=size,
                language=language,
                prompt=prompt or SCRIPT_PROMPTS.get((language or "").split("-")[0]),
            )
        headers = {
            "x-voiceos-model-ms": f"{result.elapsed_ms:.1f}",
            "x-voiceos-audio-seconds": f"{result.duration_s:.3f}",
        }
        if response_format == "text":
            return Response(result.text, media_type="text/plain", headers=headers)
        body: dict[str, Any] = {"text": result.text}
        if response_format == "verbose_json":
            body |= {
                "task": "transcribe",
                "language": result.language,
                "duration": result.duration_s,
                "segments": result.segments,
            }
        return JSONResponse(body, headers=headers)

    @app.post("/v1/audio/speech")
    async def speech(body: SpeechRequest) -> Response:
        if len(body.input) > settings.speech_max_chars:
            raise SpeechError(f"Input longer than {settings.speech_max_chars} characters")
        started = time.perf_counter()
        chunks = models.synthesize(body.input, voice=body.voice, speed=body.speed)
        # Synthesize the first sentence before answering, so a bad voice is a clean 400 and
        # the first bytes are real audio.
        await tts_slots.acquire()
        released = False

        def release() -> None:
            # Idempotent: runs from the stream's end and from the background task, which
            # also covers a client that leaves before the body starts.
            nonlocal released
            if not released:
                released = True
                tts_slots.release()

        try:
            first = await asyncio.to_thread(next, chunks, b"")
        except BaseException:
            release()
            raise
        first_ms = (time.perf_counter() - started) * 1000

        async def stream() -> AsyncIterator[bytes]:
            try:
                if body.response_format == "wav":
                    yield wav_header(KOKORO_SAMPLE_RATE)
                yield first
                while True:
                    chunk = await asyncio.to_thread(next, chunks, None)
                    if chunk is None:
                        return
                    yield chunk
            finally:
                release()

        media = "audio/wav" if body.response_format == "wav" else "audio/pcm"
        return StreamingResponse(
            stream(),
            media_type=media,
            headers={
                "x-voiceos-first-chunk-ms": f"{first_ms:.1f}",
                "x-voiceos-sample-rate": str(KOKORO_SAMPLE_RATE),
            },
            background=BackgroundTask(release),
        )

    return app


def main() -> None:
    import uvicorn

    settings = get_speech_settings()
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",  # noqa: S104 the container must listen on all interfaces
        port=8000,
        log_config=None,
        access_log=False,
    )
