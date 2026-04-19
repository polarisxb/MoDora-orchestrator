# MoDora Orchestrator

Control-plane service sitting between the user-facing frontend and MoDora's
QA backend. It owns the entire template-filling workflow:

1. Ingest the reference materials **once** (Excel files kept local, md /
   txt / docx converted to PDF and registered with MoDora for OCR + CCTree).
2. For each blank template, parse headers, classify parent / child columns,
   extract parent entities, dispatch child questions across channels, merge
   the best answer per cell, and return the filled document.

> **Project mission & hard constraints**: see `../MISSION.md` (bilingual).
> Read that first after any long break before touching code here.

## Prerequisites

- Python ≥ 3.10
- **LibreOffice** (for md / txt / docx → PDF). `soffice` on `PATH` or set
  `LIBREOFFICE_BIN`. Windows default install path is auto-detected.
- One or two **MoDora** instances running on their own ports. By default the
  orchestrator expects `http://127.0.0.1:8005/api/chat` (md/txt channel) and
  `http://127.0.0.1:8006/api/chat` (word channel). Point them at the same
  URL if you only run one MoDora.

## Quick start

```powershell
# from repository root
copy .env.example .env                # fill LLM_API_KEY and backend URLs
pip install -r orchestrator\requirements.txt

uvicorn orchestrator.service:app --host 127.0.0.1 --port 8888
# or
python -m orchestrator.service
```

Health check: `GET http://127.0.0.1:8888/health`.

## Two-phase workflow

### 1) `POST /ingest` — upload the 16 reference files once

`multipart/form-data`

| field        | type                     | required | meaning                                  |
| ------------ | ------------------------ | -------- | ---------------------------------------- |
| `ref_excel`  | `List[UploadFile]` (≤6)  | no       | Excel reference materials                |
| `ref_md_txt` | `List[UploadFile]` (≤6)  | no       | md / txt reference materials             |
| `ref_word`   | `List[UploadFile]` (≤6)  | no       | docx reference materials                 |

Behaviour:
- Excel files are stored locally for deterministic header-to-header matching.
- md / txt / docx files are converted to PDF via LibreOffice, uploaded to
  the corresponding MoDora instance, and the endpoint blocks until MoDora
  reports the CCTree is `completed`.
- Each /ingest **replaces** the previous cohort (disk + registry).
- Returns per-file status; one failed file does not block the others.

Example:
```powershell
curl -X POST http://127.0.0.1:8888/ingest `
  -F "ref_excel=@sales.xlsx" `
  -F "ref_md_txt=@notes.md" `
  -F "ref_word=@report.docx"
