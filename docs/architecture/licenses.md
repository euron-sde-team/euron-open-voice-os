# Third-party licenses

VoiceOS itself is MIT licensed. This page lists the third-party components that matter
for its license, where each one runs, and what that means if you distribute images. It
describes the 0.1.0 dependency set (`apps/api/uv.lock`, `apps/web/pnpm-lock.yaml`, the
Dockerfiles); it is not legal advice.

## By service

### Control plane (`api`, `worker`) and dashboard (`web`)

Permissive licenses only: FastAPI, Starlette, Pydantic, SQLAlchemy, Alembic, asyncpg,
redis-py, boto3, cryptography, argon2-cffi, PyJWT (MIT, BSD or Apache-2.0); Next.js, React,
TanStack Query, Base UI and shadcn components, Recharts (MIT).

The dashboard's voice client:

| Package | Version | License |
| --- | --- | --- |
| `@pipecat-ai/client-js` | 1.15.0 | BSD-2-Clause |
| `@pipecat-ai/small-webrtc-transport` | 1.11.1 | BSD-2-Clause |
| `@pipecat-ai/websocket-transport` | 1.8.1 | BSD-2-Clause |
| `@daily-co/daily-js` (a dependency of the WebRTC transport) | 0.94.x | BSD-2-Clause |

VoiceOS configures the transports with Pipecat's local `WavMediaManager`, so the browser
never loads Daily's remote call-machine bundle or reports to Sentry; daily-js is present
in the bundle only as a dependency.

### Voice runtime (`runtime`)

| Component | Version | License |
| --- | --- | --- |
| Pipecat (`pipecat-ai`) | 1.14.0 | BSD-2-Clause |
| aiortc (WebRTC) | from the lockfile | BSD-3-Clause |
| ONNX Runtime | from the lockfile | MIT |
| Silero VAD model | shipped inside the Pipecat package | MIT (upstream Silero VAD) |
| Smart Turn v3 model (`smart-turn-v3.2-cpu.onnx`) | shipped inside the Pipecat package | BSD-2-Clause (as part of Pipecat) |
| Provider SDKs (OpenAI, Anthropic, Deepgram, Sarvam) | from the lockfile | MIT or Apache-2.0 |

### Speech server (`speech`)

| Component | Version | License | How it is used |
| --- | --- | --- | --- |
| faster-whisper | 1.2.1 | MIT | Imported by `voiceos/speech/models.py` |
| CTranslate2 | from the lockfile | MIT | Whisper inference |
| Whisper model weights (CTranslate2 conversions) | tiny, base, small | MIT | Downloaded by `voiceos models` |
| kokoro-onnx | 0.6.1 | MIT | Imported by `voiceos/speech/models.py` |
| Kokoro-82M weights (`kokoro-v1.0.int8.onnx`, `voices-v1.0.bin`) | v1.0 | Apache-2.0 | Downloaded and checked against pinned SHA-256 |
| **phonemizer** (a dependency of kokoro-onnx) | 3.4.0 | **GPL-3.0-or-later** | Imported in the speech server process |
| **espeak-ng** (Debian package, Kokoro's phonemizer backend) | 1.51 | **GPL-3.0-or-later** | Installed only in the speech image; its shared library is loaded into the speech server process through phonemizer |
| **espeakng-loader** (a dependency of kokoro-onnx) | 0.2.4 | ships a copy of `libespeak-ng` (GPL-3.0-or-later) | Installed with kokoro-onnx |

**What this means.** The GPL-licensed phonemizer and espeak-ng run inside the speech
server, a separate service that the rest of VoiceOS reaches only over HTTP
(`/v1/audio/speech`). No other image contains them: the control plane, runtime, worker and
web images are built without the `speech` extra and without espeak-ng. VoiceOS's own source
stays MIT. If you **distribute** the speech image (or a derivative), you distribute GPL
components and must meet the GPL's obligations for them, such as offering their source
(Debian source packages and the PyPI source distributions). Running it for yourself, as
a network service, is not distribution under GPL-3.0.

To avoid GPL components entirely, do not deploy the speech service for synthesis: point
the agent's TTS at another provider (any OpenAI-compatible TTS server, ElevenLabs,
Cartesia or Sarvam). Whisper speech recognition has no GPL dependency.

### TURN relay (`turn`)

coturn 4.6.3 (`coturn/coturn` image), BSD-3-Clause, run unmodified as a separate program.

### Local AWS emulation

Floci 2.3.0 (`floci/floci`), MIT, used only for local development and tests.

## Considered and excluded

| Component | Why not |
| --- | --- |
| Piper TTS (`piper-tts` 1.8.0) | GPL-3.0 for the Python package itself, and Kokoro ships Hindi voices; note that Kokoro's phonemizer still brings GPL code into the speech image (above) |
