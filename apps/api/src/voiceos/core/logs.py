"""Structured JSON logging with a per-request id carried in a context variable."""

from __future__ import annotations

import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

import orjson

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}
# Never write credentials to logs, whatever a caller puts in `extra`.
_TOKEN_IN_URL = re.compile(r"((?:^|[?&\s])token=)[^&\s\"']+")
_REDACT = {"authorization", "api_key", "password", "secret", "token", "x-api-key"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            # Session tokens travel in WebSocket URLs (?token=...); never log one.
            "msg": _TOKEN_IN_URL.sub(r"\1[redacted]", record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = "[redacted]" if key.lower() in _REDACT else value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return orjson.dumps(payload, default=str).decode()


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "botocore", "urllib3", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _route_loguru()


# Pipecat logs through loguru, at DEBUG by default: the whole LLM context every turn and
# every sentence it speaks. Those are the caller's words, which retention, redaction and
# erasure govern, so they must never reach a log. Loguru is sent through the JSON logger
# with a WARNING floor (no conversation text is logged below it), and its messages are
# redacted as a second line of defence.
PIPECAT_LOG_FLOOR = logging.WARNING


def _route_loguru() -> None:
    try:
        from loguru import logger as loguru_logger
    except ImportError:  # the control plane image does not install Pipecat
        return
    from voiceos.privacy.redact import redact

    target = logging.getLogger("pipecat")

    def sink(message: object) -> None:
        record = message.record  # type: ignore[attr-defined]
        text = redact(str(record["message"])) or ""
        target.log(record["level"].no, text)

    loguru_logger.remove()
    loguru_logger.add(sink, level=PIPECAT_LOG_FLOOR, format="{message}")
