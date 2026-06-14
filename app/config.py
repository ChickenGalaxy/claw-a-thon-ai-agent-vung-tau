import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_INDEX = ROOT_DIR / "frontend" / "index.html"
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/tmp/agent_uploads"))
UPLOAD_INDEX = UPLOAD_DIR / "index.json"
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", "/tmp/agent_results"))
PROMPT_PATH = Path(os.environ.get("SYSTEM_PROMPT_PATH", "prompts/system_prompt.md"))
ASSET_DIR = Path(os.environ.get("ASSET_DIR", "assets"))
HOMEPAGE_RESULT_IMAGE = ASSET_DIR / "homepage_reference_result.png"
HOMEPAGE_LAYOUT_PATH = Path(os.environ.get("HOMEPAGE_LAYOUT_PATH", str(ASSET_DIR / "homepage_click_layout.json")))
HOMEPAGE_RESULT_IMAGE_URL = "/assets/homepage_reference_result.png"
DATA_SOURCE = os.environ.get("DATA_SOURCE", "parquet").strip().lower() or "parquet"
PARQUET_PATH = Path(os.environ.get("PARQUET_PATH", "data/event_log.parquet"))
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
llm = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

MEMORY_BASE_URL = os.environ.get("MEMORY_BASE_URL", "https://agentbase.api.vngcloud.vn/memory").rstrip("/")
AGENTBASE_MEMORY_ID = os.environ.get("AGENTBASE_MEMORY_ID", "").strip()
MEMORY_STRATEGY_ID = os.environ.get("MEMORY_STRATEGY_ID", "").strip()
MEMORY_ACTOR_ID = os.environ.get("MEMORY_ACTOR_ID", "web-user").strip() or "web-user"

JOBS: dict[str, dict] = {}
JOBS_LOCK = Lock()
JOB_EXECUTOR = ThreadPoolExecutor(max_workers=int(os.environ.get("JOB_WORKERS", "2")))
TOKEN_CACHE: dict[str, object] = {"access_token": None, "expires_at": 0}
