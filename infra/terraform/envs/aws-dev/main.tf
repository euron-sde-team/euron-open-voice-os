# ─────────────────────────────────────────────────────────────────────────────
# aws-dev: a full, cheaper copy of production. Two AZs, single NAT, single-AZ
# database, one cache node, one speech task, no deletion protection, small autoscaling
# ceilings.
#
# Validate-only in this repository (nothing is ever applied to a real account by
# the project itself); everything needed to deploy is here:
#   cp terraform.tfvars.example terraform.tfvars   # then edit
#   terraform init && terraform apply -target=module.ecr   # push images, then:
#   terraform apply
# ─────────────────────────────────────────────────────────────────────────────

module "kms" {
  source                  = "../../modules/kms"
  name_prefix             = var.name_prefix
  deletion_window_in_days = 7
}

module "network" {
  source                     = "../../modules/network"
  name_prefix                = var.name_prefix
  az_count                   = 2
  single_nat_gateway         = true
  enable_interface_endpoints = false
  logs_kms_key_arn           = module.kms.key_arn
  flow_log_retention_days    = 14
}

module "database" {
  source                = "../../modules/database"
  name_prefix           = var.name_prefix
  vpc_id                = module.network.vpc_id
  subnet_ids            = module.network.private_subnet_ids
  kms_key_arn           = module.kms.key_arn
  instance_class        = var.db_instance_class
  allocated_storage     = 20
  max_allocated_storage = 100
  multi_az              = false
  backup_retention_days = 3
  deletion_protection   = false
  skip_final_snapshot   = true
}

module "cache" {
  source                  = "../../modules/cache"
  name_prefix             = var.name_prefix
  vpc_id                  = module.network.vpc_id
  subnet_ids              = module.network.private_subnet_ids
  kms_key_arn             = module.kms.key_arn
  logs_kms_key_arn        = module.kms.key_arn
  node_type               = var.cache_node_type
  num_cache_clusters      = 1
  recovery_window_in_days = 0
  log_retention_days      = 14
  apply_immediately       = true
}

module "storage" {
  source          = "../../modules/storage"
  name_prefix     = var.name_prefix
  kms_key_arn     = module.kms.key_arn
  expiration_days = var.audio_retention_days
  force_destroy   = true
}

module "secrets" {
  source                  = "../../modules/secrets"
  name_prefix             = var.name_prefix
  kms_key_arn             = module.kms.key_arn
  recovery_window_in_days = 0
  include_connection_urls = true
  database_url            = module.database.connection_url
  redis_url               = module.cache.connection_url
}

module "ecr" {
  source       = "../../modules/ecr"
  name_prefix  = var.name_prefix
  kms_key_arn  = module.kms.key_arn
  force_delete = true
}

locals {
  url = "https://${var.hostname}"

  # Everything the api, worker and migrate read that is not a secret. Secrets
  # (SESSION_SECRET, API_KEY_PEPPER, RUNTIME_TOKEN_SECRET, INTERNAL_API_TOKEN,
  # DATABASE_URL, REDIS_URL) come from module.secrets; RUNTIME_PUBLIC_URL,
  # RUNTIME_INTERNAL_URL and OBJECTS_BUCKET from module.service.
  api_environment = merge({
    ENVIRONMENT   = "production"
    VOICEOS_CLOUD = "aws"
    LOG_LEVEL     = "INFO"
    AWS_REGION    = var.region
    KEY_MODE      = "kms"
    KMS_KEY_ID    = module.kms.alias_name
    STORAGE       = "s3"
    CORS_ORIGINS  = local.url
    COOKIE_SECURE = "true"
    # Trust X-Forwarded-For only from inside the VPC (the load balancer).
    FORWARDED_ALLOW_IPS = module.network.vpc_cidr_block
    # One uvicorn process per task (exact /metrics); scale with tasks. Pool sized so
    # (api_max_count + worker + migrate) x (pool + overflow) stays under db_max_connections.
    WEB_CONCURRENCY = "1"
    DB_POOL_SIZE    = "5"
    DB_MAX_OVERFLOW = "10"
  }, var.api_extra_environment)

  # The runtime: CONTROL_PLANE_URL and ALLOWED_ORIGINS come from module.service, its
  # secrets (RUNTIME_TOKEN_SECRET, INTERNAL_API_TOKEN, TURN_PASSWORD) from module.secrets.
  runtime_environment = merge({
    ENVIRONMENT  = "production"
    LOG_LEVEL    = "INFO"
    MAX_SESSIONS = tostring(var.runtime_max_sessions)
    ICE_URLS     = module.turn.ice_urls
  }, var.runtime_extra_environment)
}

