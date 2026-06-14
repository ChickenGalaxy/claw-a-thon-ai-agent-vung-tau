import json
import os
import time
from pathlib import Path

import requests

from .config import AGENTBASE_MEMORY_ID, MEMORY_BASE_URL, TOKEN_CACHE


def load_local_greennode_credentials() -> tuple[str, str]:
    client_id = os.environ.get("GREENNODE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GREENNODE_CLIENT_SECRET", "").strip()
    config_path = Path(".greennode.json")
    if (not client_id or not client_secret) and config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            client_id = client_id or data.get("client_id", "")
            client_secret = client_secret or data.get("client_secret", "")
        except Exception:
            pass
    return client_id, client_secret


def get_agentbase_token() -> str:
    now = int(time.time())
    cached = TOKEN_CACHE.get("access_token")
    expires_at = int(TOKEN_CACHE.get("expires_at") or 0)
    if cached and now < expires_at - 60:
        return str(cached)
    client_id, client_secret = load_local_greennode_credentials()
    if not client_id or not client_secret:
        raise RuntimeError("AgentBase IAM credentials are not available")
    response = requests.post(
        "https://iamapis.vngcloud.vn/accounts-api/v2/auth/token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Could not fetch AgentBase IAM token")
    TOKEN_CACHE["access_token"] = token
    TOKEN_CACHE["expires_at"] = now + int(data.get("expires_in", 1800))
    return token


def memory_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_agentbase_token()}",
        "Content-Type": "application/json",
    }


def memory_enabled() -> bool:
    return bool(AGENTBASE_MEMORY_ID)


def create_memory_event(actor_id: str, session_id: str, role: str, message: str) -> None:
    if not memory_enabled() or not actor_id or not session_id or not message:
        return
    payload = {"payload": {"type": "conversational", "role": role, "message": message[:100000]}}
    url = f"{MEMORY_BASE_URL}/memories/{AGENTBASE_MEMORY_ID}/actors/{actor_id}/sessions/{session_id}/events"
    response = requests.post(url, headers=memory_headers(), json=payload, timeout=20)
    response.raise_for_status()


def list_memory_events(actor_id: str, session_id: str) -> list[dict[str, str]]:
    if not memory_enabled() or not actor_id or not session_id:
        return []
    url = f"{MEMORY_BASE_URL}/memories/{AGENTBASE_MEMORY_ID}/actors/{actor_id}/sessions/{session_id}/events"
    response = requests.get(url, headers=memory_headers(), params={"page": 1, "size": 100}, timeout=20)
    response.raise_for_status()
    data = response.json()
    items = data.get("listData") or data.get("items") or data.get("data") or []
    events = []
    for item in reversed(items):
        payload = item.get("payload") or {}
        role = payload.get("role") or item.get("role") or "assistant"
        message = payload.get("message") or payload.get("content") or item.get("message") or item.get("content") or ""
        if message:
            events.append({"role": role, "message": message})
    return events


def recent_session_memory(actor_id: str, session_id: str, limit: int = 20) -> list[dict[str, str]]:
    try:
        events = list_memory_events(actor_id, session_id)
    except Exception:
        return []
    return events[-limit:]
