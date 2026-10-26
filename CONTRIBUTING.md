# Contributing

Thanks for helping improve Euron Open VoiceOS. This guide covers the workflow, the bar a
change has to clear, and the conventions the codebase follows.

## Ground rules

- **Open an issue first** for anything larger than a bug fix or a docs tweak, so we can
  agree on the approach before you invest time.
- **One concern per pull request.** A refactor and a feature are two PRs.
- **Security issues go through private reporting**, never a public issue. See
  [SECURITY.md](SECURITY.md).
- By contributing you agree your work is released under the [MIT License](LICENSE).

## Development setup

Requirements: Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 and
pnpm 9 (`corepack enable`).

```bash
make up          # Postgres, Redis, Floci (provisioned by Terraform), speech, runtime, api, worker, web, TURN
make demo        # users, providers, agents, real conversations, a month of replayed history
make test        # unit tests (API and web)
```

The API package has two optional extras: `runtime` (Pipecat, aiortc, the provider SDKs)
and `speech` (faster-whisper, kokoro-onnx). Install the runtime extra to run the runtime
unit tests and the integration suite outside Docker:

```bash
cd apps/api && uv sync --extra runtime
```

[docs/guides/quickstart-local.md](docs/guides/quickstart-local.md) walks through the local
stack in detail.

## Before you open a pull request

Each of these must pass:

```bash
make lint typecheck test
make test-integration                  # the control plane and the real voice runtime
make e2e                               # when you touched a dashboard flow, the runtime or infrastructure
make tf-validate tf-lint tf-security   # when you touched infra/terraform
make tf-aws-on-floci                   # same: apply and destroy aws-dev against Floci
make openapi                           # when you changed an endpoint (a test checks drift)
make sanitize                          # no credentials, account ids, resource ids or dashes
```

## Conventions

**Package by domain.** `apps/api/src/voiceos/<domain>/` owns its `router.py` (HTTP only),
`schemas.py` (the public contract), `service.py` (rules) and `models.py`. Dependencies
point inward: router, service, data. A domain calls another domain's service, never its
tables.

**The runtime has no database.** `voiceos/runtime/` loads agents from the control plane
(`GET /internal/agents/{id}`) and reports finished sessions back
(`POST /internal/sessions`). The contract between them is `core/contract.py`. Keep it that
way: a runtime instance must stay disposable.

**Measure, never invent.** Every latency comes from frames that actually flowed
(`runtime/turns.py`), every cost from usage a provider reported times a price someone
configured. A stage that did not run, or has no price, is `None` and shows as "not
reported", never as zero.

**Privacy is the default.** No audio is stored. Transcripts follow the agent's retention
and redaction settings. Any provider that receives audio or text outside the deployment
is disclosed to the caller before a session starts. A change that adds a new place where
words or audio go must keep all three true.

**Providers sit behind adapters.** `runtime/providers.py` builds the Pipecat service for
each adapter; `providers/schemas.py` lists which adapters fit which stage. Adding a vendor
means one case per stage it serves and one entry in `ADAPTERS`.

**Redis is optional.** Every Redis use goes through `core/kv.py`, has an in-process
fallback, and treats a Redis error as a cache miss. The test matrix runs the whole
integration suite without Redis.

**Configuration is validated.** A new setting goes in `core/config.py`, is documented in
[docs/guides/configuration.md](docs/guides/configuration.md) in the same PR, and
security-relevant ones are enforced by `guard()` at boot.

**Database changes are new migrations.** Change the models, then run
`make migration MSG="what changed"`: it migrates the local Postgres and autogenerates a
revision under `apps/api/src/voiceos/migrations/versions/` for you to review. Never edit
an applied one. Indexes for every new filter the API exposes belong in the same revision.

**Comments explain why.** The code says what it does. Comments are for the constraint, the
incident, or the trade-off that made it this way.

**Style.** ruff and mypy `--strict` for Python; ESLint and TypeScript strict for the web.
No em dashes or en dashes anywhere (the sanitization check enforces it).

## Commit messages

Imperative mood with an optional scope: `runtime: speak the fallback when STT fails`,
`web: show self-hosted stages as free`. Explain the why in the body when it is not
obvious.

## Architecture decisions

Significant decisions are recorded in [docs/architecture/adr/](docs/architecture/adr/).
If your change reverses or extends one, add a new ADR rather than editing the old one.
