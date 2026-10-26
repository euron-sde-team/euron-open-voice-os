# High-level design

Euron Open VoiceOS runs real-time voice agents on your own infrastructure. A caller talks
in a browser (or through your app with the SDK); the agent hears them, thinks with a
language model and answers out loud. Every turn is timed stage by stage, every session is
costed from the usage its providers reported, and nothing about the caller leaves your
servers unless an agent is configured to use an external provider, which the caller is
told before the call starts.

<p align="center"><img src="../assets/diagrams/architecture.svg" alt="VoiceOS architecture" width="100%"></p>

## Goals and non-goals

| Goals | Non-goals (0.1.0) |
| --- | --- |
| A voice agent that works with no cloud account: local Whisper and Kokoro, any OpenAI-compatible LLM | Telephony (SIP, PSTN numbers): browser and SDK clients only |
| Switch STT, LLM and TTS per agent by configuration, between self-hosted and hosted providers | Storing call audio (there is no recording path) |
| Measure the latency a caller feels, per turn and per stage, from frames that actually flowed | Training or fine-tuning speech models |
| Cost per session from reported usage and configured prices, never a guessed zero | Multi-tenant SaaS: one organisation per install |
| Privacy by default: no audio stored, transcripts redacted and expiring, external processing disclosed | Video |

## Components

| Component | What it does | Where |
| --- | --- | --- |
| Dashboard (`web`) | Next.js 15: talk to an agent, agents and providers, overview, sessions, benchmarks, SDK keys, users, audit, settings. Proxies `/api/*` and `/v1/*` to the API so the browser has one origin | `apps/web/` |
| Control plane (`api`) | `/api/v1/*` for the dashboard, `POST /v1/sessions` for SDK keys, `/internal/*` for the runtime. Owns every row: providers (sealed keys), agents, keys, sessions, rollups, users, audit | `apps/api/src/voiceos/` (one package per domain) |
| Voice runtime (`runtime`) | One Pipecat pipeline per call, over WebRTC or WebSocket. No database: loads the agent from the control plane, reports the finished session back | `voiceos/runtime/` |
| Speech server (`speech`) | faster-whisper and Kokoro behind OpenAI-compatible endpoints, internal only | `voiceos/speech/` |
| Worker (`worker`) | Transcript retention purge and latency benchmark runs (which hold real calls through the runtime) | `voiceos/worker.py` |
| TURN (`turn`) | coturn, so WebRTC media reaches the runtime when direct UDP cannot | Compose service; EC2 behind an NLB on AWS |
| Postgres | Everything durable | RDS on AWS |
| Redis (optional) | Config version stamp, per-key and per-IP rate-limit windows | ElastiCache on AWS |
| Object storage | Wired (local disk or S3) and provisioned, but no 0.1.0 path writes to it: benchmark results live in Postgres and audio is never recorded. Reserved for opt-in recordings and report exports | S3 (Floci locally) |
| KMS | Seals provider credentials, encrypts storage | KMS (Floci locally) |

One Python package holds the control plane, the runtime, the speech server and the
worker; one Dockerfile builds three images from it (`api`, `runtime`, `speech`), so each
container installs only what it runs (the `runtime` and `speech` extras).

## Starting a call

1. The dashboard (signed-in user) or your backend (SDK key, `POST /v1/sessions`) asks the
   control plane for a session. The control plane checks the user's role, or the key's
   agent and origin scope and rate limit.
2. It resolves the agent (config cache, below) and returns a ticket: the runtime's
   WebSocket, offer and ICE URLs, a session token, and the **disclosure** (the external
   providers the call will use, as a sentence to show the caller).
3. The browser fetches TURN credentials from the runtime's `/api/ice` with the token, then
   connects over WebRTC (`POST /api/offer`) or WebSocket (`/ws`).
4. The runtime admits the token once (signature, audience, expiry, origin, not yet used,
   capacity), loads the agent from `GET /internal/agents/{id}` and starts the pipeline.

## During a call

`transport in -> STT -> user turn (Silero VAD + turn detection) -> TurnRouter -> LLM ->
TTS -> transport out`. The turn router answers exact repeats from the response cache or
sends short turns to a smaller model; the TTS replays repeated phrases from the phrase
cache. A turn recorder observes every frame and measures each stage. See
[voice-pipeline.md](voice-pipeline.md).

## After a call

The runtime posts a `SessionReport` (turns with text and timings, usage, end reason,
external providers, errors) to `POST /internal/sessions`, retrying three times with
backoff. The control plane stores it once (the session id is the primary key), computes
cost from the agent's provider prices, redacts and keeps the words only if the agent's
retention allows, and upserts the hourly rollup in the same transaction.

## Caching layers

