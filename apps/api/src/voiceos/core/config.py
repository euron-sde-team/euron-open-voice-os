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


@lru_cache
def get_speech_settings() -> SpeechSettings:
    return SpeechSettings()
