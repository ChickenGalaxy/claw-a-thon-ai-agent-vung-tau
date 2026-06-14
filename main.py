import csv
import json
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

import psycopg
import pyarrow.compute as pc
import pyarrow.dataset as pyarrow_dataset
import pyarrow.parquet as pq
import requests
from dotenv import load_dotenv
from greennode_agentbase import GreenNodeAgentBaseApp, PingStatus, RequestContext
from openai import OpenAI
from psycopg import sql
from pypdf import PdfReader
from starlette.responses import FileResponse, HTMLResponse, JSONResponse

load_dotenv()

app = GreenNodeAgentBaseApp()

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/tmp/agent_uploads"))
UPLOAD_INDEX = UPLOAD_DIR / "index.json"
PROMPT_PATH = Path(os.environ.get("SYSTEM_PROMPT_PATH", "prompts/system_prompt.md"))
ASSET_DIR = Path(os.environ.get("ASSET_DIR", "assets"))
HOMEPAGE_RESULT_IMAGE = ASSET_DIR / "homepage_reference_result.png"
HOMEPAGE_RESULT_IMAGE_URL = "/assets/homepage_reference_result.png"
DATA_SOURCE = os.environ.get("DATA_SOURCE", "parquet").strip().lower() or "parquet"
PARQUET_PATH = Path(os.environ.get("PARQUET_PATH", "data/event_log.parquet"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(15 * 1024 * 1024)))
MAX_FILE_CONTEXT_CHARS = int(os.environ.get("MAX_FILE_CONTEXT_CHARS", "12000"))
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = Lock()
JOB_EXECUTOR = ThreadPoolExecutor(max_workers=int(os.environ.get("JOB_WORKERS", "2")))

