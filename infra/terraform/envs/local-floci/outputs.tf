output "objects_bucket" {
  description = "OBJECTS_BUCKET for the local stack."
  value       = module.storage.bucket_name
}

output "kms_key_alias" {
  description = "KMS_KEY_ID for the local stack."
  value       = module.kms.alias_name
}

output "app_secret_arn" {
  description = "The emulated Secrets Manager secret (SESSION_SECRET, API_KEY_PEPPER, RUNTIME_TOKEN_SECRET, INTERNAL_API_TOKEN)."
  value       = module.secrets.secret_arn
}

output "turn_secret_arn" {
  description = "The emulated Secrets Manager secret holding TURN_SECRET."
  value       = module.secrets.turn_secret_arn
}
