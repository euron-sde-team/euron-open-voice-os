from __future__ import annotations

from datetime import datetime

from pydantic import Field

from voiceos.core.schemas import ApiModel


class StageLatency(ApiModel):
    """Average milliseconds per stage across the period's turns."""

    endpoint_ms: float | None = Field(description="End of speech to the turn being declared over")
    stt_ms: float | None
    llm_first_token_ms: float | None
    tts_first_audio_ms: float | None


class Point(ApiModel):
    t: datetime
    sessions: int
    minutes: float
    response_ms_avg: float | None
    cost_usd: float


class AgentBreakdown(ApiModel):
    agent_key: str
    agent_name: str
    sessions: int
    minutes: float
    response_ms_avg: float | None
    cost_per_session_usd: float | None


class Overview(ApiModel):
    days: int
    sessions: int
    minutes: float
    turns: int
    interruption_rate: float
    error_sessions: int
    external_sessions: int = Field(description="Sessions that used an external provider")
    response_ms_avg: float | None
    response_ms_p50: float | None
    response_ms_p95: float | None
    stages: StageLatency
    cost_usd: float = Field(description="Estimated from provider list prices, costed sessions only")
    costed_sessions: int
    cost_per_session_usd: float | None
    savings_usd: float = Field(
        description="What the phrase and response caches avoided, at list price"
    )
    llm_tokens: int
    tts_characters_cached: int
    response_cache_hits: int
    previous: dict[str, float]
    series: list[Point]
    by_agent: list[AgentBreakdown]