```

`GET /ingest` returns the current cohort summary (for UIs / debugging).

### 2) `POST /process` — fill one template

`multipart/form-data`

| field        | type          | required | meaning                                       |
| ------------ | ------------- | -------- | --------------------------------------------- |
| `design_file`| `UploadFile`  | yes      | blank template (`.docx` or `.xlsx`)           |
| `requirement`| `str`         | no       | natural-language constraint (date/region/...) |

Returns the filled template as a binary download (same kind as input).
References are resolved from the registry populated by the most recent
/ingest; calling /process without a prior /ingest returns HTTP 400.

## Module map

| module               | responsibility |
| -------------------- | -------------- |
| `service.py`         | FastAPI app, `/ingest` + `/process` pipelines, cross-channel arbitration, LLM-based file routing |
| `ingest_registry.py` | Persistent (in-memory + sqlite) map of ingested docs (original name ↔ local path ↔ MoDora filename) |
| `pdf_converter.py`   | LibreOffice headless wrapper (md/txt/docx → pdf), serialised via lock |
| `modora_client.py`   | MoDora `/upload` + `/task/status` polling client |
| `backend_client.py`  | MoDora `/chat` dispatch, MoDora-response adapter, invalid-value filtering |
| `excel_matcher.py`   | Deterministic header-to-header match for Excel references (no LLM) |
| `readers.py`         | md / txt / docx / xlsx / pdf plain-text readers for LLM parent extraction |
| `table_ops.py`       | Merge-cell-safe read/write for Word and Excel tables |
| `llm.py`             | DashScope/OpenAI-compatible chat (with retries) + JSON extraction + prompt builders |
| `mock_modora.py`     | Standalone FastAPI app emulating MoDora's `/upload` + `/chat` for offline tests |
| `_smoke_offline.py`  | Runs the offline regression suite (retries, routing, truncation, registry) |

## Configuration (.env)

All keys live in `.env.example` at the repo root. The service refuses to
start if `LLM_API_KEY` is missing.

- **LLM**
  - `LLM_API_URL`, `LLM_API_KEY`, `LLM_MODEL_FAST`, `LLM_MODEL_LONG`
  - `LLM_MAX_RETRIES` / `LLM_BACKOFF_BASE` / `LLM_BACKOFF_CAP` — retry policy
    for 429 / 5xx / network errors inside `llm.chat`.
- **LibreOffice**
  - `LIBREOFFICE_BIN` — explicit path to `soffice` / `soffice.exe`.
  - `LIBREOFFICE_TIMEOUT` — seconds per conversion (default 60).
- **MoDora ingest**
  - `MODORA_UPLOAD_TIMEOUT` / `MODORA_READY_TIMEOUT` / `MODORA_POLL_INTERVAL`
    — upload + tree-build polling budget.
- **File routing**
  - `ORCH_ROUTE_TOP_K` — how many files the LLM may pick per channel per
    /process (default 3). Fallback to all files on failure.
  - `ORCH_ROUTE_BRIEF_CHARS` — head-of-file excerpt length fed to the
    routing prompt for disambiguation.
- **Persistence**
  - `ORCH_INGEST_DIR` — root of the persistent ingest directory.
  - `ORCH_REGISTRY_DB` — override the sqlite registry file path.

## Design notes

1. **Two-phase pipeline.** /ingest is the slow path (OCR + CCTree building);
   /process is cheap (LLM + /chat only). Contest scoring runs 5 templates
   over the same 16 references, so we amortise the expensive work.
2. **Excel is structural, not LLM.** Excel references never touch the LLM
   question pipeline; we match headers directly and read cells. This is
   both faster and avoids LLM row-recall errors on long sheets.
3. **MoDora stays black-box.** We adapt to its existing `/chat` contract
   (`{file_names, query, settings}`) inside `backend_client._build_payload`
   instead of forking MoDora. The invalid-value filter already covers
   MoDora's `"None"` / `"No answer"` literals via case-folded comparison.
4. **Per-file timeout isolation.** A slow MoDora response cannot block the
   rest of the batch; the orchestrator caps each /chat call at
   `BACKEND_TIMEOUT` seconds.
5. **Conflicting answers → LLM arbitration.** When md_txt and word channels
   disagree on the same cell, a lightweight LLM call picks the winner;
   otherwise the channel priority (md_txt = word > excel) tie-breaks.
6. **Filename sanitisation is end-to-end**, not computed-and-ignored.
7. **Word cell writes preserve paragraph/run formatting** by editing runs
   in place rather than `cell.text = ...`.
8. **Merged cells handled on both read and write** (anchor-only writes;
   slave cells are skipped).
9. **LLM file routing before dispatch.** For each channel we ask the LLM to
   pick the `ORCH_ROUTE_TOP_K` most likely-to-answer files *once per
   /process*, then only those files are sent to MoDora's /chat. Falls back
   to the full list on any failure, so routing is strictly a reducer.
10. **DashScope resiliency baked into `llm.chat`.** 429 / 5xx / 408 / 425
    and network errors retry with exponential backoff (honours
    `Retry-After`). Tunable via `LLM_MAX_RETRIES` / `LLM_BACKOFF_*`.
11. **Registry persistence.** `ingest_registry` mirrors to an sqlite file
    under `ORCH_INGEST_DIR`. An orchestrator restart reloads the registry
    in-memory, so you do **not** re-upload the 16 references after a crash
    or redeploy — as long as the ingest dir (and the PDFs inside it) are
    still there.

## Deployment runbook (new machine)

A fresh clone on a different host needs the following. Steps that end with
`// verify` should produce the exact output shown; if they don't, skip to
the **Troubleshooting** section.

