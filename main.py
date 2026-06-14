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
from PIL import Image, ImageDraw, ImageFont
from psycopg import sql
from pypdf import PdfReader
from starlette.responses import FileResponse, HTMLResponse, JSONResponse

load_dotenv()

app = GreenNodeAgentBaseApp()

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/tmp/agent_uploads"))
UPLOAD_INDEX = UPLOAD_DIR / "index.json"
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", "/tmp/agent_results"))
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
    .shell { display:grid; grid-template-columns:300px minmax(0,1fr); min-height:100vh; max-width:100vw; overflow:hidden; }
    aside { min-width:0; width:300px; border-right:1px solid var(--border); background:#080c14; padding:16px; display:grid; grid-template-rows:auto auto minmax(0,1fr) auto; gap:14px; overflow:hidden; }
    .brand { min-width:0; font-weight:760; line-height:1.25; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .panel { border:1px solid var(--border); background:var(--panel); border-radius:16px; padding:12px; }
    button { border:0; border-radius:12px; padding:10px 12px; color:#06130f; background:var(--accent); font-weight:760; cursor:pointer; }
    button.secondary { color:var(--text); background:var(--soft); border:1px solid var(--border); }
    button:disabled { opacity:.55; cursor:wait; }
    .muted { color:var(--muted); font-size:12px; line-height:1.45; }
    .section-title { color:var(--muted); font-size:11px; font-weight:800; letter-spacing:.09em; text-transform:uppercase; margin:6px 0; }
    #new-session { width:100%; }
    #sessions { min-width:0; display:grid; gap:8px; overflow:auto; }
    .session-item, .file-card { min-width:0; max-width:100%; border:1px solid var(--border); background:var(--panel); border-radius:13px; padding:10px; cursor:pointer; overflow:hidden; }
    .session-item.active { border-color:rgba(16,163,127,.7); background:var(--accent-soft); }
    .session-row { min-width:0; display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:flex-start; gap:8px; }
    .session-meta { min-width:0; flex:1; }
    .session-actions { display:flex; flex-shrink:0; gap:6px; opacity:.7; }
    .session-item:hover .session-actions { opacity:1; }
    .icon-button { border:1px solid var(--border); border-radius:9px; padding:5px 7px; background:var(--soft); color:var(--muted); font-size:11px; line-height:1; }
    .icon-button:hover { color:var(--text); border-color:rgba(16,163,127,.55); }
    .icon-button.danger:hover { color:var(--danger); border-color:rgba(251,113,133,.6); }
    .session-title, .file-name { font-weight:680; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .session-title-input { width:100%; border:1px solid var(--border); border-radius:10px; padding:7px 9px; background:var(--soft); color:var(--text); font:inherit; font-weight:680; }
    input[type=file] { width:100%; color:var(--muted); font-size:12px; }
    main { display:grid; grid-template-rows:auto 1fr auto; min-width:0; max-width:100%; max-height:100vh; overflow:hidden; }
    header { padding:16px 24px; border-bottom:1px solid var(--border); background:rgba(11,15,25,.9); }
    h1 { margin:0; font-size:17px; }
    #status { margin-top:4px; color:var(--muted); font-size:13px; }
    #chat { overflow:auto; padding:26px; display:flex; flex-direction:column; gap:14px; }
    .message { max-width:min(860px,100%); overflow-wrap:anywhere; padding:15px 17px; border:1px solid var(--border); border-radius:18px; background:var(--panel); line-height:1.58; white-space:pre-wrap; }
    .message img { display:block; max-width:min(100%,520px); height:auto; margin-top:12px; border-radius:16px; border:1px solid var(--border); background:#fff; }
    .user { align-self:flex-end; background:var(--accent-soft); border-color:rgba(16,163,127,.36); }
    .assistant { align-self:flex-start; }
    .process { align-self:flex-start; max-width:min(560px,100%); border:1px solid var(--border); border-radius:16px; background:rgba(21,29,46,.72); padding:12px 14px; color:var(--muted); }
    .process-head { display:flex; align-items:center; justify-content:space-between; gap:12px; font-weight:760; color:var(--text); }
    .process-toggle { color:var(--text); background:var(--soft); border:1px solid var(--border); padding:6px 9px; border-radius:9px; font-size:12px; }
    .process-list { display:none; margin:10px 0 0; padding-left:18px; font-size:13px; line-height:1.55; }
    .process.open .process-list { display:block; }
    .error { color:var(--danger); }
    footer { padding:16px 24px 22px; border-top:1px solid var(--border); background:rgba(11,15,25,.94); }
    .composer { border:1px solid var(--border); border-radius:16px; background:var(--panel); padding:12px; display:grid; gap:10px; }
    textarea { min-height:76px; resize:vertical; width:100%; border:0; outline:0; color:var(--text); background:transparent; font:inherit; }
    .composer-actions { display:flex; align-items:center; justify-content:space-between; gap:12px; }
    @media (max-width:860px) {
      .shell{grid-template-columns:1fr; overflow:auto}
      aside{width:100%; border-right:0; border-bottom:1px solid var(--border)}
      main{max-height:none}
    }
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
      return escaped.replace(/!\\[([^\\]]*)\\]\\((\\/(?:assets|results)\\/[A-Za-z0-9._\\/-]+)\\)/g, '<img src="$2" alt="$1" loading="lazy" />');
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
    function addProcessMessage() {
      const node = document.createElement("div");
      node.className = "process";
      node.innerHTML = '<div class="process-head"><span>Agent đang xử lý...</span><button class="process-toggle" type="button">Show process</button></div><ol class="process-list"></ol>';
      const button = node.querySelector(".process-toggle");
      button.onclick = () => {
        node.classList.toggle("open");
        button.textContent = node.classList.contains("open") ? "Hide process" : "Show process";
      };
      chatEl.appendChild(node);
      chatEl.scrollTop = chatEl.scrollHeight;
      return node;
    }
    function updateProcessMessage(node, steps = []) {
      if (!node) return;
      const list = node.querySelector(".process-list");
      list.innerHTML = "";
      for (const step of steps) {
        const item = document.createElement("li");
        item.textContent = step.message || String(step);
        list.appendChild(item);
      }
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
    async function pollJob(jobId, processNode) {
      for (let attempt = 0; attempt < 180; attempt++) {
        const response = await fetch(`/jobs/${jobId}`); const data = await readJsonSafely(response);
        updateProcessMessage(processNode, data.process || []);
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
        const processNode = addProcessMessage();
        updateProcessMessage(processNode, started.process || [{ message:"Đã nhận câu hỏi và đưa vào hàng đợi." }]);
        const data = await pollJob(started.job_id, processNode);
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


async def result_route(request):
    filename = safe_filename(request.path_params["filename"])
    path = RESULTS_DIR / filename
    if not path.exists() or path.suffix.lower() != ".png":
        return JSONResponse({"message": "Result not found"}, status_code=404)
    return FileResponse(path)


app.add_route("/", home_page, methods=["GET"])
app.add_route("/uploads", list_uploads, methods=["GET"])
app.add_route("/uploads", create_uploads, methods=["POST"])
app.add_route("/assets/{filename}", asset_route, methods=["GET"])
app.add_route("/results/{filename}", result_route, methods=["GET"])

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


def recent_session_memory(actor_id: str, session_id: str, limit: int = 20) -> list[dict[str, str]]:
    try:
        events = list_memory_events(actor_id, session_id)
    except Exception:
        return []
    return events[-limit:]


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


def clean_assistant_markdown(answer: str) -> str:
    cleaned_lines = []
    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        if re.fullmatch(r"\|?[\s:\-|\+]+\|?", line):
            continue
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        line = line.replace("**", "")
        if "|" in line and line.count("|") >= 2:
            cells = [cell.strip() for cell in line.strip("|").split("|") if cell.strip()]
            if cells:
                line = "- " + " — ".join(cells)
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


HOME_CLICK_VALUE_POSITIONS = [
    {"name": "Chuyển tiền", "x": 88, "y": 530},
    {"name": "QR của tôi", "x": 296, "y": 530},
    {"name": "Nạp/Rút", "x": 500, "y": 530},
    {"name": "Ưu đãi", "x": 708, "y": 530},
    {"name": "Hóa đơn", "x": 72, "y": 773},
    {"name": "Điện thoại", "x": 282, "y": 773},
    {"name": "Vé phim", "x": 492, "y": 773},
    {"name": "Số dư sinh lời", "x": 708, "y": 773},
    {"name": "Du lịch", "x": 72, "y": 971},
    {"name": "Ngân hàng", "x": 282, "y": 971},
    {"name": "Trả sau", "x": 492, "y": 971},
    {"name": "Xem tất cả", "x": 708, "y": 971},
    {"name": "Bảo hiểm xe máy", "x": 82, "y": 1246},
    {"name": "Tiện ích", "x": 282, "y": 1246},
    {"name": "Vé phim", "x": 488, "y": 1246},
    {"name": "Ăn uống", "x": 704, "y": 1246},
]

HOME_CLICK_SERVICE_ALIASES = {
    "Xem tất cả": ("Xem tất cả", "Tất cả"),
}


def font_for_homepage_image(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def extract_ymd_range(message: str) -> tuple[int | None, int | None, str]:
    normalized = message.lower()
    month_match = re.search(r"(?:tháng|thang|month)\s*(\d{1,2})\s*[/\-\s]\s*(20\d{2})", normalized)
    if month_match:
        month = int(month_match.group(1))
        year = int(month_match.group(2))
        if 1 <= month <= 12:
            next_month = datetime(year + (month // 12), (month % 12) + 1, 1)
            end_day = (next_month - datetime.resolution).day
            return year * 10000 + month * 100 + 1, year * 10000 + month * 100 + end_day, f"tháng {month:02d}/{year}"

    compact_match = re.search(r"\b(20\d{2})(\d{2})\b", normalized)
    if compact_match:
        year = int(compact_match.group(1))
        month = int(compact_match.group(2))
        if 1 <= month <= 12:
            next_month = datetime(year + (month // 12), (month % 12) + 1, 1)
            end_day = (next_month - datetime.resolution).day
            return year * 10000 + month * 100 + 1, year * 10000 + month * 100 + end_day, f"tháng {month:02d}/{year}"

    return None, None, "toàn bộ dữ liệu"


def ymd_in_range(value: Any, start_ymd: int | None, end_ymd: int | None) -> bool:
    if start_ymd is None or end_ymd is None:
        return True
    try:
        ymd_value = int(value)
    except Exception:
        return False
    return start_ymd <= ymd_value <= end_ymd


def calculate_homepage_click_rates(start_ymd: int | None = None, end_ymd: int | None = None) -> list[dict[str, Any]]:
    dataset = pyarrow_dataset.dataset(PARQUET_PATH, format="parquet")
    table = dataset.to_table(columns=["event_id", "user_id", "app_profile_name", "ymd"])
    event_ids = table["event_id"].to_pylist()
    user_ids = table["user_id"].to_pylist()
    names = table["app_profile_name"].to_pylist()
    ymd_values = table["ymd"].to_pylist()

    home_users: set[str] = set()
    clicked_by_service: dict[str, set[str]] = {}
    for event_id, user_id, service_name, ymd_value in zip(event_ids, user_ids, names, ymd_values):
        if not user_id:
            continue
        if not ymd_in_range(ymd_value, start_ymd, end_ymd):
            continue
        if event_id in {"AAAA.005", "01.1005.005"}:
            home_users.add(user_id)
        if event_id in {"AAAA.020", "01.1005.020"} and service_name:
            clicked_by_service.setdefault(str(service_name), set()).add(user_id)

    denominator = max(len(home_users), 1)
    rows = []
    for service_name, users in clicked_by_service.items():
        clicked_users = len(users)
        rows.append(
            {
                "service": service_name,
                "clicked_users": clicked_users,
                "home_users": len(home_users),
                "click_rate_pct": round(clicked_users / denominator * 100, 2),
            }
        )
    return sorted(rows, key=lambda row: row["click_rate_pct"], reverse=True)


def is_red_annotation(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    return red > 120 and green < 235 and blue < 235 and red > green + 20 and red > blue + 20


def scrub_old_homepage_red_values(image: Image.Image) -> None:
    width, height = image.size
    pixels = image.load()
    for item in HOME_CLICK_VALUE_POSITIONS:
        x = int(item["x"])
        y = int(item["y"])
        fill_color = (248, 252, 255) if y < 700 else (255, 255, 255)
        arrow_left = max(0, x + 55)
        arrow_top = max(0, y + 18)
        arrow_right = min(width - 1, x + 100)
        arrow_bottom = min(height - 1, y + 44)
        for pixel_y in range(arrow_top, arrow_bottom + 1):
            for pixel_x in range(arrow_left, arrow_right + 1):
                pixels[pixel_x, pixel_y] = fill_color

        left = max(0, x - 45)
        top = max(0, y - 12)
        right = min(width - 1, x + 115)
        bottom = min(height - 1, y + 70)
        for pixel_y in range(top, bottom + 1):
            for pixel_x in range(left, right + 1):
                if is_red_annotation(pixels[pixel_x, pixel_y]):
                    pixels[pixel_x, pixel_y] = fill_color


def render_homepage_click_rate_image(job_id: str, click_rates: list[dict[str, Any]]) -> str:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rates_by_service = {row["service"]: row for row in click_rates}
    image = Image.open(HOMEPAGE_RESULT_IMAGE).convert("RGB")
    scrub_old_homepage_red_values(image)
    draw = ImageDraw.Draw(image)
    font = font_for_homepage_image(26)
    red = (255, 0, 0)

    for item in HOME_CLICK_VALUE_POSITIONS:
        aliases = HOME_CLICK_SERVICE_ALIASES.get(item["name"], (item["name"],))
        row = next((rates_by_service.get(alias) for alias in aliases if rates_by_service.get(alias)), None)
        value = f"{row['click_rate_pct']:.2f}%" if row else "0.00%"
        x = int(item["x"])
        y = int(item["y"])
        draw.text((x, y), value, fill=red, font=font)

    filename = f"homepage_click_rate_{safe_filename(job_id)}.png"
    output_path = RESULTS_DIR / filename
    image.save(output_path, "PNG")
    return f"/results/{filename}"


def homepage_click_rate_context(job_id: str, message: str) -> dict[str, Any]:
    start_ymd, end_ymd, period_label = extract_ymd_range(message)
    click_rates = calculate_homepage_click_rates(start_ymd, end_ymd)
    image_url = render_homepage_click_rate_image(job_id, click_rates)
    date_filter_sql = ""
    if start_ymd and end_ymd:
        date_filter_sql = f"\n    AND ymd BETWEEN {start_ymd} AND {end_ymd}"
    return {
        "image_url": image_url,
        "period": period_label,
        "start_ymd": start_ymd,
        "end_ymd": end_ymd,
        "rows": click_rates[:30],
        "sql": f"""WITH home_users AS (
  SELECT COUNT(DISTINCT user_id) AS total_home_users
  FROM event_log
  WHERE event_id = 'AAAA.005'{date_filter_sql}
),
icon_clicks AS (
  SELECT app_profile_name, COUNT(DISTINCT user_id) AS clicked_users
  FROM event_log
  WHERE event_id = 'AAAA.020'{date_filter_sql}
  GROUP BY app_profile_name
)
SELECT app_profile_name,
       clicked_users,
       total_home_users,
       ROUND(clicked_users * 100.0 / total_home_users, 2) AS click_rate_pct
FROM icon_clicks
CROSS JOIN home_users
ORDER BY click_rate_pct DESC;""",
        "python": f"""click_rates = calculate_homepage_click_rates(start_ymd={start_ymd!r}, end_ymd={end_ymd!r})
image_url = render_homepage_click_rate_image(job_id, click_rates)""",
    }


def is_homepage_click_rate_question(message: str) -> bool:
    normalized = message.lower()
    click_terms = ("click rate", "ctr", "tỉ lệ lượt click", "tỷ lệ lượt click", "ti le luot click", "ty le luot click")
    home_terms = ("home page", "homepage", "trang chủ", "trang chu", "trang home")
    return (
        any(term in normalized for term in click_terms)
        and any(term in normalized for term in home_terms)
    )


def should_load_default_dataset(message: str) -> bool:
    normalized = message.lower()
    memory_only_terms = ("hãy nhớ", "ghi nhớ", "nhớ logic", "remember", "save this logic", "lưu logic")
    if any(term in normalized for term in memory_only_terms):
        return False
    data_terms = (
        "analytics",
        "csv",
        "data",
        "dataset",
        "event",
        "event_log",
        "parquet",
        "query",
        "sql",
        "table",
        "bảng",
        "bao nhiêu",
        "click",
        "dòng",
        "dữ liệu",
        "lọc",
        "phân tích",
        "thống kê",
        "tính",
        "tỉ lệ",
        "tỷ lệ",
        "user",
    )
    return is_homepage_click_rate_question(message) or any(term in normalized for term in data_terms)


def attach_homepage_result_image(answer: str, message: str, image_url: str | None = None) -> str:
    if not is_homepage_click_rate_question(message):
        return answer
    result_url = image_url or HOMEPAGE_RESULT_IMAGE_URL
    answer = re.sub(r"!\\[[^\\]]*\\]\\(/(?:assets|results)/homepage[^)]*\\.png\\)", "", answer).strip()
    image_markdown = f"![Home Page click-rate result]({result_url})"
    if result_url in answer:
        return answer
    return f"{answer.rstrip()}\n\n{image_markdown}"


def analyze_payload(payload: dict, session_id: str | None = None, progress=None) -> dict:
    try:
        message = payload.get("message", "Hãy phân tích dữ liệu.")
        actor_id = str(payload.get("actor_id") or MEMORY_ACTOR_ID)
        effective_session_id = str(payload.get("session_id") or session_id or uuid.uuid4())
        file_ids = payload.get("file_ids") or []
        if not isinstance(file_ids, list):
            file_ids = []
        if progress:
            progress("Đã nhận câu hỏi và xác định session chat.")

        memory_context = recent_session_memory(actor_id, effective_session_id)
        if progress and memory_context:
            progress(f"Đã tải {len(memory_context)} event memory gần nhất của session.")

        try:
            create_memory_event(actor_id, effective_session_id, "user", message)
            if progress and memory_enabled():
                progress("Đã lưu message mới vào memory của session.")
        except Exception:
            pass

        file_context = []
        if progress:
            progress("Đang kiểm tra file upload đi kèm.")
        if file_ids:
            file_context = load_file_context([str(file_id) for file_id in file_ids])
            if progress:
                progress(f"Đã đọc {len(file_context)} file upload làm context.")

        rows: list[dict[str, Any]] = []
        if not file_context and should_load_default_dataset(message) and not is_homepage_click_rate_question(message):
            if progress:
                progress("Câu hỏi cần dữ liệu; đang lấy sample rows từ Parquet local.")
            rows = fetch_rows(payload)
        elif progress and not file_context and not is_homepage_click_rate_question(message):
            progress("Câu hỏi không yêu cầu dataset; bỏ qua bước đọc Parquet.")

        homepage_context: dict[str, Any] | None = None
        if is_homepage_click_rate_question(message):
            if progress:
                progress("Phát hiện câu hỏi CTR Trang chủ; đang tính tỉ lệ click từ Parquet.")
            homepage_context = homepage_click_rate_context(effective_session_id, message)
            if progress:
                progress("Đã render ảnh kết quả mới với value đỏ được cập nhật.")

        if progress:
            progress("Đang gọi model để soạn câu trả lời.")
        answer = answer_with_llm(
            message,
            {
                "uploaded_files": file_context,
                "session_memory": {
                    "scope": "same_actor_same_session",
                    "recent_events": memory_context,
                    "instruction": "Use user-provided data logic from this session when relevant. If newer user logic conflicts with older logic, prefer the newer instruction.",
                },
                "result_assets": {
                    "homepage_click_rate_image": homepage_context["image_url"] if homepage_context else HOMEPAGE_RESULT_IMAGE_URL,
                },
                "homepage_click_rate": homepage_context,
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
        answer = clean_assistant_markdown(answer)
        answer = attach_homepage_result_image(
            answer,
            message,
            homepage_context["image_url"] if homepage_context else None,
        )
        if progress:
            progress("Hoàn tất câu trả lời.")
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


def update_job(job_id: str, data: dict[str, Any]) -> None:
    with JOBS_LOCK:
        current = JOBS.get(job_id, {})
        current.update(data)
        JOBS[job_id] = current


def add_job_process(job_id: str, message: str) -> None:
    with JOBS_LOCK:
        current = JOBS.get(job_id, {})
        process = list(current.get("process") or [])
        process.append({"time": datetime.now().isoformat(), "message": message})
        current["process"] = process
        JOBS[job_id] = current


def get_job(job_id: str) -> dict[str, Any] | None:
    with JOBS_LOCK:
        return JOBS.get(job_id)


def run_chat_job(job_id: str, payload: dict[str, Any]) -> None:
    update_job(job_id, {"status": "inprogess", "updated_at": datetime.now().isoformat()})
    add_job_process(job_id, "Bắt đầu xử lý yêu cầu.")
    result = analyze_payload(payload, session_id=job_id, progress=lambda message: add_job_process(job_id, message))
    status = "completed" if result.get("status") == "success" else "error"
    update_job(
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
    set_job(
        job_id,
        {
            "status": "queued",
            "created_at": datetime.now().isoformat(),
            "process": [{"time": datetime.now().isoformat(), "message": "Đã nhận request chat."}],
        },
    )
    JOB_EXECUTOR.submit(run_chat_job, job_id, payload)
    return JSONResponse({"status": "queued", "job_id": job_id, "process": get_job(job_id).get("process", [])}, status_code=202)


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
