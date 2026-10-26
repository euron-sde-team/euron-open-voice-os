variable "name_prefix" {
  description = "Prefix for every resource name (at most 24 characters, like the service module)."
  type        = string
}

variable "vpc_id" {
  description = "VPC of the relay and the runtime tasks."
  type        = string
}

variable "vpc_cidr_block" {
  description = "VPC CIDR: the only peers coturn will relay to."
  type        = string
}

variable "public_subnet_id" {
  description = "Public subnet for the network load balancer and its Elastic IP (one zone, see the module header)."
  type        = string
}

variable "private_subnet_id" {
  description = "Private subnet for the coturn instance, in the same zone as public_subnet_id."
  type        = string
}

variable "runtime_security_group_id" {
  description = "Runtime task security group (service module security_group_ids[\"runtime\"]); UDP between it and the relay is opened both ways."
  type        = string
}

variable "turn_secret_arn" {
  description = "Secret holding TURN_SECRET (secrets module turn_secret_arn)."
  type        = string
}

variable "kms_key_arn" {
  description = "CMK that encrypts the secret and the instance's root volume."
  type        = string
}

variable "log_group_name" {
  description = "CloudWatch log group for coturn (observability module log_group_names[\"turn\"])."
  type        = string
}

variable "image" {
  description = "coturn image, pinned."
  type        = string
  default     = "coturn/coturn:4.6.3"
}

variable "instance_type" {
  description = "ARM64 (Graviton) instance type. A t4g.small relays a few hundred concurrent calls; bandwidth is the limit, not CPU."
  type        = string
  default     = "t4g.small"
}

variable "ami_id" {
  description = "AMI for the instance. Null: the latest Amazon Linux 2023 ARM64 AMI from the public SSM parameter."
  type        = string
  default     = null
}

variable "relay_port_min" {
  description = "First UDP relay port. Each relay port is one load balancer listener."
  type        = number
  default     = 49160
}

variable "relay_port_max" {
  description = "Last UDP relay port; each concurrent relayed call uses one. A network load balancer allows 50 listeners, one of which serves port 3478."
  type        = number
  default     = 49199
  validation {
    condition     = var.relay_port_max >= var.relay_port_min && var.relay_port_max - var.relay_port_min < 48
    error_message = "relay_port_max must be at least relay_port_min, with at most 48 relay ports."
  }
}

variable "realm" {
  description = "TURN realm advertised to clients."
  type        = string
  default     = "voiceos"
}

variable "deletion_protection" {
  description = "Block accidental deletion of the load balancer."
  type        = bool
  default     = true
}
