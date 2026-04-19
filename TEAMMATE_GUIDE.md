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

需要开 **三个** PowerShell 窗口（都要先 `cd` 到项目目录 + 激活虚拟环境）。

> 每个窗口都先执行：
> ```powershell
> cd D:\MoDora-orchestrator      # 换成你的项目路径
> .\.venv\Scripts\Activate.ps1
> ```

### 窗口 1：mock_modora（md_txt 通道，端口 8005）

```powershell
python -m uvicorn orchestrator.mock_modora:app --host 127.0.0.1 --port 8005
```

### 窗口 2：mock_modora（word 通道，端口 8006）

```powershell
$env:MOCK_DOCS_DIR='C:\tmp\mock_modora_word'
python -m uvicorn orchestrator.mock_modora:app --host 127.0.0.1 --port 8006
```

> 💡 两个 mock 实例需要不同的 `MOCK_DOCS_DIR`，否则文件会互相覆盖。

### 窗口 3：orchestrator（端口 8888）

```powershell
python -m uvicorn orchestrator.service:app --host 127.0.0.1 --port 8888 --reload
```

看到 `Uvicorn running on http://127.0.0.1:8888` 就说明启动成功了。

> **如果你有真正的 MoDora 后端**，就不需要窗口 1 和 2，直接在 `.env` 里把
> `BACKEND_MD_TXT_URL` 和 `BACKEND_WORD_URL` 指向真实 MoDora 的地址即可。

### 验证服务正常

打开第四个 PowerShell（或浏览器），运行：
```powershell
curl.exe http://127.0.0.1:8888/health
```

应该返回（注意看 `env` 字段）：
```json
{
  "status": "ok",
  "registry": {"count": 0, "db": "...", "ingest_dir": "..."},
  "env": {
    "env_file_loaded": true,
    "env_file_path": "D:\\MoDora-orchestrator\\.env",
    "llm_api_key_set": true,
    "llm_api_key_preview": "sk-xxx…abcd",
    "llm_model": "qwen-plus"
  }
}
```

> ⚠️ **注意用 `curl.exe` 而不是 `curl`**。PowerShell 的 `curl` 是 `Invoke-WebRequest` 的别名，行为不同。

### 如果 `env_file_loaded: false` 或 `llm_api_key_set: false`

说明 `.env` 没生效。按这个顺序排查（**不要**听别的 AI 让你加 `--env-file`，uvicorn 根本没这个参数）：

**① 确认文件名和位置**

```powershell
# 必须在项目根目录（和 orchestrator/ 同级）
ls D:\MoDora-orchestrator\.env
```

- 文件名必须是 `.env`，不是 `.env.example`、不是 `.env.txt`
- 位置必须在 **repo 根目录**，不是 `orchestrator\` 子目录下
- Windows 资源管理器默认隐藏以点开头的文件 → 建议用 `ls` 或 VS Code 确认

**② 确认文件编码**

Windows 记事本保存会加 UTF-8 BOM，`python-dotenv` 可能解析失败：
```powershell
# 用 VS Code 打开 .env → 右下角确认是 "UTF-8"（不是 "UTF-8 with BOM"）
# 或命令行查：
Get-Content D:\MoDora-orchestrator\.env -Encoding Byte -TotalCount 3
# 如果前三个字节是 239 187 191 → 有 BOM，需要重新用 UTF-8（无 BOM）保存
```

**③ 确认内容格式**

打开 `.env`，检查：
- `LLM_API_KEY=sk-xxxx`  —— `=` 前后**不能有空格**
- 值**不要**加引号（除非值本身含空格）
- 没有中文引号 `"..."` 或全角字符
- 注释用 `#`，不要用 `//`

**④ 看 orchestrator 启动日志的第一行**

启动窗口（窗口 3）应该有这行：
```
orchestrator - .env loaded=True path=...\.env  LLM_API_KEY=sk-xxx…abcd  LLM_MODEL=qwen-plus
```
如果 `loaded=False`，说明文件路径不对。

**⑤ 兜底方案：直接设进程环境变量**

如果以上都不行（比如 `.env` 里有奇怪字符），可以在启动 orchestrator 的那个窗口里**先**设置变量，再启动：
```powershell
$env:LLM_API_KEY = "sk-你的真实key"
$env:LLM_MODEL   = "qwen-plus"
python -m uvicorn orchestrator.service:app --host 127.0.0.1 --port 8888 --reload
```
这样绕开了 `.env` 文件，直接用进程环境变量，`curl /health` 应该立刻看到 `llm_api_key_set: true`。

---

