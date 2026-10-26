from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, Response

from voiceos.audit.service import audit
from voiceos.auth.dependencies import Admin, Viewer
from voiceos.core.deps import ContainerDep, SessionDep
from voiceos.core.schemas import Page
from voiceos.keys.dependencies import ServiceKey
from voiceos.sessions import service
from voiceos.sessions.schemas import SessionDetail, SessionOut, SessionStart, SessionTicket

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])
sdk = APIRouter(prefix="/v1", tags=["sdk"])


@router.post(
    "",
    response_model=SessionTicket,
    status_code=201,
    summary="Start a session from the dashboard (Talk page)",
)
async def start_session(
    body: SessionStart, request: Request, actor: Viewer, container: ContainerDep
) -> SessionTicket:
    return await service.start(
        container,
        body.agent_id,
        subject=f"user:{actor.id}",
        origin=request.headers.get("origin"),
    )


@router.get("", response_model=Page[SessionOut], summary="Finished sessions, newest first")
async def list_sessions(
    _: Viewer,
    session: SessionDep,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    agent_id: uuid.UUID | None = None,
    errors_only: bool = False,
) -> Page[SessionOut]:
    items, nxt = await service.list_sessions(
        session, cursor=cursor, limit=limit, agent_id=agent_id, errors_only=errors_only
    )
    return Page[SessionOut](items=items, next_cursor=nxt)


@router.get("/{session_id}", response_model=SessionDetail, summary="One session with its turns")
async def get_session(session_id: uuid.UUID, _: Viewer, session: SessionDep) -> SessionDetail:
    return await service.detail(session, session_id)


@router.delete(
    "/{session_id}/transcript",
    status_code=204,
    summary="Erase a session's transcript now (timings and usage stay)",
)
async def erase_transcript(session_id: uuid.UUID, actor: Admin, session: SessionDep) -> Response:
    await service.erase_transcript(session, session_id)
    audit(session, actor, "session.transcript_erased", "session", session_id)
    await session.commit()
    return Response(status_code=204)


@sdk.post(
    "/sessions",
    response_model=SessionTicket,
    status_code=201,
    summary="Start a session with an SDK key (your backend, or an origin-bound embed)",
)
async def sdk_start(
    body: SessionStart, request: Request, key: ServiceKey, container: ContainerDep
) -> SessionTicket:
    return await service.start(
        container,
        body.agent_id,
        subject=f"key:{key.id}",
        origin=request.headers.get("origin") if key.allowed_origins else None,
        allowed_agents=key.agent_ids,
        allowed_origins=key.allowed_origins,
    )
