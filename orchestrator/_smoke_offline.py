"""Offline smoke checks for the orchestrator plumbing.

Run: ``python -m orchestrator._smoke_offline``

Does NOT hit the real LLM, the real MoDora, or the filesystem outside of
``%TEMP%``. Exits non-zero on any failure so it can be wired into CI.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _route_test_ctx():
    """Redirect registry sqlite to scratch so real /ingest state is untouched."""
    scratch = Path(tempfile.mkdtemp(prefix="orch_smoke_"))
    os.environ["ORCH_INGEST_DIR"] = str(scratch)
    os.environ["ORCH_REGISTRY_DB"] = str(scratch / "r.sqlite3")
    # Keep retries snappy so the test finishes in seconds.
    os.environ["LLM_MAX_RETRIES"] = "3"
    os.environ["LLM_BACKOFF_BASE"] = "1.05"
    os.environ["LLM_BACKOFF_CAP"] = "0.2"
    # Bypass the api-key guard; this test stubs the HTTP client entirely.
    os.environ["LLM_API_KEY"] = "test-fake-key"
    return scratch


def _reset_modules():
    for m in list(sys.modules):
        if m.startswith("orchestrator"):
            del sys.modules[m]


# ---------------------------------------------------------------------------
# G1 — llm.chat retry on 429 then success
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code, data=None, text="", headers=None):
        self.status_code = status_code
        self._data = data
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


def _test_retry_success_after_429():
    _reset_modules()
    import httpx
    from orchestrator import llm

    call_log = []

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, headers=None, json=None):
            call_log.append(len(call_log))
            if len(call_log) == 1:
                return _FakeResponse(429, text="rate limited", headers={"Retry-After": "0"})
            if len(call_log) == 2:
                return _FakeResponse(503, text="transient")
            return _FakeResponse(200, data={"choices": [{"message": {"content": "hello"}}]})

    httpx.AsyncClient = _FakeClient  # type: ignore
    result = asyncio.run(llm.chat("ping"))
    assert result == "hello", f"expected hello, got {result!r}"
    assert len(call_log) == 3, f"expected 3 attempts, got {len(call_log)}"
    print(f"[G1] retry recovered after {len(call_log)} attempts -> {result!r}  OK")


def _test_retry_gives_up_on_400():
    _reset_modules()
    import httpx
    from orchestrator import llm

    call_log = []

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, headers=None, json=None):
            call_log.append(len(call_log))
            return _FakeResponse(400, text="bad request")

    httpx.AsyncClient = _FakeClient  # type: ignore
    raised = False
    try:
        asyncio.run(llm.chat("ping"))
    except llm.LLMError as e:
        raised = True
        assert "400" in str(e), str(e)
    assert raised, "expected LLMError on 400"
    assert len(call_log) == 1, f"400 must not retry; got {len(call_log)} attempts"
    print(f"[G1] 400 surfaced immediately (no retry)  OK")


# ---------------------------------------------------------------------------
# G2 — route fallback when LLM returns garbage
# ---------------------------------------------------------------------------

def _make_fake_docs(count):
    """Create real tiny files so read_document_text doesn't log errors."""
    scratch = Path(tempfile.mkdtemp(prefix="orch_route_"))
    from orchestrator import ingest_registry
    docs = []
    for i in range(count):
        p = scratch / f"f{i}.md"
        p.write_text(f"# file {i}\ncontent for test file {i}\n", encoding="utf-8")
        docs.append(ingest_registry.IngestedDoc(
            original_name=f"f{i}.md",
            channel="md_txt",
            local_path=str(p),
            modora_filename=f"f{i}.pdf",
            status="ok",
        ))
    return scratch, docs


def _test_route_fallback():
    _reset_modules()
    from orchestrator import service

    scratch, docs = _make_fake_docs(5)

    # LLM returns prose (no JSON list) -> must fall back to all 5.
    async def _fake_chat_garbage(prompt, **kw):
        return "这是一些无关的文字，没有 JSON。"

    from orchestrator import llm as llm_mod
    orig = llm_mod.chat
    llm_mod.chat = _fake_chat_garbage  # type: ignore
    try:
        selected = asyncio.run(service._route_channel_files(
            docs,
            parent_headers=["城市"],
            child_headers=["GDP"],
            parent_rows=[["德州市"]],
            requirement="",
            top_k=3,
        ))
    finally:
        llm_mod.chat = orig
        shutil.rmtree(scratch, ignore_errors=True)

    assert len(selected) == 5, f"fallback must keep all docs, got {len(selected)}"
    print(f"[G2] garbage LLM response -> fell back to all {len(selected)} docs  OK")


