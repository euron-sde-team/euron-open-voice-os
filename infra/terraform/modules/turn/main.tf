# The TURN relay WebRTC callers need when their network blocks direct UDP to the runtime
# (most corporate and mobile networks). coturn checks short-lived credentials the runtime
# mints per session (HMAC of TURN_SECRET, `use-auth-secret`); there is no static password.
#
#   browser ──UDP 3478 / relay ports──► NLB (Elastic IP) ──► coturn (EC2, private subnet)
#                                                              │ relays only to the VPC
#                                                              ▼
#                                                     runtime tasks (UDP, by security group)
#
# Why EC2 and not Fargate: coturn must advertise one stable public address (the Elastic
# IP of the load balancer), and every relay port is its own NLB listener and target group,
# more than an ECS service can attach. One instance serves thousands of relayed calls; a
# second TURN deployment in another AZ is how to add redundancy.
#
# Hardening: no public IP and no SSH (Session Manager instead), IMDSv2 only, encrypted
# root volume, the secret read at boot through the instance role and written to a root
# only file, coturn running read-only in a container, and peers limited to the VPC CIDR so
# the relay can never reach the metadata service, other networks or the internet.
data "aws_region" "current" {}
data "aws_partition" "current" {}

data "aws_ssm_parameter" "ami" {
  count = var.ami_id == null ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

locals {
  region      = data.aws_region.current.region
  ami_id      = coalesce(var.ami_id, try(data.aws_ssm_parameter.ami[0].value, null))
  relay_ports = range(var.relay_port_min, var.relay_port_max + 1)

  # Listening port over UDP and TCP (for networks that block UDP) on one TCP_UDP listener,
  # since a load balancer allows one listener per port, then each relay port.
  listeners = merge(
    { "listen-3478" = { port = 3478, protocol = "TCP_UDP" } },
    { for p in local.relay_ports : "udp-${p}" => { port = p, protocol = "UDP" } },
  )
}

resource "aws_eip" "this" {
  domain = "vpc"
  tags   = { Name = "${var.name_prefix}-turn" }
}

# ─── Network load balancer ───────────────────────────────────────────────────

resource "aws_lb" "this" {
  #checkov:skip=CKV_AWS_150:Deletion protection is an input (deletion_protection); aws-prod enables it.
  #checkov:skip=CKV_AWS_91:Access logs for a UDP relay would record every caller's address; VPC flow logs already cover the network path.
  #checkov:skip=CKV_AWS_152:One availability zone on purpose: coturn advertises the single Elastic IP of this zone (see the header).
  name                       = "${var.name_prefix}-turn"
  load_balancer_type         = "network"
  internal                   = false
  enable_deletion_protection = var.deletion_protection

  subnet_mapping {
    subnet_id     = var.public_subnet_id
    allocation_id = aws_eip.this.id
  }
}

resource "aws_lb_target_group" "this" {
  for_each    = local.listeners
  name        = substr("${var.name_prefix}-turn-${each.key}", 0, 32)
  port        = each.value.port
  protocol    = each.value.protocol
  target_type = "instance"
  vpc_id      = var.vpc_id
  # Relayed media is long-lived; give a replaced instance's calls time to end.
  deregistration_delay = 60
  # coturn's own health endpoint (`prometheus`, port 9641): it answers only while the
  # relay process is up, which a bare TCP connect to 3478 would not tell apart.
  health_check {
    protocol = "HTTP"
    port     = "9641"
    path     = "/"
    matcher  = "200"
    interval = 10
  }
}

resource "aws_lb_listener" "this" {
  #checkov:skip=CKV_AWS_2:TURN speaks STUN/TURN over UDP and TCP, not HTTP; media is encrypted end to end by WebRTC (DTLS-SRTP).
  #checkov:skip=CKV_AWS_103:Not a TLS listener (see CKV_AWS_2).
  for_each          = local.listeners
  load_balancer_arn = aws_lb.this.arn
  port              = each.value.port
  protocol          = each.value.protocol
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this[each.key].arn
  }
}

resource "aws_lb_target_group_attachment" "this" {
  for_each         = local.listeners
  target_group_arn = aws_lb_target_group.this[each.key].arn
  target_id        = aws_instance.this.id
  port             = each.value.port
}

# ─── Security groups ─────────────────────────────────────────────────────────

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-turn"
  description = "TURN relay: callers on 3478 and the relay ports, runtime tasks over UDP"
  vpc_id      = var.vpc_id
  tags        = { Name = "${var.name_prefix}-turn" }
}

