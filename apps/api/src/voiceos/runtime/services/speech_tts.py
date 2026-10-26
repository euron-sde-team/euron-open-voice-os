"""TTS over any OpenAI-compatible speech endpoint, with any voice id.

Pipecat's OpenAI TTS service accepts only OpenAI's voice names, which rules out local
voices (Kokoro's ``af_heart``, ``hf_alpha``) and other compatible servers. This service
speaks the same API (``POST {base_url}/audio/speech``, ``response_format: pcm``) and
streams PCM16 mono as it arrives, so the first sentence plays while the rest is still being
synthesized.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import httpx
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

SAMPLE_RATE = 24_000


class SpeechServerTTSService(TTSService):
    """Streams speech from an OpenAI-compatible ``/audio/speech`` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        voice: str,
        model: str = "kokoro",
        api_key: str | None = None,
        speed: float | None = None,
        timeout_s: float = 15.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            sample_rate=SAMPLE_RATE,
            push_start_frame=True,
            push_stop_frames=True,
            settings=TTSSettings(model=model, voice=voice, language=None),
            **kwargs,
        )
        self._url = base_url.rstrip("/") + "/audio/speech"
        self._voice = voice
        self._model = model
        self._speed = speed
        headers = {"authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            headers=headers, timeout=httpx.Timeout(timeout_s, connect=5.0)
        )

    def can_generate_metrics(self) -> bool:
        return True

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        body: dict[str, Any] = {
            "model": self._model,
            "input": text,
            "voice": self._voice,
            "response_format": "pcm",
        }
        if self._speed:
            body["speed"] = self._speed
        try:
            async with self._client.stream("POST", self._url, json=body) as resp:
                if resp.status_code != 200:
                    detail = (await resp.aread()).decode(errors="replace")[:300]
                    yield ErrorFrame(error=f"TTS returned {resp.status_code}: {detail}")
                    return
                await self.start_tts_usage_metrics(text)
                carry = b""
                async for chunk in resp.aiter_bytes(self.chunk_size):
                    # PCM16 frames must hold whole samples.
                    data = carry + chunk
                    usable = len(data) - (len(data) % 2)
                    carry = data[usable:]
                    if usable:
                        await self.stop_ttfb_metrics()
                        yield TTSAudioRawFrame(data[:usable], SAMPLE_RATE, 1, context_id=context_id)
        except httpx.HTTPError as exc:
            yield ErrorFrame(error=f"TTS request failed: {type(exc).__name__}")

    async def cleanup(self) -> None:
        await super().cleanup()
        await self._client.aclose()
