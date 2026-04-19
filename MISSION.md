# MoDora — Mission & Constraints / 总目标与约束

> This file is the **source of truth** for *what we are building and why*.
> Read it first after any long break, before touching code, before
> accepting a new contributor, and before calling any change "done".
>
> 本文件是"我们在做什么、为什么这么做"的**唯一权威**。任何长时间中断
> 之后、动代码之前、接手新同事时、宣布任何改动"完成"之前,都先读这里。

---

## 1. The contest / 比赛任务

**EN**
Given up to **16 reference files** (mix of `.xlsx`, `.md`, `.txt`, `.docx`)
and up to **5 blank templates** (`.docx` with tables, or `.xlsx`), fill each
template's empty cells using facts grounded **only** in the references,
then return the filled document in its original format.

**中**
输入:最多 **16 份参考素材**(`.xlsx` / `.md` / `.txt` / `.docx` 混合)
加最多 **5 份空白模板**(带表格的 `.docx` 或 `.xlsx`)。输出:每份模板的
空格被填上答案,答案必须**只**来自参考素材,且输出文件保持原格式。

---

## 2. Hard targets / 硬指标

| metric / 指标           | target / 目标                                                                |
| ---------------------- | ---------------------------------------------------------------------------- |
| latency / 单模板耗时     | ≤ **90 s** end-to-end (`/process` only; `/ingest` is amortised across runs) |
| accuracy / 准确率        | ≥ **80 %** of cells correct against the contest rubric                      |
| format fidelity / 格式保真 | byte-identical template layout — fonts, merges, column widths, styles      |
| portability / 可迁移性    | `copy .env.example .env` + `pip install -r requirements.txt` → boots on any fresh Windows/Linux box |

**中**
- **单模板耗时 ≤ 90 秒**(仅计 `/process`;`/ingest` 的 OCR + 建树耗时被 5 次模板共用分摊)。
- **准确率 ≥ 80%**(按比赛评分口径)。
- **格式保真**:字体、合并单元格、列宽、样式必须与输入模板逐字节一致。
- **可迁移性**:换一台干净的 Windows/Linux 机器,只靠 `.env.example` + `requirements.txt` 就能启动,不靠本机残留配置。

---

## 3. Invariants we do not break / 不可动摇的设计不变性

**EN**

1. **MoDora stays a black box.** We only call `/api/upload`, `/api/task/status/...`,
   and `/api/chat`. We never fork or patch MoDora itself.
2. **Excel bypasses the LLM** whenever possible. Structured sheets are
   resolved deterministically in `excel_matcher.py`; the LLM is strictly
   a fallback for cells that header-to-header matching can't answer.
3. **Failures degrade, they don't cascade.** A dead channel, a 429 storm,
   a malformed LLM reply, or a missing file must never tank the whole
   batch. We retry inside `llm.chat`, fall back to safer defaults (e.g.
   routing keeps all files on failure), or surface `""` for the single
   affected cell and keep going.
4. **Two-phase pipeline.** `/ingest` owns the slow work (OCR + CCTree
   build). `/process` is cheap (LLM + `/chat` only). The contest reuses
   the same 16 references across 5 templates — re-ingesting per template
   would blow the 90 s SLA.

**中**

1. **MoDora 保持黑盒**。只调用它的 `/api/upload`、`/api/task/status/...`、
   `/api/chat` 三个接口;**绝不**修改或 fork MoDora 本体。
2. **Excel 绕过 LLM**。结构化表格用 `excel_matcher.py` 做确定性的表头-表头
   匹配,LLM 只在匹配失败时兜底,不作为主通道。
3. **失败只能降级,不能级联**。通道挂掉 / 429 风暴 / LLM 返回非法 JSON /
   文件缺失 —— 任何单点故障**都不能**拖垮整批填表。我们要么 `llm.chat` 内部
   重试,要么回落到更安全的默认值(比如 LLM 路由失败时保留全部候选文件),
   要么对单个出问题的格子返回 `""` 继续跑。
