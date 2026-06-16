import uuid
from datetime import datetime
from typing import Any

from .config import DATA_SOURCE, JOBS, JOBS_LOCK, MEMORY_ACTOR_ID, PARQUET_PATH, SUPABASE_TABLE, logger
from .daily_new_user import handle_daily_new_user_email, is_daily_new_user_email_request
from .data_sources import fetch_rows, parquet_summary
from .file_context import load_file_context
# [DISABLED] Home Page % image output — tạm thời bỏ. Module homepage_ctr vẫn còn
# nhưng không dùng nữa; câu hỏi CTR được trả lời bằng số liệu qua đường SQL.
# from .homepage_ctr import attach_homepage_result_image, homepage_click_rate_context, is_homepage_click_rate_question
from .llm import answer_with_llm, clean_assistant_markdown, generate_sql
from .memory import (
    create_memory_event,
    generate_long_term_from_session,
    long_term_enabled,
    memory_enabled,
    recall_long_term,
    recent_session_memory,
    remember_long_term,
)
from .query_engine import run_sql

REMEMBER_TERMS = ("hãy nhớ", "ghi nhớ", "nhớ logic", "remember", "save this logic", "lưu logic", "lưu lại")


def wants_to_remember(message: str) -> bool:
    normalized = message.lower()
    return any(term in normalized for term in REMEMBER_TERMS)


def run_data_query(message: str, memory_context: list, long_term_facts: list, progress=None) -> dict:
    """Generate DuckDB SQL for the question, execute it on the Parquet, and return
    the real result. Retries once if the first query errors. Returns a dict with
    keys: sql, columns, rows, row_count, truncated, error (error is None on success).
    """
    error_hint = ""
    for attempt in range(2):
        try:
            sql = generate_sql(message, memory_context, long_term_facts, error_hint=error_hint)
            if progress:
                progress("Đang chạy truy vấn SQL trên toàn bộ dữ liệu Parquet." if attempt == 0
                         else "Truy vấn lỗi, đang thử lại với SQL đã sửa.")
            result = run_sql(sql)
            result["error"] = None
            if progress:
                progress(f"Truy vấn xong: {result['row_count']} dòng kết quả.")
            return result
        except Exception as error:
            error_hint = f"{type(error).__name__}: {error}"
            logger.warning("run_data_query attempt %d failed: %s", attempt + 1, error_hint)
    return {"sql": error_hint and "(SQL generation/exec failed)", "columns": [], "rows": [], "row_count": 0, "truncated": False, "error": error_hint}


