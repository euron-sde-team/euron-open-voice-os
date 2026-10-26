from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from voiceos.core.schemas import ApiModel


class BenchmarkIn(ApiModel):
    kind: Literal["latency"] = "latency"
    agent_ids: list[uuid.UUID] = Field(min_length=1, max_length=5)
    sessions: int = Field(5, ge=1, le=50, description="Conversations per agent")


class BenchmarkOut(ApiModel):
    id: uuid.UUID
    kind: str
    status: str
    config: dict[str, Any]
    results: dict[str, Any]
    hardware: dict[str, Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
