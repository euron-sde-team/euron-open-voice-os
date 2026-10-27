"""Sessions: start tickets, report ingestion, history, retention.

Start: a dashboard user or an SDK key asks for a session with an agent and gets a ticket
(a one-minute token for exactly one session, the runtime URLs, and the disclosure of any
external provider), so a client can tell its user before audio leaves the device.

Ingest: the runtime reports each finished session once. The session row, its turns (text
redacted and kept only if the agent's retention allows) and the hourly rollup are written
in one transaction; a repeated report for the same session id changes nothing.
"""

from __future__ import annotations

import statistics
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from voiceos.agents import service as agents
from voiceos.analytics.models import UsageHourly
from voiceos.core.container import Container
from voiceos.core.contract import ResolvedAgent, SessionReport
from voiceos.core.errors import AppError, NotFoundError, PermissionDeniedError
from voiceos.core.money import nusd_to_usd
from voiceos.core.schemas import decode_cursor, encode_cursor
from voiceos.core.tokens import TTL, issue
from voiceos.observability import metrics
from voiceos.privacy.redact import redact
from voiceos.sessions.cost import session_cost
from voiceos.sessions.models import SessionTurn, VoiceSession
from voiceos.sessions.schemas import (
    Disclosure,
    SessionDetail,
    SessionOut,
    SessionTicket,
    TurnOut,
)


def disclosure(agent: ResolvedAgent) -> Disclosure:
    external = agent.external_providers()
    if not external:
        return Disclosure(
            external=False,
            providers=[],
            message="Audio and transcripts stay on this deployment's own servers.",
        )
    return Disclosure(
        external=True,
        providers=external,
        message=(
            "This assistant sends your audio or its transcript to "
            + ", ".join(external)
            + " to understand and answer you."
        ),
    )


async def start(
    container: Container,
    agent_id: uuid.UUID,
    *,
    subject: str,
    origin: str | None,
    allowed_agents: tuple[str, ...] = (),
    allowed_origins: tuple[str, ...] = (),
) -> SessionTicket:
    if allowed_agents and str(agent_id) not in allowed_agents:
        raise PermissionDeniedError("This key may not start that agent", code="agent_not_allowed")
    if allowed_origins and origin not in allowed_origins:
        raise PermissionDeniedError(
            "This key only starts sessions from its allowed origins", code="origin_not_allowed"
        )
    agent = await agents.resolve(container, str(agent_id))
    if agent is None:
        raise NotFoundError("Agent not found or disabled")
    metrics.SESSIONS_STARTED.labels("sdk" if subject.startswith("key:") else "dashboard").inc()
    token, claims = issue(
        str(agent_id), container.settings.runtime_token_secret, subject=subject, origin=origin
    )
    base = container.settings.runtime_public_url.rstrip("/")
    ws_base = (
        "wss://" + base.removeprefix("https://")
        if base.startswith("https://")
        else ("ws://" + base.removeprefix("http://"))
    )
    return SessionTicket(
        session_id=uuid.UUID(claims.session_id),
        token=token,
        expires_in_s=int(TTL.total_seconds()),
        websocket_url=f"{ws_base}/ws?token={token}",
        offer_url=f"{base}/api/offer?token={token}",
        ice_url=f"{base}/api/ice?token={token}",
        agent={"id": str(agent_id), "name": agent.name, "language": agent.language},
        disclosure=disclosure(agent),
    )


