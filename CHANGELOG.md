# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-27

First public release: the voice runtime, local speech, the control plane and the
dashboard.

### Added

- Voice runtime on Pipecat 1.14: one pipeline per call (transport, Silero VAD, speech to
  text, turn detection, language model, text to speech), over WebRTC (SmallWebRTC on
  aiortc) or WebSocket (Pipecat protobuf frames), with TURN credentials minted per call.
- Turn taking: Smart Turn v3 or plain silence detection per agent, a configurable pause,
  barge-in with an optional minimum word count, and a bounded wait for slow transcripts.
- Local speech server: faster-whisper (tiny, base, small) and Kokoro (int8 ONNX, English
  and Hindi voices) behind OpenAI-compatible `/v1/audio/transcriptions` and
  `/v1/audio/speech`, with SHA-256 pinned Kokoro downloads and bounded concurrency.
- Providers per stage, switchable per agent by configuration: any OpenAI-compatible
  server (Ollama, vLLM, the VoiceOS speech server), Deepgram, Sarvam, Anthropic,
  ElevenLabs and Cartesia; a Test button per provider.
- Agents from five templates (receptionist, support agent, tutor, meeting assistant,
  Hindi tutor), with greeting, instructions, voice, language, tools (current time, end
  the call, FAQ lookup, a webhook), FAQ, limits and a version that bumps on every edit.
- Measured latency per turn: end of turn, speech to text, first LLM token, first TTS
  audio and the response a caller feels, from the end of their speech to the agent's
  first audio.
- Cost per session from the usage providers report (audio seconds, tokens, characters
  synthesized) and the list prices you configure, in integer nano-USD, with explicit
  "partial", "not reported" and "self-hosted" states instead of guessed zeros; the small
  model's tokens are counted apart and priced at its own provider's rate; each report
  carries the agent configuration the call ran with, so editing or disabling an agent
  mid-call changes nothing about its record, and a runtime shutdown still reports what was
  measured.
- Cost optimizer: a TTS phrase cache, a response cache for agents without tools that
  replays an answer only for an exact repeat of the whole conversation (never just the
  last question), and routing of short turns to a smaller model; both caches count as
  savings.
- Privacy defaults: no audio stored, transcript retention per agent (0 keeps no words),
  redaction of e-mail addresses (written or spoken), phone numbers, cards (Luhn) and other
  14 to 19 digit numbers, Aadhaar numbers (Verhoeff) and PAN (any case) before storage,
  including provider error messages, no conversation text in logs, and a disclosure of
  every external provider before a call.
- SDK: `POST /v1/sessions` with a `vos_` key scoped to agents and website origins, rate
  limited per key, returning a one-minute single-use session ticket.
- Latency benchmark: real conversations with up to five agents on committed Kokoro
  utterances in English and Hindi, run by the worker, labelled with the machine.
- Speech accuracy benchmark (`make wer`): word and character error rate on Google FLEURS
  for English, Hindi and Marathi through the speech service, labelled with the machine.
- Hindi and Marathi transcription is prompted in Devanagari when the caller sends no
  prompt, so Whisper stops writing them in Urdu or Latin script.
- Dashboard: talk to an agent in the browser, agents and their pipeline editor,
  providers, overview, sessions with per-turn waterfalls, benchmarks, SDK keys,
  integrations, users, audit log and settings, light and dark.
- Demo seed that holds real conversations through the runtime and replays them into a
  month of history.
- Terraform for AWS (VPC, RDS, ElastiCache, S3, KMS, Secrets Manager, ECR, ECS Fargate for
  api, runtime, speech, worker and web, ALB, CloudWatch) and a coturn TURN relay on EC2
  behind a network load balancer, plus a local stack on Floci provisioned by the same
  modules.
- Model downloads pinned by SHA-256 and fetched from ordered mirrors (plus your own with
  `VOS_KOKORO_MIRROR`), with retries, a stall timeout and resume; the models volume
  survives `make down`.

### Security

- The runtime accepts a connection only with a session token the control plane signed:
  HS256, audience `voiceos-runtime`, 60 seconds, bound to one agent, one session id and,
  for browsers, the page origin, and usable once across every runtime replica (claimed by
  an atomic insert in Postgres before the call starts).
- Refused handshakes carry their real status (401, 403, 409, 503) instead of a bare 403.
- Provider keys are sealed with AES-256-GCM or KMS, bound to their row, and never returned;
  moving a provider to another host requires its key again; provider and webhook URLs
  cannot target link-local or instance metadata addresses in any spelling (integer, hex,
  octal, trailing dot), and webhook hosts are re-checked after DNS resolution; a disabled
  provider receives nothing.
- Deleting an agent never widens an SDK key: a key whose only agent is deleted is revoked.
- Pipecat's own logging (the LLM context and every spoken sentence at DEBUG) is routed
  through the JSON logger with a WARNING floor and redacted, so callers' words never reach
  the logs.
- The speech server caps uploads at 25 MB and refuses WAV sample rates outside 8 to 96 kHz.
- The dashboard's Content-Security-Policy is built per request and allows connections only
  to its own origin and the runtime's; the microphone is allowed for this origin only; the
  browser client uses Pipecat's local media manager, so it never downloads code from a
  third-party CDN.
- The runtime reaches the control plane only with an internal token, on the private
  network; on AWS the load balancer answers 404 for `/internal/*`.
- The audit log is append-only at the database level; sign-in has lockout and a per-IP
  throttle; password changes end every other session.
