"""How the runtime talks to the control plane: load agents, report sessions.

Both sides are small protocols. ``HttpControlPlane`` is the real one (internal endpoints
protected by ``INTERNAL_API_TOKEN``, reachable only on the private network). ``StaticAgents``
serves agents from a JSON file and keeps reports in memory, which lets the runtime run and
be tested without a control plane (``RUNTIME_STATIC_AGENTS``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Protocol

import httpx

from voiceos.core.contract import ResolvedAgent, SessionReport

log = logging.getLogger("voiceos.runtime")


class AgentNotFoundError(Exception):
    pass


class ControlPlane(Protocol):
    async def agent(self, agent_id: str) -> ResolvedAgent: ...
    async def report(self, report: SessionReport) -> None: ...
    async def close(self) -> None: ...


class HttpControlPlane:
    def __init__(
        self, base_url: str, token: str, *, ttl_s: float = 5.0, timeout_s: float = 10.0
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(timeout_s, connect=3.0),
        )
        self._ttl = ttl_s
        self._cache: dict[str, tuple[float, ResolvedAgent]] = {}

    async def agent(self, agent_id: str) -> ResolvedAgent:
        hit = self._cache.get(agent_id)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        resp = await self._client.get(f"/internal/agents/{agent_id}")
        if resp.status_code == 404:
            raise AgentNotFoundError(agent_id)
        resp.raise_for_status()
        agent = ResolvedAgent.model_validate(resp.json())
        self._cache[agent_id] = (time.monotonic() + self._ttl, agent)
        return agent

    async def report(self, report: SessionReport) -> None:
        body = report.model_dump(mode="json")
        for attempt in range(3):
            try:
                resp = await self._client.post("/internal/sessions", json=body)
                resp.raise_for_status()
                return
            except httpx.HTTPError as exc:
                log.warning(
                    "session report failed",
                    extra={
                        "session_id": report.session_id,
                        "attempt": attempt + 1,
                        "error": type(exc).__name__,
                    },
                )
                await asyncio.sleep(0.5 * 2**attempt)
        log.error("session report dropped", extra={"session_id": report.session_id})

    async def close(self) -> None:
        await self._client.aclose()


class StaticAgents:
    """Agents from a JSON file (a list of ResolvedAgent); reports kept in memory."""

    def __init__(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text())
        self._agents = {a["agent_id"]: ResolvedAgent.model_validate(a) for a in data}
        self.reports: list[SessionReport] = []

    async def agent(self, agent_id: str) -> ResolvedAgent:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise AgentNotFoundError(agent_id) from None

    async def report(self, report: SessionReport) -> None:
        self.reports.append(report)
        log.info(
            "session report",
            extra={
                "session_id": report.session_id,
                "end": report.end_reason,
                "turns": [
                    t.model_dump(exclude={"started_at"}, exclude_none=True) for t in report.turns
                ],
                "usage": report.usage.model_dump(),
            },
        )

    async def close(self) -> None:
        return None