4. **两阶段 pipeline**。`/ingest` 做慢活(OCR + CCTree),`/process` 只做
   轻量活(LLM + `/chat`)。比赛场景里 16 份素材被 5 份模板共用,每份模板
   重新 ingest 一遍会直接超时。

---

## 4. Non-goals / 明确不做的事

**EN**

- **No multi-tenancy / auth / rate limiting / CORS.** The orchestrator
  listens on loopback for a single contest judge.
- **No alternative backends.** We target MoDora. Everything is sized to
  its OCR + CCTree latency profile and its `/chat` response shape. Do
  not generalise the backend layer.
- **No generic document understanding.** We only fill blanks whose
  semantics are already pinned down by the template headers and the
  reference corpus. No open-ended QA, no summarisation, no chit-chat.
- **No model training / fine-tuning.** We use DashScope-hosted models
  as-is.

**中**

- **不做多租户 / 鉴权 / 限流 / CORS**。本服务只在 loopback 给一个评委用。
- **不做可插拔 backend**。我们针对 MoDora 设计,代码里的超时、并发、响应
  适配都是按它的 OCR + CCTree 时延和 `/chat` 返回结构算的,不要泛化。
- **不做通用文档理解**。我们只填语义被"模板表头 + 参考素材"完全锁定的格子,
  不做开放式问答、不做摘要、不做闲聊。
- **不做模型训练 / 微调**。直接用 DashScope 托管的通义千问。

---

## 5. Architecture in one glance / 架构速览

```
     ┌──────────────────────────────────────────────┐
     │                  frontend                    │
     └────────────────────┬─────────────────────────┘
                          │  POST /ingest (once)
                          │  POST /process ×5
                          ▼
     ┌──────────────────────────────────────────────┐
     │               orchestrator/                  │
     │  service.py        — FastAPI pipeline        │
     │  ingest_registry   — sqlite-backed registry  │
     │  pdf_converter     — LibreOffice headless    │
     │  modora_client     — /upload + /status       │
     │  backend_client    — /chat dispatch          │
     │  excel_matcher     — deterministic xlsx      │
     │  llm.py            — DashScope + retries     │
     │  table_ops         — docx/xlsx write-safe    │
     └─┬─────────────────┬────────────────┬─────────┘
       │ md_txt channel  │ word channel   │ excel
       ▼                 ▼                │ (no network)
     ┌──────────────┐  ┌──────────────┐  │
     │  MoDora-A    │  │  MoDora-B    │  │
     │  port 8005   │  │  port 8006   │  │
     └──────────────┘  └──────────────┘  │
                                          ▼
                                      in-process
```

`/ingest` 把素材按扩展名分三路:Excel 留本地,md/txt/docx 经 LibreOffice
转 PDF 送入 MoDora-A/B 做 OCR+CCTree。`/process` 做五步:
① 解析表头 → ② LLM 分类父列/子列 → ③ 抽父实体 → ④ LLM 选素材(routing) →
⑤ 分通道派发 `/chat` → ⑥ 冲突时 LLM 仲裁 → ⑦ 写回模板。

---

## 6. Acceptance checklist / 验收清单

Before marking any change "done" / 任何改动宣布"完成"前,下面 **三项都必须过**:

1. **Offline smoke / 离线冒烟**
   ```powershell
   python -m orchestrator._smoke_offline
   # 期望输出: "All offline smoke tests PASSED." (约 1 秒)
   ```
   覆盖:重试逻辑、LLM 路由 fallback、按文件截断、sqlite 持久化、模块导入。

2. **End-to-end with mock / 端到端回放**
   用 `orchestrator/mock_modora.py` 两份实例跑一遍 `/ingest` → `/process`,
   产物文件非空,单模板耗时 < 90 s。

3. **Health endpoint sane / 健康检查正常**
   ```powershell
   curl http://127.0.0.1:8888/health
   # 正常应返回 {"status":"ok","registry":{"count":N,"db":"...","ingest_dir":"..."}}
   ```

