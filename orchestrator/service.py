"""Orchestrator FastAPI service.

Two-phase workflow (matches the contest's 1x-ingest + 5x-process pattern):

    POST /ingest   — called once with up to 16 reference files. Excel files
                     are stored locally for deterministic matching. md /
                     txt / docx files are converted to PDF (LibreOffice)
                     and uploaded to MoDora, which runs OCR + CCTree in
                     the background; we block until each tree is ready.
                     All metadata lands in :mod:`ingest_registry`.

    POST /process  — called N times with just a blank template + a natural-
                     language requirement. References are resolved from the
                     registry populated by /ingest.

/process pipeline (per request):

    1.  Save template into a per-request temp dir.
    2.  Resolve reference docs from the registry (excel local paths,
        md_txt / word local paths for LLM reading, and the MoDora filenames
        for the /chat dispatch).
    3.  Parse template headers and (for Word) the paragraph before the table.
    4.  Ask LLM to classify each column as parent / child.
    5.  Extract parent entities. Excel goes through structural matching
        (``excel_matcher.extract_parent_entities``); md_txt / word go
        through LLM extraction IN PARALLEL. Results are deduplicated.
    6.  First fill: write parent entities into the template.
    7.  For each (data_row, child_col) try a direct Excel lookup first
        (``excel_matcher.lookup_child_value``); only cells Excel cannot
        resolve become questions for the MoDora channels.
    8.  Dispatch the residual questions with bounded concurrency. Each
        question fans out to md_txt + word in parallel. Cross-channel
        conflicts are resolved by :func:`_pick_winner` (LLM arbitration).
    9.  Second fill with the winning answers and return the rendered file.

Temporary files are removed in a ``BackgroundTasks`` callback after the
response is flushed. The ingest dir lives separately and survives /process
calls until the next /ingest.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

# Load .env before reading any env-driven config.
# We check multiple locations so the common Windows failure mode
# (ZIP-extracted nested "repo-main\repo-main\" layouts, or users putting
# .env next to their shell cwd instead of the code root) can't cause a
# silent "no LLM_API_KEY" crash.
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_CANDIDATES = [
    _REPO_ROOT / ".env",          # canonical: sibling of orchestrator/
    Path.cwd() / ".env",          # fallback: wherever uvicorn was launched
]
_ENV_FILE: Optional[Path] = None
_ENV_LOADED = False
for _cand in _ENV_CANDIDATES:
    if _cand.exists():
        load_dotenv(_cand, override=False)
        _ENV_FILE = _cand
        _ENV_LOADED = True
        break
if _ENV_FILE is None:
    _ENV_FILE = _REPO_ROOT / ".env"  # for error messages

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from orchestrator import (
    backend_client,
    excel_matcher,
    ingest_registry,
    llm,
    modora_client,
    pdf_converter,
    table_ops,
)
from orchestrator.readers import read_document_text


logging.basicConfig(
    level=os.environ.get("ORCH_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("orchestrator")

# -- .env diagnostics (so operators can spot misconfiguration instantly) --
_api_key = os.environ.get("LLM_API_KEY", "")
_key_preview = f"{_api_key[:6]}…{_api_key[-4:]}" if len(_api_key) >= 12 else "(empty)"
logger.info(
    ".env loaded=%s path=%s  LLM_API_KEY=%s  LLM_MODEL=%s",
    _ENV_LOADED,
    _ENV_FILE if _ENV_LOADED else "(missing — using process env only)",
    _key_preview,
    os.environ.get("LLM_MODEL", "(default)"),
)
if not _api_key or _api_key.startswith("replace-me") or _api_key == "sk-xxxx":
    logger.warning(
        "LLM_API_KEY missing or placeholder — LLM calls will fail. "
        "Check .env at %s", _ENV_FILE,
    )


app = FastAPI(title="MoDora Orchestrator", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Constants / helpers
# ---------------------------------------------------------------------------

MAX_FILES_PER_CHANNEL = 6
MAX_DOCS_CHARS_PER_CHANNEL = 80_000       # ~ 20k CN tokens per channel batch
_FILENAME_SAFE_RE = re.compile(r'[\\/*?:"<>|]')

# G2: LLM-based file routing. We shrink the per-channel file list to the top-k
# most likely-to-answer files before dispatching questions. ``top_k`` is the
# upper bound; if the channel already has ≤ top_k files we skip the route
# round-trip entirely.
_ROUTE_TOP_K = int(os.environ.get("ORCH_ROUTE_TOP_K", "3"))
_ROUTE_BRIEF_CHARS = int(os.environ.get("ORCH_ROUTE_BRIEF_CHARS", "400"))

# Ingest persistent dir. Lives outside per-request tempdirs so /process can
# still see the files after /ingest has returned. Overridable via env so
# operators can point this at a larger/faster volume if desired.
_INGEST_DIR = Path(
    os.environ.get("ORCH_INGEST_DIR") or (Path(tempfile.gettempdir()) / "modora_orch_ingest")
)


def sanitize_filename(name: str) -> str:
    if not name:
        return "unnamed"
    s = name.strip().strip('"').strip("'")
    s = _FILENAME_SAFE_RE.sub("_", s)
    return s or "unnamed"


async def _save_uploads(files: List[UploadFile], temp_dir: str, subdir: str) -> List[str]:
    if not files:
        return []
    out_dir = os.path.join(temp_dir, subdir)
    os.makedirs(out_dir, exist_ok=True)
    saved: List[str] = []
    for f in files:
        if not f or not f.filename:
            continue
        name = sanitize_filename(f.filename)
        dst = os.path.join(out_dir, name)
        content = await f.read()
        with open(dst, "wb") as w:
            w.write(content)
        saved.append(dst)
    return saved


def _normalize_entity(s: str) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", "", str(s).strip())


def _dedupe_entity_rows(rows: List[List[str]]) -> List[List[str]]:
    """De-duplicate entity rows across channels preserving first-seen order."""
    seen = set()
    out: List[List[str]] = []
    for row in rows:
        norm = tuple(_normalize_entity(v) for v in row)
        if not any(norm):
            continue
        if norm in seen:
            continue
        seen.add(norm)
        out.append([str(v).strip() for v in row])
    return out


def _truncate_docs(text: str, limit: int = MAX_DOCS_CHARS_PER_CHANNEL) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n...(omitted middle)...\n" + text[-half:]


def _concat_channel_texts(
    file_paths: List[str],
    limit: int = MAX_DOCS_CHARS_PER_CHANNEL,
) -> str:
    """Join up to ``limit`` chars of text across all files in the channel.

    Budget allocation (G4 fix): we give each file a proportional share rather
    than concatenating everything and then middle-stripping. The old
    behaviour dropped the entire mid-section of a long document whenever the
    total exceeded the limit, which meant entities mentioned only once in the
    middle of a long file could go missing. Per-file slicing with a head-only
    cut-off keeps every file represented.

    Small files stay whole; a pathologically long file (say the only file in
    the channel) still enjoys the full budget.
    """
    # Gather (filename, full_text) pairs, discarding files that produced no text.
    sources: List[tuple] = []
    for p in file_paths:
        text = read_document_text(p)
        if text:
            sources.append((os.path.basename(p), text))
    if not sources:
        return ""

    # Per-file ceiling = limit / N, plus a small header budget. We don't cap
    # below 2_000 chars because a too-small slice is useless to the LLM.
    per_file_cap = max(2_000, limit // len(sources))
    parts: List[str] = []
    running = 0
    for fn, text in sources:
        remaining = max(0, limit - running)
        if remaining <= 0:
            break
        cap = min(per_file_cap, remaining)
        if len(text) > cap:
            text = text[:cap] + "\n...(truncated)..."
        block = f"=== 文件: {fn} ===\n{text}"
        parts.append(block)
        running += len(block)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

async def _detect_structure(context: str, headers: List[str], requirement: str):
    """Classify each column as parent/child; retry once on parse failure.

    ``llm.chat`` already retries on network/429/5xx. The remaining failure
    mode is the model returning non-JSON prose (hallucinated Markdown fence,
    leading explanation, etc.) which ``extract_json`` can't salvage. Re-asking
    the same prompt usually gets a clean response because temperature and
    sampling vary between calls.
    """
    prompt = llm.build_structure_prompt(context, headers, requirement)
    last_err: Optional[Exception] = None
    for attempt in range(2):
        try:
            raw = await llm.chat(prompt, timeout=60.0)
            parsed = llm.extract_json(raw)
            break
        except llm.LLMError as e:
            last_err = e
            logger.warning(
                "structure detection attempt %d/2 failed: %s",
                attempt + 1, e,
            )
    else:
        logger.error("structure detection failed after 2 attempts: %s", last_err)
        raise HTTPException(status_code=500, detail="表头结构分析失败")
    parent_cols = [i for i in parsed.get("parent_columns", []) if 0 <= i < len(headers)]
    child_cols = [i for i in parsed.get("child_columns", []) if 0 <= i < len(headers)]
    return parent_cols, child_cols


async def _extract_parent_entities_for_channel(
    file_paths: List[str],
    context: str,
    parent_headers: List[str],
    child_headers: List[str],
    requirement: str,
) -> List[List[str]]:
    """Ask the LLM for parent-entity rows; return [] only after real exhaustion.

    One retry on parse failure (same rationale as _detect_structure) before
    giving up. Empty return is the contract both channels agreed on — it
    lets the other channel and Excel matcher still contribute entities.
    """
    if not file_paths:
        return []
    docs_text = _concat_channel_texts(file_paths)
    if not docs_text:
        return []
    prompt = llm.build_entities_prompt(
        docs_text, context, parent_headers, child_headers, requirement,
    )
    parsed = None
    for attempt in range(2):
        try:
            raw = await llm.chat(prompt, model=llm.LLM_MODEL_LONG, timeout=120.0)
            parsed = llm.extract_json(raw)
            break
        except llm.LLMError as e:
            logger.warning(
                "entity extraction attempt %d/2 failed (n_files=%d): %s",
                attempt + 1, len(file_paths), e,
            )
    if parsed is None:
        logger.error("entity extraction exhausted retries for %d files", len(file_paths))
        return []
    if not isinstance(parsed, list):
        logger.warning("entity prompt returned non-list: %r", parsed)
        return []
    return [[str(x) for x in row] for row in parsed if isinstance(row, list)]


async def _route_channel_files(
    docs: List[ingest_registry.IngestedDoc],
    parent_headers: List[str],
    child_headers: List[str],
    parent_rows: List[List[str]],
    requirement: str,
    top_k: int = _ROUTE_TOP_K,
) -> List[ingest_registry.IngestedDoc]:
    """Shrink a channel's file list to the ``top_k`` most relevant ones.

    Guarantees this function upholds:
    - **Never drops all docs.** If the LLM returns garbage, a list with
      unusable indices, or raises, we fall back to ``ready`` untouched.
    - **No-ops for small cohorts.** If the channel already has ≤ ``top_k``
      ready docs, routing would only add latency; we skip straight through.
    - **Only MoDora-ready docs are eligible.** A doc whose PDF build failed
      (``modora_filename is None``) can't answer /chat queries anyway.

    Called once per channel per /process (not per-question), so the routing
    cost is a single LLM round-trip regardless of how many cells need
    filling.
    """
    ready = [d for d in docs if d.modora_filename]
    if len(ready) <= top_k:
        return ready
    if not parent_rows:
        # No entity rows means we have no grounded evidence to route against;
        # keep every file so the downstream dispatcher still has coverage.
        return ready

    briefs: List[tuple] = []
    for d in ready:
        try:
            text = read_document_text(d.local_path)
        except Exception:
            logger.warning("route: failed to read %s; using filename only", d.local_path)
            text = ""
        briefs.append((d.original_name, text[:_ROUTE_BRIEF_CHARS]))

    prompt = llm.build_route_prompt(
        requirement, parent_headers, child_headers, parent_rows, briefs, top_k,
    )
    try:
        raw = await llm.chat(prompt, timeout=45.0)
        parsed = llm.extract_json(raw)
    except llm.LLMError:
        logger.warning(
            "route: LLM routing failed for channel (n=%d) — falling back to all files",
            len(ready),
        )
        return ready

    if not isinstance(parsed, list) or not parsed:
        logger.warning("route: non-list or empty selection %r — falling back", parsed)
        return ready

    indices: set = set()
    for i in parsed:
        try:
            idx = int(i)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(ready):
            indices.add(idx)
    if not indices:
        logger.warning("route: selection had no valid indices — falling back")
        return ready

    selected = [ready[i] for i in sorted(indices)]
    logger.info(
        "route: %d/%d files kept: %s",
        len(selected), len(ready),
        [d.original_name for d in selected],
    )
    return selected


def _normalise_answer(s: Optional[str]) -> str:
    """Cheap comparison key: lowercase, strip whitespace / common punctuation."""
    if s is None:
        return ""
    t = str(s).strip().lower()
    t = re.sub(r"[\s()\[\]{}:,.;/\\·\-_、，。：；（）【】《》<>]", "", t)
    return t


async def _llm_arbitrate(
    question: str,
    candidates: List[backend_client.Candidate],
) -> Optional[backend_client.Candidate]:
    """Ask the LLM to pick one candidate when channels disagree.

    Returns ``None`` on LLM failure / unparseable output so the caller can fall
    back to the deterministic priority rule instead of exploding mid-request.
    """
    options = [
        {"idx": i, "channel": c.channel, "answer": c.answer, "source": c.source}
        for i, c in enumerate(candidates)
    ]
    prompt = (
        "你是数据裁决员。多个信息源针对同一个问题给出了不同回答，请挑出最可信的一个。\n\n"
        f"【问题】: {question}\n\n"
        f"【候选答案】:\n{json.dumps(options, ensure_ascii=False, indent=2)}\n\n"
        "规则:\n"
        "  1. 优先选择与问题实体完全匹配、来源明确的候选。\n"
        "  2. 歧义或矛盾的概括性文本（如'一般是...')，则选数值/名称明确的。\n"
        "  3. 如果各候选都无法判断，选 idx=0。\n\n"
        "只返回胜出候选的 idx 数字，禁止任何其他文字。"
    )
    try:
        raw = await llm.chat(prompt, timeout=20.0)
    except llm.LLMError:
        logger.exception("llm arbitration failed")
        return None
    match = re.search(r"\d+", raw)
    if not match:
        return None
    try:
        idx = int(match.group(0))
    except ValueError:
        return None
    if 0 <= idx < len(candidates):
        return candidates[idx]
    return None


async def _pick_winner(
    question: str,
    candidates: List[backend_client.Candidate],
) -> Optional[backend_client.Candidate]:
    """Collapse a cross-channel candidate list into at most one answer.

    Decision order:
      1. Drop candidates that are ``error`` / ``not_found`` / invalid literals.
      2. One left -> use it.
      3. All remaining answers normalise to the same string -> take the
         highest-priority one (deterministic source tag).
      4. Conflicting answers -> ask LLM to arbitrate; if LLM fails, fall back
         to (channel_priority, confidence).
    """
    valid = [
        c for c in candidates
        if c.status == "found" and not backend_client.is_invalid_answer(c.answer)
    ]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]

    unique = {_normalise_answer(c.answer) for c in valid}
    if len(unique) == 1:
        valid.sort(
            key=lambda c: (backend_client.CHANNEL_PRIORITY.get(c.channel, 0), c.confidence),
            reverse=True,
        )
        return valid[0]

    # Conflict: arbitrate via LLM, fall back to deterministic priority.
    chosen = await _llm_arbitrate(question, valid)
    if chosen is not None:
        logger.info(
            "llm arbitrated conflicting answers (%d candidates) -> channel=%s",
            len(valid), chosen.channel,
        )
        return chosen
    valid.sort(
        key=lambda c: (backend_client.CHANNEL_PRIORITY.get(c.channel, 0), c.confidence),
        reverse=True,
    )
    logger.warning("llm arbitration unavailable; picking by priority")
    return valid[0]


async def _dispatch_questions(
    questions: Dict[str, str],
    files_by_channel: Dict[str, List[str]],
    requirement: str,
) -> Dict[str, str]:
    """Fan out questions with bounded concurrency.

    Each question itself fans out to the channels present in
    ``files_by_channel`` in parallel; cross-channel conflicts are resolved by
    :func:`_pick_winner`.
    """
    concurrency = int(os.environ.get("ORCH_QUESTION_CONCURRENCY", "8"))
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(coord: str, q: str):
        async with sem:
            candidates = await backend_client.dispatch(
                q, coord, files_by_channel, requirement=requirement,
            )
            best = await _pick_winner(q, candidates)
            # Compact single-line trace: one entry per coord so we can read
            # the full run at log level INFO without hex dumps.
            cand_summary = ", ".join(
                f"{c.channel}/{c.status}:{(c.answer or '')[:25]!r}"
                for c in candidates
            ) or "(none)"
            logger.info(
                "coord=%s winner=%r candidates=[%s]",
                coord,
                (best.answer if best else None),
                cand_summary,
            )
            return coord, (str(best.answer).strip() if best else "")

    if not questions:
        return {}
    pairs = await asyncio.gather(*[_one(c, q) for c, q in questions.items()])
    return dict(pairs)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Liveness + a cheap snapshot of registry state for runbook debugging."""
    api_key = os.environ.get("LLM_API_KEY", "")
    return {
        "status": "ok",
        "registry": {
            "count": ingest_registry.count(),
            "db": ingest_registry.db_path(),
            "ingest_dir": str(_INGEST_DIR),
        },
        "env": {
            "env_file_loaded": _ENV_LOADED,
            "env_file_path": str(_ENV_FILE),
            "llm_api_key_set": bool(api_key) and not api_key.startswith("replace-me"),
            "llm_api_key_preview": (
                f"{api_key[:6]}…{api_key[-4:]}" if len(api_key) >= 12 else "(empty)"
            ),
            "llm_model": os.environ.get("LLM_MODEL", "(default)"),
        },
    }


