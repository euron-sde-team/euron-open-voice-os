# Configuration reference

Every setting is an environment variable, read once at boot by
`apps/api/src/voiceos/core/config.py` (pydantic settings, case-insensitive). The variable
name is the upper-case field name, with one exception: the cloud mode is read only from
`VOICEOS_CLOUD`. Each service reads its own settings class: `Settings` for the control
plane (api, worker, CLI), `RuntimeSettings` for the voice runtime and `SpeechSettings` for
the speech server. `ENVIRONMENT` and `LOG_LEVEL` are common to all three.

## Production boot guards

With `ENVIRONMENT=production`, the control plane refuses to start and lists every problem
it finds:

- `SESSION_SECRET`, `API_KEY_PEPPER`, `RUNTIME_TOKEN_SECRET` and `INTERNAL_API_TOKEN` must
  each be at least 32 characters, must not be a known placeholder (`change-me`, `dev`,
  `secret`, `replace-with-output-of-make-env`, empty) and must not contain
  `not-for-production` (the development defaults do).
- The four must all differ.
- With `KEY_MODE=local`, `LOCAL_MASTER_KEY` must pass the same test. Or use `KEY_MODE=kms`.
- With `VOICEOS_CLOUD=aws`, `AWS_ENDPOINT_URL` must be unset.
- `COOKIE_SECURE` must be `true`.

The runtime applies the same test to `RUNTIME_TOKEN_SECRET` and `INTERNAL_API_TOKEN`. In
`development` and `test` none of these checks run, which is why the local stack can use an
emulator endpoint and plain HTTP cookies.

