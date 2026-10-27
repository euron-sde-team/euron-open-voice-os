# Testing

Every gate runs locally through `make`. The fast checks also run in CI on every push
([`.github/workflows/checks.yml`](../../.github/workflows/checks.yml)); the full pipeline is
in [`.github/workflows-full/`](../../.github/workflows-full/).

| Command | What it runs | Needs |
| --- | --- | --- |
| `make lint typecheck` | ruff (check and format), mypy `--strict`, ESLint, `tsc --noEmit` | Nothing running |
| `make test` | API unit tests (pytest) and web unit tests (Vitest) | Nothing running |
| `make test-integration` | The integration suite with coverage | Postgres (started if needed) |
| `make test-matrix` | The integration suite under every cache, key and storage backend | `make up` (Floci) |
| `make e2e` | Playwright browser tests | `make up && make demo` |
| `make qa` | Puppeteer QA sweep of every page | `make up && make demo` |
| `make openapi` | Regenerates `docs/api/openapi.yaml`; a unit test fails when it drifts | Nothing running |
| `make tf-validate tf-lint tf-security tf-aws-on-floci` | Terraform gates | Docker |
| `make sanitize` | Credentials, account ids, env files, em and en dashes | Nothing running |

The API's runtime code needs the `runtime` extra (Pipecat, aiortc). Install it once before
running Python tests outside Docker:

```bash
cd apps/api && uv sync --extra runtime
```

## Unit tests (`apps/api/tests/unit`, `apps/web/test`)

No network, no database. They mirror the source tree:

- `core/`: configuration and boot guards, the KV store and config cache invalidation,
  money rounding, sealing and storage, password and key hashing, schemas, logs, errors.
- `domain/`: session cost (complete, partial, not reported, self-hosted, savings, the small
  model at its own rate), redaction with Luhn and Verhoeff checks, spoken e-mails, PAN in
  any case and misheard card numbers, session tokens (expiry, audience, forgery), provider
  classification and private hosts, metadata addresses in every spelling, the response
  cache key (the whole conversation) and expiry, FAQ lookup, WER scoring.
- `core/test_logs_pipecat.py`: Pipecat's own logging never writes the caller's words.
- `runtime/test_turns.py`: the turn recorder fed with Pipecat frames in the orders the
  turn strategies really emit them, checking which turn gets the words, the answer and
  each latency.
- `speech/`: the speech server's request handling.
- `system/test_openapi_drift.py`: the committed OpenAPI document matches the app.
- Web (Vitest): status chips, the glossary, navigation, roles, the integration snippets,
  error messages, the SDK key form's origin parsing, the waterfall component.

## Integration tests (`apps/api/tests/integration`)

The real control plane and the real voice runtime, each served by uvicorn on a background
thread, against real Postgres (and Redis, Floci S3 and KMS when the matrix selects them).
A third server runs the mock providers (`mockproviders`): an OpenAI-compatible LLM with
scripted answers and token usage, a transcription endpoint that returns scripted text, a
TTS that returns a tone, and `/admin/faults` to make any stage fail or stall.

The runtime reaches the control plane over HTTP exactly as in production (`/internal/*`
with the internal token). Voice sessions are driven by the **headless voice client**
(`voiceos/benchmarks/client.py`): it connects to the runtime's WebSocket like a browser,
streams a committed speech file in real time in 20 ms frames, lets the greeting finish,
waits for the agent's answer and records the audio and events it gets back. So Silero VAD,
turn taking, interruption, fallbacks and reporting all run for real.

What the suites cover:

