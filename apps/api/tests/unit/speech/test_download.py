"""The model downloader survives a dropped connection and gives up cleanly."""

from __future__ import annotations

import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from voiceos.speech import download


def test_a_dropped_download_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(download.time, "sleep", lambda _s: None)
    calls: list[int] = []

    def flaky() -> None:
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.ContentTooShortError("retrieval incomplete", None)

    download.retrying("kokoro: x", flaky)
    assert len(calls) == 3


def test_a_download_that_keeps_failing_stops_with_a_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(download.time, "sleep", lambda _s: None)

    def down() -> None:
        raise urllib.error.URLError("no route")

    with pytest.raises(download.DownloadError, match="after 5 attempts"):
        download.retrying("kokoro: x", down)


def test_an_interrupted_file_resumes_where_it_stopped(tmp_path: Path) -> None:
    """The server sees a range request for the missing tail only."""
    body = bytes(range(256)) * 400
    ranges: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            ranges.append(self.headers.get("Range"))
            start = int((self.headers.get("Range") or "bytes=0-")[6:].rstrip("-"))
            if start >= len(body):
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206 if start else 200)
            self.send_header("Content-Length", str(len(body) - start))
            self.end_headers()
            self.wfile.write(body[start:])

        def log_message(self, *_args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/model"
        part = tmp_path / "model.part"
        part.write_bytes(body[:1000])
        download.fetch_resumable(url, part)
        assert part.read_bytes() == body
        download.fetch_resumable(url, part)  # already complete: a 416, not an error
        assert part.read_bytes() == body
        assert ranges == ["bytes=1000-", f"bytes={len(body)}-"]
    finally:
        server.shutdown()


def test_a_dead_mirror_falls_through_and_a_bad_copy_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Mirrors are tried in order; only bytes matching the pinned digest are kept."""
    good = b"model bytes"
    served = {"https://good.example/f.bin": good, "https://bad.example/f.bin": b"tampered"}
    tried: list[str] = []

    def fake_fetch(url: str, part: Path) -> None:
        tried.append(url)
        if url not in served:
            raise urllib.error.URLError("down")
        part.write_bytes(served[url])

    monkeypatch.setattr(download, "fetch_resumable", fake_fetch)
    monkeypatch.setattr(download.time, "sleep", lambda _s: None)
    pinned = download.Pinned(
        download.hashlib.sha256(good).hexdigest(),
        ("https://dead.example/f.bin", "https://bad.example/f.bin", "https://good.example/f.bin"),
    )
    download.fetch_pinned(tmp_path / "f.bin", pinned, [])
    assert (tmp_path / "f.bin").read_bytes() == good
    assert tried[-2:] == ["https://bad.example/f.bin", "https://good.example/f.bin"]
    assert tried.count("https://dead.example/f.bin") == download.ATTEMPTS

    (tmp_path / "f.bin").unlink()
    with pytest.raises(SystemExit, match="no mirror"):
        download.fetch_pinned(tmp_path / "f.bin", download.Pinned(pinned.sha256, ()), [])


def test_your_own_mirror_is_tried_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tried: list[str] = []

    def fake_fetch(url: str, part: Path) -> None:
        tried.append(url)
        part.write_bytes(b"x")

    monkeypatch.setattr(download, "fetch_resumable", fake_fetch)
    pinned = download.Pinned(download.hashlib.sha256(b"x").hexdigest(), ("https://public/f.bin",))
    download.fetch_pinned(tmp_path / "f.bin", pinned, ["https://mine.example/models/"])
    assert tried == ["https://mine.example/models/f.bin"]