def _clean_ingest_dir() -> None:
    """Wipe everything under :data:`_INGEST_DIR` between /ingest calls."""
    if not _INGEST_DIR.exists():
        _INGEST_DIR.mkdir(parents=True, exist_ok=True)
        return
    for child in _INGEST_DIR.iterdir():
        try:
            if child.is_file() or child.is_symlink():
                child.unlink()
            else:
                shutil.rmtree(child, ignore_errors=True)
        except Exception:
            logger.warning("could not remove %s from ingest dir", child, exc_info=True)


@app.post("/ingest", summary="Bulk-ingest reference docs for subsequent /process calls")
async def ingest(
    ref_excel: List[UploadFile] = File(default=[], description="Excel reference materials (<=6)"),
    ref_md_txt: List[UploadFile] = File(default=[], description="Markdown / text reference materials (<=6)"),
    ref_word: List[UploadFile] = File(default=[], description="Word reference materials (<=6)"),
):
    """Upload up to 16 reference documents, persist + preprocess once.

    - Excel files are stored locally for deterministic header matching.
    - md / txt / docx files are converted to PDF and pushed to MoDora, which
      runs OCR + tree construction in the background; we poll until each
      tree is ready so subsequent /process calls never block on indexing.

    Each /ingest call **replaces** any previously ingested cohort.
    """
    for name, group in (
        ("ref_excel", ref_excel),
        ("ref_md_txt", ref_md_txt),
        ("ref_word", ref_word),
    ):
        if group and len(group) > MAX_FILES_PER_CHANNEL:
            raise HTTPException(
                status_code=400,
                detail=f"{name} 最多允许 {MAX_FILES_PER_CHANNEL} 个文件，收到 {len(group)} 个",
            )

    # New cohort: wipe stale disk state and registry entries.
    ingest_registry.clear()
    _clean_ingest_dir()

    excel_paths = await _save_uploads(ref_excel, str(_INGEST_DIR), "excel")
    md_txt_paths = await _save_uploads(ref_md_txt, str(_INGEST_DIR), "md_txt")
    word_paths = await _save_uploads(ref_word, str(_INGEST_DIR), "word")

    # Excel: register as-is, no MoDora round-trip.
    for p in excel_paths:
        ingest_registry.put(ingest_registry.IngestedDoc(
            original_name=os.path.basename(p),
            channel="excel",
            local_path=p,
            modora_filename=None,
            status="ok",
        ))

    # md_txt / word: convert to PDF, upload to MoDora, block until tree ready.
    async def _ingest_one(path: str, channel: str) -> None:
        orig_name = os.path.basename(path)
        try:
            pdf_path = await pdf_converter.convert_to_pdf(path, str(_INGEST_DIR))
            fn = await modora_client.ingest(pdf_path, backend_client.CHANNEL_URLS[channel])
            ingest_registry.put(ingest_registry.IngestedDoc(
                original_name=orig_name,
                channel=channel,
                local_path=path,            # raw source for LLM-side reading
                modora_filename=fn,
                status="ok",
            ))
        except Exception as exc:
            logger.exception("ingest failed for %s", orig_name)
            ingest_registry.put(ingest_registry.IngestedDoc(
                original_name=orig_name,
                channel=channel,
                local_path=path,
                modora_filename=None,
                status=f"failed:{type(exc).__name__}:{exc}",
            ))

    tasks: List = []
    tasks.extend(_ingest_one(p, "md_txt") for p in md_txt_paths)
    tasks.extend(_ingest_one(p, "word")   for p in word_paths)
    if tasks:
        await asyncio.gather(*tasks)

    summary = ingest_registry.as_summary()
    ok_count = sum(1 for d in summary if d["status"] == "ok")
    logger.info(
        "ingest complete: total=%d ok=%d failed=%d",
        len(summary), ok_count, len(summary) - ok_count,
    )
    return {
        "count": len(summary),
        "succeeded": ok_count,
        "failed": len(summary) - ok_count,
        "docs": summary,
    }


