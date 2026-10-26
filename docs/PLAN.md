# Euron Open VoiceOS 0.1.0: build plan

Project 05 of the Euron open-source program. Repo `euron-open-voice-os`, display name
"Euron Open VoiceOS", product UI short name "VoiceOS". Rules: `../../CLAUDE.md`. Brief:
`../../briefs/05-voice-os.md` (it extends this plan; where they conflict the rules win).

Status: approved 2026-10-26; spikes 1 and 2 done (results below).

## Purpose

**Who:** developers and small teams who want a voice agent (a tutor, a receptionist, a
support line, a meeting helper) inside their own product, without renting a closed voice
platform per minute.

**Problem:** hosted voice agent platforms (Vapi, Retell, Bland) are fast to start with but
charge per minute on top of the model costs, decide which models you may use, and keep the
audio and transcripts on their servers. The open frameworks (Pipecat, LiveKit Agents) are
excellent but they are libraries: you still write the server, the browser client, provider
configuration, secrets handling, logging, retention, cost tracking and a dashboard.

**Outcome VoiceOS guarantees:** one `make up` gives you a running voice agent platform on
your own machine: talk to an agent in the browser within five minutes, with no cloud
account, using local speech recognition and synthesis. You choose the STT, LLM and TTS
provider per agent by configuration, you see what every conversation cost and how fast it
was (measured, never estimated without saying so), and audio never leaves your
infrastructure unless an agent is configured with a cloud provider, which VoiceOS discloses.

**The name is the contract.** An "OS" for voice agents must: run them (a real-time runtime
with turn-taking and barge-in), manage them (agents, providers, keys, users), and account
for them (sessions, transcripts under retention, latency and cost). Each of these is an
acceptance criterion below.

### Comparable products (researched October 2026)

| Product | Kind | What users expect from it | Our angle |
| --- | --- | --- | --- |
| Vapi, Retell, Bland | Hosted platforms | Fast setup, telephony, dashboards, per-minute pricing | Self-hosted, no platform fee, local models, cost transparency |
| Dograh (BSD-2) | Self-hostable platform | Visual workflow builder, telephony, call tracing | Local-first defaults with no cloud keys, honest latency and cost per turn, Indian language benchmarks, privacy defaults (no audio stored) |
| Pipecat (BSD-2) | Framework | Pipelines, transports, many provider services | We build on it, behind a small Euron runtime interface |
| LiveKit Agents (Apache-2.0) | Framework + media server | WebRTC infrastructure, agents SDK | Lighter: no media server needed for 0.1.0 |
| Vocode | Framework | Telephony-first agents | Not a platform; little recent activity |

What makes VoiceOS worth starring: talk to a working agent locally in minutes with zero API
keys; switch providers per agent from the dashboard; a per-turn latency waterfall (VAD, STT,
LLM first token, TTS first audio) and cost ledger for every conversation; privacy defaults
that store no audio; measured Hindi and Marathi results; and native hooks into the Euron
stack (TokenShield budgets, SmartRouter `model=auto`, ContextForge for long conversations).

## Acceptance criteria (each is an automated test)

