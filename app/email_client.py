"""Client for calling the separate email agent runtime over HTTP.

The email agent exposes the AgentBase SDK entrypoint at POST /invocations, which
takes the raw JSON payload and returns the handler's result dict directly.
"""

import requests

from .config import EMAIL_AGENT_TIMEOUT, EMAIL_AGENT_TOKEN, EMAIL_AGENT_URL, logger


def send_report_email(report: dict, recipient: str | None = None) -> dict:
    """Ask the email agent to compose and send a daily-new-user report email.

    Returns the email agent's status dict, or an error dict if the call fails.
    """
    payload: dict = {"report": report}
    if recipient:
        payload["recipient"] = recipient

    url = f"{EMAIL_AGENT_URL}/invocations"
    headers = {"Content-Type": "application/json"}
    if EMAIL_AGENT_TOKEN:
        headers["Authorization"] = f"Bearer {EMAIL_AGENT_TOKEN}"

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=EMAIL_AGENT_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        logger.info("email agent responded: status=%s transport=%s", data.get("status"), data.get("transport"))
        return data
    except requests.exceptions.RequestException as error:
        logger.warning("email agent call failed: %s", type(error).__name__)
        return {
            "status": "error",
            "message": f"Không gọi được email agent tại {EMAIL_AGENT_URL}.",
            "detail": type(error).__name__,
        }