@app.get("/ingest", summary="Inspect the current ingest cohort")
def ingest_status():
    summary = ingest_registry.as_summary()
    ok_count = sum(1 for d in summary if d["status"] == "ok")
    return {
        "count": len(summary),
        "succeeded": ok_count,
        "failed": len(summary) - ok_count,
        "docs": summary,
    }


_BATCH_MAX_ROWS = 80  # split into chunks if more rows than this


async def _batch_extract_child_column(
    child_header: str,
    parent_headers: List[str],
    rows_to_query: List[Dict[str, str]],
    md_txt_paths: List[str],
    word_paths: List[str],
    requirement: str,
    context: str,
) -> List[Optional[str]]:
    """Extract *child_header* for all *rows_to_query* via ONE LLM call.

    Returns a list the same length as *rows_to_query*.  Each element is either
    the extracted string value or ``None`` if the LLM could not find it.

    When the row count exceeds :data:`_BATCH_MAX_ROWS` the list is split into
    chunks and the chunks are sent in parallel.
    """
    all_paths = md_txt_paths + word_paths
    if not all_paths or not rows_to_query:
        return [None] * len(rows_to_query)

    docs_text = _concat_channel_texts(all_paths, limit=MAX_DOCS_CHARS_PER_CHANNEL)
    if not docs_text.strip():
        return [None] * len(rows_to_query)

    async def _one_chunk(chunk: List[Dict[str, str]]) -> List[Optional[str]]:
        prompt = llm.build_batch_child_prompt(
            docs_text, requirement, parent_headers, child_header, chunk,
        )
        try:
            raw = await llm.chat(prompt, model=None, timeout=60.0)
            parsed = llm.extract_json(raw)
        except llm.LLMError:
            logger.warning(
                "batch child extraction failed for %s (%d rows)",
                child_header, len(chunk),
            )
            return [None] * len(chunk)
        if not isinstance(parsed, list):
            logger.warning(
                "batch child returned non-list for %s — got %s",
                child_header, type(parsed).__name__,
            )
            return [None] * len(chunk)
        # Pad / trim to match input length
        result: List[Optional[str]] = []
        for i in range(len(chunk)):
            if i < len(parsed) and parsed[i] is not None:
                val = str(parsed[i]).strip()
                if val and not backend_client.is_invalid_answer(val):
                    result.append(val)
                else:
                    result.append(None)
            else:
                result.append(None)
        return result

    # Split into chunks if necessary
    if len(rows_to_query) <= _BATCH_MAX_ROWS:
        return await _one_chunk(rows_to_query)

    chunks = [
        rows_to_query[i : i + _BATCH_MAX_ROWS]
        for i in range(0, len(rows_to_query), _BATCH_MAX_ROWS)
    ]
    chunk_results = await asyncio.gather(*[_one_chunk(c) for c in chunks])
    flat: List[Optional[str]] = []
    for cr in chunk_results:
        flat.extend(cr)
    return flat


