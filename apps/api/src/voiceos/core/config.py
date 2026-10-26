"""Runtime configuration, validated once at boot.

Every setting comes from the environment. Each service reads its own settings class:
``Settings`` for the control plane (api, worker), ``RuntimeSettings`` for the voice
runtime and ``SpeechSettings`` for the local speech server. Security-relevant settings are
checked by ``guard()`` so a misconfigured production deployment refuses to start instead
of running with demo secrets.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSECURE_SECRETS = {"", "change-me", "replace-with-output-of-make-env", "dev", "secret"}


def _split(v: object) -> object:
    if isinstance(v, str):
        return [item.strip() for item in v.split(",") if item.strip()]
    return v


def _insecure(value: str) -> bool:
    return value in INSECURE_SECRETS or "not-for-production" in value or len(value) < 32


class _Base(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"


class SpeechSettings(_Base):
    """The local speech server (Whisper and Kokoro behind OpenAI-compatible endpoints)."""

    speech_models_dir: str = "./models"
    whisper_default: str = Field("base", description="Size used for model 'whisper-1'")
    whisper_preload: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["base"])
    whisper_device: Literal["cpu", "cuda", "auto"] = "cpu"
    whisper_compute_type: str = "int8"
    kokoro_model: str = "kokoro-v1.0.int8.onnx"
    kokoro_voices: str = "voices-v1.0.bin"
    kokoro_preload: bool = True
    # Concurrent model calls; each one uses several cores already.
    speech_concurrency: int = Field(2, ge=1, le=32)
    speech_max_audio_s: float = Field(60.0, gt=0)
    speech_max_chars: int = Field(4000, ge=1)
    # Optional shared secret: when set, every request must send it as a Bearer token.
    speech_api_key: str = ""

    @field_validator("whisper_preload", mode="before")
    @classmethod
    def _preload(cls, v: object) -> object:
        return _split(v)


class RuntimeSettings(_Base):
    """The voice runtime: transports, session limits, and how it reaches the control plane."""

    control_plane_url: str = "http://localhost:4530"
    # Shared with the control plane: signs session tokens (browser -> runtime) and
    # authenticates the runtime's internal calls (runtime -> control plane).
    runtime_token_secret: str = "dev-runtime-token-secret-not-for-production"
    internal_api_token: str = "dev-internal-api-token-not-for-production"
    max_sessions: int = Field(8, ge=1, le=1000, description="Concurrent sessions per instance")
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:4510"]
    )
    # ICE servers handed to aiortc and to browsers: "turn:host:port" URLs.
    ice_urls: Annotated[list[str], NoDecode] = Field(default_factory=list)
    turn_username: str = ""
    turn_password: str = ""
    # Seconds an agent config stays cached in the runtime (admin edits apply after it).
    agent_cache_ttl_s: float = 5.0
    report_timeout_s: float = 10.0

    @field_validator("allowed_origins", "ice_urls", mode="before")
    @classmethod
    def _lists(cls, v: object) -> object:
        return _split(v)

    def guard(self) -> None:
        if self.environment != "production":
            return
        problems = [
            f"{name.upper()} must be a random value of at least 32 chars"
            for name in ("runtime_token_secret", "internal_api_token")
            if _insecure(getattr(self, name))
        ]
        if problems:
            raise RuntimeError("unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_runtime_settings() -> RuntimeSettings:
    settings = RuntimeSettings()
    settings.guard()
    return settings


@lru_cache
def get_speech_settings() -> SpeechSettings:
    return SpeechSettings()
