# `secrets` module

Everything VoiceOS must not receive as plain configuration, in Secrets Manager, encrypted with the CMK. ECS injects each JSON key as an environment variable through the task execution role, and each consumer gets only its own keys.

| Secret | Keys | Lifecycle |
|---|---|---|
| `<name_prefix>/app` | `SESSION_SECRET`, `API_KEY_PEPPER`, `RUNTIME_TOKEN_SECRET`, `INTERNAL_API_TOKEN` | 64 random characters each, generated once. Rotated out of band; `ignore_changes` keeps Terraform from rolling a rotation back. |
| `<name_prefix>/turn` | `TURN_SECRET` | Same lifecycle; a separate secret so the TURN relay's instance role reads only this. |
| `<name_prefix>/connections` | `DATABASE_URL`, `REDIS_URL` | Taken from the `database` and `cache` modules' `connection_url` outputs and updated on every apply. Only with `include_connection_urls = true`. |

| Output | Consumer | Injected as |
|---|---|---|
| `ecs_secrets` | api, worker, migrate | `SESSION_SECRET`, `API_KEY_PEPPER`, `RUNTIME_TOKEN_SECRET`, `INTERNAL_API_TOKEN` (+ `DATABASE_URL`, `REDIS_URL`) |
| `runtime_secrets` | runtime | `RUNTIME_TOKEN_SECRET`, `INTERNAL_API_TOKEN`, `TURN_PASSWORD` (the TURN secret) |
| `turn_secret_arn` | TURN relay (coturn, read at boot) | `TURN_SECRET` |

The four signing values are distinct on purpose (the API refuses to boot in production if any two are equal): rotating dashboard sessions must not invalidate every SDK key hash, and a leaked ticket key must not let anyone file session reports.

Applied in `local-floci` with `include_connection_urls = false`: Compose supplies the connection URLs and `deploy/compose/.env` the signing values (`make env`); the secret is created anyway so the module is exercised on every `make up`.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. | `string` | required |
| `kms_key_arn` | CMK that encrypts the secrets. Null uses the AWS-managed key. | `string` | `null` |
| `recovery_window_in_days` | Days a deleted secret stays recoverable. 0 deletes immediately. | `number` | `30` |
| `include_connection_urls` | Create the connections secret. | `bool` | `false` |
| `database_url` | Sensitive `DATABASE_URL`. | `string` | `null` |
| `redis_url` | Sensitive `REDIS_URL`. | `string` | `null` |

## Outputs

| Name | Description |
|---|---|
| `secret_arn` | The `app` secret. |
| `connections_secret_arn` | The `connections` secret, or null. |
| `keys` | Every environment variable the secrets provide. |
| `ecs_secrets` | ECS `secrets` entries for the control plane (`<arn>:<key>::`). |
| `runtime_secrets` | ECS `secrets` entries for the runtime. |
| `turn_secret_arn` | The `turn` secret, read by the TURN relay at boot. |
