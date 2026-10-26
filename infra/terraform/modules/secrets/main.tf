# VoiceOS's secrets, in Secrets Manager. ECS injects each JSON key into the containers
# that need it as an environment variable; the values never appear in a task definition,
# a plan diff or a log. Each consumer gets only its own keys (see the outputs).
#
# Three secrets with different lifecycles and readers:
#
#   <name_prefix>/app          SESSION_SECRET, API_KEY_PEPPER, RUNTIME_TOKEN_SECRET,
#                              INTERNAL_API_TOKEN. Generated once, then rotated out of
#                              band; Terraform never rolls them back.
#   <name_prefix>/turn         TURN_SECRET, on its own so the TURN relay's instance role
#                              can read it without reading the signing keys.
#   <name_prefix>/connections  DATABASE_URL, REDIS_URL. Derived from the database and
#                              cache modules and kept in step with them on every apply.
#
# The four signing values are distinct on purpose (the API refuses to boot in production
# if any two are equal): rotating dashboard sessions must not invalidate every SDK key,
# and a leaked session ticket key must not let anyone file session reports.
locals {
  app_keys        = ["API_KEY_PEPPER", "INTERNAL_API_TOKEN", "RUNTIME_TOKEN_SECRET", "SESSION_SECRET"]
  connection_keys = var.include_connection_urls ? ["DATABASE_URL", "REDIS_URL"] : []
}

resource "random_password" "this" {
  for_each = toset(concat(local.app_keys, ["TURN_SECRET"]))
  length   = 64
  special  = false
}

resource "aws_secretsmanager_secret" "app" {
  #checkov:skip=CKV2_AWS_57:These are HMAC keys; rotation is an operator procedure (docs/guides/operations.md), not a Lambda.
  name                    = "${var.name_prefix}/app"
  description             = "VoiceOS signing secrets (sessions, SDK key pepper, runtime tickets, internal token)"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id     = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({ for k in local.app_keys : k => random_password.this[k].result })

  # Rotation happens out of band (put a new version by hand or by pipeline). Without
  # this, the next `terraform apply` would quietly roll every secret back.
  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "turn" {
  #checkov:skip=CKV2_AWS_57:A shared HMAC key between the runtime and coturn; rotation is an operator procedure (docs/guides/operations.md).
  name                    = "${var.name_prefix}/turn"
  description             = "VoiceOS TURN shared secret (runtime mints credentials, coturn checks them)"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "turn" {
  secret_id     = aws_secretsmanager_secret.turn.id
  secret_string = jsonencode({ TURN_SECRET = random_password.this["TURN_SECRET"].result })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

resource "aws_secretsmanager_secret" "connections" {
  #checkov:skip=CKV2_AWS_57:Derived values; they change when the database or cache module rotates its credential.
  count                   = var.include_connection_urls ? 1 : 0
  name                    = "${var.name_prefix}/connections"
  description             = "VoiceOS connection URLs (PostgreSQL, Redis/Valkey)"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = var.recovery_window_in_days
}

resource "aws_secretsmanager_secret_version" "connections" {
  count     = var.include_connection_urls ? 1 : 0
  secret_id = aws_secretsmanager_secret.connections[0].id
  secret_string = jsonencode({
    DATABASE_URL = var.database_url
    REDIS_URL    = var.redis_url
  })
}

locals {
  app_ref = { for k in local.app_keys : k => "${aws_secretsmanager_secret.app.arn}:${k}::" }

  turn_ref = "${aws_secretsmanager_secret.turn.arn}:TURN_SECRET::"

  # Control plane (api, worker, migrate).
  ecs_secrets = concat(
    [for k in local.app_keys : { name = k, valueFrom = local.app_ref[k] }],
    [for k in local.connection_keys : { name = k, valueFrom = "${aws_secretsmanager_secret.connections[0].arn}:${k}::" }],
  )
  # The voice runtime verifies tickets, files reports and mints TURN credentials (an HMAC
  # of the TURN secret, which RuntimeSettings reads as TURN_PASSWORD). No database access.
  runtime_secrets = [
    { name = "RUNTIME_TOKEN_SECRET", valueFrom = local.app_ref["RUNTIME_TOKEN_SECRET"] },
    { name = "INTERNAL_API_TOKEN", valueFrom = local.app_ref["INTERNAL_API_TOKEN"] },
    { name = "TURN_PASSWORD", valueFrom = local.turn_ref },
  ]
}
