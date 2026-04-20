import { useState, useEffect, useMemo } from 'react'
import {
  Download,
  FileSpreadsheet,
  FileText,
  FileType2,
  RefreshCw,
  Search,
  CheckCircle2,
  AlertCircle,
  FolderOpen,
  Database,
} from 'lucide-react'
import { PageShell, LiveStatus } from '@/components/page/PageShell'
import { InfoPanelCard } from '@/components/page/SectionLabel'
import { Card, CardContent } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { Input } from '@/components/ui/Input'
import { listMaterials, previewUrl } from '@/lib/api'
import { useToast } from '@/components/ui/Toast'

const CHANNEL_META = {
  excel: { name: 'Excel', icon: FileSpreadsheet, color: 'text-emerald-600', tint: 'bg-emerald-50' },
  md_txt: { name: 'MD/TXT', icon: FileText, color: 'text-primary-600', tint: 'bg-primary-50' },
  word: { name: 'Word', icon: FileType2, color: 'text-amber-600', tint: 'bg-amber-50' },
}

const CHANNELS_ORDER = ['all', 'excel', 'md_txt', 'word']
const CHANNEL_TAB_LABEL = {
  all: '全部',
  excel: 'Excel',
  md_txt: 'MD / TXT',
  word: 'Word',
}

