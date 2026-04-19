"""HTTP client for MoDora's ingest-side endpoints.

The orchestrator uses three MoDora endpoints:

- ``POST  /api/upload``           — submit a PDF, start background OCR + tree.
- ``GET   /api/task/status/{fn}`` — poll until the tree is ready.
- ``POST  /api/chat``             — query the tree (handled elsewhere in
                                    :mod:`backend_client`).

This module only covers the first two, i.e. the ingest / readiness workflow.
Query-time ``/chat`` calls stay in :mod:`backend_client` because they ride a
different lifecycle (short-lived, per-question).

Routing convention
------------------
The caller passes the *chat* URL of the target MoDora instance (as stored
in :data:`orchestrator.backend_client.CHANNEL_URLS`). We strip the trailing
``/chat`` segment to obtain the base URL, keeping this module ignorant of
the overall deployment topology.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_UPLOAD_TIMEOUT = float(os.environ.get("MODORA_UPLOAD_TIMEOUT", "90"))
# OCR + tree construction dominates the budget; allow several minutes for a
# large document. The ingest endpoint is called at most once per source per
# process so this timeout only hurts *unrecoverable* builds.
_READY_TIMEOUT = float(os.environ.get("MODORA_READY_TIMEOUT", "600"))
_POLL_INTERVAL = float(os.environ.get("MODORA_POLL_INTERVAL", "2"))

# Any of these ends the poll loop. Everything else is treated as "still cooking".
_TERMINAL_STATUSES = {"completed", "failed"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class MoDoraClientError(Exception):
    """Upload, polling, or tree-build step terminated in an unusable state."""


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _derive_base(chat_url: str) -> str:
    """``http://host:port/api/chat`` → ``http://host:port/api``.

    If the caller configured a non-standard path (no ``/chat`` suffix) we
    return the URL unchanged, sans trailing slash.
    """
    url = chat_url.rstrip("/")
    if url.endswith("/chat"):
        return url[: -len("/chat")]
    return url


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

async def _upload(pdf_path: str, base_url: str) -> str:
    """POST ``pdf_path`` to ``{base_url}/upload``; return MoDora's filename.

    MoDora's upload handler stores the file under ``paths.docs_dir`` using the
    uploaded basename, then schedules ``process_document_task`` in the
    background. We trust MoDora's echoed ``filename`` field and fall back to
    the local basename if absent.
    """
    src = Path(pdf_path)
    if not src.exists():
        raise MoDoraClientError(f"no such file: {pdf_path}")

    upload_url = f"{base_url}/upload"
    # trust_env=False: MoDora is always on localhost; the Windows system-proxy
    # config (e.g. Clash on 127.0.0.1:7889) would otherwise swallow the
    # request and return an opaque 502 before it ever reached MoDora.
    async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT, trust_env=False) as client:
        with src.open("rb") as fh:
            files = {"file": (src.name, fh, "application/pdf")}
            try:
                resp = await client.post(upload_url, files=files)
            except httpx.HTTPError as e:
                raise MoDoraClientError(f"upload {src.name} failed: {e}") from e
    if resp.status_code != 200:
        raise MoDoraClientError(
            f"upload {src.name} http {resp.status_code}: {resp.text[:200]}"
        )
    try:
        data = resp.json()
    except ValueError:
        raise MoDoraClientError(
            f"upload {src.name} returned non-JSON: {resp.text[:200]}"
        )
    fn = str(data.get("filename") or src.name)
    logger.info(
        "modora upload base=%s filename=%s status=%s",
        base_url, fn, data.get("status"),
    )
    return fn


# ---------------------------------------------------------------------------
# Status polling
# ---------------------------------------------------------------------------

async def _wait_ready(filename: str, base_url: str, timeout: float) -> str:
    """Block until MoDora reports a terminal status for ``filename``.

    Returns the status string (``completed`` on success). Raises
    :class:`MoDoraClientError` on timeout; caller decides whether to retry.
    """
    status_url = f"{base_url}/task/status/{filename}"
    deadline = time.monotonic() + timeout
    last_status = ""
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                resp = await client.get(status_url)
            except httpx.HTTPError as e:
                logger.warning("modora status %s transient error: %s", filename, e)
                await asyncio.sleep(_POLL_INTERVAL)
                continue
            if resp.status_code != 200:
                await asyncio.sleep(_POLL_INTERVAL)
                continue
            try:
                data = resp.json()
            except ValueError:
                await asyncio.sleep(_POLL_INTERVAL)
                continue
            status = str(data.get("status", "")).lower()
            if status != last_status:
                logger.info("modora %s status: %s", filename, status)
                last_status = status
            if status in _TERMINAL_STATUSES:
                return status
            await asyncio.sleep(_POLL_INTERVAL)
    raise MoDoraClientError(
        f"status poll timeout after {timeout:.0f}s for {filename}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def ingest(
    pdf_path: str,
    chat_url: str,
    ready_timeout: Optional[float] = None,
) -> str:
    """Upload a PDF to the MoDora instance behind ``chat_url`` and block
    until its CCTree is ready.

    Returns the filename as MoDora knows it (used later as ``file_names`` in
    :func:`backend_client._build_payload`).

    Raises :class:`MoDoraClientError` when upload fails, polling times out,
    or the build ends with a non-completed status.
    """
    base = _derive_base(chat_url)
    fn = await _upload(pdf_path, base)
    status = await _wait_ready(fn, base, ready_timeout or _READY_TIMEOUT)
    if status != "completed":
        raise MoDoraClientError(
            f"tree build for {fn} ended with status={status}"
        )
    return fn