### 1. System prerequisites

- Python 3.10+ (`python --version` // verify: reports 3.10.x or later)
- LibreOffice (`soffice --version` or `"C:\Program Files\LibreOffice\program\soffice.exe" --version` on Windows). If the binary is not on `PATH`, set `LIBREOFFICE_BIN` in `.env`.
- A running MoDora instance (or two — one per channel). Default ports 8005 / 8006.

### 2. Python env

```powershell
# From the repo root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r orchestrator\requirements.txt
```

### 3. Configuration

```powershell
copy .env.example .env
# Then edit .env:
#   LLM_API_KEY=<your DashScope key>                   # required
#   BACKEND_MD_TXT_URL=http://<modora-host>:8005/api/chat
#   BACKEND_WORD_URL=http://<modora-host>:8006/api/chat
#   ORCH_INGEST_DIR=C:\ProgramData\modora_orch_ingest  # optional but recommended
```

### 4. Start

```powershell
uvicorn orchestrator.service:app --host 127.0.0.1 --port 8888
# or
python -m orchestrator.service
```

Sanity check:

```powershell
curl http://127.0.0.1:8888/health
# {"status":"ok","registry":{"count":0,"db":"...","ingest_dir":"..."}}
```

### 5. Offline smoke test (no network, ~1 s)

After installing dependencies you can verify the core plumbing without
touching a real LLM or MoDora:

```powershell
python -m orchestrator._smoke_offline
# Should end with: "All offline smoke tests PASSED."
```

This exercises the retry loop, the LLM routing fallback, the per-file text
truncation, and the sqlite registry round-trip. If any of these fail on a
fresh clone, stop and investigate before running a real /ingest.

### 6. Smoke test without real MoDora (optional)

Two mock MoDora instances work as a drop-in for /chat during local testing:

```powershell
# Terminal A
python -m uvicorn orchestrator.mock_modora:app --port 8005
# Terminal B
$env:MOCK_DOCS_DIR = 'C:\tmp\mock_modora_word'
python -m uvicorn orchestrator.mock_modora:app --port 8006
```

Point `BACKEND_MD_TXT_URL` / `BACKEND_WORD_URL` at these two ports in
`.env` and run the normal `/ingest` → `/process` flow.

## Troubleshooting

- **`LLM_API_KEY is empty or still the placeholder`** → edit `.env` and set the real key; the server refuses to start without it.
- **`502 Bad Gateway` on localhost backend calls** → a Windows system proxy (Clash et al.) is hijacking loopback. `backend_client` and `modora_client` already disable env proxies via `trust_env=False`; if you see 502 despite this, audit any HTTP-aware middleware (VPN, corporate proxy).
- **`LibreOffice not found`** during /ingest → install LibreOffice or set `LIBREOFFICE_BIN` to the absolute path of `soffice.exe`.
- **/ingest hangs forever** → most often MoDora's tree build is stuck. Tail the MoDora logs; bump `MODORA_READY_TIMEOUT` for very large docs.
- **Random cells come out blank in Word output** → fixed in `table_ops.py` by holding `_tc` proxies in the dedup set. If you hit this again, add `ORCH_LOG_LEVEL=DEBUG` and look for `skip merged-slave cell` lines.
- **Many `No answer` cells** → check `ORCH_ROUTE_TOP_K`. Routing may be pruning too aggressively. Bump to 6 (= no pruning) to validate and tune back down.
- **Frequent DashScope 429s in the log** → fine if each call still returns via the retry loop. If they add 30+s to `/process`, drop `ORCH_QUESTION_CONCURRENCY` from 8 toward 3.
