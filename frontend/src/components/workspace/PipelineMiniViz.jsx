import { InfoPanelCard } from '@/components/page/SectionLabel'

/**
 * 迷你处理流水可视化 —— 4 阶段 + 进度状态
 * 用于 TableFill / Extract 等页面的右栏
 *
 * 用法:
 *   <PipelineMiniViz currentStage="retrieve" />
 *   <PipelineMiniViz stages={{ingest: 'done', build: 'active', retrieve: 'pending', fill: 'pending'}} />
 */
const DEFAULT_STAGES = [
  { key: 'ingest', label: 'Ingest', caption: 'OCR · 抽取' },
  { key: 'build', label: 'Build', caption: 'CCTree 构建' },
  { key: 'retrieve', label: 'Retrieve', caption: '多通道检索' },
  { key: 'fill', label: 'Fill', caption: '模板回填' },
]

/**
 * @param currentStage  - 当前激活的 key (之前的变 done, 之后的变 pending)
 * @param stages        - 可选: 显式 state map { ingest:'done'|'active'|'pending' }
 */
export function PipelineMiniViz({ currentStage, stages: explicitStages }) {
  const stages = explicitStages
    ? DEFAULT_STAGES.map((s) => ({ ...s, state: explicitStages[s.key] || 'pending' }))
    : computeStates(currentStage)

  return (
    <InfoPanelCard label="Pipeline" labelMeta="≈ 65 s">
      <ol className="space-y-0">
        {stages.map((stage, i) => (
          <li key={stage.key} className="flex gap-3">
            {/* 竖向连接线 */}
            <div className="flex flex-col items-center" style={{ minWidth: 10 }}>
              <div className={dotClasses(stage.state)} />
              {i < stages.length - 1 && (
                <div
                  className={
                    stage.state === 'done'
                      ? 'w-px flex-1 bg-primary-300'
                      : 'w-px flex-1 bg-ink-200'
                  }
                />
              )}
            </div>
            <div className={i < stages.length - 1 ? 'flex-1 pb-3' : 'flex-1'}>
              <div className="text-xs font-medium text-ink-900 leading-none">
                {stage.label}
              </div>
              <div className="text-[11px] text-ink-500 mt-1">{stage.caption}</div>
            </div>
          </li>
        ))}
      </ol>
    </InfoPanelCard>
  )
}

function computeStates(currentKey) {
  if (!currentKey) {
    // 无激活 → 全部 pending
    return DEFAULT_STAGES.map((s) => ({ ...s, state: 'pending' }))
  }
  let seen = false
  return DEFAULT_STAGES.map((s) => {
    if (s.key === currentKey) {
      seen = true
      return { ...s, state: 'active' }
    }
    return { ...s, state: seen ? 'pending' : 'done' }
  })
}

function dotClasses(state) {
  if (state === 'done') {
    return 'w-2.5 h-2.5 rounded-full bg-primary-600 mt-0.5'
  }
  if (state === 'active') {
    return 'w-2.5 h-2.5 rounded-full border-2 border-primary-600 bg-white animate-pulse mt-0.5'
  }
  return 'w-2.5 h-2.5 rounded-full border border-ink-300 bg-white mt-0.5'
}
