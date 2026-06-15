import json
import re
from typing import Any

from .config import LLM_MODEL, PROMPT_PATH, llm, logger
from .query_engine import SCHEMA_TEXT


def _extract_sql(text: str) -> str:
    text = (text or "").strip()
    # Prefer a strict JSON object {"sql": "..."}
    try:
        data = json.loads(text)
        if isinstance(data, dict) and data.get("sql"):
            return str(data["sql"]).strip()
    except Exception:
        pass
    # Fenced ```sql ... ``` block
    fence = re.search(r"```(?:sql)?\s*(.+?)```", text, re.IGNORECASE | re.DOTALL)
    if fence:
        return fence.group(1).strip()
    # First SELECT/WITH statement onward
    match = re.search(r"(?is)\b(with|select)\b.*", text)
    if match:
        return match.group(0).strip()
    return text


def generate_sql(message: str, memory_context: list | None = None, long_term_facts: list | None = None, error_hint: str = "") -> str:
    """Ask the LLM to produce a single read-only DuckDB SQL query for the question."""
    system = (
        "You translate an analytics question into ONE read-only DuckDB SQL query.\n"
        "Rules:\n"
        "- Output ONLY a JSON object: {\"sql\": \"<query>\"}. No prose, no markdown.\n"
        "- A single SELECT or WITH statement. No DDL/DML, no semicolons, no comments.\n"
        "- Query the view named event_log. Keep results small (GROUP BY + ORDER BY + LIMIT).\n"
        "- Use COUNT(DISTINCT user_id) for unique users. Normalize OS with LOWER(os).\n"
        "- Read metadata fields with json_extract_string(metadata, '$.key').\n\n"
        f"{SCHEMA_TEXT}"
    )
    hints = []
    if long_term_facts:
        hints.append("User long-term logic/definitions to honor: " + json.dumps(long_term_facts, ensure_ascii=False))
    if memory_context:
        hints.append("Recent conversation (for metric definitions taught this session): " + json.dumps(memory_context[-6:], ensure_ascii=False))
    if error_hint:
        hints.append("The previous query failed with this error, fix it: " + error_hint)
    user = json.dumps({"question": message, "hints": hints}, ensure_ascii=False)
    completion = llm.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0,
    )
    sql = _extract_sql(completion.choices[0].message.content or "")
    logger.info("generate_sql -> %s", sql.replace("\n", " ")[:300])
    return sql


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
