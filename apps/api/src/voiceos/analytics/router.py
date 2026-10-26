from __future__ import annotations

from fastapi import APIRouter, Query, Response

from voiceos.analytics import service
from voiceos.analytics.schemas import Overview
from voiceos.auth.dependencies import Viewer
from voiceos.core.deps import SessionDep

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get(
    "/overview", response_model=Overview, summary="Conversations, latency, cost and savings"
)
async def overview(
    _: Viewer, session: SessionDep, response: Response, days: int = Query(7, ge=1, le=90)
) -> Overview:
    response.headers["cache-control"] = "private, max-age=15"
    return await service.overview(session, days)
