"""The model downloader survives a dropped connection and gives up cleanly."""

from __future__ import annotations

import urllib.error

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

    with pytest.raises(SystemExit, match="after 5 attempts"):
        download.retrying("kokoro: x", down)