HOME_PAGE = """
<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Ai agent analytics data product home</title>
  <style>
    :root { --bg:#0b0f19; --panel:#111827; --soft:#151d2e; --border:#253044; --text:#e5e7eb; --muted:#8b96aa; --accent:#10a37f; --accent-soft:rgba(16,163,127,.16); --danger:#fb7185; }
    * { box-sizing: border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--text); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    .shell { display:grid; grid-template-columns:280px minmax(0,1fr); min-height:100vh; }
    aside { border-right:1px solid var(--border); background:#080c14; padding:16px; display:grid; grid-template-rows:auto auto minmax(0,1fr) auto; gap:14px; }
    .brand { font-weight:760; line-height:1.25; }
    .panel { border:1px solid var(--border); background:var(--panel); border-radius:16px; padding:12px; }
    button { border:0; border-radius:12px; padding:10px 12px; color:#06130f; background:var(--accent); font-weight:760; cursor:pointer; }
    button.secondary { color:var(--text); background:var(--soft); border:1px solid var(--border); }
    button:disabled { opacity:.55; cursor:wait; }
    .muted { color:var(--muted); font-size:12px; line-height:1.45; }
    .section-title { color:var(--muted); font-size:11px; font-weight:800; letter-spacing:.09em; text-transform:uppercase; margin:6px 0; }
    #sessions { display:grid; gap:8px; overflow:auto; }
    .session-item, .file-card { border:1px solid var(--border); background:var(--panel); border-radius:13px; padding:10px; cursor:pointer; }
    .session-item.active { border-color:rgba(16,163,127,.7); background:var(--accent-soft); }
    .session-row { display:flex; align-items:flex-start; justify-content:space-between; gap:8px; }
    .session-meta { min-width:0; flex:1; }
    .session-actions { display:flex; gap:6px; opacity:.7; }
    .session-item:hover .session-actions { opacity:1; }
    .icon-button { border:1px solid var(--border); border-radius:9px; padding:5px 7px; background:var(--soft); color:var(--muted); font-size:11px; line-height:1; }
    .icon-button:hover { color:var(--text); border-color:rgba(16,163,127,.55); }
    .icon-button.danger:hover { color:var(--danger); border-color:rgba(251,113,133,.6); }
    .session-title, .file-name { font-weight:680; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .session-title-input { width:100%; border:1px solid var(--border); border-radius:10px; padding:7px 9px; background:var(--soft); color:var(--text); font:inherit; font-weight:680; }
    input[type=file] { width:100%; color:var(--muted); font-size:12px; }
    main { display:grid; grid-template-rows:auto 1fr auto; min-width:0; max-height:100vh; }
    header { padding:16px 24px; border-bottom:1px solid var(--border); background:rgba(11,15,25,.9); }
    h1 { margin:0; font-size:17px; }
    #status { margin-top:4px; color:var(--muted); font-size:13px; }
    #chat { overflow:auto; padding:26px; display:flex; flex-direction:column; gap:14px; }
    .message { max-width:860px; padding:15px 17px; border:1px solid var(--border); border-radius:18px; background:var(--panel); line-height:1.58; white-space:pre-wrap; }
    .message img { display:block; max-width:min(100%,520px); height:auto; margin-top:12px; border-radius:16px; border:1px solid var(--border); background:#fff; }
    .user { align-self:flex-end; background:var(--accent-soft); border-color:rgba(16,163,127,.36); }
    .assistant { align-self:flex-start; }
    .error { color:var(--danger); }
    footer { padding:16px 24px 22px; border-top:1px solid var(--border); background:rgba(11,15,25,.94); }
    .composer { border:1px solid var(--border); border-radius:16px; background:var(--panel); padding:12px; display:grid; gap:10px; }
    textarea { min-height:76px; resize:vertical; width:100%; border:0; outline:0; color:var(--text); background:transparent; font:inherit; }
    .composer-actions { display:flex; align-items:center; justify-content:space-between; gap:12px; }
    @media (max-width:860px) { .shell{grid-template-columns:1fr} aside{border-right:0;border-bottom:1px solid var(--border)} main{max-height:none} }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand">Ai agent analytics data product home</div>
      <button id="new-session">+ New chat</button>
      <div>
        <div class="section-title">Sessions</div>
        <div id="sessions"></div>
      </div>
      <div>
        <div class="section-title">Files</div>
        <div class="panel">
          <input id="file-input" type="file" multiple accept=".csv,.pdf,.txt,.json,.md,text/*,application/pdf" />
        </div>
      </div>
    </aside>
    <main>
      <header>
        <h1 id="chat-title">Ai agent analytics data product home</h1>
        <div id="status">ready</div>
      </header>
      <section id="chat"></section>
      <footer>
        <form id="composer" class="composer">
          <textarea id="message" placeholder="Hỏi agent phân tích dữ liệu..."></textarea>
          <div class="composer-actions">
            <span class="muted">Enter để gửi · Shift+Enter để xuống dòng</span>
            <div>
              <button id="send" type="submit">Send</button>
            </div>
          </div>
        </form>
      </footer>
    </main>
  </div>
  <script>
    const filesEl = document.getElementById("files");
    const sessionsEl = document.getElementById("sessions");
    const chatEl = document.getElementById("chat");
    const statusEl = document.getElementById("status");
    const titleEl = document.getElementById("chat-title");
    const inputEl = document.getElementById("file-input");
    const formEl = document.getElementById("composer");
    const sendEl = document.getElementById("send");
    const messageEl = document.getElementById("message");
    const actorId = localStorage.getItem("agent_actor_id") || crypto.randomUUID();
    localStorage.setItem("agent_actor_id", actorId);
    let sessions = JSON.parse(localStorage.getItem("agent_sessions") || "[]");
    let currentSessionId = localStorage.getItem("agent_current_session") || null;

    function persistSessions() { localStorage.setItem("agent_sessions", JSON.stringify(sessions)); }
    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }
    function renderMessageHtml(text) {
      const escaped = escapeHtml(text || "");
      return escaped.replace(/!\\[([^\\]]*)\\]\\((\\/assets\\/[A-Za-z0-9._\\/-]+)\\)/g, '<img src="$2" alt="$1" loading="lazy" />');
    }
    function displayFileName(filename) {
      return String(filename || "").replace(/[.][^.]+$/, "");
    }
    function addMessage(role, text, className = "") {
      const node = document.createElement("div");
      node.className = `message ${role} ${className}`;
      if (role === "assistant") node.innerHTML = renderMessageHtml(text);
      else node.textContent = text;
      chatEl.appendChild(node);
      chatEl.scrollTop = chatEl.scrollHeight;
    }
    function upsertSessionTitle(message) {
      const session = sessions.find((item) => item.id === currentSessionId);
      if (session && session.title === "New chat") {
        session.title = message.slice(0, 42) || "New chat";
        persistSessions(); renderSessions();
      }
    }
    function createSession() {
      const session = { id: crypto.randomUUID(), title: "New chat", createdAt: new Date().toISOString() };
      sessions.unshift(session); currentSessionId = session.id;
      localStorage.setItem("agent_current_session", currentSessionId); persistSessions(); renderSessions(); loadSession(currentSessionId, true);
    }
    function renderSessions() {
      sessionsEl.innerHTML = "";
      for (const session of sessions) {
        const node = document.createElement("div");
        node.className = `session-item ${session.id === currentSessionId ? "active" : ""}`;
        node.innerHTML = `
          <div class="session-row">
            <div class="session-meta">
              <div class="session-title">${escapeHtml(session.title)}</div>
              <div class="muted">${new Date(session.createdAt).toLocaleString()}</div>
            </div>
            <div class="session-actions">
              <button class="icon-button rename-session" type="button" title="Đổi tên">Sửa</button>
              <button class="icon-button danger delete-session" type="button" title="Xoá">Xoá</button>
            </div>
          </div>`;
        node.onclick = () => { currentSessionId = session.id; localStorage.setItem("agent_current_session", currentSessionId); renderSessions(); loadSession(currentSessionId); };
        node.ondblclick = () => renameSession(session.id, node);
        node.querySelector(".rename-session").onclick = (event) => { event.stopPropagation(); renameSession(session.id, node); };
        node.querySelector(".delete-session").onclick = (event) => { event.stopPropagation(); deleteSession(session.id); };
        sessionsEl.appendChild(node);
      }
    }
    function renameSession(sessionId, node) {
      const session = sessions.find((item) => item.id === sessionId);
      if (!session) return;
      const input = document.createElement("input");
      input.className = "session-title-input";
      input.value = session.title;
      node.innerHTML = "";
      node.appendChild(input);
      input.focus(); input.select();
      function save() {
        const title = input.value.trim();
        if (title) session.title = title;
        persistSessions(); renderSessions();
        if (sessionId === currentSessionId) titleEl.textContent = session.title;
      }
      input.onblur = save;
      input.onkeydown = (event) => {
        if (event.key === "Enter") { event.preventDefault(); input.blur(); }
        if (event.key === "Escape") renderSessions();
      };
    }
    function deleteSession(sessionId) {
      sessions = sessions.filter((item) => item.id !== sessionId);
      if (currentSessionId === sessionId) {
        currentSessionId = sessions[0]?.id || null;
        if (currentSessionId) localStorage.setItem("agent_current_session", currentSessionId);
        else localStorage.removeItem("agent_current_session");
      }
      persistSessions();
      if (!sessions.length) createSession();
      else { renderSessions(); loadSession(currentSessionId); }
    }
    async function loadSession(sessionId, isNew = false) {
      titleEl.textContent = sessions.find((item) => item.id === sessionId)?.title || "Ai agent analytics data product home";
      chatEl.innerHTML = "";
      if (isNew) addMessage("assistant", "tôi có thể giúp gì được cho bạn");
      try {
        const response = await fetch(`/sessions/${sessionId}/events?actor_id=${encodeURIComponent(actorId)}`);
        const data = await response.json();
        if (data.events?.length) {
          chatEl.innerHTML = "";
          for (const event of data.events) addMessage(event.role === "user" ? "user" : "assistant", event.message || "");
        } else if (!chatEl.innerText.trim()) addMessage("assistant", "tôi có thể giúp gì được cho bạn");
      } catch { if (!chatEl.innerText.trim()) addMessage("assistant", "tôi có thể giúp gì được cho bạn"); }
    }
    async function loadFiles() {
      return;
    }
    inputEl.addEventListener("change", async () => {
      if (!inputEl.files.length) return; statusEl.textContent = "uploading";
      const formData = new FormData(); for (const file of inputEl.files) formData.append("files", file);
      const response = await fetch("/uploads", { method: "POST", body: formData });
      const data = await response.json(); statusEl.textContent = response.ok ? "ready" : "upload failed";
      if (!response.ok) addMessage("assistant", data.message || "Upload lỗi.", "error"); inputEl.value = ""; await loadFiles();
    });
    async function readJsonSafely(response) { try { return await response.json(); } catch { return { status:"error", message: await response.text() }; } }
    async function pollJob(jobId) {
      for (let attempt = 0; attempt < 180; attempt++) {
        const response = await fetch(`/jobs/${jobId}`); const data = await readJsonSafely(response);
        if (!response.ok || data.status === "error") return data;
        if (data.status === "completed") return data.result;
        statusEl.textContent = "inprogess"; await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      return { status:"error", message:"Agent analysis timed out. Please try again." };
    }
    messageEl.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); formEl.requestSubmit(); } });
    formEl.addEventListener("submit", async (event) => {
      event.preventDefault(); if (!currentSessionId) createSession();
      const message = messageEl.value.trim(); if (!message || sendEl.disabled) return;
      const fileIds = [];
      addMessage("user", message); upsertSessionTitle(message); messageEl.value = ""; statusEl.textContent = "inprogess"; sendEl.disabled = true;
      try {
        const response = await fetch("/chat", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ message, file_ids:fileIds, actor_id:actorId, session_id:currentSessionId }) });
        const started = await readJsonSafely(response);
        if (!response.ok || started.status === "error") { addMessage("assistant", started.message || "Agent trả về lỗi.", "error"); return; }
        const data = await pollJob(started.job_id);
        addMessage("assistant", data.response || data.message || JSON.stringify(data, null, 2), data.status === "error" ? "error" : "");
      } catch (error) { addMessage("assistant", `Không gọi được agent. Vui lòng thử lại. Chi tiết: ${error.message}`, "error"); messageEl.value = message; }
      finally { statusEl.textContent = "ready"; sendEl.disabled = false; messageEl.focus(); }
    });
    document.getElementById("new-session").onclick = createSession;
    if (!sessions.length || !currentSessionId) createSession(); else { renderSessions(); loadSession(currentSessionId); }
    loadFiles(); messageEl.focus();
  </script>
</body>
</html>
"""


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def ensure_upload_store() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not UPLOAD_INDEX.exists():
        UPLOAD_INDEX.write_text("[]")


