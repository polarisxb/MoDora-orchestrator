"""LLM helpers and prompt builders.

All network-bound work goes through ``chat`` so we can inject retries/telemetry
in one place later. ``extract_json`` tolerates the common LLM quirks
(markdown fences, leading prose, trailing commas) and will raise
``LLMError`` if nothing parseable is present.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when an LLM call fails or its response cannot be parsed."""


LLM_API_URL = os.environ.get(
    "LLM_API_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
)
LLM_MODEL_FAST = os.environ.get("LLM_MODEL_FAST", "qwen-plus")
LLM_MODEL_LONG = os.environ.get("LLM_MODEL_LONG", "qwen-long")

# Retry knobs. Tuned for DashScope which reliably 429s under contest-grade
# parallelism but recovers within a second or two. The backoff cap keeps the
# p99 latency bounded: max 3 sleeps of ~2+4+8s = 14s on top of the request.
_LLM_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "3"))
_LLM_BACKOFF_BASE = float(os.environ.get("LLM_BACKOFF_BASE", "1.5"))
_LLM_BACKOFF_CAP = float(os.environ.get("LLM_BACKOFF_CAP", "10"))

# HTTP statuses that warrant a retry. Everything else (400 / 401 / 404) is a
# client bug and retrying only masks it.
_RETRIABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


