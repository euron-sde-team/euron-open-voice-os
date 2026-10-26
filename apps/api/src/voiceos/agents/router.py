from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from voiceos.agents import service
from voiceos.agents.schemas import (
    AgentFromTemplate,
    AgentIn,
    AgentOut,
    AgentUpdate,
    TemplateOut,
)
from voiceos.auth.dependencies import Admin, Viewer
from voiceos.core.deps import ContainerDep, SessionDep

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


@router.get("", response_model=list[AgentOut], summary="Voice agents")
async def list_agents(_: Viewer, session: SessionDep) -> list[AgentOut]:
    return await service.list_agents(session)


@router.get("/templates", response_model=list[TemplateOut], summary="Agent templates")
async def templates(_: Viewer) -> list[TemplateOut]:
    return service.templates()


@router.get("/{agent_id}", response_model=AgentOut, summary="One agent")
async def get_agent(agent_id: uuid.UUID, _: Viewer, session: SessionDep) -> AgentOut:
    return await service.get_out(session, agent_id)


@router.post("", response_model=AgentOut, status_code=201, summary="Create an agent")
async def create_agent(
    body: AgentIn, actor: Admin, session: SessionDep, container: ContainerDep
) -> AgentOut:
    out = await service.create(session, body, actor)
    await container.config_cache.invalidate()
    return out


@router.post(
    "/from-template", response_model=AgentOut, status_code=201, summary="Create from a template"
)
async def create_from_template(
    body: AgentFromTemplate, actor: Admin, session: SessionDep, container: ContainerDep
) -> AgentOut:
    out = await service.create_from_template(session, body, actor)
    await container.config_cache.invalidate()
    return out


@router.patch("/{agent_id}", response_model=AgentOut, summary="Edit an agent (bumps its version)")
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    actor: Admin,
    session: SessionDep,
    container: ContainerDep,
) -> AgentOut:
    out = await service.update(session, agent_id, body, actor)
    await container.config_cache.invalidate()
    return out


@router.delete("/{agent_id}", status_code=204, summary="Delete an agent (sessions are kept)")
async def delete_agent(
    agent_id: uuid.UUID, actor: Admin, session: SessionDep, container: ContainerDep
) -> Response:
    await service.delete(session, agent_id, actor)
    await container.config_cache.invalidate()
    return Response(status_code=204)