| # | Criterion | Test |
| --- | --- | --- |
| AC1 | A person speaks in the browser and hears a spoken answer, over WebRTC and over WebSocket, with local STT and TTS and no cloud account | e2e: Chromium with a fake microphone playing a recorded question; transcript and agent reply appear, agent audio plays |
| AC2 | Barge-in: when the user starts speaking while the agent talks, agent audio stops and the in-flight LLM and TTS work is cancelled | integration: WebSocket client streams speech during agent audio; assert interruption event, no further agent audio frames, cancelled stages recorded |
| AC3 | Turn-taking: the agent waits through a mid-sentence pause and answers after the turn ends | integration: crafted audio with a pause; one user turn, one reply |
| AC4 | Providers switch per agent by configuration only | integration: the same agent run with provider set A, then set B, both succeed; no code change |
| AC5 | Provider secrets never reach a browser and are sealed at rest | integration: every provider read returns only a hint; database holds ciphertext bound to the row |
| AC6 | External processing is disclosed: an agent using a cloud provider shows it before a session starts, and each session records which providers received audio or text | integration + e2e |
| AC7 | No raw audio is stored by default; transcripts follow the agent's retention and redaction settings | integration: default session leaves no audio objects; redacted fields never stored; expired transcripts purged |
| AC8 | Latency is measured, not invented: per turn, time to first audio and each stage's timing are recorded; demo data comes from real runs | integration |
| AC9 | Cost per session: LLM tokens, STT audio seconds and TTS characters with estimated cost when usage and a price exist, and an explicit "not reported" otherwise | integration |
| AC10 | Provider failures are handled: STT, LLM or TTS timeout or error produces a spoken fallback and an event, never a hung session | integration with failure injection on mock providers |
| AC11 | A dropped client ends the session cleanly: pipeline cancelled, resources freed, session finalized | integration |
| AC12 | Concurrent sessions are isolated and capped per runtime instance (503 with a reason past the cap) | integration |
| AC13 | Access control: dashboard roles; SDK keys; short-lived session tokens bound to one agent; the runtime refuses any connection without one | integration |
| AC14 | Indian languages: a Hindi agent works end to end locally, and the benchmark reports word error rate for Hindi, Marathi and English on public recordings, labelled with model and hardware | benchmark + integration |
| AC15 | Cost optimizer: a repeated phrase is served from the TTS cache and an eligible repeated question from the response cache, both visible as savings; an agent can route to a smaller or local model | integration |
| AC16 | Five-minute path: create an agent from a template and talk to it, from the dashboard alone | e2e |

## Scope

### In 0.1.0

- **Voice runtime** (separate service from the control plane): Pipecat pipeline behind a
  small Euron runtime interface; transports SmallWebRTC (WebRTC, with a local TURN server
  for Docker) and WebSocket; Silero VAD plus Smart Turn v3; interruptions; session lifecycle
  (start, idle timeout, max duration, disconnect cleanup); per-instance session cap.
- **Providers** (one adapter file each, chosen by config):
  - STT: local Whisper (the `speech` service, CPU or GPU), OpenAI-compatible transcription (OpenAI,
    Groq, self-hosted Whisper servers), Deepgram, Sarvam (Indian languages).
  - LLM: OpenAI-compatible chat (OpenAI, Ollama, vLLM, TokenShield, SmartRouter), Anthropic.
  - TTS: local Kokoro (the `speech` service; Apache-2.0 weights, includes Hindi voices), OpenAI-compatible speech,
    ElevenLabs, Cartesia, Sarvam (Indian languages).
  - Mock providers (a Compose service) for tests and the zero-key demo, with failure
    injection.
- **Agents:** system prompt, greeting, language, voice, providers per stage, turn and
  interruption settings, max session length, a small tool set (current time, FAQ lookup over
  agent-attached snippets, end conversation, HTTP webhook to an allowlisted URL), templates
  (tutor, receptionist, support agent, meeting assistant, Hindi tutor).
- **Pipeline view** in the builder: the agent's STT, LLM, tools and TTS shown as a
  connected diagram you configure node by node. The free-form node graph editor is roadmap.
- **Accounting:** sessions, turns (transcript, per-stage timings, interruptions), usage
  ledger (tokens, audio seconds, characters, estimated cost), hourly rollups for dashboards.
- **Privacy:** no audio stored by default (opt-in per agent, to S3, with expiry);
  transcript retention days per agent (0 = do not store); redaction of emails, phone
  numbers, card numbers, Aadhaar and PAN before storage; external-provider disclosure.
- **Cost optimizer:** TTS phrase cache, response cache for eligible turns (agent opt-in,
  deterministic settings, no tools), routing to a smaller or local model per agent, with
  savings shown.
- **Control plane API** (FastAPI) and **dashboard** (Next.js): Talk, Overview, Agents,
  Providers, Sessions (with a turn waterfall), Benchmarks, Integrations (web embed snippet,
  REST, Pipecat client compatibility), API keys, Users, Audit log, Settings.
