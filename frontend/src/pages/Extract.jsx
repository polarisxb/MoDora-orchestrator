import { useState, useMemo } from 'react'
import {
  Sparkles,
  FileText,
  Tag,
  Calendar,
  Building2,
  Layers,
  ArrowRight,
  BarChart3,
} from 'lucide-react'
import { PageShell, LiveStatus } from '@/components/page/PageShell'
import { InfoPanelCard } from '@/components/page/SectionLabel'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Input, Label } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { FileDropzone } from '@/components/ui/FileDropzone'
import { useToast } from '@/components/ui/Toast'
import { extractInfo } from '@/lib/api'

const ENTITY_VARIANT = {
  人名: 'primary',
  机构: 'success',
  地点: 'warning',
  日期: 'default',
  金额: 'destructive',
  百分比: 'destructive',
  产品: 'primary',
  指标: 'success',
  其他: 'default',
}

export function Extract() {
  const [files, setFiles] = useState([])
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const toast = useToast()

  const submit = async () => {
    if (!files.length) return toast.error('请先上传文档')
    setLoading(true)
    setResult(null)
    try {
      const data = await extractInfo(files[0], query)
      setResult(data)
      toast.success(`提取完成 · 共 ${data.entities?.length || 0} 个实体`)
    } catch (e) {
      toast.error(`提取失败: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <PageShell
      breadcrumb={['工作台', '信息提取']}
      status={<LiveStatus meta="qwen-plus · 128k" />}
    >
      {/* Compact header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3 mb-6">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold text-ink-900 tracking-tight">信息提取</h1>
            <Badge variant="primary" className="gap-1">
              <Layers className="w-3 h-3" />
              模块 ②
            </Badge>
            <Badge variant="default">实体 · 摘要 · 关键信息</Badge>
            <span className="hidden sm:inline text-[11px] text-ink-400 font-mono">.docx · .pdf · .xlsx · .md · .txt</span>
          </div>
          <p className="text-xs text-ink-500">自动识别人名、机构、金额、日期等关键实体,生成文档摘要,保留原文上下文供追溯。</p>
        </div>
      </div>

      <div className="flex gap-8">
        {/* 主内容 */}
        <div className="flex-1 min-w-0 space-y-6">
          {/* 输入 */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2.5">
                <StepMark>1</StepMark>
                上传文档 & 描述需求
              </CardTitle>
              <CardDescription>
                支持多种格式,单份上传。需求留空则提取所有类型实体。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <FileDropzone
                accept=".docx,.pdf,.xlsx,.xls,.md,.txt"
                files={files}
                onFilesChange={setFiles}
              />
              <div>
                <Label>提取要求 · 可选</Label>
                <Input
                  placeholder="例如:提取所有公司名和金额"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              </div>
              <div className="flex items-center justify-between pt-2 border-t border-ink-100">
                <span className="text-xs text-ink-500">
                  {loading ? '识别中...' : '处理完成后会自动在下方展示结果'}
                </span>
                <Button onClick={submit} loading={loading} size="lg">
                  <Sparkles className="w-4 h-4" />
                  {loading ? '提取中…' : '开始提取'}
                  {!loading && <ArrowRight className="w-3.5 h-3.5" />}
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* 结果 */}
          {!result && !loading && <ResultEmpty />}
          {loading && <ResultSkeleton />}
          {result && <ResultView result={result} />}
        </div>

        {/* 右侧信息栏 */}
        <div className="hidden lg:flex flex-col gap-4 w-72 shrink-0">
          <EntityStatsCard result={result} />
          <CapabilitiesCard />
        </div>
      </div>
    </PageShell>
  )
}

/* ---------- 子组件 ---------- */

function StepMark({ children }) {
  return (
    <span className="w-6 h-6 rounded-md border border-primary-200 bg-primary-50 text-xs font-mono text-primary-600 flex items-center justify-center">
      {children}
    </span>
  )
}

function ResultEmpty() {
  return (
    <Card className="border-dashed">
      <CardContent className="py-16 text-center">
        <div className="w-12 h-12 rounded-lg bg-ink-100 flex items-center justify-center mx-auto mb-3">
          <FileText className="w-5 h-5 text-ink-400" />
        </div>
        <p className="text-sm font-medium text-ink-600">结果将在此展示</p>
        <p className="text-xs text-ink-400 mt-1">
          上传文档并点击「开始提取」
        </p>
      </CardContent>
    </Card>
  )
}

function ResultSkeleton() {
  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="h-4 w-1/3 rounded bg-ink-200 animate-pulse" />
        <div className="h-4 w-full rounded bg-ink-200 animate-pulse" />
        <div className="h-4 w-5/6 rounded bg-ink-200 animate-pulse" />
        <div className="h-4 w-2/3 rounded bg-ink-200 animate-pulse" />
      </CardContent>
    </Card>
  )
}

function ResultView({ result }) {
  return (
    <div className="space-y-6">
      {result.summary && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary-500" />
              文档摘要
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-ink-700 leading-relaxed">
              {result.summary}
            </p>
          </CardContent>
        </Card>
      )}

      {result.key_info && Object.keys(result.key_info).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>关键信息</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {Object.entries(result.key_info).map(([k, v]) => (
              <div key={k} className="flex items-start gap-3 text-sm">
                <KeyIcon label={k} />
                <div className="flex-1">
                  <div className="text-xs text-ink-500">{k}</div>
                  <div className="text-ink-800 font-medium">{v ?? '—'}</div>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {result.entities?.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>
              提取实体{' '}
              <span className="text-ink-400 font-normal">
                · {result.entities.length}
              </span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 max-h-[480px] overflow-y-auto scroll-thin">
            {result.entities.map((ent, i) => (
              <div
                key={i}
                className="p-3 rounded-md bg-ink-50 border border-ink-100"
              >
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant={ENTITY_VARIANT[ent.type] || 'default'}>
                    {ent.type}
                  </Badge>
                  <span className="text-sm font-medium text-ink-800">
                    {ent.value}
                  </span>
                </div>
                {ent.context && (
                  <p className="text-xs text-ink-500">⟨ {ent.context} ⟩</p>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {result.tables?.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>文档中的表格 · {result.tables.length}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {result.tables.map((t, i) => (
              <div key={i} className="text-sm">
                <div className="font-medium text-ink-800">{t.title}</div>
                <div className="text-xs text-ink-500 mt-1">
                  {t.row_count} 行 · 表头: {t.headers?.join(' | ')}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="text-[11px] text-ink-400 font-mono">
        {result.file_name} · {result.file_type} · {result.char_count} chars
      </div>
    </div>
  )
}

function KeyIcon({ label }) {
  const Icon = label.includes('日期')
    ? Calendar
    : label.includes('机构') || label.includes('作者')
      ? Building2
      : Tag
  return (
    <div className="w-8 h-8 rounded-md bg-primary-50 text-primary-600 flex items-center justify-center shrink-0">
      <Icon className="w-4 h-4" />
    </div>
  )
}

/** 右栏:实体类型分布 */
function EntityStatsCard({ result }) {
  const stats = useMemo(() => {
    if (!result?.entities?.length) return []
    const counts = {}
    result.entities.forEach((e) => {
      counts[e.type] = (counts[e.type] || 0) + 1
    })
    const total = result.entities.length
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([type, count]) => ({ type, count, pct: (count / total) * 100 }))
  }, [result])

  return (
    <InfoPanelCard
      label="Entity Stats"
      labelMeta={result ? `${result.entities?.length || 0} 实体` : '待处理'}
    >
      {stats.length === 0 ? (
        <div className="py-4 text-center">
          <BarChart3 className="w-4 h-4 text-ink-300 mx-auto mb-2" />
          <p className="text-xs text-ink-500">处理完成后显示类型分布</p>
        </div>
      ) : (
        <ul className="space-y-2.5">
          {stats.map((s) => (
            <li key={s.type}>
              <div className="flex items-center justify-between text-xs mb-1">
                <span className="text-ink-700">{s.type}</span>
                <span className="text-ink-500 font-mono tabular-nums">
                  {s.count}
                </span>
              </div>
              <div className="h-1 rounded-full bg-ink-100 overflow-hidden">
                <div
                  className="h-full bg-primary-500 rounded-full transition-all duration-500"
                  style={{ width: `${s.pct}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </InfoPanelCard>
  )
}

function CapabilitiesCard() {
  return (
    <InfoPanelCard label="Capabilities">
      <ul className="space-y-2 text-xs text-ink-600">
        <li className="flex gap-2">
          <Sparkles className="w-3 h-3 text-primary-500 mt-0.5 shrink-0" />
          <span>人名、机构、地点、日期、金额自动识别</span>
        </li>
        <li className="flex gap-2">
          <Sparkles className="w-3 h-3 text-primary-500 mt-0.5 shrink-0" />
          <span>保留原文上下文片段,方便追溯</span>
        </li>
        <li className="flex gap-2">
          <Sparkles className="w-3 h-3 text-primary-500 mt-0.5 shrink-0" />
          <span>自动生成文档主题摘要</span>
        </li>
        <li className="flex gap-2">
          <Sparkles className="w-3 h-3 text-primary-500 mt-0.5 shrink-0" />
          <span>表格结构识别 · 表头 / 行数</span>
        </li>
      </ul>
    </InfoPanelCard>
  )
}
