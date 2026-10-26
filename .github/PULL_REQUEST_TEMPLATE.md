## What and why

<!-- One paragraph: the problem, and how this change solves it. Link the issue. -->

## How it was verified

- [ ] `make lint typecheck test`
- [ ] `make test-integration` (if the API, the runtime, a cache or database code changed)
- [ ] `make e2e` (if a dashboard flow or infrastructure changed)
- [ ] `make tf-validate tf-lint tf-security tf-aws-on-floci` (if Terraform changed)

## Checklist

- [ ] Docs updated (README, `docs/`, configuration reference) for any behavior or config change
- [ ] New Alembic revision instead of editing an applied one
- [ ] Latency and cost are still measured, never estimated or invented; a missing price or usage stays "not reported"
- [ ] No new place where audio or transcripts are stored or sent outside the deployment without disclosure
- [ ] `make openapi` run if the API changed
- [ ] No secrets, account ids, real hostnames or em/en dashes (`make sanitize` is clean)
- [ ] Security-relevant change? Described the threat and mitigation above
