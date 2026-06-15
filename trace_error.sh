#!/usr/bin/env bash
# Diagnose the deployed AgentBase runtime without requiring jq.
#
# Usage:
#   bash trace_error.sh
#   bash trace_error.sh "câu hỏi test của bạn"
set -euo pipefail
cd "$(dirname "$0")"

MSG="${1:-tỷ lệ click Điện thoại trên trang chủ tháng 4/2026}"
LIMIT="${LIMIT:-500}"

venv/bin/python -u - "$MSG" "$LIMIT" <<'PY'
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RUNTIME_ID = "runtime-30d2e3d5-b5d2-4d62-bba8-9ded41801c70"
ENDPOINT_ID = "endpoint-9a8cfca7-0890-468a-be06-0d3e1379e5dd"
BASE_API = "https://agentbase.api.vngcloud.vn/runtime/agent-runtimes"
PUBLIC_URL = "https://endpoint-9a8cfca7-0890-468a-be06-0d3e1379e5dd.agentbase-runtime.aiplatform.vngcloud.vn"
MESSAGE = sys.argv[1]
LIMIT = int(sys.argv[2])


def refresh_token() -> str:
    creds = json.loads(Path(".greennode.json").read_text(encoding="utf-8"))
    client_id = creds.get("client_id", "")
    client_secret = creds.get("client_secret", "")
    if not client_id or not client_secret:
        raise RuntimeError(".greennode.json is missing client_id/client_secret")
    request = urllib.request.Request("https://iam.api.vngcloud.vn/accounts-api/v2/auth/token", method="POST")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request.add_header("Authorization", f"Basic {basic}")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request, data=b"grant_type=client_credentials", timeout=30) as response:
        token = json.loads(response.read().decode())["access_token"]
    Path(".agentbase").mkdir(exist_ok=True)
    Path(".agentbase/token_cache").write_text(token, encoding="utf-8")
    return token


TOKEN = refresh_token()


def api(method: str, url: str, body=None, timeout: int = 30):
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode(errors="replace")
            return response.status, json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")
    except Exception as error:
        return None, str(error)


def public(method: str, path: str, body=None, timeout: int = 180):
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(PUBLIC_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode(errors="replace")
            try:
                return response.status, json.loads(text)
            except Exception:
                return response.status, text
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")
    except Exception as error:
        return None, str(error)


def print_json(title: str, value) -> None:
    print(f"\n===== {title} =====")
    if isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2)[:12000])
    else:
        print(str(value)[:12000])


print("############################################################")
print(f"# Trace error | runtime={RUNTIME_ID}")
print("############################################################")

runtime_status, runtime = api("GET", f"{BASE_API}/{RUNTIME_ID}")
print_json("1) Runtime status", runtime)

endpoint_status, endpoints = api("GET", f"{BASE_API}/{RUNTIME_ID}/endpoints?page=1&size=100")
print_json("2) Endpoint status", endpoints)

health_code, health_body = public("GET", "/health", timeout=20)
print_json("3) Health NOW", {"http_status": health_code, "body": health_body})

print_json("4) Test /invocations", {"message": MESSAGE, "note": "timeout is 180s because analytics questions call LLM + DuckDB"})
invoke_code, invoke_body = public("POST", "/invocations", {"message": MESSAGE, "actor_id": "web-user"}, timeout=180)
print_json("4a) /invocations response", {"http_status": invoke_code, "body": invoke_body})

chat_code, chat_body = public("POST", "/chat", {"message": MESSAGE, "actor_id": "web-user"}, timeout=30)
print_json("4b) /chat start", {"http_status": chat_code, "body": chat_body})
job_id = chat_body.get("job_id") if isinstance(chat_body, dict) else None
if job_id:
    final = None
    for index in range(60):
        job_code, job_body = public("GET", f"/jobs/{job_id}", timeout=30)
        status = job_body.get("status") if isinstance(job_body, dict) else None
        print(f"job poll {index + 1}: http={job_code} status={status}")
        if status in {"completed", "failed", "error"}:
            final = job_body
            break
        time.sleep(2)
    print_json("4c) /chat final", final or {"status": "timeout", "job_id": job_id})

events_status, events = api("GET", f"{BASE_API}/{RUNTIME_ID}/endpoints/{ENDPOINT_ID}/events")
print_json("5) Endpoint events", events)

logs_status, logs = api("POST", f"{BASE_API}/{RUNTIME_ID}/endpoints/{ENDPOINT_ID}/logs", {"limit": LIMIT})
print("\n===== 6) Filtered endpoint logs =====")
print("# Excludes access-log noise for /health, /, /jobs, /chat unless it contains errors.")
if isinstance(logs, dict):
    noisy = ("GET /health", "GET / HTTP", "GET /jobs", "GET /sessions", "POST /chat")
    interesting = ("traceback", "error", "exception", "failed", "invalid json", "timeout", "oom", "killed")
    rows = logs.get("logs", [])
    printed = 0
    for row in rows:
        content = row.get("content", "")
        lower = content.lower()
        if any(token in content for token in noisy) and not any(token in lower for token in interesting):
            continue
        print(f"{row.get('timestamp')}  {content}")
        printed += 1
        if printed >= 160:
            break
else:
    print(logs)

print("\n############################################################")
print("# Done.")
print("############################################################")
PY
