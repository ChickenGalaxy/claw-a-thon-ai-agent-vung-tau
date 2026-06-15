import json
import os
import time
from pathlib import Path

import requests

from .config import (
    AGENTBASE_MEMORY_ID,
    IAM_TOKEN_URL,
    LTM_RECALL_LIMIT,
    LTM_SCORE_THRESHOLD,
    MEMORY_BASE_URL,
    MEMORY_STRATEGY_ID,
    TOKEN_CACHE,
    logger,
)


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
            logger.exception("Failed to read .greennode.json")
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
        IAM_TOKEN_URL,
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


# --------------------------------------------------------------------------- #
# Short-term memory: conversation events (scoped to one actor + one session)
# --------------------------------------------------------------------------- #


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
    items = _extract_items(response.json())
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
        logger.exception("recent_session_memory failed (actor=%s session=%s)", actor_id, session_id)
        return []
    return events[-limit:]


# --------------------------------------------------------------------------- #
# Long-term memory: semantic facts (scoped to one actor, persists ACROSS sessions)
# --------------------------------------------------------------------------- #


def long_term_enabled() -> bool:
    """Long-term memory needs both a memory store and a configured strategy."""
    return bool(AGENTBASE_MEMORY_ID and MEMORY_STRATEGY_ID)


def ltm_namespace(actor_id: str) -> str:
    """Records are partitioned per actor so each user has their own long-term memory."""
    return f"/strategies/{MEMORY_STRATEGY_ID}/actors/{actor_id}"


def _extract_items(data) -> list:
    """Normalize a Memory API response into a list of items.

    Some endpoints return a bare JSON array (e.g. memory-records:search),
    others wrap items in listData/items/data/memoryRecords/records.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("listData", "items", "data", "memoryRecords", "records", "content"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def _record_text(record) -> str:
    if not isinstance(record, dict):
        return str(record)
    return (
        record.get("memory")
        or record.get("content")
        or record.get("text")
        or record.get("fact")
        or ""
    )


def recall_long_term(actor_id: str, query: str, limit: int | None = None) -> list[str]:
    """Semantic search of this actor's long-term facts. Returns plain fact strings.

    Cross-session: facts learned in any past session for the same actor are recalled.
    Best-effort — never raises; logs and returns [] on failure.
    """
    if not long_term_enabled() or not actor_id or not query:
        return []
    try:
        url = f"{MEMORY_BASE_URL}/memories/{AGENTBASE_MEMORY_ID}/memory-records:search"
        body: dict = {"query": query, "limit": int(limit or LTM_RECALL_LIMIT)}
        if LTM_SCORE_THRESHOLD > 0:
            body["scoreThreshold"] = LTM_SCORE_THRESHOLD
        response = requests.post(
            url,
            headers=memory_headers(),
            params={"namespace": ltm_namespace(actor_id)},
            json=body,
            timeout=20,
        )
        response.raise_for_status()
        items = _extract_items(response.json())
        facts = [text for item in items if (text := _record_text(item))]
        logger.info("recall_long_term: %d fact(s) for actor=%s", len(facts), actor_id)
        return facts
    except Exception:
        logger.exception("recall_long_term failed (actor=%s)", actor_id)
        return []


def remember_long_term(actor_id: str, facts: list[str]) -> bool:
    """Insert explicit facts directly into this actor's long-term memory.

    Best-effort — never raises; logs and returns False on failure.
    """
    clean = [fact.strip() for fact in facts if fact and fact.strip()]
    if not long_term_enabled() or not actor_id or not clean:
        return False
    try:
        url = f"{MEMORY_BASE_URL}/memories/{AGENTBASE_MEMORY_ID}/memory-records:insert-directly"
        response = requests.post(
            url,
            headers=memory_headers(),
            params={"namespace": ltm_namespace(actor_id)},
            json={"memoryRecords": clean},
            timeout=20,
        )
        response.raise_for_status()
        logger.info("remember_long_term: stored %d fact(s) for actor=%s", len(clean), actor_id)
        return True
    except Exception:
        logger.exception("remember_long_term failed (actor=%s)", actor_id)
        return False


def generate_long_term_from_session(actor_id: str, session_id: str) -> bool:
    """Ask the platform to extract long-term facts from this session's events
    using the configured strategy. Best-effort — never raises.
    """
    if not long_term_enabled() or not actor_id or not session_id:
        return False
    try:
        url = f"{MEMORY_BASE_URL}/memories/{AGENTBASE_MEMORY_ID}/memory-records:generate-from-session"
        response = requests.post(
            url,
            headers=memory_headers(),
            params={
                "actorId": actor_id,
                "sessionId": session_id,
                "longTermMemoryStrategyId": MEMORY_STRATEGY_ID,
            },
            timeout=30,
        )
        response.raise_for_status()
        logger.info("generate_long_term_from_session ok (actor=%s session=%s)", actor_id, session_id)
        return True
    except Exception:
        logger.exception("generate_long_term_from_session failed (actor=%s session=%s)", actor_id, session_id)
        return False