module "service" {
  source             = "../../modules/service"
  name_prefix        = var.name_prefix
  vpc_id             = module.network.vpc_id
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids
  hostname           = var.hostname
  runtime_hostname   = var.runtime_hostname
  certificate_arn    = var.certificate_arn
  route53_zone_id    = var.route53_zone_id

  api_image     = "${module.ecr.repository_urls["api"]}:${var.image_tag}"
  runtime_image = "${module.ecr.repository_urls["runtime"]}:${var.image_tag}"
  speech_image  = "${module.ecr.repository_urls["speech"]}:${var.image_tag}"
  web_image     = "${module.ecr.repository_urls["web"]}:${var.image_tag}"

  environment         = local.api_environment
  runtime_environment = local.runtime_environment
  speech_environment  = { LOG_LEVEL = "INFO" }
  secrets             = module.secrets.ecs_secrets
  runtime_secrets     = module.secrets.runtime_secrets

  kms_key_arn             = module.kms.key_arn
  objects_bucket_arn      = module.storage.bucket_arn
  objects_bucket_name     = module.storage.bucket_name
  db_security_group_id    = module.database.security_group_id
  db_port                 = module.database.port
  cache_security_group_id = module.cache.security_group_id
  log_group_names         = module.observability.log_group_names
  logs_kms_key_arn        = module.kms.key_arn

  api_cpu           = 512
  api_memory        = 1024
  api_min_count     = 1
  api_max_count     = 2
  runtime_min_count = 1
  runtime_max_count = 2
  speech_min_count  = 1
  speech_max_count  = 1
  web_min_count     = 1
  web_max_count     = 2
  worker_count      = 1

  deletion_protection    = false
  enable_waf             = true
  waf_log_retention_days = 14
  metrics_allowed_cidrs  = var.metrics_allowed_cidrs
  worker_metrics_cidrs   = var.worker_metrics_cidrs
  provider_egress        = var.provider_egress
}

module "turn" {
  source                    = "../../modules/turn"
  name_prefix               = var.name_prefix
  vpc_id                    = module.network.vpc_id
  vpc_cidr_block            = module.network.vpc_cidr_block
  public_subnet_id          = module.network.public_subnet_ids[0]
  private_subnet_id         = module.network.private_subnet_ids[0]
  runtime_security_group_id = module.service.security_group_ids["runtime"]
  turn_secret_arn           = module.secrets.turn_secret_arn
  kms_key_arn               = module.kms.key_arn
  log_group_name            = module.observability.log_group_names["turn"]
  instance_type             = var.turn_instance_type
  ami_id                    = var.turn_ami_id
  deletion_protection       = false
}

module "observability" {
  source             = "../../modules/observability"
  name_prefix        = var.name_prefix
  log_retention_days = 14
  logs_kms_key_arn   = module.kms.key_arn
  alarm_email        = var.alarm_email

  alb_arn_suffix   = module.service.alb_arn_suffix
  ecs_cluster_name = module.service.cluster_name
  lb_services      = module.service.services
  ecs_services     = module.service.service_names

  db_instance_identifier     = module.database.instance_identifier
  db_max_connections         = 100
  cache_replication_group_id = module.cache.replication_group_id
  cache_node_count           = 1
  session_failed_threshold   = var.session_failed_threshold

  enable_turn_alarm           = true
  nlb_arn_suffix              = module.turn.nlb_arn_suffix
  nlb_target_group_arn_suffix = module.turn.target_group_arn_suffix
}
