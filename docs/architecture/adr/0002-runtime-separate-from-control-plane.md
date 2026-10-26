# ADR-0002: The runtime is a separate service with no database

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

The control plane (dashboard API, SDK endpoint) is request/response, stateless and cheap.
A voice call holds a long-lived connection, CPU for VAD and turn detection, and media over
UDP. They scale on different signals (requests versus concurrent calls), fail differently,
and need different network exposure (the runtime must accept WebRTC and WebSocket from
browsers; the database must not be reachable from anything browsers touch).

## Decision

Run the voice runtime as its own service (`voiceos runtime`, its own image with the
`runtime` extra) with no database connection. It trusts only session tokens signed with
`RUNTIME_TOKEN_SECRET`, loads the agent from `GET /internal/agents/{id}` (cached for
`AGENT_CACHE_TTL_S`), and posts a `SessionReport` to `POST /internal/sessions` when the call
ends, both with `INTERNAL_API_TOKEN`. The contract between the two is `core/contract.py`.
The control plane stores the report idempotently, computes cost, applies redaction and
retention, and updates the rollup.

## Consequences

**Good**
- Runtime instances are disposable and scale on concurrent calls (`MAX_SESSIONS`,
  `/readyz` turns 503 when full); a crash loses the calls in progress, never data at rest.
- The internet-facing media service holds no database credentials. Redaction and
  retention happen in one place.

**Bad / caveats**
- A report in flight is lost if the control plane stays down for the three retries; the
  loss is logged.
- Agent edits reach new calls after the runtime's cache TTL (5 s by default), not
  instantly.
- Used-token memory is per instance, so single use is per instance; the 60 s token
  lifetime bounds a cross-instance replay ([threat-model.md](../threat-model.md), T1).

## Alternatives considered

- **One process for everything**: simplest locally, but couples scaling and exposes the
  database-holding process to media traffic.
- **The runtime writing sessions to Postgres directly**: removes a hop but spreads
  redaction, cost and retention logic across two services and puts database credentials
  in the media tier.
