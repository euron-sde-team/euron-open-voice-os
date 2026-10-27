"""Provider lifecycle: create, edit, test, delete, and resolve for the runtime.

Secrets are write-only: sealed with KMS (or AES-GCM locally) bound to the provider's id,
never returned, and opened only when the runtime asks for an agent's resolved config.
Whether a provider is *external* is derived from its adapter and URL, so a misconfigured
form cannot hide that audio leaves your infrastructure.
"""

from __future__ import annotations

import time
import uuid
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceos.audit.service import Actor, audit
from voiceos.core.container import Container
from voiceos.core.contract import Price, ProviderConfig
from voiceos.core.errors import AppError, ConflictError, NotFoundError
from voiceos.core.net import host_of, is_private_host
from voiceos.providers.models import Provider
from voiceos.providers.schemas import (
    CLOUD_ADAPTERS,
    ProviderIn,
    ProviderOut,
    ProviderTest,
    ProviderUpdate,
)


def classify(adapter: str, base_url: str | None, marked_external: bool) -> tuple[bool, bool]:
    """(external, self_hosted). Mock providers are neither: they are test stand-ins."""
    if adapter in CLOUD_ADAPTERS:
        return True, False
    if adapter == "mock":
        return False, False
    private = is_private_host(host_of(base_url or ""))
    external = marked_external or not private
    return external, not external


def _hint(key: str) -> str:
    return f"...{key[-4:]}" if len(key) >= 8 else "set"


def _origin(url: str | None) -> str:
    parts = urlsplit(url or "")
    return f"{parts.scheme}://{parts.netloc}".lower()


async def _usage(session: AsyncSession) -> dict[uuid.UUID, int]:
    from voiceos.agents.models import Agent

    counts: dict[uuid.UUID, int] = {}
    for column in (
        Agent.stt_provider_id,
        Agent.llm_provider_id,
        Agent.tts_provider_id,
        Agent.llm_small_provider_id,
    ):
        rows = await session.execute(
            select(column, func.count()).where(column.is_not(None)).group_by(column)
        )
        for pid, n in rows.all():
            if pid is not None:
                counts[pid] = counts.get(pid, 0) + int(n)
    return counts


