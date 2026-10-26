#!/usr/bin/env python3
"""Regenerate the committed test utterances with the local Kokoro voice.

The latency benchmark, the demo seed and the e2e fake microphone all play these files, so
every run hears exactly the same audio. They are synthesized speech (Kokoro-82M, Apache-2.0
weights), not recordings of people.

    python3 scripts/gen-utterances.py [SPEECH_URL]    default http://localhost:4537

Standard library only; needs the speech service running (make up starts it).
"""

from __future__ import annotations

import json
import struct
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "apps/api/src/voiceos/benchmarks/audio"
E2E = ROOT / "e2e/audio"
RATE = 24_000

# (file, voice, text). The voice prefix picks the language (a = US English, h = Hindi).
UTTERANCES = [
    (BENCH / "en-01-booking.wav", "af_heart", "Hello, I would like to book a table for two tonight."),
    (BENCH / "en-02-hours.wav", "am_michael", "What time do you open on Sunday?"),
    (BENCH / "en-03-order.wav", "af_bella", "Can you tell me where my order is?"),
    (BENCH / "hi-01-booking.wav", "hf_alpha", "नमस्ते, मुझे आज रात दो लोगों के लिए टेबल बुक करनी है।"),
    (BENCH / "hi-02-hours.wav", "hm_omega", "आप रविवार को कितने बजे खुलते हैं?"),
]
# Chromium loops its fake microphone file, so the e2e clip ends in a long silence that
# lets the turn end and the agent answer before the question repeats.
E2E_CLIP = (E2E / "en-booking.wav", "af_heart", "Hello, I would like to book a table for two tonight.")


def synthesize(url: str, voice: str, text: str) -> bytes:
    body = json.dumps({"input": text, "voice": voice, "response_format": "pcm"}).encode()
    req = urllib.request.Request(
        f"{url}/v1/audio/speech", data=body, headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310 (local service)
        return bytes(resp.read())


def write_wav(path: Path, pcm: bytes, lead_s: float, tail_s: float) -> None:
    data = b"\0\0" * int(RATE * lead_s) + pcm + b"\0\0" * int(RATE * tail_s)
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(data))
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + data)
    print(f"{path.relative_to(ROOT)}  {len(data) / 2 / RATE:.2f} s")


def main() -> None:
    url = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:4537").rstrip("/")
    for path, voice, text in UTTERANCES:
        write_wav(path, synthesize(url, voice, text), lead_s=0.3, tail_s=0.3)
    path, voice, text = E2E_CLIP
    write_wav(path, synthesize(url, voice, text), lead_s=0.5, tail_s=4.0)


if __name__ == "__main__":
    main()
