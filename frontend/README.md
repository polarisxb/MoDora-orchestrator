# MoDora Orchestrator UI

React + Vite + Tailwind frontend for the MoDora orchestrator backend.

Covers all three competition modules:

| 模块 | 路由 | 功能 |
|------|------|------|
| ① 文档智能编辑 | `/doc-edit` | 自然语言 → Word 文档编辑（格式 / 排版 / 内容） |
| ② 信息提取 | `/extract` | 文档 → 实体 / 摘要 / 关键信息 JSON |
| ③ 表格智能填写 | `/table-fill` | 素材 + 模板 → 自动填表 |
| 概览 | `/` | 服务状态 + 操作历史 |
| 素材库 | `/library` | 已入库素材管理 |

## 启动

### 1. 安装依赖

```powershell
cd frontend
npm install
```

### 2. 确保后端正在运行

```powershell
# 在另一个终端，仓库根目录下
$env:LLM_API_KEY="sk-..."
python -m orchestrator.service
# 监听 http://127.0.0.1:8888
```

### 3. 启动前端开发服务器

```powershell
npm run dev
# 打开 http://127.0.0.1:5173
```

Vite 会把 `/api/*` 的请求代理到后端 `http://127.0.0.1:8888`。

## 生产构建

```powershell
npm run build
# 输出到 dist/
```

部署时如果后端不在同源，设置环境变量：

```powershell
$env:VITE_API_BASE="https://your-backend.example.com"
npm run build
```

## 技术栈

- **React 18** + **Vite 5** — 现代构建
- **Tailwind CSS 3** — 工具优先样式
- **react-router-dom** — 客户端路由
- **axios** — HTTP 客户端
- **lucide-react** — 图标
- **clsx + tailwind-merge** — shadcn/ui 风格的 className 合并

UI 组件遵循 shadcn/ui 视觉规范（位于 `src/components/ui/`），但不依赖 shadcn 的 CLI。
后续如需更多组件，可执行 `npx shadcn-ui@latest init` 接入。

## 目录结构

```
frontend/
├── src/
│   ├── lib/
│   │   ├── api.js          # 后端 API 客户端
│   │   └── utils.js        # cn / formatBytes / downloadBlob
│   ├── components/
│   │   ├── ui/             # 通用 UI 组件 (Button, Card, Input, ...)
│   │   ├── Sidebar.jsx
│   │   └── PageHeader.jsx
│   ├── pages/
│   │   ├── Dashboard.jsx   # 概览
│   │   ├── DocEdit.jsx     # 模块①
│   │   ├── Extract.jsx     # 模块②
│   │   ├── TableFill.jsx   # 模块③
│   │   └── Library.jsx     # 素材库
│   ├── App.jsx             # 路由
│   ├── main.jsx            # 入口
│   └── index.css           # Tailwind 入口
├── package.json
├── vite.config.js          # 含 /api → :8888 代理
├── tailwind.config.js
└── postcss.config.js
```

## 开发提示

**后端未启动时**，概览页会显示红色提示。其他页面提交请求会通过 toast 报错。

**OCR 入库较慢**：上传 Word 素材后，后端会调用 LibreOffice 转 PDF + MoDora 跑 OCR，可能需要 30 秒~2 分钟，请耐心等待。

**Excel 素材**走结构化匹配通道，入库快、填表准确率高，推荐优先使用。