def to_out(row: Provider, used_by: int = 0) -> ProviderOut:
    return ProviderOut(
        id=row.id,
        name=row.name,
        stage=row.stage,
        adapter=row.adapter,
        base_url=row.base_url,
        model=row.model,
        voice=row.voice,
        language=row.language,
        has_api_key=row.sealed_key is not None,
        key_hint=row.key_hint,
        external=row.external,
        self_hosted=row.self_hosted,
        timeout_s=row.timeout_s,
        price=Price.model_validate(row.price or {}),
        enabled=row.enabled,
        used_by=used_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def list_providers(session: AsyncSession, stage: str | None = None) -> list[ProviderOut]:
    stmt = select(Provider).order_by(Provider.stage, Provider.name)
    if stage:
        stmt = stmt.where(Provider.stage == stage)
    usage = await _usage(session)
    return [to_out(r, usage.get(r.id, 0)) for r in (await session.scalars(stmt)).all()]


async def get(session: AsyncSession, provider_id: uuid.UUID) -> Provider:
    row = await session.get(Provider, provider_id)
    if row is None:
        raise NotFoundError("Provider not found")
    return row


async def create(
    session: AsyncSession, container: Container, data: ProviderIn, actor: Actor
) -> ProviderOut:
    if await session.scalar(select(Provider.id).where(Provider.name == data.name)):
        raise ConflictError(
            f"A provider named {data.name!r} already exists", code="provider_exists"
        )
    external, self_hosted = classify(data.adapter, data.base_url, data.external)
    row = Provider(
        id=uuid.uuid4(),
        name=data.name,
        stage=data.stage,
        adapter=data.adapter,
        base_url=data.base_url,
        model=data.model,
        voice=data.voice,
        language=data.language,
        external=external,
        force_external=data.external,
        self_hosted=self_hosted,
        timeout_s=data.timeout_s,
        price=data.price.model_dump(exclude_none=True),
        enabled=data.enabled,
    )
    if data.api_key:
        row.sealed_key = await container.sealer.seal(data.api_key, str(row.id))
        row.key_hint = _hint(data.api_key)
    session.add(row)
    await session.flush()
    audit(
        session,
        actor,
        "provider.created",
        "provider",
        row.id,
        name=row.name,
        stage=row.stage,
        adapter=row.adapter,
        external=external,
    )
    await session.commit()
    await session.refresh(row)
    return to_out(row)


async def update(
    session: AsyncSession,
    container: Container,
    provider_id: uuid.UUID,
    data: ProviderUpdate,
    actor: Actor,
) -> ProviderOut:
    row = await get(session, provider_id)
    changes = data.model_dump(exclude_unset=True, exclude={"api_key", "clear_api_key"})
    if (
        "name" in changes
        and changes["name"] != row.name
        and await session.scalar(select(Provider.id).where(Provider.name == changes["name"]))
    ):
        raise ConflictError(
            f"A provider named {changes['name']!r} already exists", code="provider_exists"
        )
    old_origin = _origin(row.base_url)
    moved = data.base_url is not None and _origin(data.base_url) != old_origin
    if moved and row.sealed_key and not data.api_key and not data.clear_api_key:
        # Repointing a stored key at another host would hand that host the credential.
        raise AppError(
            "Changing the provider's host needs its API key again (or clear_api_key), so a "
            "stored key is never sent to a new host",
            code="api_key_required",
        )
    for field, value in changes.items():
        if value is None:
            continue
        if field == "price":
            row.price = Price.model_validate(value).model_dump(exclude_none=True)
        elif field == "external":
            row.force_external = bool(value)
        else:
            setattr(row, field, value)
    row.external, row.self_hosted = classify(row.adapter, row.base_url, row.force_external)
    if data.clear_api_key:
        row.sealed_key, row.key_hint = None, None
    elif data.api_key:
        row.sealed_key = await container.sealer.seal(data.api_key, str(row.id))
        row.key_hint = _hint(data.api_key)
    audit(
        session,
        actor,
        "provider.updated",
        "provider",
        row.id,
        fields=sorted([*changes, *(["api_key"] if data.api_key or data.clear_api_key else [])]),
        **({"from_host": old_origin, "to_host": _origin(row.base_url)} if moved else {}),
    )
    await session.commit()
    await session.refresh(row)
    return to_out(row, (await _usage(session)).get(row.id, 0))


async def delete(session: AsyncSession, provider_id: uuid.UUID, actor: Actor) -> None:
    row = await get(session, provider_id)
    used = (await _usage(session)).get(row.id, 0)
    if used:
        raise ConflictError(
            f"{used} agent(s) use this provider. Switch them to another provider first",
            code="provider_in_use",
            details={"agents": used},
        )
    await session.delete(row)
    audit(session, actor, "provider.deleted", "provider", provider_id, name=row.name)
    await session.commit()


async def resolve(container: Container, row: Provider) -> ProviderConfig:
    """The provider as the runtime needs it, secret opened."""
    key = await container.sealer.open(row.sealed_key, str(row.id)) if row.sealed_key else None
    return ProviderConfig(
        provider_id=str(row.id),
        name=row.name,
        stage=row.stage,
        adapter=row.adapter,
        base_url=row.base_url,
        api_key=SecretStr(key) if key else None,
        model=row.model,
        voice=row.voice,
        language=row.language,
        external=row.external,
        self_hosted=row.self_hosted,
        timeout_s=row.timeout_s,
        price=Price.model_validate(row.price or {}),
    )


async def test(container: Container, row: Provider) -> ProviderTest:
    """A cheap reachability check: GET {base_url}/models on OpenAI-compatible servers."""
    if row.adapter not in ("openai_compatible", "mock") or not row.base_url:
        return ProviderTest(
            ok=True,
            message="This adapter has no test call. Start a session with it to verify the key.",
        )
    key = await container.sealer.open(row.sealed_key, str(row.id)) if row.sealed_key else None
    headers = {"authorization": f"Bearer {key}"} if key else {}
    started = time.perf_counter()
    try:
        resp = await container.http.get(f"{row.base_url}/models", headers=headers, timeout=8.0)
    except httpx.HTTPError as exc:
        return ProviderTest(
            ok=False, message=f"Could not reach {row.base_url}: {type(exc).__name__}"
        )
    ms = round((time.perf_counter() - started) * 1000, 1)
    if resp.status_code in (401, 403):
        return ProviderTest(ok=False, latency_ms=ms, message="The provider refused the API key")
    if resp.status_code >= 400:
        return ProviderTest(
            ok=False, latency_ms=ms, message=f"The provider answered HTTP {resp.status_code}"
        )
    return ProviderTest(ok=True, latency_ms=ms, message="Reachable")


async def get_many(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, Provider]:
    rows = await session.scalars(select(Provider).where(Provider.id.in_(ids)))
    return {r.id: r for r in rows}
