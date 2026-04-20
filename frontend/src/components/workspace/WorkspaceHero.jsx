import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BookOpen, ArrowRight, Check, Zap } from 'lucide-react'

const HINTS = [
  '支持 .xlsx / .docx / .md / .txt',
  '单模板 90 s 内完成',
  '已服务 280+ 企业',
]

export function WorkspaceHero() {
  const navigate = useNavigate()
  const [requirement, setRequirement] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    navigate('/table-fill', {
      state: { requirement: requirement.trim() },
    })
  }

  return (
    <section className="relative overflow-hidden rounded-2xl border border-ink-200 bg-white">
      <div className="relative z-10 p-8 lg:p-10">
        {/* 顶部徽章 */}
        <div className="flex flex-wrap items-center gap-2 mb-7">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary-50 border border-primary-100 text-[11px] text-primary-700 font-medium">
            <Zap className="w-2.5 h-2.5" fill="currentColor" />
            Qwen-Plus · 128k
          </span>
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-ink-100 text-[11px] text-ink-600 font-medium">
            批处理 · 多通道检索 · 自动仲裁
          </span>
          <span className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white border border-ink-200 text-[11px] text-ink-500 font-mono">
            65 s · avg
          </span>
        </div>

        {/* 标题 — 原型 font-serif + sketch-underline */}
        <h1 className="font-serif text-[28px] lg:text-[38px] font-semibold text-ink-900 leading-[1.3] tracking-tight max-w-[680px]">
          让 AI 自动读取 <span className="sketch-underline">素材</span>、理解
          <span className="sketch-underline">结构</span>,
          <br />
          一键生成可交付的 <span className="text-primary-600">企业模板</span>。
        </h1>
        <p className="mt-5 text-sm lg:text-[15px] text-ink-600 leading-relaxed max-w-[560px]">
          从 Excel、Word、Markdown 到业务结构 —— 统一在一个工作台里完成识别、对齐与填充。
        </p>

        {/* 输入 + CTA */}
        <form onSubmit={handleSubmit} className="mt-8 flex flex-col sm:flex-row gap-3 max-w-2xl">
          <div className="flex-1 relative">
            <BookOpen className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-400 pointer-events-none" />
            <input
              type="text"
              value={requirement}
              onChange={(e) => setRequirement(e.target.value)}
              placeholder="描述你的需求,例如:按省份汇总 2024 Q1 各项污染物排放指标…"
              className="w-full h-11 pl-10 pr-4 rounded-md border border-ink-300 bg-white text-sm placeholder:text-ink-400 focus:outline-none focus:border-primary-600 focus:ring-2 focus:ring-primary-500/20 transition-all"
            />
          </div>
          <button
            type="submit"
            className="h-11 px-6 rounded-md bg-primary-600 hover:bg-primary-700 text-white text-sm font-medium transition-all duration-200 flex items-center justify-center gap-2 shadow-soft hover:shadow-soft-md active:scale-[0.98]"
          >
            开始批量
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </form>

        {/* 能力提示 */}
        <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-ink-500">
          {HINTS.map((hint) => (
            <span key={hint} className="inline-flex items-center gap-1.5">
              <Check className="w-3 h-3 text-emerald-600" strokeWidth={2.5} />
              {hint}
            </span>
          ))}
        </div>
      </div>

      {/* 右侧线稿插画 — 1:1 原型 SVG */}
      <div className="absolute top-0 right-0 w-[380px] h-full opacity-90 hidden xl:block pointer-events-none">
        <svg viewBox="0 0 380 400" className="w-full h-full">
          {/* 左侧输入流 */}
          <g stroke="#cbd5e1" strokeWidth="1.2" fill="none" strokeLinecap="round" opacity=".6">
            <path d="M50 100 C 120 100, 150 180, 220 180" />
            <path d="M50 180 C 120 180, 150 200, 220 200" />
            <path d="M50 260 C 120 260, 150 220, 220 220" />
          </g>
          {/* 中心 CCTree */}
          <g stroke="#94a3b8" strokeWidth="1.5" fill="none" strokeLinecap="round" opacity=".7">
            <path d="M260 200 L240 140 M260 200 L300 130" />
            <path d="M260 200 L220 240 M260 200 L260 280 M260 200 L300 270" />
            <path d="M240 140 L230 100" />
            <path d="M300 130 L310 90 M300 130 L340 110" />
            <path d="M220 240 L200 280 M220 240 L210 300" />
            <path d="M260 280 L250 320 M260 280 L280 330" />
          </g>
          <circle cx="260" cy="200" r="7" fill="#2563eb" />
          <circle
            cx="260" cy="200" r="14" fill="none"
            stroke="#2563eb" strokeWidth="1.5" opacity=".4"
            className="animate-pulse-slow" style={{ transformOrigin: '260px 200px' }}
          />
          <circle cx="240" cy="140" r="5" fill="#2563eb" opacity=".8" />
          <circle cx="300" cy="130" r="5" fill="#2563eb" opacity=".8" />
          <circle cx="220" cy="240" r="5" fill="#2563eb" opacity=".8" />
          <circle cx="260" cy="280" r="5" fill="#2563eb" opacity=".8" />
          <circle cx="300" cy="270" r="5" fill="#2563eb" opacity=".8" />
          {/* 叶节点 */}
          {[[225,95],[305,85],[335,105],[195,275],[205,295],[245,315],[275,325]].map(([x,y]) => (
            <rect key={`${x}-${y}`} x={x} y={y} width="10" height="10" rx="2" fill="#64748b" opacity=".7" />
          ))}
          {/* 右侧输出流 */}
          <g stroke="#cbd5e1" strokeWidth="1.2" fill="none" strokeLinecap="round" opacity=".6">
            <path d="M320 190 C 360 190, 360 160, 380 160" />
            <path d="M320 200 C 360 200, 360 200, 380 200" />
            <path d="M320 210 C 360 210, 360 240, 380 240" />
          </g>
          {/* 标签 */}
          <text x="30" y="92" fontFamily="Caveat, cursive" fontSize="14" fill="#64748b">raw excel</text>
          <text x="30" y="172" fontFamily="Caveat, cursive" fontSize="14" fill="#64748b">raw word</text>
          <text x="30" y="252" fontFamily="Caveat, cursive" fontSize="14" fill="#64748b">markdown</text>
          <text x="238" y="372" fontFamily="Caveat, cursive" fontSize="16" fill="#2563eb" fontWeight="600">CCTree</text>
        </svg>
      </div>
    </section>
  )
}
