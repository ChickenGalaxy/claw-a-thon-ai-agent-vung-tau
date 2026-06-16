"""Email transport layer.

Two transports, selected by EMAIL_TRANSPORT:
  - "mock" (default): does NOT send anything; logs the full email to stdout/log.
    Used for local testing of the end-to-end flow before real SMTP is wired in.
  - "smtp": sends via a real SMTP server using the SMTP_* env vars.

Switching from mock to real sending later is just an env change — no code change.
"""

import os
import smtplib
import ssl
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


def _send_mock(recipient: str, subject: str, body: str) -> dict:
    """Pretend to send — just log the whole email so we can verify the flow."""
    banner = "=" * 64
    logger.info(
        "\n%s\n[MOCK EMAIL — NOT ACTUALLY SENT]\nFrom:    %s\nTo:      %s\nSubject: %s\n%s\n%s\n%s",
        banner, EMAIL_FROM or "(unset)", recipient, subject, banner, body, banner,
    )
    return {
        "status": "sent",
        "transport": "mock",
        "recipient": recipient,
        "subject": subject,
        "delivered": False,
        "note": "Mock transport: email logged, not actually delivered.",
    }


def _send_smtp(recipient: str, subject: str, body: str) -> dict:
    """Send a real email via SMTP."""
    if not SMTP_HOST:
        raise RuntimeError("EMAIL_TRANSPORT=smtp but SMTP_HOST is not configured.")
    sender = EMAIL_FROM or SMTP_USER
    message = MIMEMultipart()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        server.ehlo()
        if SMTP_USE_TLS:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if SMTP_USER and SMTP_PASSWORD:
            server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(sender, [recipient], message.as_string())

    logger.info("SMTP email sent to %s (subject=%s)", recipient, subject)
    return {
        "status": "sent",
        "transport": "smtp",
        "recipient": recipient,
        "subject": subject,
        "delivered": True,
    }


def send_email(recipient: str, subject: str, body: str) -> dict:
    """Dispatch to the configured transport. Returns a JSON-serializable status dict."""
    transport = (EMAIL_TRANSPORT or "mock").strip().lower()
    if transport == "smtp":
        return _send_smtp(recipient, subject, body)
    return _send_mock(recipient, subject, body)
