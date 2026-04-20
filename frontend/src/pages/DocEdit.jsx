import { useState } from 'react'
import {
  Wand2,
  Lightbulb,
  Layers,
  ArrowRight,
  Type,
  AlignLeft,
  Replace,
  Heading1,
} from 'lucide-react'
import { PageShell, LiveStatus } from '@/components/page/PageShell'
import { InfoPanelCard } from '@/components/page/SectionLabel'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Textarea, Label } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { FileDropzone } from '@/components/ui/FileDropzone'
import { useToast } from '@/components/ui/Toast'
import { docEdit } from '@/lib/api'
import { downloadBlob } from '@/lib/utils'

const PRESETS = [
  { label: '把第 1 段加粗', category: '格式' },
  { label: '所有标题居中对齐', category: '对齐' },
  { label: '字体改为宋体 · 12 磅', category: '字体' },
  { label: '在第 1 段后插入一段新内容', category: '插入' },
  { label: '把"测试"全部替换为"正式"', category: '替换' },
  { label: '把所有 H2 升为 H1', category: '层级' },
]

const CAPABILITIES = [
  { icon: Type, label: '文字格式', hint: '加粗 / 斜体 / 字体 / 字号 / 颜色' },
  { icon: AlignLeft, label: '段落对齐', hint: '左 / 中 / 右 / 两端对齐' },
  { icon: Replace, label: '插入 / 替换', hint: '新增段落、查找替换、整段删除' },
  { icon: Heading1, label: '层级调整', hint: '设置 H1–H6、升降级标题' },
]

export function DocEdit() {
  const [files, setFiles] = useState([])
  const [instruction, setInstruction] = useState('')
  const [loading, setLoading] = useState(false)
  const toast = useToast()

  const submit = async () => {
    if (!files.length) return toast.error('请先上传 .docx 文件')
    if (!instruction.trim()) return toast.error('请输入编辑指令')
    setLoading(true)
    try {
      const blob = await docEdit(files[0], instruction)
      const baseName = files[0].name.replace(/\.docx$/i, '')
      downloadBlob(blob, `${baseName}_edited.docx`)
      toast.success('编辑完成,文件已开始下载')
    } catch (e) {
      toast.error(`编辑失败: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <PageShell
      breadcrumb={['工作台', '文档编辑']}
      status={<LiveStatus meta="qwen-plus · 128k" />}
    >
      {/* Compact header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3 mb-6">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold text-ink-900 tracking-tight">文档编辑</h1>
            <Badge variant="primary" className="gap-1">
              <Layers className="w-3 h-3" />
              模块 ①
            </Badge>
            <Badge variant="default">格式 · 排版 · 内容</Badge>
            <span className="hidden sm:inline text-[11px] text-ink-400 font-mono">.docx only</span>
          </div>
          <p className="text-xs text-ink-500">描述你想要的改动,系统会解析为结构化操作,保留原有样式并精准下刀。</p>
        </div>
      </div>

      <div className="flex gap-8">
        {/* 主内容 */}
        <div className="flex-1 min-w-0 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2.5">
                <StepMark>1</StepMark>
                上传 Word 文档
              </CardTitle>
              <CardDescription>当前仅支持 .docx 格式</CardDescription>
            </CardHeader>
            <CardContent>
              <FileDropzone
                accept=".docx"
                files={files}
                onFilesChange={setFiles}
                hint="拖拽或点击选择 .docx 文件"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2.5">
                <StepMark>2</StepMark>
                描述需要的改动
              </CardTitle>
              <CardDescription>
                指令示例:把标题加粗 · 第二段字体改为黑体 16 磅 · 所有段落两端对齐
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Label>自然语言指令</Label>
              <Textarea
                placeholder="把第一段标题加粗,字号设置为 18 磅..."
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                rows={4}
              />
              <div className="flex items-center justify-between pt-3 mt-3 border-t border-ink-100">
                <span className="text-xs text-ink-500">
                  {loading ? '应用指令中...' : '指令越具体,执行越稳'}
                </span>
                <Button onClick={submit} loading={loading} size="lg">
                  <Wand2 className="w-4 h-4" />
                  {loading ? '编辑中…' : '执行编辑'}
                  {!loading && <ArrowRight className="w-3.5 h-3.5" />}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* 右侧信息栏 */}
        <div className="hidden lg:flex flex-col gap-4 w-72 shrink-0">
          <PresetCard onPick={setInstruction} />
          <CapabilitiesCard />
        </div>
      </div>
    </PageShell>
  )
}

/* ------ 子组件 ------ */

function StepMark({ children }) {
  return (
    <span className="w-6 h-6 rounded-md border border-primary-200 bg-primary-50 text-xs font-mono text-primary-600 flex items-center justify-center">
      {children}
    </span>
  )
}

function PresetCard({ onPick }) {
  return (
    <InfoPanelCard
      label="Quick Presets"
      action={
        <span className="inline-flex items-center gap-1 text-[11px] text-ink-400">
          <Lightbulb className="w-3 h-3" />
          点击套用
        </span>
      }
    >
      <ul className="space-y-1.5">
        {PRESETS.map((p) => (
          <li key={p.label}>
            <button
              type="button"
              onClick={() => onPick(p.label)}
              className="group w-full text-left px-2.5 py-2 rounded-md hover:bg-ink-50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-1"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-ink-700 group-hover:text-ink-900 truncate">
                  {p.label}
                </span>
                <span className="text-[10px] text-ink-400 font-mono shrink-0">
                  {p.category}
                </span>
              </div>
            </button>
          </li>
        ))}
      </ul>
    </InfoPanelCard>
  )
}

function CapabilitiesCard() {
  return (
    <InfoPanelCard label="Capabilities">
      <ul className="space-y-3">
        {CAPABILITIES.map((c) => {
          const Icon = c.icon
          return (
            <li key={c.label} className="flex gap-3">
              <div className="w-7 h-7 rounded-md bg-primary-50 text-primary-600 flex items-center justify-center shrink-0">
                <Icon className="w-3.5 h-3.5" />
              </div>
              <div className="min-w-0">
                <div className="text-xs font-medium text-ink-900">{c.label}</div>
                <div className="text-[11px] text-ink-500 mt-0.5">{c.hint}</div>
              </div>
            </li>
          )
        })}
      </ul>
    </InfoPanelCard>
  )
}
