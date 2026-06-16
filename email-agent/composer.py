"""Compose the email subject + body from a daily-new-user report.

Primary path: ask the LLM (openai/gpt-oss-20b) to write a clean Vietnamese
business email from the structured data. If the LLM is disabled or fails for
any reason, fall back to a deterministic template so the agent never breaks.
"""

import json

from config import EMAIL_USE_LLM, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, logger

_MONTHS_VI = {
    1: "01", 2: "02", 3: "03", 4: "04", 5: "05", 6: "06",
    7: "07", 8: "08", 9: "09", 10: "10", 11: "11", 12: "12",
}


def _format_rows_table(rows: list[dict]) -> str:
    """Plain-text 'date — count' lines, robust to varied column names."""
    lines = []
    for row in rows:
        day = row.get("reg_date") or row.get("day") or row.get("date") or ""
        count = (
            row.get("new_users")
            if row.get("new_users") is not None
            else row.get("count")
        )
        lines.append(f"  - Ngày {day}: {count} new user")
    return "\n".join(lines) if lines else "  (không có dữ liệu)"


def _template(report: dict) -> tuple[str, str]:
    month = report.get("month")
    year = report.get("year")
    rows = report.get("rows") or []
    total = report.get("total_new_users")
    if total is None:
        total = sum((r.get("new_users") or r.get("count") or 0) for r in rows)

    mm = _MONTHS_VI.get(int(month), str(month)) if month else "?"
    subject = f"[ZaloPay Analytics] Daily New User — Tháng {mm}/{year}"
    body = (
        f"Kính gửi anh/chị,\n\n"
        f"Dưới đây là báo cáo số lượng người dùng mới (new user) theo từng ngày "
        f"trong tháng {mm}/{year}:\n\n"
        f"{_format_rows_table(rows)}\n\n"
        f"Tổng new user trong tháng: {total}\n"
        f"Số ngày có dữ liệu: {len(rows)}\n\n"
        f"Email này được gửi tự động bởi ZaloPay Analytics Agent.\n"
        f"Trân trọng."
    )
    return subject, body


def _compose_with_llm(report: dict) -> tuple[str, str]:
    from openai import OpenAI

    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    system = (
        "Bạn là trợ lý soạn email báo cáo nội bộ cho team ZaloPay Analytics. "
        "Viết email tiếng Việt, lịch sự, ngắn gọn, chuyên nghiệp. "
        "Trả về DUY NHẤT một JSON object: {\"subject\": \"...\", \"body\": \"...\"}. "
        "Không markdown, không giải thích. Body là plain text, có chào hỏi, "
        "tóm tắt số liệu daily new user theo từng ngày và tổng tháng. "
        "QUAN TRỌNG: dùng nguyên các giá trị ngày ('date') và số ('new_users') "
        "trong dữ liệu, KHÔNG tự đổi định dạng ngày, KHÔNG bịa thêm số liệu. "
        "Ký tên cuối email là 'ZaloPay Analytics Agent' — KHÔNG dùng tên người thật."
    )
    user = json.dumps({"report": report}, ensure_ascii=False)
    completion = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
    )
    content = (completion.choices[0].message.content or "").strip()
    # Tolerate a ```json fence if the model adds one.
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
    data = json.loads(content)
    subject = str(data["subject"]).strip()
    body = str(data["body"]).strip()
    if not subject or not body:
        raise ValueError("LLM returned empty subject/body")
    return subject, body


def compose_email(report: dict) -> tuple[str, str]:
    """Return (subject, body). Uses LLM when enabled, template otherwise/on error."""
    if EMAIL_USE_LLM and LLM_API_KEY:
        try:
            subject, body = _compose_with_llm(report)
            logger.info("Composed email via LLM (%s)", LLM_MODEL)
            return subject, body
        except Exception as error:
            logger.warning("LLM compose failed (%s); using template fallback", type(error).__name__)
    return _template(report)
