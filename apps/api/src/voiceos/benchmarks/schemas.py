from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from voiceos.core.schemas import ApiModel


class BenchmarkIn(ApiModel):
    kind: Literal["latency"] = "latency"
    agent_ids: list[uuid.UUID] = Field(min_length=1, max_length=5)
    sessions: int = Field(5, ge=1, le=50, description="Conversations per agent")


class StageAverages(ApiModel):
    endpoint_ms: float | None = None
    stt_ms: float | None = None
    llm_first_token_ms: float | None = None
    tts_first_audio_ms: float | None = None


class AgentResult(ApiModel):
    """One agent's measurements; `error` is set instead when the agent could not run."""

    name: str | None = None
    language: str | None = None
    providers: dict[str, str] = Field(default_factory=dict)
    sessions: int = 0
    turns: int = 0
    response_ms_p50: float | None = None
    response_ms_p95: float | None = None
    client_first_audio_ms_p50: float | None = Field(
        None, description="Measured by the benchmark client: its audio end to the first reply audio"
    )
    client_first_audio_ms_p95: float | None = None
    stages_ms_avg: StageAverages = Field(default_factory=StageAverages)
    error: str | None = None


class BenchmarkResults(ApiModel):
    agents: dict[str, AgentResult] = Field(default_factory=dict)


class Hardware(ApiModel):
    machine: str | None = None
    system: str | None = None
    cpus: int | None = None
    cpu: str | None = None
    gpu: str | None = None
    python: str | None = None


class BenchmarkConfig(ApiModel):
    agent_ids: list[str] = Field(default_factory=list)
    sessions: int = 0


class BenchmarkOut(ApiModel):
    id: uuid.UUID
    kind: str
    status: str
    config: BenchmarkConfig
    results: BenchmarkResults
    hardware: Hardware
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
