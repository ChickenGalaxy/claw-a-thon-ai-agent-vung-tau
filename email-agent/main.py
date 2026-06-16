"""ZaloPay Email Agent — a small AgentBase runtime whose only job is to send email.

Invoked by the main analytics agent when a user asks to email a
"daily new user trong tháng" report. Receives the computed report (or a ready
subject/body), composes a clean email with openai/gpt-oss-20b, and sends it
(mock-logged by default; real SMTP when EMAIL_TRANSPORT=smtp).

Entrypoint payload (POST /invocations), all keys optional except one of
{report | (subject & body)}:
  {
    "recipient": "trucnt7@vng.com.vn",
    "report": {"month": 5, "year": 2026, "rows": [{"reg_date": "260501", "new_users": 123}, ...],
               "total_new_users": 4567},
    "subject": "...",   # if provided with body, skip LLM compose
    "body": "..."
  }
"""

from greennode_agentbase import GreenNodeAgentBaseApp, PingStatus, RequestContext

from composer import compose_email
from config import DEFAULT_RECIPIENT, PORT, logger
from emailer import send_email

app = GreenNodeAgentBaseApp()


def handle_email(payload: dict) -> dict:
    try:
        # Accept "recipients" (list/str) or legacy single "recipient".
        recipients = payload.get("recipients") or payload.get("recipient") or DEFAULT_RECIPIENT
        subject = payload.get("subject")
        body = payload.get("body")
        html_body = payload.get("html_body")
        attachment = payload.get("attachment")  # {"filename","content_base64","subtype"}

        if not (subject and body):
            report = payload.get("report") or {}
            if not isinstance(report, dict):
                report = {}
            subject, body = compose_email(report)

        result = send_email(
            recipients, str(subject), str(body),
            html_body=html_body, attachment=attachment,
        )
        result["body_preview"] = str(body)[:280]
        result["subject"] = str(subject)
        result["has_html"] = bool(html_body)
        result["has_attachment"] = bool(attachment and attachment.get("content_base64"))
        return result
    except Exception as error:
        logger.exception("email agent failed")
        return {
            "status": "error",
            "message": "Email agent failed to send email.",
            "detail": type(error).__name__,
        }


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    return handle_email(payload or {})


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


if __name__ == "__main__":
    logger.info("Starting email agent on port %d", PORT)
    app.run(port=PORT, host="0.0.0.0")
