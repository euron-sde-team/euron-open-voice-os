from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from voiceos.core.contract import Price
from voiceos.core.net import check_url
from voiceos.core.schemas import ApiModel

Stage = Literal["stt", "llm", "tts"]
Adapter = Literal[
    "openai_compatible", "deepgram", "sarvam", "anthropic", "elevenlabs", "cartesia", "mock"
]

ADAPTERS: dict[str, set[str]] = {
    "stt": {"openai_compatible", "deepgram", "sarvam", "mock"},
    "llm": {"openai_compatible", "anthropic", "mock"},
    "tts": {"openai_compatible", "elevenlabs", "cartesia", "sarvam", "mock"},
}
# These always send audio or text to the vendor's cloud.
CLOUD_ADAPTERS = {"deepgram", "sarvam", "anthropic", "elevenlabs", "cartesia"}
NEEDS_URL = {"openai_compatible", "mock"}


def _check_url(v: str | None) -> str | None:
    return None if v is None else check_url(v, "base_url")


class ProviderIn(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    stage: Stage
    adapter: Adapter
    base_url: str | None = Field(None, max_length=500)
    model: str | None = Field(None, max_length=120)
    voice: str | None = Field(None, max_length=120)
    language: str | None = Field(None, max_length=16)
    api_key: str | None = Field(None, max_length=4000, description="Write-only; sealed at rest")
    external: bool = Field(
        False, description="Mark as external even if the URL looks private (never the reverse)"
    )
    timeout_s: float = Field(15.0, gt=0, le=120)
    price: Price = Price()
    enabled: bool = True

    _url = field_validator("base_url")(_check_url)

    @model_validator(mode="after")
    def _adapter_fits_stage(self) -> ProviderIn:
        if self.adapter not in ADAPTERS[self.stage]:
            allowed = ", ".join(sorted(ADAPTERS[self.stage]))
            raise ValueError(
                f"{self.adapter} is not a {self.stage} adapter (use one of: {allowed})"
            )
        if self.adapter in NEEDS_URL and not self.base_url:
            raise ValueError(f"{self.adapter} providers need a base_url")
        return self


class ProviderUpdate(ApiModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    base_url: str | None = Field(None, max_length=500)
    model: str | None = Field(None, max_length=120)
    voice: str | None = Field(None, max_length=120)
    language: str | None = Field(None, max_length=16)
    api_key: str | None = Field(None, max_length=4000)
    clear_api_key: bool = False
    external: bool | None = None
    timeout_s: float | None = Field(None, gt=0, le=120)
    price: Price | None = None
    enabled: bool | None = None

    _url = field_validator("base_url")(_check_url)


class ProviderOut(ApiModel):
    id: uuid.UUID
    name: str
    stage: str
    adapter: str
    base_url: str | None
    model: str | None
    voice: str | None
    language: str | None
    has_api_key: bool
    key_hint: str | None
    external: bool = Field(description="Audio or text leaves your infrastructure")
    self_hosted: bool
    timeout_s: float
    price: Price
    enabled: bool
    used_by: int = Field(0, description="Agents that use this provider")
    created_at: datetime
    updated_at: datetime


class ProviderTest(ApiModel):
    ok: bool
    latency_ms: float | None = None
    message: str
