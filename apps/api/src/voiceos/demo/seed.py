"""Demo data: a working VoiceOS install with a month of history and real conversations.

* **Configuration** (users, providers, agents from every template, SDK keys) is created
  through the same services the dashboard uses.
* **Real conversations**: the headless voice client calls the agents through the real
  runtime, speaking the committed test utterances (synthesized with Kokoro). Whisper hears
  them, the LLM answers, Kokoro speaks, and the runtime files its reports with the timings
  it measured. Nothing about these sessions is invented.
* **History**: 30 days of sessions, each a replay of one of those real reports through the
  same ingest path (cost, redaction, retention, rollups); only the session id and the
  timestamps change. The dashboard therefore shows real measurements spread over time.
* **A benchmark run** is executed so the Benchmarks page has results.

The language model is the local mock (scripted answers with token usage). One copy of it
is marked external and priced like a hosted model, to show disclosure and costing; its
name says so.
"""

from __future__ import annotations

import asyncio
import os
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from voiceos.agents import service as agents
from voiceos.agents.models import Agent
from voiceos.agents.schemas import AgentFromTemplate, AgentUpdate
from voiceos.audit.service import Actor
from voiceos.benchmarks import service as bench
from voiceos.benchmarks.schemas import BenchmarkIn
from voiceos.core.config import Settings, get_settings
from voiceos.core.container import Container
from voiceos.core.contract import (
    Price,
    PrivacySettings,
    SessionReport,
    TurnReport,
    UsageReport,
)
from voiceos.core.security import hash_password
from voiceos.keys.models import ApiKey
from voiceos.keys.schemas import KeyIn
from voiceos.keys.service import create_key
from voiceos.providers import service as providers
from voiceos.providers.models import Provider
from voiceos.providers.schemas import ProviderIn
from voiceos.sessions import service as sessions
from voiceos.sessions.models import SessionTurn, VoiceSession
from voiceos.users.models import User

OWNER_EMAIL = "admin@voiceos.local"
PEOPLE = [
    ("Riya Sharma", "riya.sharma@voiceos.local", "admin"),
    ("Daniel Okafor", "daniel.okafor@voiceos.local", "viewer"),
]
PRICED_LLM = "Mock LLM (external, priced like gpt-4o-mini)"


@dataclass
class Demo:
    owner: Actor
    agents: dict[str, uuid.UUID] = field(default_factory=dict)
    languages: dict[uuid.UUID, str] = field(default_factory=dict)
    keys: dict[str, uuid.UUID] = field(default_factory=dict)


async def _people(container: Container, password: str) -> Actor:
    async with container.db.sessionmaker() as session:
        owner = await session.scalar(select(User).where(User.email == OWNER_EMAIL))
        if owner is None:
            owner = User(
                email=OWNER_EMAIL,
                name="Avery Chen",
                role="owner",
                password_hash=hash_password(password),
            )
            session.add(owner)
        for name, email, role in PEOPLE:
            if await session.scalar(select(User.id).where(User.email == email)) is None:
                session.add(
                    User(email=email, name=name, role=role, password_hash=hash_password(password))
                )
        await session.commit()
        return Actor(id=owner.id, email=owner.email, role="owner")


async def _providers(container: Container, actor: Actor, s: Settings) -> dict[str, uuid.UUID]:
    wanted = [
        ProviderIn(
            name="Local Whisper",
            stage="stt",
            adapter="openai_compatible",
            base_url=s.demo_speech_url,
            model="whisper-base",
            language="en",
            timeout_s=30,
        ),
        ProviderIn(
            name="Local Whisper (Hindi)",
            stage="stt",
            adapter="openai_compatible",
            base_url=s.demo_speech_url,
            model="whisper-small",
            language="hi",
            timeout_s=30,
        ),
        ProviderIn(
            name="Local Kokoro",
            stage="tts",
            adapter="openai_compatible",
            base_url=s.demo_speech_url,
            model="kokoro",
            voice="af_heart",
            timeout_s=30,
        ),
        ProviderIn(
            name="Mock LLM",
            stage="llm",
            adapter="openai_compatible",
            base_url=s.demo_llm_url,
            model="mock-llm",
        ),
        ProviderIn(
            name=PRICED_LLM,
            stage="llm",
            adapter="openai_compatible",
            base_url=s.demo_llm_url,
            model="mock-llm",
            external=True,
            price=Price(per_million_input_tokens=0.15, per_million_output_tokens=0.60),
        ),
    ]
    out: dict[str, uuid.UUID] = {}
    async with container.db.sessionmaker() as session:
        for p in wanted:
            existing = await session.scalar(select(Provider.id).where(Provider.name == p.name))
            out[p.name] = existing or (await providers.create(session, container, p, actor)).id
    return out