async def _filter_excel_rows(
    sheets: List[excel_matcher.SheetIndex],
    context: str,
    requirement: str,
) -> List[excel_matcher.SheetIndex]:
    """Use an LLM call to derive row-level filters, then apply them.

    Returns the original *sheets* unchanged when:
    - there are no sheets to filter,
    - the LLM returns ``[]`` (no filtering needed), or
    - any error occurs (fail-open to avoid losing data).
    """
    if not sheets:
        return sheets
    # Collect all unique raw headers across sheets so the LLM can see what
    # columns are available for filtering.
    all_headers: List[str] = []
    seen: set = set()
    for s in sheets:
        for h in s.raw_headers:
            if h and h not in seen:
                seen.add(h)
                all_headers.append(h)
    if not all_headers:
        return sheets

    prompt = llm.build_excel_filter_prompt(context, requirement, all_headers)
    try:
        raw = await llm.chat(prompt, timeout=30.0)
        parsed = llm.extract_json(raw)
    except llm.LLMError:
        logger.warning("excel filter LLM call failed — skipping filter (all rows kept)")
        return sheets

    if not isinstance(parsed, list):
        logger.warning("excel filter returned non-list %r — skipping", type(parsed).__name__)
        return sheets
    # Normalise filter dicts — drop any malformed entries.
    filters: List[dict] = []
    for item in parsed:
        if isinstance(item, dict) and "column" in item:
            filters.append(item)
    if not filters:
        logger.info("excel filter: LLM returned no filters — all rows kept")
        return sheets

    logger.info("excel filter: applying %d filter(s): %s", len(filters), filters)
    return excel_matcher.apply_row_filters(sheets, filters)


