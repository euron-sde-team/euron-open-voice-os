"""The speech service's HTTP layer and model plumbing, with the two model objects faked.

Real Whisper and Kokoro run in the e2e suite, the demo seed and the benchmark; here the
contract is pinned: audio decoding and limits, the OpenAI-compatible response shapes,
sentence streaming, voices and languages, auth, readiness and the model download checks.
"""

from __future__ import annotations

import hashlib
import io
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import numpy as np
import pytest
from asgi_lifespan import LifespanManager

from voiceos.core.config import SpeechSettings
from voiceos.speech import download
from voiceos.speech.app import create_app, decode_wav, wav_header
from voiceos.speech.models import (
    SpeechError,
    split_sentences,
    to_pcm16,
    voice_language,
    whisper_size,
)


def wav(seconds: float, rate: int = 16_000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return buf.getvalue()


class FakeWhisper:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: np.ndarray, **kw: Any) -> tuple[Any, Any]:
        self.calls.append({"samples": len(audio), **kw})
        segs = [SimpleNamespace(start=0.0, end=0.8, text=" Hello there. ")]
        return iter(segs), SimpleNamespace(language=kw.get("language") or "en")


class FakeKokoro:
    def __init__(self) -> None:
        self.sentences: list[tuple[str, str]] = []

    def get_voices(self) -> list[str]:
        return ["hf_alpha", "af_heart"]

    def create(self, text: str, *, voice: str, speed: float, lang: str) -> tuple[np.ndarray, int]:
        self.sentences.append((text, lang))
        return np.zeros(2400, dtype=np.float32), 24_000


def settings(tmp_path: Path, **kw: Any) -> SpeechSettings:
    values: dict[str, Any] = {
        "speech_models_dir": str(tmp_path),
        "whisper_preload": [],
        "kokoro_preload": False,
        **kw,
    }
    return SpeechSettings(**values)


async def client_for(s: SpeechSettings) -> tuple[httpx.AsyncClient, Any, LifespanManager]:
    app = create_app(s)
    manager = LifespanManager(app)
    await manager.__aenter__()
    models = app.state.models
    models._whisper = {"base": FakeWhisper(), "small": FakeWhisper()}
    models._kokoro = FakeKokoro()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://speech")
    return client, models, manager


@pytest.fixture
async def speech(tmp_path: Path) -> Any:
    client, models, manager = await client_for(settings(tmp_path))
    yield client, models
    await client.aclose()
    await manager.__aexit__(None, None, None)


async def test_transcription_shapes_and_model_choice(speech: Any) -> None:
    client, models = speech
    files = {"file": ("a.wav", wav(1.0, rate=8_000, channels=2), "audio/wav")}
    r = await client.post(
        "/v1/audio/transcriptions", files=files, data={"model": "whisper-small", "language": "hi"}
    )
    assert r.status_code == 200
    assert r.json() == {"text": "Hello there."}
    assert float(r.headers["x-voiceos-audio-seconds"]) == pytest.approx(1.0, abs=0.01)
    call = models._whisper["small"].calls[0]
    assert call["language"] == "hi" and call["samples"] == 16_000  # resampled to 16 kHz mono
    assert call["initial_prompt"].startswith("नमस्ते")  # steers Whisper to Devanagari

    r = await client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", wav(0.5), "audio/wav")},
        data={"response_format": "verbose_json"},
    )
    body = r.json()
    assert body["task"] == "transcribe" and body["segments"][0]["text"] == "Hello there."
    assert models._whisper["base"].calls[-1]["initial_prompt"] is None  # English: no prompt
    r = await client.post(
        "/v1/audio/transcriptions",
        files={"file": ("a.wav", wav(0.5), "audio/wav")},
        data={"response_format": "text"},
    )
    assert r.text == "Hello there." and r.headers["content-type"].startswith("text/plain")


async def test_bad_audio_and_models_are_clean_400s(speech: Any) -> None:
    client, _ = speech
    cases = [
        ({"file": ("a.wav", b"not audio", "audio/wav")}, {}, "Send WAV audio"),
        ({"file": ("a.wav", wav(0.5, width=1), "audio/wav")}, {}, "Send WAV audio"),
        ({"file": ("a.wav", wav(61.0, rate=8_000), "audio/wav")}, {}, "longer than"),
        ({"file": ("a.wav", wav(0.5), "audio/wav")}, {"model": "whisper-huge"}, "Unknown Whisper"),
    ]
    for files, data, fragment in cases:
        r = await client.post("/v1/audio/transcriptions", files=files, data=data)
        assert r.status_code == 400, r.text
        assert fragment in r.json()["error"]["message"]
        assert r.json()["error"]["code"] == "speech_error"


