#!/usr/bin/env bash
# Diagnose a stuck / ERROR AgentBase deployment for this repo.
# Run on your Mac (has network + .greennode.json credentials):
#   bash debug_deploy.sh
set -uo pipefail

cd "$(dirname "$0")"

S="greennode-agentbase-skills/.claude/skills/agentbase/scripts"
RID="runtime-30d2e3d5-b5d2-4d62-bba8-9ded41801c70"
EID="endpoint-9a8cfca7-0890-468a-be06-0d3e1379e5dd"

echo "############################################################"
echo "# AgentBase deploy diagnostics"
echo "# runtime : $RID"
echo "# endpoint: $EID"
echo "############################################################"

echo ""; echo "===== 1) Credentials ====="
bash "$S/check_credentials.sh" iam

echo ""; echo "===== 2) Runtime status (live) ====="
bash "$S/runtime.sh" get "$RID" | jq '{id,name,status,statusReason,updatedAt}' 2>/dev/null \
  || bash "$S/runtime.sh" get "$RID"

echo ""; echo "===== 3) Runtime versions ====="
bash "$S/runtime.sh" versions "$RID" 2>/dev/null | jq '.' 2>/dev/null \
  || bash "$S/runtime.sh" versions "$RID"

echo ""; echo "===== 4) Endpoints (status + replica count + version) ====="
bash "$S/runtime.sh" endpoints list "$RID" | jq '.listData[] | {name,version,status,currentReplicaCount,updatedAt}' 2>/dev/null \
  || bash "$S/runtime.sh" endpoints list "$RID"

echo ""; echo "===== 5) ENDPOINT EVENTS (look here first for startup failures) ====="
echo "# OOM / image pull / probe-failed / scheduling errors appear here before app logs"
bash "$S/runtime.sh" endpoints events "$RID" "$EID" --from 0 --limit 100

echo ""; echo "===== 6) ENDPOINT LOGS (app startup traceback) ====="
bash "$S/runtime.sh" endpoints logs "$RID" "$EID" --from 0 --limit 200

echo ""; echo "===== 7) RUNTIME LOGS (errors only) ====="
bash "$S/runtime.sh" logs "$RID" --from 0 --limit 200 --query "error"

echo ""; echo "===== 8) Current metrics (CPU/RAM — check for OOM) ====="
bash "$S/runtime.sh" endpoints metrics "$RID" "$EID" 2>/dev/null \
  || echo "(metrics unavailable — likely 0 replicas running)"

echo ""
echo "############################################################"
echo "# Done. Paste sections 5/6/7 back to me to pinpoint the cause."
echo "############################################################"
