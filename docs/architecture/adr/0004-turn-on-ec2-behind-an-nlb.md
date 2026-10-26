# ADR-0004: TURN on EC2 behind a network load balancer

- **Status:** Accepted
- **Date:** 2026-10-26

## Context

WebRTC media is UDP. Runtime tasks live in private subnets, and many callers sit behind
NATs and firewalls, so a TURN relay is needed for WebRTC to connect reliably (the
WebSocket transport is the fallback when it cannot). coturn needs one stable public
address that it advertises in its relay candidates, a UDP port range for relays, and the
ability to reach the runtime tasks. An Application Load Balancer cannot carry UDP. An ECS
service can attach at most five target groups, and every relay port needs its own network
load balancer listener and target group.

## Decision

The `turn` Terraform module runs coturn (the pinned `coturn/coturn` image) on one hardened
EC2 instance (ARM64, IMDSv2 only, no SSH, encrypted root volume) in a private subnet,
behind a single-zone network load balancer with an Elastic IP: one `TCP_UDP` listener on
3478 plus one UDP listener per relay port (40 by default). coturn uses `use-auth-secret`
with `TURN_SECRET` from its own Secrets Manager secret; the runtime mints per-call
credentials from the same secret. coturn relays only to the VPC CIDR. Locally, the `turn`
Compose service runs the same image; browsers use `ICE_URLS`, the runtime uses its private
address, `SERVER_ICE_URLS`.

## Consequences

**Good**
- WebRTC works from restrictive networks, with no static TURN password and no open relay
  to the internet.
- The relay is independent of runtime deployments.

**Bad / caveats**
- One instance in one zone: for redundancy deploy the module twice and list both in
  `ICE_URLS`.
- An EC2 instance to patch (Amazon Linux 2023, Session Manager access).

## Alternatives considered

- **Fargate**: no stable public address for coturn to advertise, and the target group
  limit per service.
- **A hosted TURN service**: would send callers' media through a third party, against the
  privacy default.
