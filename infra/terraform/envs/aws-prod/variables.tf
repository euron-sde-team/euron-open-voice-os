variable "region" {
  description = "AWS region."
  type        = string
}

variable "environment" {
  description = "Environment tag."
  type        = string
  default     = "prod"
}

variable "extra_tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}

variable "name_prefix" {
  description = "Prefix for every resource name (at most 24 characters); the objects bucket name derives from it, so make it globally unique (e.g. \"acme-voiceos-prod\")."
  type        = string
}

variable "hostname" {
  description = "Public host name of the dashboard and API, e.g. voice.example.com."
  type        = string
}

variable "runtime_hostname" {
  description = "Public host name browsers reach the voice runtime on, e.g. voice-rt.example.com. Same load balancer and certificate."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate in the same region covering hostname and runtime_hostname."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone for both alias records. Null: create the CNAMEs yourself (load_balancer_dns_name output)."
  type        = string
  default     = null
}

variable "image_tag" {
  description = "Image tag to deploy (the git commit or a release)."
  type        = string
}

variable "alarm_email" {
  description = "Alarm notification address."
  type        = string
  default     = null
}

variable "api_extra_environment" {
  description = "Extra api/worker environment (see docs/guides/configuration.md). Never secrets."
  type        = map(string)
  default     = {}
}

variable "runtime_extra_environment" {
  description = "Extra runtime environment (e.g. AGENT_CACHE_TTL_S, REPORT_TIMEOUT_S). Never secrets."
  type        = map(string)
  default     = {}
}

variable "runtime_max_sessions" {
  description = "Concurrent voice sessions per runtime task (MAX_SESSIONS); new sessions get 503 above it."
  type        = number
  default     = 8
}

variable "audio_retention_days" {
  description = "Days opt-in session audio is kept in S3 before the bucket lifecycle deletes it."
  type        = number
  default     = 30
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "cache_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.small"
}

variable "turn_instance_type" {
  description = "ARM64 instance type for the TURN relay."
  type        = string
  default     = "t4g.small"
}

variable "turn_ami_id" {
  description = "AMI for the TURN relay. Null: the latest Amazon Linux 2023 ARM64 AMI."
  type        = string
  default     = null
}

variable "metrics_allowed_cidrs" {
  description = "Source CIDRs allowed to scrape the api's /metrics through the load balancer."
  type        = list(string)
  default     = []
}

variable "session_failed_threshold" {
  description = "Failed voice sessions per 5 minutes that raise an alarm. Null: no alarm."
  type        = number
  default     = null
}

variable "worker_metrics_cidrs" {
  description = "In-VPC Prometheus CIDRs allowed to scrape the worker's /metrics on port 9464. Empty: no worker ingress."
  type        = list(string)
  default     = []
}

variable "provider_egress" {
  description = "Extra runtime egress for self-hosted providers not on HTTPS 443, as { cidr, port } pairs."
  type = list(object({
    cidr = string
    port = number
  }))
  default = []
}
