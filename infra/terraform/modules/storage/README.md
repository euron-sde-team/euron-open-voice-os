# `storage` module

One private S3 bucket, `<name_prefix>-objects` (`OBJECTS_BUCKET`), for session audio (only when an agent opts in with `store_audio`, off by default) and benchmark reports. Objects are written with SSE-KMS and expire on a schedule.

- Public access blocked, bucket-owner-enforced ownership, TLS-only bucket policy (`aws:SecureTransport`).
- Default encryption SSE-KMS with the CMK (bucket key on), SSE-S3 when no key is given.
- Lifecycle: session audio (`audio/`) expires after `expiration_days` (30 by default), benchmark reports (`benchmarks/`) after `report_expiration_days` (365), incomplete multipart uploads abort after a day. Not versioned: a deleted recording must stay deleted.
- Optional CORS (`cors_origins`), only for JavaScript fetches from the dashboard.

Applied in `local-floci` as `voiceos-local-objects` with `enforce_tls = false` (the emulator speaks plain HTTP) and `force_destroy = true`.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. The bucket is `<name_prefix>-objects`. | `string` | required |
| `kms_key_arn` | CMK for SSE-KMS. Null falls back to SSE-S3. | `string` | `null` |
| `enforce_tls` | Deny any request not made over TLS. | `bool` | `true` |
| `expiration_days` | Days stored session audio is kept. | `number` | `30` |
| `report_expiration_days` | Days a benchmark report is kept. | `number` | `365` |
| `cors_origins` | Browser origins allowed to GET objects with JavaScript. Empty = no CORS. | `list(string)` | `[]` |
| `force_destroy` | Allow destroying a non-empty bucket. Never in production. | `bool` | `false` |

## Outputs

| Name | Description |
|---|---|
| `bucket_name` | Objects bucket name (`OBJECTS_BUCKET`). |
| `bucket_arn` | Objects bucket ARN, for IAM policies. |
