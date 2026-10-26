# `turn` module

The TURN relay WebRTC callers need when their network blocks direct UDP to the runtime: coturn on one hardened EC2 instance behind a single-zone network load balancer with an Elastic IP.

- **Credentials**: `use-auth-secret`. The runtime mints a short-lived username and HMAC per session from `TURN_SECRET` (`<name_prefix>/turn` in Secrets Manager); coturn checks it with the same secret. There is no static TURN password.
- **Network load balancer**: one `TCP_UDP` listener on 3478 (a load balancer allows one listener per port), plus one UDP listener per relay port (`relay_port_min` to `relay_port_max`, 40 by default), all forwarding to the instance with the caller's address preserved. One zone on purpose: coturn advertises the single Elastic IP (`external-ip`).
- **Relay scope**: `denied-peer-ip` everything, `allowed-peer-ip` the VPC CIDR only, so the relay reaches the runtime tasks and nothing else (no metadata service, no other network, no internet). Security group rules open UDP between the relay and the runtime's security group both ways.
- **Health**: the load balancer checks coturn's own endpoint (`prometheus`, HTTP `/` on 9641, open to the VPC only), which also serves TURN metrics at `/metrics`.
- **Instance**: Amazon Linux 2023 ARM64, no public IP, no SSH key (Session Manager), IMDSv2 only, encrypted gp3 root volume with the CMK, detailed monitoring. At boot it reads `TURN_SECRET` through its instance role (that one secret only), writes a config file only coturn can read, and runs the pinned coturn image read-only with logs to CloudWatch.
- **Why not Fargate**: coturn needs one stable public address, and every relay port is its own target group, more than an ECS service can attach.

Scale and redundancy: one `t4g.small` relays a few hundred concurrent calls (bandwidth bound). For redundancy deploy the module twice in two zones and list both in `ICE_URLS`.

Not applied in `local-floci`: locally the `turn` Compose service runs the same coturn image.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. | `string` | required |
| `vpc_id`, `vpc_cidr_block` | VPC, and the only peers coturn relays to. | `string` | required |
| `public_subnet_id` | Subnet for the load balancer and Elastic IP. | `string` | required |
| `private_subnet_id` | Subnet for the instance (same zone). | `string` | required |
| `runtime_security_group_id` | Runtime task security group. | `string` | required |
| `turn_secret_arn` | Secret holding `TURN_SECRET`. | `string` | required |
| `kms_key_arn` | CMK for the secret and the root volume. | `string` | required |
| `log_group_name` | Log group for coturn. | `string` | required |
| `image` | coturn image. | `string` | `"coturn/coturn:4.6.3"` |
| `instance_type` | ARM64 instance type. | `string` | `"t4g.small"` |
| `ami_id` | AMI; null uses the latest Amazon Linux 2023 ARM64. | `string` | `null` |
| `relay_port_min`, `relay_port_max` | UDP relay port range (at most 48 ports). | `number` | `49160`, `49199` |
| `realm` | TURN realm. | `string` | `"voiceos"` |
| `deletion_protection` | Protect the load balancer. | `bool` | `true` |

## Outputs

| Name | Description |
|---|---|
| `public_ip` | Elastic IP of the relay. |
| `ice_urls` | `ICE_URLS` for the runtime (UDP, then TCP). |
| `nlb_arn_suffix`, `target_group_arn_suffix` | For the observability module's TURN alarm. |
| `security_group_id` | Relay security group. |
| `instance_id` | Relay instance. |
