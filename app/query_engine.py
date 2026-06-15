"""Read-only SQL execution over the bundled Parquet dataset using DuckDB.

The LLM generates a DuckDB SQL query against a view named ``event_log`` (backed
by ``data/event_log.parquet``). This module validates the query is a single
read-only SELECT/WITH statement, executes it, caps the result size, and returns
JSON-serializable rows that get fed back to the LLM for a natural-language answer.
"""

import datetime
import decimal
import re
import threading

import duckdb

from .config import PARQUET_PATH, logger

_LOCK = threading.Lock()
_CON = None

# Statement-level keywords that must never appear (no DDL/DML/side effects).
_FORBIDDEN = re.compile(
    r"\b(attach|copy|install|load|pragma|create|insert|update|delete|drop|alter|"
    r"export|import|call|set|truncate|grant|revoke|vacuum|checkpoint)\b",
    re.IGNORECASE,
)

# Authoritative schema description handed to the SQL generator.
SCHEMA_TEXT = """Table (DuckDB view): event_log  -- backed by data/event_log.parquet (~1.19M rows)
Columns:
  ymd               INTEGER   -- event date as YYYYMMDD (e.g. 20260419). Range 20260301..20260531.
  timestamp         VARCHAR   -- ISO8601 with +07:00, e.g. '2026-04-19T20:55:36.126+07:00'
  user_id           VARCHAR   -- first 6 chars = registration date YYMMDD (e.g. '260508AAAAA9283' -> 2026-05-08)
  event_id          VARCHAR   -- event code, format 'AAAA.xxx'. Key codes:
                              --   'AAAA.005' = load Home Page (denominator for Home click-rate)
                              --   'AAAA.020' = click a service icon on Home Page (uses app_profile_name)
  os                VARCHAR   -- 'Android' / 'android' / 'ios' / NULL  -> normalize with LOWER(os)
  appver            VARCHAR   -- app version, e.g. '11.3.1'
  app_profile_id    VARCHAR   -- service id (string) for click events, may be NULL
  app_profile_name  VARCHAR   -- service display name for click events, may be NULL (e.g. 'Chuyển tiền')
  metadata          VARCHAR   -- JSON string. Extract with json_extract_string(metadata, '$.key')
  session_id        VARCHAR   -- numeric session id as string

DuckDB dialect notes:
- Query the view directly: FROM event_log
- Unique users: COUNT(DISTINCT user_id) (never COUNT(*))
- New users registered in a date range: substr(user_id,1,6) BETWEEN '260323' AND '260329' (YYMMDD)
- Read a metadata field: json_extract_string(metadata, '$.section')
- Home Page service click-rate: users with event_id='AAAA.020' (per app_profile_name) / users with event_id='AAAA.005'
- Filter by date: ymd BETWEEN 20260501 AND 20260531
- Always alias aggregates and keep results small (GROUP BY + ORDER BY + LIMIT)."""


def _connect():
    global _CON
    if _CON is None:
        con = duckdb.connect(database=":memory:")
        safe_path = str(PARQUET_PATH).replace("'", "''")
        con.execute(f"CREATE VIEW event_log AS SELECT * FROM read_parquet('{safe_path}')")
        _CON = con
    return _CON


def is_safe_select(sql: str) -> bool:
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        return False
    if ";" in statement:  # reject multiple statements
        return False
    if not re.match(r"(?is)^\s*(with|select)\b", statement):
        return False
    if _FORBIDDEN.search(statement):
        return False
    return True


def _jsonable(value):
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "ignore")
    return value


def run_sql(sql: str, max_rows: int = 200) -> dict:
    """Execute a read-only query and return {sql, columns, rows, row_count, truncated}.

    Raises ValueError for unsafe SQL; DuckDB exceptions propagate to the caller.
    """
    statement = sql.strip().rstrip(";").strip()
    if not is_safe_select(statement):
        raise ValueError("Only a single read-only SELECT/WITH query is allowed")
    wrapped = f"SELECT * FROM (\n{statement}\n) AS _agent_q LIMIT {int(max_rows)}"
    with _LOCK:
        con = _connect()
        cursor = con.execute(wrapped)
        columns = [desc[0] for desc in cursor.description]
        raw_rows = cursor.fetchall()
    rows = [{col: _jsonable(val) for col, val in zip(columns, row)} for row in raw_rows]
    truncated = len(rows) >= max_rows
    logger.info("run_sql ok: %d row(s)%s", len(rows), " (truncated)" if truncated else "")
    return {
        "sql": statement,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }
