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


class Settings(_Base):
    """The control plane: API, worker and CLI."""

    cloud: Literal["local", "floci", "aws"] = Field("local", alias="VOICEOS_CLOUD")

    database_url: str = "postgresql+asyncpg://voiceos:voiceos@localhost:4542/voiceos"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # Empty: no Redis. Caches, rate limits and config invalidation then run in process.
    redis_url: str = ""
    memory_cache_max_bytes: int = Field(64_000_000, ge=1_000_000)

    session_secret: str = "dev-session-secret-not-for-production"  # noqa: S105 dev default, refused in production by guard()
    api_key_pepper: str = "dev-api-key-pepper-not-for-production"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:4510"]
    )

    # Provider API keys are sealed before they reach the database.
    key_mode: Literal["local", "kms"] = "local"
    local_master_key: str = "dev-local-master-key-not-for-production"
    kms_key_id: str = "alias/voiceos-local"

    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = None
    s3_force_path_style: bool = False
    # Opt-in session audio and benchmark reports. Rows keep only the object key.
    objects_bucket: str = "voiceos-local-objects"
    storage: Literal["local", "s3"] = "local"
    local_storage_dir: str = "./.data/objects"

    # The voice runtime: where browsers connect, and the secrets shared with it.
    runtime_public_url: str = "http://localhost:4535"
    # How the worker reaches the runtime on the private network (benchmarks, demo traffic).
    runtime_internal_url: str = "http://localhost:4535"
    runtime_token_secret: str = "dev-runtime-token-secret-not-for-production"  # noqa: S105 refused in production
    internal_api_token: str = "dev-internal-api-token-not-for-production"  # noqa: S105 refused in production

    # Where the demo seed points its providers, as the runtime reaches them.
    demo_speech_url: str = "http://speech:8080/v1"
    demo_llm_url: str = "http://mock-providers:4550/v1"

    default_rpm_limit: int = 120
    max_body_bytes: int = 2_000_000
    max_internal_body_bytes: int = 32_000_000
    worker_poll_interval_s: float = 30.0
    worker_metrics_port: int = Field(9464, ge=0, le=65535)
    otel_enabled: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        return _split(v)

    @property
    def cache_backend(self) -> Literal["redis", "memory"]:
        return "redis" if self.redis_url else "memory"

    def guard(self) -> None:
        """Refuse to boot in production with demo secrets or unsafe options."""
        if self.environment != "production":
            return
        problems: list[str] = [
            f"{name.upper()} must be a random value of at least 32 chars"
            for name in (
                "session_secret",
                "api_key_pepper",
                "runtime_token_secret",
                "internal_api_token",
            )
            if _insecure(getattr(self, name))
        ]
        if self.key_mode == "local" and _insecure(self.local_master_key):
            problems.append("LOCAL_MASTER_KEY must be set (or use KEY_MODE=kms)")
        secrets = [
            self.session_secret,
            self.api_key_pepper,
            self.runtime_token_secret,
            self.internal_api_token,
        ]
        if len(set(secrets)) != len(secrets):
            problems.append(
                "SESSION_SECRET, API_KEY_PEPPER, RUNTIME_TOKEN_SECRET and INTERNAL_API_TOKEN "
                "must all differ"
            )
        if self.cloud == "aws" and self.aws_endpoint_url:
            problems.append("AWS_ENDPOINT_URL must be unset when VOICEOS_CLOUD=aws")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if problems:
            raise RuntimeError("unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.guard()
    return settings


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
    # CPU threads each model call may use. Keep threads x concurrency within the cores
    # the container really gets; oversubscribing makes every call slower.
    speech_threads: int = Field(4, ge=1, le=64)
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
    runtime_token_secret: str = "dev-runtime-token-secret-not-for-production"  # noqa: S105 refused in production
    internal_api_token: str = "dev-internal-api-token-not-for-production"  # noqa: S105 refused in production
    max_sessions: int = Field(8, ge=1, le=1000, description="Concurrent sessions per instance")
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:4510"]
    )
    # ICE servers handed to browsers: "turn:host:port" URLs they can reach.
    ice_urls: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # The same TURN server as the runtime itself reaches it (a private address); empty
    # means the browser URLs, which is right when both sides see the same address.
    server_ice_urls: Annotated[list[str], NoDecode] = Field(default_factory=list)
    turn_password: str = ""
    # Seconds an agent config stays cached in the runtime (admin edits apply after it).
    agent_cache_ttl_s: float = 5.0
    report_timeout_s: float = 10.0

    @field_validator("allowed_origins", "ice_urls", "server_ice_urls", mode="before")
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
