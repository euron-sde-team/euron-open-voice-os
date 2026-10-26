from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from voiceos.core.contract import CacheSettings, PrivacySettings, ToolSpec, TurnSettings
from voiceos.core.schemas import ApiModel

LANGUAGE = r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$"


class _AgentFields(ApiModel):
    description: str | None = Field(None, max_length=500)
    greeting: str | None = Field(None, max_length=500)
    voice: str | None = Field(None, max_length=120, description="Overrides the TTS provider voice")
    llm_small_provider_id: uuid.UUID | None = Field(
        None, description="Optional cheaper model for short turns (cost optimizer routing)"
    )
    small_model_max_words: int = Field(8, ge=1, le=100)
    turn: TurnSettings = TurnSettings()
    privacy: PrivacySettings = PrivacySettings()
    cache: CacheSettings = CacheSettings()
    tools: list[ToolSpec] = Field(default_factory=list, max_length=10)
    faq: list[str] = Field(default_factory=list, max_length=200)
    max_duration_s: int = Field(900, ge=30, le=7200)
    idle_timeout_s: int = Field(60, ge=10, le=600)
    enabled: bool = True

    @field_validator("faq")
    @classmethod
    def _faq(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s.strip()]
        if any(len(s) > 1000 for s in cleaned):
            raise ValueError("FAQ entries are at most 1000 characters")
        return cleaned


class AgentIn(_AgentFields):
    name: str = Field(min_length=1, max_length=120)
    language: str = Field("en", pattern=LANGUAGE)
    system_prompt: str = Field(min_length=1, max_length=8000)
    stt_provider_id: uuid.UUID
    llm_provider_id: uuid.UUID
    tts_provider_id: uuid.UUID


class AgentFromTemplate(ApiModel):
    template: str
    name: str | None = Field(None, min_length=1, max_length=120)
    stt_provider_id: uuid.UUID | None = None
    llm_provider_id: uuid.UUID | None = None
    tts_provider_id: uuid.UUID | None = None


class AgentUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    language: str | None = Field(None, pattern=LANGUAGE)
    system_prompt: str | None = Field(None, min_length=1, max_length=8000)
    greeting: str | None = Field(None, max_length=500)
    voice: str | None = Field(None, max_length=120)
    stt_provider_id: uuid.UUID | None = None
    llm_provider_id: uuid.UUID | None = None
    llm_small_provider_id: uuid.UUID | None = None
    tts_provider_id: uuid.UUID | None = None
    small_model_max_words: int | None = Field(None, ge=1, le=100)
    turn: TurnSettings | None = None
    privacy: PrivacySettings | None = None
    cache: CacheSettings | None = None
    tools: list[ToolSpec] | None = Field(None, max_length=10)
    faq: list[str] | None = Field(None, max_length=200)
    max_duration_s: int | None = Field(None, ge=30, le=7200)
    idle_timeout_s: int | None = Field(None, ge=10, le=600)
    enabled: bool | None = None


class ProviderRef(ApiModel):
    id: uuid.UUID
    name: str
    adapter: str
    model: str | None
    external: bool


class AgentOut(ApiModel):
    id: uuid.UUID
    name: str
    description: str | None
    template: str | None
    language: str
    system_prompt: str
    greeting: str | None
    voice: str | None
    stt: ProviderRef
    llm: ProviderRef
    llm_small: ProviderRef | None
    tts: ProviderRef
    small_model_max_words: int
    turn: TurnSettings
    privacy: PrivacySettings
    cache: CacheSettings
    tools: list[ToolSpec]
    faq: list[str]
    max_duration_s: int
    idle_timeout_s: int
    enabled: bool
    version: int
    external_providers: list[str] = Field(
        description="Providers that receive this agent's audio or text outside your infrastructure"
    )
    created_at: datetime
    updated_at: datetime


class TemplateOut(ApiModel):
    id: str
    name: str
    description: str
    language: str
