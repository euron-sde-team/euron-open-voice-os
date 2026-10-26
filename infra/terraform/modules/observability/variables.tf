variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention for the app log groups."
  type        = number
  default     = 30
}

variable "logs_kms_key_arn" {
  description = "CMK for the log groups (its key policy must allow CloudWatch Logs, as the kms module's does). Null uses CloudWatch's default encryption."
  type        = string
  default     = null
}

variable "alarm_email" {
  description = "Address subscribed to alarm notifications (confirm the e-mail AWS sends). Null: subscribe something else to the topic."
  type        = string
  default     = null
}

variable "alb_arn_suffix" {
  description = "Load balancer ARN suffix."
  type        = string
}

variable "ecs_cluster_name" {
  description = "ECS cluster name."
  type        = string
}

variable "lb_services" {
  description = "Load-balanced services (service module `services`): { api = { service_name, target_group_arn_suffix }, runtime = { ... }, web = { ... } }. Must contain api."
  type = map(object({
    service_name            = string
    target_group_arn_suffix = string
  }))
  validation {
    condition     = contains(keys(var.lb_services), "api")
    error_message = "lb_services must contain api."
  }
}

variable "ecs_services" {
  description = "Every ECS service to watch for CPU and memory (service module `service_names`): { api = \"api\", runtime = \"runtime\", speech = \"speech\", ... }."
  type        = map(string)
}

variable "db_instance_identifier" {
  description = "RDS instance identifier."
  type        = string
}

variable "db_max_connections" {
  description = "Connection ceiling the alarm measures against."
  type        = number
  default     = 200
}

variable "cache_replication_group_id" {
  description = "ElastiCache replication group id; nodes are <id>-001, <id>-002, ..."
  type        = string
}

variable "cache_node_count" {
  description = "Nodes in the replication group (cache module num_cache_clusters)."
  type        = number
  default     = 1
}

variable "target_5xx_threshold" {
  description = "5xx responses per 5 minutes (per app, and at the load balancer) that raise an alarm."
  type        = number
  default     = 25
}

variable "api_p95_latency_seconds" {
  description = "api p95 time to first byte that raises an alarm. The control plane never calls a model on a request path."
  type        = number
  default     = 3
}

variable "session_failed_log_pattern" {
  description = "CloudWatch Logs filter pattern matching one runtime log line per failed session."
  type        = string
  default     = "{ ($.msg = \"session failed\") || ($.msg = \"session report dropped\") || ($.msg = \"session rejected: provider setup failed\") }"
}

variable "session_failed_threshold" {
  description = "Failed voice sessions per 5 minutes that raise an alarm. Null: metric and dashboard only, no alarm."
  type        = number
  default     = null
}

variable "enable_turn_alarm" {
  description = "Alarm when the TURN relay fails its network load balancer health check (needs nlb_arn_suffix and nlb_target_group_arn_suffix)."
  type        = bool
  default     = false
}

variable "nlb_arn_suffix" {
  description = "TURN network load balancer ARN suffix (turn module nlb_arn_suffix), with enable_turn_alarm."
  type        = string
  default     = null
}

variable "nlb_target_group_arn_suffix" {
  description = "TURN listening-port target group ARN suffix (turn module target_group_arn_suffix), with enable_turn_alarm."
  type        = string
  default     = null
}