def _test_route_success():
    _reset_modules()
    from orchestrator import service

    scratch, docs = _make_fake_docs(5)

    async def _fake_chat_good(prompt, **kw):
        return "[0, 2]"

    from orchestrator import llm as llm_mod
    orig = llm_mod.chat
    llm_mod.chat = _fake_chat_good  # type: ignore
    try:
        selected = asyncio.run(service._route_channel_files(
            docs,
            parent_headers=["城市"],
            child_headers=["GDP"],
            parent_rows=[["德州市"]],
            requirement="",
            top_k=3,
        ))
    finally:
        llm_mod.chat = orig
        shutil.rmtree(scratch, ignore_errors=True)

    assert [d.original_name for d in selected] == ["f0.md", "f2.md"], selected
    print(f"[G2] valid [0,2] -> kept {[d.original_name for d in selected]}  OK")


def _test_route_noop_when_small():
    _reset_modules()
    from orchestrator import ingest_registry, service

    docs = [
        ingest_registry.IngestedDoc(
            original_name="only.md",
            channel="md_txt",
            local_path="/tmp/only.md",
            modora_filename="only.pdf",
            status="ok",
        )
    ]

    chat_called = [0]

    async def _fake_chat(prompt, **kw):
        chat_called[0] += 1
        return "[]"

    from orchestrator import llm as llm_mod
    orig = llm_mod.chat
    llm_mod.chat = _fake_chat  # type: ignore
    try:
        selected = asyncio.run(service._route_channel_files(
            docs,
            parent_headers=["x"],
            child_headers=["y"],
            parent_rows=[["v"]],
            requirement="",
            top_k=3,
        ))
    finally:
        llm_mod.chat = orig

    assert len(selected) == 1, selected
    assert chat_called[0] == 0, f"LLM should not be called when files <= top_k; got {chat_called[0]}"
    print(f"[G2] len(docs)=1 <= top_k=3 -> skipped LLM round-trip  OK")


# ---------------------------------------------------------------------------
# G4 — per-file text truncation
# ---------------------------------------------------------------------------

def _test_per_file_truncation():
    _reset_modules()
    from orchestrator import service

    # three files: short, medium, huge. Budget is small so truncation triggers.
    scratch = Path(tempfile.mkdtemp(prefix="orch_texts_"))
    try:
        small = scratch / "small.txt"
        medium = scratch / "medium.txt"
        huge = scratch / "huge.txt"
        small.write_text("小内容", encoding="utf-8")
        medium.write_text("中" * 3_000, encoding="utf-8")
        huge.write_text("大" * 100_000, encoding="utf-8")

        out = service._concat_channel_texts(
            [str(small), str(medium), str(huge)], limit=10_000
        )
        # Every file must be represented by its header marker.
        assert "=== 文件: small.txt ===" in out
        assert "=== 文件: medium.txt ===" in out
        assert "=== 文件: huge.txt ===" in out
        # The total must stay within sanity bounds of the limit.
        assert len(out) <= 15_000, f"truncation failed; len={len(out)}"
        # Huge file should be truncated but still partially present.
        assert "大" * 1_000 in out, "huge file lost most of its content"
        print(f"[G4] per-file truncation kept all 3 files, total={len(out)} chars  OK")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# G5 — registry persistence (already tested inline earlier, repeat for CI)
# ---------------------------------------------------------------------------

def _test_registry_roundtrip():
    _reset_modules()
    from orchestrator import ingest_registry as r

    r.clear()
    r.put(r.IngestedDoc("a.xlsx", "excel", "/tmp/a.xlsx", None, "ok"))
    r.put(r.IngestedDoc("b.md", "md_txt", "/tmp/b.md", "b.pdf", "ok"))
    assert r.count() == 2

    _reset_modules()
    from orchestrator import ingest_registry as r2
    assert r2.count() == 2, f"restart lost records; got {r2.count()}"
    names = sorted(d.original_name for d in r2.all_docs())
    assert names == ["a.xlsx", "b.md"], names
    r2.clear()
    print(f"[G5] registry restarted with {len(names)} docs restored  OK")


# ---------------------------------------------------------------------------
# Whole-service import smoke
# ---------------------------------------------------------------------------

def _test_service_imports():
    _reset_modules()
    from orchestrator import service  # noqa: F401
    assert hasattr(service, "app")
    assert hasattr(service, "_route_channel_files")
    assert hasattr(service, "_concat_channel_texts")
    print("[IMPORT] orchestrator.service + all helpers importable  OK")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    scratch = _route_test_ctx()
    try:
        _test_service_imports()
        _test_retry_success_after_429()
        _test_retry_gives_up_on_400()
        _test_route_noop_when_small()
        _test_route_success()
        _test_route_fallback()
        _test_per_file_truncation()
        _test_registry_roundtrip()
        print("\nAll offline smoke tests PASSED.")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