- **SDK surface:** REST to create a session token, a drop-in web widget script, and the
  standard Pipecat JS client against our runtime.
- **Benchmarks:** latency (time to first audio, end-to-end) per provider combination on the
  machine that ran it, and WER for English, Hindi and Marathi on a small public sample
  (FLEURS, CC-BY-4.0, fetched by the benchmark script with attribution).
- Everything the rules require: Docker Compose, Floci, Terraform for AWS, all test layers,
  QA screenshots, docs.

### Roadmap (not 0.1.0)

Free-form visual node graph editor; telephony (Twilio, SIP); knowledge bases beyond agent
snippets; local Marathi TTS (IndicF5 needs a GPU and gated weights); Piper as an optional
separate service (GPL-3.0, never linked into VoiceOS); voice cloning; mobile SDKs; multi-
tenant organisations; Kubernetes.

## Design

### Services

| Service | What it does | Port |
| --- | --- | --- |
| `web` | Next.js dashboard and Talk page | 4510 |
| `api` | Control plane: auth, agents, providers, sessions, usage, analytics, session tokens | 4530 |
| `runtime` | Voice runtime: WebRTC offer/answer, WebSocket audio, Pipecat pipelines | 4535 |
| `speech` | Local speech models behind OpenAI-compatible endpoints: `/v1/audio/transcriptions` (faster-whisper) and streamed `/v1/audio/speech` (Kokoro). Its own container because Kokoro needs espeak-ng (GPL-3.0), kept out of the MIT code, and so models can scale or move to a GPU on their own | 4537 |
| `worker` | Retention purge, rollups, benchmark runs | n/a |
| `mock-providers` | OpenAI-compatible LLM, STT and TTS stand-ins with failure injection | 4550 |
| `turn` | coturn, so WebRTC works from Docker Desktop | 4578 (+ small relay range inside 4581 to 4589) |
| `postgres`, `redis`, `floci` | Data, caches and session cap, AWS APIs | 4542, 4579, 4566 |
| `models` (one-shot) | Downloads local Whisper, Kokoro, Smart Turn and Silero weights into a volume | n/a |

The runtime never reads the database directly: it fetches an agent's resolved config
(including opened provider secrets) from an internal API with a service token, caches it
briefly, and posts turn and usage events back. The control plane can be slow or restarted
without dropping live audio.

### Session flow

1. Browser asks `api` for a session token for agent X (dashboard session or `vos_` SDK key).
2. Browser connects to `runtime` with the token (WebRTC offer, or WebSocket upgrade).
3. Runtime verifies the token (signed, 60 s to start, bound to agent and origin), loads the
   agent config, builds the pipeline: transport in, VAD, Smart Turn, STT, context, LLM
   (tools), TTS (phrase cache), transport out.
4. Each turn emits timings: user stop, STT final, LLM first token, TTS first audio, first
   audio sent. Interruptions cancel downstream work and are recorded.
5. On end (hang-up, disconnect, idle, max length, failure) the runtime finalizes the
   session: usage ledger, transcript (redacted, if retained), disclosure record.

### Data model (Postgres)

`users`, `api_keys` (SDK keys), `providers` (kind, adapter, base URL, sealed key, hint,
external flag, prices), `agents` (prompt, greeting, language, voice, provider per stage,
turn settings, tools, privacy and cache settings, template origin), `agent_snippets`,
`sessions` (agent, transport, status, end reason, started/ended, providers used, external
disclosure), `turns` (append-only: text when retained, stage timings, interruption,
tokens), `usage_events` (append-only ledger), `usage_rollups_hourly`, `benchmark_runs`,
`audit_log`, `revoked_sessions`.

### Caching layers

Agent config in the runtime (short TTL, version stamp invalidation like ContextForge),
TTS phrase cache (Redis or in-process, keyed by provider, voice, language and text hash),
response cache (opt-in per agent, keyed by normalized utterance plus agent version),
analytics rollups, dashboard React Query. Documented with TTLs in `HLD.md`.

