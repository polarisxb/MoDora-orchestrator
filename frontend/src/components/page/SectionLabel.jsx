/**
 * SECTION LABEL · 右侧 Info Panel 里的小标题
 * 字号固定 [11px]、字重 semibold、字距 [0.14em]、uppercase
 *
 * 用法:
 *   <SectionLabel meta="30 min ago">TODAY · 今日生成</SectionLabel>
 */
export function SectionLabel({ children, meta }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <span className="text-[11px] font-semibold tracking-[0.14em] text-ink-500 uppercase">
        {children}
      </span>
      {meta && (
        <span className="text-[11px] text-ink-400 font-mono">{meta}</span>
      )}
    </div>
  )
}

/**
 * Info Panel Card · 右侧信息栏的通用容器
 * 区别于主内容 Card: 更薄 padding、border 默认显示、section label 在顶
 */
export function InfoPanelCard({ label, labelMeta, children, className, action }) {
  return (
    <section
      className={`rounded-xl border border-ink-200 bg-white px-5 py-4 ${className || ''}`}
    >
      {label && (
        <div className="flex items-center justify-between mb-3">
          <span className="text-[11px] font-semibold tracking-[0.14em] text-ink-500 uppercase">
            {label}
          </span>
          {action
            ? action
            : labelMeta && (
                <span className="text-[11px] text-ink-400 font-mono">{labelMeta}</span>
              )}
        </div>
      )}
      {children}
    </section>
  )
}