async def _fill_one_table(
    ti: table_ops.TemplateInfo,
    *,
    excel_sheets: List[excel_matcher.SheetIndex],
    md_txt_docs: List[ingest_registry.IngestedDoc],
    word_docs: List[ingest_registry.IngestedDoc],
    md_txt_paths: List[str],
    word_paths: List[str],
    requirement: str,
) -> None:
    """Run the full fill pipeline (steps 4-9) for **one** table.

    For single-table templates this is called once.  For Word documents
    containing multiple independent tables (e.g. TC1: three cities in one
    docx) this is called per table, each time with the table's own headers
    and context so the LLM sees the right scope.

    Modifies ``ti.doc_obj`` in place — all tables share the same underlying
    Document / Workbook object.
    """
    kind = ti.kind
    headers = ti.headers
    context = ti.context
    tidx = ti.table_index

    if not any(h.strip() for h in headers):
        logger.warning("table[%d] has empty headers, skipping", tidx)
        return
    logger.info(
        "table[%d] start: headers=%s context=%r",
        tidx, headers, context[:120] if context else "(none)",
    )

    # -------- 4. parent / child column classification --------
    parent_cols, child_cols = await _detect_structure(context, headers, requirement)
    logger.info("table[%d] parent_cols=%s child_cols=%s", tidx, parent_cols, child_cols)

    # -------- 4.5. pre-filter Excel rows by context + requirement --------
    filtered_sheets = await _filter_excel_rows(
        excel_sheets, context, requirement,
    )

    # -------- 5. extract parent entities --------
    parent_headers = [headers[i] for i in parent_cols]
    child_headers = [headers[i] for i in child_cols]

    excel_rows: List[List[str]] = []
    all_rows: List[List[str]] = []
    if parent_cols:
        excel_rows = excel_matcher.extract_parent_entities(filtered_sheets, parent_headers)
        modora_rows = await asyncio.gather(
            _extract_parent_entities_for_channel(
                md_txt_paths, context, parent_headers, child_headers, requirement,
            ),
            _extract_parent_entities_for_channel(
                word_paths, context, parent_headers, child_headers, requirement,
            ),
        )
        all_rows.extend(excel_rows)
        for rows in modora_rows:
            all_rows.extend(rows)
        all_rows = _dedupe_entity_rows(all_rows)
    logger.info(
        "table[%d] parent rows: excel=%d total=%d",
        tidx, len(excel_rows), len(all_rows),
    )

    # -------- 6. first fill (parent entities) --------
    parent_fill: Dict[str, str] = {}
    for row_idx, row_vals in enumerate(all_rows, start=1):  # row 0 is header
        for i, col in enumerate(parent_cols):
            if i < len(row_vals):
                parent_fill[f"{row_idx}_{col}"] = row_vals[i]
    if kind == "word":
        table_ops.write_word_cells(ti.doc_obj, parent_fill, table_index=tidx)
    else:
        table_ops.write_excel_cells(ti.doc_obj, parent_fill)
    logger.info("table[%d] first fill wrote %d cells", tidx, len(parent_fill))

    # -------- 6.5. route channel files (G2, for MoDora fallback) --------
    md_txt_routed, word_routed = await asyncio.gather(
        _route_channel_files(md_txt_docs, parent_headers, child_headers, all_rows, requirement),
        _route_channel_files(word_docs,   parent_headers, child_headers, all_rows, requirement),
    )
    logger.info(
        "table[%d] after routing: md_txt=%d word=%d",
        tidx,
        sum(1 for d in md_txt_routed if d.modora_filename),
        sum(1 for d in word_routed if d.modora_filename),
    )

    # -------- 7. resolve child values (Excel → batch LLM → MoDora fallback) --------
    if kind == "word":
        grid = table_ops.get_word_grid(ti.doc_obj, table_index=tidx)
    else:
        grid = table_ops.get_excel_grid(ti.doc_obj)

    # 7a: collect data rows and try Excel direct match first.
    #   data_rows[i] = (grid_row_idx, parent_values_dict)
    data_rows: List[tuple] = []
    excel_child_fill: Dict[str, str] = {}
    for r_idx, row in enumerate(grid):
        if r_idx == 0:
            continue  # header row
        parent_values: Dict[str, str] = {}
        for col in parent_cols:
            if col < len(row) and row[col]:
                parent_values[headers[col]] = row[col]
        if parent_cols and not parent_values:
            continue
        data_rows.append((r_idx, parent_values))
        for col in child_cols:
            if col >= len(headers):
                continue
            coord = f"{r_idx}_{col}"
            match = excel_matcher.lookup_child_value(
                filtered_sheets, parent_values, headers[col],
            )
            if match is not None:
                value, source_tag = match
                excel_child_fill[coord] = value
                logger.debug(
                    "table[%d] excel direct %s=%r (%s)",
                    tidx, coord, value, source_tag,
                )

    # 7b: batch LLM extraction per child column (the big performance win).
    #   For each child column we send ONE LLM call with all parent rows,
    #   reading the document text directly instead of N individual /chat hops.
    batch_child_fill: Dict[str, str] = {}
    batch_tasks = []
    for col in child_cols:
        if col >= len(headers):
            continue
        # Figure out which rows still need this column (not covered by Excel).
        rows_needing: List[int] = []  # indices into data_rows
        for dr_i, (r_idx, _pv) in enumerate(data_rows):
            coord = f"{r_idx}_{col}"
            if coord not in excel_child_fill:
                rows_needing.append(dr_i)
        if not rows_needing:
            continue
        query_rows = [data_rows[i][1] for i in rows_needing]
        batch_tasks.append((col, rows_needing, query_rows))

    if batch_tasks:
        batch_results = await asyncio.gather(*[
            _batch_extract_child_column(
                headers[col], parent_headers, query_rows,
                md_txt_paths, word_paths, requirement, context,
            )
            for col, _rn, query_rows in batch_tasks
        ])
        for (col, rows_needing, _qr), values in zip(batch_tasks, batch_results):
            for dr_i, val in zip(rows_needing, values):
                if val is not None:
                    r_idx = data_rows[dr_i][0]
                    batch_child_fill[f"{r_idx}_{col}"] = val

    logger.info(
        "table[%d] child: excel=%d batch_llm=%d",
        tidx, len(excel_child_fill), len(batch_child_fill),
    )

    # 7c: MoDora fallback for cells that neither Excel nor batch LLM resolved.
    questions: Dict[str, str] = {}
    for dr_i, (r_idx, parent_values) in enumerate(data_rows):
        for col in child_cols:
            if col >= len(headers):
                continue
            coord = f"{r_idx}_{col}"
            if coord in excel_child_fill or coord in batch_child_fill:
                continue
            q = llm.render_question(parent_values, headers[col], requirement)
            questions[coord] = q

    modora_child_fill: Dict[str, str] = {}
    if questions:
        logger.info(
            "table[%d] MoDora fallback: %d residual questions",
            tidx, len(questions),
        )
        md_txt_modora_fns = [d.modora_filename for d in md_txt_routed if d.modora_filename]
        word_modora_fns   = [d.modora_filename for d in word_routed   if d.modora_filename]
        modora_channels: Dict[str, List[str]] = {
            "md_txt": md_txt_modora_fns,
            "word":   word_modora_fns,
        }
        modora_child_fill = await _dispatch_questions(questions, modora_channels, requirement)

    # Merge: Excel > batch LLM > MoDora (priority order).
    child_fill: Dict[str, str] = {}
    child_fill.update(modora_child_fill)
    child_fill.update(batch_child_fill)
    child_fill.update(excel_child_fill)

    # -------- 9. second fill (child values) --------
    if kind == "word":
        table_ops.write_word_cells(ti.doc_obj, child_fill, table_index=tidx)
    else:
        table_ops.write_excel_cells(ti.doc_obj, child_fill)
    logger.info(
        "table[%d] done: %d parent + %d child = %d cells",
        tidx, len(parent_fill), len(child_fill),
        len(parent_fill) + len(child_fill),
    )


