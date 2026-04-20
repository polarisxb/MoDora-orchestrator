/**
 * 实时 CCTree 可视化 — 1:1 匹配原型
 */
const DEFAULT_STATS = { nodes: 24, depth: 4, progress: 68 }

export function LiveTreeCard({ stats = DEFAULT_STATS, status = 'building' }) {
  const statusLabel = {
    building: '正在构建',
    idle: '等待输入',
    done: '已就绪',
  }[status] || '等待输入'

  const statusColor =
    status === 'building'
      ? 'text-emerald-700'
      : status === 'done'
        ? 'text-primary-700'
        : 'text-ink-500'
  const statusDot =
    status === 'building'
      ? 'bg-emerald-600 animate-pulse'
      : status === 'done'
        ? 'bg-primary-600'
        : 'bg-ink-400'

  return (
    <section className="rounded-xl border border-ink-200 bg-white p-5 transition-shadow duration-200 hover:shadow-soft">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] font-semibold tracking-[0.14em] text-ink-500 uppercase">
          Live · CCTree
        </span>
        <span className={`inline-flex items-center gap-1 text-[11px] ${statusColor}`}>
          <span className={`w-1 h-1 rounded-full ${statusDot}`} />
          {statusLabel}
        </span>
      </div>

      <div className="h-36 flex items-center justify-center">
        <TreeSvg />
      </div>

      <div className="mt-2 pt-3 border-t border-ink-100 grid grid-cols-3 gap-2 text-[11px] text-ink-500">
        <StatItem value={stats.nodes} label="节点" />
        <StatItem value={stats.depth} label="层级" />
        <StatItem value={`${stats.progress}%`} label="已分析" accent />
      </div>
    </section>
  )
}

function StatItem({ value, label, accent = false }) {
  return (
    <div>
      <div className={`text-sm font-semibold tabular-nums ${accent ? 'text-primary-600' : 'text-ink-900'}`}>
        {value}
      </div>
      <div>{label}</div>
    </div>
  )
}

function TreeSvg() {
  return (
    <svg viewBox="0 0 260 140" className="w-full h-full" aria-label="CCTree 结构" role="img">
      <g stroke="#cbd5e1" strokeWidth="1.1" fill="none" strokeLinecap="round">
        <path d="M130 22 Q130 32 60 50 Q60 60 30 76" />
        <path d="M130 22 Q130 32 60 50 Q60 60 90 76" />
        <path d="M130 22 Q130 32 130 52" />
        <path d="M130 22 Q130 32 200 50 Q200 60 170 76" />
        <path d="M130 22 Q130 32 200 50 Q200 60 230 76" />
        <path d="M30 76 Q30 90 20 108" />
        <path d="M30 76 Q30 90 42 108" />
        <path d="M90 76 Q90 90 84 108" />
        <path d="M130 52 Q130 80 120 108" />
        <path d="M130 52 Q130 80 140 108" />
        <path d="M170 76 Q170 90 168 108" />
        <path d="M230 76 Q230 90 222 108" />
      </g>

      <circle cx="130" cy="22" r="6" fill="#2563eb" />
      <circle
        cx="130" cy="22" r="12" fill="none"
        stroke="#2563eb" strokeWidth="1.5" opacity=".4"
        className="animate-pulse-slow" style={{ transformOrigin: '130px 22px' }}
      />

      <circle cx="60" cy="50" r="4" fill="#2563eb" opacity=".85" />
      <circle cx="130" cy="52" r="4" fill="#2563eb" opacity=".85" />
      <circle cx="200" cy="50" r="4" fill="#2563eb" opacity=".85" />

      <circle cx="30" cy="76" r="3" fill="#64748b" />
      <circle cx="90" cy="76" r="3" fill="#64748b" />
      <circle cx="170" cy="76" r="3" fill="#64748b" />
      <circle cx="230" cy="76" r="3" fill="#64748b" />

      {[16, 38, 80, 116, 136, 164, 218].map((x) => (
        <rect key={x} x={x} y="104" width="8" height="8" rx="1.5" fill="#94a3b8" />
      ))}

      <text x="138" y="18" fontFamily="Caveat, cursive" fontSize="12" fill="#64748b">root</text>
    </svg>
  )
}
