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
import time
import uuid
from collections import deque
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


# Trailing Chinese administrative-division suffixes. Used ONLY to build dedup
# keys — the original value is preserved for display. The regex intentionally
# anchors to the end of the string (``$``) to avoid mangling names like
# "内蒙古自治区包头市" where "自治区" is *not* the terminal suffix.
_ADMIN_SUFFIX_RE = re.compile(
    r"(特别行政区|自治区|自治州|自治县|自治旗|省|市|区|县|镇|乡|旗)+$"
)


def _dedupe_key(s: str) -> str:
    """Normalised key for entity deduplication across channels.

    On top of :func:`_normalize_entity`, strips trailing admin-division
    suffixes so "合肥" and "合肥市" collapse to the same bucket. If stripping
    the suffix would leave an empty string (i.e. the value *is* just "市"),
    we keep the un-stripped form so we don't collapse every bare-suffix cell
    into a single empty key.
    """
    norm = _normalize_entity(s)
    stripped = _ADMIN_SUFFIX_RE.sub("", norm)
    return stripped if stripped else norm


def _dedupe_entity_rows(rows: List[List[str]]) -> List[List[str]]:
    """De-duplicate entity rows across channels preserving first-seen order.

    Key equality uses :func:`_dedupe_key` so ``["合肥市"]`` (from Excel) and
    ``["合肥"]`` (from an md document) are recognised as the same entity; the
    first-seen row wins, which in practice means Excel's well-formed value
    displaces MoDora's truncated one because Excel rows come first in the
    merge order.
    """
    seen = set()
    out: List[List[str]] = []
    for row in rows:
        key = tuple(_dedupe_key(v) for v in row)
        if not any(key):
            continue
        if key in seen:
            continue
        seen.add(key)
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
    text_cache: Optional[Dict[str, str]] = None,
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

    If ``text_cache`` is provided, file reads are memoised in it (G9). The
    first call for a given path populates the cache; subsequent calls within
    the same /process reuse the stored string. Passing ``None`` preserves the
    legacy behaviour of reading from disk every time (used by tests and
    endpoints that only look at one file).
    """
    # Gather (filename, full_text) pairs, discarding files that produced no text.
    sources: List[tuple] = []
    for p in file_paths:
        if text_cache is not None and p in text_cache:
            text = text_cache[p]
        else:
            text = read_document_text(p)
            if text_cache is not None:
                text_cache[p] = text or ""
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
    parsed: Optional[dict] = None
    for attempt in range(2):
        try:
            raw = await llm.chat(prompt, timeout=60.0)
            result = llm.extract_json(raw)
            if isinstance(result, dict):
                parsed = result
                break
            # extract_json returned a non-dict (e.g. list) — retry
            logger.warning(
                "structure detection attempt %d/2: expected dict, got %s",
                attempt + 1, type(result).__name__,
            )
        except Exception as e:
            last_err = e
            logger.warning(
                "structure detection attempt %d/2 failed: %s",
                attempt + 1, e,
            )

    # Heuristic fallback. Two keyword sets so we can resolve conflicts
    # deterministically: if a header matches BOTH a parent and a child cue
    # (unusual, but e.g. "站点总数" hits 站点 from _PARENT_KW and 总数 from
    # _CHILD_KW), _CHILD_KW wins because measurement-like words almost
    # always indicate a value column in the contest corpus.
    _PARENT_KW = {
        # 地理 / 行政
        "名", "区", "省", "市", "国", "县", "镇", "乡", "街道",
        # 标识符
        "编号", "代码", "编码", "站点", "序号", "排名", "id",
        # 人 / 组织
        "姓名", "公司", "机构", "单位", "部门",
        # 时间类(常作为时间序列主键)
        "日期", "时间", "年月", "年份", "月份", "期号", "期",
    }
    _CHILD_KW = {
        # 核心度量
        "gdp", "产值", "产量", "人口", "面积", "售价", "价格", "金额",
        "收入", "支出", "利润", "营收", "预算",
        # 统计
        "总数", "总量", "数量", "人数", "次数", "数目",
        "率", "比例", "占比", "指数", "指标",
        # 空气 / 气象 / 环境
        "aqi", "pm2.5", "pm10", "降雨量", "温度", "湿度", "浓度",
        # 健康 / 疫情
        "确诊", "治愈", "死亡", "检测", "病例",
    }

    def _heuristic() -> tuple:
        logger.warning("structure detection: using heuristic fallback")
        pc: List[int] = []
        cc: List[int] = []
        for i, h in enumerate(headers):
            h_low = h.lower()
            is_child = any(kw in h_low for kw in _CHILD_KW)
            is_parent = any(kw in h_low for kw in _PARENT_KW)
            if is_child:
                cc.append(i)
            elif is_parent:
                pc.append(i)
            else:
                cc.append(i)  # unknown → default to child (safer: LLM will be queried)
        if not pc:
            # Nothing looked parent-ish → fall back to "first column is the key"
            pc = [0]
            cc = [i for i in range(len(headers)) if i != 0]
        return pc, cc

    if parsed is None:
        return _heuristic()

    parent_cols = [i for i in parsed.get("parent_columns", []) if 0 <= i < len(headers)]
    child_cols = [i for i in parsed.get("child_columns", []) if 0 <= i < len(headers)]
    # Bug 2 guard: if both are empty, the LLM response was useless
    if not parent_cols and not child_cols:
        return _heuristic()
    return parent_cols, child_cols


async def _extract_parent_entities_for_channel(
    file_paths: List[str],
    context: str,
    parent_headers: List[str],
    child_headers: List[str],
    requirement: str,
    text_cache: Optional[Dict[str, str]] = None,
) -> List[List[str]]:
    """Ask the LLM for parent-entity rows; return [] only after real exhaustion.

    One retry on parse failure (same rationale as _detect_structure) before
    giving up. Empty return is the contract both channels agreed on — it
    lets the other channel and Excel matcher still contribute entities.
    """
    if not file_paths:
        return []
    docs_text = _concat_channel_texts(file_paths, text_cache=text_cache)
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


_ROUTE_TOKEN_SPLIT_RE = re.compile(r"[\s,。;、/()【】\[\]（）<>]+")


def _keyword_route_fallback(
    ready: List[ingest_registry.IngestedDoc],
    briefs: List[tuple],
    parent_rows: List[List[str]],
    child_headers: List[str],
    requirement: str,
    top_k: int,
) -> List[ingest_registry.IngestedDoc]:
    """Pick ``top_k`` docs by keyword overlap in filename + brief.

    Used when LLM routing fails. Weighs hits in descending importance:
      - parent-row values (the entities we actually need to answer)  × 3
      - child-column headers (the metrics we're asking about)        × 1.5
      - requirement tokens (date range, region, topic qualifier)     × 1

    If zero docs score positively, returns ``ready`` untouched — that means
    we genuinely have nothing better than "try everything" and the LLM
    fallback was doing the right thing in the first place.
    """
    parent_kw: set = set()
    for row in parent_rows:
        for v in row:
            vs = str(v).strip().lower()
            if len(vs) >= 2:
                parent_kw.add(vs)
    child_kw = {h.strip().lower() for h in child_headers if h.strip()}
    req_kw: set = set()
    if requirement:
        for tok in _ROUTE_TOKEN_SPLIT_RE.split(requirement):
            tok = tok.strip().lower()
            if len(tok) >= 2 and not tok.isdigit():
                req_kw.add(tok)

    scored: List[tuple] = []  # (score, idx)
    for i, (fn, brief) in enumerate(briefs):
        haystack = f"{fn}\n{brief}".lower()
        score = 0.0
        for kw in parent_kw:
            if kw in haystack:
                score += 3.0
        for kw in child_kw:
            if kw in haystack:
                score += 1.5
        for kw in req_kw:
            if kw in haystack:
                score += 1.0
        scored.append((score, i))

    positive = [i for s, i in sorted(scored, key=lambda x: x[0], reverse=True) if s > 0]
    if not positive:
        # No hits at all → keyword match didn't help; let caller keep full list.
        return ready
    keep = positive[:top_k]
    return [ready[i] for i in sorted(keep)]


async def _route_channel_files(
    docs: List[ingest_registry.IngestedDoc],
    parent_headers: List[str],
    child_headers: List[str],
    parent_rows: List[List[str]],
    requirement: str,
    top_k: int = _ROUTE_TOP_K,
    text_cache: Optional[Dict[str, str]] = None,
) -> List[ingest_registry.IngestedDoc]:
    """Shrink a channel's file list to the ``top_k`` most relevant ones.

    Guarantees this function upholds:
    - **Never drops all docs.** If the LLM returns garbage, a list with
      unusable indices, or raises, we fall back to keyword routing; if THAT
      also yields nothing we fall back to ``ready`` untouched.
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
        # Reuse the cached text when available; fall back to fresh disk read
        # so direct callers (tests, /extract) that don't pass a cache still
        # work.
        cached = text_cache.get(d.local_path) if text_cache is not None else None
        if cached is not None:
            text = cached
        else:
            try:
                text = read_document_text(d.local_path)
            except Exception:
                logger.warning("route: failed to read %s; using filename only", d.local_path)
                text = ""
            if text_cache is not None:
                text_cache[d.local_path] = text or ""
        briefs.append((d.original_name, text[:_ROUTE_BRIEF_CHARS]))

    # G3: keyword prefilter BEFORE LLM routing. If parent entities clearly
    # disqualify some files (no mention of any entity in filename + brief
    # prefix), drop them from the candidate pool up-front. Two benefits:
    #   1. Smaller candidate list → LLM has an easier job choosing top-k.
    #   2. When prefilter alone narrows to ≤ top_k docs, we skip the LLM
    #      round-trip entirely.
    # We disable the prefilter whenever it would be too aggressive (fewer
    # than top_k hits) because losing a relevant doc is strictly worse than
    # letting the LLM see a few irrelevant ones.
    parent_kw: set = set()
    for row in parent_rows:
        for v in row:
            vs = str(v).strip().lower()
            if len(vs) >= 2:
                parent_kw.add(vs)

    prefilter_hits: Optional[List[int]] = None
    if parent_kw:
        hits = [
            i for i, (fn, brief) in enumerate(briefs)
            if any(kw in f"{fn}\n{brief}".lower() for kw in parent_kw)
        ]
        if len(hits) >= top_k:
            # Only trust the prefilter when it leaves enough room for LLM
            # ranking; otherwise we risk losing the actual answer doc.
            prefilter_hits = hits

    if prefilter_hits is not None and len(prefilter_hits) == top_k:
        # Perfect match: exactly top_k parent-hit candidates. Skip the LLM.
        selected = [ready[i] for i in prefilter_hits]
        logger.info(
            "route: keyword prefilter alone kept %d/%d files (no LLM call): %s",
            len(selected), len(ready),
            [d.original_name for d in selected],
        )
        return selected

    # Candidate pool for LLM routing: either the prefilter hits or the full
    # ready list when prefilter was skipped.
    if prefilter_hits is not None and len(prefilter_hits) < len(ready):
        candidate_indices = prefilter_hits
        candidate_briefs = [briefs[i] for i in candidate_indices]
        logger.info(
            "route: keyword prefilter narrowed candidates %d -> %d for LLM",
            len(ready), len(candidate_indices),
        )
    else:
        candidate_indices = list(range(len(ready)))
        candidate_briefs = briefs

    def _keyword_fallback(reason: str) -> List[ingest_registry.IngestedDoc]:
        kw_selected = _keyword_route_fallback(
            ready, briefs, parent_rows, child_headers, requirement, top_k,
        )
        if kw_selected is not ready and len(kw_selected) < len(ready):
            logger.warning(
                "route: %s — keyword fallback kept %d/%d files: %s",
                reason, len(kw_selected), len(ready),
                [d.original_name for d in kw_selected],
            )
            return kw_selected
        logger.warning(
            "route: %s — keyword fallback yielded no hits, keeping all %d files",
            reason, len(ready),
        )
        return ready

    prompt = llm.build_route_prompt(
        requirement, parent_headers, child_headers, parent_rows,
        candidate_briefs, top_k,
    )
    try:
        raw = await llm.chat(prompt, timeout=45.0)
        parsed = llm.extract_json(raw)
    except llm.LLMError:
        return _keyword_fallback(f"LLM routing failed (n={len(candidate_briefs)})")

    if not isinstance(parsed, list) or not parsed:
        return _keyword_fallback(f"non-list or empty selection {parsed!r}")

    # LLM indices point into candidate_briefs, not ready. Remap through
    # candidate_indices so we always return ready-space selections.
    indices: set = set()
    for i in parsed:
        try:
            local_idx = int(i)
        except (TypeError, ValueError):
            continue
        if 0 <= local_idx < len(candidate_indices):
            indices.add(candidate_indices[local_idx])
    if not indices:
        return _keyword_fallback("selection had no valid indices")

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
    """Wipe everything under :data:`_INGEST_DIR` between /ingest calls.

    We skip ``registry.sqlite3*`` files (db, -wal, -shm) because they may
    still be held open by the sqlite driver — removing them on Windows
    raises PermissionError (WinError 32). The registry data has already
    been cleared via :func:`ingest_registry.clear`.
    """
    if not _INGEST_DIR.exists():
        _INGEST_DIR.mkdir(parents=True, exist_ok=True)
        return
    for child in _INGEST_DIR.iterdir():
        if child.name.startswith("registry.sqlite3"):
            continue
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
    _record_op("ingest", f"文件数: {len(summary)}, 成功: {ok_count}")
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
    text_cache: Optional[Dict[str, str]] = None,
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

    docs_text = _concat_channel_texts(
        all_paths, limit=MAX_DOCS_CHARS_PER_CHANNEL, text_cache=text_cache,
    )
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


async def _batch_extract_children_multi(
    child_headers: List[str],
    parent_headers: List[str],
    rows_to_query: List[Dict[str, str]],
    md_txt_paths: List[str],
    word_paths: List[str],
    requirement: str,
    context: str,
    text_cache: Optional[Dict[str, str]] = None,
) -> Dict[str, List[Optional[str]]]:
    """Extract **all** *child_headers* for **all** rows in ONE LLM call.

    Returns ``{child_header: [val_or_None, ...]}`` where each list matches
    the length of *rows_to_query*.

    Internally chunks at :data:`_BATCH_MAX_ROWS` and merges results.
    Falls back to per-column :func:`_batch_extract_child_column` on failure.
    """
    all_paths = md_txt_paths + word_paths
    empty = {h: [None] * len(rows_to_query) for h in child_headers}
    if not all_paths or not rows_to_query or not child_headers:
        return empty

    docs_text = _concat_channel_texts(
        all_paths, limit=MAX_DOCS_CHARS_PER_CHANNEL, text_cache=text_cache,
    )
    if not docs_text.strip():
        return empty

    async def _one_chunk(
        chunk: List[Dict[str, str]],
    ) -> List[Dict[str, Optional[str]]]:
        prompt = llm.build_batch_child_multi_prompt(
            docs_text, requirement, parent_headers, child_headers, chunk,
        )
        try:
            raw = await llm.chat(prompt, model=None, timeout=90.0)
            parsed = llm.extract_json(raw)
        except llm.LLMError:
            logger.warning(
                "multi-child extraction failed (%d cols, %d rows), "
                "falling back to per-column",
                len(child_headers), len(chunk),
            )
            return []  # signal fallback
        if not isinstance(parsed, list):
            logger.warning(
                "multi-child returned non-list — got %s, falling back",
                type(parsed).__name__,
            )
            return []
        # Normalise: ensure each element is a dict
        result: List[Dict[str, Optional[str]]] = []
        for i in range(len(chunk)):
            if i < len(parsed) and isinstance(parsed[i], dict):
                row_dict: Dict[str, Optional[str]] = {}
                for h in child_headers:
                    v = parsed[i].get(h)
                    if v is not None:
                        vs = str(v).strip()
                        if vs and not backend_client.is_invalid_answer(vs):
                            row_dict[h] = vs
                        else:
                            row_dict[h] = None
                    else:
                        row_dict[h] = None
                result.append(row_dict)
            else:
                result.append({h: None for h in child_headers})
        return result

    # Chunk if necessary
    if len(rows_to_query) <= _BATCH_MAX_ROWS:
        chunks = [rows_to_query]
    else:
        chunks = [
            rows_to_query[i : i + _BATCH_MAX_ROWS]
            for i in range(0, len(rows_to_query), _BATCH_MAX_ROWS)
        ]
    chunk_results = await asyncio.gather(*[_one_chunk(c) for c in chunks])

    # Check for fallback signal (empty list from any chunk)
    need_fallback = any(len(cr) == 0 for cr in chunk_results)
    if need_fallback:
        logger.info("multi-child fallback → per-column extraction")
        per_col = await asyncio.gather(*[
            _batch_extract_child_column(
                h, parent_headers, rows_to_query,
                md_txt_paths, word_paths, requirement, context,
                text_cache=text_cache,
            )
            for h in child_headers
        ])
        return {h: vals for h, vals in zip(child_headers, per_col)}

    # Merge chunks into per-column lists
    merged: Dict[str, List[Optional[str]]] = {h: [] for h in child_headers}
    for cr in chunk_results:
        for row_dict in cr:
            for h in child_headers:
                merged[h].append(row_dict.get(h))
    return merged


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
    channel_health: Optional[Dict[str, bool]] = None,
    text_cache: Optional[Dict[str, str]] = None,
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
        # G6: Excel is structured and authoritative. When it yields enough
        # parent rows we skip the MoDora LLM extraction entirely — that path
        # costs 2 LLM round-trips AND is the main source of hallucinated
        # entities (e.g. LLM inventing an extra city that isn't really in
        # the docs). ``ORCH_ENTITY_EXTRACT_EXCEL_MIN`` lets operators tune
        # how much we trust Excel; set it very high (e.g. 10_000) to force
        # the legacy always-run behaviour, or 1 (default) to skip whenever
        # Excel provides any rows at all.
        excel_min = int(os.environ.get("ORCH_ENTITY_EXTRACT_EXCEL_MIN", "1"))
        skip_modora_entities = bool(excel_rows) and len(excel_rows) >= excel_min
        if skip_modora_entities:
            logger.info(
                "table[%d] entity extraction: excel yielded %d rows (>= %d), "
                "skipping MoDora LLM extraction",
                tidx, len(excel_rows), excel_min,
            )
            all_rows = list(excel_rows)
        else:
            modora_rows = await asyncio.gather(
                _extract_parent_entities_for_channel(
                    md_txt_paths, context, parent_headers, child_headers, requirement,
                    text_cache=text_cache,
                ),
                _extract_parent_entities_for_channel(
                    word_paths, context, parent_headers, child_headers, requirement,
                    text_cache=text_cache,
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
        _route_channel_files(
            md_txt_docs, parent_headers, child_headers, all_rows, requirement,
            text_cache=text_cache,
        ),
        _route_channel_files(
            word_docs, parent_headers, child_headers, all_rows, requirement,
            text_cache=text_cache,
        ),
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

    # 7b: batch LLM extraction — ALL child columns × ALL rows in ONE call.
    #   Previous version made one LLM call per child column; this merges them
    #   so a table with 4 child cols does 1 call instead of 4.
    batch_child_fill: Dict[str, str] = {}

    # Identify rows × columns that still need LLM extraction.
    cols_needing: List[int] = []              # child col indices with residuals
    rows_needing_set: set = set()             # union of dr_i across all cols
    col_row_map: Dict[int, List[int]] = {}    # col → [dr_i, ...]
    for col in child_cols:
        if col >= len(headers):
            continue
        rn: List[int] = []
        for dr_i, (r_idx, _pv) in enumerate(data_rows):
            if f"{r_idx}_{col}" not in excel_child_fill:
                rn.append(dr_i)
                rows_needing_set.add(dr_i)
        if rn:
            cols_needing.append(col)
            col_row_map[col] = rn

    if cols_needing:
        # Build query rows: union of all rows needed by any child column.
        rows_needing_sorted = sorted(rows_needing_set)
        query_rows = [data_rows[i][1] for i in rows_needing_sorted]
        dr_i_to_qi = {dr_i: qi for qi, dr_i in enumerate(rows_needing_sorted)}

        multi_result = await _batch_extract_children_multi(
            [headers[c] for c in cols_needing],
            parent_headers, query_rows,
            md_txt_paths, word_paths, requirement, context,
            text_cache=text_cache,
        )
        for col in cols_needing:
            h = headers[col]
            col_vals = multi_result.get(h, [])
            for dr_i in col_row_map[col]:
                qi = dr_i_to_qi.get(dr_i)
                if qi is not None and qi < len(col_vals) and col_vals[qi] is not None:
                    r_idx = data_rows[dr_i][0]
                    batch_child_fill[f"{r_idx}_{col}"] = col_vals[qi]

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
        # Skip unhealthy channels entirely. ``channel_health.get(c, True)``
        # defaults to healthy so callers that don't pass a probe result (e.g.
        # tests, Excel-only runs) keep the previous behaviour.
        health = channel_health or {}
        modora_channels: Dict[str, List[str]] = {}
        if md_txt_modora_fns and health.get("md_txt", True):
            modora_channels["md_txt"] = md_txt_modora_fns
        if word_modora_fns and health.get("word", True):
            modora_channels["word"] = word_modora_fns
        skipped = [
            c for c in ("md_txt", "word")
            if health.get(c, True) is False
        ]
        if skipped:
            logger.warning(
                "table[%d] skipping unhealthy channel(s): %s — %d residual "
                "questions will be unanswered by those channels",
                tidx, skipped, len(questions),
            )
        if modora_channels:
            modora_child_fill = await _dispatch_questions(questions, modora_channels, requirement)
        else:
            logger.warning(
                "table[%d] no healthy MoDora channels available — all %d "
                "residual questions will be left blank",
                tidx, len(questions),
            )

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

    # -------- 2.5. probe MoDora channels so we don't hang on dead peers --------
    # Only probe channels that actually have ingested files; no point failing
    # over a channel we weren't going to call anyway. Excel is in-process so
    # it's always "healthy" by definition.
    channels_to_probe: List[str] = []
    if md_txt_docs:
        channels_to_probe.append("md_txt")
    if word_docs:
        channels_to_probe.append("word")
    if channels_to_probe:
        channel_health = await backend_client.probe_channels(channels_to_probe)
        unhealthy = [c for c, ok in channel_health.items() if not ok]
        if unhealthy:
            logger.warning(
                "unhealthy channels detected: %s — /chat fallback will skip them",
                unhealthy,
            )
        else:
            logger.info("channel probe: %s all healthy", channels_to_probe)
    else:
        channel_health = {}

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

    # G9: pre-read every non-Excel doc once so every downstream prompt — parent
    # extraction, routing briefs, batch child extraction — shares the same
    # text buffer instead of hitting disk per call. For a typical TC2 run
    # with 6 md/word docs this avoids 12+ redundant file reads per /process.
    # Failures fall back to "" so downstream `if text:` checks still work.
    text_cache: Dict[str, str] = {}
    for p in md_txt_paths + word_paths:
        try:
            text_cache[p] = read_document_text(p) or ""
        except Exception:
            logger.warning("text_cache: failed to pre-read %s", p, exc_info=True)
            text_cache[p] = ""
    logger.info(
        "text_cache: pre-read %d file(s), total %d chars",
        len(text_cache), sum(len(v) for v in text_cache.values()),
    )

    # -------- 4-9. fill each table independently (parallel when >1 table) --------
    async def _safe_fill(ti: table_ops.TemplateInfo) -> None:
        try:
            await _fill_one_table(
                ti,
                excel_sheets=excel_sheets,
                md_txt_docs=md_txt_docs,
                word_docs=word_docs,
                md_txt_paths=md_txt_paths,
                word_paths=word_paths,
                requirement=requirement,
                channel_health=channel_health,
                text_cache=text_cache,
            )
        except Exception:
            logger.exception("table[%d] fill failed — skipping", ti.table_index)

    if len(infos) == 1:
        await _safe_fill(infos[0])
    else:
        await asyncio.gather(*[_safe_fill(ti) for ti in infos])

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
    _record_op("process", f"模板: {design_name}, 表数: {len(infos)}, 要求: {requirement[:60]}")
    return FileResponse(path=out_path, filename=out_name, media_type=media_type)


# ---------------------------------------------------------------------------
# File preview (for the frontend)
# ---------------------------------------------------------------------------

@app.get("/preview/{filename}", summary="Preview / download an ingested file")
def preview_file(filename: str):
    """Serve an ingested file so the frontend can preview it.

    Guarded against path traversal: the resolved path must stay inside
    :data:`_INGEST_DIR`.
    """
    # Reject obviously malicious names BEFORE touching the filesystem
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    safe_name = sanitize_filename(filename)
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    fpath = (_INGEST_DIR / safe_name).resolve()
    ingest_root = _INGEST_DIR.resolve()
    try:
        fpath.relative_to(ingest_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径越界")

    if not fpath.exists() or not fpath.is_file():
        raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")
    # Basic MIME mapping
    ext = fpath.suffix.lower()
    _MIME = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pdf": "application/pdf",
        ".md": "text/markdown; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
    }
    return FileResponse(
        path=str(fpath),
        filename=filename,
        media_type=_MIME.get(ext, "application/octet-stream"),
    )


# ---------------------------------------------------------------------------
# Operation history
# ---------------------------------------------------------------------------

_OP_HISTORY: deque = deque(maxlen=200)  # ring buffer, newest last
_OP_COUNTER = 0  # monotonic, never wraps even when ring buffer drops old entries


def _record_op(op_type: str, detail: str, status: str = "ok") -> dict:
    global _OP_COUNTER
    _OP_COUNTER += 1
    entry = {
        "id": _OP_COUNTER,
        "type": op_type,
        "detail": detail,
        "status": status,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _OP_HISTORY.append(entry)
    return entry


@app.get("/history", summary="Operation history (recent 200)")
def get_history(limit: int = 50):
    """Return the most recent operations for the frontend dashboard."""
    items = list(_OP_HISTORY)
    items.reverse()  # newest first
    return {"history": items[:limit]}


# ---------------------------------------------------------------------------
# Module 2: Information Extraction
# ---------------------------------------------------------------------------

@app.post("/extract", summary="Extract structured info from an uploaded document")
async def extract_info(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Document to extract from (.docx/.pdf/.xlsx/.md/.txt)"),
    query: str = Form("", description="Optional: specify what to extract"),
):
    """Module-2 endpoint: upload a document, get structured entities/key-info back."""
    temp_dir = tempfile.mkdtemp(prefix="orch_extract_")
    background_tasks.add_task(shutil.rmtree, temp_dir, ignore_errors=True)

    fname = sanitize_filename(file.filename or "document")
    ext = os.path.splitext(fname)[1].lower()
    supported = {".md", ".txt", ".docx", ".xlsx", ".xls", ".pdf"}
    if ext not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}。支持: {', '.join(sorted(supported))}",
        )

    fpath = os.path.join(temp_dir, fname)
    with open(fpath, "wb") as f:
        f.write(await file.read())

    doc_text = read_document_text(fpath)
    if not doc_text or not doc_text.strip():
        raise HTTPException(status_code=400, detail="无法从文件中提取文本内容")

    # Truncate to fit LLM context
    doc_text = _truncate_docs(doc_text, limit=MAX_DOCS_CHARS_PER_CHANNEL)

    prompt = llm.build_extract_prompt(doc_text, query)
    try:
        raw = await llm.chat(prompt, timeout=90.0)
        result = llm.extract_json(raw)
    except llm.LLMError as e:
        logger.warning("extract LLM failed: %s", e)
        raise HTTPException(status_code=500, detail=f"信息提取失败: {e}")

    if not isinstance(result, dict):
        result = {"raw": result}

    result["file_name"] = fname
    result["file_type"] = ext.lstrip(".")
    result["char_count"] = len(doc_text)
    _record_op("extract", f"文件: {fname}, 类型: {ext}")
    return result


# ---------------------------------------------------------------------------
# Module 1: Document Intelligent Editing
# ---------------------------------------------------------------------------

def _describe_doc_structure(path: str) -> str:
    """Build a concise structural description of a .docx for the LLM."""
    from docx import Document
    from docx.oxml.ns import qn

    doc = Document(path)
    parts: List[str] = []
    para_idx = 0
    w_t = qn("w:t")
    w_tr = qn("w:tr")
    w_tc = qn("w:tc")

    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            para_idx += 1
            texts = child.findall(".//" + w_t)
            text = "".join(t.text or "" for t in texts).strip()
            if text:
                preview = text[:80] + ("..." if len(text) > 80 else "")
                # Detect heading level
                pPr = child.find(qn("w:pPr"))
                style = ""
                if pPr is not None:
                    pStyle = pPr.find(qn("w:pStyle"))
                    if pStyle is not None:
                        style = f" [style={pStyle.get(qn('w:val'), '')}]"
                parts.append(f"  段落{para_idx}{style}: {preview}")
        elif tag == "tbl":
            rows = child.findall(".//" + w_tr)
            first_row_cells = []
            if rows:
                for tc in rows[0].findall(".//" + w_tc):
                    ts = tc.findall(".//" + w_t)
                    first_row_cells.append("".join(t.text or "" for t in ts).strip())
            parts.append(
                f"  [表格: {len(rows)}行, 表头: {first_row_cells[:6]}]"
            )

    return f"共 {para_idx} 个段落:\n" + "\n".join(parts[:50])


def _apply_edit_ops(path: str, ops: List[dict]) -> str:
    """Apply a list of edit operations to a .docx and return the saved path."""
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document(path)
    paragraphs = doc.paragraphs

    _ALIGN_MAP = {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }

    def _find_targets(target_desc: str) -> List[int]:
        """Resolve a target description like '第1段' / '包含XXX的段落' / '所有段落'."""
        desc = target_desc.strip()
        if desc == "所有段落":
            return list(range(len(paragraphs)))
        # '第N段'
        m = re.match(r"第(\d+)段", desc)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(paragraphs):
                return [idx]
            return []
        # '标题' — first paragraph
        if "标题" in desc:
            return [0] if paragraphs else []
        # '包含XXX的段落'
        m2 = re.match(r"包含[\"']?(.+?)[\"']?的段落", desc)
        keyword = m2.group(1) if m2 else desc
        return [i for i, p in enumerate(paragraphs) if keyword in p.text]

    for op in ops:
        action = op.get("action", "")
        target = op.get("target", "")
        params = op.get("params", {})

        try:
            indices = _find_targets(target)

            if action == "format_text":
                for idx in indices:
                    for run in paragraphs[idx].runs:
                        if "bold" in params:
                            run.bold = params["bold"]
                        if "italic" in params:
                            run.italic = params["italic"]
                        if "underline" in params:
                            run.underline = params["underline"]
                        if "font_name" in params:
                            run.font.name = params["font_name"]
                        if "font_size" in params:
                            run.font.size = Pt(params["font_size"])
                        if "color" in params:
                            hex_color = params["color"].lstrip("#")
                            run.font.color.rgb = RGBColor(
                                int(hex_color[0:2], 16),
                                int(hex_color[2:4], 16),
                                int(hex_color[4:6], 16),
                            )

            elif action == "set_alignment":
                align = _ALIGN_MAP.get(params.get("alignment", ""), None)
                if align is not None:
                    for idx in indices:
                        paragraphs[idx].alignment = align

            elif action == "replace_text":
                old = params.get("old", "")
                new = params.get("new", "")
                if old:
                    for idx in indices:
                        for run in paragraphs[idx].runs:
                            if old in run.text:
                                run.text = run.text.replace(old, new)

            elif action == "insert_text":
                position = params.get("position", "after")
                text = params.get("text", "")
                if text and indices:
                    ref_idx = indices[0]
                    ref_para = paragraphs[ref_idx]
                    new_para = doc.add_paragraph(text)
                    # Move the new paragraph to the right position
                    if position == "before":
                        ref_para._element.addprevious(new_para._element)
                    else:
                        ref_para._element.addnext(new_para._element)

            elif action == "delete_text":
                for idx in sorted(indices, reverse=True):
                    p = paragraphs[idx]._element
                    p.getparent().remove(p)

            elif action == "set_heading":
                level = params.get("level", 1)
                for idx in indices:
                    paragraphs[idx].style = doc.styles[f"Heading {level}"]

            elif action == "insert_table":
                rows = params.get("rows", 2)
                cols = params.get("cols", 2)
                headers = params.get("headers", [])
                tbl = doc.add_table(rows=rows, cols=cols)
                tbl.style = "Table Grid"
                if headers:
                    for ci, h in enumerate(headers[:cols]):
                        tbl.rows[0].cells[ci].text = h
                # Move table after target paragraph
                if indices:
                    paragraphs[indices[0]]._element.addnext(tbl._element)

            elif action == "set_page_margin":
                sections = doc.sections
                for section in sections:
                    if "top" in params:
                        section.top_margin = Cm(params["top"])
                    if "bottom" in params:
                        section.bottom_margin = Cm(params["bottom"])
                    if "left" in params:
                        section.left_margin = Cm(params["left"])
                    if "right" in params:
                        section.right_margin = Cm(params["right"])

            logger.info("doc-edit applied: action=%s target=%s", action, target)
        except Exception as e:
            logger.warning("doc-edit op failed: %s — %s", op, e)

    base, ext = os.path.splitext(path)
    out_path = f"{base}_edited{ext}"
    doc.save(out_path)
    return out_path


@app.post("/doc-edit", summary="Edit a document via natural language instruction")
async def doc_edit(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Word document (.docx)"),
    instruction: str = Form(..., description="Natural language edit instruction"),
):
    """Module-1 endpoint: upload a .docx + a natural language instruction,
    get the edited document back."""
    if not instruction or not instruction.strip():
        raise HTTPException(status_code=400, detail="请提供编辑指令")

    temp_dir = tempfile.mkdtemp(prefix="orch_docedit_")
    background_tasks.add_task(shutil.rmtree, temp_dir, ignore_errors=True)

    fname = sanitize_filename(file.filename or "document.docx")
    ext = os.path.splitext(fname)[1].lower()
    if ext != ".docx":
        raise HTTPException(status_code=400, detail="目前仅支持 .docx 格式")

    fpath = os.path.join(temp_dir, fname)
    with open(fpath, "wb") as f:
        f.write(await file.read())

    # 1. Describe the document structure for the LLM
    try:
        doc_structure = _describe_doc_structure(fpath)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文档解析失败: {e}")

    # 2. Ask LLM to parse the instruction into operations
    prompt = llm.build_doc_edit_prompt(instruction, doc_structure)
    try:
        raw = await llm.chat(prompt, timeout=60.0)
        ops = llm.extract_json(raw)
    except llm.LLMError as e:
        raise HTTPException(status_code=500, detail=f"指令解析失败: {e}")

    if not isinstance(ops, list):
        raise HTTPException(status_code=500, detail="LLM 返回的操作格式异常")

    # 3. Apply the operations
    try:
        edited_path = _apply_edit_ops(fpath, ops)
    except Exception as e:
        logger.exception("doc-edit apply failed")
        raise HTTPException(status_code=500, detail=f"文档编辑执行失败: {e}")

    base, ext = os.path.splitext(fname)
    out_name = f"{base}_edited{ext}"
    _record_op("doc-edit", f"文件: {fname}, 指令: {instruction[:60]}")
    return FileResponse(
        path=edited_path,
        filename=out_name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ---------------------------------------------------------------------------
# Chat Agent (unified conversational entry point)
# ---------------------------------------------------------------------------

# Persistent (TTL-cleaned) storage for files generated during chat sessions.
# Files live here until the next process restart OR until manually purged.
_CHAT_RESULT_DIR = Path(tempfile.gettempdir()) / "modora_chat_results"
_CHAT_RESULT_DIR.mkdir(parents=True, exist_ok=True)


def _store_chat_result(content: bytes, ext: str) -> str:
    """Persist a result file and return its file_id."""
    file_id = uuid.uuid4().hex
    safe_ext = ext if ext.startswith(".") else f".{ext}"
    fpath = _CHAT_RESULT_DIR / f"{file_id}{safe_ext}"
    with open(fpath, "wb") as f:
        f.write(content)
    return file_id


@app.get("/agent/chat/result/{file_id}", summary="Download a chat-generated file")
def get_chat_result(file_id: str):
    """Serve a file produced by the chat agent. Guarded against path traversal."""
    if not re.fullmatch(r"[a-f0-9]{32}", file_id):
        raise HTTPException(status_code=400, detail="非法 file_id")
    matches = list(_CHAT_RESULT_DIR.glob(f"{file_id}.*"))
    if not matches:
        raise HTTPException(status_code=404, detail="结果文件不存在或已过期")
    fpath = matches[0]
    ext = fpath.suffix.lower()
    _MIME = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pdf": "application/pdf",
        ".json": "application/json",
        ".txt": "text/plain; charset=utf-8",
    }
    return FileResponse(
        path=str(fpath),
        filename=fpath.name,
        media_type=_MIME.get(ext, "application/octet-stream"),
    )


async def _classify_chat_intent(
    user_message: str,
    file_names: List[str],
) -> str:
    """LLM-driven intent classification. Falls back to keyword heuristics."""
    try:
        prompt = llm.build_intent_prompt(user_message, bool(file_names), file_names)
        raw = await llm.chat(prompt, timeout=30.0)
        parsed = llm.extract_json(raw)
        if isinstance(parsed, dict):
            intent = parsed.get("intent", "chat")
            if intent in {"doc_edit", "extract", "fill_table", "chat"}:
                return intent
    except Exception as e:
        logger.warning("intent classification failed, using heuristic: %s", e)
    # Heuristic fallback
    msg = user_message.lower()
    if any(kw in user_message for kw in ["加粗", "字体", "对齐", "排版", "标题", "缩进", "颜色", "插入", "替换"]):
        return "doc_edit"
    if any(kw in user_message for kw in ["提取", "实体", "关键信息", "摘要", "总结"]):
        return "extract"
    if any(kw in user_message for kw in ["填表", "填写", "模板", "表格"]):
        return "fill_table"
    return "chat"


@app.post("/agent/chat", summary="Unified conversational entry point")
async def agent_chat(
    background_tasks: BackgroundTasks,
    message: str = Form(..., description="User's current message"),
    history: str = Form("[]", description="JSON array of prior {role, content}"),
    files: List[UploadFile] = File(default=[], description="Attached files for this turn"),
):
    """Conversational dispatcher. Routes to the right module based on intent."""
    # 1. Save attached files to a per-request tempdir (cleaned after response)
    temp_dir = tempfile.mkdtemp(prefix="orch_chat_")
    background_tasks.add_task(shutil.rmtree, temp_dir, ignore_errors=True)

    saved: List[tuple] = []  # (filename, fpath)
    for f in files:
        if not f or not f.filename:
            continue
        name = sanitize_filename(f.filename)
        fpath = os.path.join(temp_dir, name)
        with open(fpath, "wb") as out:
            out.write(await f.read())
        saved.append((name, fpath))

    file_names = [n for n, _ in saved]

    # 2. Classify intent
    intent = await _classify_chat_intent(message, file_names)
    logger.info("agent.chat intent=%s files=%s", intent, file_names)

    # 3. Dispatch
    try:
        if intent == "doc_edit":
            return await _handle_chat_doc_edit(message, saved)
        if intent == "extract":
            return await _handle_chat_extract(message, saved)
        if intent == "fill_table":
            return _handle_chat_fill_table_redirect()
        # chat: free-form conversation
        return await _handle_chat_general(message, history, saved)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("agent.chat dispatch failed")
        return {
            "role": "assistant",
            "intent": intent,
            "content": f"很抱歉，处理时出错了: {e}",
            "result": None,
        }


# --- Per-intent handlers --------------------------------------------------

async def _handle_chat_doc_edit(user_message: str, saved: List[tuple]) -> dict:
    docx_files = [(n, p) for n, p in saved if n.lower().endswith(".docx")]
    if not docx_files:
        return {
            "role": "assistant",
            "intent": "doc_edit",
            "content": "我可以帮你编辑 Word 文档。请把需要编辑的 .docx 文件附在消息里再发送一次。",
            "result": None,
        }

    name, fpath = docx_files[0]
    try:
        doc_structure = _describe_doc_structure(fpath)
    except Exception as e:
        return {
            "role": "assistant",
            "intent": "doc_edit",
            "content": f"无法解析文档结构: {e}",
            "result": None,
        }

    prompt = llm.build_doc_edit_prompt(user_message, doc_structure)
    try:
        raw = await llm.chat(prompt, timeout=60.0)
        ops = llm.extract_json(raw)
    except llm.LLMError as e:
        return {
            "role": "assistant",
            "intent": "doc_edit",
            "content": f"无法解析您的指令: {e}",
            "result": None,
        }
    if not isinstance(ops, list):
        return {
            "role": "assistant",
            "intent": "doc_edit",
            "content": "LLM 返回了不期望的格式，请重述指令。",
            "result": None,
        }

    edited_path = _apply_edit_ops(fpath, ops)
    with open(edited_path, "rb") as f:
        content = f.read()
    base, ext = os.path.splitext(name)
    file_id = _store_chat_result(content, ext)
    out_name = f"{base}_edited{ext}"

    _record_op("agent.doc-edit", f"{name}: {user_message[:50]}")
    return {
        "role": "assistant",
        "intent": "doc_edit",
        "content": f"已对《{name}》执行 {len(ops)} 个编辑操作，点击下方下载。",
        "result": {
            "type": "file_download",
            "file_id": file_id,
            "filename": out_name,
            "size": len(content),
            "operations": ops,
        },
    }


async def _handle_chat_extract(user_message: str, saved: List[tuple]) -> dict:
    if not saved:
        return {
            "role": "assistant",
            "intent": "extract",
            "content": "请先上传一份文档（.docx / .pdf / .xlsx / .md / .txt），我帮你提取关键信息。",
            "result": None,
        }

    name, fpath = saved[0]
    ext = os.path.splitext(name)[1].lower()
    supported = {".md", ".txt", ".docx", ".xlsx", ".xls", ".pdf"}
    if ext not in supported:
        return {
            "role": "assistant",
            "intent": "extract",
            "content": f"暂不支持 {ext} 格式。支持: {', '.join(sorted(supported))}",
            "result": None,
        }

    doc_text = read_document_text(fpath)
    if not doc_text or not doc_text.strip():
        return {
            "role": "assistant",
            "intent": "extract",
            "content": f"无法从《{name}》中读取文本，可能是扫描件或加密文档。",
            "result": None,
        }
    doc_text = _truncate_docs(doc_text, limit=MAX_DOCS_CHARS_PER_CHANNEL)

    prompt = llm.build_extract_prompt(doc_text, user_message)
    try:
        raw = await llm.chat(prompt, timeout=90.0)
        result = llm.extract_json(raw)
    except llm.LLMError as e:
        return {
            "role": "assistant",
            "intent": "extract",
            "content": f"信息提取失败: {e}",
            "result": None,
        }
    if not isinstance(result, dict):
        result = {"raw": result}

    n_ent = len(result.get("entities") or [])
    n_keys = len(result.get("key_info") or {})
    summary_preview = (result.get("summary") or "").strip()
    reply = f"已从《{name}》提取出 {n_ent} 个实体、{n_keys} 个关键信息字段。"
    if summary_preview:
        reply += f"\n\n**摘要**: {summary_preview[:200]}"

    _record_op("agent.extract", f"{name}: {user_message[:50]}")
    return {
        "role": "assistant",
        "intent": "extract",
        "content": reply,
        "result": {
            "type": "extract_data",
            "filename": name,
            "data": result,
        },
    }


def _handle_chat_fill_table_redirect() -> dict:
    return {
        "role": "assistant",
        "intent": "fill_table",
        "content": (
            "表格智能填写需要协调多份素材文件（Excel/Word/MD），"
            "聊天模式难以一次完成。请打开侧栏的"
            "「专家模式 → 表格智能填写」，按引导分步上传素材和模板。"
        ),
        "result": {
            "type": "redirect",
            "url": "/table-fill",
            "label": "去表格填写页",
        },
    }


async def _handle_chat_general(
    user_message: str,
    history_json: str,
    saved: List[tuple],
) -> dict:
    """Free-form chat. If files are attached, mention their content briefly."""
    try:
        history = json.loads(history_json) if history_json else []
    except (json.JSONDecodeError, TypeError):
        history = []

    file_context = ""
    if saved:
        snippets = []
        for name, fpath in saved[:3]:
            text = read_document_text(fpath)
            if text:
                snippets.append(f"=== {name} (前 1500 字) ===\n{text[:1500]}")
        if snippets:
            file_context = "\n\n【附带文档内容】\n" + "\n\n".join(snippets) + "\n"

    history_text = ""
    if history:
        history_text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')[:300]}"
            for m in history[-6:]
        )
        history_text = f"\n\n【对话历史】\n{history_text}\n"

    prompt = (
        "你是 MoDora 智能文档助手。请用中文友好回答用户问题。"
        "如果用户附带了文档，请基于文档内容回答；如果没有，按通用知识回答。"
        "回答控制在 200 字以内，简洁清晰。\n"
        f"{history_text}"
        f"{file_context}\n"
        f"用户当前消息: {user_message}\n"
    )
    try:
        reply = await llm.chat(prompt, timeout=60.0)
    except llm.LLMError as e:
        reply = f"暂时无法回复: {e}"

    return {
        "role": "assistant",
        "intent": "chat",
        "content": reply.strip(),
        "result": None,
    }


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
