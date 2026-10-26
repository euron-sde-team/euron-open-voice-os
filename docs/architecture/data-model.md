# Data model

PostgreSQL 16, one Alembic revision in 0.1.0
(`apps/api/src/voiceos/migrations/versions/0001_initial_schema.py`). Only the control plane
connects to the database; the runtime and the speech server never do. Money is stored as
integer nano-USD (`BIGINT`, 10^-9 USD), never as floats; see
[latency-and-cost.md](latency-and-cost.md).

```
users ─┬─< api_keys            (created_by)
       ├─< agents              (created_by, SET NULL)
       └─< benchmark_runs      (requested_by, SET NULL)
providers ─< agents            (stt, llm, llm_small, tts provider ids, RESTRICT)
agents ─< sessions             (agent_id, SET NULL: history outlives the agent)
sessions ─< session_turns      (CASCADE)
usage_hourly                   (rollup, no foreign keys)
audit_log                      (append-only)
revoked_sessions               (signed-out dashboard sessions)
```

## Tables

### `users`

Dashboard accounts. `email` unique; `password_hash` is argon2id; `role` is `owner`,
`admin` or `viewer`; `failed_logins` and `locked_until` implement lockout;
`session_version` is bumped on a password change, which ends every other session.

### `api_keys`

SDK keys. The full key (`vos_<prefix>_<secret>`) is shown once; the row keeps the public
`prefix` (unique) and `secret_hash`, an HMAC-SHA256 of the secret with `API_KEY_PEPPER`.
`agent_ids` and `allowed_origins` (JSONB lists, empty means any) scope what the key may
start; `rpm_limit` overrides `DEFAULT_RPM_LIMIT`; `expires_at`, `revoked_at` and
`last_used_at` complete the lifecycle.

### `providers`

One row per STT, LLM or TTS endpoint. `stage` is checked (`stt`, `llm`, `tts`) and `name`
is unique. `adapter` is one of the adapters allowed for the stage. `sealed_key` holds the
API key sealed with AES-256-GCM or KMS, bound to the row id; `key_hint` is the only part
ever returned. `external` and `self_hosted` are derived from the adapter and the URL;
`force_external` records the admin's choice to mark a private URL external (it can only
raise the classification). `price` is JSONB (`per_audio_minute`,
`per_million_input_tokens`, `per_million_output_tokens`, `per_million_characters`), each
optional: a missing price makes the stage "not reported".

### `agents`

The agent: `language`, `system_prompt`, `greeting`, `voice`, the four provider foreign
keys (`ON DELETE RESTRICT`, so a provider in use cannot be deleted), `small_model_max_words`,
and JSONB settings: `turn` (mode, pause, interruptions, transcript wait), `privacy`
(retention days, redaction), `cache` (phrase cache, response cache), `tools`, `faq`.
`max_duration_s` and `idle_timeout_s` bound a call. `version` starts at 1 and is
incremented by every update: the runtime's response cache keys on it, and each session
records the version it ran.

### `sessions`

One finished call. The primary key is the session id the token carried, which makes report
ingestion idempotent. Columns: `agent_id` (nullable), `agent_name` and `agent_version` as
they were, `transport` (`webrtc` or `websocket`), `subject` (`user:<id>` or `key:<id>`),
`origin`, `started_at`, `ended_at`, `duration_s`, `end_reason`, `external_providers`
(JSONB), `turn_count`, `interruptions`, `response_ms_p50`, `response_ms_max`, `usage`
(JSONB: audio seconds, tokens, characters, cache hits, routed turns, and the stages that
were self-hosted), `cost_stt_nusd`, `cost_llm_nusd`, `cost_tts_nusd`, `cost_total_nusd`
(each nullable: null is "not reported"), `cost_status`, `savings_nusd`, `errors`,
`transcript_stored`, `transcript_expires_at`.

Indexes: `ix_sessions_started_at` (started_at DESC) for the list,
`ix_sessions_agent_started` (agent_id, started_at DESC) for the agent filter, and the
partial `ix_sessions_transcript_expiry` (transcript_expires_at WHERE transcript_stored) for
the retention purge. The list is keyset paginated on (started_at, id).

### `session_turns`

One row per turn: `idx`, `started_at`, `user_text` and `agent_text` (null when not kept),
`interrupted`, the measured milliseconds (`user_speech_ms`, `endpoint_ms`, `stt_ms`,
`llm_first_token_ms`, `tts_first_audio_ms`, `response_ms`), `llm_model`,
`llm_routed_small`, `response_cache_hit` and `error`. Index
`ix_session_turns_session` (session_id, idx).

### `usage_hourly`

The analytics rollup, upserted (`ON CONFLICT DO UPDATE`, additive) in the same transaction
as the session. Primary key (hour, agent_key, transport), where `agent_key` is the agent id
or `deleted`. Sums: sessions, turns, interruptions, errors, duration, audio seconds,
tokens, characters (and cached characters), response cache hits, response time sum and
count, cost, costed sessions, savings, external sessions. The overview reads only this
table and a percentile query over the period's turns.

### `benchmark_runs`

`kind` (`latency`), `status` (`queued`, `running`, `succeeded`, `failed`), `config`,
`results`, `hardware`, `error`, timestamps. The partial unique index
`ux_benchmark_runs_active` on `(true) WHERE status IN ('queued', 'running')` allows at most
one active run, enforced by the database.

### `audit_log`

Every mutation: `at`, actor id and e-mail, `action` (for example `agent.updated`,
`api_key.revoked`, `session.transcript_erased`), target, `details`, `ip`. A trigger
(`audit_log_append_only`) refuses UPDATE and DELETE, so the log is append-only at the
database level.

### `revoked_sessions`

Signed-out dashboard session ids (`jti`) until they would have expired anyway, so a
signed-out cookie stays dead even after a cache eviction.

## Retention

Transcripts are cleared by the worker when `transcript_expires_at` passes (words set to
null, timings and usage kept). Session rows, turns without words and rollups are kept;
remove old sessions with your own database policy if you need to.