def should_load_default_dataset(message: str) -> bool:
    normalized = message.lower()
    if any(term in normalized for term in REMEMBER_TERMS):
        return False
    data_terms = (
        "analytics", "csv", "data", "dataset", "event", "event_log", "parquet", "query", "sql", "table",
        "bảng", "bao nhiêu", "click", "dòng", "dữ liệu", "lọc", "phân tích", "thống kê", "tính", "tỉ lệ",
        "tỷ lệ", "user",
    )
    return any(term in normalized for term in data_terms)


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

        # Long-term memory: recall facts this user taught the agent in ANY past session.
        long_term_facts = recall_long_term(actor_id, message)
        if progress and long_term_facts:
            progress(f"Đã nhớ lại {len(long_term_facts)} điều đã học từ các phiên trước.")

        try:
            create_memory_event(actor_id, effective_session_id, "user", message)
            if progress and memory_enabled():
                progress("Đã lưu message mới vào memory của session.")
        except Exception:
            logger.exception("create_memory_event(user) failed")

        # If the user explicitly asks the agent to remember something, persist it
        # immediately as a long-term fact (survives across sessions).
        if wants_to_remember(message) and remember_long_term(actor_id, [message]):
            if progress:
                progress("Đã ghi nhớ dài hạn yêu cầu của bạn.")

        # Daily-new-user-in-a-month report → compute here, then hand off to the
        # separate email agent to email the result to the configured recipient.
        if is_daily_new_user_email_request(message):
            email_result = handle_daily_new_user_email(message, progress=progress)
            try:
                create_memory_event(actor_id, effective_session_id, "assistant", email_result.get("response", ""))
            except Exception:
                logger.exception("create_memory_event(assistant) failed for daily-new-user email")
            email_result["session_id"] = effective_session_id
            email_result["actor_id"] = actor_id
            return email_result

        file_context = []
        if progress:
            progress("Đang kiểm tra file upload đi kèm.")
        if file_ids:
            file_context = load_file_context([str(file_id) for file_id in file_ids])
            if progress:
                progress(f"Đã đọc {len(file_context)} file upload làm context.")

        rows: list[dict[str, Any]] = []
        executed_query: dict[str, Any] | None = None
        # NOTE: Home Page click-rate questions are no longer special-cased — they go
        # through the normal DuckDB SQL path below like any other analytics question.
        needs_data = not file_context and should_load_default_dataset(message)
        if needs_data and DATA_SOURCE == "parquet":
            # Run a REAL SQL query over the whole dataset via DuckDB.
            executed_query = run_data_query(message, memory_context, long_term_facts, progress)
            rows = executed_query.get("rows", [])
            if executed_query.get("error"):
                # Fall back to a raw sample so the model still has some grounding.
                if progress:
                    progress("Truy vấn SQL thất bại; lấy tạm sample rows để tham chiếu.")
                try:
                    rows = fetch_rows(payload)
                except Exception:
                    logger.exception("fallback fetch_rows failed")
        elif needs_data:
            # Non-parquet (legacy Supabase) path: keep the sample-row behaviour.
            if progress:
                progress("Câu hỏi cần dữ liệu; đang lấy rows từ nguồn dữ liệu.")
            rows = fetch_rows(payload)
        elif progress and not file_context:
            progress("Câu hỏi không yêu cầu dataset; bỏ qua bước đọc dữ liệu.")

        # ------------------------------------------------------------------ #
        # [DISABLED] Home Page click-rate % IMAGE output.
        # Tạm thời bỏ phần render ảnh % cho từng sản phẩm trên màn hình Home.
        # Câu hỏi CTR giờ được trả lời bằng số liệu qua đường SQL ở trên.
        # Để bật lại: bỏ comment khối dưới + dòng attach_homepage_result_image,
        # khôi phục "result_assets"/"homepage_click_rate" trong context, và xem
        # config ảnh trong app/config.py (ASSET_DIR, RESULTS_DIR, HOMEPAGE_*).
        # ------------------------------------------------------------------ #
        homepage_context: dict[str, Any] | None = None
        # if is_homepage_click_rate_question(message):
        #     if progress:
        #         progress("Phát hiện câu hỏi CTR Trang chủ; đang tính tỉ lệ click từ Parquet.")
        #     homepage_context = homepage_click_rate_context(result_id, message)
        #     if progress:
        #         progress("Đã render ảnh kết quả mới với value đỏ được cập nhật.")

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
                "long_term_memory": {
                    "scope": "cross_session_same_actor",
                    "facts": long_term_facts,
                    "instruction": "These are facts and logic this user taught the agent in previous sessions. Apply them when relevant. If they conflict with newer instructions in this session, prefer the newer one.",
                },
                # [DISABLED] Home Page % image output — tạm thời bỏ, không gửi asset ảnh nữa.
                # "result_assets": {
                #     "homepage_click_rate_image": homepage_context["image_url"] if homepage_context else HOMEPAGE_RESULT_IMAGE_URL,
                # },
                # "homepage_click_rate": homepage_context,
                "data_source": {
                    "type": DATA_SOURCE,
                    "parquet": parquet_summary(),
                    "supabase_enabled": DATA_SOURCE == "supabase",
                },
                "executed_query": (
                    {
                        "engine": "duckdb",
                        "sql": executed_query.get("sql"),
                        "columns": executed_query.get("columns"),
                        "row_count": executed_query.get("row_count"),
                        "truncated": executed_query.get("truncated"),
                        "rows": executed_query.get("rows"),
                        "error": executed_query.get("error"),
                        "instruction": "These rows are the AUTHORITATIVE result of running a query on the full dataset. Base your numbers ONLY on these rows. Do NOT show this SQL to the user — instead show ONE equivalent SAMPLE query written in PYTHON only (e.g. using duckdb or pandas) under the label 'Python query:'. If 'error' is set, explain the query failed and what is missing — do not fabricate numbers.",
                    }
                    if executed_query is not None
                    else None
                ),
                "query_rows": {"table": SUPABASE_TABLE, "row_count": len(rows), "rows": rows},
            },
        )
        answer = clean_assistant_markdown(answer)
        # [DISABLED] không đính kèm ảnh % Home Page vào câu trả lời nữa.
        # answer = attach_homepage_result_image(answer, message, homepage_context["image_url"] if homepage_context else None)
        if progress:
            progress("Hoàn tất câu trả lời.")
        try:
            create_memory_event(actor_id, effective_session_id, "assistant", answer)
        except Exception:
            logger.exception("create_memory_event(assistant) failed")

        # Let the platform distil long-term facts from this turn's events
        # (best-effort; complements the explicit "remember" path above).
        if long_term_enabled():
            generate_long_term_from_session(actor_id, effective_session_id)
            if progress:
                progress("Đã cập nhật long-term memory từ hội thoại.")

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
            "long_term_memory_enabled": long_term_enabled(),
            "long_term_facts_used": len(long_term_facts),
            "data_source": DATA_SOURCE,
            "parquet_path": str(PARQUET_PATH) if DATA_SOURCE == "parquet" else None,
            "executed_sql": executed_query.get("sql") if executed_query else None,
            "query_error": executed_query.get("error") if executed_query else None,
        }
    except Exception as error:
        logger.exception("analyze_payload failed")
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
    try:
        result = analyze_payload(payload_with_job_id, session_id=job_id, progress=lambda message: add_job_process(job_id, message))
        status = "completed" if result.get("status") == "success" else "error"
    except Exception as error:
        # Never leave a job stuck in "inprogess" — the UI would spin until its own
        # poll timeout. Always land on a terminal status with a usable message.
        logger.exception("run_chat_job failed for %s", job_id)
        result = {
            "status": "error",
            "message": "Agent gặp lỗi khi xử lý yêu cầu. Vui lòng thử lại.",
            "detail": type(error).__name__,
            "timestamp": datetime.now().isoformat(),
        }
        status = "error"
        add_job_process(job_id, "Đã xảy ra lỗi trong quá trình xử lý.")
    update_job(job_id, {"status": status, "result": result, "updated_at": datetime.now().isoformat()})
