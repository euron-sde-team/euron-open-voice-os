output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "cluster_arn" {
  description = "ECS cluster ARN."
  value       = aws_ecs_cluster.this.arn
}

output "url" {
  description = "Public URL of the dashboard and API."
  value       = local.public_url
}

output "runtime_url" {
  description = "Public URL of the voice runtime (RUNTIME_PUBLIC_URL)."
  value       = local.runtime_url
}

output "internal_urls" {
  description = "Private service URLs through Cloud Map: { api, runtime, speech }."
  value       = local.internal_url
}

output "alb_dns_name" {
  description = "Load balancer DNS name (CNAME target for both host names when the zone is not in Route53)."
  value       = aws_lb.this.dns_name
}

output "alb_arn_suffix" {
  description = "Load balancer ARN suffix, for CloudWatch metrics."
  value       = aws_lb.this.arn_suffix
}

output "services" {
  description = "Load-balanced services: { api, runtime, web } => { service_name, target_group_arn_suffix }."
  value = {
    for k in keys(local.load_balanced) : k => {
      service_name            = aws_ecs_service.this[k].name
      target_group_arn_suffix = aws_lb_target_group.this[k].arn_suffix
    }
  }
}

output "service_names" {
  description = "Every ECS service name (api, runtime, speech, worker, web)."
  value       = { for k, s in aws_ecs_service.this : k => s.name }
}

output "security_group_ids" {
  description = "Task security group per app."
  value       = { for k, sg in aws_security_group.task : k => sg.id }
}

output "task_role_arns" {
  description = "Task role per app."
  value       = { for k, r in aws_iam_role.task : k => r.arn }
}

output "run_task" {
  description = "Parameters for one-off tasks: `voiceos migrate` (task_definition, the default) or `create-owner` as a command override; `seed-demo` runs on seed_task_definition (the runtime image, which holds real conversations)."
  value = {
    cluster              = aws_ecs_cluster.this.name
    task_definition      = aws_ecs_task_definition.this["migrate"].family
    container            = "migrate"
    seed_task_definition = aws_ecs_task_definition.this["worker"].family
    seed_container       = "worker"
    subnets              = var.private_subnet_ids
    security_groups      = [aws_security_group.task["migrate"].id]
    seed_security_groups = [aws_security_group.task["worker"].id]
  }
}