def _get_api_key() -> str:
    key = (os.environ.get("LLM_API_KEY") or "").strip()
    if not key or key == "replace-me":
        raise LLMError(
            "LLM_API_KEY is empty or still the placeholder. "
            "Set it in .env at the repository root."
        )
    return key


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json|JSON)?\s*|\s*```$")
_JSON_BLOCK_RE = re.compile(r"(\{[\s\S]*\}|\[[\s\S]*\])")


def extract_json(raw: str) -> Any:
    """Parse JSON from a possibly messy LLM response."""
    if raw is None:
        raise LLMError("empty LLM response")
    cleaned = raw.strip()
    cleaned = _FENCE_RE.sub("", cleaned).strip()
    # fast path
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(cleaned)
    if not match:
        raise LLMError(f"no JSON object/array in LLM response: {raw!r}")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise LLMError(f"malformed JSON in LLM response: {e}; raw={raw!r}") from e


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

def _compute_backoff(attempt: int, retry_after: Optional[str]) -> float:
    """Exponential backoff with a touch of jitter, honouring Retry-After.

    If the server told us how long to wait (e.g. DashScope sometimes sets
    ``Retry-After: 1``), we trust it up to the cap. Otherwise fall back to
    ``base ** attempt`` plus 0-0.5s jitter to avoid thundering herds when
    several in-flight calls all fail at the same timestamp.
    """
    if retry_after:
        try:
            return min(float(retry_after), _LLM_BACKOFF_CAP)
        except ValueError:
            pass
    delay = min(_LLM_BACKOFF_BASE ** attempt, _LLM_BACKOFF_CAP)
    return delay + random.uniform(0.0, 0.5)


async def chat(
    prompt: str,
    *,
    model: Optional[str] = None,
    timeout: float = 60.0,
    temperature: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> str:
    """Send a single-turn chat completion request and return the assistant message.

    Resiliency contract
    -------------------
    - Network errors (timeout, connection reset, DNS) are retried with
      exponential backoff.
    - HTTP statuses in :data:`_RETRIABLE_HTTP` (429, 5xx, 408, 425) are
      retried the same way, honouring ``Retry-After`` when present.
    - 4xx client errors (other than the retriable ones above) raise
      :class:`LLMError` immediately — retrying a malformed request is futile.
    - After ``max_retries`` attempts a terminal :class:`LLMError` is raised;
      the caller (``_detect_structure``, ``_route_channel_files``, etc.) is
      responsible for deciding whether to fall back gracefully or propagate.
    """
    model = model or LLM_MODEL_FAST
    attempts = _LLM_MAX_RETRIES if max_retries is None else max(1, max_retries)
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    if temperature is not None:
        payload["temperature"] = temperature

    last_detail = "unknown"
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    LLM_API_URL,
                    headers={"Authorization": f"Bearer {_get_api_key()}"},
                    json=payload,
                )
        except httpx.HTTPError as e:
            last_detail = f"network: {e}"
            if attempt + 1 >= attempts:
                raise LLMError(f"LLM network error after {attempts} attempts: {e}") from e
            delay = _compute_backoff(attempt, None)
            logger.warning(
                "llm.chat network error (attempt %d/%d, model=%s): %s — retrying in %.1fs",
                attempt + 1, attempts, model, e, delay,
            )
            await asyncio.sleep(delay)
            continue

        if resp.status_code == 200:
            try:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as e:
                raise LLMError(
                    f"LLM unexpected response: {e}; body={resp.text[:400]}"
                ) from e

        last_detail = f"http{resp.status_code}: {resp.text[:200]}"
        if resp.status_code in _RETRIABLE_HTTP and attempt + 1 < attempts:
            delay = _compute_backoff(attempt, resp.headers.get("Retry-After"))
            logger.warning(
                "llm.chat http %d (attempt %d/%d, model=%s) — retrying in %.1fs",
                resp.status_code, attempt + 1, attempts, model, delay,
            )
            await asyncio.sleep(delay)
            continue

        # Non-retriable HTTP or retries exhausted: surface immediately.
        raise LLMError(f"LLM http {resp.status_code}: {resp.text[:400]}")

    # Should be unreachable — loop either returns or raises — but keeps the
    # type checker happy.
    raise LLMError(f"LLM exhausted {attempts} attempts: {last_detail}")


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _format_requirement(requirement: str) -> str:
    r = (requirement or "").strip()
    if not r:
        return ""
    return (
        "【用户填表要求 / 约束】(必须严格遵守,不符合约束的数据一律剔除):\n"
        f"{r}\n"
    )


def build_structure_prompt(
    context: str,
    headers: List[str],
    requirement: str,
) -> str:
    return (
        "你是表格结构分析助手。\n"
        + _format_requirement(requirement)
        + f"【表格上下文】: {context or '(无)'}\n"
        + f"【表头(从左到右)】: {headers}\n\n"
        "判断每一列的角色:\n"
        "  - 父列 (parent):用来唯一标识实体的维度,如城市 / 区 / 站点名 / 公司名 / 排名。\n"
        "  - 子列 (child):待查询的数值或属性指标,如 GDP / 人口 / AQI / 收入、类别、分类、部门、负责人、时间。\n"
        "规则:\n"
        "  1. 父列通常在左侧,子列通常在右侧,但不绝对。\n"
        "  2. **父列必须是唯一标识符**,不能由其他列推导得出。\n"
        "     - 若单列已能唯一标识实体(如产品名称、股票代码、员工姓名、身份证号),则仅该列为父列。\n"
        "     - 只有当单列不足以唯一标识(如行政区需要 '省'+'市'+'区')时,才把多列合并为父列。\n"
        "  3. 描述性 / 从属性的列(如 '类别' 跟随 '产品名称','部门' 跟随 '员工')一律归为子列——\n"
        "     这些列在文档中是参考,而不是查询键。\n"
        "  4. 所有列索引从 0 开始。\n\n"
        "严格只返回 JSON,禁止任何解释、禁止 Markdown 代码块。\n"
        '示例 1: 表头 ["产品名称","类别","售价","上线时间"] -> {"parent_columns": [0], "child_columns": [1, 2, 3]}\n'
        '示例 2: 表头 ["省","市","GDP","人口"]           -> {"parent_columns": [0, 1], "child_columns": [2, 3]}\n'
    )


def build_entities_prompt(
    docs_content: str,
    context: str,
    parent_headers: List[str],
    child_headers: List[str],
    requirement: str,
) -> str:
    return (
        "你是数据挖掘专家,任务是从冗杂文档中提取用于填表的父类实体组合。\n"
        + _format_requirement(requirement)
        + f"【填表业务上下文】: {context or '(无)'}\n"
        + f"【父类列(按顺序)】: {parent_headers}\n"
        + f"【后续要查询的子列指标】: {child_headers}\n\n"
        "规则:\n"
        "  1. 只能提取文档中真实出现的实体,绝不可凭空编造。\n"
        "  2. 必须满足用户约束(日期 / 地域 / 主题等),不符合的剔除。\n"
        "  3. 若有多列父类,返回每一行有效的组合,且列顺序与【父类列】一致。\n"
        "  4. 去重;同一实体只出现一次。\n\n"
        "【文档数据全集】:\n"
        f"{docs_content}\n\n"
        "严格只返回 JSON 二维数组,禁止解释、禁止 Markdown 代码块。\n"
        '示例: [["上海市"], ["北京市"]]\n'
        "若无匹配项: []\n"
    )


def build_route_prompt(
    requirement: str,
    parent_headers: List[str],
    child_headers: List[str],
    parent_rows: List[List[str]],
    file_briefs: List[Tuple[str, str]],
    top_k: int,
) -> str:
    """Ask the LLM to pick the ``top_k`` files most likely to answer this table.

    ``file_briefs`` is ``[(filename, first_few_hundred_chars), ...]``. The
    filename alone is often enough ("2024-德州市-GDP.md" obviously matches a
    德州 GDP table) but we pass a short head-of-file excerpt too so the model
    can disambiguate generic names.

    Return-format contract: the LLM replies with a JSON array of indices into
    ``file_briefs``, e.g. ``[0, 3]``. Any other shape is treated as a failed
    route and the caller falls back to "keep all files".
    """
    rows_preview = parent_rows[:8]  # avoid flooding the prompt with 100-row tables
    rows_json = json.dumps(rows_preview, ensure_ascii=False)
    briefs_text = "\n\n".join(
        f"[{i}] 文件名: {fn}\n摘要(前 {min(len(brief), 400)} 字): {brief[:400]}"
        for i, (fn, brief) in enumerate(file_briefs)
    )
    return (
        "你是素材路由员。从下列候选文件中挑出最可能回答当前填表任务的若干份。\n"
        + _format_requirement(requirement)
        + f"【父列表头】: {parent_headers}\n"
        + f"【子列表头】: {child_headers}\n"
        + f"【待查询的部分父实体行(最多 8 行样例)】: {rows_json}\n\n"
        + f"【候选文件共 {len(file_briefs)} 份】:\n{briefs_text}\n\n"
        + f"从中挑出最多 {top_k} 份最相关的文件。若候选文件总体都相关,挑最具体的前 {top_k} 份。\n"
        "严格只返回 JSON 数组形式的索引,如 [0, 2]。禁止任何其他文字、禁止 Markdown 代码块。\n"
        "若无相关文件,返回 []。"
    )


def render_question(
    parent_values: Dict[str, str],
    child_header: str,
    requirement: str,  # noqa: ARG001 (kept for signature stability; see NOTE)
) -> str:
    """Deterministic question template — no extra LLM round-trip.

    ``parent_values`` is an ordered ``{header_name: value}`` dict, e.g.
    ``{"城市": "德州市", "区": "东城区"}``.

    NOTE: ``requirement`` is intentionally **not** inlined here. The MoDora
    path relies on :func:`backend_client._build_payload` to prefix the query
    with ``【约束: ...】`` exactly once. Inlining it both here and there
    produced duplicated constraint clauses (observed triggering hallucinated
    ``No answer`` replies from qwen-turbo under load).
    """
    if parent_values:
        parent_clause = "、".join(f"{k}为{v}" for k, v in parent_values.items() if v)
        return f"{parent_clause} 的 {child_header} 是多少?"
    return f"{child_header} 是多少?"


def build_batch_child_prompt(
    docs_content: str,
    requirement: str,
    parent_headers: List[str],
    child_header: str,
    parent_rows: List[Dict[str, str]],
) -> str:
    """Build a prompt that extracts *child_header* for ALL *parent_rows* at once.

    This is the key performance optimisation: instead of N individual /chat
    round-trips (one per row), we make ONE LLM call per child column and get
    back a JSON array of values in the same order as ``parent_rows``.

    Return contract: a JSON array of strings (or ``null`` for unknowns),
    **same length and order** as ``parent_rows``.
    """
    rows_json = json.dumps(parent_rows, ensure_ascii=False)
    return (
        "你是数据提取专家。请从文档中为下列每一行提取指定指标的值。\n\n"
        + _format_requirement(requirement)
        + f"【要提取的指标】: {child_header}\n"
        + f"【父列名称】: {json.dumps(parent_headers, ensure_ascii=False)}\n\n"
        + f"【待查询的行】(共 {len(parent_rows)} 行, JSON 数组):\n{rows_json}\n\n"
        + f"【文档数据】:\n{docs_content}\n\n"
        "规则:\n"
        "  1. 返回一个 JSON 数组，长度必须等于待查询行数，顺序一一对应。\n"
        "  2. 值为字符串；若文档中没有对应数据，填 null。\n"
        "  3. 只提取文档中明确存在的值，不可编造。\n"
        "  4. 数值保留原始精度（不要四舍五入）。\n\n"
        "严格只返回 JSON 数组，禁止解释、禁止 Markdown 代码块。\n"
        '示例: ["1.23", "0.87", null, "2.15"]\n'
    )


def build_excel_filter_prompt(
    context: str,
    requirement: str,
    available_headers: List[str],
) -> str:
    """Ask the LLM to extract column-level row filters from context + requirement.

    The reply contract is a JSON array of filter objects::

        [
          {"column": "城市", "value": "德州市"},
          {"column": "日期", "start": "2020-07-01", "end": "2020-08-31"}
        ]

    - ``value`` → exact / substring match  (normalised, case-insensitive).
    - ``start`` / ``end`` → inclusive range comparison on the raw cell text.
      Dates should be normalised to ``YYYY-MM-DD`` by the LLM.
    - An empty array ``[]`` means "no filtering needed" (all rows pass).
    """
    headers_str = json.dumps(available_headers, ensure_ascii=False)
    return (
        "你是数据过滤专家。根据下面的【表格上下文】和【用户要求】，判断 Excel "
        "参考数据中哪些列需要按条件过滤，只保留符合要求的行。\n\n"
        + _format_requirement(requirement)
        + f"【表格上下文(描述当前要填的表)】:\n{context or '(无)'}\n\n"
        + f"【Excel 参考数据可用的列名】:\n{headers_str}\n\n"
        "规则:\n"
        "  1. 只返回有明确约束值的列。没有约束的列不要出现。\n"
        "  2. 精确值用 {\"column\":\"列名\", \"value\":\"值\"} 格式。\n"
        "  3. 日期/数值范围用 {\"column\":\"列名\", \"start\":\"起始\", \"end\":\"结束\"} 格式，"
        "日期统一 YYYY-MM-DD。\n"
        "  4. 如果上下文和要求都没有给出任何过滤条件，返回空数组 []。\n\n"
        "严格只返回 JSON 数组，禁止解释、禁止 Markdown 代码块。\n"
        '示例: [{"column":"城市","value":"德州市"},{"column":"日期","start":"2020-07-01","end":"2020-08-31"}]\n'
        "无过滤时: []\n"
    )
