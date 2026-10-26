from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from voiceos.core.schemas import ApiModel


class SessionStart(ApiModel):
    agent_id: uuid.UUID


class Disclosure(ApiModel):
    external: bool
    providers: list[str]
    message: str


class SessionTicket(ApiModel):
    """Everything a client needs to connect, valid for a minute and one session."""

    session_id: uuid.UUID
    token: str
    expires_in_s: int
    websocket_url: str
    offer_url: str
    ice_url: str
    agent: dict[str, str]
    disclosure: Disclosure


class TurnOut(ApiModel):
    index: int
    started_at: datetime
    user_text: str | None
    agent_text: str | None
    interrupted: bool
    user_speech_ms: float | None
    endpoint_ms: float | None
    stt_ms: float | None
    llm_first_token_ms: float | None
    tts_first_audio_ms: float | None
    response_ms: float | None
    llm_model: str | None
    llm_routed_small: bool
    response_cache_hit: bool
    error: str | None


class SessionOut(ApiModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    agent_name: str
    agent_version: int
    transport: str
    subject: str
    started_at: datetime
    ended_at: datetime
    duration_s: float
    end_reason: str
    external_providers: list[str]
    turn_count: int
    interruptions: int
    response_ms_p50: float | None
    response_ms_max: float | None
    cost_total_usd: float | None = Field(
        description="Null when a provider did not report usage or price"
    )
    cost_status: str
    savings_usd: float
    error_count: int
    transcript_stored: bool


class SessionDetail(SessionOut):
    usage: dict[str, Any]
    self_hosted_stages: list[str] = Field(
        description="Stages that ran on your own servers and so have no per-call price"
    )
    cost_stt_usd: float | None
    cost_llm_usd: float | None
    cost_tts_usd: float | None
    errors: list[str]
    transcript_expires_at: datetime | None
    turns: list[TurnOut]
