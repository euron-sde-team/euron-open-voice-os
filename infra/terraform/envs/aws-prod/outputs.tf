output "url" {
  description = "Public URL (dashboard, admin API under /api, SDK under /v1)."
  value       = module.service.url
}

output "runtime_url" {
  description = "Public URL of the voice runtime (RUNTIME_PUBLIC_URL)."
  value       = module.service.runtime_url
}

output "load_balancer_dns_name" {
  description = "CNAME target for both host names when the zone is not in Route53."
  value       = module.service.alb_dns_name
}

output "turn_public_ip" {
  description = "Elastic IP of the TURN relay (allow UDP 3478 and the relay ports to it on restrictive networks)."
  value       = module.turn.public_ip
}

output "cluster_name" {
  description = "ECS cluster."
  value       = module.service.cluster_name
}

output "services" {
  description = "ECS service names."
  value       = module.service.service_names
}

output "ecr_repositories" {
  description = "Image repositories."
  value       = module.ecr.repository_urls
}

output "run_task" {
  description = "Parameters for one-off tasks (migrate, create-owner, seed-demo)."
  value       = module.service.run_task
}

output "objects_bucket" {
  description = "Objects bucket (OBJECTS_BUCKET)."
  value       = module.storage.bucket_name
}

output "kms_key_alias" {
  description = "KMS key alias (KMS_KEY_ID)."
  value       = module.kms.alias_name
}

output "dashboard_name" {
  description = "CloudWatch dashboard."
  value       = module.observability.dashboard_name
}
