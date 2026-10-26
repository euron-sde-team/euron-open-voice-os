from __future__ import annotations

import ipaddress
import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from voiceos.core.contract import Price
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
_METADATA_HOSTS = {"metadata", "metadata.google.internal", "instance-data"}
_AWS_METADATA_V6 = ipaddress.ip_address("fd00:ec2::254")


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def is_private_host(host: str) -> bool:
    """Loopback, private ranges and single-label names (Compose service names) stay inside."""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return "." not in host or host.endswith((".local", ".internal", ".svc", ".cluster.local"))
    return ip.is_private or ip.is_loopback


def _check_url(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip().rstrip("/")
    if not v.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    host = host_of(v)
    if not host:
        raise ValueError("base_url needs a host")
    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = ipaddress.ip_address(
            host.strip("[]")
        )
    except ValueError:
        ip = None  # a host name
    if ip is not None and (ip.is_link_local or ip.is_unspecified or ip == _AWS_METADATA_V6):
        # Instance metadata holds the task's own credentials: never a provider target.
        raise ValueError("base_url must not point at a link-local or metadata address")
    if host in _METADATA_HOSTS:
        raise ValueError("base_url must not point at an instance metadata host")
    return v


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
