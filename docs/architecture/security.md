# Security

How VoiceOS authenticates callers, dashboard users and its own services, protects provider
credentials, and keeps a caller's audio and words where they belong. Threats and residual
risks are in [threat-model.md](threat-model.md); privacy rules are in
[privacy.md](privacy.md).

## Session tokens (browser and SDK to runtime)

The runtime is the only service a caller's browser talks to directly, so it trusts nothing
but a token the control plane signed (`core/tokens.py`):

| Property | Value |
| --- | --- |
| Algorithm | HS256 with `RUNTIME_TOKEN_SECRET` (shared by the control plane and the runtime only) |
| Audience | `voiceos-runtime` |
| Lifetime | 60 seconds |
| Claims | `sid` (the session id, a random UUID), `agent`, `origin` (the page origin, for browsers), `sub` (`user:<id>` or `key:<id>`) |
| Use | Once: the runtime remembers used session ids for 120 s and refuses a replay with 409 `token_used` |

`Sessions.admit()` (`runtime/app.py`) also refuses a browser whose `Origin` differs from
the token's (403), a WebSocket from an origin outside `ALLOWED_ORIGINS` (403), and any
connection past `MAX_SESSIONS` (503 `runtime_busy`). Refused WebSocket handshakes answer
with their real status through the ASGI denial-response extension. The agent comes from
the token, never from the request, so a token for one agent cannot open another.

TURN credentials (`GET /api/ice?token=...`) are coturn `use-auth-secret` credentials: a
username of `<expiry>:<label>` and an HMAC-SHA1 of it with `TURN_SECRET`, valid for an
hour. The runtime mints its own per offer. There is no static TURN password.

## SDK keys (`POST /v1/sessions`)

- Format `vos_<prefix>_<secret>`, shown once. Stored as an HMAC-SHA256 of the secret with
  `API_KEY_PEPPER`; the pepper is not in the database.
