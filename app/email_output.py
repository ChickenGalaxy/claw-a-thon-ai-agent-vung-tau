"""Generic "email this result to me" flow.

Lets the user email the most recent agent answer to any address. If the user
asks to email a result but doesn't give a recipient, the caller asks back and
sends on their reply (see the pending-email mechanism in ``daily_new_user``).

This is separate from the daily-new-user report flow (which computes fresh data);
here we simply forward an already-produced answer as the email body.
"""

import base64
import re
import unicodedata
from datetime import datetime

from .config import logger
from .report_render import answer_title, build_email_html, markdown_to_pdf_bytes


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def wants_email_output(message: str) -> bool:
    """True when the user asks to send/email a result (generic, any output).

    Conservative on purpose: requires a send-verb next to 'mail'/'email', or an
    explicit 'qua mail/email' phrase, so normal data questions that merely mention
    email don't trigger it.
    """
    norm = _strip_accents((message or "").lower())
    if not (("mail" in norm) or ("email" in norm)):
        return False
    patterns = (
        r"\bgui\b.*\b(mail|email)\b",        # gửi ... mail/email
        r"\b(mail|email)\b.*\bcho\b",         # mail/email cho ...
        r"\bqua\s+(mail|email)\b",            # qua mail / qua email
        r"\bsend\b.*\b(mail|email)\b",        # send ... email
        r"\b(mail|email)\s+(ket qua|result|cai nay|bao cao|output)\b",
        r"\bgui\s+(ket qua|result|cai nay|bao cao|output)\b",
    )
    return any(re.search(p, norm) for p in patterns)


def last_assistant_answer(memory_context: list) -> str | None:
    """Return the most recent assistant message text from session memory, if any."""
    for event in reversed(memory_context or []):
        if event.get("role") == "assistant":
            text = (event.get("message") or "").strip()
            if text:
                return text
    return None


def _subject_from_body(body: str) -> str:
    return f"[ZaloPay Analytics] {answer_title(body)}"


def _safe_pdf_name(title: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", _strip_accents(title)).strip("-._").lower()
    return (base[:50] or "ket-qua") + ".pdf"


def handle_email_output(body: str, recipient, subject: str | None = None, progress=None) -> dict:
    """Email a result (HTML-formatted body + PDF attachment) to one or more recipients.

    ``recipient`` may be a single address or a list of addresses.
    """
    recipients = recipient if isinstance(recipient, list) else [recipient]
    recipients = [r.strip() for r in recipients if r and r.strip()]
    subject = (subject or _subject_from_body(body)).strip()
    title = answer_title(body)

    if progress:
        progress(f"Đang định dạng email (HTML + PDF) gửi tới {', '.join(recipients)}.")

    html_body = build_email_html(body, title=title)
    attachment = None
    try:
        pdf_bytes = markdown_to_pdf_bytes(body, title=title)
        attachment = {
            "filename": _safe_pdf_name(title),
            "content_base64": base64.b64encode(pdf_bytes).decode("ascii"),
            "subtype": "pdf",
        }
    except Exception:
        logger.exception("handle_email_output: PDF render failed; sending without attachment")

    email_result = _send_direct(subject, body, recipients, html_body=html_body, attachment=attachment)
    email_ok = email_result.get("status") == "sent"
    who = ", ".join(recipients)
    if email_ok:
        transport = email_result.get("transport", "?")
        att_note = " (kèm file PDF)" if attachment else ""
        note = (
            f"✅ Đã gửi kết quả tới {who}{att_note}"
            + (" (chế độ MOCK — email được ghi log, chưa gửi thật)." if transport == "mock" else ".")
        )
    else:
        note = f"⚠️ Không gửi được email: {email_result.get('message') or email_result.get('detail')}"

    return {
        "status": "success",
        "response": note,
        "intent": "email_output",
        "email": email_result,
        "recipients": recipients,
        "timestamp": datetime.now().isoformat(),
    }


def _send_direct(subject: str, body: str, recipients: list, html_body=None, attachment=None) -> dict:
    """Call the email agent with subject/body/html/attachment at the payload top level."""
    import requests

    from .config import EMAIL_AGENT_TIMEOUT, EMAIL_AGENT_TOKEN, EMAIL_AGENT_URL

    url = f"{EMAIL_AGENT_URL}/invocations"
    headers = {"Content-Type": "application/json"}
    if EMAIL_AGENT_TOKEN:
        headers["Authorization"] = f"Bearer {EMAIL_AGENT_TOKEN}"
    payload = {"recipients": recipients, "subject": subject, "body": body}
    if html_body:
        payload["html_body"] = html_body
    if attachment:
        payload["attachment"] = attachment
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=EMAIL_AGENT_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as error:
        logger.warning("email_output direct send failed: %s", type(error).__name__)
        return {"status": "error", "message": f"Không gọi được email agent tại {EMAIL_AGENT_URL}.", "detail": type(error).__name__}
