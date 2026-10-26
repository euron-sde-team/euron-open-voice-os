"""The contract between the control plane and the voice runtime.

The control plane resolves an agent (its providers with opened secrets, prompts, turn,
privacy and cache settings) into ``ResolvedAgent`` and hands it to the runtime over an
internal, token-protected endpoint. The runtime reports what happened back as
``SessionReport``. Both sides import only this module, so neither depends on the other's
internals (the control plane never imports Pipecat).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

Stage = Literal["stt", "llm", "tts"]
Transport = Literal["webrtc", "websocket"]
EndReason = Literal[
    "client_left", "agent_ended", "idle_timeout", "max_duration", "error", "shutdown", "rejected"
]

# Adapters the runtime can build. Each is one file under voiceos/runtime/providers.
SttAdapter = Literal["openai_compatible", "deepgram", "sarvam", "mock"]
LlmAdapter = Literal["openai_compatible", "anthropic", "mock"]
TtsAdapter = Literal["openai_compatible", "elevenlabs", "cartesia", "sarvam", "mock"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Price(_Model):
    """List prices used to estimate cost. Missing means "not reported", never zero."""

    per_audio_minute: float | None = Field(None, ge=0, description="STT, USD per minute")
    per_million_input_tokens: float | None = Field(None, ge=0)
    per_million_output_tokens: float | None = Field(None, ge=0)
    per_million_characters: float | None = Field(None, ge=0, description="TTS")


class ProviderConfig(_Model):
    provider_id: str
    name: str
    stage: Stage
    adapter: str
    base_url: str | None = None
    api_key: SecretStr | None = None
    model: str | None = None
    voice: str | None = None
    language: str | None = None
    # External: audio or text leaves your infrastructure (disclosed to the user).
    external: bool = False
    self_hosted: bool = False
    timeout_s: float = Field(15.0, gt=0, le=120)
    price: Price = Price()


class TurnSettings(_Model):
    # "smart": Silero VAD plus the Smart Turn v3 model; "vad": silence only.
    mode: Literal["smart", "vad"] = "smart"
    vad_stop_secs: float = Field(0.6, ge=0.1, le=3.0)
    allow_interruptions: bool = True
    # Words the user must say before an interruption counts (filters coughs and "uh huh").
    interruption_min_words: int = Field(1, ge=0, le=10)
    # How long a finished turn may wait for its transcript before it is treated as empty.
    # Raise it when speech recognition is slow (a busy CPU, a large model).
    transcript_wait_s: float = Field(15.0, ge=1.0, le=30.0)


class PrivacySettings(_Model):
    transcript_retention_days: int = Field(30, ge=0, le=3650, description="0: never stored")
    redact_pii: bool = True
    store_audio: bool = False


class CacheSettings(_Model):
    tts_phrase_cache: bool = True
    # Exact repeats of a normalized user utterance replay the stored answer. Only for
    # agents without tools, where the same question has one right answer.
    response_cache: bool = False


class ToolSpec(_Model):
    name: Literal["get_current_time", "end_conversation", "faq_lookup", "http_webhook"]
    description: str | None = None
    url: str | None = None


class ResolvedAgent(_Model):
    agent_id: str
    version: int
    name: str
    language: str = "en"
    system_prompt: str
    greeting: str | None = None
    stt: ProviderConfig
    llm: ProviderConfig
    tts: ProviderConfig
    # Optional cheaper model for short, simple turns (the cost optimizer's routing).
    llm_small: ProviderConfig | None = None
    small_model_max_words: int = Field(8, ge=1, le=100)
    turn: TurnSettings = TurnSettings()
    privacy: PrivacySettings = PrivacySettings()
    cache: CacheSettings = CacheSettings()
    tools: list[ToolSpec] = Field(default_factory=list)
    faq: list[str] = Field(default_factory=list)
    max_duration_s: int = Field(900, ge=30, le=7200)
    idle_timeout_s: int = Field(60, ge=10, le=600)

    def external_providers(self) -> list[str]:
        stages = [self.stt, self.llm, self.tts, *([self.llm_small] if self.llm_small else [])]
        return sorted({p.name for p in stages if p.external})


class TurnReport(_Model):
    index: int
    started_at: datetime
    user_text: str | None = None
    agent_text: str | None = None
    interrupted: bool = False
    # Milliseconds, measured by the runtime. None when the stage did not run.
    user_speech_ms: float | None = None
    # End of speech (VAD) to the turn being declared over (Smart Turn or silence timeout).
    endpoint_ms: float | None = None
    stt_ms: float | None = None
    llm_first_token_ms: float | None = None
    tts_first_audio_ms: float | None = None
    response_ms: float | None = Field(
        None, description="end of the user's speech (VAD) to the agent's first audio"
    )
    llm_model: str | None = None
    llm_routed_small: bool = False
    response_cache_hit: bool = False
    error: str | None = None


class UsageReport(_Model):
    stt_audio_seconds: float = 0.0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    tts_characters: int = 0
    tts_characters_cached: int = 0
    tts_cache_hits: int = 0
    response_cache_hits: int = 0
    llm_turns_routed_small: int = 0
    # Usage the provider did not report stays None, so cost reads "not reported".
    llm_usage_reported: bool = False


class SessionReport(_Model):
    session_id: str
    agent_id: str
    agent_version: int
    transport: Transport
    # Who started it ("user:<id>" or "key:<id>") and, for browsers, from which site.
    subject: str = ""
    origin: str | None = None
    started_at: datetime
    ended_at: datetime
    end_reason: EndReason
    turns: list[TurnReport] = Field(default_factory=list)
    usage: UsageReport = UsageReport()
    external_providers: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