def load_upload_index() -> list[dict[str, Any]]:
    ensure_upload_store()
    return json.loads(UPLOAD_INDEX.read_text())


def save_upload_index(items: list[dict[str, Any]]) -> None:
    ensure_upload_store()
    UPLOAD_INDEX.write_text(json.dumps(items, ensure_ascii=False, indent=2))


def safe_filename(filename: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip("-")
    return clean or "uploaded-file"


def file_kind(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".txt", ".md", ".json"}:
        return "text"
    return "file"


async def home_page(request) -> HTMLResponse:
    return HTMLResponse(HOME_PAGE)


async def list_uploads(request) -> JSONResponse:
    return JSONResponse({"files": load_upload_index()})


async def create_uploads(request) -> JSONResponse:
    form = await request.form()
    incoming_files = form.getlist("files")
    if not incoming_files:
        return JSONResponse({"message": "No files uploaded"}, status_code=400)

    items = load_upload_index()
    created = []
    for upload in incoming_files:
        content = await upload.read()
        if len(content) > MAX_UPLOAD_BYTES:
            return JSONResponse(
                {"message": f"{upload.filename} exceeds max upload size"},
                status_code=413,
            )
        file_id = str(uuid.uuid4())
        filename = safe_filename(upload.filename or "uploaded-file")
        stored_name = f"{file_id}-{filename}"
        path = UPLOAD_DIR / stored_name
        path.write_bytes(content)
        item = {
            "id": file_id,
            "filename": filename,
            "stored_name": stored_name,
            "kind": file_kind(filename),
            "size": len(content),
            "created_at": datetime.now().isoformat(),
        }
        items.append(item)
        created.append(item)

    save_upload_index(items)
    return JSONResponse({"files": created})


async def asset_route(request):
    filename = request.path_params["filename"]
    if filename != HOMEPAGE_RESULT_IMAGE.name or not HOMEPAGE_RESULT_IMAGE.exists():
        return JSONResponse({"message": "Asset not found"}, status_code=404)
    return FileResponse(HOMEPAGE_RESULT_IMAGE)


app.add_route("/", home_page, methods=["GET"])
app.add_route("/uploads", list_uploads, methods=["GET"])
app.add_route("/uploads", create_uploads, methods=["POST"])
app.add_route("/assets/{filename}", asset_route, methods=["GET"])

# Legacy Supabase connector. It is intentionally not used by default anymore:
# set DATA_SOURCE=supabase if you want the agent to query Supabase instead of
# the local Parquet file bundled in the image.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    or os.environ.get("SUPABASE_ANON_KEY", "").strip()
)
SUPABASE_TABLE = os.environ.get("SUPABASE_TABLE", "event_log").strip() or "event_log"
SUPABASE_SELECT = os.environ.get("SUPABASE_SELECT", "*").strip() or "*"
MAX_ROWS = int(os.environ.get("MAX_ROWS", "100"))