## Common

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development`, `test` or `production` (turns the boot guards on) |
| `LOG_LEVEL` | `INFO` | Structured JSON logs to stdout |

## Control plane (api, worker, CLI)

| Variable | Default | Meaning |
| --- | --- | --- |
| `VOICEOS_CLOUD` | `local` | `local`, `floci` or `aws`; informational, plus the `AWS_ENDPOINT_URL` guard |
| `DATABASE_URL` | `postgresql+asyncpg://voiceos:voiceos@localhost:4542/voiceos` | Postgres (asyncpg driver) |
| `DB_POOL_SIZE` | `10` | Connections per process |
| `DB_MAX_OVERFLOW` | `20` | Extra connections under burst |
| `REDIS_URL` | empty | Redis for the config version stamp and rate limits. Empty: in process (exact for one replica) |
| `MEMORY_CACHE_MAX_BYTES` | `64000000` | Bound of the in-process KV store when Redis is absent |
| `SESSION_SECRET` | development value | Signs dashboard sessions |
| `API_KEY_PEPPER` | development value | HMAC pepper for SDK key secrets |
| `SESSION_TTL_HOURS` | `12` | Dashboard session lifetime |
| `COOKIE_SECURE` | `false` | `Secure` flag on the session cookie (required in production) |
| `CORS_ORIGINS` | `http://localhost:4510` | Comma-separated origins allowed to call the API from a browser |
| `KEY_MODE` | `local` | Provider key sealing: `local` (AES-256-GCM) or `kms` |
| `LOCAL_MASTER_KEY` | development value | Key material for `KEY_MODE=local` |
| `KMS_KEY_ID` | `alias/voiceos-local` | Key for `KEY_MODE=kms` |
| `AWS_REGION` | `us-east-1` | Region for KMS, S3, Secrets Manager |
| `AWS_ENDPOINT_URL` | unset | Emulator endpoint (Floci); must be unset on AWS |
| `S3_FORCE_PATH_STYLE` | `false` | Path-style S3 URLs (emulators) |
| `STORAGE` | `local` | Object storage backend: `local` or `s3` (no 0.1.0 code path writes objects) |
| `OBJECTS_BUCKET` | `voiceos-local-objects` | Bucket for `STORAGE=s3` |
| `LOCAL_STORAGE_DIR` | `./.data/objects` | Directory for `STORAGE=local` |
| `RUNTIME_PUBLIC_URL` | `http://localhost:4535` | The runtime as browsers reach it; session tickets carry URLs built from it |
| `RUNTIME_INTERNAL_URL` | `http://localhost:4535` | The runtime on the private network (benchmarks and the demo seed hold calls through it) |
| `RUNTIME_TOKEN_SECRET` | development value | Signs session tokens; must equal the runtime's |
| `INTERNAL_API_TOKEN` | development value | The runtime's credential for `/internal/*`; must equal the runtime's |
| `DEMO_SPEECH_URL` | `http://speech:8080/v1` | The speech server URL the demo seed gives its providers (as the runtime reaches it) |
| `DEMO_LLM_URL` | `http://mock-providers:4550/v1` | The LLM URL the demo seed gives its providers |
| `DEFAULT_RPM_LIMIT` | `120` | Requests per minute for an SDK key without its own limit |
| `MAX_BODY_BYTES` | `2000000` | Larger request bodies get 413 |
| `MAX_INTERNAL_BODY_BYTES` | `32000000` | Body limit for `/internal/*` (the runtime's session reports), so a long call's report is never refused |
| `WORKER_POLL_INTERVAL_S` | `30` | Worker idle wait between passes |
| `WORKER_METRICS_PORT` | `9464` | Worker Prometheus port (0 disables) |
| `OTEL_ENABLED` | `false` | Install an OpenTelemetry SDK with an OTLP exporter, configured by the standard `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME` |

Read by the CLI and the server entry point directly:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORT` | `8080` | Listen port for `serve`, `runtime` and `speech` |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies whose `X-Forwarded-For` is trusted (the client IP for the sign-in throttle and the audit log) |
| `VOICEOS_OWNER_PASSWORD` | prompt | Password for `voiceos create-owner` (otherwise asked interactively) |
| `VOS_DEMO_PASSWORD` | required | Password of the demo users `voiceos seed-demo` creates (10+ characters) |
| `BENCH_GPU` | `none detected (CPU only)` | GPU description recorded with benchmark results |

## Voice runtime

| Variable | Default | Meaning |
| --- | --- | --- |
| `CONTROL_PLANE_URL` | `http://localhost:4530` | The control plane on the private network (`/internal/*`) |
| `RUNTIME_TOKEN_SECRET` | development value | Verifies session tokens; must equal the control plane's |
| `INTERNAL_API_TOKEN` | development value | Sent to `/internal/*`; must equal the control plane's |
| `MAX_SESSIONS` | `8` | Concurrent calls per instance; past it, 503 `runtime_busy` and `/readyz` 503 |
| `ALLOWED_ORIGINS` | `http://localhost:4510` | Comma-separated browser origins allowed to connect (CORS and the WebSocket origin check) |
| `ICE_URLS` | empty | Comma-separated TURN URLs **browsers** use, for example `turn:turn.example.com:3478?transport=udp`. Empty: no TURN (direct connections only) |
| `SERVER_ICE_URLS` | empty | The same TURN server as the **runtime** reaches it on the private network. Empty: `ICE_URLS`. Locally `turn:turn:3478?transport=udp` |
| `TURN_PASSWORD` | empty | coturn's `static-auth-secret` (the stack's `TURN_SECRET`); credentials are minted per call from it |
| `AGENT_CACHE_TTL_S` | `5` | How long the runtime caches an agent fetched from `/internal/agents/{id}`. Call admission does not use it: each call gets its agent fresh with the ticket claim |
| `REPORT_TIMEOUT_S` | `10` | Timeout of calls to the control plane |
| `RUNTIME_STATIC_AGENTS` | unset | Path to a JSON list of `ResolvedAgent`: run the runtime without a control plane (development and tests); reports are kept in memory |

## Speech server