### Terraform modules

The ContextForge set (network, database, cache, storage, kms, secrets, ecr, service,
observability) plus: the runtime as its own ECS service behind the ALB for WebSocket and
signalling, and a `turn` module (coturn on ECS behind an NLB with UDP) so WebRTC works in
AWS. `make tf-aws-on-floci` applies all of it against a throwaway Floci on port 4596.

## Ports (project 05)

web 4510, api 4530, runtime 4535, speech 4537, postgres 4542, redis 4579, floci 4566, mock providers
4550, TURN 4578 with relay ports 4581 to 4589, tf-aws-on-floci 4596. Compose project
`voiceos`. All overridable in `deploy/compose/.env`.

## Test plan

- **Unit:** adapters (request shapes, usage parsing, errors), redaction, cost math, caches,
  token signing, turn timing math, template validation. Vitest for dashboard logic.
- **Integration:** the real api and runtime against Postgres, Redis, Floci and mock
  providers, with a Python WebSocket client streaming real audio files: AC2 to AC13, AC15.
  Local Whisper and Kokoro run in the integration suite with the smallest models.
- **E2E:** Playwright Chromium with `--use-file-for-fake-audio-capture` so a real recorded
  question goes through the microphone path: AC1, AC6, AC16, plus every dashboard journey.
- **Option matrix:** cache Redis or none, keys local or KMS, storage disk or S3, transport
  WebRTC or WebSocket.
- **Benchmarks:** `make benchmark` (latency per provider combination, WER per language),
  results committed with the hardware they ran on.
- **QA:** Puppeteer sweep of every page, light and dark, desktop and phone.

### Honest labelling

Latency numbers state the machine, the models and whether a GPU was used. Local providers
show cost as "self-hosted (hardware not included)", never as free savings. Cloud provider
results appear only when someone runs the benchmark with their own keys; the committed
numbers use local and mock providers and say so. WER uses a small public sample and says
how many utterances.

## Spike results (2026-10-26, arm64 Docker on a 12-core laptop CPU, no GPU)

| Model | English | Hindi |
| --- | --- | --- |
| Whisper tiny, int8 | 0.30 s for 3.7 s of speech, correct | 0.41 s, wrong (romanized) |
| Whisper base, int8 | 0.52 s, correct | 0.88 s, wrong script |
| Whisper small, int8 | 2.4 s, correct | 2.8 s, correct Devanagari |
| Kokoro int8 | 2.2 s to synthesize 3.7 s | 0.9 s to synthesize 3.5 s |

Decisions: English agents default to Whisper `base`; Hindi agents default to Whisper `small`
locally (slow on CPU, stated in the UI) with Sarvam or a GPU recommended for snappy turns;
TTS streams sentence by sentence so the first audio waits only for the first sentence.
`kokoro-v1.0.int8.onnx` is as good and as fast as the full model and a third of the size.
On macOS the `espeakng-loader` wheel ignores its data path, one more reason the speech
models run in a Linux container with the distribution's `espeak-ng`.

## Risks and first spikes

1. **WebRTC from Docker Desktop:** aiortc behind Docker NAT needs TURN. Spike: SmallWebRTC
   with local coturn, a browser on the host, audio both ways. Fallback: WebSocket stays a
   first-class transport.
2. **CPU latency:** Whisper and Kokoro on CPU in an arm64 container. Spike: measure time to
   first audio with `base` Whisper and Kokoro; pick defaults that keep a conversation
   usable, and report the numbers as measured.
3. **Pipecat 1.14 API surface:** pin the version, wrap it behind the Euron runtime
   interface so upgrades touch one package.
4. **Hindi and Marathi quality locally:** Whisper handles both, unevenly; Kokoro has Hindi
   voices but no Marathi. Marathi speech output in 0.1.0 needs a cloud provider (Sarvam);
   the docs and benchmark say so plainly.
