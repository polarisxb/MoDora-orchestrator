"""Dispatch questions to the three backend channels with timeout isolation.

Channel layout (matches the user-specified architecture)
--------------------------------------------------------
- ``excel``   : handled in-process by ``excel_matcher`` (header-to-header match
                + LLM fallback). Currently still routes through HTTP for
                backwards compatibility; B1 will short-circuit this channel so
                ``dispatch()`` never posts over the network for Excel.
- ``md_txt``  : MoDora-A, POST ``/chat``  (md / txt reference files only)
- ``word``    : MoDora-B, POST ``/chat``  (docx reference files only)

Each channel is called with the **same question** but a **type-matched file
subset**. A channel that has no files in its subset is silently skipped, so
dispatch never fans out to a backend that cannot possibly know the answer.

The MoDora /chat request / response shapes are fixed upstream; we adapt them
here so the rest of the orchestrator only sees a canonical :class:`Candidate`.
See ``MoDora-backend/src/modora/api/v1/models.py`` for the authoritative
schema (``ChatRequest`` / ``ChatResponse``).
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    channel: str
    answer: Optional[str]
    status: str        # "found" | "not_found" | "error"
    confidence: float
    source: str = ""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CHANNEL_URLS: Dict[str, str] = {
    # excel: will be short-circuited in dispatch() once B1 lands; URL kept for
    # backward compatibility but in practice not reached.
    "excel":  os.environ.get("BACKEND_EXCEL_URL",  "http://127.0.0.1:9001/api/solve"),
    # md_txt: MoDora-A instance. Path must be /api/chat (see MoDora app.py).
    "md_txt": os.environ.get("BACKEND_MD_TXT_URL", "http://127.0.0.1:8005/api/chat"),
    # word: MoDora-B instance (separate port if you run two MoDora processes).
    "word":   os.environ.get("BACKEND_WORD_URL",   "http://127.0.0.1:8006/api/chat"),
}

# When two channels return the same coord, higher priority wins ties.
# Textual channels win over Excel's pure-LLM because structural / retrieval
# grounding is usually stronger evidence.
CHANNEL_PRIORITY: Dict[str, int] = {"md_txt": 3, "word": 3, "excel": 2}

_BACKEND_TIMEOUT = float(os.environ.get("BACKEND_TIMEOUT", "60"))

# Shared connection pool — avoids TCP setup/teardown on every /chat call.
_http_pool: Optional[httpx.AsyncClient] = None


async def _get_pool() -> httpx.AsyncClient:
    global _http_pool
    if _http_pool is None or _http_pool.is_closed:
        _http_pool = httpx.AsyncClient(
            timeout=_BACKEND_TIMEOUT, trust_env=False,
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
        )
    return _http_pool


# ---------------------------------------------------------------------------
# Invalid-value detection
# ---------------------------------------------------------------------------

# NOTE: All comparisons go through ``str.lower()`` so MoDora's literal
# ``"None"`` (see qa_service.py when retrieval yields 0 results) and ``"No answer"``
# (chat.py ``qa_result.get("answer", "No answer")`` fallback) are covered by the
# lowercase entries ``"none"`` and ``"no answer"`` respectively.
_INVALID_EXACT = {
    "", "null", "none", "n/a", "na", "nan", "error",
    "未找到", "未查到", "未获取", "未获取到", "未获取到有效数据",
    "未知", "无", "暂无", "不适用", "无法确定", "无法回答", "无法找到",
    "无相关信息", "信息不足", "no answer", "not found",
}
_INVALID_PREFIXES = (
    "未找到", "未能", "无法", "不适用", "没有找到", "没找到",
    "no answer", "not found", "cannot", "can't",
)


def is_invalid_answer(ans: Optional[str]) -> bool:
    if ans is None:
        return True
    s = str(ans).strip()
    if not s:
        return True
    sl = s.lower()
    if sl in _INVALID_EXACT:
        return True
    for prefix in _INVALID_PREFIXES:
        if sl.startswith(prefix.lower()):
            return True
    return False


# ---------------------------------------------------------------------------
# Per-channel call
# ---------------------------------------------------------------------------

def _wrap_response(channel: str, data: Any) -> Candidate:
    """Canonicalise a generic ``{answer, status?, confidence?, source?}`` payload.

    Used for legacy / non-MoDora channels (currently only ``excel`` before B1
    lands).
    """
    if isinstance(data, dict):
        answer = data.get("answer")
        status = data.get("status")
        if not status:
            status = "found" if not is_invalid_answer(answer) else "not_found"
        try:
            confidence = float(data.get("confidence", 0.5 if status == "found" else 0.0))
        except (TypeError, ValueError):
            confidence = 0.5 if status == "found" else 0.0
        source = str(data.get("source") or channel)
        return Candidate(channel=channel, answer=answer, status=status,
                         confidence=confidence, source=source)
    # legacy: plain string / number
    answer = None if data is None else str(data)
    status = "found" if not is_invalid_answer(answer) else "not_found"
    return Candidate(channel=channel, answer=answer, status=status,
                     confidence=0.5 if status == "found" else 0.0, source=channel)


def _wrap_modora_response(channel: str, data: Any) -> Candidate:
    """Adapt MoDora's ``ChatResponse`` into a :class:`Candidate`.

    MoDora shape (see ``modora.api.v1.models.ChatResponse``)::

        {
          "answer": str,
          "reasoning_log": str,
          "retrieved_documents": [{file_name, page, content, bboxes, score}, ...],
          "node_impacts": {...}
        }
    """
    if not isinstance(data, dict):
        return Candidate(channel=channel, answer=None, status="error",
                         confidence=0.0, source=f"{channel}:bad-shape")

    answer = data.get("answer")
    status = "found" if not is_invalid_answer(answer) else "not_found"
    confidence = 0.6 if status == "found" else 0.0  # MoDora grounding > pure LLM
    source = channel

    retrieved = data.get("retrieved_documents") or []
    if isinstance(retrieved, list) and retrieved:
        first = retrieved[0] if isinstance(retrieved[0], dict) else None
        if first is not None:
            fn = first.get("file_name") or ""
            page = first.get("page", 0)
            source = f"{channel}:{fn}:p{page}" if fn else f"{channel}:p{page}"
            try:
                score = float(first.get("score") or 0.0)
                if score > 0:
                    confidence = max(confidence, min(1.0, score))
            except (TypeError, ValueError):
                pass

    return Candidate(channel=channel, answer=answer, status=status,
                     confidence=confidence, source=source)


def _build_payload(
    channel: str,
    question: str,
    file_paths: List[str],
    coord: str,
    requirement: str,
) -> Dict[str, Any]:
    """Channel-specific request body.

    MoDora's ``/chat`` has no ``requirement`` field so we inline the constraint
    into ``query``. We send **file basenames** (not absolute paths) because
    MoDora resolves them against its own ``paths.docs_dir``.
    """
    if channel in ("md_txt", "word"):
        if requirement and requirement.strip():
            query_text = f"【约束: {requirement.strip()}】\n{question}"
        else:
            query_text = question
        return {
            "file_names": [os.path.basename(p) for p in file_paths],
            "query": query_text,
            "settings": {},
        }
    # excel (legacy until B1) -- generic coord/question shape
    return {
        "coord": coord,
        "question": question,
        "file_paths": file_paths,
        "requirement": requirement,
    }


async def _call_one(
    channel: str,
    question: str,
    file_paths: List[str],
    coord: str,
    requirement: str,
) -> Candidate:
    url = CHANNEL_URLS[channel]
    payload = _build_payload(channel, question, file_paths, coord, requirement)

    try:
        client = await _get_pool()
        resp = await client.post(url, json=payload)
    except httpx.TimeoutException:
        logger.warning("backend %s timeout after %.1fs (coord=%s)", channel, _BACKEND_TIMEOUT, coord)
        return Candidate(channel=channel, answer=None, status="error",
                         confidence=0.0, source=f"{channel}:timeout")
    except httpx.HTTPError as e:
        logger.warning("backend %s network error: %s", channel, e)
        return Candidate(channel=channel, answer=None, status="error",
                         confidence=0.0, source=f"{channel}:network")

    if resp.status_code != 200:
        logger.warning("backend %s http %d: %s", channel, resp.status_code, resp.text[:200])
        return Candidate(channel=channel, answer=None, status="error",
                         confidence=0.0, source=f"{channel}:http{resp.status_code}")

    try:
        data = resp.json()
    except ValueError:
        return Candidate(channel=channel, answer=None, status="error",
                         confidence=0.0, source=f"{channel}:bad-json")

    if channel in ("md_txt", "word"):
        return _wrap_modora_response(channel, data)
    return _wrap_response(channel, data)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _health_url(chat_url: str) -> str:
    """Derive the /health endpoint from a /api/chat URL on the same host.

    ``http://127.0.0.1:8005/api/chat`` -> ``http://127.0.0.1:8005/health``

    We keep this separate from ``CHANNEL_URLS`` because the /chat path is
    controller-owned but /health is app-wide (mounted directly on FastAPI).
    """
    parsed = urlparse(chat_url)
    return urlunparse((parsed.scheme, parsed.netloc, "/health", "", "", ""))


_DEFAULT_PROBE_CHANNELS = ("md_txt", "word")


async def probe_channels(
    channels: Optional[List[str]] = None,
    *,
    timeout: float = 2.0,
) -> Dict[str, bool]:
    """Return ``{channel: True/False}`` based on /health reachability.

    A channel is considered healthy iff its /health endpoint returns HTTP 200
    within ``timeout`` seconds. Any network error, non-200 status, or timeout
    classifies it as unhealthy — callers should drop unhealthy channels from
    ``files_by_channel`` so they never get a 60s /chat timeout per question.

    The default 2-second timeout is intentionally aggressive: if the process
    is alive, /health responds in < 50 ms. If it takes > 2 s, something is
    already broken and we shouldn't wait for each individual /chat to find
    that out the slow way.
    """
    targets = list(channels) if channels else list(_DEFAULT_PROBE_CHANNELS)

    async def _one(channel: str) -> tuple:
        url = CHANNEL_URLS.get(channel)
        if not url:
            return channel, False
        health = _health_url(url)
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.get(health)
                return channel, resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("probe %s (%s) failed: %s", channel, health, e)
            return channel, False

    results = await asyncio.gather(*[_one(c) for c in targets])
    return dict(results)


async def dispatch(
    question: str,
    coord: str,
    files_by_channel: Dict[str, List[str]],
    requirement: str = "",
) -> List[Candidate]:
    """Broadcast ``question`` to every channel that has at least one file.

    Returns a list of up-to-three candidates, one per participating channel,
    in completion order. Callers typically pass the result through
    :func:`pick_best` to collapse to a single answer.
    """
    tasks = []
    for channel in ("excel", "md_txt", "word"):
        paths = files_by_channel.get(channel) or []
        if not paths:
            continue
        tasks.append(_call_one(channel, question, paths, coord, requirement))
    if not tasks:
        return []
    return list(await asyncio.gather(*tasks))


def pick_best(candidates: List[Candidate]) -> Optional[Candidate]:
    """Pick a single winner across channels for one coordinate."""
    valid = [c for c in candidates
             if c.status == "found" and not is_invalid_answer(c.answer)]
    if not valid:
        return None
    valid.sort(
        key=lambda c: (CHANNEL_PRIORITY.get(c.channel, 0), c.confidence),
        reverse=True,
    )
    return valid[0]