def _p50(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


async def ingest(session: AsyncSession, container: Container, report: SessionReport) -> bool:
    """Store a finished session. False when this session was already stored."""
    sid = uuid.UUID(report.session_id)
    if await session.get(VoiceSession, sid) is not None:
        return False
    # The configuration the call ran with; older runtimes did not send it.
    agent = report.agent or await agents.resolve(container, report.agent_id)
    privacy = agent.privacy if agent else None
    keep_days = privacy.transcript_retention_days if privacy else 0
    scrub = privacy.redact_pii if privacy else True
    responses = [t.response_ms for t in report.turns if t.response_ms is not None]
    cost = session_cost(agent, report)
    try:
        agent_uuid: uuid.UUID | None = uuid.UUID(report.agent_id)
    except ValueError:
        agent_uuid = None
    if agent_uuid is not None and await agents_exists(session, agent_uuid) is False:
        agent_uuid = None
    duration = max(0.0, (report.ended_at - report.started_at).total_seconds())
    row = VoiceSession(
        id=sid,
        agent_id=agent_uuid,
        agent_name=(agent.name if agent else "Deleted agent")[:120],
        agent_version=report.agent_version,
        transport=report.transport,
        subject=report.subject[:80],
        origin=(report.origin or None) and report.origin[:200],
        started_at=report.started_at,
        ended_at=report.ended_at,
        duration_s=round(duration, 3),
        end_reason=report.end_reason,
        external_providers=report.external_providers,
        turn_count=len(report.turns),
        interruptions=sum(1 for t in report.turns if t.interrupted),
        response_ms_p50=_p50(responses),
        response_ms_max=max(responses) if responses else None,
        usage={
            **report.usage.model_dump(),
            # Which stages ran on your own servers, so a zero cost reads as self-hosted.
            "self_hosted_stages": [
                stage
                for stage, p in (("stt", agent.stt), ("llm", agent.llm), ("tts", agent.tts))
                if p.self_hosted
            ]
            if agent
            else [],
        },
        cost_stt_nusd=cost.stt,
        cost_llm_nusd=cost.llm,
        cost_tts_nusd=cost.tts,
        cost_total_nusd=cost.total,
        cost_status=cost.status,
        savings_nusd=cost.savings,
        # Provider errors can echo what the caller said: redact them like the transcript.
        errors=[redact(e[:300]) or "" for e in report.errors[:20]],
        transcript_stored=keep_days > 0,
        transcript_expires_at=report.ended_at + timedelta(days=keep_days) if keep_days else None,
    )
    session.add(row)
    # The session row first: turns reference it, and without a mapped relationship the unit
    # of work does not order the two inserts by their foreign key.
    await session.flush()
    for t in report.turns:
        user, said = (t.user_text, t.agent_text) if keep_days else (None, None)
        if scrub:
            user, said = redact(user), redact(said)
        session.add(
            SessionTurn(
                session_id=sid,
                idx=t.index,
                started_at=t.started_at,
                user_text=user,
                agent_text=said,
                interrupted=t.interrupted,
                user_speech_ms=t.user_speech_ms,
                endpoint_ms=t.endpoint_ms,
                stt_ms=t.stt_ms,
                llm_first_token_ms=t.llm_first_token_ms,
                tts_first_audio_ms=t.tts_first_audio_ms,
                response_ms=t.response_ms,
                llm_model=t.llm_model,
                llm_routed_small=t.llm_routed_small,
                response_cache_hit=t.response_cache_hit,
                error=(t.error or None) and redact(t.error[:300]),
            )
        )
    await session.flush()
    await _rollup(session, row, report, responses)
    await session.commit()
    metrics.SESSIONS_REPORTED.labels(report.end_reason, report.transport).inc()
    return True


async def agents_exists(session: AsyncSession, agent_id: uuid.UUID) -> bool:
    from voiceos.agents.models import Agent

    return await session.get(Agent, agent_id) is not None


async def _rollup(
    session: AsyncSession, row: VoiceSession, report: SessionReport, responses: list[float]
) -> None:
    u = report.usage
    values = {
        "hour": row.started_at.replace(minute=0, second=0, microsecond=0),
        "agent_key": str(row.agent_id) if row.agent_id else "deleted",
        "transport": row.transport,
        "agent_name": row.agent_name,
        "sessions": 1,
        "turns": row.turn_count,
        "interruptions": row.interruptions,
        "errors": 1 if row.errors else 0,
        "duration_s": row.duration_s,
        "stt_audio_seconds": u.stt_audio_seconds,
        "llm_input_tokens": u.llm_input_tokens,
        "llm_output_tokens": u.llm_output_tokens,
        "tts_characters": u.tts_characters,
        "tts_characters_cached": u.tts_characters_cached,
        "response_cache_hits": u.response_cache_hits,
        "response_ms_sum": sum(responses),
        "response_count": len(responses),
        "cost_nusd": row.cost_total_nusd or 0,
        "costed_sessions": 1 if row.cost_total_nusd is not None else 0,
        "savings_nusd": row.savings_nusd,
        "external_sessions": 1 if row.external_providers else 0,
    }
    stmt = insert(UsageHourly).values(**values)
    t = UsageHourly.__table__.c
    additive = [k for k in values if k not in ("hour", "agent_key", "transport", "agent_name")]
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["hour", "agent_key", "transport"],
            set_={
                "agent_name": stmt.excluded.agent_name,
                **{k: t[k] + stmt.excluded[k] for k in additive},
            },
        )
    )


def _usd(nusd: int | None) -> float | None:
    return round(nusd_to_usd(nusd), 6) if nusd is not None else None


def to_out(r: VoiceSession) -> SessionOut:
    return SessionOut(
        id=r.id,
        agent_id=r.agent_id,
        agent_name=r.agent_name,
        agent_version=r.agent_version,
        transport=r.transport,
        subject=r.subject,
        started_at=r.started_at,
        ended_at=r.ended_at,
        duration_s=r.duration_s,
        end_reason=r.end_reason,
        external_providers=list(r.external_providers or []),
        turn_count=r.turn_count,
        interruptions=r.interruptions,
        response_ms_p50=r.response_ms_p50,
        response_ms_max=r.response_ms_max,
        cost_total_usd=_usd(r.cost_total_nusd),
        cost_status=r.cost_status,
        savings_usd=_usd(r.savings_nusd) or 0.0,
        error_count=len(r.errors or []),
        transcript_stored=r.transcript_stored,
    )


