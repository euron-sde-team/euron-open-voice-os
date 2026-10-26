output "secret_arn" {
  description = "ARN of the JSON secret holding SESSION_SECRET, API_KEY_PEPPER, RUNTIME_TOKEN_SECRET and INTERNAL_API_TOKEN."
  value       = aws_secretsmanager_secret.app.arn
}

output "connections_secret_arn" {
  description = "ARN of the JSON secret holding DATABASE_URL and REDIS_URL (null without include_connection_urls)."
  value       = var.include_connection_urls ? aws_secretsmanager_secret.connections[0].arn : null
}

output "keys" {
  description = "Every environment variable the secrets provide."
  value       = sort(concat(local.app_keys, ["TURN_SECRET"], local.connection_keys))
}

output "ecs_secrets" {
  description = "ECS `secrets` entries for the control plane (api, worker, migrate): [{ name, valueFrom = \"<arn>:<key>::\" }]."
  value       = local.ecs_secrets
}

output "runtime_secrets" {
  description = "ECS `secrets` entries for the voice runtime (RUNTIME_TOKEN_SECRET, INTERNAL_API_TOKEN, TURN_PASSWORD)."
  value       = local.runtime_secrets
}

output "turn_secret_arn" {
  description = "ARN of the JSON secret holding TURN_SECRET (read by the TURN relay at boot)."
  value       = aws_secretsmanager_secret.turn.arn
}