| File | Covers |
| --- | --- |
| `test_voice_sessions.py` | A spoken question gets a spoken answer and a full report (every stage timed, usage, cost, disclosure); the runtime refuses missing, forged and reused tokens and other sites |
| `test_voice_behaviour.py` | Barge-in, a pause inside a sentence, switching providers by configuration, disclosure, no stored audio, STT and LLM failures and an LLM timeout heard as fallbacks, a dropped client, the session cap (503), concurrent sessions, the phrase and response caches, small-model routing |
| `test_worker_tools.py` | The worker runs a queued benchmark through the runtime, and the agent's tools (time, FAQ, ending the call) work in a live call |
| `test_admin.py` | Sign-in, lockout, CSRF, sign-out, password change, roles, SDK key lifecycle, rate limit, agent and origin scopes |
| `test_providers_agents.py` | Sealed provider keys never returned, host moves, the SSRF guard, adapters per stage, classification, providers in use, the Test button, templates, versions reaching the runtime, internal-token refusal |
| `test_sessions_api.py` | Idempotent reports, pagination and filters, cost and "not reported", redaction, retention 0, erase, purge, the overview against the filed reports |
| `test_hardening.py` | Health, readiness, system info, metrics, security headers, the error envelope, the body limit, the append-only audit log, parallel benchmarks and reports |
| `test_cli_owner.py` | `voiceos create-owner` creates an owner, then resets it and signs the old sessions out |
| `test_review_fixes.py` | One test per issue an independent review found: a ticket used once across two runtime replicas, deleting a key's only agent revokes the key, clearing a key's rate limit, a disabled provider receiving no calls, a report costed with the configuration the call ran with, webhook URLs aimed at metadata refused, a runtime shutdown still reporting what it measured |

Safety: the suite drops and recreates its database, so it refuses any database whose name
does not contain `test`, and any non-local host unless `ALLOW_REMOTE_TEST_DB=true`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `TEST_DATABASE_URL` | `postgresql+asyncpg://voiceos:voiceos@localhost:4542/voiceos_test` | The test database (created and migrated at session start) |
| `TEST_CACHE` | `memory` | `memory` (no Redis) or `redis` |
| `TEST_REDIS_URL` | `redis://localhost:4579/15` | Redis for `TEST_CACHE=redis` |
| `TEST_KEY_MODE`, `TEST_STORAGE` | `local` | `kms` and `s3` run against Floci |
| `TEST_AWS_ENDPOINT` | unset | Floci for the KMS and S3 legs |

`make test-matrix` runs the suite eight times: cache `redis` or `memory`, keys `local` or
`kms`, storage `local` or `s3`.

The committed speech files (`voiceos/benchmarks/audio/*.wav`) are synthesized with the
local Kokoro voice, not recordings of people; `make utterances` (or
`scripts/gen-utterances.py`) regenerates them.

## End-to-end tests (`e2e/`)

Playwright with Chromium against the running stack (`make up && make demo`). Chromium's
fake microphone plays `e2e/audio/en-booking.wav` (a Kokoro-synthesized question followed by
silence, looped), so a real conversation runs without a person: the local Whisper hears
it, the LLM answers, Kokoro speaks.

| Spec | Journey |
| --- | --- |
| `01-auth` | Wrong and right passwords, redirect after sign-in, no open redirect, sign-out ends the session |
| `02-talk` | Talk to an agent over WebRTC (through the local TURN relay) and over WebSocket; the session is stored with its waterfall |
| `03-five-minute-path` | Create an agent from a template and talk to it, from the dashboard alone |
| `04-providers-and-disclosure` | Add a provider, test it, switch an agent to it in the editor, see the disclosure before the call and "Sent to" after |
| `05-sessions-and-overview` | The overview's latency and cost, a session's turns and waterfall, erasing its words |
| `06-keys-and-sdk` | An SDK key shown once, starting sessions only for its agent from its origin; integrations and settings |
| `07-people-and-account` | Users and roles, password change, what a viewer cannot do, the theme |
| `08-benchmarks` | Run a latency benchmark from the dashboard and read its results |

| Variable | Default | Meaning |
| --- | --- | --- |
| `WEB_URL` | `http://localhost:4510` | The dashboard |
| `E2E_EMAIL` | `admin@voiceos.local` | User to sign in as |
| `E2E_PASSWORD` or `VOS_DEMO_PASSWORD` | from `make e2e` | Its password |
| `E2E_AGENT` | unset | Agent name to pick on the Talk page (the first enabled one otherwise) |
| `E2E_HEADED` | unset | Show the browser |

## Browser QA (`scripts/qa/`)

`make qa` signs in through the real form and visits every page (including an agent editor
and an open session) in light and dark mode at desktop and phone width. It fails on
console errors, failed or 4xx/5xx requests, broken images, error states and horizontal
overflow, and saves a screenshot of every page to `scripts/qa/output/`. `QA_PAGES`,
`QA_THEMES`, `QA_SIZES` narrow the sweep.
