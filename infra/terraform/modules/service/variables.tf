variable "name_prefix" {
  description = "Deployment prefix, e.g. \"voiceos-prod\". At most 24 characters, so target group names stay unique within AWS's 32-character limit."
  type        = string
  validation {
    condition     = length(var.name_prefix) <= 24
    error_message = "name_prefix must be at most 24 characters."
  }
}

variable "vpc_id" {
  description = "VPC of the load balancer and the tasks."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for the load balancer."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnets the tasks run in."
  type        = list(string)
}

variable "hostname" {
  description = "Public host name of the dashboard and API, e.g. voice.example.com. The certificate must cover it."
  type        = string
}

variable "runtime_hostname" {
  description = "Public host name browsers reach the voice runtime on (RUNTIME_PUBLIC_URL), e.g. voice-rt.example.com. Same load balancer; the certificate must cover it too."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate (same region) for the HTTPS listener, covering hostname and runtime_hostname."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone to create the hostname and runtime_hostname alias records in. Null: point DNS at alb_dns_name yourself."
  type        = string
  default     = null
}

variable "api_image" {
  description = "Full api image reference (also runs migrate), e.g. <registry>/voiceos-prod/api:<tag>."
  type        = string
}

variable "runtime_image" {
  description = "Full runtime image reference (also runs the worker, which holds benchmark conversations), e.g. <registry>/voiceos-prod/runtime:<tag>."
  type        = string
}

variable "speech_image" {
  description = "Full speech image reference (Whisper and Kokoro), e.g. <registry>/voiceos-prod/speech:<tag>."
  type        = string
}

variable "web_image" {
  description = "Full web image reference, e.g. <registry>/voiceos-prod/web:<tag>."
  type        = string
}

variable "container_port" {
  description = "Port every container listens on (PORT)."
  type        = number
  default     = 8080
}

variable "environment" {
  description = "Plain environment for api, worker and migrate (RUNTIME_PUBLIC_URL, RUNTIME_INTERNAL_URL and OBJECTS_BUCKET are set by the module). Never secrets."
  type        = map(string)
  default     = {}
}

variable "runtime_environment" {
  description = "Plain environment for the runtime (CONTROL_PLANE_URL and ALLOWED_ORIGINS are set by the module; pass ICE_URLS from the turn module). Never secrets."
  type        = map(string)
  default     = {}
}

variable "speech_environment" {
  description = "Plain environment for the speech service (models dir, preload, concurrency and threads are set by the module). Never secrets."
  type        = map(string)
  default     = {}
}

