"""Health, readiness, metrics and deployment info."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from typing import Any

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text

from voiceos import __version__
from voiceos.agents.models import Agent
from voiceos.auth.dependencies import Viewer
from voiceos.core.deps import ContainerDep, SessionDep
from voiceos.core.schemas import ApiModel
from voiceos.keys import service as key_service
from voiceos.providers.models import Provider

router = APIRouter(tags=["system"])


@router.get("/healthz", summary="Liveness")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health", summary="Liveness (alias of /healthz)")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


async def _probe(name: str, coro: Awaitable[Any]) -> tuple[str, dict[str, Any]]:
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=2)
        return name, {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:
        return name, {"ok": False, "error": type(exc).__name__}


@router.get("/readyz", summary="Readiness: Postgres reachable (Redis too, when configured)")
async def readyz(container: ContainerDep, response: Response) -> dict[str, Any]:
    async def pg() -> None:
        async with container.db.engine.connect() as conn:
            await conn.execute(text("select 1"))

    probes = [_probe("postgres", pg())]
    if container.kv.backend == "redis":
        probes.append(_probe("redis", container.kv.ping()))
    checks = dict(await asyncio.gather(*probes))
    # Redis is optional: when it is down the service still works, so only Postgres
    # decides readiness. A Redis failure is reported as degraded but stays ready.
    ok = checks["postgres"]["ok"]
    response.status_code = 200 if ok else 503
    degraded = not all(c["ok"] for c in checks.values())
    return {"status": "degraded" if degraded else "ready", "checks": checks}


@router.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class RuntimeProbe(ApiModel):
    """The voice runtime as the API sees it on the private network."""

    ok: bool
    status: str | None = None
    sessions: int | None = None
    capacity: int | None = None
    error: str | None = None


class SystemInfo(ApiModel):
    version: str
    environment: str
    cloud: str
    key_mode: str
    storage: str
    cache_backend: str
    runtime_url: str
    runtime: RuntimeProbe
    providers: dict[str, int]
    external_providers: int
    agents: int
    active_keys: int
    checks: dict[str, Any]


@router.get("/api/v1/system", response_model=SystemInfo, summary="Deployment configuration")
async def system(_: Viewer, session: SessionDep, container: ContainerDep) -> SystemInfo:
    s = container.settings
    rows = (
        await session.execute(
            select(Provider.stage, func.count(), func.count().filter(Provider.external)).group_by(
                Provider.stage
            )
        )
    ).all()
    agents = int(await session.scalar(select(func.count()).select_from(Agent)) or 0)
    keys = await key_service.count_active(session)
    checks: dict[str, Any] = {"postgres": {"ok": True}}
    if container.kv.backend == "redis":
        checks.update(dict([await _probe("redis", container.kv.ping())]))
    try:
        resp = await container.http.get(f"{s.runtime_internal_url.rstrip('/')}/readyz", timeout=2.0)
        body = resp.json()
        runtime = RuntimeProbe(
            ok=resp.status_code in (200, 503),
            status=body.get("status"),
            sessions=body.get("sessions"),
            capacity=body.get("capacity"),
        )
    except Exception as exc:
        runtime = RuntimeProbe(ok=False, error=type(exc).__name__)
    return SystemInfo(
        version=__version__,
        environment=s.environment,
        cloud=s.cloud,
        key_mode=s.key_mode,
        storage=s.storage,
        cache_backend=container.kv.backend,
        runtime_url=s.runtime_public_url,
        runtime=runtime,
        providers={stage: int(n) for stage, n, _ in rows},
        external_providers=sum(int(e) for _, _, e in rows),
        agents=agents,
        active_keys=int(keys or 0),
        checks=checks,
    )
