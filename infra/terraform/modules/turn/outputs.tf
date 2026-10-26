output "public_ip" {
  description = "Elastic IP callers reach the relay on."
  value       = aws_eip.this.public_ip
}

output "ice_urls" {
  description = "ICE_URLS for the runtime: TURN over UDP, then over TCP for networks that block UDP."
  value       = "turn:${aws_eip.this.public_ip}:3478?transport=udp,turn:${aws_eip.this.public_ip}:3478?transport=tcp"
}

output "nlb_arn_suffix" {
  description = "Network load balancer ARN suffix, for CloudWatch metrics."
  value       = aws_lb.this.arn_suffix
}

output "target_group_arn_suffix" {
  description = "ARN suffix of the TCP_UDP 3478 target group, for the health alarm."
  value       = aws_lb_target_group.this["listen-3478"].arn_suffix
}

output "security_group_id" {
  description = "Security group of the relay instance."
  value       = aws_security_group.this.id
}

output "instance_id" {
  description = "Relay instance (open a shell with Session Manager)."
  value       = aws_instance.this.id
}
