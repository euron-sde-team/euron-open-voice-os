# `service` module

The VoiceOS application plane on ECS Fargate behind one Application Load Balancer, with Cloud Map private DNS (`<app>.<name_prefix>.internal`) for service to service calls.

| App | Image / command | Traffic | Task role |
|---|---|---|---|
| `api` | api image, `voiceos serve` | ALB on `hostname`: `/v1/*`, `/api/*`, `/healthz`, `/readyz`, `/health`, `/docs`, `/openapi.json` (and `/metrics` from `metrics_allowed_cidrs` only); private DNS from runtime and web | objects bucket, KMS seal/unseal |
| `runtime` | runtime image, `voiceos runtime` | ALB on `runtime_hostname` (WebSocket `/ws`, WebRTC signalling `/api/offer`, `/api/ice`), sticky; private DNS from the worker; UDP media only through the `turn` module | none |
| `speech` | speech image, `voiceos speech` after a `models` init container | private DNS from the runtime only | none |
| `worker` | runtime image, `voiceos worker` | none (no ingress rule at all) | objects bucket, KMS seal/unseal |
| `web` | web image (Next.js standalone) | ALB default action on `hostname`: every other path | none |
| `migrate` | api image, `voiceos migrate` (task definition only) | none | objects bucket, KMS seal/unseal |

The `migrate` task definition also runs `create-owner` (a command override on `aws ecs run-task`); `seed-demo` runs on the worker's task definition, because it holds real conversations through the runtime. The `run_task` output has every parameter.

**Load balancer.** HTTP answers with a 301 to HTTPS; HTTPS uses `ELBSecurityPolicy-TLS13-1-2-2021-06` and drops invalid header fields. The runtime has its own host name so its `/api/offer` never collides with the API's `/api/*`; its target group is sticky (an offer and its ICE PATCHes must reach the task holding the peer connection) and deregisters slowly (`runtime_drain_seconds`, 300 s) so live calls finish during a deploy. `/internal/*` (session reports, agent lookups) and `/metrics` answer 404 at the edge on both host names, except `/metrics` from `metrics_allowed_cidrs`. Optional Route53 aliases point both host names at it.

**WAF** (`enable_waf`). AWS managed common, known-bad-inputs and IP-reputation rule sets plus a per-IP flood guard. The body-inspecting rules of the common set only count: agent prompts and FAQ snippets are long free text. WAF logs redact `authorization`, `cookie` and the query string (session tickets travel as `?token=`).

**Speech.** Whisper and Kokoro are not baked into the image: a `models` init container downloads the configured sizes (checksummed) into task storage (`speech_ephemeral_storage_gib`, 30 GiB), then the server starts with them read-only. 4 vCPU and 8 GiB by default; `speech_concurrency` x `speech_threads` should not exceed the vCPUs. For a GPU, run speech on EC2 capacity instead; the contract (OpenAI-compatible endpoints on the private DNS name) does not change.

**Least privilege.**

- One security group per app. Ingress only from the load balancer or a named caller on the container port (runtime to api and speech, worker to runtime, web to api), none for `worker` and `migrate`; egress HTTPS (AWS APIs, ECR, hosted providers, the model download) plus PostgreSQL and Redis for the apps that use them. The database and cache security groups get matching ingress rules, so access is granted per security group, never by CIDR.
- Execution role per app: pull, log, and `secretsmanager:GetSecretValue` on exactly its own secrets (control plane: `secrets`; runtime: `runtime_secrets`; speech and web: none), plus `kms:Decrypt` via Secrets Manager.
- Task role for `api`, `worker`, `migrate`: `s3:PutObject`/`GetObject`/`DeleteObject` on the objects bucket, `s3:ListBucket` on the bucket, `kms:GenerateDataKey`/`Decrypt` only via S3, and `kms:Encrypt`/`Decrypt` only with the `voiceos:record` encryption context the sealer always sends. `runtime`, `speech` and `web` have empty task roles.
- Read-only root filesystem; only `/tmp` (and `/app/.next/cache` for `web`, `/models` for the speech init container) is writable. ARM64, no public IP, `initProcessEnabled`.

**Deploys.** Circuit breaker with automatic rollback. `api`, `runtime`, `speech` and `web` roll 100/200 % and autoscale on CPU (slow scale-in so runtime tasks drain); the `worker` is replaced (0/100 %) so two generations never run the same sweep side by side.

