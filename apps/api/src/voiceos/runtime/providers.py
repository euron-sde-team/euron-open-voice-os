"""Provider adapters: one ``ProviderConfig`` in, one Pipecat service out.

Adding a provider means adding a builder here and a value to the adapter literal in
``core/contract.py``; the pipeline and the dashboard never change. Builders receive a
``Resources`` holder for anything that must be closed when the session ends (HTTP
sessions for the HTTP-based TTS services).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language

from voiceos.core.contract import ProviderConfig
from voiceos.runtime.services.phrase_cache import PhraseCache, cached, wiring
from voiceos.runtime.services.speech_tts import SpeechServerTTSService


class ProviderError(Exception):
    """A provider is misconfigured (unknown adapter, missing key)."""


@dataclass
class Resources:
    http: aiohttp.ClientSession | None = None
    closers: list[Callable[[], Any]] = field(default_factory=list)

    def aiohttp(self) -> aiohttp.ClientSession:
        if self.http is None:
            self.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        return self.http

    async def close(self) -> None:
        if self.http is not None:
            await self.http.close()


def _key(p: ProviderConfig) -> str:
    if p.api_key is None or not p.api_key.get_secret_value():
        raise ProviderError(f"Provider {p.name!r} needs an API key")
    return p.api_key.get_secret_value()


def _optional_key(p: ProviderConfig) -> str:
    # Local OpenAI-compatible servers (Ollama, VoiceOS speech) accept any key.
    return p.api_key.get_secret_value() if p.api_key else "not-needed"


def language(code: str | None) -> Language:
    try:
        return Language((code or "en").lower())
    except ValueError:
        return Language.EN


# ── STT ──────────────────────────────────────────────────────────────────────────────
def build_stt(p: ProviderConfig, agent_language: str) -> STTService:
    lang = language(p.language or agent_language)
    match p.adapter:
        case "openai_compatible" | "mock":
            from pipecat.services.openai.stt import OpenAISTTService

            return OpenAISTTService(
                api_key=_optional_key(p),
                base_url=p.base_url,
                settings=OpenAISTTService.Settings(model=p.model or "whisper-1", language=lang),
            )
        case "deepgram":
            from pipecat.services.deepgram.stt import DeepgramSTTService

            return DeepgramSTTService(
                api_key=_key(p),
                settings=DeepgramSTTService.Settings(model=p.model or "nova-3", language=lang),
            )
        case "sarvam":
            from pipecat.services.sarvam.stt import SarvamSTTService

            return SarvamSTTService(
                api_key=_key(p),
                model=p.model or "saarika:v2.5",
                settings=SarvamSTTService.Settings(language=lang),
            )
    raise ProviderError(f"Unknown STT adapter {p.adapter!r}")


# ── LLM ──────────────────────────────────────────────────────────────────────────────
def build_llm(p: ProviderConfig, system_prompt: str) -> LLMService[Any]:
    match p.adapter:
        case "openai_compatible" | "mock":
            from pipecat.services.openai.llm import OpenAILLMService

            return _bounded(
                OpenAILLMService(
                    api_key=_optional_key(p),
                    base_url=p.base_url,
                    retry_timeout_secs=p.timeout_s,
                    retry_on_timeout=True,
                    settings=OpenAILLMService.Settings(
                        model=p.model or "gpt-4o-mini", system_instruction=system_prompt
                    ),
                ),
                p.timeout_s,
            )
        case "anthropic":
            from pipecat.services.anthropic.llm import AnthropicLLMService

            return _bounded(
                AnthropicLLMService(
                    api_key=_key(p),
                    retry_timeout_secs=p.timeout_s,
                    retry_on_timeout=True,
                    settings=AnthropicLLMService.Settings(
                        model=p.model or "claude-haiku-4-5", system_instruction=system_prompt
                    ),
                ),
                p.timeout_s,
            )
    raise ProviderError(f"Unknown LLM adapter {p.adapter!r}")


def _bounded(service: LLMService[Any], timeout_s: float) -> LLMService[Any]:
    """Bound every request by the provider timeout, the retry included.

    Pipecat's ``retry_on_timeout`` re-issues a slow request once *without* a timeout, so a
    hung model would hang the caller's turn. With the client itself bounded, the retry
    times out too and the caller hears the spoken fallback.
    """
    client = getattr(service, "_client", None)
    if client is not None and hasattr(client, "with_options"):
        service._client = client.with_options(timeout=timeout_s)  # type: ignore[attr-defined]
    return service


# ── TTS ──────────────────────────────────────────────────────────────────────────────
def build_tts(
    p: ProviderConfig, res: Resources, cache: PhraseCache | None, agent_language: str
) -> TTSService:
    namespace = f"{p.provider_id}:{p.adapter}:{p.model}:{p.voice}"
    extra: dict[str, Any] = {"phrase_cache": wiring(cache, namespace)} if cache else {}
    # How long to wait for a synthesis to produce audio before calling it failed. Local
    # models on a busy CPU can need more than Pipecat's 3 s default for a first sentence.
    extra["stop_frame_timeout_s"] = max(3.0, min(p.timeout_s, 10.0))

    def cls(service: type[TTSService]) -> type[TTSService]:
        return cached(service) if cache else service

    match p.adapter:
        case "openai_compatible" | "mock":
            return cls(SpeechServerTTSService)(
                base_url=p.base_url or "",
                voice=p.voice or "af_heart",
                model=p.model or "kokoro",
                api_key=p.api_key.get_secret_value() if p.api_key else None,
                timeout_s=p.timeout_s,
                **extra,
            )
        case "elevenlabs":
            from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService

            return cls(ElevenLabsHttpTTSService)(
                api_key=_key(p),
                voice_id=p.voice,
                model=p.model or "eleven_flash_v2_5",
                aiohttp_session=res.aiohttp(),
                **extra,
            )
        case "cartesia":
            from pipecat.services.cartesia.tts import CartesiaHttpTTSService

            return cls(CartesiaHttpTTSService)(
                api_key=_key(p),
                voice_id=p.voice,
                model=p.model or "sonic-2",
                aiohttp_session=res.aiohttp(),
                **extra,
            )
        case "sarvam":
            from pipecat.services.sarvam.tts import SarvamHttpTTSService

            return cls(SarvamHttpTTSService)(
                api_key=_key(p),
                voice_id=p.voice or "anushka",
                model=p.model or "bulbul:v2",
                aiohttp_session=res.aiohttp(),
                settings=SarvamHttpTTSService.Settings(
                    language=language(p.language or agent_language)
                ),
                **extra,
            )
    raise ProviderError(f"Unknown TTS adapter {p.adapter!r}")
