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
import threading
import unicodedata
from datetime import datetime

from .config import EMAIL_RECIPIENT, logger
from .query_engine import run_sql

# Basic email matcher — good enough to pull a recipient out of a chat message.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Pending "who should I email this to?" requests, keyed by actor+session. When the
# user asks to email something without giving a recipient, we stash what to send
# here and ask back; their next message (an email) completes it. The stored value
# is a dict describing the pending send, e.g.
#   {"kind": "daily_new_user", "message": "<original request>"}
#   {"kind": "generic", "subject": "...", "body": "..."}
_PENDING: dict[str, dict] = {}
_PENDING_LOCK = threading.Lock()

# Last ANALYSIS result (Markdown) per actor+session. Email-send always uses this —
# i.e. the actual analysis, never a later conversational/offer message.
_LAST_ANALYSIS: dict[str, str] = {}
_LAST_ANALYSIS_LOCK = threading.Lock()


def set_last_analysis(actor_id: str, session_id: str, markdown: str) -> None:
    with _LAST_ANALYSIS_LOCK:
        _LAST_ANALYSIS[f"{actor_id}:{session_id}"] = markdown


def get_last_analysis(actor_id: str, session_id: str) -> str | None:
    with _LAST_ANALYSIS_LOCK:
        return _LAST_ANALYSIS.get(f"{actor_id}:{session_id}")


def extract_email(message: str) -> str | None:
    """Return the first email address found in the message, or None."""
    match = _EMAIL_RE.search(message or "")
    return match.group(0) if match else None


def extract_emails(message: str) -> list[str]:
    """Return ALL distinct email addresses found in the message, in order."""
    seen, out = set(), []
    for m in _EMAIL_RE.findall(message or ""):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _pending_key(actor_id: str, session_id: str) -> str:
    return f"{actor_id}:{session_id}"


def set_pending_email(actor_id: str, session_id: str, pending: dict) -> None:
    with _PENDING_LOCK:
        _PENDING[_pending_key(actor_id, session_id)] = pending


def pop_pending_email(actor_id: str, session_id: str) -> dict | None:
    """Return and clear the stashed pending email for this session, if any."""
    with _PENDING_LOCK:
        return _PENDING.pop(_pending_key(actor_id, session_id), None)


def peek_pending_email(actor_id: str, session_id: str) -> bool:
    with _PENDING_LOCK:
        return _pending_key(actor_id, session_id) in _PENDING

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


def _build_report_markdown(month: int, year: int, report_rows: list[dict], total: int) -> str:
    """Markdown report (title + summary + table) shared by the UI, email HTML, and PDF."""
    lines = [
        f"### Báo cáo Daily New User — Tháng {month:02d}/{year}",
        "",
        f"Tổng new user trong tháng: **{total:,}**  •  Số ngày có new user: **{len(report_rows)}**",
        "",
        "| Ngày đăng ký | New users |",
        "|---|---:|",
    ]
    for r in report_rows:
        lines.append(f"| {r['date']} | {r['new_users']:,} |")
    if not report_rows:
        lines.append("| (không có dữ liệu) | 0 |")
    return "\n".join(lines)


def build_daily_new_user_report(message: str, progress=None) -> str:
    """Compute the daily-new-user report for the requested month → Markdown (no email)."""
    now = datetime.now()
    year, month = parse_month_year(message, now)
    if progress:
        progress(f"Đang tính báo cáo daily new user tháng {month:02d}/{year}.")
    computed = compute_daily_new_users(year, month)
    report_rows = [
        {"date": _fmt_yymmdd(r.get("reg_date")), "new_users": int(r.get("new_users") or 0)}
        for r in computed["rows"]
    ]
    if progress:
        progress(f"Đã tính xong: {len(report_rows)} ngày có new user, tổng {computed['total_new_users']} user.")
    return _build_report_markdown(month, year, report_rows, computed["total_new_users"])


def handle_daily_new_user_email(message: str, progress=None, recipient=None) -> dict:
    """Full flow: parse month → compute → email (HTML + PDF) → return UI dict.

    ``recipient`` may be a single address or a list; defaults to EMAIL_RECIPIENT.
    """
    # Import here to avoid a circular import at module load (email_output is light).
    from .email_output import handle_email_output

    if isinstance(recipient, list):
        recipients = [r.strip() for r in recipient if r and r.strip()]
    else:
        recipients = [(recipient or EMAIL_RECIPIENT or "").strip()]
    recipients = [r for r in recipients if r]

    now = datetime.now()
    year, month = parse_month_year(message, now)
    if progress:
        progress(f"Phát hiện yêu cầu báo cáo daily new user tháng {month:02d}/{year}.")

    computed = compute_daily_new_users(year, month)
    rows = computed["rows"]
    total = computed["total_new_users"]
    if progress:
        progress(f"Đã tính xong: {len(rows)} ngày có new user, tổng {total} user.")

    report_rows = [
        {"date": _fmt_yymmdd(r.get("reg_date")), "new_users": int(r.get("new_users") or 0)}
        for r in rows
    ]
    report_md = _build_report_markdown(month, year, report_rows, total)

    if progress:
        progress(f"Đang định dạng & gửi báo cáo tới {', '.join(recipients)}.")
    email_out = handle_email_output(
        report_md, recipient=recipients,
        subject=f"[ZaloPay Analytics] Daily New User — Tháng {month:02d}/{year}",
        progress=progress,
    )
    email_result = email_out.get("email", {})
    sent_note = email_out.get("response", "")

    response = f"{report_md}\n\n{sent_note}"

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
