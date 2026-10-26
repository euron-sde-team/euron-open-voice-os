"""Integration harness: the real control plane and the real voice runtime, each served over
HTTP from a background thread, against real Postgres (and Redis, Floci S3 and KMS when the
option matrix selects them), with the mock speech and LLM providers on a third server.

    make test-integration      (starts Postgres and Redis containers if needed)
    make test-matrix           (reruns everything under every backend combination)

The runtime reaches the control plane over HTTP exactly as it does in production
(``/internal/*`` with the internal token), and voice sessions are driven by the headless
WebSocket client streaming the committed speech files, so VAD, turn taking, interruption,
fallbacks and reporting all run for real. Only the providers are mocks; the local Whisper
and Kokoro path is covered by the e2e suite and the benchmark.

Safety: the suite truncates every table, so it refuses any database whose name does not
contain "test", and any non-local host unless ALLOW_REMOTE_TEST_DB=true.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from voiceos.core.config import RuntimeSettings, Settings

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://voiceos:voiceos@localhost:4542/voiceos_test"
)
# TEST_CACHE=memory runs the whole suite with no Redis at all.
TEST_CACHE = os.environ.get("TEST_CACHE", "memory")
TEST_REDIS = os.environ.get("TEST_REDIS_URL", "redis://localhost:4579/15")
OWNER = {"email": "owner@example.test", "password": "Owner-Pass-123"}
CSRF = {"x-voiceos-csrf": "1"}
RUNTIME_SECRET = "test-only-runtime-token-secret-32-bytes-plus"
INTERNAL_TOKEN = "test-only-internal-api-token-32-bytes-plus"
TABLES = (
    "usage_hourly, session_turns, sessions, benchmark_runs, audit_log, api_keys, agents, "
    "providers, revoked_sessions, users"
)
AUDIO = Path(__file__).resolve().parents[2] / "src/voiceos/benchmarks/audio"


def _guard(url: str) -> None:
    parsed = urlparse(url.replace("+asyncpg", ""))
    if "test" not in (parsed.path or ""):
        raise RuntimeError(
            f"refusing to run against {parsed.path!r}: database name must contain 'test'"
        )
    if (
        parsed.hostname not in ("localhost", "127.0.0.1", "postgres")
        and os.environ.get("ALLOW_REMOTE_TEST_DB") != "true"
    ):
        raise RuntimeError("refusing a non-local test database (set ALLOW_REMOTE_TEST_DB=true)")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Served:
    """An ASGI app (or import string) served by uvicorn on a thread, with its own loop."""

    def __init__(self, app: Any, port: int | None = None) -> None:
        self.port = port or free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_level="warning", ws="websockets"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, health: str = "/healthz") -> Served:
        self.thread.start()
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                if httpx.get(self.url + health, timeout=1).status_code < 500:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"server on {self.url} did not start")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)


@pytest.fixture(scope="session")
def mock_url() -> Iterator[str]:
    served = Served("mockproviders.app:app").start()
    yield served.url
    served.stop()


@pytest.fixture(scope="session")
async def database() -> AsyncIterator[str]:
    _guard(TEST_DB)
    admin_url = TEST_DB.rsplit("/", 1)[0] + "/postgres"
    name = TEST_DB.rsplit("/", 1)[1]
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()
    from voiceos.migrations.runner import upgrade

    await asyncio.to_thread(upgrade, TEST_DB)
    yield TEST_DB


def make_settings(database: str, tmp_path: Path, runtime_url: str, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": database,
        "redis_url": TEST_REDIS if TEST_CACHE == "redis" else "",
        "session_secret": "test-only-session-secret-with-32-plus-bytes",
        "api_key_pepper": "test-only-api-key-pepper-with-32-plus-bytes",
        "local_master_key": "test-only-master-key-with-32-plus-bytes-ok",
        "runtime_token_secret": RUNTIME_SECRET,
        "internal_api_token": INTERNAL_TOKEN,
        "runtime_public_url": runtime_url,
        "runtime_internal_url": runtime_url,
        "local_storage_dir": str(tmp_path / "objects"),
        # The option matrix (make test-matrix) reruns the suite against Floci KMS and S3.
        "key_mode": os.environ.get("TEST_KEY_MODE", "local"),
        "storage": os.environ.get("TEST_STORAGE", "local"),
        "aws_endpoint_url": os.environ.get("TEST_AWS_ENDPOINT"),
        "s3_force_path_style": True,
        "kms_key_id": os.environ.get("TEST_KMS_KEY_ID", "alias/voiceos-local"),
        "objects_bucket": os.environ.get("TEST_OBJECTS_BUCKET", "voiceos-local-objects"),
    }
    values.update(overrides)
    return Settings(**values)


async def reset(database: str, mock_url: str) -> None:
    engine = create_async_engine(database)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
    await engine.dispose()
    if TEST_CACHE == "redis":
        from redis.asyncio import Redis

        redis = Redis.from_url(TEST_REDIS)
        await redis.flushdb()
        await redis.aclose()
    async with httpx.AsyncClient() as client:
        await client.post(f"{mock_url}/stats/reset")


async def bootstrap_owner(database: str) -> None:
    from voiceos.core.db import Database
    from voiceos.core.security import hash_password
    from voiceos.users.models import User

    db = Database(database, pool_size=1, max_overflow=0)
    async with db.sessionmaker() as session:
        session.add(
            User(
                email=OWNER["email"],
                name="Owner",
                role="owner",
                password_hash=hash_password(OWNER["password"]),
            )
        )
        await session.commit()
    await db.dispose()


@dataclass
class Stack:
    """The running control plane and runtime, a signed-in owner, and helpers."""

    api_url: str
    runtime_url: str
    mock_url: str
    settings: Settings
    client: httpx.AsyncClient
    app: FastAPI

    async def ok(self, method: str, path: str, json: Any = None, status: int | None = None) -> Any:
        resp = await self.client.request(method, path, json=json)
        expected = status or (201 if method == "POST" and resp.status_code == 201 else 200)
        assert resp.status_code == expected, f"{method} {path}: {resp.status_code} {resp.text}"
        return resp.json() if resp.content else None

    def anonymous(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.api_url, timeout=30)

    async def mock(self, path: str, body: Any = None) -> Any:
        async with httpx.AsyncClient() as c:
            resp = await (c.post if body is not None else c.get)(
                f"{self.mock_url}{path}", **({"json": body} if body is not None else {})
            )
            return resp.json()

    async def session_row(self, session_id: str, wait_s: float = 20) -> dict[str, Any]:
        """The stored session, once the runtime has reported it."""
        deadline = time.monotonic() + wait_s
        while True:
            resp = await self.client.get(f"/api/v1/sessions/{session_id}")
            if resp.status_code == 200:
                data: dict[str, Any] = resp.json()
                return data
            if time.monotonic() > deadline:
                raise AssertionError(f"session {session_id} was never reported ({resp.text})")
            await asyncio.sleep(0.3)


async def login(base_url: str, creds: dict[str, str] = OWNER) -> httpx.AsyncClient:
    client = httpx.AsyncClient(base_url=base_url, timeout=30, headers=CSRF)
    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200, resp.text
    client.headers["authorization"] = f"Bearer {resp.json()['session_token']}"
    return client


def runtime_settings(control_plane_url: str, **overrides: Any) -> RuntimeSettings:
    values: dict[str, Any] = {
        "environment": "test",
        "control_plane_url": control_plane_url,
        "runtime_token_secret": RUNTIME_SECRET,
        "internal_api_token": INTERNAL_TOKEN,
        "max_sessions": 4,
        "agent_cache_ttl_s": 0.0,
        "allowed_origins": ["http://localhost:4510"],
    }
    values.update(overrides)
    return RuntimeSettings(**values)


@pytest.fixture
def runtime_overrides() -> dict[str, Any]:
    """Tests override this to change the runtime's settings (for example the session cap)."""
    return {}


