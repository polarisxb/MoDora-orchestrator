"""Persistent registry of ingested reference documents.

Contest workflow this supports
------------------------------
1. Client calls ``POST /ingest`` **once** with up to 16 reference files.
2. Client calls ``POST /process`` **up to 5 times**, each with a different
   blank template but no references — the orchestrator looks them up here.

Each record holds both:
- ``local_path`` — where the orchestrator persisted the original for its
  own reading (e.g. LLM parent-entity extraction loves the raw docx/md
  layout, PDFs suffer from OCR artefacts).
- ``modora_filename`` — the filename MoDora serves under ``docs_dir`` after
  /upload + tree build. Used verbatim in ``ChatRequest.file_names``. ``None``
  for Excel since Excel bypasses MoDora.

Storage
-------
In-memory dict as the authoritative copy, **mirrored to a sqlite file** so
that orchestrator restarts (or a fresh clone of the repo on another
machine) can resume from the last successful /ingest without re-uploading
the 16 references.

Why not sqlite-only? Because the hot path (``by_channel`` / ``count`` called
several times per /process) wants O(1) dict lookups rather than a SELECT
round-trip, and the mutation rate is tiny (one /ingest per contest run).
sqlite is strictly the durability layer.

sqlite location
  Default: ``<ORCH_INGEST_DIR or %TEMP%/modora_orch_ingest>/registry.sqlite3``
  Override: ``ORCH_REGISTRY_DB`` (absolute path).

Concurrency
-----------
The orchestrator runs as a single-process uvicorn; dict operations on CPython
are atomic under the GIL and all mutators happen from the FastAPI event
loop. sqlite writes are guarded by a ``threading.Lock`` so a background task
that calls ``put()`` from a worker thread still serialises cleanly.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class IngestedDoc:
    original_name: str              # user-uploaded basename, e.g. "财报.docx"
    channel: str                    # "excel" | "md_txt" | "word"
    local_path: str                 # path on our disk for LLM-side reading
    modora_filename: Optional[str]  # filename registered with MoDora; None for excel
    status: str                     # "ok" | "failed:<reason>"


# ---------------------------------------------------------------------------
# In-memory cache (hot path)
# ---------------------------------------------------------------------------

_DOCS: Dict[str, IngestedDoc] = {}
_DB_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# sqlite durability layer
# ---------------------------------------------------------------------------

def _default_db_path() -> Path:
    root = os.environ.get("ORCH_INGEST_DIR") or (
        Path(tempfile.gettempdir()) / "modora_orch_ingest"
    )
    return Path(root) / "registry.sqlite3"


_DB_PATH = Path(os.environ.get("ORCH_REGISTRY_DB") or _default_db_path())


def _connect() -> sqlite3.Connection:
    """Open a short-lived connection; WAL is enabled to tolerate read while
    the FastAPI loop writes from another context.
    """
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), isolation_level=None, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS docs (
            original_name   TEXT PRIMARY KEY,
            channel         TEXT NOT NULL,
            local_path      TEXT NOT NULL,
            modora_filename TEXT,
            status          TEXT NOT NULL
        )
        """
    )
    return conn


def _load_from_disk() -> None:
    """Populate the in-memory dict from sqlite on module import.

    Missing DB / schema file is fine (fresh install). Corrupt rows are
    dropped with a warning so one bad record can't wedge startup.
    """
    try:
        with _DB_LOCK, _connect() as conn:
            cur = conn.execute(
                "SELECT original_name, channel, local_path, modora_filename, status FROM docs"
            )
            loaded = 0
            for name, channel, local_path, mf, status in cur.fetchall():
                try:
                    _DOCS[name] = IngestedDoc(
                        original_name=name,
                        channel=channel,
                        local_path=local_path,
                        modora_filename=mf,
                        status=status,
                    )
                    loaded += 1
                except Exception:
                    logger.warning("skipping corrupt registry row %r", name, exc_info=True)
            if loaded:
                logger.info("ingest_registry: restored %d docs from %s", loaded, _DB_PATH)
    except sqlite3.DatabaseError:
        logger.exception("ingest_registry: sqlite open failed; starting empty (db=%s)", _DB_PATH)


_load_from_disk()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clear() -> None:
    """Drop every record, in-memory and on-disk. Called at start of /ingest."""
    with _DB_LOCK:
        _DOCS.clear()
        try:
            with _connect() as conn:
                conn.execute("DELETE FROM docs")
        except sqlite3.DatabaseError:
            logger.exception("ingest_registry: failed to clear sqlite (db=%s)", _DB_PATH)


def put(doc: IngestedDoc) -> None:
    """Upsert by ``original_name``, persisting to sqlite synchronously.

    The in-memory dict is updated first so readers on the event loop see the
    new state immediately even if the sqlite write lags.
    """
    with _DB_LOCK:
        _DOCS[doc.original_name] = doc
        try:
            with _connect() as conn:
                conn.execute(
                    """
                    INSERT INTO docs (original_name, channel, local_path, modora_filename, status)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(original_name) DO UPDATE SET
                        channel          = excluded.channel,
                        local_path       = excluded.local_path,
                        modora_filename  = excluded.modora_filename,
                        status           = excluded.status
                    """,
                    (doc.original_name, doc.channel, doc.local_path,
                     doc.modora_filename, doc.status),
                )
        except sqlite3.DatabaseError:
            logger.exception(
                "ingest_registry: failed to persist %s (db=%s)",
                doc.original_name, _DB_PATH,
            )


def get(original_name: str) -> Optional[IngestedDoc]:
    return _DOCS.get(original_name)


def all_docs() -> List[IngestedDoc]:
    return list(_DOCS.values())


def by_channel(channel: str, successful_only: bool = True) -> List[IngestedDoc]:
    """Filter by channel; by default only returns fully-ingested docs."""
    return [
        d for d in _DOCS.values()
        if d.channel == channel and (not successful_only or d.status == "ok")
    ]


def as_summary() -> List[dict]:
    """JSON-serialisable form suitable for /ingest response bodies and UIs."""
    return [asdict(d) for d in _DOCS.values()]


def count() -> int:
    return len(_DOCS)


def db_path() -> str:
    """Exposed for diagnostics / health endpoints."""
    return str(_DB_PATH)