## 五点五、真实端到端测试（最重要的部分！）

> 下面是**完整的测试流程**：先灌素材（`/ingest`），再填表（`/process`），最后检查产出文件。
> **请务必按顺序操作，跳步会报错。**

### 准备测试文件

你需要准备两类文件：

| 类别 | 说明 | 示例 |
|------|------|------|
| **参考素材**（最多 16 份） | 包含答案的原始资料 | `公司财报.xlsx`、`项目说明.docx`、`通知.md`、`简介.txt` |
| **空白模板**（最多 5 份） | 需要被填充的表格 | `待填表格.docx`（内含空表格）、`汇总表.xlsx`（有空列） |

把这些文件**放到一个方便的文件夹里**，比如 `D:\test_data\`。

---

### Step A：上传参考素材（POST /ingest）

这一步把参考素材灌进系统。**只需要做一次**，之后的多份模板共用这批素材。

打开一个**新的 PowerShell 窗口**（窗口 3），运行：

```powershell
# ============================================================
# 根据你的素材类型，修改下面的文件路径
# ============================================================

# 方式一：如果只有 Excel 素材
curl.exe -X POST http://127.0.0.1:8888/ingest `
  -F "ref_excel=@D:\test_data\公司财报.xlsx" `
  -F "ref_excel=@D:\test_data\销售数据.xlsx"

# 方式二：如果有混合类型的素材（Excel + Word + 文本）
curl.exe -X POST http://127.0.0.1:8888/ingest `
  -F "ref_excel=@D:\test_data\公司财报.xlsx" `
  -F "ref_md_txt=@D:\test_data\项目说明.md" `
  -F "ref_md_txt=@D:\test_data\通知.txt" `
  -F "ref_word=@D:\test_data\背景资料.docx"
```

> ⚠️ **注意**：
> - `@` 符号不能省，它表示"上传这个文件"
> - 文件路径里如果有空格，用双引号包起来：`-F "ref_excel=@\"D:\test data\文件.xlsx\""`
> - 三个字段对应三种通道：`ref_excel`（Excel）、`ref_md_txt`（md/txt）、`ref_word`（Word）
> - 每个通道最多 6 个文件，总共最多 16 个

**正常返回**（JSON）：
```json
{
  "count": 4,
  "succeeded": 4,
  "failed": 0,
  "docs": [
    {"original_name": "公司财报.xlsx", "channel": "excel", "status": "ok", ...},
    {"original_name": "项目说明.md", "channel": "md_txt", "status": "ok", ...},
    ...
  ]
}
```

**关键检查点**：
- `"failed": 0` → 全部成功 ✅
- 如果有 `"failed": N`，看 `docs` 数组里 `status` 为 `"failed:..."` 的条目，截图发给我

**这一步可能比较慢**（30 秒 ~ 几分钟），因为：
1. Word/md/txt 文件会被 LibreOffice 转成 PDF
2. PDF 会被上传到 MoDora 做 OCR + 建树
3. 代码会等 MoDora 处理完才返回

---

### Step B：检查素材状态（GET /ingest）

如果你忘了上次 ingest 了什么，或者想确认状态：

```powershell
curl.exe http://127.0.0.1:8888/ingest
```

返回格式同上，会告诉你当前库里有哪些素材。

---

### Step C：填充模板（POST /process）

**每份模板调一次**。这是核心功能——系统会读取模板的表头，从素材里找答案，填进去。

```powershell
# 填充一份 Word 模板
curl.exe -X POST http://127.0.0.1:8888/process `
  -F "design_file=@D:\test_data\待填表格.docx" `
  -F "requirement=2024年度" `
  -o D:\test_data\结果_待填表格.docx

# 填充一份 Excel 模板
curl.exe -X POST http://127.0.0.1:8888/process `
  -F "design_file=@D:\test_data\汇总表.xlsx" `
  -F "requirement=华东地区" `
  -o D:\test_data\结果_汇总表.xlsx
