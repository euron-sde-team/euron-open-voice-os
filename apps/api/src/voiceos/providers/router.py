from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response

from voiceos.auth.dependencies import Admin, Viewer
from voiceos.core.deps import ContainerDep, SessionDep
from voiceos.providers import service
from voiceos.providers.schemas import ProviderIn, ProviderOut, ProviderTest, ProviderUpdate

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


@router.get("", response_model=list[ProviderOut], summary="Configured STT, LLM and TTS providers")
async def list_providers(
    _: Viewer, session: SessionDep, stage: str | None = Query(None, pattern="^(stt|llm|tts)$")
) -> list[ProviderOut]:
    return await service.list_providers(session, stage)


@router.post("", response_model=ProviderOut, status_code=201, summary="Add a provider")
async def create_provider(
    body: ProviderIn, actor: Admin, session: SessionDep, container: ContainerDep
) -> ProviderOut:
    out = await service.create(session, container, body, actor)
    await container.config_cache.invalidate()
    return out


@router.patch("/{provider_id}", response_model=ProviderOut, summary="Edit a provider")
async def update_provider(
    provider_id: uuid.UUID,
    body: ProviderUpdate,
    actor: Admin,
    session: SessionDep,
    container: ContainerDep,
) -> ProviderOut:
    out = await service.update(session, container, provider_id, body, actor)
    await container.config_cache.invalidate()
    return out


@router.delete("/{provider_id}", status_code=204, summary="Delete an unused provider")
async def delete_provider(
    provider_id: uuid.UUID, actor: Admin, session: SessionDep, container: ContainerDep
) -> Response:
    await service.delete(session, provider_id, actor)
    await container.config_cache.invalidate()
    return Response(status_code=204)


@router.post("/{provider_id}/test", response_model=ProviderTest, summary="Check it is reachable")
async def check_provider(
    provider_id: uuid.UUID, _: Admin, session: SessionDep, container: ContainerDep
) -> ProviderTest:
    row = await service.get(session, provider_id)
    return await service.test(container, row)
