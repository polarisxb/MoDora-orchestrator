/**
 * 问候卡:显示 "你好!" 气泡 + 用户信息 + 今日统计
 */
export function GreetingCard({
  userName = '研究员 · 李煦宸',
  dateLabel,
  stats = { generated: 3, avgDuration: '72 秒', accuracy: '86%' },
}) {
  const date =
    dateLabel ??
    new Date().toLocaleDateString('en-US', { weekday: 'short' }) +
      ' · ' +
      new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

  return (
    <section className="rounded-xl border border-ink-200 bg-white p-5 transition-shadow duration-200 hover:shadow-soft">
      <div className="flex items-start justify-between">
        <div className="greeting-chip inline-flex items-center gap-1.5 px-3 py-1 border-[1.5px] border-ink-800 rounded-full bg-paper-50">
          <span className="w-1.5 h-1.5 rounded-full bg-ink-800" />
          <span className="brush-text text-[17px] leading-none text-ink-900 pt-0.5">
            你好!
          </span>
        </div>
        <span className="cursive-text text-[13px] text-ink-400">{date}</span>
      </div>

      <h3 className="mt-3.5 text-sm font-semibold text-ink-900">{userName}</h3>
      <p className="mt-1 text-xs text-ink-500 leading-relaxed">
        今天已生成{' '}
        <span className="text-ink-900 font-semibold">{stats.generated} 份</span>{' '}
        模板,平均耗时{' '}
        <span className="text-ink-900 font-semibold">{stats.avgDuration}</span>
        ,准确率{' '}
        <span className="text-emerald-700 font-semibold">{stats.accuracy}</span>
        。
      </p>
    </section>
  )
}
