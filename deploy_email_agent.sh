#!/usr/bin/env bash
# Deploy the SEPARATE email agent to its OWN GreenNode AgentBase runtime.
# First run CREATES a new runtime; later runs UPDATE it (pass RUNTIME_ID).
#   bash deploy_email_agent.sh                      # create new runtime
#   RUNTIME_ID=runtime-xxxx bash deploy_email_agent.sh   # update existing
set -euo pipefail
cd "$(dirname "$0")"

export DOCKER_CONFIG="${DOCKER_CONFIG:-$HOME/.agentbase-docker-config}"
mkdir -p "$DOCKER_CONFIG"
printf '{}' > "$DOCKER_CONFIG/config.json"

S="greennode-agentbase-skills/.claude/skills/agentbase/scripts"
IMAGE_BASE="${IMAGE_BASE:-vcr.vngcloud.vn/111480-abp111915/claw-a-thon-email-agent}"
FLAVOR="${FLAVOR:-runtime-s2-general-2x4}"
PLATFORM="linux/amd64"   # AgentBase runtime is amd64 — do not change.
ENV_FILE="${ENV_FILE:-email-agent/.env}"
RUNTIME_NAME="${RUNTIME_NAME:-claw-a-thon-email-agent}"
TAG="v$(date +%Y%m%d%H%M%S)"
IMAGE="$IMAGE_BASE:$TAG"

echo "============================================================"
echo " Email agent deploy"
echo "   Image   : $IMAGE"
echo "   Flavor  : $FLAVOR   Network: PUBLIC"
echo "   Env file: $ENV_FILE   Platform: $PLATFORM"
echo "   Runtime : ${RUNTIME_ID:-<create new \"$RUNTIME_NAME\">}"
echo "============================================================"

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found."; exit 1; }
docker info >/dev/null 2>&1 || { echo "ERROR: Docker daemon not running."; exit 1; }
[ -f email-agent/Dockerfile ] || { echo "ERROR: email-agent/Dockerfile missing."; exit 1; }
[ -f "$ENV_FILE" ] || { echo "ERROR: env file '$ENV_FILE' missing."; exit 1; }
bash "$S/check_credentials.sh" iam

# Fetch CR credentials and write a base64 auth into the isolated docker config
# (avoids `docker login` + macOS Keychain helper).
echo ">> fetch CR credentials"
TOKEN="$(bash "$S/get_token.sh")"
CR_API="https://agentbase.api.vngcloud.vn/cr/api/v1"
CRED_JSON="$(curl -s "$CR_API/registry-credential" -H "Authorization: Bearer $TOKEN")"
REGISTRY_HOST="vcr.vngcloud.vn"
CR_USER="$(printf '%s' "$CRED_JSON" | jq -r '.username // empty')"
CR_SECRET="$(printf '%s' "$CRED_JSON" | jq -r '.secret // empty')"
[ -n "$CR_USER" ] && [ -n "$CR_SECRET" ] || { echo "ERROR: could not fetch CR credentials."; exit 1; }
AUTH_B64="$(printf '%s:%s' "$CR_USER" "$CR_SECRET" | base64 | tr -d '\n')"
jq -n --arg host "$REGISTRY_HOST" --arg auth "$AUTH_B64" '{auths: {($host): {auth:$auth}}}' > "$DOCKER_CONFIG/config.json"
echo "   wrote auth for $REGISTRY_HOST (user: $CR_USER)"

echo ">> docker build $IMAGE"
docker build --pull --platform "$PLATFORM" -t "$IMAGE" email-agent

echo ">> docker push $IMAGE"
docker push "$IMAGE"

if [ -n "${RUNTIME_ID:-}" ]; then
  echo ">> runtime update $RUNTIME_ID"
  bash "$S/runtime.sh" update "$RUNTIME_ID" \
    --image "$IMAGE" --flavor "$FLAVOR" --env-file "$ENV_FILE" \
    --from-cr --network-mode PUBLIC \
    --min-replicas 1 --max-replicas 1 --cpu-scale 50 --mem-scale 50
  bash "$S/runtime.sh" get "$RUNTIME_ID"
else
  echo ">> runtime create \"$RUNTIME_NAME\""
  bash "$S/runtime.sh" create \
    --name "$RUNTIME_NAME" \
    --description "ZaloPay email agent (sends analytics report emails)" \
    --image "$IMAGE" --flavor "$FLAVOR" --env-file "$ENV_FILE" \
    --from-cr --network-mode PUBLIC \
    --min-replicas 1 --max-replicas 1 --cpu-scale 50 --mem-scale 50
fi

echo ""
echo "Done. Image: $IMAGE"
echo "Console: https://aiplatform.console.vngcloud.vn/agent-runtime?tab=runtime"
