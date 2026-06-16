import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("agent")

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_INDEX = ROOT_DIR / "frontend" / "index.html"
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/tmp/agent_uploads"))
UPLOAD_INDEX = UPLOAD_DIR / "index.json"
PROMPT_PATH = Path(os.environ.get("SYSTEM_PROMPT_PATH", "prompts/system_prompt.md"))
# ---------------------------------------------------------------------------- #
# [DISABLED] Config cho phần OUTPUT HÌNH % CTR cho từng sản phẩm trên màn hình Home.
# Tạm thời bỏ tính năng này — agent trả lời CTR bằng số liệu (SQL) thay vì ảnh.
# Để bật lại: bỏ comment các dòng dưới, bật lại 2 route /assets, /results trong
# app/routes.py, và bỏ comment khối homepage_context trong app/agent.py.
# ---------------------------------------------------------------------------- #
# RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", "/tmp/agent_results"))
# ASSET_DIR = Path(os.environ.get("ASSET_DIR", "assets"))
# HOMEPAGE_RESULT_IMAGE = ASSET_DIR / "homepage_reference_result.png"
# HOMEPAGE_LAYOUT_PATH = Path(os.environ.get("HOMEPAGE_LAYOUT_PATH", str(ASSET_DIR / "homepage_click_layout.json")))
# HOMEPAGE_RESULT_IMAGE_URL = "/assets/homepage_reference_result.png"
DATA_SOURCE = os.environ.get("DATA_SOURCE", "parquet").strip().lower() or "parquet"
PARQUET_PATH = Path(os.environ.get("PARQUET_PATH", "data/event_log.parquet"))
PAYMENT_PARQUET_PATH = Path(os.environ.get("PAYMENT_PARQUET_PATH", "data/payment.parquet"))
# Where generated result PDFs are written and served from (/results/<file>.pdf).
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", "/tmp/agent_results"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
MAX_FILE_CONTEXT_CHARS = int(os.environ.get("MAX_FILE_CONTEXT_CHARS", "12000"))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    or os.environ.get("SUPABASE_ANON_KEY", "").strip()
)
SUPABASE_TABLE = os.environ.get("SUPABASE_TABLE", "event_log").strip() or "event_log"
SUPABASE_SELECT = os.environ.get("SUPABASE_SELECT", "*").strip() or "*"
SUPABASE_LIMIT = int(os.environ.get("SUPABASE_LIMIT", "10"))

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini").strip()
# Bound each LLM call so a slow/hung upstream can't leave a chat job stuck in
# "inprogess" forever (which made the UI spin until its own poll timeout).
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "60"))
# One retry for transient MaaS timeouts. With thinking disabled, calls return in
# well under a second, so a retry is cheap and rarely needed.
LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "1"))
# Qwen3 "thinking" mode emits huge reasoning and routinely times out (4+ min per
# call). Disable it by default so calls return in <1s. Override to "true" to re-enable.
LLM_ENABLE_THINKING = os.environ.get("LLM_ENABLE_THINKING", "false").strip().lower() in ("1", "true", "yes")
llm = OpenAI(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    timeout=LLM_TIMEOUT,
    max_retries=LLM_MAX_RETRIES,
)

MEMORY_BASE_URL = os.environ.get("MEMORY_BASE_URL", "https://agentbase.api.vngcloud.vn/memory").rstrip("/")
AGENTBASE_MEMORY_ID = os.environ.get("AGENTBASE_MEMORY_ID", "").strip()
MEMORY_STRATEGY_ID = os.environ.get("MEMORY_STRATEGY_ID", "").strip()
MEMORY_ACTOR_ID = os.environ.get("MEMORY_ACTOR_ID", "web-user").strip() or "web-user"

# --- Email agent (separate AgentBase runtime that sends report emails) ------
# Local default points at the email agent running on port 8090. In production,
# set this to the email agent's AgentBase endpoint URL.
EMAIL_AGENT_URL = os.environ.get("EMAIL_AGENT_URL", "http://localhost:8090").strip().rstrip("/")
# No hard-coded default recipient — the user must always supply the email(s).
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "").strip()
EMAIL_AGENT_TIMEOUT = int(os.environ.get("EMAIL_AGENT_TIMEOUT", "120"))
# Optional bearer token when calling a deployed (PUBLIC) email agent endpoint.
EMAIL_AGENT_TOKEN = os.environ.get("EMAIL_AGENT_TOKEN", "").strip()

# IAM token endpoint. Default matches the AgentBase deploy scripts / endpoints whitelist
# (iam.api.vngcloud.vn). Override via env if your tenant uses a different host.
IAM_TOKEN_URL = os.environ.get(
    "IAM_TOKEN_URL", "https://iam.api.vngcloud.vn/accounts-api/v2/auth/token"
).strip()
# How many long-term facts to recall per turn, and minimum similarity score.
LTM_RECALL_LIMIT = int(os.environ.get("LTM_RECALL_LIMIT", "5"))
LTM_SCORE_THRESHOLD = float(os.environ.get("LTM_SCORE_THRESHOLD", "0.3"))

JOBS: dict[str, dict] = {}
JOBS_LOCK = Lock()
JOB_EXECUTOR = ThreadPoolExecutor(max_workers=int(os.environ.get("JOB_WORKERS", "2")))
TOKEN_CACHE: dict[str, object] = {"access_token": None, "expires_at": 0}
