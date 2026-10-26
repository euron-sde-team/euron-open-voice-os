from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from voiceos.auth.dependencies import Admin, Viewer
from voiceos.benchmarks import service
from voiceos.benchmarks.schemas import BenchmarkIn, BenchmarkOut
from voiceos.core.deps import SessionDep

router = APIRouter(prefix="/api/v1/benchmarks", tags=["benchmarks"])


@router.get("", response_model=list[BenchmarkOut], summary="Benchmark runs, newest first")
async def list_runs(
    _: Viewer, session: SessionDep, limit: int = Query(20, ge=1, le=100)
) -> list[BenchmarkOut]:
    return await service.list_runs(session, limit)


@router.post("", response_model=BenchmarkOut, status_code=202, summary="Queue a latency benchmark")
async def queue(body: BenchmarkIn, actor: Admin, session: SessionDep) -> BenchmarkOut:
    return await service.queue(session, body, actor)


@router.get("/{run_id}", response_model=BenchmarkOut, summary="One benchmark run")
async def get_run(run_id: uuid.UUID, _: Viewer, session: SessionDep) -> BenchmarkOut:
    return service.to_out(await service.get(session, run_id))