LLM_BASE_URL = require_env("LLM_BASE_URL").rstrip("/")
if "/chat/completions" in LLM_BASE_URL:
    LLM_BASE_URL = LLM_BASE_URL.split("/chat/completions", 1)[0].rstrip("/")
if not LLM_BASE_URL.endswith("/v1"):
    LLM_BASE_URL = f"{LLM_BASE_URL}/v1"
LLM_API_KEY = require_env("LLM_API_KEY")
LLM_MODEL = require_env("LLM_MODEL")

llm = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

MEMORY_BASE_URL = os.environ.get("MEMORY_BASE_URL", "https://agentbase.api.vngcloud.vn/memory").rstrip("/")
AGENTBASE_MEMORY_ID = os.environ.get("AGENTBASE_MEMORY_ID", "").strip()
MEMORY_STRATEGY_ID = os.environ.get("MEMORY_STRATEGY_ID", "").strip()
MEMORY_ACTOR_ID = os.environ.get("MEMORY_ACTOR_ID", "web-user").strip() or "web-user"
TOKEN_CACHE: dict[str, Any] = {}


def supabase_headers() -> dict[str, str]:
    if not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY is required for Supabase REST URLs")
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def fetch_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if DATA_SOURCE == "parquet":
        return fetch_rows_from_parquet(payload)
    if DATA_SOURCE != "supabase":
        raise RuntimeError("DATA_SOURCE must be either parquet or supabase")
    if SUPABASE_URL.startswith(("postgres://", "postgresql://")):
        return fetch_rows_from_postgres(payload)
    if SUPABASE_URL.startswith("https://"):
        return fetch_rows_from_rest(payload)
    raise RuntimeError("SUPABASE_URL must be either an https:// Supabase API URL or a postgresql:// connection string")


