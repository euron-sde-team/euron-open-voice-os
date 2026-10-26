# Full CI pipeline (opt-in)

These workflows are the complete quality pipeline for Euron Open VoiceOS. They are kept
here, outside `.github/workflows/`, so they do **not** run on the upstream repository.
Only the fast [`checks`](../workflows/checks.yml) workflow (lint, typecheck, unit tests,
web build) runs there.

| Workflow | What it runs |
| --- | --- |
| [`ci.yml`](ci.yml) | Sanitization scan, OpenAPI drift, and the integration suite on Postgres 16 and Redis 7: the control plane and the real voice runtime, driven by a headless WebSocket client against the mock providers, with an 85% coverage floor |
| [`security.yml`](security.yml) | gitleaks over full history, CodeQL (Python and TypeScript), pip-audit, pnpm audit |
| [`terraform.yml`](terraform.yml) | `terraform fmt` and `validate` for every environment, tflint, checkov, and the full `aws-dev` environment applied and destroyed against Floci |
| [`docker.yml`](docker.yml) | Multi-arch image builds for the api, runtime, speech and web images |
| [`e2e.yml`](e2e.yml) | The full stack on the local AWS emulator: the integration suite under every cache, key and storage backend, the Playwright browser tests (Chromium with a fake microphone, over WebRTC and WebSocket) and the Puppeteer QA sweep |

To enable them in your fork, move them into `.github/workflows/`:

```bash
git mv .github/workflows-full/*.yml .github/workflows/
```

Every gate is also runnable locally:
`make lint typecheck test test-integration test-matrix e2e qa tf-validate tf-lint tf-security tf-aws-on-floci sanitize`.