Not applied in `local-floci`: locally the same images run as Compose services.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Deployment prefix (at most 24 characters). | `string` | required |
| `vpc_id` | VPC. | `string` | required |
| `public_subnet_ids` | Subnets for the load balancer. | `list(string)` | required |
| `private_subnet_ids` | Subnets for the tasks. | `list(string)` | required |
| `hostname` | Dashboard and API host name. | `string` | required |
| `runtime_hostname` | Voice runtime host name (`RUNTIME_PUBLIC_URL`). | `string` | required |
| `certificate_arn` | ACM certificate covering both host names. | `string` | required |
| `route53_zone_id` | Zone for the alias records; null skips them. | `string` | `null` |
| `api_image`, `runtime_image`, `speech_image`, `web_image` | Image references. | `string` | required |
| `container_port` | Port every container listens on. | `number` | `8080` |
| `environment` | Plain environment for api, worker, migrate. | `map(string)` | `{}` |
| `runtime_environment` | Plain environment for the runtime (pass `ICE_URLS`). | `map(string)` | `{}` |
| `speech_environment` | Plain environment for speech. | `map(string)` | `{}` |
| `web_environment` | Plain environment for web. | `map(string)` | `{}` |
| `secrets` | Control plane secrets (secrets module `ecs_secrets`). | `list(object)` | `[]` |
| `runtime_secrets` | Runtime secrets (secrets module `runtime_secrets`). | `list(object)` | `[]` |
| `kms_key_arn` | CMK for provider-key sealing, the objects bucket and secrets. | `string` | required |
| `objects_bucket_arn`, `objects_bucket_name` | Objects bucket. | `string` | required |
| `db_security_group_id` / `db_port` | Database access. | `string` / `number` | required / `5432` |
| `cache_security_group_id` / `cache_port` | Cache access. | `string` / `number` | required / `6379` |
| `log_group_names` | Log group per app (observability module). | `map(string)` | required |
| `logs_kms_key_arn` | CMK for the WAF log group. | `string` | `null` |
| `cpu_architecture` | `ARM64` or `X86_64`. | `string` | `"ARM64"` |
| `container_insights` | `enabled`, `enhanced` or `disabled`. | `string` | `"enabled"` |
| `api_cpu`, `api_memory`, `api_min_count`, `api_max_count` | api sizing. | `number` | `1024`, `2048`, `2`, `6` |
| `runtime_cpu`, `runtime_memory`, `runtime_min_count`, `runtime_max_count` | runtime sizing. | `number` | `1024`, `2048`, `2`, `8` |
| `runtime_drain_seconds` | How long live calls may finish on a deregistering runtime task. | `number` | `300` |
| `speech_cpu`, `speech_memory`, `speech_min_count`, `speech_max_count` | speech sizing. | `number` | `4096`, `8192`, `1`, `4` |
| `speech_ephemeral_storage_gib` | Task storage for the models. | `number` | `30` |
| `speech_whisper_download`, `speech_whisper_preload` | Whisper sizes fetched and preloaded. | `string` | `"base,small"` |
| `speech_concurrency`, `speech_threads` | Speech parallelism. | `number` | `2`, `2` |
| `worker_cpu`, `worker_memory`, `worker_count` | worker sizing. | `number` | `512`, `1024`, `1` |
| `web_cpu`, `web_memory`, `web_min_count`, `web_max_count` | web sizing. | `number` | `512`, `1024`, `1`, `3` |
| `cpu_target_percent` | Autoscaling CPU target. | `number` | `60` |
| `idle_timeout` | Load balancer idle timeout (s). | `number` | `120` |
| `deletion_protection` | Protect the load balancer. | `bool` | `true` |
| `access_logs_bucket` | Bucket for ALB access logs; null disables. | `string` | `null` |
| `metrics_allowed_cidrs` | Who may read the api's `/metrics` through the ALB. | `list(string)` | `[]` |
| `provider_egress` | Extra runtime egress as `{ cidr, port }` for providers not on HTTPS 443 (Ollama, vLLM in the VPC). | `list(object)` | `[]` |
| `worker_metrics_cidrs` | In-VPC Prometheus CIDRs allowed to scrape the worker's `/metrics`. Empty: no worker ingress. | `list(string)` | `[]` |
| `worker_metrics_port` | Worker metrics port; matches `WORKER_METRICS_PORT`. | `number` | `9464` |
| `enable_waf` | Attach the WAF web ACL. | `bool` | `true` |
| `waf_rate_limit_per_5min` | Per-IP flood guard. | `number` | `20000` |
| `waf_log_retention_days` | WAF log retention. | `number` | `30` |

## Outputs

| Name | Description |
|---|---|
| `cluster_name`, `cluster_arn` | ECS cluster. |
| `url`, `runtime_url` | `https://<hostname>`, `https://<runtime_hostname>`. |
| `internal_urls` | Private URLs of api, runtime and speech. |
| `alb_dns_name` | CNAME target when the zone is not in Route53. |
| `alb_arn_suffix` | For CloudWatch metrics. |
| `services` | `{ api, runtime, web } => { service_name, target_group_arn_suffix }` (observability input). |
| `service_names` | Every ECS service name. |
| `security_group_ids` | Task security group per app. |
| `task_role_arns` | Task role per app. |
| `run_task` | Cluster, task definitions, containers, subnets and security groups for one-off CLI tasks. |