variable "web_environment" {
  description = "Plain environment for web (API_INTERNAL_URL and RUNTIME_PUBLIC_URL are set by the module). Never secrets."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Secrets injected into api, worker and migrate: [{ name, valueFrom = \"<secret arn>:<json key>::\" }] (secrets module ecs_secrets)."
  type        = list(object({ name = string, valueFrom = string }))
  default     = []
}

variable "runtime_secrets" {
  description = "Secrets injected into the runtime (secrets module runtime_secrets)."
  type        = list(object({ name = string, valueFrom = string }))
  default     = []
}

variable "kms_key_arn" {
  description = "CMK that seals provider API keys, encrypts the objects bucket and the injected secrets."
  type        = string
}

variable "objects_bucket_arn" {
  description = "Objects bucket (storage module bucket_arn)."
  type        = string
}

variable "objects_bucket_name" {
  description = "Objects bucket name (storage module bucket_name), passed as OBJECTS_BUCKET."
  type        = string
}

variable "db_security_group_id" {
  description = "Database security group; api, worker and migrate get ingress on it."
  type        = string
}

variable "db_port" {
  description = "Database port."
  type        = number
  default     = 5432
}

variable "cache_security_group_id" {
  description = "Cache security group; api, worker and migrate get ingress on it."
  type        = string
}

variable "cache_port" {
  description = "Cache port."
  type        = number
  default     = 6379
}

variable "log_group_names" {
  description = "CloudWatch log group per app: { api, runtime, speech, worker, web, migrate } (observability module log_group_names)."
  type        = map(string)
  validation {
    condition     = alltrue([for k in ["api", "runtime", "speech", "worker", "web", "migrate"] : contains(keys(var.log_group_names), k)])
    error_message = "log_group_names needs api, runtime, speech, worker, web and migrate."
  }
}

variable "logs_kms_key_arn" {
  description = "CMK for the WAF log group. Null uses CloudWatch's default encryption."
  type        = string
  default     = null
}

variable "cpu_architecture" {
  description = "ARM64 (Graviton, cheaper) or X86_64. Images must be built for it."
  type        = string
  default     = "ARM64"
}

variable "container_insights" {
  description = "ECS Container Insights: enabled, enhanced or disabled."
  type        = string
  default     = "enabled"
}

variable "api_cpu" {
  description = "Fargate CPU units per api task."
  type        = number
  default     = 1024
}

variable "api_memory" {
  description = "Fargate memory (MiB) per api task."
  type        = number
  default     = 2048
}

variable "api_min_count" {
  description = "Minimum (and initial) api task count."
  type        = number
  default     = 2
}

variable "api_max_count" {
  description = "Maximum api task count under autoscaling. Equal to api_min_count disables scaling."
  type        = number
  default     = 6
}

variable "runtime_cpu" {
  description = "Fargate CPU units per runtime task. Each live call resamples audio and runs voice activity and turn detection."
  type        = number
  default     = 1024
}

variable "runtime_memory" {
  description = "Fargate memory (MiB) per runtime task."
  type        = number
  default     = 2048
}

variable "runtime_min_count" {
  description = "Minimum (and initial) runtime task count."
  type        = number
  default     = 2
}

variable "runtime_max_count" {
  description = "Maximum runtime task count under autoscaling. Size with MAX_SESSIONS per task."
  type        = number
  default     = 8
}

variable "runtime_drain_seconds" {
  description = "How long the load balancer lets a deregistering runtime task finish its live calls before ECS stops it."
  type        = number
  default     = 300
  validation {
    condition     = var.runtime_drain_seconds >= 0 && var.runtime_drain_seconds <= 3600
    error_message = "runtime_drain_seconds must be between 0 and 3600."
  }
}

variable "speech_cpu" {
  description = "Fargate CPU units per speech task. Whisper small and Kokoro are CPU bound: 4 vCPU recognizes a short utterance in about a second."
  type        = number
  default     = 4096
}

variable "speech_memory" {
  description = "Fargate memory (MiB) per speech task (Whisper base and small plus Kokoro fit in 8 GiB with room for concurrency)."
  type        = number
  default     = 8192
}

variable "speech_min_count" {
  description = "Minimum (and initial) speech task count."
  type        = number
  default     = 1
}

variable "speech_max_count" {
  description = "Maximum speech task count under autoscaling."
  type        = number
  default     = 4
}

variable "speech_ephemeral_storage_gib" {
  description = "Task storage for the downloaded models (about 1 GiB for tiny, base and small plus Kokoro). Fargate allows 21 to 200."
  type        = number
  default     = 30
  validation {
    condition     = var.speech_ephemeral_storage_gib >= 21 && var.speech_ephemeral_storage_gib <= 200
    error_message = "speech_ephemeral_storage_gib must be between 21 and 200."
  }
}

variable "speech_whisper_download" {
  description = "Whisper sizes the models init container fetches (checksummed), comma separated."
  type        = string
  default     = "base,small"
}

variable "speech_whisper_preload" {
  description = "Whisper sizes loaded at start (WHISPER_PRELOAD); others load on first use."
  type        = string
  default     = "base,small"
}

variable "speech_concurrency" {
  description = "Concurrent recognitions and syntheses per speech task (SPEECH_CONCURRENCY)."
  type        = number
  default     = 2
}

variable "speech_threads" {
  description = "Threads per recognition or synthesis (SPEECH_THREADS); concurrency x threads should not exceed the task's vCPUs."
  type        = number
  default     = 2
}

variable "worker_cpu" {
  description = "Fargate CPU units for the worker."
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "Fargate memory (MiB) for the worker."
  type        = number
  default     = 1024
}

variable "worker_count" {
  description = "Worker task count. Not autoscaled; deploys replace tasks rather than double them."
  type        = number
  default     = 1
}

variable "web_cpu" {
  description = "Fargate CPU units per web task."
  type        = number
  default     = 512
}

variable "web_memory" {
  description = "Fargate memory (MiB) per web task."
  type        = number
  default     = 1024
}

variable "web_min_count" {
  description = "Minimum (and initial) web task count."
  type        = number
  default     = 1
}

variable "web_max_count" {
  description = "Maximum web task count under autoscaling."
  type        = number
  default     = 3
}

variable "cpu_target_percent" {
  description = "Average CPU the autoscaler aims for (api, runtime, speech and web)."
  type        = number
  default     = 60
}

variable "idle_timeout" {
  description = "Load balancer idle timeout in seconds. A live call sends audio every 20 ms, so this only reaps abandoned connections."
  type        = number
  default     = 120
}

variable "deletion_protection" {
  description = "Block accidental deletion of the load balancer."
  type        = bool
  default     = true
}

variable "access_logs_bucket" {
  description = "Existing bucket for load balancer access logs (needs the ELB log-delivery bucket policy). Null disables."
  type        = string
  default     = null
}

variable "metrics_allowed_cidrs" {
  description = "Source CIDRs allowed to read /metrics through the load balancer. Empty: /metrics answers 404 at the edge."
  type        = list(string)
  default     = []
}

variable "enable_waf" {
  description = "Attach a WAF web ACL (managed rule sets plus a per-IP flood guard) to the load balancer."
  type        = bool
  default     = true
}

variable "waf_rate_limit_per_5min" {
  description = "Requests per source IP per 5 minutes before WAF blocks. Keep it high: SDK backends often sit behind one NAT address."
  type        = number
  default     = 20000
}

variable "waf_log_retention_days" {
  description = "WAF log retention."
  type        = number
  default     = 30
}

variable "worker_metrics_cidrs" {
  description = "Source CIDRs (an in-VPC Prometheus) allowed to scrape the worker's /metrics. Empty: the worker has no ingress at all."
  type        = list(string)
  default     = []
}

variable "worker_metrics_port" {
  description = "Port the worker serves /metrics on; must match WORKER_METRICS_PORT (default 9464)."
  type        = number
  default     = 9464
}

variable "provider_egress" {
  description = "Extra egress from the runtime tasks for providers not on HTTPS 443, as { cidr, port } pairs (for example Ollama or vLLM inside the VPC). Empty: HTTPS only."
  type = list(object({
    cidr = string
    port = number
  }))
  default = []
}