export function Library() {
  const [materials, setMaterials] = useState(null)
  const [loading, setLoading] = useState(false)
  const [channel, setChannel] = useState('all')
  const [query, setQuery] = useState('')
  const toast = useToast()

  const refresh = async () => {
    setLoading(true)
    try {
      setMaterials(await listMaterials())
    } catch (e) {
      toast.error(`无法加载素材库: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    refresh()
  }, [])

  // 统计每通道数量
  const channelCounts = useMemo(() => {
    const counts = { all: 0, excel: 0, md_txt: 0, word: 0 }
    materials?.docs?.forEach((d) => {
      counts.all += 1
      if (counts[d.channel] != null) counts[d.channel] += 1
    })
    return counts
  }, [materials])

  // 过滤后的文件
  const filtered = useMemo(() => {
    if (!materials?.docs) return []
    return materials.docs.filter((d) => {
      if (channel !== 'all' && d.channel !== channel) return false
      if (query && !d.original_name.toLowerCase().includes(query.toLowerCase()))
        return false
      return true
    })
  }, [materials, channel, query])

  return (
    <PageShell
      breadcrumb={['工作台', '素材库']}
      status={<LiveStatus meta={materials ? `${materials.count} 份 · 成功 ${materials.succeeded}` : '加载中'} />}
    >
      {/* Compact page header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold text-ink-900 tracking-tight">素材库</h1>
            <Badge variant="primary" className="gap-1">
              <Database className="w-3 h-3" />
              {materials?.count ?? 0} 份
            </Badge>
            <span className="hidden sm:inline text-[11px] text-ink-400 font-mono">
              OCR · CCTree · Embedding
            </span>
          </div>
          <p className="text-xs text-ink-500">不同文件类型走独立通道,统一通过 CCTree 索引,可在任意填表任务中被检索与引用。</p>
        </div>
        <Button variant="outline" onClick={refresh} loading={loading} className="shrink-0">
          <RefreshCw className="w-3.5 h-3.5" />
          刷新
        </Button>
      </div>

      <div className="flex gap-8">
        {/* 主内容 */}
        <div className="flex-1 min-w-0 space-y-4">
          {/* 工具条: tabs + search */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-1 bg-ink-100 p-1 rounded-lg border border-ink-200">
              {CHANNELS_ORDER.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setChannel(c)}
                  className={
                    channel === c
                      ? 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-white text-ink-900 text-xs font-medium shadow-sm'
                      : 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-ink-500 hover:text-ink-900 text-xs font-medium transition-colors'
                  }
                >
                  {CHANNEL_TAB_LABEL[c]}
                  <span className="text-[10px] font-mono tabular-nums text-ink-400">
                    {channelCounts[c]}
                  </span>
                </button>
              ))}
            </div>
            <div className="relative sm:w-64">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-ink-400 pointer-events-none" />
              <Input
                placeholder="搜索文件名…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="pl-8"
              />
            </div>
          </div>

          {/* 列表 / 空态 */}
          {!materials || materials.count === 0 ? (
            <EmptyState />
          ) : filtered.length === 0 ? (
            <Card className="border-dashed">
              <CardContent className="py-14 text-center">
                <p className="text-sm text-ink-600 font-medium">
                  没有匹配的素材
                </p>
                <p className="text-xs text-ink-400 mt-1">
                  换个筛选条件或搜索词
                </p>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="p-0">
                <ul className="divide-y divide-ink-100">
                  {filtered.map((d, i) => (
                    <MaterialRow key={i} doc={d} />
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>

        {/* 右侧信息栏 */}
        <div className="hidden lg:flex flex-col gap-4 w-64 shrink-0">
          <StatsCard materials={materials} />
          <ChannelDistributionCard counts={channelCounts} />
          <UsageTipsCard />
        </div>
      </div>
    </PageShell>
  )
}

/* -------- 子组件 -------- */

function MaterialRow({ doc }) {
  const meta = CHANNEL_META[doc.channel] || {
    name: doc.channel,
    icon: FileText,
    color: 'text-ink-600',
    tint: 'bg-ink-100',
  }
  const Icon = meta.icon
  const previewable = !!doc.modora_filename || doc.channel === 'excel'
  return (
    <li className="px-5 py-3.5 flex items-center gap-4 hover:bg-paper-50 transition-colors group">
      <div className={`w-8 h-8 rounded-md ${meta.tint} flex items-center justify-center shrink-0`}>
        <Icon className={`w-4 h-4 ${meta.color}`} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-ink-800 truncate">
          {doc.original_name}
        </div>
        {doc.modora_filename && (
          <div className="text-[11px] text-ink-400 mt-0.5 font-mono truncate">
            → {doc.modora_filename}
          </div>
        )}
      </div>
      <Badge variant="default" className="shrink-0 hidden sm:inline-flex">
        {meta.name}
      </Badge>
      <span
        className={`inline-flex items-center gap-1 text-xs shrink-0 ${
          doc.status === 'ok' ? 'text-emerald-700' : 'text-red-600'
        }`}
      >
        {doc.status === 'ok' ? (
          <CheckCircle2 className="w-3.5 h-3.5" />
        ) : (
          <AlertCircle className="w-3.5 h-3.5" />
        )}
        {doc.status === 'ok' ? '已入库' : '失败'}
      </span>
      {previewable && doc.status === 'ok' && (
        <a
          href={previewUrl(
            doc.channel === 'excel' ? doc.original_name : doc.modora_filename,
          )}
          target="_blank"
          rel="noreferrer"
          className="text-ink-300 hover:text-primary-600 transition-colors opacity-0 group-hover:opacity-100 shrink-0"
          title="下载 / 预览"
        >
          <Download className="w-4 h-4" />
        </a>
      )}
    </li>
  )
}

function EmptyState() {
  return (
    <Card className="border-dashed">
      <CardContent className="py-20 text-center">
        <div className="w-12 h-12 rounded-lg bg-ink-100 flex items-center justify-center mx-auto mb-4">
          <FolderOpen className="w-5 h-5 text-ink-400" />
        </div>
        <p className="text-sm font-medium text-ink-600">素材库为空</p>
        <p className="text-xs text-ink-400 mt-1">
          前往「表格智能填写」页面上传第一份素材
        </p>
      </CardContent>
    </Card>
  )
}

function StatsCard({ materials }) {
  if (!materials) return null
  const successRate = materials.count
    ? Math.round((materials.succeeded / materials.count) * 100)
    : 0
  return (
    <InfoPanelCard label="Overview">
      <div className="grid grid-cols-3 gap-3">
        <Stat value={materials.count} label="总数" />
        <Stat value={materials.succeeded} label="成功" tone="emerald" />
        <Stat value={materials.failed} label="失败" tone={materials.failed ? 'red' : 'default'} />
      </div>
      <div className="mt-4 pt-3 border-t border-ink-100">
        <div className="flex items-center justify-between text-xs mb-1.5">
          <span className="text-ink-500">成功率</span>
          <span className="text-ink-900 font-semibold tabular-nums">
            {successRate}%
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-ink-100 overflow-hidden">
          <div
            className="h-full bg-emerald-500 rounded-full transition-all duration-500"
            style={{ width: `${successRate}%` }}
          />
        </div>
      </div>
    </InfoPanelCard>
  )
}

function Stat({ value, label, tone = 'default' }) {
  const color = {
    default: 'text-ink-900',
    emerald: 'text-emerald-600',
    red: 'text-red-600',
  }[tone]
  return (
    <div>
      <div className={`text-lg font-semibold tabular-nums ${color}`}>{value}</div>
      <div className="text-[11px] text-ink-500 mt-0.5">{label}</div>
    </div>
  )
}

function ChannelDistributionCard({ counts }) {
  const total = counts.all || 1
  const channels = ['excel', 'md_txt', 'word']
  return (
    <InfoPanelCard label="By Channel">
      <ul className="space-y-2.5">
        {channels.map((key) => {
          const meta = CHANNEL_META[key]
          const Icon = meta.icon
          const count = counts[key]
          const pct = (count / total) * 100
          return (
            <li key={key}>
              <div className="flex items-center gap-2 mb-1">
                <Icon className={`w-3.5 h-3.5 ${meta.color}`} />
                <span className="text-xs text-ink-700 flex-1">{meta.name}</span>
                <span className="text-xs text-ink-500 font-mono tabular-nums">
                  {count}
                </span>
              </div>
              <div className="h-1 rounded-full bg-ink-100 overflow-hidden ml-5">
                <div
                  className="h-full bg-primary-500 rounded-full transition-all duration-500"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </li>
          )
        })}
      </ul>
    </InfoPanelCard>
  )
}

function UsageTipsCard() {
  return (
    <InfoPanelCard label="Tips">
      <ul className="space-y-2 text-xs text-ink-600">
        <li className="flex gap-2">
          <span className="w-1 h-1 rounded-full bg-ink-400 mt-1.5 shrink-0" />
          入库后可在任意填表任务中引用
        </li>
        <li className="flex gap-2">
          <span className="w-1 h-1 rounded-full bg-ink-400 mt-1.5 shrink-0" />
          失败素材可以重新上传覆盖
        </li>
        <li className="flex gap-2">
          <span className="w-1 h-1 rounded-full bg-ink-400 mt-1.5 shrink-0" />
          同名文件会按上传时间区分
        </li>
      </ul>
    </InfoPanelCard>
  )
}
