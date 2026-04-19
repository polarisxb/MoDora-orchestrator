# 队友本地环境搭建 & 日常协作指南

> **适用系统**：Windows 10 / 11
> **仓库地址**：https://github.com/polarisxb/MoDora-orchestrator.git
> **预计耗时**：首次搭建 ~20 分钟（主要等 pip 下载 + LibreOffice 安装）

---

## 〇、你需要先装好的东西（前置条件）

| 软件 | 版本要求 | 下载地址 | 备注 |
|------|---------|---------|------|
| **Git** | ≥ 2.40 | https://git-scm.com/download/win | 安装时全选默认即可 |
| **Python** | **3.10 – 3.12**（推荐 3.11） | https://www.python.org/downloads/ | ⚠️ 安装时**必须勾选** "Add Python to PATH" |
| **LibreOffice** | ≥ 7.6 | https://www.libreoffice.org/download/ | 用于 docx/txt/md → PDF 转换 |

### 怎么验证装好了

打开 **PowerShell**（Win+R → 输入 `powershell` → 回车），依次输入：

```powershell
git --version          # 应显示 git version 2.xx.x
python --version       # 应显示 Python 3.10.x / 3.11.x / 3.12.x
```

如果 `python` 没反应但 `python3` 可以，后续所有命令把 `python` 换成 `python3`。

**LibreOffice** 只要装了就行，不需要打开它。默认装在：
```
C:\Program Files\LibreOffice\program\soffice.exe
```
代码会自动找到这个路径。如果你装在了别的地方（比如 D 盘），后面配置 `.env` 时需要额外填一行。

---

## 一、拉代码

```powershell
cd D:\                          # 换成你想放项目的盘/目录
git clone https://github.com/polarisxb/MoDora-orchestrator.git
cd MoDora-orchestrator
```

> 💡 **不要**把项目放在带中文或空格的路径下（如 `C:\Users\张三\桌面\`），
> 否则 LibreOffice 转 PDF 可能会报错。推荐放 `D:\` 或 `C:\projects\`。

---

## 二、创建虚拟环境 + 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

如果报 **"无法加载……因为在此系统上禁止运行脚本"** 错误：
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# 输入 Y 确认，然后重新运行：
.\.venv\Scripts\Activate.ps1
```

看到命令行前面出现 `(.venv)` 就说明激活成功了。然后安装依赖：

```powershell
pip install -r orchestrator\requirements.txt
```

### 常见问题

| 现象 | 原因 | 解法 |
|------|------|------|
| `pip install` 很慢 / 超时 | 默认源在国外 | 加镜像：`pip install -r orchestrator\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| `pymupdf` 安装失败 | 需要 C++ 编译环境 | 先运行 `pip install pymupdf==1.24.0`，还不行就装 [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)，勾选 "C++ 桌面开发" |
| `python-docx` 安装报错 | pip 版本太旧 | 先 `pip install --upgrade pip`，再重新装 |

---

## 三、配置 .env 文件

```powershell
copy .env.example .env
```

用记事本或 VS Code 打开 `.env`，**必须改**下面这几行：

### 3.1 必须改的

```ini
# 把 replace-me 换成真实的 DashScope API Key
# 找我要，或者用你自己的（注意 quota 别超）
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# MoDora 后端地址。如果你本机跑了 MoDora，保持默认即可：
BACKEND_MD_TXT_URL=http://127.0.0.1:8005/api/chat
BACKEND_WORD_URL=http://127.0.0.1:8006/api/chat
```

### 3.2 强烈建议改的

```ini
# 把 ingest 目录设到固定位置（而不是默认的临时目录）
# 这样电脑重启后不用重新 ingest
ORCH_INGEST_DIR=D:\modora_ingest
```

### 3.3 LibreOffice 路径（仅当安装在非默认位置时）

如果你把 LibreOffice 装到了非默认路径，取消注释并改成你的路径：
```ini
LIBREOFFICE_BIN=D:\你的安装路径\program\soffice.exe
```

### 3.4 其他变量

**不要动**，保持 `.env.example` 里的默认值就好。

---

## 四、离线验证（重要！）

```powershell
python -m orchestrator._smoke_offline
```

**必须看到这个输出**：
```
All offline smoke tests PASSED.
```

> ⚠️ 如果没过：**截图发给我，不要跳过这步继续往下走**。
> 这个测试不需要网络、不需要 MoDora、不需要 API Key，
> 它只验证代码本身有没有问题。如果这都不过，后面一定会出更多问题。

### 常见失败原因

| 错误信息 | 解法 |
|---------|------|
| `ModuleNotFoundError: No module named 'xxx'` | `pip install -r orchestrator\requirements.txt` 没跑完整，重跑一次 |
| `ImportError: DLL load failed` | pymupdf 没装好，见上面"常见问题"表 |
| 任何 `SyntaxError` | Python 版本不对，必须 ≥ 3.10 |

---

## 五、启动服务

需要开 **两个** PowerShell 窗口（都要先激活虚拟环境）。

### 窗口 1：启动 orchestrator

```powershell
cd D:\MoDora-orchestrator      # 你的项目目录
.\.venv\Scripts\Activate.ps1
uvicorn orchestrator.service:app --host 127.0.0.1 --port 8888 --reload
```

看到类似下面的输出就说明启动成功了：
```
INFO:     Uvicorn running on http://127.0.0.1:8888 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx]
```

### 窗口 2：启动 MoDora 后端

如果你有真正的 MoDora 后端，按它的文档启动。
如果**没有**，可以用我们的 mock 代替（用于基本功能测试）：

```powershell
cd D:\MoDora-orchestrator
.\.venv\Scripts\Activate.ps1
python -m uvicorn orchestrator.mock_modora:app --host 127.0.0.1 --port 8005
```

### 验证服务正常

打开浏览器（或新开第三个 PowerShell），访问：
```powershell
curl http://127.0.0.1:8888/health
```

应该返回：
```json
{"status":"ok","registry":{"count":0,"db":"...","ingest_dir":"..."}}
```

---

## 六、每天的工作流程

### 6.1 拉取最新代码

```powershell
cd D:\MoDora-orchestrator
git pull
```

### 6.2 跑离线测试

```powershell
.\.venv\Scripts\Activate.ps1
python -m orchestrator._smoke_offline
```

如果全绿就没问题。`--reload` 模式的 orchestrator **不需要手动重启**，
它会自动检测到文件变化并重载。

### 6.3 测试 → 反馈

用以下格式给我发 bug 报告（**拍脑袋描述的 bug 很难定位，请务必按格式来**）：

```
【触发命令】: 比如 curl -X POST http://127.0.0.1:8888/process ...
             或者前端做了什么操作
