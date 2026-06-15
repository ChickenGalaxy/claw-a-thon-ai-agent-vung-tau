#!/usr/bin/env bash
# Redeploy this agent to GreenNode AgentBase (Custom Agent, managed CR, PUBLIC mode).
# Re-uses the existing runtime + the same settings as previous versions.
# Run on your Mac (needs Docker running + .greennode.json credentials):
#   bash deploy_agentbase.sh
#
# Override flavor if needed, e.g.:
#   FLAVOR=runtime-s1-general-1x2 bash deploy_agentbase.sh
set -euo pipefail
cd "$(dirname "$0")"

# Force Docker to use an isolated config dir WITHOUT any credential helper,
# so `docker login` stores credentials in-file instead of macOS Keychain.
# Fixes "Keychain Error (-60008)" without touching your normal ~/.docker config.
# (Kept in /tmp so the base64 creds never land in the build context.)
export DOCKER_CONFIG="${DOCKER_CONFIG:-$HOME/.agentbase-docker-config}"
mkdir -p "$DOCKER_CONFIG"
printf '{}' > "$DOCKER_CONFIG/config.json"

S="greennode-agentbase-skills/.claude/skills/agentbase/scripts"
RUNTIME_ID="${RUNTIME_ID:-runtime-30d2e3d5-b5d2-4d62-bba8-9ded41801c70}"
IMAGE_BASE="${IMAGE_BASE:-vcr.vngcloud.vn/111480-abp111915/claw-a-thon-ai-agent-vung-tau}"
FLAVOR="${FLAVOR:-runtime-s2-general-2x4}"
# AgentBase Runtime chạy amd64 — KHÔNG đổi. Build arm64 sẽ chắc chắn lỗi khi deploy.
PLATFORM="linux/amd64"
ENV_FILE="${ENV_FILE:-.env}"
TAG="v$(date +%Y%m%d%H%M%S)"
IMAGE="$IMAGE_BASE:$TAG"

echo "============================================================"
echo " Deploy plan"
echo "   Runtime : $RUNTIME_ID (update -> new version)"
echo "   Image   : $IMAGE"
echo "   Flavor  : $FLAVOR   Network: PUBLIC"
echo "   Env file: $ENV_FILE   Platform: $PLATFORM"
echo "============================================================"

# 0. Preflight
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found."; exit 1; }
docker info >/dev/null 2>&1 || { echo "ERROR: Docker daemon not running — start Docker Desktop."; exit 1; }
[ -f Dockerfile ] || { echo "ERROR: Dockerfile missing."; exit 1; }
[ -f "$ENV_FILE" ] || { echo "ERROR: env file '$ENV_FILE' missing."; exit 1; }
bash "$S/check_credentials.sh" iam

# 0b. Local SOURCE sanity — make sure we're about to build the CURRENT code,
# not a stale checkout. Abort early if expected markers are missing.
echo ">> verify local source has latest changes"
MARKER_OK=1
[ -f app/query_engine.py ] || { echo "  MISSING: app/query_engine.py"; MARKER_OK=0; }
grep -q "_extract_items" app/memory.py        || { echo "  MISSING: _extract_items in app/memory.py (recall fix)"; MARKER_OK=0; }
grep -q "^duckdb" requirements.txt             || { echo "  MISSING: duckdb in requirements.txt"; MARKER_OK=0; }
grep -q "run_data_query" app/agent.py          || { echo "  MISSING: run_data_query in app/agent.py"; MARKER_OK=0; }
if [ "$MARKER_OK" != "1" ]; then
  echo "ERROR: local source is missing expected changes — fix files before deploying."
  exit 1
fi
echo "   local source OK"

# Safety: make sure no platform-injected vars are baked into the env file
if grep -qE '^(GREENNODE_CLIENT_ID|GREENNODE_CLIENT_SECRET|GREENNODE_AGENT_IDENTITY|GREENNODE_ENDPOINT_URL)=' "$ENV_FILE"; then
  echo "WARNING: $ENV_FILE contains GREENNODE_* vars that AgentBase auto-injects. Remove them to avoid conflicts."
