import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import UPLOAD_DIR, UPLOAD_INDEX


def ensure_upload_store() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    if not UPLOAD_INDEX.exists():
        UPLOAD_INDEX.write_text("[]", encoding="utf-8")


def load_upload_index() -> list[dict[str, Any]]:
    ensure_upload_store()
    return json.loads(UPLOAD_INDEX.read_text(encoding="utf-8"))


def save_upload_index(items: list[dict[str, Any]]) -> None:
    ensure_upload_store()
    UPLOAD_INDEX.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_filename(filename: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-._")
    return clean or "uploaded-file"


def file_kind(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".txt", ".md", ".json", ".log"}:
        return "text"
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
        return "image"
    return "binary"


def register_upload(filename: str, size: int, stored_path: Path) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "filename": filename,
        "path": str(stored_path),
        "size": size,
        "kind": file_kind(filename),
        "created_at": datetime.now().isoformat(),
    }