```

**参数说明**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `design_file` | ✅ | 空白模板文件（`.docx` 或 `.xlsx`） |
| `requirement` | ❌ | 自然语言约束条件，比如"2024年"、"华东地区"、"Q3数据"。留空也行 |
| `-o 路径` | ❌ | 把返回的填充后文件保存到本地。**不加 -o 会把二进制内容打到终端上（乱码）** |

**正常结果**：
- 命令跑完后，`D:\test_data\结果_待填表格.docx` 就是填好的文件
- 用 Word / Excel 打开它，检查表格里的格子是否被填上了正确的内容

**这一步耗时约 10~90 秒**，取决于表格大小和素材数量。

---

### Step D：检查结果

打开产出文件，逐个格子对照：

1. **格式是否完好？** → 字体、合并单元格、列宽应该和原模板一模一样
2. **内容是否正确？** → 对照参考素材，填的答案对不对
3. **有没有空格子？** → 应该填但没填的，记下来
4. **有没有填错的？** → 填了但答案不对的，记下来

---

### Step E：多模板连续测试

比赛场景是 **16 份素材 + 5 份模板**。真实测法：

```powershell
# 1. 一次性灌入全部素材（只做一次）
curl.exe -X POST http://127.0.0.1:8888/ingest `
  -F "ref_excel=@D:\test_data\素材1.xlsx" `
  -F "ref_excel=@D:\test_data\素材2.xlsx" `
  -F "ref_md_txt=@D:\test_data\素材3.md" `
  -F "ref_md_txt=@D:\test_data\素材4.txt" `
  -F "ref_word=@D:\test_data\素材5.docx" `
  -F "ref_word=@D:\test_data\素材6.docx"

# 2. 逐份填模板（每份调一次 /process）
curl.exe -X POST http://127.0.0.1:8888/process -F "design_file=@D:\test_data\模板1.docx" -o D:\test_data\结果1.docx
curl.exe -X POST http://127.0.0.1:8888/process -F "design_file=@D:\test_data\模板2.xlsx" -o D:\test_data\结果2.xlsx
curl.exe -X POST http://127.0.0.1:8888/process -F "design_file=@D:\test_data\模板3.docx" -o D:\test_data\结果3.docx
curl.exe -X POST http://127.0.0.1:8888/process -F "design_file=@D:\test_data\模板4.xlsx" -o D:\test_data\结果4.xlsx
curl.exe -X POST http://127.0.0.1:8888/process -F "design_file=@D:\test_data\模板5.docx" -o D:\test_data\结果5.docx
```

**关键计时**：每次 `/process` 必须 **< 90 秒**。如果超时了，告诉我具体是哪一步慢（看 orchestrator 窗口的日志）。

---

### 常见测试错误

| 错误 | 原因 | 解法 |
|------|------|------|
| `没有已入库的素材。请先调用 POST /ingest` | 忘了先 ingest，或者重启后 ingest 数据丢了 | 重新跑一次 Step A |
| `模板表头为空` | 模板文件里没有表格 / 表头行是空的 | 检查模板文件，确保第一行是表头 |
| `模板解析失败` | 文件格式不对（比如 `.doc` 而不是 `.docx`） | 必须是 `.docx` 或 `.xlsx`，不支持旧版 `.doc` / `.xls` |
| `-o` 出来的文件是 0 KB | 请求失败了，错误信息被吃掉了 | 不加 `-o` 重跑一次，看返回的错误 JSON |
| 终端输出一堆乱码 | 忘了加 `-o` 保存文件 | 加上 `-o D:\test_data\结果.docx` |
| 产出文件打开后格式乱了 | 可能是 bug | 截图 + 原模板 + 产出文件一起发给我 |
| `curl` 不是内部命令 | Windows 旧版没自带 curl | 用 `curl.exe`（加 .exe）或者升级 Windows |

---

### Step F：赛方测试集（三个真实案例，直接复制粘贴）

> 测试数据在 `testData\包含模板文件\` 目录下。下面的命令假设项目在 `D:\MoDora-orchestrator`，
> 如果你的路径不同请替换。**每个 TC 之间不需要重启服务，但需要重新 ingest。**

#### TC1：山东省空气质量（Word 多表 + Excel 20000 行，纯 Excel 匹配）

```powershell
# 1. Ingest（只有 Excel 素材）
curl.exe -X POST http://127.0.0.1:8888/ingest `
  -F "ref_excel=@testData\包含模板文件\2025山东省环境空气质量监测数据信息\山东省环境空气质量监测数据信息202512171921_0.xlsx"

# 2. Process（Word 模板，3 个表：德州/潍坊/临沂）
curl.exe -X POST http://127.0.0.1:8888/process `
  -F "design_file=@testData\包含模板文件\2025山东省环境空气质量监测数据信息\2025山东省环境空气质量监测数据信息-模板.docx" `
  -F "requirement=完成填表工作，要求提取表格中对应数据。模板文件中对应有三个表，并且每一个表上文均有对该表的描述。表一：监测时间：2025-11-25 09:00:00.0 城市：德州市 表二：监测时间：2025-11-25 09:00:00.0 城市：潍坊市 表三：监测时间：2025-11-25 09:00:00.0 城市：临沂市" `
  -o testData\TC1_output.docx
