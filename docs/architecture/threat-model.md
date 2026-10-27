# Threat model

Scope: the control plane (dashboard API, SDK endpoint, internal endpoints), the voice
runtime, the speech server, the worker, the TURN relay, Redis, Postgres, object storage,
the AWS resources the Terraform creates, and the dashboard. Method: STRIDE per asset, with
the mitigation that exists in this repository and the residual risk. Controls are
described in [security.md](security.md) and [privacy.md](privacy.md).

## Assets

1. **A caller's audio** in transit (browser to runtime, runtime to STT).
2. **Transcripts** in transit (to the LLM and TTS) and at rest (when retention keeps them).
3. **Provider credentials** (direct financial exposure at the vendor).
4. **Session tokens, SDK keys and dashboard sessions.**
5. **Runtime capacity** (concurrent call slots, speech CPU).
6. **Session history, cost figures and the audit log.**

## Actors

| Actor | Trust | Reach |
| --- | --- | --- |
| Caller in a browser | Untrusted; speaks whatever they like | The runtime, with a token someone else obtained for them |
| Your backend holding an SDK key | Trusted for its scoped agents and origins | `POST /v1/sessions` |
| Dashboard viewer, admin, owner | Authenticated staff, by role | `/api/v1/*` |
| A provider (cloud STT, LLM or TTS vendor) | Trusted with what the agent sends it, and disclosed to callers | Audio or text of calls that use it |
| Network attacker | Untrusted | Public endpoints, the TURN relay |
| Holder of a database or backup copy | Untrusted | Postgres contents only |

## Threats and mitigations

| # | Threat (STRIDE) | Asset | Mitigation | Residual risk |
| --- | --- | --- | --- | --- |
| T1 | Spoofing: connecting to the runtime without permission, or reusing a captured token | 1, 5 | HS256 token, 60 s lifetime, audience bound, agent taken from the token, origin checked for browsers, refused on reuse (409) across every runtime replica: each ticket is claimed by an atomic insert into `session_claims` before the call starts | A captured token can be used by whoever connects first within its 60 s life. Tokens travel over TLS in production; keep the lifetime short |
| T2 | Elevation: an SDK key starting an agent or from a site it is not scoped to | 4, 5 | Scope checks in `sessions.service.start` (403), per-key rate limit, expiry, revocation that propagates in about a second; deleting a key's only agent revokes the key instead of leaving it unscoped | An unscoped key starts any agent; scope keys. `allowed_origins` relies on the browser's `Origin` header, which a server-side caller can set freely: origin scope stops other websites, not someone holding the key |
| T3 | Information disclosure: a caller's words reaching a provider the caller was not told about | 1, 2 | `external` derived from adapter and URL; an admin can only raise it (`force_external`); the disclosure is in every ticket and shown before the call; each session records `external_providers` | A self-hosted model on a private address that you do not control is classified self-hosted; mark it external. VoiceOS cannot see what a provider does with data it receives |
| T4 | Information disclosure: transcripts read after their retention, or with personal details | 2, 6 | Retention per agent (0 stores no words), worker purge on `transcript_expires_at`, redaction before storage (e-mail written or spoken, phone, card, misheard card-length numbers, Aadhaar, PAN in any case), provider errors redacted too, erase by admins, audit row on erase; no conversation text in logs (Pipecat's DEBUG output is not logged) | Redaction is pattern based: names, addresses and details spoken in words ("four one one one ...") are not caught. Words exist in runtime memory and in the report in transit until ingestion |
| T5 | Information disclosure: leaked database or backup | 2, 3, 4 | Provider keys sealed (AES-GCM or KMS, row bound); SDK keys peppered HMACs; passwords argon2id; no audio in the database or object storage | Kept transcripts, session metadata, user e-mails and cost figures are readable. With `KEY_MODE=local` a leak of both the database and `LOCAL_MASTER_KEY` opens provider keys |
| T6 | SSRF: a provider `base_url` aimed at instance metadata or an internal service, or at an attacker host to capture a provider key | 3 | Admin only; audited; scheme check; hosts canonicalized (integer, hex, octal, trailing dot) before link-local and metadata addresses are refused, for provider URLs and webhook URLs alike; webhook hosts re-checked after DNS resolution when called; moving a provider to another host needs its key again; on AWS the runtime's egress is limited to HTTPS plus any `provider_egress` you allow | Private addresses are allowed on purpose (self-hosted models). An admin can point a new provider at an internal HTTP service and read its error messages through the Test button |
| T7 | Abuse of the TURN relay as an open proxy | 5 | `use-auth-secret` credentials minted per call (1 hour), no static password; on AWS coturn relays only to the VPC CIDR (`denied-peer-ip` everything else) | Anyone with a valid session token can obtain TURN credentials for an hour and relay to VPC addresses on the UDP ports the security groups allow (the runtime) |
| T8 | Denial of service: many calls, long calls, or expensive speech requests | 5 | `MAX_SESSIONS` per runtime instance (503 past it, `/readyz` turns 503), `max_duration_s` and `idle_timeout_s` per agent, per-key rate limit, bounded speech concurrency and request size (25 MB uploads, 8 to 96 kHz WAV), provider timeouts bound every request including Pipecat's retry, a failed connection setup frees its slot at once | A caller with a ticket can hold a slot until the idle or maximum duration ends. Speech recognition is CPU bound; size the speech service for your concurrency |
| T9 | Tampering: a forged session report | 6 | `/internal/*` requires `INTERNAL_API_TOKEN` (constant-time compare) and is not routed at the edge on AWS; reports are idempotent on the session id | Anyone holding the internal token can write session history; keep it in Secrets Manager |
| T10 | Information disclosure: secrets or callers' words in logs | 2, 3, 4 | Token query parameters and sensitive fields redacted, SQL parameters hidden; Pipecat's loguru output routed into the JSON logger with a WARNING floor and redacted, so the LLM context and spoken sentences (DEBUG) are never logged; provider error messages redacted before they are stored | A provider error at WARNING or above is logged as the provider worded it, after pattern redaction |
| T11 | Repudiation: an admin denies a change | 6 | Append-only `audit_log` enforced by a database trigger, with actor, target and IP | A database owner can drop the trigger |
| T12 | Third-party code in the browser | 1 | The Pipecat client uses its local media manager, so no third-party script or telemetry is loaded; CSP allows only the dashboard and runtime origins | Supply chain of the npm packages themselves (lockfile pinned, `pnpm audit` in CI) |
