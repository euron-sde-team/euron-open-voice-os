"""voiceos create-owner against the real database: creates an owner, or resets one."""

from __future__ import annotations

import asyncio

import pytest

from tests.integration.conftest import Stack, login
from voiceos import cli
from voiceos.core.config import get_settings

pytestmark = pytest.mark.asyncio


async def test_create_owner_creates_then_resets(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", stack.settings.database_url)
    get_settings.cache_clear()
    try:
        monkeypatch.setenv("VOICEOS_OWNER_PASSWORD", "First-Owner-Pass-1")
        await asyncio.to_thread(
            cli.main, ["create-owner", "--email", "Ops@Example.test", "--name", "Ops"]
        )
        first = await login(
            stack.api_url, {"email": "ops@example.test", "password": "First-Owner-Pass-1"}
        )
        me = (await first.get("/api/v1/auth/me")).json()
        assert me["role"] == "owner" and me["name"] == "Ops"

        # Running it again resets the password and signs the old sessions out.
        monkeypatch.setenv("VOICEOS_OWNER_PASSWORD", "Second-Owner-Pass-2")
        await asyncio.to_thread(cli.main, ["create-owner", "--email", "ops@example.test"])
        assert (await first.get("/api/v1/auth/me")).status_code == 401
        await first.aclose()
        second = await login(
            stack.api_url, {"email": "ops@example.test", "password": "Second-Owner-Pass-2"}
        )
        await second.aclose()
    finally:
        get_settings.cache_clear()