async def _agents(container: Container, demo: Demo, prov: dict[str, uuid.UUID]) -> None:
    plan = [
        ("receptionist", "Front desk", "Local Whisper", "Mock LLM", None),
        ("support", "Acme support line", "Local Whisper", PRICED_LLM, None),
        ("tutor", "Study buddy", "Local Whisper", "Mock LLM", None),
        ("meeting", "Stand-up assistant", "Local Whisper", "Mock LLM", 0),
        ("hindi-tutor", "Hindi tutor", "Local Whisper (Hindi)", "Mock LLM", None),
    ]
    async with container.db.sessionmaker() as session:
        for template, name, stt, llm, retention in plan:
            row = await session.scalar(select(Agent).where(Agent.name == name))
            if row is None:
                created = await agents.create_from_template(
                    session,
                    AgentFromTemplate(
                        template=template,
                        name=name,
                        stt_provider_id=prov[stt],
                        llm_provider_id=prov[llm],
                        tts_provider_id=prov["Local Kokoro"],
                    ),
                    demo.owner,
                )
                agent_id, language = created.id, created.language
                if retention is not None:
                    await agents.update(
                        session,
                        agent_id,
                        AgentUpdate(privacy=PrivacySettings(transcript_retention_days=retention)),
                        demo.owner,
                    )
            else:
                agent_id, language = row.id, row.language
            demo.agents[name] = agent_id
            demo.languages[agent_id] = language


async def _keys(container: Container, demo: Demo, s: Settings) -> None:
    wanted = [
        ("Website widget", ["Front desk"], ["https://www.example.com"], 60),
        ("Support backend", ["Acme support line"], [], 300),
        ("Learning app", ["Study buddy", "Hindi tutor"], [], None),
    ]
    async with container.db.sessionmaker() as session:
        for name, agent_names, origins, rpm in wanted:
            existing = await session.scalar(
                select(ApiKey.id).where(ApiKey.name == name, ApiKey.revoked_at.is_(None))
            )
            if existing is None:
                created = await create_key(
                    session,
                    KeyIn(
                        name=name,
                        rpm_limit=rpm,
                        agent_ids=[demo.agents[a] for a in agent_names],
                        allowed_origins=origins,
                    ),
                    s.api_key_pepper,
                    demo.owner,
                )
                existing = created.id
            demo.keys[name] = existing


async def _converse(container: Container, demo: Demo, n: int) -> list[str]:
    """Real conversations through the runtime; returns the session ids it reported."""
    from voiceos.benchmarks import latency

    base = container.settings.runtime_internal_url.rstrip("/")
    ws = (
        "wss://" + base[8:]
        if base.startswith("https://")
        else "ws://" + base.removeprefix("http://")
    )
    by_key = {
        "Front desk": "Website widget",
        "Acme support line": "Support backend",
        "Study buddy": "Learning app",
        "Hindi tutor": "Learning app",
    }
    names = list(demo.agents)
    ids: list[str] = []
    for i in range(n):
        name = names[i % len(names)]
        agent_id = demo.agents[name]
        files = latency.utterances(demo.languages[agent_id])
        key = by_key.get(name) if i % 3 else None
        subject = f"key:{demo.keys[key]}" if key else f"user:{demo.owner.id}"
        ticket = await sessions.start(container, agent_id, subject=subject, origin=None)
        try:
            await latency.converse_once(f"{ws}/ws?token={ticket.token}", files[i % len(files)])
        except Exception as exc:  # one failed call should not stop the seed; it is reported
            print(f"  conversation {i + 1} with {name} failed: {type(exc).__name__}")
            continue
        ids.append(str(ticket.session_id))
        print(f"  conversation {i + 1}/{n} with {name}")
    return await _await_reports(container, ids)


