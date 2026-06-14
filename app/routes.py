import uuid
from datetime import datetime
from pathlib import Path

from starlette.responses import FileResponse, HTMLResponse, JSONResponse

from .agent import get_job, run_chat_job, set_job
from .config import FRONTEND_INDEX, HOMEPAGE_RESULT_IMAGE, JOB_EXECUTOR, MAX_UPLOAD_BYTES, MEMORY_ACTOR_ID, RESULTS_DIR, UPLOAD_DIR
from .memory import list_memory_events
from .storage import load_upload_index, register_upload, safe_filename, save_upload_index


async def home_page(request) -> HTMLResponse:
    return HTMLResponse(FRONTEND_INDEX.read_text(encoding="utf-8"))


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
            return JSONResponse({"message": f"{upload.filename} exceeds max upload size"}, status_code=413)
        filename = safe_filename(upload.filename or "uploaded-file")
        stored_name = f"{uuid.uuid4()}-{filename}"
        stored_path = UPLOAD_DIR / stored_name
        stored_path.write_bytes(content)
        item = register_upload(filename, len(content), stored_path)
        items.append(item)
        created.append(item)
    save_upload_index(items)
    return JSONResponse({"files": created})


async def asset_route(request):
    filename = safe_filename(request.path_params["filename"])
    if filename != HOMEPAGE_RESULT_IMAGE.name or not HOMEPAGE_RESULT_IMAGE.exists():
        return JSONResponse({"message": "Asset not found"}, status_code=404)
    return FileResponse(HOMEPAGE_RESULT_IMAGE)


async def result_route(request):
    filename = safe_filename(request.path_params["filename"])
    path = RESULTS_DIR / filename
    if not path.exists() or path.suffix.lower() != ".png":
        return JSONResponse({"message": "Result not found"}, status_code=404)
    return FileResponse(path)


async def session_events_route(request) -> JSONResponse:
    session_id = request.path_params["session_id"]
    actor_id = request.query_params.get("actor_id") or MEMORY_ACTOR_ID
    try:
        return JSONResponse({"events": list_memory_events(actor_id, session_id)})
    except Exception as error:
        return JSONResponse({"events": [], "error": type(error).__name__}, status_code=200)


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


def register_routes(app) -> None:
    app.add_route("/", home_page, methods=["GET"])
    app.add_route("/uploads", list_uploads, methods=["GET"])
    app.add_route("/uploads", create_uploads, methods=["POST"])
    app.add_route("/assets/{filename}", asset_route, methods=["GET"])
    app.add_route("/results/{filename}", result_route, methods=["GET"])
    app.add_route("/sessions/{session_id}/events", session_events_route, methods=["GET"])
    app.add_route("/chat", chat_route, methods=["POST"])
    app.add_route("/jobs/{job_id}", job_route, methods=["GET"])
