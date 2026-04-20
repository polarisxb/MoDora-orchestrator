import { NavLink } from 'react-router-dom'
import {
  MessageSquare,
  LayoutDashboard,
  LayoutGrid,
  FileEdit,
  FileSearch,
  Table2,
  FolderOpen,
  Sparkles,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { BRAND } from '@/lib/brand'

const PRIMARY = [
  { to: '/workspace', label: '工作台', icon: LayoutGrid },
  { to: '/', label: '智能对话', icon: MessageSquare, end: true },
]

const EXPERT = [
  { to: '/doc-edit', label: '文档编辑', icon: FileEdit, badge: '①' },
  { to: '/extract', label: '信息提取', icon: FileSearch, badge: '②' },
  { to: '/table-fill', label: '表格填写', icon: Table2, badge: '③' },
  { to: '/library', label: '素材库', icon: FolderOpen },
]

const META = [
  { to: '/dashboard', label: '运行状态', icon: LayoutDashboard },
]

export function Sidebar() {
  return (
    <aside className="w-60 shrink-0 bg-white border-r border-ink-200 flex flex-col">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-ink-100">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center text-white shadow-sm">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <div className="font-semibold text-ink-900 text-sm tracking-tight">{BRAND.name}</div>
            <div className="text-[11px] text-ink-500">{BRAND.tagline}</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 scroll-thin overflow-y-auto">
        {/* Primary */}
        <div className="space-y-1 mb-5">
          {PRIMARY.map((item) => (
            <NavItem key={item.to} item={item} />
          ))}
        </div>

        {/* Expert mode */}
        <SectionHeader>专家模式</SectionHeader>
        <div className="space-y-1 mb-5">
          {EXPERT.map((item) => (
            <NavItem key={item.to} item={item} />
          ))}
        </div>

        {/* Meta */}
        <SectionHeader>系统</SectionHeader>
        <div className="space-y-1">
          {META.map((item) => (
            <NavItem key={item.to} item={item} />
          ))}
        </div>
      </nav>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-ink-100 text-[11px] text-ink-400">
        {BRAND.version} · {BRAND.name}
      </div>
    </aside>
  )
}

function SectionHeader({ children }) {
  return (
    <div className="px-3 mb-1.5 text-[10px] font-semibold text-ink-400 uppercase tracking-wider">
      {children}
    </div>
  )
}

function NavItem({ item }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors duration-150',
          isActive
            ? 'bg-primary-50 text-primary-700 font-medium'
            : 'text-ink-600 hover:bg-ink-50 hover:text-ink-900',
        )
      }
    >
      <Icon className="w-4 h-4" />
      <span className="flex-1">{item.label}</span>
      {item.badge && (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-ink-100 text-ink-500 font-mono">
          {item.badge}
        </span>
      )}
    </NavLink>
  )
}
