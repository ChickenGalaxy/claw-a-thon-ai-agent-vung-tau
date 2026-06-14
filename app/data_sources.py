from typing import Any

import psycopg
import pyarrow.compute as pc
import pyarrow.dataset as pyarrow_dataset
import pyarrow.parquet as pq
import requests
from psycopg import sql

from .config import (
    DATA_SOURCE,
    PARQUET_PATH,
    SUPABASE_KEY,
    SUPABASE_LIMIT,
    SUPABASE_SELECT,
    SUPABASE_TABLE,
    SUPABASE_URL,
)


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
        return {}
    allowed = {"event_id", "user_id", "ymd", "app_profile_name"}
    return {key: value for key, value in filters.items() if key in allowed and value not in (None, "")}


def selected_columns() -> list[str] | None:
    if SUPABASE_SELECT == "*":
        return None
    columns = [column.strip() for column in SUPABASE_SELECT.split(",") if column.strip()]
    return columns or None


def parquet_schema() -> dict[str, Any]:
    if not PARQUET_PATH.exists():
        raise RuntimeError(f"Parquet data file not found: {PARQUET_PATH}")
    metadata = pq.read_metadata(PARQUET_PATH)
    return {"columns": metadata.schema.names, "num_rows": metadata.num_rows}


def parquet_filter_expression(filters: dict[str, Any]):
    expression = None
    for key, value in filters.items():
        condition = pc.field(key) == value
        if key == "ymd":
            try:
                condition = pc.field(key) == int(value)
            except Exception:
                condition = pc.field(key) == value
        expression = condition if expression is None else expression & condition
    return expression


def fetch_rows_from_parquet(payload: dict[str, Any]) -> list[dict[str, Any]]:
    limit = min(int(payload.get("limit") or SUPABASE_LIMIT), 100)
    schema_info = parquet_schema()
    requested = payload.get("select")
    columns = None
    if requested and requested != "*":
        columns = [column.strip() for column in str(requested).split(",") if column.strip()]
    elif selected_columns():
        columns = selected_columns()
    if columns:
        columns = [column for column in columns if column in schema_info["columns"]]
    dataset = pyarrow_dataset.dataset(PARQUET_PATH, format="parquet")
    table = dataset.to_table(columns=columns, filter=parquet_filter_expression(safe_filters(payload)))
    if table.num_rows > limit:
        table = table.slice(0, limit)
    return table.to_pylist()


def parquet_value_counts(column: str, limit: int = 20) -> list[dict[str, Any]]:
    schema_info = parquet_schema()
    if column not in schema_info["columns"]:
        return []
    table = pyarrow_dataset.dataset(PARQUET_PATH, format="parquet").to_table(columns=[column])
    counts = pc.value_counts(table[column]).to_pylist()
    counts = sorted(counts, key=lambda item: item["counts"], reverse=True)[:limit]
    return [{"value": item["values"], "count": item["counts"]} for item in counts]


def parquet_summary() -> dict[str, Any]:
    if DATA_SOURCE != "parquet":
        return {}
    schema_info = parquet_schema()
    summary = {"path": str(PARQUET_PATH), **schema_info}
    for column in ("event_id", "app_profile_name", "ymd"):
        summary[f"top_{column}"] = parquet_value_counts(column, 10)
    return summary


def fetch_rows_from_rest(payload: dict[str, Any]) -> list[dict[str, Any]]:
    limit = min(int(payload.get("limit") or SUPABASE_LIMIT), 100)
    params: dict[str, Any] = {
        "select": str(payload.get("select") or SUPABASE_SELECT),
        "limit": str(limit),
    }
    for key, value in safe_filters(payload).items():
        params[key] = f"eq.{value}"
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
    limit = min(int(payload.get("limit") or SUPABASE_LIMIT), 100)
    columns = selected_columns()
    column_sql = sql.SQL("*") if not columns else sql.SQL(", ").join(sql.Identifier(column) for column in columns)
    query = sql.SQL("SELECT {columns} FROM {table}").format(
        columns=column_sql,
        table=sql.Identifier(SUPABASE_TABLE),
    )
    values: list[Any] = []
    filters = safe_filters(payload)
    if filters:
        clauses = []
        for key, value in filters.items():
            clauses.append(sql.SQL("{} = %s").format(sql.Identifier(key)))
            values.append(value)
        query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)
    query += sql.SQL(" LIMIT %s")
    values.append(limit)
    with psycopg.connect(SUPABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, values)
            column_names = [description[0] for description in cursor.description]
            return [dict(zip(column_names, row)) for row in cursor.fetchall()]
