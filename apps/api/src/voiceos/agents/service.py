"""Agent lifecycle and resolution for the runtime.

``resolve`` turns an agent into the ``ResolvedAgent`` contract (providers with opened
secrets), cached briefly in the config cache: any agent or provider write invalidates it
cluster wide, so an edit applies to the next session within about a second.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceos.agents.models import Agent
from voiceos.agents.schemas import (
    AgentFromTemplate,
    AgentIn,
    AgentOut,
    AgentUpdate,
    ProviderRef,
    TemplateOut,
)
from voiceos.agents.templates import TEMPLATES
from voiceos.audit.service import Actor, audit
from voiceos.core.container import Container
from voiceos.core.contract import (
    CacheSettings,
    PrivacySettings,
    ResolvedAgent,
    ToolSpec,
    TurnSettings,
)
from voiceos.core.errors import AppError, NotFoundError
from voiceos.providers import service as providers
from voiceos.providers.models import Provider

STAGES = {
    "stt_provider_id": "stt",
    "llm_provider_id": "llm",
    "llm_small_provider_id": "llm",
    "tts_provider_id": "tts",
}


def _ref(p: Provider) -> ProviderRef:
    return ProviderRef(id=p.id, name=p.name, adapter=p.adapter, model=p.model, external=p.external)


def to_out(a: Agent, by_id: dict[uuid.UUID, Provider]) -> AgentOut:
    used = [
        by_id[i]
        for i in (a.stt_provider_id, a.llm_provider_id, a.llm_small_provider_id, a.tts_provider_id)
        if i is not None and i in by_id
    ]
    return AgentOut(
        id=a.id,
        name=a.name,
        description=a.description,
        template=a.template,
        language=a.language,
        system_prompt=a.system_prompt,
        greeting=a.greeting,
        voice=a.voice,
        stt=_ref(by_id[a.stt_provider_id]),
        llm=_ref(by_id[a.llm_provider_id]),
        llm_small=_ref(by_id[a.llm_small_provider_id]) if a.llm_small_provider_id else None,
        tts=_ref(by_id[a.tts_provider_id]),
        small_model_max_words=a.small_model_max_words,
        turn=TurnSettings.model_validate(a.turn or {}),
        privacy=PrivacySettings.model_validate(a.privacy or {}),
        cache=CacheSettings.model_validate(a.cache or {}),
        tools=[ToolSpec.model_validate(t) for t in a.tools or []],
        faq=list(a.faq or []),
        max_duration_s=a.max_duration_s,
        idle_timeout_s=a.idle_timeout_s,
        enabled=a.enabled,
        version=a.version,
        external_providers=sorted({p.name for p in used if p.external}),
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


async def _providers_for(session: AsyncSession, agents: list[Agent]) -> dict[uuid.UUID, Provider]:
    ids = {
        i
        for a in agents
        for i in (a.stt_provider_id, a.llm_provider_id, a.llm_small_provider_id, a.tts_provider_id)
        if i
    }
    return await providers.get_many(session, list(ids))


async def list_agents(session: AsyncSession) -> list[AgentOut]:
    rows = list((await session.scalars(select(Agent).order_by(Agent.created_at.desc()))).all())
    by_id = await _providers_for(session, rows)
    return [to_out(a, by_id) for a in rows]


async def get(session: AsyncSession, agent_id: uuid.UUID) -> Agent:
    row = await session.get(Agent, agent_id)
    if row is None:
        raise NotFoundError("Agent not found")
    return row


async def get_out(session: AsyncSession, agent_id: uuid.UUID) -> AgentOut:
    row = await get(session, agent_id)
    return to_out(row, await _providers_for(session, [row]))


async def missing(session: AsyncSession, ids: list[str]) -> list[str]:
    """Which of these agent ids do not exist (for key scopes)."""
    parsed: list[uuid.UUID] = []
    for raw in ids:
        try:
            parsed.append(uuid.UUID(raw))
        except ValueError:
            return [raw]
    found = set(await session.scalars(select(Agent.id).where(Agent.id.in_(parsed))))
    return [str(i) for i in parsed if i not in found]


async def _check_providers(session: AsyncSession, values: dict[str, Any]) -> None:
    ids = [v for k, v in values.items() if k in STAGES and v is not None]
    by_id = await providers.get_many(session, ids)
    for field, stage in STAGES.items():
        pid = values.get(field)
        if pid is None:
            continue
        p = by_id.get(pid)
        if p is None:
            raise AppError(f"No provider with id {pid}", code="unknown_provider")
        if p.stage != stage:
            raise AppError(
                f"{p.name!r} is a {p.stage.upper()} provider, not {stage.upper()}",
                code="wrong_provider_stage",
            )
        if not p.enabled:
            raise AppError(f"{p.name!r} is disabled", code="provider_disabled")


def _settings(data: AgentIn | AgentUpdate) -> dict[str, Any]:
    out = data.model_dump(exclude_unset=isinstance(data, AgentUpdate), exclude_none=False)
    for key in ("turn", "privacy", "cache"):
        if out.get(key) is not None:
            out[key] = getattr(data, key).model_dump()
    if out.get("tools") is not None and data.tools is not None:
        out["tools"] = [t.model_dump(exclude_none=True) for t in data.tools]
    return out


async def create(
    session: AsyncSession, data: AgentIn, actor: Actor, *, template: str | None = None
) -> AgentOut:
    values = _settings(data)
    await _check_providers(session, values)
    _check_tools(data.tools)
    row = Agent(id=uuid.uuid4(), template=template, created_by=actor.id, **values)
    session.add(row)
    await session.flush()
    audit(session, actor, "agent.created", "agent", row.id, name=row.name, template=template)
    await session.commit()
    await session.refresh(row)
    return to_out(row, await _providers_for(session, [row]))


def _check_tools(tools: list[ToolSpec]) -> None:
    if any(t.name == "http_webhook" and not t.url for t in tools):
        raise AppError("The webhook tool needs a URL", code="webhook_url_required")


async def default_provider(session: AsyncSession, stage: str, language: str) -> uuid.UUID:
    """For templates: a self-hosted provider first (no key needed), then any enabled one."""
    rows = list(
        (
            await session.scalars(
                select(Provider)
                .where(Provider.stage == stage, Provider.enabled.is_(True))
                .order_by(Provider.self_hosted.desc(), Provider.created_at)
            )
        ).all()
    )
    if not rows:
        raise AppError(
            f"Add a {stage.upper()} provider first (Providers page)",
            code="no_provider",
            details={"stage": stage},
        )
    return rows[0].id


async def create_from_template(
    session: AsyncSession, data: AgentFromTemplate, actor: Actor
) -> AgentOut:
    t = TEMPLATES.get(data.template)
    if t is None:
        raise NotFoundError(f"No template {data.template!r}")
    body = AgentIn(
        name=data.name or t.name,
        description=t.description,
        language=t.language,
        system_prompt=t.system_prompt,
        greeting=t.greeting,
        voice=t.voice,
        stt_provider_id=data.stt_provider_id or await default_provider(session, "stt", t.language),
        llm_provider_id=data.llm_provider_id or await default_provider(session, "llm", t.language),
        tts_provider_id=data.tts_provider_id or await default_provider(session, "tts", t.language),
        tools=[ToolSpec.model_validate(x) for x in t.tools],
        faq=t.faq,
        turn=TurnSettings.model_validate(t.turn),
        cache=CacheSettings.model_validate(t.cache),
    )
    return await create(session, body, actor, template=t.id)


async def update(
    session: AsyncSession, agent_id: uuid.UUID, data: AgentUpdate, actor: Actor
) -> AgentOut:
    row = await get(session, agent_id)
    changes = _settings(data)
    for required in (
        "stt_provider_id",
        "llm_provider_id",
        "tts_provider_id",
        "name",
        "system_prompt",
        "language",
    ):
        if required in changes and changes[required] is None:
            changes.pop(required)
    if data.tools is not None:
        _check_tools(data.tools)
    await _check_providers(session, changes)
    for field, value in changes.items():
        setattr(row, field, value)
    row.version += 1
    audit(
        session,
        actor,
        "agent.updated",
        "agent",
        row.id,
        fields=sorted(changes),
        version=row.version,
    )
    await session.commit()
    await session.refresh(row)
    return to_out(row, await _providers_for(session, [row]))


async def delete(session: AsyncSession, agent_id: uuid.UUID, actor: Actor) -> None:
    from voiceos.keys import service as keys

    row = await get(session, agent_id)
    await keys.forget_agent(session, str(row.id), actor)
    await session.delete(row)
    audit(session, actor, "agent.deleted", "agent", agent_id, name=row.name)
    await session.commit()


def templates() -> list[TemplateOut]:
    return [
        TemplateOut(id=t.id, name=t.name, description=t.description, language=t.language)
        for t in TEMPLATES.values()
    ]


async def resolve(container: Container, agent_id: str) -> ResolvedAgent | None:
    """The agent as the runtime needs it, or None when missing, disabled, or relying on a
    disabled provider."""

    async def load() -> ResolvedAgent | None:
        try:
            uid = uuid.UUID(agent_id)
        except ValueError:
            return None
        async with container.db.sessionmaker() as session:
            a = await session.get(Agent, uid)
            if a is None or not a.enabled:
                return None
            by_id = await _providers_for(session, [a])
        # A disabled provider receives nothing: an agent that needs one cannot take calls
        # (the runtime refuses it), and a disabled small model just turns routing off.
        stages = (a.stt_provider_id, a.llm_provider_id, a.tts_provider_id)
        if any(not by_id[p].enabled for p in stages):
            return None
        stt = await providers.resolve(container, by_id[a.stt_provider_id])
        llm = await providers.resolve(container, by_id[a.llm_provider_id])
        tts = await providers.resolve(container, by_id[a.tts_provider_id])
        small = (
            await providers.resolve(container, by_id[a.llm_small_provider_id])
            if a.llm_small_provider_id and by_id[a.llm_small_provider_id].enabled
            else None
        )
        if a.voice:
            tts = tts.model_copy(update={"voice": a.voice})
        stt = stt.model_copy(update={"language": stt.language or a.language})
        return ResolvedAgent(
            agent_id=str(a.id),
            version=a.version,
            name=a.name,
            language=a.language,
            system_prompt=a.system_prompt,
            greeting=a.greeting,
            stt=stt,
            llm=llm,
            tts=tts,
            llm_small=small,
            small_model_max_words=a.small_model_max_words,
            turn=TurnSettings.model_validate(a.turn or {}),
            privacy=PrivacySettings.model_validate(a.privacy or {}),
            cache=CacheSettings.model_validate(a.cache or {}),
            tools=[ToolSpec.model_validate(t) for t in a.tools or []],
            faq=list(a.faq or []),
            max_duration_s=a.max_duration_s,
            idle_timeout_s=a.idle_timeout_s,
        )

    return await container.config_cache.get(f"agent:{agent_id}", load)
