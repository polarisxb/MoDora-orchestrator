"""Plain-text document readers.

Replaces the old "convert everything to PDF, then read with PyPDF2" pipeline.
Each file type is handled by its native library so tables / layout are preserved
as best as possible when fed into the LLM.

Public API
----------
read_document_text(path) -> str
    Dispatches by extension. Returns empty string on failure (with logged
    traceback) so a single bad file does not kill the entire pipeline.
"""
from __future__ import annotations

import logging
import os
from typing import List

logger = logging.getLogger(__name__)


def _read_md_or_txt(path: str) -> str:
    # try a few common encodings before falling back to lossy decode
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="replace")


def _read_docx(path: str) -> str:
    """Read a .docx preserving the relative order of paragraphs and tables."""
    from docx import Document  # lazy import
    from docx.oxml.ns import qn

    doc = Document(path)
    parts: List[str] = []
    w_t = qn("w:t")
    w_tr = qn("w:tr")
    w_tc = qn("w:tc")

    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            texts = child.findall(".//" + w_t)
            text = "".join(t.text or "" for t in texts).strip()
            if text:
                parts.append(text)
        elif tag == "tbl":
            rendered_rows: List[str] = []
            for tr in child.findall(".//" + w_tr):
                cells = tr.findall(".//" + w_tc)
                cell_texts: List[str] = []
                for tc in cells:
                    ts = tc.findall(".//" + w_t)
                    cell_texts.append("".join(t.text or "" for t in ts).strip())
                rendered_rows.append(" | ".join(cell_texts))
            if rendered_rows:
                parts.append("\n".join(rendered_rows))
    return "\n".join(parts)


def _read_xlsx(path: str) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    parts: List[str] = []
    try:
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            parts.append(f"--- Sheet: {sheet_name} ---")
            for row in ws.iter_rows(values_only=True):
                row_vals = [
                    str(v).strip() for v in row
                    if v is not None and str(v).strip()
                ]
                if row_vals:
                    parts.append(" | ".join(row_vals))
    finally:
        wb.close()
    return "\n".join(parts)


def _read_pdf(path: str) -> str:
    try:
        import fitz  # pymupdf
    except ImportError:
        logger.warning("pymupdf not installed; skipping PDF %s", path)
        return ""
    chunks: List[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            text = page.get_text("text")
            if text:
                chunks.append(text)
    return "\n".join(chunks)


_READERS = {
    ".md": _read_md_or_txt,
    ".markdown": _read_md_or_txt,
    ".txt": _read_md_or_txt,
    ".docx": _read_docx,
    ".xlsx": _read_xlsx,
    ".xls": _read_xlsx,
    ".xlsm": _read_xlsx,
    ".pdf": _read_pdf,
}


def read_document_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    reader = _READERS.get(ext)
    if reader is None:
        logger.warning("no reader for extension %s (%s)", ext, path)
        return ""
    try:
        return reader(path)
    except Exception:
        logger.exception("failed to read %s", path)
        return ""
