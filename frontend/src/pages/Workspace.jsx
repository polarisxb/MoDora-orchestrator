import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { GreetingCard } from '@/components/workspace/GreetingCard'
import { RecentRunsCard } from '@/components/workspace/RecentRunsCard'
import { LiveTreeCard } from '@/components/workspace/LiveTreeCard'
import { WorkspaceHero } from '@/components/workspace/WorkspaceHero'
import { UploadGrid } from '@/components/workspace/UploadGrid'
import { ProcessFlow } from '@/components/workspace/ProcessFlow'
import { getHealth, getHistory, listMaterials } from '@/lib/api'

export function Workspace() {
  const navigate = useNavigate()
  const [health, setHealth] = useState(null)
  const [history, setHistory] = useState([])
  const [materials, setMaterials] = useState(null)

  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      getHealth(),
      getHistory(10),
      listMaterials(),
    ])
    if (results[0].status === 'fulfilled') setHealth(results[0].value)
    if (results[1].status === 'fulfilled') setHistory(results[1].value.history || [])
    if (results[2].status === 'fulfilled') setMaterials(results[2].value)
  }, [])

  useEffect(() => { refresh() }, [refresh])

  // --- derive sidebar data from real API responses ---

  // GreetingCard stats
  const todayOps = history.filter((op) => {
    const today = new Date().toISOString().slice(0, 10)
    return op.timestamp?.startsWith(today)
  })
  const processOps = todayOps.filter((op) => op.type === 'process')
  const greetingStats = {
    generated: processOps.length,
    avgDuration: processOps.length ? '—' : '0 s',
    accuracy: materials?.count ? `${Math.round((materials.succeeded / materials.count) * 100)}%` : '—',
  }

  // RecentRuns — map history ops to the card format
  const recentRuns = history.slice(0, 5).map((op) => ({
    title: op.detail || op.type,
    status: op.status === 'ok' ? 'completed' : 'queued',
    meta: `${op.type} · ${op.timestamp?.slice(11, 19) || ''}`,
  }))

  // LiveTree — derive from health + materials
  const treeStatus = materials?.count > 0
    ? (materials.succeeded === materials.count ? 'done' : 'building')
    : 'idle'
  const treeStats = {
    nodes: materials?.count || 0,
    depth: materials?.count > 0 ? Math.min(materials.count + 1, 6) : 0,
    progress: materials?.count ? Math.round((materials.succeeded / materials.count) * 100) : 0,
  }

  return (
    <div className="flex-1 max-w-[1440px] w-full mx-auto px-6 py-8 grid lg:grid-cols-[296px_1fr] gap-6">
      {/* ===== Sidebar ===== */}
      <aside className="space-y-4 stagger-in">
        <GreetingCard stats={greetingStats} />
        <RecentRunsCard
          runs={recentRuns}
          onViewAll={() => navigate('/dashboard')}
        />
        <LiveTreeCard stats={treeStats} status={treeStatus} />
      </aside>

      {/* ===== Main ===== */}
      <main className="space-y-6 min-w-0 stagger-in">
        <WorkspaceHero />
        <UploadGrid />
        <ProcessFlow />
      </main>
    </div>
  )
}
