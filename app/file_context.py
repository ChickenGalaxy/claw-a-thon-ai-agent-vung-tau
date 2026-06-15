import csv
from pathlib import Path

from pypdf import PdfReader

from .config import MAX_FILE_CONTEXT_CHARS
from .storage import load_upload_index


def summarize_csv(path: Path) -> str:
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle)
        rows = []
        for index, row in enumerate(reader):
            rows.append(row)
            if index >= 12:
                break
    return "CSV preview (first rows):\n" + "\n".join(", ".join(cell[:80] for cell in row) for row in rows)


def summarize_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages[:5]:
        parts.append(page.extract_text() or "")
    return "PDF text preview:\n" + "\n".join(parts)[:MAX_FILE_CONTEXT_CHARS]


def summarize_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")[:MAX_FILE_CONTEXT_CHARS]


def summarize_image(path: Path, filename: str, size: int) -> str:
    kb = round(size / 1024, 1)
    suffix = path.suffix.upper().lstrip(".")
    return (
        f"User uploaded an image file: '{filename}' ({suffix}, {kb} KB). "
        f"The current model is text-only and cannot view image contents directly. "
        f"Use the filename and the user's question to infer what data analysis is needed, "
        f"then query the event_log dataset accordingly."
    )


def load_file_context(file_ids: list[str]) -> list[dict[str, str]]:
    items = {item["id"]: item for item in load_upload_index()}
    contexts = []
    for file_id in file_ids:
        item = items.get(file_id)
        if not item:
            continue
        path = Path(item["path"])
        try:
            if item["kind"] == "csv":
                summary = summarize_csv(path)
            elif item["kind"] == "pdf":
                summary = summarize_pdf(path)
            elif item["kind"] == "text":
                summary = summarize_text(path)
            elif item["kind"] == "image":
                summary = summarize_image(path, item["filename"], item["size"])
            else:
                summary = f"Uploaded file: {item['filename']} ({item['size']} bytes)."
        except Exception as error:
            summary = f"Could not read {item['filename']}: {type(error).__name__}"
        contexts.append({"filename": item["filename"], "kind": item["kind"], "summary": summary})
    return contexts
