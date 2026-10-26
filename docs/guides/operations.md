# Operations

Running VoiceOS day to day: capacity, secrets, models, health and metrics.

## Services and what they need

| Service | Scales on | Notes |
| --- | --- | --- |
| `api` | Requests | Stateless; run several behind the load balancer |
| `runtime` | Concurrent calls | Each instance admits `MAX_SESSIONS`; `/readyz` answers 503 when full |
| `speech` | Speech CPU (or GPU) | `SPEECH_CONCURRENCY` model calls per kind, `SPEECH_THREADS` threads each |
| `worker` | Rarely | Purge and benchmarks; one is enough, more are safe |
| `web` | Requests | Stateless |
| `turn` | Relayed media bandwidth | One instance per zone; list every relay in `ICE_URLS` |

## Runtime capacity and draining

- Size `MAX_SESSIONS` by measurement: hold calls at increasing concurrency (the benchmark,
  or several Talk pages) and watch `voiceos_runtime_response_seconds` and the speech
  service's CPU. Response time rising with concurrency means the speech service, not the
  runtime, is the limit.
- `GET /readyz` on the runtime returns `{"status": "ready" | "busy", "sessions", "capacity"}`
  and 503 when busy, so a load balancer health check takes a full instance out of
  rotation for new calls.
- On shutdown the runtime cancels its calls and reports them with `end_reason=shutdown`. To
  deploy without cutting calls, give tasks a stop timeout longer than your usual call and
  stop sending new calls to an instance before stopping it (an ECS deployment drains the
  target first; set the target group's deregistration delay to cover a call).

## Secrets and rotation

| Secret | Used by | Rotation |
| --- | --- | --- |
| `SESSION_SECRET` | api | Rotating signs every dashboard user out |
| `API_KEY_PEPPER` | api | Rotating invalidates every SDK key; create new keys first |
| `RUNTIME_TOKEN_SECRET` | api and runtime | Must change on both at once; tickets live 60 s, so a rolling change only fails tickets issued in that window |
| `INTERNAL_API_TOKEN` | api and runtime | Must change on both; reports during the window are retried three times, then dropped |
| `TURN_SECRET` | turn (coturn) and runtime (`TURN_PASSWORD`) | Change both; credentials already issued stop working, so calls in progress keep their media but new calls need the new secret |
| `LOCAL_MASTER_KEY` | api (`KEY_MODE=local`) | Re-enter provider keys after changing it, or use `KEY_MODE=kms` (KMS rotates its key material yearly without re-sealing) |
| Provider API keys | sealed in the database | Edit the provider on the dashboard and paste the new key |
| SDK keys | your backends | Create a new key, deploy it, revoke the old one |

On AWS the Terraform `secrets` module stores the application secrets in
`<name_prefix>/app` and the TURN secret in `<name_prefix>/turn`; ECS injects them as
environment variables, so a rotation needs a new deployment of the services that read them.

## Models

- The speech service reads models from `SPEECH_MODELS_DIR`. `voiceos models --dir <dir>
  --whisper tiny,base,small` downloads them (Kokoro files are checked against pinned
  SHA-256). Locally the one-shot `models` container fills the `models` volume; on AWS an
  init container downloads them into the task's storage at start.
- `WHISPER_PRELOAD` sizes load at start; others load on first use (the first request with a
  new size is slow).
- `GET /readyz` on the speech server reports which models are loaded.

## Health and metrics

| Endpoint | Service | Meaning |
| --- | --- | --- |
| `/healthz` | api, runtime, speech | The process is up |
| `/readyz` | api | Postgres reachable (Redis reported, never decisive) |
| `/readyz` | runtime | Capacity left (503 when busy) |
| `/readyz` | speech | Models loaded |
| `/api/v1/system` | api | Configuration summary and a runtime probe, shown on the Settings page |
| `/metrics` | api, runtime; worker on `WORKER_METRICS_PORT` | Prometheus |

Metrics worth alerting on:

| Metric | What it tells you |
| --- | --- |
| `voiceos_runtime_response_seconds` | Response time per turn (histogram) |
| `voiceos_runtime_sessions_active` | Calls in progress per runtime instance |
| `voiceos_runtime_sessions_total{transport,end}` | Finished calls by end reason (watch `error`) |
| `voiceos_runtime_rejected_total{reason}` | Refused connections (`runtime_busy` means add capacity) |
| `voiceos_sessions_started_total{source}` | Tickets issued (dashboard or SDK) |
| `voiceos_sessions_reported_total{end_reason,transport}` | Sessions stored |
| `voiceos_transcripts_purged_total` | Retention at work |
| `voiceos_dependency_errors_total{dependency,operation}` | Redis and other dependency failures |

On AWS the `observability` module adds CloudWatch alarms (5xx, latency, unhealthy targets,
CPU and memory, database and cache, the TURN relay's health) and a dashboard, plus an
optional alarm on failed voice sessions from the runtime's logs.

## Data

- Transcripts expire by agent retention; the worker clears them in batches of 500.
- Session rows and turns without words stay; prune them with your own database policy if
  needed. `usage_hourly` keeps the analytics.
- Back up Postgres (RDS automated backups on AWS). There is no audio to back up.
