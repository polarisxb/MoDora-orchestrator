import { Fragment } from 'react'

/**
 * 页面外壳：breadcrumb + live status + 内容
 * 让每个业务页都自动拥有"Workspace 级"的视觉 DNA
 *
 * 用法：
 *   <PageShell
 *     breadcrumb={['工作台', '表格智能填写']}
 *     status={<LiveStatus meta="qwen-plus · 128k" />}
 *   >
 *     ...
 *   </PageShell>
 */
export function PageShell({ breadcrumb, status, children, maxWidth = '1400px' }) {
  const hasBar = breadcrumb || status
  return (
    <div className="mx-auto px-6 py-8" style={{ maxWidth }}>
      {hasBar && (
        <div className="flex items-center justify-between gap-4 mb-8">
          {breadcrumb ? <PageBreadcrumb items={breadcrumb} /> : <span />}
          {status}
        </div>
      )}
      {children}
    </div>
  )
}

/** 面包屑 —— 最后一段用 ink-700 加粗，之前用 ink-400 */
export function PageBreadcrumb({ items }) {
  return (
    <nav className="flex items-center gap-2 text-xs" aria-label="面包屑">
      {items.map((item, i) => {
        const isLast = i === items.length - 1
        return (
          <Fragment key={i}>
            {i > 0 && <span className="text-ink-300">/</span>}
            <span className={isLast ? 'text-ink-700 font-medium' : 'text-ink-400'}>
              {item}
            </span>
          </Fragment>
        )
      })}
    </nav>
  )
}

/** 实时状态指示 —— 绿色脉冲点 + 标签 + 可选模型/版本 meta */
export function LiveStatus({ label = 'AI 已连接', meta, color = 'emerald' }) {
  const dotColors = {
    emerald: { ring: 'bg-emerald-400', core: 'bg-emerald-500' },
    primary: { ring: 'bg-primary-400', core: 'bg-primary-500' },
    amber: { ring: 'bg-amber-400', core: 'bg-amber-500' },
  }
  const c = dotColors[color] || dotColors.emerald
  return (
    <div className="flex items-center gap-4">
      <span className="inline-flex items-center gap-1.5 text-xs text-ink-500">
        <span className="relative flex w-1.5 h-1.5">
          <span
            className={`absolute inline-flex w-full h-full rounded-full opacity-60 animate-ping ${c.ring}`}
          />
          <span className={`relative inline-flex w-1.5 h-1.5 rounded-full ${c.core}`} />
        </span>
        {label}
      </span>
      {meta && (
        <span className="text-[11px] text-ink-400 font-mono">{meta}</span>
      )}
    </div>
  )
}
