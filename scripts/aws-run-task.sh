#!/usr/bin/env bash
# Run a one-off `voiceos` command as an ECS task, wait for it, print its logs.
#   scripts/aws-run-task.sh <aws-dev|aws-prod> migrate
#   VOICEOS_OWNER_PASSWORD=... scripts/aws-run-task.sh aws-dev create-owner --email you@example.com
#   VOS_DEMO_PASSWORD=... scripts/aws-run-task.sh aws-dev seed-demo
# The command runs as arguments to the `voiceos` CLI (the image's entrypoint). migrate and
# create-owner run on the api image; seed-demo runs on the runtime image (the worker's task
# definition), because it holds real voice conversations through the runtime.
# VOICEOS_OWNER_PASSWORD and VOS_DEMO_PASSWORD, when set, are passed as environment overrides.
set -euo pipefail
ENV="${1:?usage: aws-run-task.sh <env> <voiceos command...>}"; shift
DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/terraform/envs/$ENV"
spec=$(terraform -chdir="$DIR" output -json run_task)
get() { echo "$spec" | python3 -c "import json,sys; v=json.load(sys.stdin)['$1']; print(','.join(v) if isinstance(v, list) else v)"; }
cluster=$(get cluster)
if [[ "${1:-}" == "seed-demo" ]]; then
  taskdef=$(get seed_task_definition); container=$(get seed_container); groups=$(get seed_security_groups)
else
  taskdef=$(get task_definition); container=$(get container); groups=$(get security_groups)
fi
overrides=$(python3 - "$container" "$@" <<'PY'
import json, os, sys
container, *command = sys.argv[1:]
override = {"name": container, "command": command}
env = [{"name": k, "value": os.environ[k]} for k in ("VOICEOS_OWNER_PASSWORD", "VOS_DEMO_PASSWORD") if os.environ.get(k)]
if env:
    override["environment"] = env
print(json.dumps({"containerOverrides": [override]}))
PY
)
network="awsvpcConfiguration={subnets=[$(get subnets)],securityGroups=[$groups],assignPublicIp=DISABLED}"
arn=$(aws ecs run-task --cluster "$cluster" --task-definition "$taskdef" --launch-type FARGATE \
  --network-configuration "$network" --overrides "$overrides" \
  --query 'tasks[0].taskArn' --output text)
echo "started $arn"
aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$arn"
code=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$arn" --query 'tasks[0].containers[0].exitCode' --output text)
group=$(aws ecs describe-task-definition --task-definition "$taskdef" \
  --query 'taskDefinition.containerDefinitions[0].logConfiguration.options."awslogs-group"' --output text)
aws logs tail "$group" --since 15m --format short | tail -40
echo "exit code: $code"
[[ "$code" == "0" ]]