# The network load balancer preserves the caller's address, so callers are allowed here
# directly. That is the point of a TURN server; credentials gate every allocation.
resource "aws_vpc_security_group_ingress_rule" "callers" {
  #checkov:skip=CKV_AWS_24:Not SSH; TURN must accept callers from anywhere (credentials gate every allocation).
  #checkov:skip=CKV_AWS_25:Not RDP; see CKV_AWS_24.
  #checkov:skip=CKV_AWS_260:Not HTTP; see CKV_AWS_24.
  for_each          = { tcp = [3478, 3478], udp = [3478, 3478], relay = [var.relay_port_min, var.relay_port_max] }
  security_group_id = aws_security_group.this.id
  description       = "TURN callers (${each.key})"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = each.key == "tcp" ? "tcp" : "udp"
  from_port         = each.value[0]
  to_port           = each.value[1]
}

# Health checks (and an in-VPC Prometheus) on coturn's metrics port; never public.
resource "aws_vpc_security_group_ingress_rule" "health" {
  security_group_id = aws_security_group.this.id
  description       = "Load balancer health checks and metrics from inside the VPC"
  cidr_ipv4         = var.vpc_cidr_block
  ip_protocol       = "tcp"
  from_port         = 9641
  to_port           = 9641
}

resource "aws_vpc_security_group_egress_rule" "https" {
  security_group_id = aws_security_group.this.id
  description       = "HTTPS: the coturn image, Secrets Manager, CloudWatch Logs, Session Manager"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# Relayed media between coturn and the runtime's WebRTC peer connections (aiortc picks
# its UDP ports from the ephemeral range).
resource "aws_vpc_security_group_egress_rule" "to_runtime" {
  security_group_id            = aws_security_group.this.id
  description                  = "Relayed media to runtime tasks"
  referenced_security_group_id = var.runtime_security_group_id
  ip_protocol                  = "udp"
  from_port                    = 1024
  to_port                      = 65535
}

resource "aws_vpc_security_group_ingress_rule" "from_runtime" {
  security_group_id            = aws_security_group.this.id
  description                  = "Relayed media from runtime tasks"
  referenced_security_group_id = var.runtime_security_group_id
  ip_protocol                  = "udp"
  from_port                    = var.relay_port_min
  to_port                      = var.relay_port_max
}

resource "aws_vpc_security_group_ingress_rule" "runtime_from_turn" {
  #checkov:skip=CKV_AWS_25:Source is the TURN relay's security group, not 0.0.0.0/0; the UDP ephemeral range merely contains 3389.
  security_group_id            = var.runtime_security_group_id
  description                  = "Relayed media from the TURN relay"
  referenced_security_group_id = aws_security_group.this.id
  ip_protocol                  = "udp"
  from_port                    = 1024
  to_port                      = 65535
}

resource "aws_vpc_security_group_egress_rule" "runtime_to_turn" {
  security_group_id            = var.runtime_security_group_id
  description                  = "Relayed media to the TURN relay"
  referenced_security_group_id = aws_security_group.this.id
  ip_protocol                  = "udp"
  from_port                    = var.relay_port_min
  to_port                      = var.relay_port_max
}

# ─── IAM ─────────────────────────────────────────────────────────────────────

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.name_prefix}-turn"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# Session Manager instead of SSH: no key pair, no inbound port.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "this" {
  statement {
    sid       = "ReadTurnSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.turn_secret_arn]
  }
  statement {
    sid       = "DecryptTurnSecret"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["secretsmanager.${local.region}.amazonaws.com"]
    }
  }
  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:${data.aws_partition.current.partition}:logs:${local.region}:*:log-group:${var.log_group_name}:*"]
  }
}

resource "aws_iam_role_policy" "this" {
  name   = "turn"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.this.json
}

resource "aws_iam_instance_profile" "this" {
  name = "${var.name_prefix}-turn"
  role = aws_iam_role.this.name
}

# ─── Instance ────────────────────────────────────────────────────────────────

resource "aws_instance" "this" {
  ami                         = local.ami_id
  instance_type               = var.instance_type
  subnet_id                   = var.private_subnet_id
  vpc_security_group_ids      = [aws_security_group.this.id]
  iam_instance_profile        = aws_iam_instance_profile.this.name
  associate_public_ip_address = false
  monitoring                  = true
  ebs_optimized               = true

  metadata_options {
    http_tokens                 = "required"
    http_endpoint               = "enabled"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    encrypted   = true
    kms_key_id  = var.kms_key_arn
    volume_type = "gp3"
    volume_size = 20
  }

  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    region         = local.region
    secret_arn     = var.turn_secret_arn
    public_ip      = aws_eip.this.public_ip
    realm          = var.realm
    relay_port_min = var.relay_port_min
    relay_port_max = var.relay_port_max
    peer_range     = "${cidrhost(var.vpc_cidr_block, 0)}-${cidrhost(var.vpc_cidr_block, -1)}"
    image          = var.image
    log_group      = var.log_group_name
  })

  tags = { Name = "${var.name_prefix}-turn" }

  # A new AMI is picked up when the instance is replaced on purpose, not on every plan.
  lifecycle {
    ignore_changes = [ami]
  }
}
