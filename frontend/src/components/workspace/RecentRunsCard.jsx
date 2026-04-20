import { Check, Loader2, Clock, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

const DEFAULT_RUNS = [
  {
    title: '2024 Q3 山东环境空气质量',
    status: 'completed',
    meta: '16 张表 · 86% · 68 s',
  },
  {
    title: '国考职位表批量整理',
    status: 'processing',
    meta: '分析中 · 2/25 列 · ≈ 45 s',
    progress: 14,
  },
  {
    title: 'COVID-19 全球数据汇总',
    status: 'queued',
    meta: '排队中 · 第 2 位',
  },
]

const STATUS_STYLES = {
  completed: {
    Icon: Check,
    wrap: 'bg-emerald-50 border border-emerald-200 text-emerald-700',
    titleClass: 'text-ink-900',
  },
  processing: {
    Icon: Loader2,
    wrap: 'bg-primary-50 border border-primary-200 text-primary-700',
    iconClass: 'animate-spin [animation-duration:3s]',
    titleClass: 'text-ink-900',
  },
  queued: {
    Icon: Clock,
    wrap: 'bg-ink-100 border border-ink-200 text-ink-500',
    titleClass: 'text-ink-700',
  },
}

export function RecentRunsCard({ runs = DEFAULT_RUNS, onViewAll }) {
  return (
    <section className="rounded-xl border border-ink-200 bg-white overflow-hidden transition-shadow duration-200 hover:shadow-soft">
      <div className="px-5 pt-4 pb-3 flex items-center justify-between border-b border-ink-100">
        <span className="text-[11px] font-semibold tracking-[0.14em] text-ink-500 uppercase">
          Today · 今日生成
        </span>
        <button
          type="button"
          onClick={onViewAll}
          className="text-xs text-ink-500 hover:text-ink-900 transition-colors"
        >
          全部
        </button>
      </div>

      {runs.length === 0 ? (
        <div className="p-6 text-center">
          <div className="text-sm text-ink-600 font-medium">今天还没有任务</div>
          <p className="text-xs text-ink-500 mt-1">上传素材或模板,开始第一次填充</p>
        </div>
      ) : (
        <ul className="divide-y divide-ink-100">
          {runs.map((run, i) => (
            <RunItem key={i} run={run} />
          ))}
        </ul>
      )}
    </section>
  )
}

function RunItem({ run }) {
  const style = STATUS_STYLES[run.status] || STATUS_STYLES.queued
  const Icon = style.Icon

  return (
    <li className="px-5 py-3 hover:bg-paper-50 cursor-pointer transition-colors group">
      <div className="flex items-start gap-3">
        <div
          className={cn(
            'w-8 h-8 rounded-md flex-shrink-0 flex items-center justify-center',
            style.wrap,
          )}
        >
          <Icon className={cn('w-[15px] h-[15px]', style.iconClass)} strokeWidth={2.2} />
        </div>

        <div className="flex-1 min-w-0">
          <p className={cn('text-sm font-medium truncate', style.titleClass)}>
            {run.title}
          </p>
          <p className="text-[11px] text-ink-500 mt-0.5 font-mono">{run.meta}</p>
          {run.status === 'processing' && typeof run.progress === 'number' && (
            <div className="mt-1.5 h-1 rounded-full bg-ink-100 overflow-hidden">
              <div
                className="h-full bg-primary-600 rounded-full transition-all duration-500 progress-shimmer"
                style={{ width: `${run.progress}%` }}
              />
            </div>
          )}
        </div>

        {run.status === 'completed' && (
          <ChevronRight className="w-3.5 h-3.5 text-ink-300 group-hover:text-ink-600 transition-colors mt-1" />
        )}
      </div>
    </li>
  )
}
