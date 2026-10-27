"""Fetch the local speech models into the models volume (``make models``).

Kokoro files are pinned by SHA-256 and fetched from an ordered list of mirrors (the
kokoro-onnx GitHub release first, then Hugging Face where an identical copy exists), so one
host being down or throttled does not block a first run, and a corrupted or substituted file
is refused whichever host served it. ``--mirror`` puts your own copy first. Whisper models
are fetched by faster-whisper from Hugging Face (Systran/faster-whisper-*, MIT) into the
same volume.
Nothing is downloaded at request time.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"


@dataclass(frozen=True)
class Pinned:
    sha256: str
    mirrors: tuple[str, ...]


KOKORO_FILES = {
    # Apache-2.0 weights (hexgrad/Kokoro-82M), int8 ONNX export by kokoro-onnx (MIT).
    "kokoro-v1.0.int8.onnx": Pinned(
        "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c",
        (f"{KOKORO_RELEASE}/kokoro-v1.0.int8.onnx",),
    ),
    "voices-v1.0.bin": Pinned(
        "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
        (
            f"{KOKORO_RELEASE}/voices-v1.0.bin",
            "https://huggingface.co/fastrtc/kokoro-onnx/resolve/main/voices-v1.0.bin",
        ),
    ),
}
# A first run pulls several hundred MB; one dropped connection should not fail `make up`.
ATTEMPTS = 5
# A connection that sends nothing for this long counts as dropped and is retried.
READ_TIMEOUT_S = 60


class DownloadError(Exception):
    pass


def retrying(what: str, fn: Callable[[], object], *, delay_s: float = 2.0) -> None:
    """Run a download, retrying network failures with exponential backoff."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            fn()
            return
        except OSError as exc:  # URLError and ContentTooShortError are OSErrors
            if attempt == ATTEMPTS:
                raise DownloadError(
                    f"{what}: download failed after {ATTEMPTS} attempts ({exc})"
                ) from exc
            wait = delay_s * 2 ** (attempt - 1)
            print(f"{what}: attempt {attempt} failed ({exc}); retrying in {wait:.0f}s")
            time.sleep(wait)


def fetch_resumable(url: str, part: Path) -> None:
    """Download into ``part``, continuing from its current size, so a retry after a
    dropped connection does not start a large file over."""
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    req = urllib.request.Request(url, headers=headers)  # noqa: S310 fixed https URL
    try:
        resp = urllib.request.urlopen(req, timeout=READ_TIMEOUT_S)  # noqa: S310 fixed https URL
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and have:  # nothing left to fetch; the checksum decides
            return
        raise
    # 206: the server honoured the range; anything else is the whole file again.
    with resp, part.open("ab" if resp.status == 206 else "wb") as out:
        for block in iter(lambda: resp.read(1 << 20), b""):
            out.write(block)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_pinned(path: Path, pinned: Pinned, mirrors: list[str]) -> None:
    """Fetch one file from the first mirror that serves the pinned bytes. The bytes are
    identical everywhere, so a partial file from one mirror resumes from the next."""
    if path.exists() and sha256(path) == pinned.sha256:
        print(f"kokoro: {path.name} present")
        return
    part = path.with_suffix(path.suffix + ".part")
    sources = [f"{m.rstrip('/')}/{path.name}" for m in mirrors] + list(pinned.mirrors)
    for url in sources:
        print(f"kokoro: downloading {path.name} from {url.split('/')[2]}")
        try:
            retrying(f"kokoro: {path.name}", functools.partial(fetch_resumable, url, part))
        except DownloadError as exc:
            print(f"{exc}; trying the next mirror")
            continue
        got = sha256(part)
        if got == pinned.sha256:
            part.rename(path)
            return
        print(f"kokoro: {path.name} from {url} has checksum {got}; refusing it")
        part.unlink(missing_ok=True)
    raise SystemExit(
        f"kokoro: no mirror served {path.name} intact; see docs/guides/troubleshooting.md"
    )


def fetch_kokoro(target: Path, mirrors: list[str] | None = None) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for name, pinned in KOKORO_FILES.items():
        fetch_pinned(target / name, pinned, mirrors or [])


def fetch_whisper(target: Path, sizes: list[str]) -> None:
    from faster_whisper.utils import download_model

    for size in sizes:
        print(f"whisper: {size}")
        try:
            retrying(
                f"whisper: {size}", functools.partial(download_model, size, cache_dir=str(target))
            )
        except DownloadError as exc:
            raise SystemExit(str(exc)) from exc


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download VoiceOS local speech models")
    parser.add_argument("--dir", default="./models")
    parser.add_argument("--whisper", default="tiny,base,small", help="comma separated sizes")
    parser.add_argument(
        "--mirror",
        action="append",
        default=[],
        help="base URL holding the Kokoro files, tried before the public hosts (repeatable)",
    )
    args = parser.parse_args(argv)
    root = Path(args.dir)
    fetch_kokoro(root / "kokoro", args.mirror)
    fetch_whisper(root / "whisper", [s for s in args.whisper.split(",") if s])
    print("models ready")


if __name__ == "__main__":
    main(sys.argv[1:])