【输入文件】: 用的哪份模板 + 哪些参考素材（文件名）
【期望结果】: 某个格子应该填什么
【实际结果】: 填了什么 / 空了 / 报错了
【orchestrator 日志】: 最后 50 行（从跑 uvicorn 的那个窗口复制）
```

---

## 七、关掉服务

在每个 PowerShell 窗口按 `Ctrl+C` 即可停止对应服务。

---

## 八、紧急情况速查

| 问题 | 快速解法 |
|------|---------|
| **orchestrator 启动报端口被占用** | `netstat -ano \| findstr 8888`，找到 PID 后 `taskkill /PID xxxx /F` |
| **pip install 中途断了** | 重新跑一遍 `pip install -r orchestrator\requirements.txt`，pip 会跳过已安装的 |
| **git pull 报冲突** | 你不应该改仓库里的代码。如果不小心改了：`git stash` → `git pull` → `git stash pop`（或直接 `git checkout .` 放弃本地修改） |
| **LibreOffice 转 PDF 超时** | `.env` 里把 `LIBREOFFICE_TIMEOUT` 从 60 改成 120 |
| **DashScope 429 Too Many Requests** | 正常现象，代码会自动重试。如果频繁出现，把 `ORCH_QUESTION_CONCURRENCY` 从 8 降到 4 |
| **重启电脑后 ingest 数据丢了** | 你没设 `ORCH_INGEST_DIR`，数据在临时目录被清了。设好后重新 `/ingest` 一次 |
| **`python` 命令找不到** | 安装 Python 时没勾 "Add to PATH"。重新安装并勾选，或手动加环境变量 |
| **PowerShell 脚本禁止运行** | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`，输入 Y 确认 |

---

## 九、项目结构速览（了解就好）

```
MoDora-orchestrator/
├── .env.example          ← 环境变量模板，复制成 .env
├── MISSION.md            ← 项目总目标（中英双语），有空读一遍
├── orchestrator/         ← 我们写的编排层，核心代码都在这
│   ├── service.py        ← FastAPI 主服务（/ingest, /process, /health）
│   ├── llm.py            ← DashScope LLM 调用 + 自动重试
│   ├── excel_matcher.py  ← Excel 表头匹配（不走 LLM）
│   ├── table_ops.py      ← 读写 docx/xlsx 模板
│   ├── readers.py        ← 读各种格式的文本
│   ├── ingest_registry.py← ingest 状态持久化（sqlite）
│   ├── mock_modora.py    ← MoDora 模拟服务（测试用）
│   ├── _smoke_offline.py ← 离线测试
│   └── requirements.txt  ← Python 依赖
├── MoDora-backend/       ← MoDora 原始后端（不要改）
└── MoDora-frontend/      ← MoDora 前端（不要改）
```

**关键原则**：`MoDora-backend/` 和 `MoDora-frontend/` 里的东西**绝对不要改**，
我们只改 `orchestrator/` 里的代码。

---

> 有任何问题先截图，带上日志发给我。没有日志的 bug 反馈 = 没有反馈 😄
