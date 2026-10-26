#!/usr/bin/env bash
# Plan, apply, re-plan and destroy the full aws-dev environment against a throwaway Floci.
#
# terraform validate cannot see plan-time and apply-time failures (unknown for_each keys,
# rejected arguments, broken references between modules). This runs the real production
# configuration against an AWS API without an AWS account. The repository is not touched:
# the Terraform tree is copied to a temp directory and a provider override is added there.
#
# Expected re-plan drift: Floci does not persist a few attributes (maintenance windows,
# transit encryption mode, log delivery, parameter group values, storage type, KMS rotation
# period, security groups on replication groups and instances, an alarm's extended
# statistic, a network load balancer's Elastic IP mapping). Real AWS stores them all; they
# show as in-place updates. Three more would force a replacement, so the temp copy (never the repository)
# gets override files that ignore exactly them: Cloud Map's health_check_custom_config and
# the TURN instance's ebs_optimized and root volume encryption.
# Takes about five minutes. KEEP_FLOCI=1 keeps the emulator and work dir after a failure.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${TF_FLOCI_PORT:-4596}"
NAME="voiceos-tf-floci"
WORK="$(mktemp -d)"
TF_IMAGE="hashicorp/terraform:1.16.6"
# KEEP_FLOCI=1 leaves the emulator and the work directory for debugging a failed run.
cleanup() {
  if [[ -n "${KEEP_FLOCI:-}" ]]; then echo "kept: container $NAME, work dir $WORK" >&2; return; fi
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -p "127.0.0.1:$PORT:4566" -e FLOCI_HOSTNAME=localhost floci/floci:2.3.0 >/dev/null
for _ in $(seq 1 60); do curl -sf -o /dev/null "http://localhost:$PORT/" && break; sleep 1; done

cp -R "$ROOT/infra/terraform" "$WORK/"
find "$WORK" -name ".terraform*" -prune -exec rm -rf {} +
ENV_DIR="$WORK/terraform/envs/aws-dev"

# The ALB listener needs a certificate: request one from Floci's ACM.
CERT_ARN="$(docker run --rm --add-host host.docker.internal:host-gateway \
  -e AWS_ACCESS_KEY_ID=test -e AWS_SECRET_ACCESS_KEY=test -e AWS_DEFAULT_REGION=us-east-1 \
  amazon/aws-cli:2.31.18 --endpoint-url "http://host.docker.internal:$PORT" \
  acm request-certificate --domain-name voice-dev.example.com --subject-alternative-names voice-rt-dev.example.com --validation-method DNS \
  --query CertificateArn --output text)"

cat > "$ENV_DIR/zz_floci_override.tf" <<'TF'
provider "aws" {
  s3_use_path_style           = true
  skip_credentials_validation = true
  skip_metadata_api_check     = true
}
TF
# Attributes Floci does not persist and AWS treats as replacing (see the header). Override
# files merge into the module's resources in this temp copy only.
cat > "$WORK/terraform/modules/service/zz_floci_override.tf" <<'TF'
resource "aws_service_discovery_service" "this" {
  lifecycle {
    ignore_changes = [health_check_custom_config]
  }
}
TF
cat > "$WORK/terraform/modules/turn/zz_floci_override.tf" <<'TF'
resource "aws_instance" "this" {
  lifecycle {
    ignore_changes = [ami, ebs_optimized, root_block_device]
  }
}
TF
cat > "$ENV_DIR/terraform.tfvars" <<TF
region           = "us-east-1"
name_prefix      = "vos-floci-dev"
hostname         = "voice-dev.example.com"
runtime_hostname = "voice-rt-dev.example.com"
certificate_arn  = "$CERT_ARN"
image_tag        = "0.1.0"
alarm_email      = "oncall@example.com"
TF

tf() {
  docker run --rm -v "$WORK/terraform:/infra" -w /infra/envs/aws-dev \
    --add-host host.docker.internal:host-gateway --add-host 000000000000.host.docker.internal:host-gateway \
    -e AWS_ACCESS_KEY_ID=test -e AWS_SECRET_ACCESS_KEY=test -e AWS_REGION=us-east-1 \
    -e AWS_ENDPOINT_URL="http://host.docker.internal:$PORT" -e TF_IN_AUTOMATION=1 "$TF_IMAGE" "$@"
}

echo "== init";    tf init -input=false -no-color >/dev/null
echo "== plan";    tf plan -input=false -no-color -out=tfplan | grep -E "^Plan:"
echo "== apply";   tf apply -input=false -no-color -auto-approve tfplan | grep -E "^Apply complete"
echo "== re-plan (attributes Floci does not persist may show as updates; nothing may be added or replaced)"
REPLAN="$(tf plan -input=false -no-color)"
echo "$REPLAN" | grep -E "^  # .* will be updated in-place" | sed "s/^  #/  updated:/" || true
echo "$REPLAN" | grep -E "^Plan:|No changes" || true
if echo "$REPLAN" | grep -qE "must be replaced|Plan: [1-9][0-9]* to add"; then
  echo "re-plan wants to add or replace resources: the configuration does not converge" >&2
  echo "$REPLAN" | grep -E "must be replaced|will be created|# forces replacement" | sed 's/^/  /' >&2
  exit 1
fi
# Floci backs ECR with a real registry container it can start only when given the Docker
# socket, which this script deliberately does not hand over. Without it, DeleteRepository
# fails with a ServerException and the provider retries forever, so ECR (whose creation was
# exercised above) is dropped from state before the destroy.
echo "== destroy (ECR left to the throwaway emulator, see comment)"
tf state rm module.ecr >/dev/null
tf destroy -input=false -no-color -auto-approve | grep -E "^Destroy complete"
echo "aws-dev: planned, applied, converged and destroyed against Floci"
