import uuid
from datetime import datetime
from typing import Any

from .config import DATA_SOURCE, HOMEPAGE_RESULT_IMAGE_URL, JOBS, JOBS_LOCK, MEMORY_ACTOR_ID, PARQUET_PATH, SUPABASE_TABLE
from .data_sources import fetch_rows, parquet_summary
from .file_context import load_file_context
from .homepage_ctr import attach_homepage_result_image, homepage_click_rate_context, is_homepage_click_rate_question
from .llm import answer_with_llm, clean_assistant_markdown
from .memory import create_memory_event, memory_enabled, recent_session_memory


def should_load_default_dataset(message: str) -> bool:
    normalized = message.lower()
    memory_only_terms = ("hãy nhớ", "ghi nhớ", "nhớ logic", "remember", "save this logic", "lưu logic")
    if any(term in normalized for term in memory_only_terms):
        return False
    data_terms = (
        "analytics", "csv", "data", "dataset", "event", "event_log", "parquet", "query", "sql", "table",
        "bảng", "bao nhiêu", "click", "dòng", "dữ liệu", "lọc", "phân tích", "thống kê", "tính", "tỉ lệ",
        "tỷ lệ", "user",
    )
    return is_homepage_click_rate_question(message) or any(term in normalized for term in data_terms)


def analyze_payload(payload: dict, session_id: str | None = None, progress=None) -> dict:
    try:
        message = payload.get("message", "Hãy phân tích dữ liệu.")
        actor_id = str(payload.get("actor_id") or MEMORY_ACTOR_ID)
        effective_session_id = str(payload.get("session_id") or session_id or uuid.uuid4())
        result_id = str(payload.get("_job_id") or uuid.uuid4())
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
            homepage_context = homepage_click_rate_context(result_id, message)
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
                "query_rows": {"table": SUPABASE_TABLE, "row_count": len(rows), "rows": rows},
            },
        )
        answer = clean_assistant_markdown(answer)
        answer = attach_homepage_result_image(answer, message, homepage_context["image_url"] if homepage_context else None)
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
        return {"status": "error", "message": "Agent failed while analyzing data.", "detail": type(error).__name__, "timestamp": datetime.now().isoformat(), "session_id": session_id}


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
    payload_with_job_id = {**payload, "_job_id": job_id}
    result = analyze_payload(payload_with_job_id, session_id=job_id, progress=lambda message: add_job_process(job_id, message))
    status = "completed" if result.get("status") == "success" else "error"
    update_job(job_id, {"status": status, "result": result, "updated_at": datetime.now().isoformat()})