def safe_filters(payload: dict[str, Any]) -> dict[str, Any]:
    filters = payload.get("filters") or {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object of exact-match column/value pairs")
    for column in filters:
        if not str(column).replace("_", "").isalnum():
            raise ValueError(f"Unsafe filter column: {column}")
    return filters


def selected_columns() -> list[str] | None:
    if SUPABASE_SELECT == "*":
        return None
    columns = [column.strip() for column in SUPABASE_SELECT.split(",") if column.strip()]
    for column in columns:
        if not column.replace("_", "").isalnum():
            raise ValueError(f"Unsafe select column: {column}")
    return columns


def parquet_schema() -> dict[str, Any]:
    if not PARQUET_PATH.exists():
        raise RuntimeError(f"Parquet data file not found: {PARQUET_PATH}")
    return {field.name: field.type for field in pq.read_schema(PARQUET_PATH)}


def parquet_filter_expression(filters: dict[str, Any]):
    schema = parquet_schema()
    expression = None
    for column, value in filters.items():
        column_type = schema.get(column)
        if column_type is None:
            raise ValueError(f"Unknown Parquet column: {column}")
        typed_value = value
        if str(column_type).startswith("int"):
            typed_value = int(value)
        part = pyarrow_dataset.field(column) == typed_value
        expression = part if expression is None else expression & part
    return expression


def fetch_rows_from_parquet(payload: dict[str, Any]) -> list[dict[str, Any]]:
    limit = min(int(payload.get("limit", MAX_ROWS)), MAX_ROWS)
    filters = safe_filters(payload)
    schema = parquet_schema()
    requested_columns = selected_columns()
    columns = requested_columns or list(schema.keys())
    for column in columns:
        if column not in schema:
            raise ValueError(f"Unknown Parquet column: {column}")

    dataset = pyarrow_dataset.dataset(PARQUET_PATH, format="parquet")
    table = dataset.to_table(
        columns=columns,
        filter=parquet_filter_expression(filters) if filters else None,
    )
    return table.slice(0, limit).to_pylist()


def parquet_value_counts(column: str, limit: int = 20) -> list[dict[str, Any]]:
    table = pyarrow_dataset.dataset(PARQUET_PATH, format="parquet").to_table(columns=[column])
    counts = pc.value_counts(table[column]).to_pylist()
    rows = [{"value": item["values"], "count": item["counts"]} for item in counts]
    return sorted(rows, key=lambda row: row["count"], reverse=True)[:limit]


def parquet_summary() -> dict[str, Any]:
    if DATA_SOURCE != "parquet" or not PARQUET_PATH.exists():
        return {"enabled": False}
    metadata = pq.read_metadata(PARQUET_PATH)
    schema = pq.read_schema(PARQUET_PATH)
    summary: dict[str, Any] = {
        "enabled": True,
        "path": str(PARQUET_PATH),
        "rows": metadata.num_rows,
        "size_bytes": PARQUET_PATH.stat().st_size,
        "columns": schema.names,
    }
    dataset = pyarrow_dataset.dataset(PARQUET_PATH, format="parquet")
    if "ymd" in schema.names:
        ymd_table = dataset.to_table(columns=["ymd"])
        summary["ymd_min"] = pc.min(ymd_table["ymd"]).as_py()
        summary["ymd_max"] = pc.max(ymd_table["ymd"]).as_py()
    if "event_id" in schema.names:
        summary["top_event_ids"] = parquet_value_counts("event_id")
    if "os" in schema.names:
        summary["os_counts"] = parquet_value_counts("os")
    return summary


def fetch_rows_from_rest(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # Legacy Supabase REST connector. Not used unless DATA_SOURCE=supabase.
    limit = min(int(payload.get("limit", MAX_ROWS)), MAX_ROWS)
    params: dict[str, str | int] = {
        "select": str(payload.get("select") or SUPABASE_SELECT),
        "limit": limit,
    }
    for column, value in safe_filters(payload).items():
        params[str(column)] = f"eq.{value}"

    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}",
        headers=supabase_headers(),
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError("Unexpected Supabase response")
    return data


def fetch_rows_from_postgres(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # Legacy Supabase Postgres connector. Not used unless DATA_SOURCE=supabase.
    limit = min(int(payload.get("limit", MAX_ROWS)), MAX_ROWS)
    filters = safe_filters(payload)
    columns = selected_columns()
    select_sql = sql.SQL("*") if columns is None else sql.SQL(", ").join(
        sql.Identifier(column) for column in columns
    )
    query = sql.SQL("SELECT {columns} FROM {table}").format(
        columns=select_sql,
        table=sql.Identifier(SUPABASE_TABLE),
    )
    values: list[Any] = []
    if filters:
        where_parts = []
        for column, value in filters.items():
            where_parts.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
            values.append(value)
        query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where_parts)
    query += sql.SQL(" LIMIT %s")
    values.append(limit)

    with psycopg.connect(SUPABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, values)
            names = [column.name for column in cursor.description or []]
            return [dict(zip(names, row)) for row in cursor.fetchall()]


def summarize_csv(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as file:
        reader = csv.DictReader(file)
        rows = []
        for index, row in enumerate(reader):
            if index >= 40:
                break
            rows.append(row)
        columns = reader.fieldnames or []
    return json.dumps(
        {"type": "csv", "columns": columns, "sample_rows": rows},
        ensure_ascii=False,
    )[:MAX_FILE_CONTEXT_CHARS]


def summarize_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages[:8]:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)[:MAX_FILE_CONTEXT_CHARS]


def summarize_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_CONTEXT_CHARS]


