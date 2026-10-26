"""SDK key lifecycle. Keys are stored as a peppered HMAC; the plaintext is shown once."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceos.agents import service as agent_service
from voiceos.audit.service import Actor, audit
from voiceos.core.errors import AppError, NotFoundError
from voiceos.core.security import API_KEY_PREFIX, generate_api_key
from voiceos.keys.models import ApiKey
from voiceos.keys.schemas import KeyCreated, KeyIn, KeyOut, KeyUpdate


def to_out(key: ApiKey) -> KeyOut:
    return KeyOut(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        display=f"{API_KEY_PREFIX}_{key.prefix}_****",
        rpm_limit=key.rpm_limit,
        agent_ids=list(key.agent_ids or []),
        allowed_origins=list(key.allowed_origins or []),
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        last_used_at=key.last_used_at,
        created_at=key.created_at,
    )


async def list_keys(session: AsyncSession, include_revoked: bool) -> list[KeyOut]:
    stmt = select(ApiKey).order_by(ApiKey.created_at.desc())
    if not include_revoked:
        stmt = stmt.where(ApiKey.revoked_at.is_(None))
    return [to_out(k) for k in (await session.scalars(stmt)).all()]


async def _check_agents(session: AsyncSession, agent_ids: list[uuid.UUID] | None) -> list[str]:
    """Scoped keys must name agents that exist; otherwise every session start would fail."""
    ids = [str(a) for a in agent_ids or []]
    missing = await agent_service.missing(session, ids)
    if missing:
        raise AppError(
            f"No agent with id {missing[0]}", code="unknown_agent", details={"missing": missing}
        )
    return ids


async def create_key(session: AsyncSession, data: KeyIn, pepper: str, actor: Actor) -> KeyCreated:
    agent_ids = await _check_agents(session, data.agent_ids)
    generated = generate_api_key(pepper)
    key = ApiKey(
        name=data.name,
        rpm_limit=data.rpm_limit,
        agent_ids=agent_ids,
        allowed_origins=list(data.allowed_origins),
        expires_at=data.expires_at,
        prefix=generated.prefix,
        secret_hash=generated.secret_hash,
        created_by=actor.id,
    )
    session.add(key)
    await session.flush()
    await session.refresh(key)
    audit(session, actor, "api_key.created", "api_key", key.id, name=key.name)
    await session.commit()
    return KeyCreated(**to_out(key).model_dump(), key=generated.plaintext)


async def update_key(
    session: AsyncSession, key_id: uuid.UUID, data: KeyUpdate, actor: Actor
) -> KeyOut:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise NotFoundError("API key not found")
    changes = data.model_dump(exclude_unset=True)
    if "agent_ids" in changes:
        changes["agent_ids"] = await _check_agents(session, data.agent_ids)
    for field, value in changes.items():
        setattr(key, field, value if value is not None or field == "expires_at" else [])
    audit(
        session,
        actor,
        "api_key.updated",
        "api_key",
        key.id,
        fields=sorted(changes),
    )
    await session.commit()
    return to_out(key)


async def revoke_key(session: AsyncSession, key_id: uuid.UUID, actor: Actor) -> KeyOut:
    key = await session.get(ApiKey, key_id)
    if key is None:
        raise NotFoundError("API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        audit(session, actor, "api_key.revoked", "api_key", key.id, name=key.name)
        await session.commit()
    return to_out(key)


async def count_active(session: AsyncSession) -> int:
    """Keys that are not revoked (expired keys included: they may be renewed)."""
    stmt = select(func.count()).select_from(ApiKey).where(ApiKey.revoked_at.is_(None))
    return int(await session.scalar(stmt) or 0)


async def forget_agent(session: AsyncSession, agent_id: str) -> None:
    """Remove a deleted agent from every key's scope (in the caller's transaction)."""
    keys = await session.scalars(select(ApiKey).where(ApiKey.agent_ids.contains([agent_id])))
    for key in keys:
        key.agent_ids = [a for a in key.agent_ids if a != agent_id]
