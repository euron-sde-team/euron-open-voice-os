"""Helpers for the control-plane suites: other users, SDK calls, filed session reports and
direct database reads (on this test's own engine; the app's engine lives on the server
thread's event loop)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.integration.conftest import INTERNAL_TOKEN, Stack, login

VIEWER = {"email": "viewer@example.test", "password": "Viewer-Pass-123"}
ADMIN = {"email": "admin@example.test", "password": "Admin-Pass-1234"}


async def add_user(stack: Stack, creds: dict[str, str], role: str) -> dict[str, Any]:
    body = {"name": role.title(), "role": role, **creds}
    user: dict[str, Any] = await stack.ok("POST", "/api/v1/users", body, status=201)
    return user


@asynccontextmanager
async def as_user(stack: Stack, creds: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    client = await login(stack.api_url, creds)
    try:
        yield client
    finally:
        await client.aclose()


@asynccontextmanager
async def db(stack: Stack) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(stack.settings.database_url)
    try:
        async with engine.begin() as conn:
            yield conn
    finally:
        await engine.dispose()


async def scalar(stack: Stack, sql: str, **params: Any) -> Any:
    async with db(stack) as conn:
        return (await conn.execute(text(sql), params)).scalar()


async def sdk(
    stack: Stack, key: str | None, agent_id: str, origin: str | None = None
) -> httpx.Response:
    headers = {"authorization": f"Bearer {key}"} if key else {}
    if origin:
        headers["origin"] = origin
    async with stack.anonymous() as c:
        return await c.post("/v1/sessions", json={"agent_id": agent_id}, headers=headers)


def internal(stack: Stack, token: str | None = INTERNAL_TOKEN) -> httpx.AsyncClient:
    headers = {"authorization": f"Bearer {token}"} if token else {}
    return httpx.AsyncClient(base_url=stack.api_url, headers=headers, timeout=30)


def report(
    agent_id: str,
    *,
    session_id: str | None = None,
    started: datetime | None = None,
    seconds: float = 30.0,
    turns: list[dict[str, Any]] | None = None,
    usage: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    external: list[str] | None = None,
) -> dict[str, Any]:
    """A SessionReport as the runtime files it."""
    start = started or datetime.now(UTC) - timedelta(minutes=5)
    return {
        "session_id": session_id or str(uuid.uuid4()),
        "agent_id": agent_id,
        "agent_version": 1,
        "transport": "websocket",
        "subject": "user:test",
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(seconds=seconds)).isoformat(),
        "end_reason": "client_left",
        "turns": turns
        if turns is not None
        else [
            {
                "index": 0,
                "started_at": start.isoformat(),
                "user_text": "Book a table for two",
                "agent_text": "Done, see you tonight.",
                "endpoint_ms": 300.0,
                "stt_ms": 250.0,
                "llm_first_token_ms": 400.0,
                "tts_first_audio_ms": 200.0,
                "response_ms": 900.0,
                "llm_model": "mock-llm",
            }
        ],
        "usage": usage
        or {
            "stt_audio_seconds": 3.0,
            "llm_input_tokens": 1000,
            "llm_output_tokens": 200,
            "tts_characters": 22,
            "llm_usage_reported": True,
        },
        "external_providers": external if external is not None else ["Mock LLM"],
        "errors": errors or [],
    }


async def file_report(stack: Stack, body: dict[str, Any]) -> dict[str, Any]:
    async with internal(stack) as c:
        resp = await c.post("/internal/sessions", json=body)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def turn(i: int, response_ms: float, user: str = "hi", said: str = "hello") -> dict[str, Any]:
    return {
        "index": i,
        "started_at": datetime.now(UTC).isoformat(),
        "user_text": user,
        "agent_text": said,
        "endpoint_ms": 100.0,
        "stt_ms": 100.0,
        "llm_first_token_ms": 100.0,
        "tts_first_audio_ms": 100.0,
        "response_ms": response_ms,
    }
