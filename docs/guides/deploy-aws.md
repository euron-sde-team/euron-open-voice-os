# Deploy to AWS

The Terraform in `infra/terraform` provisions a complete production deployment. The
maintainers develop and test against the local emulator; the AWS environments are kept
valid (`terraform validate`, tflint, checkov) on every change, and the whole `aws-dev`
environment is planned, applied, re-planned and destroyed against the emulator
(`make tf-aws-on-floci`). Nothing in this project is applied to a real AWS account by the
maintainers. This guide describes how to apply it in your own account.

## What gets created

| Module | Resources |
| --- | --- |
| `network` | VPC across two or three availability zones, public and private subnets, NAT, flow logs, an S3 gateway endpoint; KMS and Secrets Manager interface endpoints in `aws-prod` |
| `database` | RDS PostgreSQL 16, private, encrypted with the CMK, TLS enforced, automated backups |
| `cache` | ElastiCache Valkey with TLS, an auth token and `allkeys-lru`, for the config version stamp and rate limits |
| `storage` | Private, TLS-only objects bucket (`<name_prefix>-objects`) with SSE-KMS and lifecycle rules. Provisioned for later features; no 0.1.0 code path writes to it |
| `kms` | Customer-managed key with yearly rotation; encrypts the database, cache, logs, images, bucket and secrets, and seals provider credentials |
| `secrets` | `<name_prefix>/app` (`SESSION_SECRET`, `API_KEY_PEPPER`, `RUNTIME_TOKEN_SECRET`, `INTERNAL_API_TOKEN`), `<name_prefix>/turn` (`TURN_SECRET`) and `<name_prefix>/connections` (`DATABASE_URL`, `REDIS_URL`) |
| `ecr` | Repositories for the `api`, `runtime`, `speech` and `web` images (immutable tags, scan on push) |
| `service` | ECS Fargate cluster with `api`, `runtime`, `speech`, `worker` and `web` services, one ALB with WAF, Cloud Map private DNS (`<app>.<name_prefix>.internal`), and a `migrate` task definition for one-off commands. ARM64 by default |
| `turn` | coturn on one hardened EC2 instance behind a network load balancer with an Elastic IP: `TCP_UDP` 3478 and 40 UDP relay ports, relaying only to the VPC ([ADR-0004](../architecture/adr/0004-turn-on-ec2-behind-an-nlb.md)) |
| `observability` | CloudWatch log groups, alarms (5xx, latency, unhealthy targets, CPU and memory, database, cache, the TURN relay's health, optionally failed voice sessions) and a dashboard |

### Traffic

- `https://<hostname>`: the dashboard by default; `/v1/*`, `/api/*`, `/healthz`, `/readyz`,
  `/docs` and `/openapi.json` go to the api.
- `https://<runtime_hostname>`: the runtime (`/ws`, `/api/offer`, `/api/ice`). Its own host
  name keeps the runtime's `/api/offer` apart from the API's `/api/*`. The target group is
  sticky and deregisters slowly (300 s) so calls finish during a deploy.
- `/internal/*` and `/metrics` answer 404 at the edge on both host names (`/metrics` is
  served to `metrics_allowed_cidrs` only).
- The runtime reaches the api (`CONTROL_PLANE_URL`) and the speech server over Cloud Map
  names; the speech server has no public route at all.
- WebRTC media goes browser to TURN relay to runtime. `ICE_URLS` comes from the `turn`
  module's `ice_urls` output.

### Environment

The control plane runs with `ENVIRONMENT=production`, `VOICEOS_CLOUD=aws`,
`KEY_MODE=kms`, `KMS_KEY_ID`, `STORAGE=s3`, `CORS_ORIGINS=https://<hostname>`,
`COOKIE_SECURE=true` and `FORWARDED_ALLOW_IPS` set to the VPC CIDR, so the production boot
guards pass. `RUNTIME_PUBLIC_URL` is `https://<runtime_hostname>`; the runtime's
`ALLOWED_ORIGINS` is the dashboard's URL. Add non-secret settings through
`api_extra_environment` and `runtime_extra_environment` in `terraform.tfvars`.

## One command

From the repository root, once `terraform.tfvars` (and optionally `backend.tf`) exist in the
environment folder:

```bash
make aws-deploy ENV=aws-dev TAG=0.1.0
VOICEOS_OWNER_PASSWORD='<strong password>' make aws-admin ENV=aws-dev EMAIL=you@example.com
```

`make aws-deploy` (`scripts/aws-deploy.sh`) runs five steps and stops at the first
failure: the registries, the api, runtime, speech and web images for `linux/arm64`
(override with `PLATFORM`), the full apply with `image_tag` set to `TAG` (including the TURN
relay), migrations as a one-off ECS task (`scripts/aws-run-task.sh`, which waits for the
task and prints its logs and exit code), then a wait until every service is stable.
`make aws-migrate ENV=...` reruns only the migrations.

## Steps by hand

```bash
cd infra/terraform/envs/aws-dev                    # or aws-prod
cp terraform.tfvars.example terraform.tfvars       # region, name_prefix, hostname, runtime_hostname, certificate, zone, image_tag
cp backend.tf.example backend.tf                   # recommended: S3 state with locking
terraform init

# 1. Registries first, so there is somewhere to push images.
terraform apply -target=module.ecr

# 2. Build and push the four images (one Dockerfile, three targets, plus the web image).
#    See scripts/aws-deploy.sh for the exact commands.

# 3. Everything else.
terraform apply

# 4. Migrations and the first owner, as one-off tasks (parameters in `terraform output run_task`).
cd - && scripts/aws-run-task.sh aws-dev migrate
VOICEOS_OWNER_PASSWORD='<strong password>' scripts/aws-run-task.sh aws-dev create-owner --email you@example.com
```

Then open `https://<hostname>`, sign in, add your providers (the speech server is
reachable from the runtime at `http://speech.<name_prefix>.internal:8080/v1` on its
Cloud Map name), create agents and SDK keys, and integrate with
[integrate.md](integrate.md).

## Notes

- `certificate_arn` must cover both `hostname` and `runtime_hostname`. Without
  `route53_zone_id`, create CNAMEs for both to the `load_balancer_dns_name` output.
- Runtime tasks reach the internet on HTTPS (443) only. A provider on another port (a
  self-hosted model server in your network) needs a `provider_egress` entry
  (`{ cidr, port }`).
- The speech service downloads its models at start with an init container into 30 GiB of
  task storage; the first start of each task takes longer. It runs on 4 vCPU and 8 GiB by
  default; for a GPU, run speech on EC2 capacity behind the same private name.
- The worker serves Prometheus metrics on 9464; set `worker_metrics_cidrs` to your
  Prometheus to open that port to it.
- `name_prefix` names every resource and the bucket; make it globally unique (for example
  `acme-voiceos-dev`).
- State contains generated secrets (database password, cache auth token, signing secrets):
  keep the state bucket private, versioned and encrypted.
- One TURN instance serves one zone. For redundancy, deploy the module twice and list both
  relays in `ICE_URLS`.
- `aws-prod` differs from `aws-dev` in resilience and retention: three zones with a NAT
  gateway each (dev: two, one NAT), interface endpoints, Multi-AZ RDS with more storage and
  14 days of backups (dev: 3), a primary and replica cache, deletion protection, larger and
  more tasks (api 2 to 6, runtime 2 to 12, speech 2 to 8; dev: 1 to 2, 1 to 2, 1), a 30-day
  KMS deletion window (dev: 7) and a year of log retention (dev: 14 days).
- Never run `seed-demo` against a real deployment.
- For a cheaper trial, use [local against AWS](local-with-aws.md): local containers with a
  real KMS key and objects bucket.
