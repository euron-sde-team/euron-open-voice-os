"""Background worker: transcript retention and benchmark runs.

Stateless and safe to run as several replicas: the purge works in bounded batches with
plain UPDATEs (idempotent), and benchmark runs are claimed with ``FOR UPDATE SKIP LOCKED``.
SIGTERM finishes the item in hand, then exits. Prometheus metrics on WORKER_METRICS_PORT.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from prometheus_client import start_http_server

from voiceos.core.config import get_settings
from voiceos.core.container import Container
from voiceos.core.db import import_all_models
from voiceos.core.logs import configure_logging
from voiceos.sessions import service as sessions

log = logging.getLogger("voiceos.worker")


async def tick(container: Container) -> bool:
    """One pass. True when anything was done (so the loop runs again at once)."""
    async with container.db.sessionmaker() as session:
        purged = await sessions.purge_expired(session)
        await sessions.purge_claims(session)
    if purged:
        log.info("transcripts purged", extra={"sessions": purged})
    from voiceos.benchmarks import service as benchmarks

    ran = await benchmarks.run_once(container)
    return bool(purged) or ran


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    import_all_models()
    if settings.worker_metrics_port:
        start_http_server(settings.worker_metrics_port)
    container = Container.build(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log.info("worker started")
    try:
        while not stop.is_set():
            try:
                busy = await tick(container)
            except Exception:
                log.exception("worker tick failed")
                busy = False
            if not busy:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_interval_s)
    finally:
        await container.close()
        log.info("worker stopped")