| Variable | Default | Meaning |
| --- | --- | --- |
| `SPEECH_MODELS_DIR` | `./models` | Where `voiceos models` downloads and the server reads the models |
| `WHISPER_DEFAULT` | `base` | Whisper size used for the model name `whisper-1` |
| `WHISPER_PRELOAD` | `base` | Comma-separated sizes loaded at start (others load on first use) |
| `WHISPER_DEVICE` | `cpu` | `cpu`, `cuda` or `auto` |
| `WHISPER_COMPUTE_TYPE` | `int8` | CTranslate2 compute type |
| `KOKORO_MODEL` | `kokoro-v1.0.int8.onnx` | Kokoro model file |
| `KOKORO_VOICES` | `voices-v1.0.bin` | Kokoro voices file |
| `KOKORO_PRELOAD` | `true` | Load Kokoro at start |
| `SPEECH_CONCURRENCY` | `2` | Model calls in flight, for recognition and for synthesis separately |
| `SPEECH_THREADS` | `4` | CPU threads per model call; keep threads x concurrency within the container's cores |
| `SPEECH_MAX_AUDIO_S` | `60` | Longest audio accepted for transcription (uploads are also capped at 25 MB, and WAV sample rates must be 8 to 96 kHz) |
| `SPEECH_MAX_CHARS` | `4000` | Longest text accepted for synthesis |
| `SPEECH_API_KEY` | empty | When set, every request except health checks must send it as a Bearer token |
| `WHISPER_DOWNLOAD` | `tiny,base,small` | Sizes `voiceos models` downloads |

Model names on the endpoints: `whisper-<size>` for transcription, with the sizes
`tiny`, `base` and `small` downloaded by default (`medium`, `large-v3` and
`large-v3-turbo` are accepted once present), and `whisper-1` meaning `WHISPER_DEFAULT`;
`kokoro` for speech. Voice ids are
Kokoro's (`af_heart`, `am_michael`, `hf_alpha`, `hm_omega`, ...); `GET /v1/voices` lists
them. The first letter picks the language (`a` American English, `b` British English,
`h` Hindi, and others).

## Dashboard (web)

| Variable | Default | Meaning |
| --- | --- | --- |
| `API_INTERNAL_URL` | `http://localhost:4530` | Where Next proxies `/api`, `/v1`, `/healthz`, `/readyz`, `/docs` (server side only) |
| `RUNTIME_PUBLIC_URL` | unset | The runtime's public URL; the Content-Security-Policy allows connections to exactly this origin. Unset: the Talk page cannot connect |
| `PORT` | `8080` in the image | Listen port |

## Local stack

`deploy/compose/.env` (written by `make env`, git-ignored) holds the secrets and optional
overrides:

| Variable | Meaning |
| --- | --- |
| `SESSION_SECRET`, `API_KEY_PEPPER`, `LOCAL_MASTER_KEY`, `RUNTIME_TOKEN_SECRET`, `INTERNAL_API_TOKEN` | Random 64-character values |
| `TURN_SECRET` | coturn's shared secret, passed to the runtime as `TURN_PASSWORD` |
| `VOS_DEMO_PASSWORD` | The demo users' password |
| `VOS_LOG_LEVEL` | Log level for every service |
| `VOS_REDIS_URL` | Set empty to run the stack without Redis |
| `VOS_WHISPER_DOWNLOAD`, `VOS_WHISPER_PRELOAD` | Whisper sizes to download and to preload |
| `VOS_SPEECH_CONCURRENCY` | `SPEECH_CONCURRENCY` for the speech container |
| `VOS_MAX_SESSIONS` | `MAX_SESSIONS` for the runtime |
| `VOS_WEB_PORT` (4510), `VOS_API_PORT` (4530), `VOS_RUNTIME_PORT` (4535), `VOS_SPEECH_PORT` (4537), `VOS_MOCK_PORT` (4550), `VOS_PG_PORT` (4542), `VOS_REDIS_PORT` (4579), `VOS_TURN_PORT` (4578), `VOS_FLOCI_PORT` (4566) | Host ports, all bound to 127.0.0.1. The TURN relay range is fixed at 4581 to 4589 |

## Per-agent settings

Agents carry their own behaviour, edited on the dashboard or through `/api/v1/agents`:
`turn` (`mode` `smart` or `vad`, `vad_stop_secs`, `allow_interruptions`,
`interruption_min_words`, `transcript_wait_s`), `privacy` (`transcript_retention_days`,
`redact_pii`), `cache` (`tts_phrase_cache`, `response_cache`), `small_model_max_words`,
`max_duration_s`, `idle_timeout_s`, tools and FAQ. See the API reference at `/docs`.