async def test_speech_streams_pcm_or_wav_one_sentence_at_a_time(speech: Any) -> None:
    client, models = speech
    r = await client.post(
        "/v1/audio/speech", json={"input": "Hello. How are you?", "voice": "af_heart"}
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("audio/pcm")
    assert len(r.content) == 2 * 2400 * 2  # two sentences of 2400 samples, 16-bit
    assert [s for s, _ in models._kokoro.sentences] == ["Hello.", "How are you?"]

    r = await client.post(
        "/v1/audio/speech",
        json={"input": "Namaste.", "voice": "hf_alpha", "response_format": "wav"},
    )
    assert r.content[:4] == b"RIFF" and r.content[8:12] == b"WAVE"
    assert models._kokoro.sentences[-1] == ("Namaste.", "hi")

    for body, fragment in (
        ({"input": "Hi.", "voice": "zz_nobody"}, "Unknown voice"),
        ({"input": "Hi.", "voice": "am_nobody"}, "Unknown voice"),
    ):
        r = await client.post("/v1/audio/speech", json=body)
        assert r.status_code == 400 and fragment in r.json()["error"]["message"]
    r = await client.post("/v1/audio/speech", json={"input": "", "voice": "af_heart"})
    assert r.status_code == 422


async def test_listing_health_and_readiness(speech: Any) -> None:
    client, _ = speech
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    ready = await client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["status"] == "ready"
    ids = [m["id"] for m in (await client.get("/v1/models")).json()["data"]]
    assert ids == ["whisper-tiny", "whisper-base", "whisper-small", "kokoro"]
    assert (await client.get("/v1/voices")).json() == {"voices": ["af_heart", "hf_alpha"]}


async def test_an_api_key_guards_everything_but_probes(tmp_path: Path) -> None:
    client, _, manager = await client_for(settings(tmp_path, speech_api_key="s3cret-speech-key"))
    try:
        assert (await client.get("/v1/models")).status_code == 401
        assert (await client.get("/healthz")).status_code == 200
        ok = await client.get("/v1/models", headers={"authorization": "Bearer s3cret-speech-key"})
        assert ok.status_code == 200
    finally:
        await client.aclose()
        await manager.__aexit__(None, None, None)


async def test_missing_kokoro_files_say_how_to_fix_it(tmp_path: Path) -> None:
    app = create_app(settings(tmp_path))
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://s") as c,
    ):
        r = await c.post("/v1/audio/speech", json={"input": "Hi.", "voice": "af_heart"})
    assert r.status_code == 400 and "make models" in r.json()["error"]["message"]


def test_helpers() -> None:
    assert whisper_size("whisper-1", "base") == "base"
    assert whisper_size("faster-whisper-small", "base") == "small"
    assert voice_language("hf_alpha") == "hi" and voice_language("af_heart") == "en-us"
    with pytest.raises(SpeechError):
        voice_language("x")
    long = "word " * 100 + ", and then " + "more " * 80
    parts = split_sentences(long.strip() + ". Done.", max_chars=120)
    assert all(len(p) <= 121 for p in parts) and parts[-1] == "Done."
    assert to_pcm16(np.array([2.0, -2.0, 0.0], dtype=np.float32)) == b"\xff\x7f\x01\x80\x00\x00"
    assert wav_header(24_000, 0)[:4] == b"RIFF"
    assert len(decode_wav(wav(0.25, rate=48_000), 5)) == 4000
    # 32-bit float WAV (FLEURS ships these), written by hand: format tag 3.
    floats = np.linspace(-0.5, 0.5, 1600, dtype="<f4").tobytes()
    header = b"RIFF" + (36 + len(floats)).to_bytes(4, "little") + b"WAVEfmt "
    header += (16).to_bytes(4, "little") + (3).to_bytes(2, "little") + (1).to_bytes(2, "little")
    header += (16_000).to_bytes(4, "little") + (64_000).to_bytes(4, "little")
    header += (4).to_bytes(2, "little") + (32).to_bytes(2, "little")
    decoded = decode_wav(header + b"data" + len(floats).to_bytes(4, "little") + floats, 5)
    assert decoded.dtype == np.float32 and len(decoded) == 1600
    assert decoded[0] == pytest.approx(-0.5)


def test_kokoro_download_is_checksum_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = b"model bytes"
    monkeypatch.setattr(download, "KOKORO_FILES", {"m.onnx": hashlib.sha256(good).hexdigest()})
    fetched: list[str] = []

    def fake_fetch(url: str, path: Path) -> None:
        fetched.append(url)
        Path(path).write_bytes(good)

    monkeypatch.setattr(download.urllib.request, "urlretrieve", fake_fetch)
    download.fetch_kokoro(tmp_path)
    assert (tmp_path / "m.onnx").read_bytes() == good
    download.fetch_kokoro(tmp_path)  # present and verified: no second download
    assert len(fetched) == 1

    monkeypatch.setattr(download, "KOKORO_FILES", {"bad.onnx": "0" * 64})
    with pytest.raises(SystemExit, match="checksum mismatch"):
        download.fetch_kokoro(tmp_path)
    assert not (tmp_path / "bad.onnx").exists() and not (tmp_path / "bad.onnx.part").exists()
