"""In-process matcher for Excel reference materials.

Why this module exists
----------------------
Excel sources are fully structured: header row + data rows. Running them
through a heavy QA backend (MoDora or a hot-tree / LLM service) spends LLM
tokens just to re-discover a structure that is already machine-readable, and
worse, the LLM will miss rows when a sheet is long. For the contest SLA
(≤ 90 s / template, ≥ 80 % accuracy) we short-circuit the Excel channel with
deterministic header-to-header matching and only fall back to the LLM when
matching fails.

Two public surfaces
-------------------
1. ``build_index(excel_paths)`` — load every sheet once per request.
2. ``extract_parent_entities(sheets, parent_headers)`` — gather distinct
   parent-value tuples to feed the "first fill" step in ``service.py``.
3. ``lookup_child_value(sheets, parent_values, child_header)`` — given a row
   whose parent columns are already filled, try to resolve the child cell's
   value directly from an Excel source.

All matching is done on ``_norm``-ised strings (lower-cased, whitespace and
common punctuation stripped) so "城市" / "城 市" / "City" collapse to a
comparable key.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class SheetIndex:
    source_path: str
    sheet_name: str
    raw_headers: List[str]     # original header text, preserved for reporting
    headers: List[str]         # _norm-ised for matching
    rows: List[List[str]]      # all non-empty data rows as strings


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
# ASCII + common CJK punctuation — we strip anything that is decoration rather
# than semantically meaningful for header / value equality.
_PUNCT_RE = re.compile(r"[()\[\]{}:,.;/\\·\-_、,。:;()【】《》<>]")


def _norm(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = _PUNCT_RE.sub("", text)
    text = _WS_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Date helpers (for range filters)
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(
    r"(\d{4})[\-/年.](\d{1,2})[\-/月.](\d{1,2})"
)


def _parse_date(value: Any) -> Optional[str]:
    """Try to extract a YYYY-MM-DD string from *value*.

    Returns ``None`` if no recognisable date pattern is found.
    """
    if value is None:
        return None
    m = _DATE_RE.search(str(value))
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


# ---------------------------------------------------------------------------
# Row-level filtering (P1)
# ---------------------------------------------------------------------------

def apply_row_filters(
    sheets: List[SheetIndex],
    filters: List[Dict[str, str]],
) -> List[SheetIndex]:
    """Return copies of *sheets* with rows narrowed by *filters*.

    Each filter dict has one of two forms:

    - ``{"column": "城市", "value": "德州市"}`` — substring / exact match
      (normalised, case-insensitive).
    - ``{"column": "日期", "start": "2020-07-01", "end": "2020-08-31"}``
      — inclusive date-range comparison on the raw cell text.

    Filters are ANDed: a row must pass **every** filter to survive.
    If *filters* is empty the original sheets are returned unchanged.
    """
    if not filters:
        return sheets

    out: List[SheetIndex] = []
    for sheet in sheets:
        # Resolve filter column indices within this sheet.
        resolved: List[tuple] = []
        for f in filters:
            col_name = f.get("column", "")
            col_idx = _find_column(sheet, col_name)
            if col_idx is None:
                # This sheet doesn't have the filter column — skip filter
                # (the sheet might still be useful for other columns).
                continue
            if "value" in f:
                resolved.append(("eq", col_idx, _norm(f["value"])))
            elif "start" in f or "end" in f:
                resolved.append(("range", col_idx, f.get("start", ""), f.get("end", "9999-12-31")))
        if not resolved:
            # None of the filters apply to this sheet → keep all rows.
            out.append(sheet)
            continue

        kept: List[List[str]] = []
        for row in sheet.rows:
            ok = True
            for kind, cidx, *args in resolved:
                cell = row[cidx] if cidx < len(row) else ""
                if kind == "eq":
                    if args[0] not in _norm(cell):
                        ok = False
                        break
                elif kind == "range":
                    d = _parse_date(cell)
                    if d is None:
                        ok = False
                        break
                    if d < args[0] or d > args[1]:
                        ok = False
                        break
            if ok:
                kept.append(row)
        logger.info(
            "apply_row_filters: sheet %s:%s  %d -> %d rows",
            sheet.source_path, sheet.sheet_name,
            len(sheet.rows), len(kept),
        )
        out.append(SheetIndex(
            source_path=sheet.source_path,
            sheet_name=sheet.sheet_name,
            raw_headers=sheet.raw_headers,
            headers=sheet.headers,
            rows=kept,
        ))
    return out


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def build_index(excel_paths: List[str]) -> List[SheetIndex]:
    """Load headers + rows for every sheet in every Excel path.

    Returns an empty list if ``excel_paths`` is empty. Failing workbooks are
    logged and skipped; one bad file does not poison the rest.
    """
    if not excel_paths:
        return []
    import openpyxl

    out: List[SheetIndex] = []
    for path in excel_paths:
        try:
            wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
        except Exception:
            logger.exception("excel_matcher: failed to open %s", path)
            continue
        try:
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows_iter = ws.iter_rows(values_only=True)
                try:
                    first = next(rows_iter)
                except StopIteration:
                    continue
                raw_headers = ["" if v is None else str(v).strip() for v in first]
                headers = [_norm(h) for h in raw_headers]
                rows: List[List[str]] = []
                for row in rows_iter:
                    row_vals = ["" if v is None else str(v).strip() for v in row]
                    if any(row_vals):
                        rows.append(row_vals)
                out.append(SheetIndex(
                    source_path=path,
                    sheet_name=sheet_name,
                    raw_headers=raw_headers,
                    headers=headers,
                    rows=rows,
                ))
        finally:
            try:
                wb.close()
            except Exception:
                pass
    logger.info("excel_matcher: indexed %d sheet(s) from %d file(s)",
                len(out), len(excel_paths))
    return out


# ---------------------------------------------------------------------------
# Column matching
# ---------------------------------------------------------------------------

def _find_column(sheet: SheetIndex, header: str) -> Optional[int]:
    """Return the column index whose header matches ``header`` (normalised).

    1. exact normalised equality
    2. substring either direction (handles "城市 (市级)" ↔ "城市")
    """
    target = _norm(header)
    if not target:
        return None
    for i, h in enumerate(sheet.headers):
        if h == target:
            return i
    for i, h in enumerate(sheet.headers):
        if h and (target in h or h in target):
            return i
    return None


# ---------------------------------------------------------------------------
# Parent-entity extraction
# ---------------------------------------------------------------------------

def extract_parent_entities(
    sheets: List[SheetIndex],
    parent_headers: List[str],
) -> List[List[str]]:
    """Collect distinct parent-value combinations seen in any sheet.

    - Only sheets that expose *all* parent headers contribute rows.
    - The returned values are the **raw** (non-normalised) cell strings so the
      template reads naturally ("德州市" rather than "德州市").
    - Dedup key is the tuple of normalised values.
    """
    if not parent_headers or not sheets:
        return []
    seen: set = set()
    out: List[List[str]] = []
    for sheet in sheets:
        cols = [_find_column(sheet, h) for h in parent_headers]
        if any(c is None for c in cols):
            continue
        for row in sheet.rows:
            combo: List[str] = []
            for c in cols:
                combo.append(row[c] if c < len(row) else "")
            key = tuple(_norm(v) for v in combo)
            if not any(key):
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(combo)
    return out


# ---------------------------------------------------------------------------
# Child-value lookup
# ---------------------------------------------------------------------------

def lookup_child_value(
    sheets: List[SheetIndex],
    parent_values: Dict[str, str],
    child_header: str,
) -> Optional[Tuple[str, str]]:
    """Resolve ``child_header`` given a fully-bound ``parent_values`` row.

    Returns ``(raw_value, source_tag)`` on success, ``None`` if no sheet has a
    row whose parent columns match every ``parent_values`` entry AND a
    non-empty child column.

    The caller should treat an empty string as "no answer", matching the
    convention used by the LLM channels.
    """
    if not child_header or not sheets:
        return None

    norm_items: List[Tuple[str, str]] = [
        (_norm(k), _norm(v)) for k, v in parent_values.items() if v
    ]

    for sheet in sheets:
        child_col = _find_column(sheet, child_header)
        if child_col is None:
            continue
        # Resolve parent columns within this sheet; every parent must be present.
        parent_cols: List[Tuple[int, str]] = []
        ok = True
        for hname_norm, hval_norm in norm_items:
            found = None
            for i, h in enumerate(sheet.headers):
                if h == hname_norm or (hname_norm and h and (hname_norm in h or h in hname_norm)):
                    found = i
                    break
            if found is None:
                ok = False
                break
            parent_cols.append((found, hval_norm))
        if not ok:
            continue
        for row in sheet.rows:
            all_match = True
            for col, val_norm in parent_cols:
                actual = _norm(row[col]) if col < len(row) else ""
                if actual != val_norm:
                    all_match = False
                    break
            if not all_match:
                continue
            if child_col < len(row) and row[child_col]:
                return row[child_col], f"excel:{sheet.source_path}:{sheet.sheet_name}"
    return None
