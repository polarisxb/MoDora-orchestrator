import { NavLink } from 'react-router-dom'
import { Search, Bell, Layers } from 'lucide-react'
import { BRAND } from '@/lib/brand'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/workspace', label: '工作台' },
  { to: '/library', label: '模板库' },
  { to: '/dashboard', label: '历史' },
  { to: '/doc-edit', label: '文档' },
]

export function TopNav() {
  return (
    <header className="sticky top-0 z-30 border-b border-ink-200/70 bg-white/75 backdrop-blur">
      <div className="max-w-[1440px] mx-auto h-14 px-6 flex items-center justify-between">
        {/* Left: Logo + Nav */}
        <div className="flex items-center gap-6">
          <NavLink to="/workspace" className="flex items-center gap-2.5 group">
            <div className="w-8 h-8 rounded-lg bg-primary-600 text-white flex items-center justify-center transition-transform group-hover:-rotate-3">
              <Layers className="w-[18px] h-[18px]" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-semibold text-[15px] text-ink-900 tracking-tight">
                {BRAND.name}
              </span>
              <span className="text-xs text-ink-500 hidden sm:inline">
                {BRAND.tagline}
              </span>
            </div>
          </NavLink>

          <nav className="hidden md:flex items-center gap-0.5 text-sm border-l border-ink-200 pl-5 ml-2">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'px-3 py-1.5 rounded-md transition-colors',
                    isActive
                      ? 'text-ink-900 font-medium bg-ink-100/80'
                      : 'text-ink-600 hover:text-ink-900 hover:bg-ink-100',
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>

        {/* Right: Status + Actions */}
        <div className="flex items-center gap-2.5">
          <div className="hidden sm:flex items-center gap-2 px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-[11px] text-emerald-700 font-medium">
            <span className="relative flex w-1.5 h-1.5">
              <span className="absolute inset-0 rounded-full bg-emerald-500 opacity-75 animate-ping" />
              <span className="relative inline-flex rounded-full w-1.5 h-1.5 bg-emerald-600" />
            </span>
            AI 已连接
          </div>
          <span className="hidden lg:inline text-[11px] text-ink-400 font-mono">
            qwen-plus · 128k
          </span>
          <button
            aria-label="搜索"
            className="w-9 h-9 rounded-md hover:bg-ink-100 text-ink-600 flex items-center justify-center transition-colors"
          >
            <Search className="w-[18px] h-[18px]" />
          </button>
          <button
            aria-label="通知"
            className="w-9 h-9 rounded-md hover:bg-ink-100 text-ink-600 relative flex items-center justify-center transition-colors"
          >
            <Bell className="w-[18px] h-[18px]" />
            <span className="absolute top-1.5 right-2 w-2 h-2 rounded-full bg-primary-600 ring-2 ring-white/75" />
          </button>
          <div className="w-px h-5 bg-ink-200 mx-1" />
          <button className="w-8 h-8 rounded-full bg-gradient-to-br from-primary-600 to-primary-700 text-white text-sm font-medium flex items-center justify-center">
            {BRAND.shortName}
          </button>
        </div>
      </div>
    </header>
  )
}
