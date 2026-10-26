"""Benchmark runs: queued from the dashboard, executed by the worker, kept with a report.

Only one run is queued or running at a time (a partial unique index). The worker issues
its own session tokens (it shares the runtime token secret), talks to the runtime over the
private network, then reads the sessions the runtime reported to compute the results.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from voiceos.agents import service as agents
from voiceos.audit.service import Actor, audit
from voiceos.benchmarks.models import BenchmarkRun
from voiceos.benchmarks.schemas import BenchmarkIn, BenchmarkOut
from voiceos.core.container import Container
from voiceos.core.errors import AppError, ConflictError, NotFoundError
from voiceos.core.tokens import issue
from voiceos.sessions.models import SessionTurn, VoiceSession

log = logging.getLogger("voiceos.benchmarks")
STALE_AFTER = timedelta(minutes=30)


def to_out(r: BenchmarkRun) -> BenchmarkOut:
    return BenchmarkOut.model_validate(r, from_attributes=True)


async def list_runs(session: AsyncSession, limit: int) -> list[BenchmarkOut]:
    rows = await session.scalars(
        select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc()).limit(limit)
    )
    return [to_out(r) for r in rows]


async def get(session: AsyncSession, run_id: uuid.UUID) -> BenchmarkRun:
    row = await session.get(BenchmarkRun, run_id)
    if row is None:
        raise NotFoundError("Benchmark run not found")
    return row


async def queue(session: AsyncSession, data: BenchmarkIn, actor: Actor) -> BenchmarkOut:
    missing = await agents.missing(session, [str(a) for a in data.agent_ids])
    if missing:
        raise AppError(f"No agent with id {missing[0]}", code="unknown_agent")
    await session.execute(
        update(BenchmarkRun)
        .where(
            BenchmarkRun.status == "running",
            func.coalesce(BenchmarkRun.started_at, BenchmarkRun.created_at)
            < datetime.now(UTC) - STALE_AFTER,
        )
        .values(
            status="failed",
            error="The worker stopped during this run",
            finished_at=datetime.now(UTC),
        )
    )
    row = BenchmarkRun(
        id=uuid.uuid4(),
        kind=data.kind,
        requested_by=actor.id,
        config={"agent_ids": [str(a) for a in data.agent_ids], "sessions": data.sessions},
    )
    session.add(row)
    audit(session, actor, "benchmark.queued", "benchmark", row.id, kind=data.kind)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            "A benchmark is already queued or running", code="benchmark_running"
        ) from exc
    await session.refresh(row)
    return to_out(row)


async def claim(container: Container) -> BenchmarkRun | None:
    async with container.db.sessionmaker() as session:
        row = await session.scalar(
            select(BenchmarkRun)
            .where(BenchmarkRun.status == "queued")
            .order_by(BenchmarkRun.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return None
        row.status = "running"
        row.started_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(row)
        return row


async def run_once(container: Container) -> bool:
    row = await claim(container)
    if row is None:
        return False
    await execute(container, row)
    return True


async def execute(container: Container, row: BenchmarkRun) -> None:
    from voiceos.benchmarks import latency

    values: dict[str, Any]
    try:
        results: dict[str, Any] = {"agents": {}}
        base = container.settings.runtime_internal_url.rstrip("/")
        ws = (
            "ws://" + base.removeprefix("http://")
            if base.startswith("http://")
            else ("wss://" + base.removeprefix("https://"))
        )
        for agent_id in row.config.get("agent_ids", []):
            agent = await agents.resolve(container, agent_id)
            if agent is None:
                results["agents"][agent_id] = {"error": "agent missing or disabled"}
                continue
            files = latency.utterances(agent.language)
            jobs = [
                _one_session(container, ws, agent_id, row.id, files[i % len(files)])
                for i in range(int(row.config.get("sessions", 3)))
            ]
            outcomes = await latency.gather(jobs, concurrency=1)
            session_ids = [sid for sid, _ in outcomes]
            client_ms = [ms for _, ms in outcomes if ms is not None]
            await asyncio.sleep(2)  # let the runtime file its reports
            turns = await _turns(container, session_ids)
            results["agents"][agent_id] = {
                "name": agent.name,
                "language": agent.language,
                "providers": {
                    "stt": agent.stt.name + (f" ({agent.stt.model})" if agent.stt.model else ""),
                    "llm": agent.llm.name + (f" ({agent.llm.model})" if agent.llm.model else ""),
                    "tts": agent.tts.name + (f" ({agent.tts.voice})" if agent.tts.voice else ""),
                },
                "sessions": len(session_ids),
                **latency.summarize(turns, client_ms),
            }
        values = {"status": "succeeded", "results": results, "hardware": latency.hardware()}
    except Exception as exc:
        log.exception("benchmark failed", extra={"run_id": str(row.id)})
        values = {
            "status": "failed",
            "error": f"The benchmark failed on the worker ({type(exc).__name__})",
        }
    async with container.db.sessionmaker() as session:
        result = await session.execute(
            update(BenchmarkRun)
            .where(
                BenchmarkRun.id == row.id,
                BenchmarkRun.status == "running",
                BenchmarkRun.started_at == row.started_at,
            )
            .values(**values, finished_at=datetime.now(UTC))
        )
        await session.commit()
    if not getattr(result, "rowcount", 0):
        log.warning(
            "benchmark result discarded: run was marked stale", extra={"run_id": str(row.id)}
        )


async def _one_session(
    container: Container, ws: str, agent_id: str, run_id: uuid.UUID, file: Any
) -> tuple[str, float | None]:
    """One benchmark conversation: (session id, client-perceived first audio in ms)."""
    # Imported here: it needs Pipecat's frame format, which only the worker image installs.
    from voiceos.benchmarks import latency

    token, claims = issue(
        agent_id, container.settings.runtime_token_secret, subject=f"benchmark:{run_id}"
    )
    convo = await latency.converse_once(f"{ws}/ws?token={token}", file)
    return claims.session_id, convo.client_first_audio_ms


async def _turns(container: Container, session_ids: list[str]) -> list[dict[str, Any]]:
    ids = [uuid.UUID(s) for s in session_ids]
    async with container.db.sessionmaker() as session:
        rows = await session.execute(
            select(SessionTurn)
            .join(VoiceSession, VoiceSession.id == SessionTurn.session_id)
            .where(
                SessionTurn.session_id.in_(ids),
                SessionTurn.user_text.is_not(None) | SessionTurn.response_ms.is_not(None),
            )
        )
        return [
            {
                "response_ms": t.response_ms,
                "endpoint_ms": t.endpoint_ms,
                "stt_ms": t.stt_ms,
                "llm_first_token_ms": t.llm_first_token_ms,
                "tts_first_audio_ms": t.tts_first_audio_ms,
            }
            for (t,) in rows.all()
            if t.response_ms is not None
        ]