fi

# 1. Authenticate to the AgentBase CR WITHOUT `docker login`.
# `docker login` on this Mac triggers the broken Keychain helper (Keychain Error -60008),
# so instead we fetch the CR credentials via the API and write them directly into the
# isolated DOCKER_CONFIG as a base64 "auth". `docker push` reads this — no helper involved.
echo ">> fetch CR credentials (skip docker login -> avoid Keychain)"
TOKEN="$(bash "$S/get_token.sh")"
CR_API="https://agentbase.api.vngcloud.vn/cr/api/v1"
REPO_JSON="$(curl -s "$CR_API/repository" -H "Authorization: Bearer $TOKEN")"
REGISTRY_URL="$(printf '%s' "$REPO_JSON" | jq -r '.registryUrl // empty')"
CRED_JSON="$(curl -s "$CR_API/registry-credential" -H "Authorization: Bearer $TOKEN")"
CR_USER="$(printf '%s' "$CRED_JSON" | jq -r '.username // empty')"
CR_SECRET="$(printf '%s' "$CRED_JSON" | jq -r '.secret // empty')"
if [ -z "$REGISTRY_URL" ] || [ -z "$CR_USER" ] || [ -z "$CR_SECRET" ]; then
  echo "ERROR: could not fetch CR registry/credentials from API."
  echo "  repository resp: $(printf '%s' "$REPO_JSON" | head -c 200)"
  exit 1
fi
AUTH_B64="$(printf '%s:%s' "$CR_USER" "$CR_SECRET" | base64 | tr -d '\n')"
REGISTRY_HOST="${REGISTRY_URL%%/*}"
jq -n --arg full "$REGISTRY_URL" --arg host "$REGISTRY_HOST" --arg auth "$AUTH_B64" \
  '{auths: ({($full): {auth:$auth}} + {($host): {auth:$auth}})}' > "$DOCKER_CONFIG/config.json"
echo "   wrote auth for $REGISTRY_HOST (user: $CR_USER)"

# 2. Build (--pull for fresh base; COPY . . busts cache when any file changed)
echo ">> docker build $IMAGE"
docker build --pull --platform "$PLATFORM" -t "$IMAGE" .

# 2b. Verify the BUILT IMAGE actually contains the latest code (catches stale
# build context / wrong cache). If the marker isn't inside the image, abort.
echo ">> verify built image contains latest code"
if ! docker run --rm --entrypoint sh "$IMAGE" -c 'grep -q _extract_items /app/app/memory.py && grep -q run_data_query /app/app/agent.py'; then
  echo "ERROR: built image does NOT contain the latest code (memory/agent markers missing)."
  echo "       Build likely used stale files. Aborting before push."
  exit 1
fi
echo "   image content OK (latest code baked in)"

# 3. Push
echo ">> docker push $IMAGE"
docker push "$IMAGE"

# 4. Update the runtime (creates a new version; DEFAULT endpoint auto-rolls to it)
echo ">> runtime update"
bash "$S/runtime.sh" update "$RUNTIME_ID" \
  --image "$IMAGE" \
  --flavor "$FLAVOR" \
  --env-file "$ENV_FILE" \
  --from-cr \
  --network-mode PUBLIC \
  --min-replicas 1 --max-replicas 1 --cpu-scale 50 --mem-scale 50

# 5. Status
echo ">> runtime status"
bash "$S/runtime.sh" get "$RUNTIME_ID"

echo ""
echo "Done. Image: $IMAGE"
echo "Console: https://aiplatform.console.vngcloud.vn/agent-runtime?tab=runtime"
echo "If status is ERROR, run: bash debug_deploy.sh  (xem mục 5/6 endpoint events + logs)"
