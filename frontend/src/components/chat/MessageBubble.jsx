import { Sparkles, User, Download, Tag, FileText, ArrowRight, Paperclip } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { cn, formatBytes } from '@/lib/utils'
import { chatResultUrl } from '@/lib/api'
import { Badge } from '@/components/ui/Badge'

const INTENT_LABEL = {
  doc_edit: { text: '文档编辑', variant: 'primary' },
  extract: { text: '信息提取', variant: 'success' },
  fill_table: { text: '表格填写', variant: 'warning' },
  chat: { text: '对话', variant: 'default' },
}

export function MessageBubble({ message }) {
  const isUser = message.role === 'user'
  return (
    <div
      className={cn(
        'flex gap-3 animate-fade-in',
        isUser ? 'flex-row-reverse' : 'flex-row',
      )}
    >
      {/* Avatar — flat square with rounded corners (ref: inspirations.md) */}
      <div
        className={cn(
          'w-8 h-8 rounded-lg flex items-center justify-center shrink-0',
          isUser
            ? 'bg-ink-100 text-ink-600'
            : 'bg-primary-50 text-primary-600',
        )}
      >
        {isUser ? <User className="w-4 h-4" /> : <Sparkles className="w-4 h-4" />}
      </div>

      {/* Bubble */}
      <div className={cn('max-w-[78%] flex flex-col', isUser ? 'items-end' : 'items-start')}>
        {/* Intent badge for assistant */}
        {!isUser && message.intent && message.intent !== 'chat' && (
          <Badge variant={INTENT_LABEL[message.intent]?.variant || 'default'} className="mb-1.5">
            {INTENT_LABEL[message.intent]?.text || message.intent}
          </Badge>
        )}

        {/* User attachments */}
        {isUser && message.attachments?.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5 justify-end">
            {message.attachments.map((a, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-ink-100 border border-ink-200 text-xs text-ink-700"
              >
                <Paperclip className="w-3 h-3" />
                {a.name}
              </span>
            ))}
          </div>
        )}

        {/* Text content */}
        <div
          className={cn(
            'px-4 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap break-words',
            isUser
              ? 'bg-primary-600 text-white rounded-br-md'
              : 'bg-white border border-ink-200 text-ink-800 rounded-bl-md',
          )}
        >
          {message.content || (message.isLoading ? <LoadingDots /> : '')}
        </div>

        {/* Result card */}
        {!isUser && message.result && <ResultCard result={message.result} />}
      </div>
    </div>
  )
}

function LoadingDots() {
  return (
    <span className="inline-flex gap-1 items-center text-ink-400">
      <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce" />
      <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce [animation-delay:0.2s]" />
      <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce [animation-delay:0.4s]" />
    </span>
  )
}

function ResultCard({ result }) {
  if (result.type === 'file_download') return <DownloadCard result={result} />
  if (result.type === 'extract_data') return <ExtractCard result={result} />
  if (result.type === 'redirect') return <RedirectCard result={result} />
  return null
}

function DownloadCard({ result }) {
  return (
    <a
      href={chatResultUrl(result.file_id)}
      download={result.filename}
      className="mt-2 inline-flex items-center gap-3 px-4 py-2.5 rounded-xl border border-primary-200 bg-primary-50 hover:bg-primary-100 transition-colors text-sm group"
    >
      <div className="w-9 h-9 rounded-lg bg-primary-600 text-white flex items-center justify-center shrink-0">
        <FileText className="w-4 h-4" />
      </div>
      <div>
        <div className="font-medium text-primary-700">{result.filename}</div>
        <div className="text-xs text-primary-700">{formatBytes(result.size)}</div>
      </div>
      <Download className="w-4 h-4 text-primary-600 ml-2 group-hover:translate-x-0.5 transition-transform" />
    </a>
  )
}

function RedirectCard({ result }) {
  const navigate = useNavigate()
  return (
    <button
      onClick={() => navigate(result.url)}
      className="mt-2 inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-primary-200 bg-primary-50 hover:bg-primary-100 transition-colors text-sm font-medium text-primary-700"
    >
      {result.label || '前往'}
      <ArrowRight className="w-4 h-4" />
    </button>
  )
}

function ExtractCard({ result }) {
  const data = result.data || {}
  const entities = data.entities || []
  const keyInfo = data.key_info || {}
  return (
    <div className="mt-2 w-full max-w-lg space-y-2">
      {/* Key info */}
      {Object.keys(keyInfo).length > 0 && (
        <div className="p-3 rounded-xl bg-white border border-ink-200">
          <div className="text-xs font-semibold text-ink-500 mb-2">关键信息</div>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
            {Object.entries(keyInfo).map(([k, v]) => (
              <div key={k}>
                <dt className="text-ink-500">{k}</dt>
                <dd className="text-ink-800 font-medium">{v ?? '—'}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {/* Entities */}
      {entities.length > 0 && (
        <div className="p-3 rounded-xl bg-white border border-ink-200">
          <div className="text-xs font-semibold text-ink-500 mb-2">
            提取实体 ({entities.length})
          </div>
          <div className="flex flex-wrap gap-1.5 max-h-40 overflow-y-auto scroll-thin">
            {entities.map((e, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-ink-100 text-xs text-ink-700"
                title={e.context}
              >
                <Tag className="w-3 h-3 text-primary-500" />
                <span className="font-medium">{e.value}</span>
                <span className="text-ink-400">· {e.type}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
