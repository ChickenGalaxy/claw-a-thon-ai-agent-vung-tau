"""Render an assistant answer (Markdown) into HTML (for email) and PDF (download + attach).

The chat answer is Markdown with tables/headings/lists. We reproduce that as:
  - styled HTML matching the chat look (for the email body), and
  - a PDF built with fpdf2 + a bundled DejaVu font (full Vietnamese support).
"""

import re
from pathlib import Path

import markdown as _markdown

_FONT_DIR = Path(__file__).resolve().parent / "assets"
_FONT_REGULAR = _FONT_DIR / "DejaVuSans.ttf"
_FONT_BOLD = _FONT_DIR / "DejaVuSans-Bold.ttf"

# CSS mirrors the chat's assistant-message + .data-table styling (rounded card,
# header band, horizontal row lines, right-aligned numbers).
_EMAIL_CSS = """
  body { font-family: Arial, Helvetica, sans-serif; color:#1c1917; line-height:1.6; font-size:14px; margin:0; padding:4px 2px; }
  h1,h2,h3 { color:#0052cc; margin:18px 0 8px; }
  h1 { font-size:20px; } h2 { font-size:17px; } h3 { font-size:15px; }
  p { margin:8px 0; }
  .tbl-wrap { border:1px solid #d9d4cc; border-radius:12px; overflow:hidden; margin:14px 0; display:inline-block; max-width:100%; }
  table.data { border-collapse:collapse; width:100%; font-size:13px; }
  table.data th, table.data td { padding:9px 14px; border-bottom:1px solid #e7e2da; text-align:left; white-space:nowrap; }
  table.data thead th { background:#ebe7e1; font-weight:700; color:#1c1917; }
  table.data tbody tr:last-child td { border-bottom:0; }
  table.data .num { text-align:right; font-variant-numeric:tabular-nums; }
  code, pre { font-family:Menlo,Consolas,monospace; background:#f0ede8; border-radius:6px; }
  pre { padding:10px 12px; overflow:auto; }
  code { padding:1px 4px; }
  ul { margin:8px 0; padding-left:22px; }
  .footer { margin-top:20px; color:#8a8278; font-size:12px; }
"""


def answer_title(answer: str, fallback: str = "Kết quả phân tích") -> str:
    """Derive a short title from the first heading/line of the answer."""
    for line in (answer or "").splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:120]
    return fallback


def _esc(text: str) -> str:
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_html_table(header: list[str], rows: list[list[str]]) -> str:
    """A clean HTML table styled like the chat (numeric columns right-aligned)."""
    ncols = len(header)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    num_cols = _numeric_cols(header, rows)

    def cls(c):
        return ' class="num"' if c in num_cols else ""

    th = "".join(f"<th{cls(c)}>{_esc(_strip_inline(header[c]))}</th>" for c in range(ncols))
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td{cls(c)}>{_esc(_strip_inline(r[c]))}</td>" for c in range(ncols)) + "</tr>"
    return f'<div class="tbl-wrap"><table class="data"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _render_body_html(answer: str) -> str:
    """Render the answer to HTML: tables via our styled renderer, the rest via Markdown."""
    lines = (answer or "").splitlines()
    out, buf = [], []
    i, n = 0, len(lines)

    def flush_text():
        if buf:
            chunk = "\n".join(buf).strip()
            if chunk:
                out.append(_markdown.markdown(chunk, extensions=["fenced_code", "sane_lists", "nl2br"]))
            buf.clear()

    while i < n:
        line = lines[i]
        if _TABLE_ROW.match(line) and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            flush_text()
            header = _split_table_row(line)
            trows, j = [], i + 2
            while j < n and _TABLE_ROW.match(lines[j]):
                trows.append(_split_table_row(lines[j]))
                j += 1
            out.append(_render_html_table(header, trows))
            i = j
            continue
        buf.append(line)
        i += 1
    flush_text()
    return "\n".join(out)


def markdown_to_html(answer: str) -> str:
    """Convert the answer Markdown to an HTML fragment (kept for compatibility)."""
    return _render_body_html(answer)


def build_email_html(answer: str, title: str | None = None) -> str:
    """Full standalone HTML document for the email body."""
    body = _render_body_html(answer)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{_EMAIL_CSS}</style></head><body>"
        f"{body}"
        "<div class='footer'>Email này được gửi tự động bởi ZaloPay Analytics Agent.</div>"
        "</body></html>"
    )


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #

_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _split_table_row(line: str) -> list[str]:
    inner = line.strip().strip("|")
    return [c.strip() for c in inner.split("|")]


