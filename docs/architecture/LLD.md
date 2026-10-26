# Low-level design

How the code is laid out and how the main paths run, module by module. The
[HLD](HLD.md) has the picture; this is the map.

## Packages

```
apps/api/src/
  voiceos/
    core/          config (Settings, RuntimeSettings, SpeechSettings), contract (the runtime
                   and control-plane models), tokens (session tokens), sealing, security
                   (passwords, SDK key hashing), cache (ConfigCache), kv (Redis or memory),
                   db, storage, money, middleware, logs, tracing, errors, container
    auth/ users/ keys/ audit/          dashboard identity, roles, SDK keys, the audit log
    providers/     provider rows, URL and adapter validation, classification, sealing, Test
    agents/        agent rows, templates, versioning, resolve() for the runtime
    sessions/      tickets (start), report ingestion, cost, history, erase, retention purge
    analytics/     usage_hourly rollup and the overview
    benchmarks/    latency benchmark runs, the headless voice client, committed utterances
    privacy/       redaction (e-mail, phone, card, Aadhaar, PAN)
    internal/      /internal/agents/{id} and /internal/sessions for the runtime
    system/        /healthz, /readyz, /metrics, /api/v1/system
    runtime/       the voice runtime: app (transports, admission, ICE), pipeline, turns
                   (TurnRecorder), router (TurnRouter, ResponseCache), providers (Pipecat
                   services per adapter), services/ (speech server TTS, phrase cache),
                   tools, control (HttpControlPlane)
    speech/        the local speech server: models (faster-whisper, Kokoro), download, app
    demo/          seed-demo
    worker.py      purge and benchmark loop
    cli.py         serve, runtime, speech, worker, migrate, revision, create-owner, models,
                   seed-demo, openapi
  mockproviders/   deterministic STT, LLM and TTS with fault injection (tests and demo only)
apps/web/src/
  app/             routes only
  features/<domain>/  api.ts (TanStack Query hooks) and components/
  components/      shared composites and components/ui (shadcn on Base UI)
  lib/             generated API types, query keys, formatting, chips, glossary, snippets
  middleware.ts    per-request Content-Security-Policy and the sign-in redirect
```

Dependencies point inward (router, service, models), and a domain calls another domain's
service, never its tables. The runtime imports only `core/contract.py`, `core/config.py`
and `core/tokens.py` from the control plane side; it never touches the database.

## Starting a session

`sessions/router.py` has two entry points that end in `sessions.service.start()`:

- `POST /api/v1/sessions` for a signed-in user (`subject = user:<id>`, origin from the
  request's `Origin`),
- `POST /v1/sessions` for an SDK key (`subject = key:<id>`, scoped by the key's
  `agent_ids` and `allowed_origins`, rate limited per key).

`start()` resolves the agent through the config cache, issues a token
(`core/tokens.issue`: HS256, audience `voiceos-runtime`, 60 s, claims `sid`, `agent`,
`origin`, `sub`) and returns a `SessionTicket` with the runtime URLs built from
`RUNTIME_PUBLIC_URL` and the disclosure built from the agent's external providers.

## Admission in the runtime

`runtime/app.py` `Sessions.admit()` runs for `POST /api/offer` and `/ws`:

1. a token must be present (401 `missing_token`) and verify (401 `invalid_token`),
2. a browser `Origin` must match the token's origin (403 `origin_mismatch`), and for the
   WebSocket be in `ALLOWED_ORIGINS` (403),
3. the session id must not have been used on this instance in the last 120 s (409
   `token_used`),
4. fewer than `MAX_SESSIONS` calls may be live (503 `runtime_busy`).

Then the agent is loaded (`HttpControlPlane.agent`, cached `AGENT_CACHE_TTL_S`; 404
`unknown_agent` or 503 `control_plane_unavailable`). A refused WebSocket handshake is
answered with the real status through the ASGI denial-response extension.

## The call

`runtime/pipeline.run_session()` builds the providers (`runtime/providers.py`), the
`LLMContextAggregatorPair` with Silero VAD and the turn strategies, the `TurnRouter`, an
`LLMSwitcher` when a small model is configured, and the Pipecat `PipelineWorker` with two
observers: the `TurnRecorder` and `_AnswerStore` (fills the response cache). The greeting,
if any, is spoken with a `TTSSpeakFrame`; otherwise the LLM opens. The session ends on
client disconnect, the `end_conversation` tool, the idle timeout, the maximum duration or
an unhandled error, and always returns a `SessionReport`.

## Reporting

`HttpControlPlane.report()` posts the report to `/internal/sessions` (three attempts,
0.5 s, 1 s and 2 s backoff). `sessions.service.ingest()`:

1. returns early if the session id exists (idempotent),
2. resolves the agent and computes cost (`sessions/cost.py`),
3. stores the session row, then its turns: words redacted when the agent's `redact_pii`
   is on, and kept only when `transcript_retention_days` is above 0 (with
   `transcript_expires_at = ended_at + days`),
4. upserts the `usage_hourly` row in the same transaction.

## The worker

`worker.tick()` purges expired transcripts (500 sessions per batch: words set to null,
`transcript_stored` false) and runs at most one queued benchmark. A benchmark holds
`sessions` calls per agent through the runtime's internal URL with the headless client
(`benchmarks/client.py`), each speaking one committed utterance in the agent's language,
then reads the turns the runtime reported and stores percentiles, stage averages and the
machine description.

## The dashboard

Server state only through TanStack Query hooks in `features/<domain>/api.ts`, with typed
calls generated from `docs/api/openapi.yaml` (`pnpm gen:api`). The Talk page
(`features/talk/use-voice-session.ts`) asks for a ticket, fetches ICE servers, and
connects with the Pipecat client: `SmallWebRTCTransport` (all ICE candidates gathered
before the offer) or `WebSocketTransport`, both with Pipecat's local `WavMediaManager`.
"Auto" tries WebRTC for 8 seconds, then takes a fresh ticket (tokens are single use) and
falls back to WebSocket.