- Scoped: `agent_ids` (403 `agent_not_allowed`) and `allowed_origins` (403
  `origin_not_allowed` when the browser's `Origin` is missing or different). Keep keys on
  your server; scope a key to origins only when the browser calls `/v1/sessions` itself.
- Rate limited per key (`rpm_limit`, default `DEFAULT_RPM_LIMIT` 120 per minute, 429 with
  `Retry-After`), expiring, revocable; revocation reaches every replica within about a
  second through the config version stamp.
- Malformed prefixes are refused before any cache or database lookup.

## Dashboard authentication (`/api/v1`)

- argon2id password hashes; sign-in lockout after repeated failures; a per-IP sign-in
  throttle (20 per minute) that a forged `X-Forwarded-For` cannot dodge (only
  `FORWARDED_ALLOW_IPS` proxies are trusted); failed sign-ins audited.
- Session cookie `vos_session`: HttpOnly, SameSite=Lax, Secure in production, lifetime
  `SESSION_TTL_HOURS` (12). Sign-out records the session in `revoked_sessions`; a password
  change bumps `session_version` and ends every other session.
- Cookie-authenticated mutations must send `X-VoiceOS-CSRF: 1`, which a cross-site form
  cannot add. Bearer tokens (`session_token` from sign-in) skip the check.

## Authorisation

| Role | Can |
| --- | --- |
| viewer | Read agents, providers (never their keys), sessions, analytics, benchmarks; talk to agents |
| admin | Everything a viewer can, plus create and edit providers, agents, SDK keys, benchmarks, erase transcripts; read the user list and the audit log |
| owner | Everything, plus creating users and changing roles. The last active owner cannot be demoted or disabled |

## The runtime and the control plane

The runtime calls `GET /internal/agents/{id}` (which returns provider credentials opened
for this call) and `POST /internal/sessions` with `Authorization: Bearer
INTERNAL_API_TOKEN`, compared in constant time. On AWS these calls stay inside the VPC
(Cloud Map names), and the load balancer answers 404 for `/internal/*`.

## Provider credentials

- Sealed before they reach Postgres: `KEY_MODE=local` uses AES-256-GCM with a key derived
  from `LOCAL_MASTER_KEY`; `KEY_MODE=kms` calls KMS with the encryption context
  `voiceos:record=<provider id>`, so a sealed value copied to another row fails to open.
- Never returned: the API returns `has_api_key` and a short `key_hint` only.
- Moving a provider's `base_url` to another host requires the key again, so an admin
  cannot redirect a stored key to a host of their choice.
- `base_url` must be `http://` or `https://` and must not be a link-local, unspecified or
  instance metadata address (`169.254.0.0/16`, `fd00:ec2::254`, `metadata`,
  `metadata.google.internal`, `instance-data`). Private addresses are allowed on purpose:
  self-hosted models live there.

## The browser

- The dashboard's Content-Security-Policy is built per request (`apps/web/src/middleware.ts`):
  everything from its own origin, plus `connect-src` for exactly the runtime origin named by
  `RUNTIME_PUBLIC_URL` (http and ws forms). `script-src` and `worker-src` allow `blob:`
  because the voice client runs its audio worklets from blob URLs only this origin's code
  can create. `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'`,
  `form-action 'self'`.
- `Permissions-Policy` allows the microphone for the dashboard's own origin only
  (`microphone=(self)`), and nothing else (camera, geolocation, payment are off). API
  responses disable the microphone entirely.
- The Pipecat client is given its local `WavMediaManager`. The default media manager loads
  Daily's call-machine bundle from Daily's CDN and reports to Sentry; with the local one
  the browser contacts only the dashboard and the runtime.
- HSTS in production; `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`.

## HTTP hardening (API)

- Request bodies above `MAX_BODY_BYTES` (2 MB) are refused with 413, counted as bytes
  arrive, so chunked uploads are covered.
- One JSON error envelope (`{"error": {"code", "message", ...}}`), no stack traces.
- SQLAlchemy runs with `hide_parameters=True`: database errors never log bound values.
- Tokens in URLs (`?token=` on the runtime's offer, WebSocket and ICE URLs) are redacted
  from access logs; `authorization`, `password`, `secret`, `api_key` fields are redacted
  from structured logs.

## Speech server

Internal only (no public route on AWS). Optionally requires `SPEECH_API_KEY` as a Bearer
token on every request except health checks. Request size is bounded by
`SPEECH_MAX_AUDIO_S` (60 s of audio) and `SPEECH_MAX_CHARS` (4,000 characters).

## Audit log

Every mutation (providers, agents, keys, users, transcript erasure, benchmarks, password
changes) is written to `audit_log` with actor, target and IP. A database trigger refuses
UPDATE and DELETE on the table.

## Production boot guards

With `ENVIRONMENT=production` the control plane refuses to start when `SESSION_SECRET`,
`API_KEY_PEPPER`, `RUNTIME_TOKEN_SECRET` or `INTERNAL_API_TOKEN` is a development value or
shorter than 32 characters, when they are not all different, when `KEY_MODE=local` has no
real `LOCAL_MASTER_KEY`, when `AWS_ENDPOINT_URL` is set with `VOICEOS_CLOUD=aws`, or when
`COOKIE_SECURE` is false. The runtime refuses weak `RUNTIME_TOKEN_SECRET` and
`INTERNAL_API_TOKEN` the same way.

## Operator checklist

- [ ] Generate every secret with a CSPRNG (the Terraform `secrets` module does) and keep
      them in Secrets Manager; `TURN_SECRET` lives in its own secret that only the TURN
      instance and the runtime can read.
- [ ] Use `KEY_MODE=kms`.
- [ ] Set `COOKIE_SECURE=true` and serve the dashboard and the runtime over HTTPS only.
- [ ] Set `CORS_ORIGINS` and the runtime's `ALLOWED_ORIGINS` to the dashboard's exact
      origin (plus the sites that embed agents with SDK keys).
- [ ] Give the admin role sparingly: admins choose where callers' audio and words go
      (providers) and can read transcripts.
- [ ] Keep `/internal/*`, `/metrics` and the speech server off the public internet.
- [ ] Mark a self-hosted provider external if it runs outside your trust boundary, so
      callers are told.
- [ ] Set transcript retention per agent to the least you need (0 keeps no words).
- [ ] Never run `make demo` or `seed-demo` against a real deployment.
