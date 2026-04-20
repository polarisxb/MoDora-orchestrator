import { useNavigate } from 'react-router-dom'
import { FileSpreadsheet, FileText, FileType, LayoutTemplate } from 'lucide-react'
import { cn } from '@/lib/utils'

const CARDS = [
  {
    key: 'excel',
    channel: 'excel',
    title: '上传 Excel',
    description: '含指标、多维参数的结构化数据表,自动识别表头层级与单位。',
    formats: ['.xlsx', '.xls'],
    icon: FileSpreadsheet,
    iconStyle: 'bg-emerald-50 border border-emerald-200 text-emerald-700',
  },
  {
    key: 'md_txt',
    channel: 'md_txt',
    title: 'MD / TXT',
    description: '报告、纪要、技术说明稿,自动解析段落结构与数据要点。',
    formats: ['.md', '.txt'],
    icon: FileText,
    iconStyle: 'bg-primary-50 border border-primary-200 text-primary-700',
  },
  {
    key: 'word',
    channel: 'word',
    title: '上传 Word',
    description: '带格式的设计稿或收集表,保留标题层级,自动抽字段。',
    formats: ['.docx'],
    icon: FileType,
    iconStyle: 'bg-amber-50 border border-amber-200 text-amber-700',
  },
  {
    key: 'template',
    channel: 'template',
    title: '选择模板',
    description: '已有的 .xlsx / .docx 模板直接复用,跳过结构识别。',
    formats: ['复用'],
    icon: LayoutTemplate,
    iconStyle: 'bg-ink-100 border border-ink-200 text-ink-700',
  },
]

export function UploadGrid() {
  const navigate = useNavigate()

  return (
    <section>
      <div className="flex items-end justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-ink-900">从素材开始</h2>
          <p className="text-xs text-ink-500 mt-0.5">
            选择一种或多种格式,MoDora 会并行识别每一份文件的结构
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 stagger-in">
        {CARDS.map((card) => (
          <UploadCard
            key={card.key}
            card={card}
            onClick={() =>
              navigate('/table-fill', {
                state: { focusChannel: card.channel },
              })
            }
          />
        ))}
      </div>
    </section>
  )
}

function UploadCard({ card, onClick }) {
  const Icon = card.icon
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'group relative rounded-xl border border-ink-200 bg-white p-5 text-left',
        'transition-all duration-200 hover:border-primary-300 hover:shadow-soft-md hover:-translate-y-0.5',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-1',
      )}
    >
      <div className={cn('w-10 h-10 rounded-lg flex items-center justify-center mb-3', card.iconStyle)}>
        <Icon className="w-5 h-5" strokeWidth={1.8} />
      </div>

      <h3 className="text-sm font-semibold text-ink-900">{card.title}</h3>
      <p className="mt-1 text-xs text-ink-500 leading-relaxed">{card.description}</p>

      <div className="mt-3 flex flex-wrap gap-1">
        {card.formats.map((fmt) => (
          <span key={fmt} className="text-[10px] px-1.5 py-0.5 rounded bg-ink-100 text-ink-600 font-mono">
            {fmt}
          </span>
        ))}
      </div>
    </button>
  )
}