async def list_sessions(
    session: AsyncSession,
    *,
    cursor: str | None,
    limit: int,
    agent_id: uuid.UUID | None,
    errors_only: bool,
) -> tuple[list[SessionOut], str | None]:
    stmt = select(VoiceSession).order_by(VoiceSession.started_at.desc(), VoiceSession.id.desc())
    if after := decode_cursor(cursor):
        stamp, _, last_id = after.partition("|")
        try:
            at = datetime.fromisoformat(stamp)
            stmt = stmt.where(
                (VoiceSession.started_at < at)
                | ((VoiceSession.started_at == at) & (VoiceSession.id < uuid.UUID(last_id)))
            )
        except ValueError:
            raise AppError("Invalid cursor", code="invalid_cursor") from None
    if agent_id:
        stmt = stmt.where(VoiceSession.agent_id == agent_id)
    if errors_only:
        stmt = stmt.where(VoiceSession.errors != [])
    rows = list((await session.scalars(stmt.limit(limit + 1))).all())
    page = rows[:limit]
    nxt = (
        encode_cursor(f"{page[-1].started_at.isoformat()}|{page[-1].id}")
        if len(rows) > limit and page
        else None
    )
    return [to_out(r) for r in page], nxt


async def detail(session: AsyncSession, session_id: uuid.UUID) -> SessionDetail:
    row = await session.get(VoiceSession, session_id)
    if row is None:
        raise NotFoundError("Session not found")
    turns = (
        await session.scalars(
            select(SessionTurn)
            .where(SessionTurn.session_id == session_id)
            .order_by(SessionTurn.idx)
        )
    ).all()
    return SessionDetail(
        **to_out(row).model_dump(),
        usage=dict(row.usage or {}),
        self_hosted_stages=[str(x) for x in (row.usage or {}).get("self_hosted_stages", [])],
        cost_stt_usd=_usd(row.cost_stt_nusd),
        cost_llm_usd=_usd(row.cost_llm_nusd),
        cost_tts_usd=_usd(row.cost_tts_nusd),
        errors=list(row.errors or []),
        transcript_expires_at=row.transcript_expires_at,
        turns=[
            TurnOut(
                index=t.idx,
                started_at=t.started_at,
                user_text=t.user_text,
                agent_text=t.agent_text,
                interrupted=t.interrupted,
                user_speech_ms=t.user_speech_ms,
                endpoint_ms=t.endpoint_ms,
                stt_ms=t.stt_ms,
                llm_first_token_ms=t.llm_first_token_ms,
                tts_first_audio_ms=t.tts_first_audio_ms,
                response_ms=t.response_ms,
                llm_model=t.llm_model,
                llm_routed_small=t.llm_routed_small,
                response_cache_hit=t.response_cache_hit,
                error=t.error,
            )
            for t in turns
        ],
    )


async def erase_transcript(session: AsyncSession, session_id: uuid.UUID) -> None:
    """Remove the words of a session now; timings and usage stay for analytics."""
    row = await session.get(VoiceSession, session_id)
    if row is None:
        raise NotFoundError("Session not found")
    await session.execute(
        update(SessionTurn)
        .where(SessionTurn.session_id == session_id)
        .values(user_text=None, agent_text=None)
    )
    row.transcript_stored = False
    row.transcript_expires_at = None


async def claim(session: AsyncSession, session_id: uuid.UUID) -> bool:
    """Mark a session token used; False if any runtime replica already used it.

    One atomic insert in Postgres, so two replicas racing on the same token cannot both win.
    """
    from sqlalchemy.dialects.postgresql import insert

    from voiceos.sessions.models import SessionClaim

    result = await session.execute(
        insert(SessionClaim)
        .values(session_id=session_id)
        .on_conflict_do_nothing(index_elements=["session_id"])
        .returning(SessionClaim.session_id)
    )
    won = result.scalar_one_or_none() is not None
    await session.commit()
    return won


async def purge_claims(session: AsyncSession, older_than: timedelta = timedelta(hours=1)) -> int:
    """Forget used tokens long after they expired (tokens live 60 seconds)."""
    from sqlalchemy import delete

    from voiceos.sessions.models import SessionClaim

    result = await session.execute(
        delete(SessionClaim).where(SessionClaim.claimed_at < datetime.now(UTC) - older_than)
    )
    await session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def purge_expired(session: AsyncSession, now: datetime | None = None) -> int:
    """Clear transcripts past their retention (the worker runs this periodically)."""
    now = now or datetime.now(UTC)
    expired = list(
        (
            await session.scalars(
                select(VoiceSession.id)
                .where(VoiceSession.transcript_stored, VoiceSession.transcript_expires_at <= now)
                .limit(500)
            )
        ).all()
    )
    if not expired:
        return 0
    await session.execute(
        update(SessionTurn)
        .where(SessionTurn.session_id.in_(expired))
        .values(user_text=None, agent_text=None)
    )
    await session.execute(
        update(VoiceSession)
        .where(VoiceSession.id.in_(expired))
        .values(transcript_stored=False, transcript_expires_at=None)
    )
    await session.commit()
    metrics.TRANSCRIPTS_PURGED.inc(len(expired))
    return len(expired)