如果这三项中**任何一项**没跑或没过,这次改动就**不算完成**,不要提交 PR,
不要 deploy,不要去调下一件事。

---

## 7. When in doubt / 拿不准时

**EN** — Any design decision should be traceable back to one of the four
invariants in §3. If a proposed change makes sense only by violating an
invariant, update this file (with rationale in the PR description) *before*
you write code. Invariants shift rarely and deliberately, never by accident.

**中** — 任何设计选择都应该能追回到第 3 节的四条不变性之一。如果某个
改动"只有违反不变性才说得通",先在 PR 里写清理由、改这份 `MISSION.md`,
**再**动代码。不变性只能有意识地、带理由地更新,不能被顺手改掉。

---

## 8. Collaborator onboarding (Windows) / 协作者上机清单 (Windows)

> Your teammate does `git clone` → follows these steps → ready to test.
>
> 你的队友 clone 下来后,按这个清单走,走完就能测。

### Step 1 — Clone + virtual env / 拉代码 + 虚拟环境

```powershell
git clone https://github.com/<你的用户名>/<你的仓库名>.git
cd <仓库名>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r orchestrator\requirements.txt
```

### Step 2 — Configuration / 配置

```powershell
copy .env.example .env
```

打开 `.env`,**必须改**的:

| 变量 | 填什么 |
|------|--------|
| `LLM_API_KEY` | DashScope 真实 API Key(各自用各自的,避免抢 quota） |
| `BACKEND_MD_TXT_URL` | `http://127.0.0.1:8005/api/chat`（本机 MoDora 端口） |
| `BACKEND_WORD_URL` | `http://127.0.0.1:8006/api/chat`（或同一个端口） |

**建议改**:

| 变量 | 推荐值 | 理由 |
|------|--------|------|
| `ORCH_INGEST_DIR` | `D:\modora_ingest`（任意持久路径） | 默认在 `%TEMP%`,重启可能清掉 |

其他变量保持 `.env.example` 默认值即可。

### Step 3 — LibreOffice / 安装 LibreOffice

如果还没装:去 https://www.libreoffice.org 下载安装。默认路径
`C:\Program Files\LibreOffice\program\soffice.exe` 会被自动检测到。

如果安装在非默认路径,在 `.env` 里加:
```
LIBREOFFICE_BIN=D:\你的路径\soffice.exe
```

### Step 4 — Offline smoke / 离线验证

```powershell
python -m orchestrator._smoke_offline
```

**必须看到** `All offline smoke tests PASSED.`。
如果不过,先截图告诉我,不要继续后面的步骤。

### Step 5 — Start services / 启动服务

```powershell
# 终端 1: 启动 orchestrator（带热重载,pull 后不用重启）
uvicorn orchestrator.service:app --host 127.0.0.1 --port 8888 --reload

# 终端 2: 启动 MoDora（按 MoDora 自己的启动方式）
# 如果没有真 MoDora,可以用 mock 代替:
# python -m uvicorn orchestrator.mock_modora:app --port 8005
```

验证:
```powershell
curl http://127.0.0.1:8888/health
# 应返回 {"status":"ok","registry":{"count":0,...}}
```

### Step 6 — Daily pull workflow / 每天拉代码的流程

```powershell
git pull
python -m orchestrator._smoke_offline   # 1 秒,先确认代码不坏
# uvicorn --reload 会自动检测文件变化,不需要重启
```

### Bug 反馈模板 / 报 bug 请用这个格式

```
【触发命令】: curl -X POST ... 或 前端操作描述
【输入文件】: 用的哪份模板 + 哪些参考素材
【期望结果】: xxx 格子应该填什么
【实际结果】: 填了什么 / 空了 / 报错了
【orchestrator 日志最后 50 行】: <粘贴>
```

日志里有 `route: 2/5 files kept`、`llm.chat http 429` 这些信号,
拿到日志我就能判断是路由错了还是重试爆了,不用猜。
