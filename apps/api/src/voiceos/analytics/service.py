"""The overview: conversations, minutes, latency, cost and savings over a period.

Totals and series come from ``usage_hourly``. Latency percentiles and the per-stage
breakdown come from the period's turns (``percentile_cont`` in Postgres, one query), so
p95 is a real percentile rather than an average of averages.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceos.analytics.models import UsageHourly
from voiceos.analytics.schemas import AgentBreakdown, Overview, Point, StageLatency
from voiceos.core.money import nusd_to_usd
from voiceos.sessions.models import SessionTurn, VoiceSession

U = UsageHourly


async def overview(session: AsyncSession, days: int, now: datetime | None = None) -> Overview:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    prev_since = since - timedelta(days=days)

    async def totals(start: datetime, end: datetime) -> dict[str, Any]:
        row = (
            await session.execute(
                select(
                    func.coalesce(func.sum(U.sessions), 0),
                    func.coalesce(func.sum(U.turns), 0),
                    func.coalesce(func.sum(U.duration_s), 0.0),
                    func.coalesce(func.sum(U.interruptions), 0),
                    func.coalesce(func.sum(U.errors), 0),
                    func.coalesce(func.sum(U.cost_nusd), 0),
                    func.coalesce(func.sum(U.costed_sessions), 0),
                    func.coalesce(func.sum(U.savings_nusd), 0),
                    func.coalesce(func.sum(U.response_ms_sum), 0.0),
                    func.coalesce(func.sum(U.response_count), 0),
                    func.coalesce(func.sum(U.external_sessions), 0),
                    func.coalesce(func.sum(U.llm_input_tokens + U.llm_output_tokens), 0),
                    func.coalesce(func.sum(U.tts_characters_cached), 0),
                    func.coalesce(func.sum(U.response_cache_hits), 0),
                ).where(U.hour >= start, U.hour < end)
            )
        ).one()
        keys = [
            "sessions",
            "turns",
            "duration_s",
            "interruptions",
            "errors",
            "cost_nusd",
            "costed",
            "savings_nusd",
            "rsum",
            "rcount",
            "external",
            "tokens",
            "tts_cached",
            "cache_hits",
        ]
        return dict(zip(keys, row, strict=True))

    cur, prev = await totals(since, now), await totals(prev_since, since)

    pct = (
        await session.execute(
            select(
                func.percentile_cont(0.5).within_group(SessionTurn.response_ms),
                func.percentile_cont(0.95).within_group(SessionTurn.response_ms),
                func.avg(SessionTurn.endpoint_ms),
                func.avg(SessionTurn.stt_ms),
                func.avg(SessionTurn.llm_first_token_ms),
                func.avg(SessionTurn.tts_first_audio_ms),
            )
            .join(VoiceSession, VoiceSession.id == SessionTurn.session_id)
            .where(VoiceSession.started_at >= since, SessionTurn.response_ms.is_not(None))
        )
    ).one()

    bucket = "hour" if days <= 2 else "day"
    series_rows = (
        await session.execute(
            select(
                func.date_trunc(bucket, U.hour).label("b"),
                func.sum(U.sessions),
                func.sum(U.duration_s),
                func.sum(U.response_ms_sum),
                func.sum(U.response_count),
                func.sum(U.cost_nusd),
            )
            .where(U.hour >= since)
            .group_by("b")
            .order_by("b")
        )
    ).all()
    agent_rows = (
        await session.execute(
            select(
                U.agent_key,
                func.max(U.agent_name),
                func.sum(U.sessions),
                func.sum(U.duration_s),
                func.sum(U.response_ms_sum),
                func.sum(U.response_count),
                func.sum(U.cost_nusd),
                func.sum(U.costed_sessions),
            )
            .where(U.hour >= since)
            .group_by(U.agent_key)
            .order_by(func.sum(U.sessions).desc())
            .limit(20)
        )
    ).all()

    def avg(sum_: float, n: int) -> float | None:
        return round(sum_ / n, 1) if n else None

    def r(v: Any) -> float | None:
        return round(float(v), 1) if v is not None else None

    return Overview(
        days=days,
        sessions=int(cur["sessions"]),
        minutes=round(float(cur["duration_s"]) / 60, 1),
        turns=int(cur["turns"]),
        interruption_rate=round(cur["interruptions"] / cur["turns"], 4) if cur["turns"] else 0.0,
        error_sessions=int(cur["errors"]),
        external_sessions=int(cur["external"]),
        response_ms_avg=avg(float(cur["rsum"]), int(cur["rcount"])),
        response_ms_p50=r(pct[0]),
        response_ms_p95=r(pct[1]),
        stages=StageLatency(
            endpoint_ms=r(pct[2]),
            stt_ms=r(pct[3]),
            llm_first_token_ms=r(pct[4]),
            tts_first_audio_ms=r(pct[5]),
        ),
        cost_usd=round(nusd_to_usd(int(cur["cost_nusd"])), 6),
        costed_sessions=int(cur["costed"]),
        cost_per_session_usd=(
            round(nusd_to_usd(int(cur["cost_nusd"])) / cur["costed"], 6) if cur["costed"] else None
        ),
        savings_usd=round(nusd_to_usd(int(cur["savings_nusd"])), 6),
        llm_tokens=int(cur["tokens"]),
        tts_characters_cached=int(cur["tts_cached"]),
        response_cache_hits=int(cur["cache_hits"]),
        previous={
            "sessions": float(prev["sessions"]),
            "minutes": round(float(prev["duration_s"]) / 60, 1),
            "response_ms_avg": avg(float(prev["rsum"]), int(prev["rcount"])) or 0.0,
            "cost_usd": round(nusd_to_usd(int(prev["cost_nusd"])), 6),
        },
        series=[
            Point(
                t=row[0],
                sessions=int(row[1] or 0),
                minutes=round(float(row[2] or 0) / 60, 2),
                response_ms_avg=avg(float(row[3] or 0), int(row[4] or 0)),
                cost_usd=round(nusd_to_usd(int(row[5] or 0)), 6),
            )
            for row in series_rows
        ],
        by_agent=[
            AgentBreakdown(
                agent_key=row[0],
                agent_name=row[1],
                sessions=int(row[2] or 0),
                minutes=round(float(row[3] or 0) / 60, 1),
                response_ms_avg=avg(float(row[4] or 0), int(row[5] or 0)),
                cost_per_session_usd=(
                    round(nusd_to_usd(int(row[6] or 0)) / int(row[7]), 6) if row[7] else None
                ),
            )
            for row in agent_rows
        ],
    )