def load_file_context(file_ids: list[str]) -> list[dict[str, str]]:
    items = {item["id"]: item for item in load_upload_index()}
    contexts = []
    for file_id in file_ids:
        item = items.get(file_id)
        if not item:
            continue
        path = UPLOAD_DIR / item["stored_name"]
        if not path.exists():
            continue
        try:
            if item["kind"] == "csv":
                content = summarize_csv(path)
            elif item["kind"] == "pdf":
                content = summarize_pdf(path)
            elif item["kind"] == "text":
                content = summarize_text(path)
            else:
                content = f"Unsupported file type for deep extraction. filename={item['filename']} size={item['size']}"
        except Exception as error:
            content = f"Could not extract file: {type(error).__name__}"
        contexts.append({"filename": item["filename"], "kind": item["kind"], "content": content})
    return contexts


def load_local_greennode_credentials() -> tuple[str, str]:
    client_id = os.environ.get("GREENNODE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GREENNODE_CLIENT_SECRET", "").strip()
    config_path = Path(".greennode.json")
    if (not client_id or not client_secret) and config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            client_id = client_id or data.get("client_id", "")
            client_secret = client_secret or data.get("client_secret", "")
        except Exception:
            pass
    return client_id, client_secret


def get_agentbase_token() -> str:
    now = datetime.now().timestamp()
    cached = TOKEN_CACHE.get("access_token")
    expires_at = TOKEN_CACHE.get("expires_at", 0)
    if cached and expires_at > now + 60:
        return cached

    client_id, client_secret = load_local_greennode_credentials()
    if not client_id or not client_secret:
        raise RuntimeError("AgentBase IAM credentials are not available")

    response = requests.post(
        "https://iam.api.vngcloud.vn/accounts-api/v2/auth/token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=20,
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
    payload = {
        "payload": {
            "type": "conversational",
            "role": role,
            "message": message[:100000],
        }
    }
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


async def session_events_route(request) -> JSONResponse:
    session_id = request.path_params["session_id"]
    actor_id = request.query_params.get("actor_id") or MEMORY_ACTOR_ID
    try:
        return JSONResponse({"events": list_memory_events(actor_id, session_id)})
    except Exception as error:
        return JSONResponse({"events": [], "error": type(error).__name__}, status_code=200)


app.add_route("/sessions/{session_id}/events", session_events_route, methods=["GET"])


def load_system_prompt() -> str:
    fallback_prompt = (
        "You are a professional analytics data product agent. Prefer Vietnamese. "
        "Answer normal user questions when they are not data-analysis questions. "
        "If data is insufficient, explain what is missing."
    )
    try:
        return PROMPT_PATH.read_text(encoding="utf-8").strip() or fallback_prompt
    except FileNotFoundError:
        return fallback_prompt


def answer_with_llm(message: str, context: dict[str, Any]) -> str:
    system_prompt = load_system_prompt()
    completion = llm.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps({"question": message, "model": LLM_MODEL, **context}, ensure_ascii=False)},
        ],
        temperature=0.2,
    )
    return completion.choices[0].message.content or ""


