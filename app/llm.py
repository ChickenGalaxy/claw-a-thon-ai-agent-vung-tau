import json
import re
from typing import Any

from .config import LLM_MODEL, PROMPT_PATH, llm


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