@app.post("/process", summary="Template-driven table filling (uses /ingest'ed docs)")
async def process(
    background_tasks: BackgroundTasks,
    design_file: UploadFile = File(..., description="Blank template (.docx or .xlsx)"),
    requirement: str = Form("", description="Natural-language constraint (date, region, topic, ...)"),
):
    if ingest_registry.count() == 0:
        raise HTTPException(
            status_code=400,
            detail="没有已入库的素材。请先调用 POST /ingest 上传素材文件。",
        )

    temp_dir = tempfile.mkdtemp(prefix="orch_")
    # Always clean up, even if the request path raises.
    background_tasks.add_task(shutil.rmtree, temp_dir, ignore_errors=True)

    # -------- 1. save template --------
    design_name = sanitize_filename(design_file.filename or "template")
    design_path = os.path.join(temp_dir, design_name)
    with open(design_path, "wb") as f:
        f.write(await design_file.read())
    try:
        kind = table_ops.classify_template(design_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(
        "new request: kind=%s template=%s requirement=%r",
        kind, design_name, requirement,
    )

    # -------- 2. resolve reference docs from the registry --------
    excel_paths = [d.local_path for d in ingest_registry.by_channel("excel")]
    md_txt_docs = ingest_registry.by_channel("md_txt")
    word_docs   = ingest_registry.by_channel("word")
    md_txt_paths = [d.local_path for d in md_txt_docs]
    word_paths   = [d.local_path for d in word_docs]
    logger.info(
        "registry snapshot: excel=%d md_txt=%d word=%d",
        len(excel_paths), len(md_txt_docs), len(word_docs),
    )

    # -------- 3. parse template (multi-table aware) --------
    try:
        if kind == "word":
            infos = table_ops.load_word_template(design_path)
        else:
            infos = [table_ops.load_excel_template(design_path)]
    except Exception as e:
        logger.exception("template parsing failed")
        raise HTTPException(status_code=400, detail=f"模板解析失败: {e}")
    if not any(any(h.strip() for h in ti.headers) for ti in infos):
        raise HTTPException(status_code=400, detail="模板表头为空,无法继续")
    logger.info("template parsed: %d table(s)", len(infos))

    # Build Excel index once (shared across all tables).
    excel_sheets = excel_matcher.build_index(excel_paths)
    logger.info("excel_matcher indexed %d sheet(s)", len(excel_sheets))

    # -------- 4-9. fill each table independently --------
    for ti in infos:
        await _fill_one_table(
            ti,
            excel_sheets=excel_sheets,
            md_txt_docs=md_txt_docs,
            word_docs=word_docs,
            md_txt_paths=md_txt_paths,
            word_paths=word_paths,
            requirement=requirement,
        )

    # -------- 10. persist + return --------
    out_name = f"filled_{design_name}"
    out_path = os.path.join(temp_dir, out_name)
    try:
        table_ops.save_template(infos[0], out_path)  # all infos share same doc_obj
    except Exception as e:
        logger.exception("failed to save filled template")
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")

    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if kind == "word"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return FileResponse(path=out_path, filename=out_name, media_type=media_type)


# ---------------------------------------------------------------------------
# Dev server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "orchestrator.service:app",
        host=os.environ.get("ORCH_HOST", "127.0.0.1"),
        port=int(os.environ.get("ORCH_PORT", "8888")),
        reload=False,
    )
