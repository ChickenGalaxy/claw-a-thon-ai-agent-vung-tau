"""Daily-new-user-per-month report + email trigger.

When the user asks the analytics agent to "tính daily new user trong tháng ...",
this module:
  1. Detects the intent and parses which month/year (current, specified, or last month).
  2. Computes daily new users deterministically via DuckDB SQL on the Parquet.
     "New user on day D" = a user whose registration date (first 6 chars of
     user_id, YYMMDD) equals D. Counted distinct per registration day.
  3. Calls the separate email agent to send the report to EMAIL_RECIPIENT.
  4. Returns a success dict (with a human-friendly Vietnamese summary) for the UI.
"""

import calendar
import re
import unicodedata
from datetime import datetime

from .config import EMAIL_RECIPIENT, logger
from .email_client import send_report_email
from .query_engine import run_sql

_MONTH_NAMES_VI = {
    "một": 1, "hai": 2, "ba": 3, "tư": 4, "bốn": 4, "năm": 5, "sáu": 6,
    "bảy": 7, "tám": 8, "chín": 9, "mười": 10, "mười một": 11, "mười hai": 12,
}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def is_daily_new_user_email_request(message: str) -> bool:
    """True when the message asks for a daily-new-user-in-a-month report (→ email)."""
    norm = _strip_accents(message.lower())
    has_new_user = ("new user" in norm) or ("nguoi dung moi" in norm) or ("user moi" in norm)
    has_month = ("thang" in norm) or ("month" in norm)
    has_daily = any(k in norm for k in ("daily", "theo ngay", "hang ngay", "moi ngay", "tung ngay", "per day"))
    return has_new_user and has_month and (has_daily or "daily new user" in norm)


def parse_month_year(message: str, now: datetime | None = None) -> tuple[int, int]:
    """Return (year, month). Handles 'tháng này/hiện tại', 'tháng trước',
    'tháng N', 'tháng N/YYYY', 'tháng N năm YYYY'. Defaults to the current month."""
    now = now or datetime.now()
    norm = _strip_accents(message.lower())

    if any(k in norm for k in ("thang nay", "thang hien tai", "this month", "thang hientai")):
        return now.year, now.month
    if any(k in norm for k in ("thang truoc", "thang vua roi", "last month", "thang qua")):
        month = now.month - 1 or 12
        year = now.year if now.month != 1 else now.year - 1
        return year, month

    # "thang 5/2026", "thang 05 nam 2026", "thang 5 2026", "month 5"
    match = re.search(r"thang\s*(\d{1,2})(?:\s*[/\-]\s*(\d{4})|\s*nam\s*(\d{4})|\s+(\d{4}))?", norm)
    if not match:
        match = re.search(r"month\s*(\d{1,2})(?:\s*[/\-]\s*(\d{4}))?", norm)
    if match:
        month = int(match.group(1))
        year = next((int(g) for g in match.groups()[1:] if g), now.year)
        if 1 <= month <= 12:
            return year, month

    return now.year, now.month


def _build_sql(year: int, month: int) -> str:
    yy = year % 100
    last_day = calendar.monthrange(year, month)[1]
    start = f"{yy:02d}{month:02d}01"
    end = f"{yy:02d}{month:02d}{last_day:02d}"
    return (
        "SELECT substr(user_id, 1, 6) AS reg_date, "
        "COUNT(DISTINCT user_id) AS new_users "
        "FROM event_log "
        f"WHERE substr(user_id, 1, 6) BETWEEN '{start}' AND '{end}' "
        "GROUP BY reg_date ORDER BY reg_date"
    )


def compute_daily_new_users(year: int, month: int) -> dict:
    """Run the deterministic SQL and return {rows, total_new_users, sql}."""
    sql = _build_sql(year, month)
    result = run_sql(sql, max_rows=40)
    rows = result.get("rows", [])
    total = sum(int(r.get("new_users") or 0) for r in rows)
    return {"rows": rows, "total_new_users": total, "sql": sql}


def _fmt_yymmdd(value: str) -> str:
    """260501 -> 2026-05-01 for readability."""
    s = str(value)
    if len(s) == 6 and s.isdigit():
        return f"20{s[0:2]}-{s[2:4]}-{s[4:6]}"
    return s


def handle_daily_new_user_email(message: str, progress=None) -> dict:
    """Full flow: parse month → compute → email → return success dict for the UI."""
    now = datetime.now()
    year, month = parse_month_year(message, now)
    if progress:
        progress(f"Phát hiện yêu cầu báo cáo daily new user tháng {month:02d}/{year}.")

    computed = compute_daily_new_users(year, month)
    rows = computed["rows"]
    total = computed["total_new_users"]
    if progress:
        progress(f"Đã tính xong: {len(rows)} ngày có new user, tổng {total} user.")

    # Pre-format dates to YYYY-MM-DD so the email composer never has to parse the
    # YYMMDD user_id prefix (which it tends to misread).
    report_rows = [
        {"date": _fmt_yymmdd(r.get("reg_date")), "new_users": int(r.get("new_users") or 0)}
        for r in rows
    ]
    report = {
        "metric": "daily_new_user",
        "month": month,
        "year": year,
        "rows": report_rows,
        "total_new_users": total,
        "recipient": EMAIL_RECIPIENT,
    }

    if progress:
        progress(f"Đang gọi email agent để gửi báo cáo tới {EMAIL_RECIPIENT}.")
    email_result = send_report_email(report, recipient=EMAIL_RECIPIENT)
    email_ok = email_result.get("status") == "sent"

    preview_lines = [f"  • {_fmt_yymmdd(r.get('reg_date'))}: {r.get('new_users')} new user" for r in rows[:10]]
    preview = "\n".join(preview_lines) if preview_lines else "  (không có new user nào trong tháng này)"
    more = f"\n  … và {len(rows) - 10} ngày khác" if len(rows) > 10 else ""

    if email_ok:
        transport = email_result.get("transport", "?")
        sent_note = (
            f"✅ Đã gửi email báo cáo tới {EMAIL_RECIPIENT}"
            + (" (chế độ MOCK — email được ghi log, chưa gửi thật)." if transport == "mock" else ".")
        )
    else:
        sent_note = (
            f"⚠️ Đã tính xong báo cáo nhưng KHÔNG gửi được email: "
            f"{email_result.get('message') or email_result.get('detail')}"
        )

    response = (
        f"Báo cáo Daily New User — Tháng {month:02d}/{year}\n\n"
        f"Tổng new user trong tháng: {total}\n"
        f"Số ngày có new user: {len(rows)}\n\n"
        f"Chi tiết theo ngày đăng ký:\n{preview}{more}\n\n"
        f"{sent_note}"
    )

    return {
        "status": "success",
        "response": response,
        "intent": "daily_new_user_email",
        "month": month,
        "year": year,
        "total_new_users": total,
        "days_with_data": len(rows),
        "email": email_result,
        "executed_sql": computed["sql"],
        "timestamp": now.isoformat(),
    }
