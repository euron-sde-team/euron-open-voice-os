"""Fetch the local speech models into the models volume (``make models``).

Kokoro files come from the kokoro-onnx release and are checked against pinned SHA-256
digests, so a corrupted or substituted file is refused. Whisper models are fetched by
faster-whisper from Hugging Face (Systran/faster-whisper-*, MIT) into the same volume.
Nothing is downloaded at request time.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
KOKORO_FILES = {
    # Apache-2.0 weights (hexgrad/Kokoro-82M), int8 ONNX export by kokoro-onnx (MIT).
    "kokoro-v1.0.int8.onnx": "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_kokoro(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name, digest in KOKORO_FILES.items():
        path = target / name
        if path.exists() and sha256(path) == digest:
            print(f"kokoro: {name} present")
            continue
        part = path.with_suffix(path.suffix + ".part")
        print(f"kokoro: downloading {name}")
        urllib.request.urlretrieve(f"{KOKORO_RELEASE}/{name}", part)  # noqa: S310 fixed https URL
        got = sha256(part)
        if got != digest:
            part.unlink(missing_ok=True)
            raise SystemExit(f"kokoro: {name} checksum mismatch ({got}); refusing it")
        part.rename(path)


def fetch_whisper(target: Path, sizes: list[str]) -> None:
    from faster_whisper.utils import download_model

    for size in sizes:
        print(f"whisper: {size}")
        download_model(size, cache_dir=str(target))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download VoiceOS local speech models")
    parser.add_argument("--dir", default="./models")
    parser.add_argument("--whisper", default="tiny,base,small", help="comma separated sizes")
    args = parser.parse_args(argv)
    root = Path(args.dir)
    fetch_kokoro(root / "kokoro")
    fetch_whisper(root / "whisper", [s for s in args.whisper.split(",") if s])
    print("models ready")


if __name__ == "__main__":
    main(sys.argv[1:])