def is_homepage_click_rate_question(message: str) -> bool:
    normalized = message.lower()
    click_terms = ("click rate", "ctr", "tỉ lệ lượt click", "tỷ lệ lượt click", "ti le luot click", "ty le luot click")
    home_terms = ("home page", "homepage", "trang chủ", "trang chu")
    icon_terms = ("icon", "dịch vụ", "dich vu")
    return (
        any(term in normalized for term in click_terms)
        and any(term in normalized for term in home_terms)
        and any(term in normalized for term in icon_terms)
    )


def attach_homepage_result_image(answer: str, message: str) -> str:
    if not is_homepage_click_rate_question(message):
        return answer
    image_markdown = f"![Home Page click-rate result]({HOMEPAGE_RESULT_IMAGE_URL})"
    if HOMEPAGE_RESULT_IMAGE_URL in answer:
        return answer
    return f"{answer.rstrip()}\n\n{image_markdown}"


def analyze_payload(payload: dict, session_id: str | None = None) -> dict:
    try:
        message = payload.get("message", "Hãy phân tích dữ liệu.")
        actor_id = str(payload.get("actor_id") or MEMORY_ACTOR_ID)
        effective_session_id = str(payload.get("session_id") or session_id or uuid.uuid4())
        file_ids = payload.get("file_ids") or []
        if not isinstance(file_ids, list):
            file_ids = []

        try:
            create_memory_event(actor_id, effective_session_id, "user", message)
        except Exception:
            pass

        file_context = load_file_context([str(file_id) for file_id in file_ids])
        rows: list[dict[str, Any]] = []
        if not file_context:
            rows = fetch_rows(payload)

        answer = answer_with_llm(
            message,
            {
                "uploaded_files": file_context,
                "result_assets": {
                    "homepage_click_rate_image": HOMEPAGE_RESULT_IMAGE_URL,
                },
                "data_source": {
                    "type": DATA_SOURCE,
                    "parquet": parquet_summary(),
                    "supabase_enabled": DATA_SOURCE == "supabase",
                },
                "query_rows": {
                    "table": SUPABASE_TABLE,
                    "row_count": len(rows),
                    "rows": rows,
                },
            },
        )
        answer = attach_homepage_result_image(answer, message)
        try:
            create_memory_event(actor_id, effective_session_id, "assistant", answer)
        except Exception:
            pass
        return {
            "status": "success",
            "response": answer,
            "rows_used": len(rows),
            "files_used": [file["filename"] for file in file_context],
            "table": SUPABASE_TABLE,
            "timestamp": datetime.now().isoformat(),
            "session_id": effective_session_id,
            "actor_id": actor_id,
            "memory_enabled": memory_enabled(),
            "data_source": DATA_SOURCE,
            "parquet_path": str(PARQUET_PATH) if DATA_SOURCE == "parquet" else None,
        }
    except Exception as error:
        return {
            "status": "error",
            "message": "Agent failed while analyzing data.",
            "detail": type(error).__name__,
            "timestamp": datetime.now().isoformat(),
            "session_id": session_id,
        }


