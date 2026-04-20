import { useEffect, useState } from 'react'
import {
  Activity,
  Database,
  Key,
  Cpu,
  RefreshCw,
  AlertCircle,
  Server,
} from 'lucide-react'
import { PageShell, LiveStatus } from '@/components/page/PageShell'
import { InfoPanelCard } from '@/components/page/SectionLabel'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/Card'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { getHealth, getHistory } from '@/lib/api'

const TYPE_VARIANT = {
  ingest: 'primary',
  process: 'success',
  extract: 'warning',
  'doc-edit': 'default',
}

export function Dashboard() {
  const [health, setHealth] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refresh = async () => {
    setLoading(true)
    try {
      const [h, hist] = await Promise.all([getHealth(), getHistory(20)])
      setHealth(h)
      setHistory(hist.history || [])
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    refresh()
  }, [])

  const apiOk = health?.env?.llm_api_key_set
  const ingestCount = health?.registry?.count || 0
  const connected = !!health && !error

  return (
    <PageShell
      breadcrumb={['工作台', '运行状态']}
      status={
        <LiveStatus
          label={connected ? '后端已连接' : '后端未连接'}
          meta={health?.env?.llm_model || 'offline'}
          color={connected ? 'emerald' : 'amber'}
        />
      }
    >
      {/* Compact header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold text-ink-900 tracking-tight">运行状态</h1>
            <Badge variant="primary" className="gap-1">
              <Server className="w-3 h-3" />
              System
            </Badge>
            <Badge variant={connected ? 'success' : 'warning'}>
              {connected ? '运行中' : '未连接'}
            </Badge>
            <span className="hidden sm:inline text-[11px] text-ink-400 font-mono">
              {health?.env?.llm_model || '—'}
            </span>
          </div>
          <p className="text-xs text-ink-500">Orchestrator 的实时健康信息、素材库规模、LLM 凭据与模型。</p>
        </div>
        <Button variant="outline" onClick={refresh} loading={loading} className="shrink-0">
          <RefreshCw className="w-3.5 h-3.5" />
          刷新
        </Button>
      </div>

      {error && (
        <Card className="mt-6 border-red-200 bg-red-50/60">
          <CardContent className="flex items-start gap-3">
            <AlertCircle className="w-4 h-4 text-red-600 mt-0.5 shrink-0" />
            <div className="text-sm text-red-700">
              <div className="font-medium">无法连接后端</div>
              <p className="text-xs mt-1 text-red-600">
                {error} — 请确认 orchestrator 已在 :8888 启动。
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="mt-2 flex gap-8">
        {/* 主内容 */}
        <div className="flex-1 min-w-0 space-y-6">
          {/* Stat cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              icon={Activity}
              label="服务状态"
              value={connected ? '运行中' : '未连接'}
              variant={connected ? 'success' : 'destructive'}
            />
            <StatCard
              icon={Database}
              label="素材库"
              value={`${ingestCount} 份`}
              variant="primary"
            />
            <StatCard
              icon={Key}
              label="LLM 凭据"
              value={apiOk ? '已配置' : '未配置'}
              variant={apiOk ? 'success' : 'warning'}
              detail={health?.env?.llm_api_key_preview}
            />
            <StatCard
              icon={Cpu}
              label="模型"
              value={health?.env?.llm_model || '—'}
            />
          </div>

          {/* History */}
          <Card>
            <CardHeader>
              <CardTitle>最近操作</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {history.length === 0 ? (
                <div className="py-14 text-center">
                  <div className="w-10 h-10 rounded-lg bg-ink-100 flex items-center justify-center mx-auto mb-3">
                    <Activity className="w-4 h-4 text-ink-400" />
                  </div>
                  <p className="text-sm font-medium text-ink-600">
                    暂无操作记录
                  </p>
                  <p className="text-xs text-ink-400 mt-1">
                    开始使用后,这里会显示最近 20 条
                  </p>
                </div>
              ) : (
                <ul className="divide-y divide-ink-100">
                  {history.map((op) => (
                    <li
                      key={op.id}
                      className="px-5 py-3 flex items-center gap-4 hover:bg-ink-50 transition-colors"
                    >
                      <Badge variant={TYPE_VARIANT[op.type] || 'default'}>
                        {op.type}
                      </Badge>
                      <div className="flex-1 text-sm text-ink-700 truncate">
                        {op.detail}
                      </div>
                      <div className="text-[11px] text-ink-400 font-mono shrink-0">
                        {op.timestamp}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        {/* 右侧信息栏 */}
        <div className="hidden lg:flex flex-col gap-4 w-72 shrink-0">
          <SystemInfoCard health={health} />
          <QuickActionsCard />
        </div>
      </div>
    </PageShell>
  )
}

/* -------- 子组件 -------- */

function StatCard({ icon: Icon, label, value, detail, variant = 'default' }) {
  const iconVariant = {
    default: 'bg-ink-100 text-ink-600',
    primary: 'bg-primary-50 text-primary-600',
    success: 'bg-emerald-50 text-emerald-600',
    warning: 'bg-amber-50 text-amber-600',
    destructive: 'bg-red-50 text-red-600',
  }
  return (
    <Card>
      <CardContent className="flex items-start gap-3.5">
        <div
          className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${iconVariant[variant]}`}
        >
          <Icon className="w-5 h-5" />
        </div>
        <div className="min-w-0">
          <div className="text-[11px] font-semibold text-ink-400 uppercase tracking-wider mb-1">
            {label}
          </div>
          <div className="text-base font-semibold text-ink-900 truncate">
            {value}
          </div>
          {detail && (
            <div className="text-[11px] text-ink-400 mt-0.5 font-mono truncate">
              {detail}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function SystemInfoCard({ health }) {
  const rows = [
    { label: 'Backend', value: health ? ':8888' : '—' },
    { label: 'Version', value: 'v0.1.0' },
    { label: 'Persistence', value: health?.env?.persist_dir || '—' },
    { label: 'Concurrency', value: health?.env?.llm_concurrency || '—' },
  ]
  return (
    <InfoPanelCard label="System Info">
      <dl className="space-y-2">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between gap-2 text-xs">
            <dt className="text-ink-500">{r.label}</dt>
            <dd className="text-ink-700 font-mono truncate max-w-[60%]">
              {r.value}
            </dd>
          </div>
        ))}
      </dl>
    </InfoPanelCard>
  )
}

function QuickActionsCard() {
  return (
    <InfoPanelCard label="Quick Actions">
      <ul className="space-y-2">
        <ActionLink href="/workspace" label="打开工作台" />
        <ActionLink href="/table-fill" label="开始新一次填表" />
        <ActionLink href="/library" label="查看素材库" />
      </ul>
    </InfoPanelCard>
  )
}

function ActionLink({ href, label }) {
  return (
    <li>
      <a
        href={href}
        className="group flex items-center justify-between gap-2 px-2.5 py-2 rounded-md hover:bg-ink-50 text-xs text-ink-700 hover:text-ink-900 transition-colors"
      >
        <span>{label}</span>
        <span className="text-ink-300 group-hover:text-primary-500 transition-colors">
          →
        </span>
      </a>
    </li>
  )
}
