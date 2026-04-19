"""Convert md / txt / docx sources to PDF via LibreOffice headless.

Why LibreOffice
---------------
MoDora's ingest pipeline (OCR → CCTree) accepts only PDF. We chose
LibreOffice because a single binary handles every non-Excel textual format
we care about (``.md``, ``.txt``, ``.docx``, ``.doc``, ``.odt``, ``.rtf``),
runs headless on Windows / Linux / macOS, and produces layout that MoDora's
OCR pass copes with comfortably. ``docx2pdf`` is Windows+Word only;
``weasyprint`` has CJK font landmines; ``pandoc`` requires a separate
pdflatex / xelatex install. LibreOffice is the single-dependency choice.

Requirements
------------
- LibreOffice installed on the host, and ``soffice`` (or ``soffice.exe``)
  either on ``PATH`` or pointed to by the ``LIBREOFFICE_BIN`` env var.
- Disk space for the output directory caller provides.

Concurrency
-----------
LibreOffice shares a single user profile by default; invoking multiple
converters in parallel triggers profile-lock errors. We serialise
conversions through a module-level ``asyncio.Lock``. At 1-5 s per file and
≤ 16 files per ingest that is comfortably within the 90 s contest budget.

Public surface
--------------
- :func:`available` — fast probe for startup diagnostics.
- :func:`convert_to_pdf` — async; raises :class:`PDFConversionError` on
  failure so callers see something louder than a silent skip.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CONVERT_TIMEOUT_DEFAULT = float(os.environ.get("LIBREOFFICE_TIMEOUT", "60"))

# Extensions this module knows how to convert. PDFs pass through unchanged
# so callers can treat every input uniformly.
_SUPPORTED_INPUT_EXT = {".md", ".txt", ".docx", ".doc", ".odt", ".rtf", ".pdf"}

# Serialise LibreOffice invocations per-process. See module docstring.
_CONVERSION_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class PDFConversionError(Exception):
    """Raised when we cannot produce a usable PDF from the given source."""


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------

def _find_soffice() -> Optional[str]:
    """Resolve the LibreOffice binary path.

    Priority: ``LIBREOFFICE_BIN`` env var > ``PATH`` lookup > common Windows
    install location (``C:\\Program Files\\LibreOffice\\program\\soffice.exe``).
    Returns ``None`` when nothing is found.
    """
    override = os.environ.get("LIBREOFFICE_BIN")
    if override:
        p = Path(override)
        if p.exists():
            return str(p)
        logger.warning(
            "LIBREOFFICE_BIN=%r points to a non-existent path; falling back to PATH lookup",
            override,
        )

    for name in ("soffice", "soffice.exe"):
        found = shutil.which(name)
        if found:
            return found

    win_default = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
    if win_default.exists():
        return str(win_default)
    return None


def available() -> bool:
    """True iff a LibreOffice binary can be located right now."""
    return _find_soffice() is not None


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

async def convert_to_pdf(
    src_path: str,
    out_dir: str,
    timeout: Optional[float] = None,
) -> str:
    """Convert ``src_path`` to a PDF placed in ``out_dir``; return its path.

    PDF inputs are **copied** (not converted) into ``out_dir`` so callers do
    not have to branch on input type. For every other supported extension we
    call LibreOffice headless.

    Raises
    ------
    PDFConversionError
        Any terminal failure — missing binary, unsupported extension,
        LibreOffice timeout, non-zero exit code, or missing output file.
    """
    src = Path(src_path)
    if not src.exists():
        raise PDFConversionError(f"source does not exist: {src_path}")

    ext = src.suffix.lower()
    if ext not in _SUPPORTED_INPUT_EXT:
        raise PDFConversionError(f"unsupported input extension: {ext}")

    out_dir_p = Path(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)

    # Pass-through for PDFs so downstream callers see a uniform interface.
    if ext == ".pdf":
        dst = out_dir_p / src.name
        try:
            if dst.resolve() != src.resolve():
                shutil.copy2(src, dst)
        except FileNotFoundError:
            # resolve() on a not-yet-existent dst path; copy anyway.
            shutil.copy2(src, dst)
        return str(dst)

    soffice = _find_soffice()
    if not soffice:
        raise PDFConversionError(
            "LibreOffice not found. Install it and/or set LIBREOFFICE_BIN "
            "(Windows default: C:\\Program Files\\LibreOffice\\program\\soffice.exe)."
        )

    expected_out = out_dir_p / (src.stem + ".pdf")
    effective_timeout = timeout if timeout is not None else _CONVERT_TIMEOUT_DEFAULT

    async with _CONVERSION_LOCK:
        cmd = [
            soffice,
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(out_dir_p),
            str(src),
        ]
        logger.info("pdf_converter: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
                # Let the process cleanup before we surface the error.
                with contextlib.suppress(Exception):
                    await proc.wait()
            raise PDFConversionError(
                f"LibreOffice timed out after {effective_timeout:.0f}s on {src}"
            )

    if proc.returncode != 0:
        raise PDFConversionError(
            f"LibreOffice exited {proc.returncode}: "
            f"stdout={stdout[:500]!r} stderr={stderr[:500]!r}"
        )
    if not expected_out.exists():
        raise PDFConversionError(
            f"LibreOffice reported success but {expected_out} is missing"
        )
    logger.info("pdf_converter: %s -> %s", src.name, expected_out.name)
    return str(expected_out)