def set_job(job_id: str, data: dict[str, Any]) -> None:
    with JOBS_LOCK:
        JOBS[job_id] = data


def get_job(job_id: str) -> dict[str, Any] | None:
    with JOBS_LOCK:
        return JOBS.get(job_id)


def run_chat_job(job_id: str, payload: dict[str, Any]) -> None:
    set_job(job_id, {"status": "inprogess", "created_at": datetime.now().isoformat()})
    result = analyze_payload(payload, session_id=job_id)
    status = "completed" if result.get("status") == "success" else "error"
    set_job(
        job_id,
        {
            "status": status,
            "result": result,
            "updated_at": datetime.now().isoformat(),
        },
    )


async def chat_route(request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON payload"}, status_code=400)
    job_id = str(uuid.uuid4())
    set_job(job_id, {"status": "queued", "created_at": datetime.now().isoformat()})
    JOB_EXECUTOR.submit(run_chat_job, job_id, payload)
    return JSONResponse({"status": "queued", "job_id": job_id}, status_code=202)


async def job_route(request) -> JSONResponse:
    job_id = request.path_params["job_id"]
    job = get_job(job_id)
    if not job:
        return JSONResponse({"status": "error", "message": "Job not found"}, status_code=404)
    return JSONResponse(job)


app.add_route("/chat", chat_route, methods=["POST"])
app.add_route("/jobs/{job_id}", job_route, methods=["GET"])


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    return analyze_payload(payload, session_id=context.session_id)


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
