"""Configuration for the email agent runtime.

All values come from environment variables (loaded from .env when present).
Kept tiny on purpose — this agent only composes and sends email.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] %(levelname)s email-agent %(message)s",
)
logger = logging.getLogger("email-agent")

# Local dev port (AgentBase runtime always uses 8080 in production via uvicorn).
PORT = int(os.environ.get("PORT", "8090"))

# Where to deliver reports by default if the caller doesn't specify a recipient.
DEFAULT_RECIPIENT = os.environ.get("DEFAULT_RECIPIENT", "trucnt7@vng.com.vn").strip()

# --- Email transport --------------------------------------------------------
# "mock" = log only (default, for local testing). "smtp" = real send.
EMAIL_TRANSPORT = os.environ.get("EMAIL_TRANSPORT", "mock").strip().lower()
EMAIL_FROM = os.environ.get("EMAIL_FROM", "zalopay-analytics-agent@vng.com.vn").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").strip().lower() in ("1", "true", "yes")

# --- LLM (used to compose a nice email body) --------------------------------
# Per requirement: this agent uses model openai/gpt-oss-20b.
EMAIL_USE_LLM = os.environ.get("EMAIL_USE_LLM", "true").strip().lower() in ("1", "true", "yes")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-20b").strip()