@pytest.fixture
async def stack(
    database: str, tmp_path: Path, mock_url: str, runtime_overrides: dict[str, Any]
) -> AsyncIterator[Stack]:
    from voiceos.main import create_app
    from voiceos.runtime.app import create_app as create_runtime

    await reset(database, mock_url)
    await bootstrap_owner(database)
    api_port, runtime_port = free_port(), free_port()
    settings = make_settings(database, tmp_path, f"http://127.0.0.1:{runtime_port}")
    app = create_app(settings)
    api = Served(app, api_port).start()
    runtime = Served(
        create_runtime(runtime_settings(api.url, **runtime_overrides)), runtime_port
    ).start()
    client = await login(api.url)
    try:
        yield Stack(api.url, runtime.url, mock_url, settings, client, app)
    finally:
        await client.aclose()
        runtime.stop()
        api.stop()


@dataclass
class Voice:
    """Providers on the mock server and an agent wired to them."""

    stt: str
    llm: str
    tts: str
    agent: str


async def make_voice(stack: Stack, **agent: Any) -> Voice:
    """STT and TTS are self-hosted (a private URL); the LLM is marked external and priced,
    as a hosted model would be, so disclosure and costing both have something to show."""
    base = f"{stack.mock_url}/v1"
    stt = await stack.ok(
        "POST",
        "/api/v1/providers",
        {
            "name": "Mock STT",
            "stage": "stt",
            "adapter": "openai_compatible",
            "base_url": base,
            "model": "whisper-1",
            "timeout_s": 5,
        },
    )
    llm = await stack.ok(
        "POST",
        "/api/v1/providers",
        {
            "name": "Mock LLM",
            "stage": "llm",
            "adapter": "openai_compatible",
            "base_url": base,
            "model": "mock-llm",
            "timeout_s": 5,
            "external": True,
            "price": {"per_million_input_tokens": 0.15, "per_million_output_tokens": 0.6},
        },
    )
    tts = await stack.ok(
        "POST",
        "/api/v1/providers",
        {
            "name": "Mock TTS",
            "stage": "tts",
            "adapter": "openai_compatible",
            "base_url": base,
            "model": "tts-1",
            "voice": "alloy",
            "timeout_s": 5,
        },
    )
    body = {
        "name": "Test agent",
        "system_prompt": "You are a test agent.",
        # Spoken by TTS without the LLM, so LLM faults hit the caller's turn.
        "greeting": "Hi there.",
        "stt_provider_id": stt["id"],
        "llm_provider_id": llm["id"],
        "tts_provider_id": tts["id"],
        "turn": {"mode": "vad", "vad_stop_secs": 0.4},
        **agent,
    }
    created = await stack.ok("POST", "/api/v1/agents", body)
    return Voice(stt["id"], llm["id"], tts["id"], created["id"])


@pytest.fixture
async def voice(stack: Stack) -> Voice:
    return await make_voice(stack)


async def ticket(stack: Stack, agent_id: str) -> dict[str, Any]:
    data: dict[str, Any] = await stack.ok("POST", "/api/v1/sessions", {"agent_id": agent_id})
    return data


def utterance(name: str = "en-01-booking.wav") -> bytes:
    from voiceos.benchmarks.client import load_pcm16k

    return load_pcm16k(AUDIO / name)