| Layer | What is cached | Where | Key | TTL and invalidation |
| --- | --- | --- | --- | --- |
| Config cache | Resolved agents (providers with opened credentials), SDK key rows | Control plane process memory, single flight per key, at most 10,000 entries | `agent:<id>`, `key:<prefix>` | 5 s TTL. Every provider, agent and key write calls `invalidate()`, which bumps `vos:cfg:version` in the KV store; each process checks the stamp at most once a second and drops its entries when it moved. Without Redis the stamp is per process, exact for one replica. A load that raced an invalidation is returned but not stored |
| Runtime agent cache | `ResolvedAgent` fetched from `/internal/agents/{id}` | Runtime process memory | agent id | `AGENT_CACHE_TTL_S` (5 s). No invalidation message: an edit reaches new calls within the TTL; calls in progress keep the version they started with |
| TTS phrase cache | Synthesized audio of short phrases (greetings, confirmations), at most 200 characters each | Runtime process memory, LRU bounded at 64 MB, no single entry above an eighth of it | SHA-256 of provider id, adapter, model, voice and the exact text | Process lifetime with LRU eviction. A voice or model change changes the key, so the wrong audio is never replayed. Hits and the characters they saved are reported per session as savings |
| Response cache | The agent's answer to an exact repeat of a question | Runtime process memory, LRU of 5,000 entries | SHA-256 of agent id, agent **version** and the normalized question (lowercased, punctuation removed) | 24 h. Any edit bumps the agent version, so old answers are never replayed. Only agents that opt in and have no tools; an answer is stored only after it played without interruption |
| Rate limits | Sliding-window counters per SDK key and per sign-in IP | Redis (atomic), or per process | `vos:rl:<name>:<window>` | One minute windows |
| Analytics | Overview aggregates | Postgres `usage_hourly`, written in the report's transaction, plus `Cache-Control: private, max-age=15` on the overview | hour, agent, transport | Exact at write time; a browser may reuse an overview for 15 s |
| Dashboard | Server state | TanStack Query | per resource (`apps/web/src/lib/query-keys.ts`) | `staleTime` per kind: analytics 15 s, config 30 s, live lists 5 s, static 5 min; mutations invalidate exactly the keys they touched |

Correctness of invalidation is tested: the config cache unit tests
(`tests/unit/core/test_kv_cache.py`), an integration test that edits an agent and reads it
back through `/internal/agents/{id}` (`test_providers_agents.py`), the response cache key
and expiry unit tests (`tests/unit/domain/`), and the voice test that asks the same
question twice and sees one LLM call (`test_voice_behaviour.py`).

## Scalability

- The control plane is stateless: state lives in Postgres, Redis and S3. Run N replicas
  behind the load balancer.
- The runtime holds calls, so it is stateful for their duration only. Each instance admits
  at most `MAX_SESSIONS` concurrent calls and answers 503 `runtime_busy` past that
  (`/readyz` also turns 503, so a load balancer stops sending new calls). The browser
  gathers all ICE candidates before sending its offer, so no follow-up request has to
  reach the same instance.
- The speech server is CPU bound. `SPEECH_CONCURRENCY` bounds model calls in flight
  (separately for recognition and synthesis) and `SPEECH_THREADS` the threads per call;
  keep their product within the cores the container really has.
- Workers scale horizontally: the purge is batched idempotent UPDATEs, benchmark runs are
  claimed with `FOR UPDATE SKIP LOCKED`, and at most one benchmark is queued or running
  (a partial unique index).
- Dashboards read hourly rollups and keyset-paginated session lists, never full scans.

## Failure behaviour

| Dependency down | Effect |
| --- | --- |
| An STT or LLM provider (error or timeout) | The caller hears a spoken fallback ("Sorry, I did not catch that", "I am having trouble answering"), the error is recorded on the turn and the session, the call continues |
| A TTS provider | The error is recorded; the call continues, silently for that answer |
| Control plane, when a call starts | The runtime refuses with 503 `control_plane_unavailable` |
| Control plane, when a call ends | The report is retried three times with backoff, then logged as dropped |
| Client disconnects | The pipeline is cancelled, the slot freed, the session reported with `client_left` |
| Runtime restarts mid-call | The call ends; its session is reported with `shutdown` |
| Redis | Rate limits pass, config caches fall back to their TTL, `/readyz` reports degraded but stays ready |

## Deployment

Locally: Docker Compose with Floci for S3, KMS and Secrets Manager, provisioned by the
same Terraform modules as AWS (`make up`). On AWS: ECS Fargate for api, runtime, speech,
worker and web behind one ALB (the runtime on its own host name), coturn on EC2 behind a
network load balancer, RDS, ElastiCache, S3, KMS, Secrets Manager and CloudWatch, from
`infra/terraform/envs/aws-dev` or `aws-prod`. See [deploy-aws.md](../guides/deploy-aws.md).

## Related documents

[LLD](LLD.md), [voice pipeline](voice-pipeline.md), [latency and cost](latency-and-cost.md),
[privacy](privacy.md), [data model](data-model.md), [security](security.md),
[threat model](threat-model.md), [licenses](licenses.md), [decision records](adr/).
