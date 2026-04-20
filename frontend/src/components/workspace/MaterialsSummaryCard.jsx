import { FileSpreadsheet, FileText, FileType2, CheckCircle2 } from 'lucide-react'
import { InfoPanelCard } from '@/components/page/SectionLabel'

const CHANNEL_META = {
  excel: { name: 'Excel', icon: FileSpreadsheet, color: 'text-emerald-600' },
  md_txt: { name: 'MD/TXT', icon: FileText, color: 'text-primary-600' },
  word: { name: 'Word', icon: FileType2, color: 'text-amber-600' },
}

/**
 * 素材库摘要卡 —— TableFill 右栏组件
 * 显示按通道分类的素材数量 + 成功率
 */
export function MaterialsSummaryCard({ materials }) {
  if (!materials) return null
  const byChannel = {}
  materials.docs?.forEach((d) => {
    if (!byChannel[d.channel]) byChannel[d.channel] = { total: 0, ok: 0 }
    byChannel[d.channel].total += 1
    if (d.status === 'ok') byChannel[d.channel].ok += 1
  })

  const channels = Object.keys(CHANNEL_META)
  const successRate = materials.count
    ? Math.round((materials.succeeded / materials.count) * 100)
    : 0

  return (
    <InfoPanelCard label="素材库" labelMeta={`${materials.count} 份`}>
      {materials.count === 0 ? (
        <p className="text-xs text-ink-500 py-2">
          还没有素材，在左侧上传第一份吧。
        </p>
      ) : (
        <>
          <ul className="space-y-2">
            {channels.map((key) => {
              const meta = CHANNEL_META[key]
              const stat = byChannel[key] || { total: 0, ok: 0 }
              const Icon = meta.icon
              return (
                <li key={key} className="flex items-center gap-2.5">
                  <Icon className={`w-4 h-4 ${meta.color}`} />
                  <span className="text-xs text-ink-700 flex-1">
                    {meta.name}
                  </span>
                  <span className="text-xs text-ink-500 font-mono tabular-nums">
                    {stat.ok}/{stat.total || '0'}
                  </span>
                </li>
              )
            })}
          </ul>
          <div className="mt-3 pt-3 border-t border-ink-100 flex items-center justify-between">
            <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
              <CheckCircle2 className="w-3 h-3" />
              成功率
            </span>
            <span className="text-sm font-semibold text-ink-900 tabular-nums">
              {successRate}%
            </span>
          </div>
        </>
      )}
    </InfoPanelCard>
  )
}