async def _await_reports(container: Container, ids: list[str], wait_s: float = 60) -> list[str]:
    wanted = {uuid.UUID(i) for i in ids}
    deadline = asyncio.get_running_loop().time() + wait_s
    while True:
        async with container.db.sessionmaker() as session:
            found = set(
                (
                    await session.scalars(
                        select(VoiceSession.id).where(VoiceSession.id.in_(wanted))
                    )
                ).all()
            )
        if found == wanted or asyncio.get_running_loop().time() > deadline:
            return [str(x) for x in found]
        await asyncio.sleep(1)


def _report(row: VoiceSession, turns: list[SessionTurn], start: datetime) -> SessionReport:
    shift = start - row.started_at
    usage_fields = set(UsageReport.model_fields)
    return SessionReport(
        session_id=str(uuid.uuid4()),
        agent_id=str(row.agent_id),
        agent_version=row.agent_version,
        transport=row.transport,
        subject=row.subject,
        origin=row.origin,
        started_at=start,
        ended_at=row.ended_at + shift,
        end_reason=row.end_reason,
        turns=[
            TurnReport(
                index=t.idx,
                started_at=t.started_at + shift,
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
        usage=UsageReport.model_validate(
            {k: v for k, v in (row.usage or {}).items() if k in usage_fields}
        ),
        external_providers=list(row.external_providers or []),
        errors=list(row.errors or []),
    )


async def _history(container: Container, recorded: list[str], days: int) -> int:
    """Replay the recorded sessions over the past ``days`` with a weekday rhythm and growth."""
    rng = random.Random(7)
    async with container.db.sessionmaker() as session:
        rows = list(
            (
                await session.scalars(
                    select(VoiceSession).where(
                        VoiceSession.id.in_([uuid.UUID(i) for i in recorded])
                    )
                )
            ).all()
        )
        turns = {
            r.id: list(
                (
                    await session.scalars(
                        select(SessionTurn)
                        .where(SessionTurn.session_id == r.id)
                        .order_by(SessionTurn.idx)
                    )
                ).all()
            )
            for r in rows
        }
    rows = [r for r in rows if r.agent_id is not None and turns[r.id]]
    if not rows:
        return 0
    today = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    count = 0
    for d in range(days, 0, -1):
        day = today - timedelta(days=d)
        weekday = day.weekday() < 5
        n = int((3 if weekday else 1) + (days - d) / 6 + rng.random() * 3)
        for _ in range(n):
            row = rng.choice(rows)
            start = day.replace(hour=rng.randint(8, 20), minute=rng.randint(0, 59))
            async with container.db.sessionmaker() as session:
                if await sessions.ingest(session, container, _report(row, turns[row.id], start)):
                    count += 1
    return count


async def _benchmark(container: Container, demo: Demo) -> None:
    async with container.db.sessionmaker() as session:
        await bench.queue(
            session,
            BenchmarkIn(
                agent_ids=[demo.agents["Front desk"], demo.agents["Hindi tutor"]], sessions=3
            ),
            demo.owner,
        )
    await bench.run_once(container)


async def run(conversations: int = 12, days: int = 30) -> None:
    password = os.environ.get("VOS_DEMO_PASSWORD", "")
    if len(password) < 10:
        raise SystemExit("Set VOS_DEMO_PASSWORD (10+ characters); make env generates one.")
    s = get_settings()
    container = Container.build(s)
    try:
        demo = Demo(owner=await _people(container, password))
        prov = await _providers(container, demo.owner, s)
        await _agents(container, demo, prov)
        await _keys(container, demo, s)
        print(f"configured {len(prov)} providers, {len(demo.agents)} agents, {len(demo.keys)} keys")
        print(f"holding {conversations} real conversations through {s.runtime_internal_url}")
        recorded = await _converse(container, demo, conversations)
        print(f"  {len(recorded)} sessions reported by the runtime")
        replayed = await _history(container, recorded, days)
        print(f"replayed {replayed} sessions over the past {days} days from those recordings")
        print("running a latency benchmark (2 agents, 3 conversations each)")
        await _benchmark(container, demo)
    finally:
        await container.close()
    print("\nSign in at the dashboard with any of:")
    for email in [OWNER_EMAIL, *(p[1] for p in PEOPLE)]:
        print(f"  {email}")
    print("Password: the VOS_DEMO_PASSWORD in deploy/compose/.env")
