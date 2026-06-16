"""Email transport layer.

Two transports, selected by EMAIL_TRANSPORT:
  - "mock" (default): logs the full email, sends nothing (for local flow testing).
  - "smtp": sends via a real SMTP server using the SMTP_* env vars.

Supports an HTML alternative body, a single file attachment (base64), and
multiple recipients in one send.
"""

import base64
import re
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import (
    EMAIL_FROM,
    EMAIL_TRANSPORT,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USE_TLS,
    SMTP_USER,
    logger,
)


def _normalize_recipients(recipients) -> list[str]:
    """Accept a list, or a comma/semicolon/whitespace-separated string → clean list."""
    if isinstance(recipients, (list, tuple)):
        items = list(recipients)
    else:
        items = re.split(r"[,;\s]+", str(recipients or ""))
    seen, out = set(), []
    for r in items:
        r = (r or "").strip()
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _build_message(recipients: list[str], subject: str, body: str,
                   html_body: str | None, attachment: dict | None) -> MIMEMultipart:
    sender = EMAIL_FROM or SMTP_USER
    root = MIMEMultipart("mixed")
    root["From"] = sender
    root["To"] = ", ".join(recipients)
    root["Subject"] = subject

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(body or "", "plain", "utf-8"))
    if html_body:
        alt.attach(MIMEText(html_body, "html", "utf-8"))
    root.attach(alt)

    if attachment and attachment.get("content_base64"):
        try:
            data = base64.b64decode(attachment["content_base64"])
            part = MIMEApplication(data, _subtype=attachment.get("subtype", "pdf"))
            part.add_header(
                "Content-Disposition", "attachment",
                filename=attachment.get("filename", "report.pdf"),
            )
            root.attach(part)
        except Exception:
            logger.exception("failed to attach file; sending without attachment")
    return root


def _send_mock(recipients, subject, body, html_body, attachment) -> dict:
    banner = "=" * 64
    att = attachment.get("filename") if attachment else "(none)"
    logger.info(
        "\n%s\n[MOCK EMAIL — NOT SENT]\nFrom:    %s\nTo:      %s\nSubject: %s\nAttach:  %s\nHTML:    %s\n%s\n%s\n%s",
        banner, EMAIL_FROM or "(unset)", ", ".join(recipients), subject, att,
        bool(html_body), banner, body, banner,
    )
    return {"status": "sent", "transport": "mock", "recipients": recipients,
            "subject": subject, "delivered": False,
            "note": "Mock transport: email logged, not actually delivered."}


def _send_smtp(recipients, subject, body, html_body, attachment) -> dict:
    if not SMTP_HOST:
        raise RuntimeError("EMAIL_TRANSPORT=smtp but SMTP_HOST is not configured.")
    sender = EMAIL_FROM or SMTP_USER
    message = _build_message(recipients, subject, body, html_body, attachment)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.ehlo()
        if SMTP_USE_TLS:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(sender, recipients, message.as_string())
    logger.info("SMTP email sent to %s (subject=%s)", ", ".join(recipients), subject)
    return {"status": "sent", "transport": "smtp", "recipients": recipients,
            "subject": subject, "delivered": True}


def send_email(recipients, subject: str, body: str,
               html_body: str | None = None, attachment: dict | None = None) -> dict:
    """Dispatch to the configured transport. ``recipients`` may be a list or string."""
    recipient_list = _normalize_recipients(recipients)
    if not recipient_list:
        return {"status": "error", "message": "No valid recipient."}
    if (EMAIL_TRANSPORT or "mock").strip().lower() == "smtp":
        return _send_smtp(recipient_list, subject, body, html_body, attachment)
    return _send_mock(recipient_list, subject, body, html_body, attachment)
