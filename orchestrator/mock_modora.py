"""Lightweight MoDora mock for orchestrator smoke tests.

What it implements
------------------
- ``POST /api/upload`` — stores the uploaded file to a local ``docs`` dir,
  immediately marks it ``completed`` (real MoDora runs OCR + tree build in
  the background; we skip both and pretend the tree is ready).
- ``GET  /api/task/status/{filename}`` — always returns ``completed`` for
  uploaded files, ``unknown`` otherwise.
- ``POST /api/chat`` — reads the referenced PDFs with pymupdf, stuffs their
  text into a prompt, asks DashScope (via :mod:`orchestrator.llm`) to answer
  the query, and returns a :class:`ChatResponse`-shaped JSON body.

Why this is enough for end-to-end tests
---------------------------------------
Behaviour the orchestrator relies on:
  1. Upload echoes a filename it can poll.
  2. Status eventually flips to ``completed``.
  3. /chat returns ``{answer, retrieved_documents}`` with a real string.
All three are honoured. The mock does **not** build a CCTree and has no
retrieval scoring, so it will never be as sharp as real MoDora on long
documents, but it is more than adequate for validating that the
orchestrator's ingest + process plumbing is wired correctly end-to-end.

Run
---
Two instances, one per channel (same binary, different port + docs dir)::

    # md_txt channel
    python -m uvicorn orchestrator.mock_modora:app --port 8005
    # word channel  (use MOCK_DOCS_DIR so the two instances don't collide)
    $env:MOCK_DOCS_DIR = 'C:\\tmp\\mock_modora_word'
    python -m uvicorn orchestrator.mock_modora:app --port 8006
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

# Load .env so DashScope credentials flow into this process too.
# Same dual-path fallback as service.py: try repo root first, then cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
for _cand in (_REPO_ROOT / ".env", Path.cwd() / ".env"):
    if _cand.exists():
        from dotenv import load_dotenv
        load_dotenv(_cand, override=False)
        break

from orchestrator import llm  # noqa: E402  (after load_dotenv)

logger = logging.getLogger("mock_modora")
logging.basicConfig(
    level=os.environ.get("MOCK_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


# ---------------------------------------------------------------------------
# Config + storage
# ---------------------------------------------------------------------------

DOCS_DIR = Path(
    os.environ.get("MOCK_DOCS_DIR")
    or (Path(tempfile.gettempdir()) / "mock_modora_docs")
)
DOCS_DIR.mkdir(parents=True, exist_ok=True)

# filename -> "completed" | "processing" | "failed"
_STATUS: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    file_names: List[str]
    query: str
    settings: Optional[dict] = None


class RetrievedDoc(BaseModel):
    file_name: str
    snippet: str = ""


class ChatResponse(BaseModel):
    answer: str
    retrieved_documents: List[RetrievedDoc] = []


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title=f"mock-modora ({DOCS_DIR})")


@app.get("/health")
def health():
    return {"status": "ok", "docs_dir": str(DOCS_DIR), "known": len(_STATUS)}


@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    settings: Optional[str] = Form(None),  # noqa: ARG001 (ignored, matches real MoDora)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename missing")
    dst = DOCS_DIR / file.filename
    content = await file.read()
    dst.write_bytes(content)
    # Real MoDora runs OCR + tree build in the background; the mock treats
    # everything as immediately ready so orchestrator /ingest returns fast.
    _STATUS[file.filename] = "completed"
    logger.info("upload %s (%d bytes) -> completed", file.filename, len(content))
    return {
        "filename": file.filename,
        "status": "uploaded",
        "message": "ok (mock: tree pre-built)",
    }


@app.get("/api/task/status/{filename}")
def task_status(filename: str):
    return {"status": _STATUS.get(filename, "unknown")}


# ---------------------------------------------------------------------------
# /api/chat
# ---------------------------------------------------------------------------

def _read_pdf_text(path: Path, page_limit: int = 20, char_limit: int = 30_000) -> str:
    """Shallow text extraction. Enough for a mock; real MoDora uses OCR + tree."""
    try:
        import fitz  # pymupdf
    except ImportError:
        return ""
    chunks: list[str] = []
    try:
        with fitz.open(str(path)) as doc:
            for i, page in enumerate(doc):
                if i >= page_limit:
                    break
                chunks.append(page.get_text("text") or "")
    except Exception:
        logger.exception("mock: failed to read %s", path)
        return ""
    text = "\n".join(chunks)
    return text[:char_limit]


def _build_prompt(query: str, docs: list[tuple[str, str]]) -> str:
    """Pack referenced documents into a RAG-style prompt for DashScope.

    ``docs`` is ``[(filename, text), ...]``. We deliberately keep the prompt
    small and forceful about MoDora's answer contract: prefer short, direct
    values; say ``No answer`` when nothing relevant is found.
    """
    joined = []
    for fn, text in docs:
        if not text.strip():
            continue
        joined.append(f"=== {fn} ===\n{text}")
    doc_block = "\n\n".join(joined) if joined else "(no document text available)"
    return (
        "你正在为表格填充提供数据。严格依据下列参考文档回答问题:\n"
        "  - 回答应当尽量简短、直接,只给值(如数字、姓名、日期),不要解释。\n"
        "  - 如果文档里没有明确答案,回复 `No answer`。\n"
        "  - 不允许编造内容。\n\n"
        f"【参考文档】\n{doc_block}\n\n"
        f"【问题】{query}\n\n"
        "【答案】"
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    missing = [fn for fn in req.file_names if not (DOCS_DIR / fn).exists()]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"No valid document trees found for: {missing}",
        )

    docs: list[tuple[str, str]] = []
    for fn in req.file_names:
        text = _read_pdf_text(DOCS_DIR / fn)
        docs.append((fn, text))

    prompt = _build_prompt(req.query, docs)
    # qwen-turbo answers short-factoid prompts in 2-5 s; qwen-plus is closer
    # to 10-20 s which blows the orchestrator's default BACKEND_TIMEOUT.
    model = os.environ.get("MOCK_MODORA_MODEL", "qwen-turbo")
    try:
        raw = await llm.chat(prompt, model=model, timeout=18.0)
    except llm.LLMError:
        logger.exception("mock /chat LLM failure")
        # MoDora-shaped "unanswerable" response: orchestrator treats this as
        # a soft miss, not a network error, which is the correct semantics
        # when the underlying tree/LLM has no grounded answer.
        return ChatResponse(answer="No answer", retrieved_documents=[])
    answer = (raw or "").strip() or "No answer"
    logger.info("chat query=%r files=%s -> %r", req.query, req.file_names, answer[:80])
    return ChatResponse(
        answer=answer,
        retrieved_documents=[
            RetrievedDoc(file_name=fn, snippet=(docs[i][1][:120]))
            for i, fn in enumerate(req.file_names)
        ],
    )


@app.post("/admin/reset")
def reset():
    """Wipe the mock state; handy between test runs."""
    shutil.rmtree(DOCS_DIR, ignore_errors=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    _STATUS.clear()
    return {"status": "reset"}