```

**预期结果**：
- 耗时 **< 60 秒**
- 输出 `.docx` 包含 3 个表，分别填入德州市/潍坊市/临沂市的监测站点数据
- 每个表 25~30 行，8 列全填满（0 空格子）
- 用 Word 打开检查：城市列只包含对应城市，AQI/PM2.5 等数值合理

---

#### TC2：中国城市经济百强（Excel 模板 + Word 素材，100 行 × 5 列）

```powershell
# 1. Ingest（只有 Word 素材）
curl.exe -X POST http://127.0.0.1:8888/ingest `
  -F "ref_word=@testData\包含模板文件\2025年中国城市经济百强全景报告\2025年中国城市经济百强全景报告.docx"

# 2. Process
curl.exe -X POST http://127.0.0.1:8888/process `
  -F "design_file=@testData\包含模板文件\2025年中国城市经济百强全景报告\2025年中国城市经济百强全景报告-模板.xlsx" `
  -F "requirement=帮我智能填表" `
  -o testData\TC2_output.xlsx
```

**预期结果**：
- 耗时 **< 90 秒**（已验证 ~76 秒）
- 输出 `.xlsx` 有 101 行（1 表头 + 100 城市），5 列：城市名/GDP/人口/人均GDP/公共预算
- 500/500 单元格全填满
- 用 Excel 打开检查：上海 GDP ~56700 亿，北京 ~52000 亿，数值量级合理即可

---

#### TC3：COVID-19 全球数据（Excel 模板 + Excel+Word 素材，日期范围过滤）

```powershell
# 1. Ingest（Excel + Word 混合素材）
curl.exe -X POST http://127.0.0.1:8888/ingest `
  -F "ref_excel=@testData\包含模板文件\COVID-19数据集\COVID-19全球数据集（节选）.xlsx" `
  -F "ref_word=@testData\包含模板文件\COVID-19数据集\中国COVID-19新冠疫情情况.docx"

# 2. Process
curl.exe -X POST http://127.0.0.1:8888/process `
  -F "design_file=@testData\包含模板文件\COVID-19数据集\COVID-19 模板.xlsx" `
  -F "requirement=智能填表，将两个文件的内容中日期一列从2020/7/1到2020/8/31的数据填入模板中" `
  -o testData\TC3_output.xlsx
```

**预期结果**：
- 耗时 **< 60 秒**（已验证 ~52 秒）
- 输出 `.xlsx` 有 ~43 行，6 列：国家/大洲/人均GDP/人口/每日检测数/病例数
- 填充率 ≥ 99%（1~2 个空格子可以接受）
- 用 Excel 打开检查：国家名都是英文（Albania, Algeria 等），数值量级合理

---

#### 测试结果对照表（我已验证通过的基准）

| TC | 耗时 | 行数 | 填充率 | 关键检查点 |
|----|------|------|--------|-----------|
| TC1 | 56s | 3 表 × 25~30 行 | 100% | 每表只包含对应城市的数据 |
| TC2 | 76s | 100 行 | 100% | GDP 数值量级在千亿~万亿 |
| TC3 | 52s | 42 行 | 99.6% | 数据仅包含 2020/7/1~8/31 时间范围 |

> ⚠️ 由于 LLM 有随机性，你跑出来的数值可能和我的略有不同，**量级对就行**。
> 如果耗时 >90 秒或填充率 <80%，截图 + orchestrator 日志发给我。

---

### 如果你更喜欢用 Python 测试（可选）

如果觉得 curl 命令太长，可以用 Python 脚本：

```python
import httpx, pathlib

BASE = "http://127.0.0.1:8888"
DATA = pathlib.Path(r"D:\test_data")

# ---- Step A: ingest ----
resp = httpx.post(f"{BASE}/ingest", files=[
    ("ref_excel", open(DATA / "公司财报.xlsx", "rb")),
    ("ref_md_txt", open(DATA / "项目说明.md", "rb")),
    ("ref_word", open(DATA / "背景资料.docx", "rb")),
], timeout=300)
print("ingest:", resp.json())

# ---- Step C: process ----
resp = httpx.post(f"{BASE}/process", files={
    "design_file": open(DATA / "待填表格.docx", "rb"),
}, data={"requirement": "2024年度"}, timeout=120)

out = DATA / "结果_待填表格.docx"
out.write_bytes(resp.content)
print(f"saved to {out}  ({out.stat().st_size} bytes)")
```

把上面的代码保存成 `test_run.py`，放在项目目录下，运行：
```powershell
python test_run.py
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
