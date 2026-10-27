"""Endpoints only the voice runtime calls, on the private network.

Protected by ``INTERNAL_API_TOKEN`` (a constant-time comparison) and, on AWS, by security
groups: the load balancer never routes ``/internal``. They return provider secrets, so they
must never be reachable from a browser.
"""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import IntegrityError

from voiceos.agents import service as agents
from voiceos.core.container import Container
from voiceos.core.contract import SessionReport
from voiceos.core.deps import ContainerDep, SessionDep
from voiceos.core.errors import AuthenticationError, ConflictError, NotFoundError
from voiceos.sessions import service as sessions


async def internal_caller(request: Request, container: ContainerDep) -> None:
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    expected = container.settings.internal_api_token
    if not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise AuthenticationError("Internal endpoint", code="internal_only")


Internal = Annotated[None, Depends(internal_caller)]
router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


@router.get("/agents/{agent_id}")
async def resolved_agent(agent_id: str, _: Internal, container: ContainerDep) -> dict[str, Any]:
    return await _agent_body(container, agent_id)


@router.post("/claims/{session_id}")
async def claim_session(
    session_id: uuid.UUID,
    agent_id: str,
    _: Internal,
    session: SessionDep,
    container: ContainerDep,
) -> dict[str, Any]:
    """Use a session token once, across every runtime replica, and get its agent.

    The runtime calls this while admitting a connection; only the first call for a session
    id wins, so a ticket replayed against another replica is refused."""
    if not await sessions.claim(session, session_id):
        raise ConflictError("This session token was already used", code="token_used")
    return await _agent_body(container, agent_id)


async def _agent_body(container: Container, agent_id: str) -> dict[str, Any]:
    agent = await agents.resolve(container, agent_id)
    if agent is None:
        raise NotFoundError("Agent not found or disabled")
    body = agent.model_dump(mode="json")
    # SecretStr serializes masked; the runtime needs the real keys, over this private hop only.
    for stage in ("stt", "llm", "tts", "llm_small"):
        provider = getattr(agent, stage)
        if provider is not None and provider.api_key is not None:
            body[stage]["api_key"] = provider.api_key.get_secret_value()
    return body


@router.post("/sessions")
async def report_session(
    report: SessionReport, _: Internal, session: SessionDep, container: ContainerDep
) -> dict[str, bool]:
    try:
        stored = await sessions.ingest(session, container, report)
    except IntegrityError as exc:
        await session.rollback()
        # Only a duplicate session id means "a retry raced the first report"; anything
        # else is a real failure the runtime must see (it retries, then logs the drop).
        if "sessions_pkey" not in str(exc.orig):
            raise
        stored = False
    return {"stored": stored}