def _strip_inline(md: str) -> str:
    """Drop inline markdown markers + stray HTML so cells render cleanly."""
    md = re.sub(r"\*\*(.+?)\*\*", r"\1", md or "")
    md = re.sub(r"`(.+?)`", r"\1", md)
    md = re.sub(r"<\s*br\s*/?\s*>", " ", md, flags=re.IGNORECASE)  # data sometimes has <br/>
    md = re.sub(r"<[^>]+>", "", md)  # any other stray tags
    return md.strip()


def _is_num(text: str) -> bool:
    return bool(re.match(r"^[\s$€₫]*[-+]?[\d.,%]+\s*(pts|%)?\s*$", text or "")) and any(c.isdigit() for c in text)


def _numeric_cols(header: list[str], rows: list[list[str]]) -> set[int]:
    """Columns whose data cells are mostly numeric → right-aligned, like the chat."""
    ncols = len(header)
    nums = set()
    for c in range(ncols):
        vals = [r[c] for r in rows if c < len(r) and r[c].strip()]
        if vals and sum(_is_num(v) for v in vals) >= max(1, len(vals) * 0.6):
            nums.add(c)
    return nums


def markdown_to_pdf_bytes(answer: str, title: str | None = None) -> bytes:
    """Render the answer Markdown to a PDF (returns raw bytes)."""
    from fpdf import FPDF

    title = title or answer_title(answer)
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("DejaVu", "", str(_FONT_REGULAR))
    pdf.add_font("DejaVu", "B", str(_FONT_BOLD))
    pdf.add_page()

    pdf.set_font("DejaVu", "B", 15)
    pdf.set_text_color(0, 82, 204)
    pdf.multi_cell(0, 8, title)
    pdf.set_text_color(28, 25, 23)
    pdf.ln(2)

    lines = (answer or "").splitlines()
    i = 0
    n = len(lines)
    in_code = False
    code_buf: list[str] = []
    while i < n:
        line = lines[i]
        pdf.set_x(pdf.l_margin)  # always render blocks from the left margin

        # fenced code block
        if line.strip().startswith("```"):
            if in_code:
                pdf.set_font("DejaVu", "", 9)
                pdf.set_fill_color(240, 237, 232)
                pdf.multi_cell(0, 5, "\n".join(code_buf), fill=True)
                pdf.ln(1)
                code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # markdown table: a row line followed by a separator line
        if _TABLE_ROW.match(line) and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            header = _split_table_row(line)
            rows = []
            j = i + 2
            while j < n and _TABLE_ROW.match(lines[j]):
                rows.append(_split_table_row(lines[j]))
                j += 1
            _render_pdf_table(pdf, header, rows)
            i = j
            continue

        stripped = line.strip()
        if not stripped:
            pdf.ln(3)
            i += 1
            continue

        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            # Skip the first heading if it just repeats the PDF title.
            if _strip_inline(m.group(2)).strip() == title.strip():
                i += 1
                continue
            level = len(m.group(1))
            size = {1: 14, 2: 13, 3: 12}.get(level, 11)
            pdf.ln(1)
            pdf.set_font("DejaVu", "B", size)
            pdf.set_text_color(0, 82, 204)
            pdf.multi_cell(0, 6, _strip_inline(m.group(2)))
            pdf.set_text_color(28, 25, 23)
            i += 1
            continue

        # bullet list
        if re.match(r"^[-*]\s+", stripped):
            pdf.set_font("DejaVu", "", 11)
            pdf.multi_cell(0, 6, "  •  " + _strip_inline(re.sub(r"^[-*]\s+", "", stripped)))
            i += 1
            continue

        # paragraph (gather inline bold via fpdf markdown)
        pdf.set_font("DejaVu", "", 11)
        pdf.multi_cell(0, 6, stripped, markdown=True)
        i += 1

    out = pdf.output()
    return bytes(out)


def _render_pdf_table(pdf, header: list[str], rows: list[list[str]]) -> None:
    from fpdf.fonts import FontFace

    ncols = len(header)
    rows = [r + [""] * (ncols - len(r)) for r in rows]  # pad ragged rows
    num_cols = _numeric_cols(header, rows)
    col_align = tuple("RIGHT" if c in num_cols else "LEFT" for c in range(ncols))

    pdf.ln(1)
    pdf.set_font("DejaVu", "", 9)
    pdf.set_draw_color(217, 212, 204)  # light row separators, like the chat
    with pdf.table(
        first_row_as_headings=True,
        headings_style=FontFace(emphasis="BOLD", color=(28, 25, 23), fill_color=(235, 231, 225)),
        line_height=7,
        text_align=col_align,
        borders_layout="HORIZONTAL_LINES",
        cell_fill_color=(250, 248, 245),
        cell_fill_mode="ROWS",
    ) as table:
        hr = table.row()
        for h in header:
            hr.cell(_strip_inline(h))
        for r in rows:
            tr = table.row()
            for cell in r[:ncols]:
                tr.cell(_strip_inline(cell))
    pdf.ln(2)
