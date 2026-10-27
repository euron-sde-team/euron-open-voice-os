"""Pipecat's own logging (loguru) never writes the caller's words."""

from __future__ import annotations

import pytest

pytest.importorskip("loguru")

from loguru import logger

from voiceos.core.logs import configure_logging


def test_conversation_text_is_never_logged(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG")
    logger.debug("Generating TTS [Your card 4111 1111 1111 1111 is booked]")
    logger.info("LLM context: my email is priya@example.com")
    logger.warning("TTS failed for priya@example.com")
    out = capsys.readouterr().out
    assert "4111" not in out and "Generating TTS" not in out
    assert "LLM context" not in out
    assert '"logger":"pipecat"' in out and "[email]" in out and "priya@" not in out
