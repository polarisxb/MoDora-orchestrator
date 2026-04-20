import { useEffect, useRef, useState } from 'react'
import {
  Sparkles,
  Trash2,
  FileEdit,
  FileSearch,
  Table2,
  ArrowRight,
  Zap,
  Shield,
  Layers,
} from 'lucide-react'
import { BRAND } from '@/lib/brand'
import { PageBreadcrumb, LiveStatus } from '@/components/page/PageShell'
import { MessageBubble } from '@/components/chat/MessageBubble'
import { ChatInput } from '@/components/chat/ChatInput'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { useToast } from '@/components/ui/Toast'
import { chatAgent } from '@/lib/api'

const SUGGESTIONS = [
  {
    icon: FileEdit,
    label: '帮我把这份 Word 文档的标题加粗',
    intent: 'doc_edit',
  },
  {
    icon: FileSearch,
    label: '提取这份合同里的关键实体和摘要',
    intent: 'extract',
  },
  {
    icon: Table2,
    label: '我要用素材填一个空白表格',
    intent: 'fill_table',
  },
  {
    icon: Sparkles,
    label: '介绍一下你能做什么',
    intent: 'chat',
  },
]

export function Chat() {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef(null)
  const toast = useToast()

  // Auto scroll to bottom on new message
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, loading])

  const send = async ({ message, files }) => {
    // Append user message
    const userMsg = {
      role: 'user',
      content: message,
      attachments: files.map((f) => ({ name: f.name, size: f.size })),
    }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setLoading(true)

    // Append placeholder assistant message
    const placeholder = { role: 'assistant', content: '', isLoading: true }
    setMessages((cur) => [...cur, placeholder])

    try {
      // Build history excluding placeholder & attachments metadata for backend
      const history = newMessages.map((m) => ({
        role: m.role,
        content: m.content,
      }))
      const reply = await chatAgent({
        message,
        history: history.slice(0, -1), // exclude the user message we just added (sent as `message` field)
        files,
      })
      // Replace placeholder with real reply
      setMessages((cur) => {
        const copy = [...cur]
        copy[copy.length - 1] = reply
        return copy
      })
    } catch (e) {
      setMessages((cur) => {
        const copy = [...cur]
        copy[copy.length - 1] = {
          role: 'assistant',
          content: `请求失败: ${e.message}`,
          intent: 'chat',
        }
        return copy
      })
      toast.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  const clear = () => {
    if (messages.length === 0) return
    if (window.confirm('清空当前对话？')) {
      setMessages([])
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] max-w-4xl mx-auto -m-2">
      {/* 顶部面包屑 + live status + 操作 */}
      <div className="flex items-center justify-between mb-4 px-2">
        <PageBreadcrumb items={['工作台', '智能对话']} />
        <div className="flex items-center gap-3">
          <LiveStatus meta={`qwen-plus · ${messages.length} msg`} />
          {messages.length > 0 && (
            <Button variant="ghost" size="sm" onClick={clear}>
              <Trash2 className="w-4 h-4" />
              清空
            </Button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto scroll-thin px-2 py-4 space-y-4"
      >
        {messages.length === 0 ? (
          <Welcome onPick={(text) => send({ message: text, files: [] })} />
        ) : (
          messages.map((m, i) => <MessageBubble key={i} message={m} />)
        )}
      </div>

      {/* Input */}
      <div className="px-2 pt-3">
        <ChatInput onSend={send} loading={loading} />
        <p className="text-[11px] text-ink-400 mt-2 px-1 text-center">
          提示：可以拖拽文件到输入框 · 内容由 LLM 生成，请核对结果
        </p>
      </div>
    </div>
  )
}

function Welcome({ onPick }) {
  return (
    <div className="flex flex-col items-center justify-center h-full px-2">
      {/* 顶部 badges */}
      <div className="flex flex-wrap items-center justify-center gap-2 mb-6">
        <Badge variant="primary" className="gap-1.5">
          <Zap className="w-3 h-3" />
          Qwen-Plus · 128k
        </Badge>
        <Badge variant="default">工作台 智能入口</Badge>
      </div>

      {/* 主标题 */}
      <h2 className="text-2xl font-semibold text-ink-900 tracking-tight mb-3 text-center">
        什么都能{' '}
        <span className="text-primary-600">上传给我</span>
      </h2>
      <p className="text-sm text-ink-500 mb-8 max-w-lg leading-relaxed text-center">
        编辑 Word 文档、提取关键信息、回答问题 —— 附上文件 + 描述需求，
        {BRAND.name} 会自动选择最合适的处理通道。
      </p>

      {/* 建议输入 */}
      <div className="w-full max-w-2xl mb-6">
        <div className="text-[11px] font-semibold tracking-[0.14em] text-ink-500 uppercase mb-3 px-1">
          尝试以下请求
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 stagger-in">
          {SUGGESTIONS.map((s, i) => {
            const Icon = s.icon
            return (
              <button
                key={i}
                onClick={() => onPick(s.label)}
                className="group flex items-center gap-3 px-3.5 py-3 rounded-lg border border-ink-200 bg-white hover:border-primary-300 hover:bg-ink-50 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-soft text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-1"
              >
                <div className="w-8 h-8 rounded-md bg-ink-100 text-ink-600 group-hover:bg-primary-50 group-hover:text-primary-600 flex items-center justify-center shrink-0 transition-colors">
                  <Icon className="w-4 h-4" />
                </div>
                <span className="flex-1 text-xs text-ink-700 leading-relaxed">
                  {s.label}
                </span>
                <ArrowRight className="w-3 h-3 text-ink-300 group-hover:text-primary-500 transition-colors" />
              </button>
            )
          })}
        </div>
      </div>

      {/* 底部能力条 */}
      <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs text-ink-500 max-w-2xl">
        <span className="inline-flex items-center gap-1.5">
          <Zap className="w-3 h-3 text-primary-500" />
          自动路由 3 个通道
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Layers className="w-3 h-3 text-primary-500" />
          多文件并行处理
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Shield className="w-3 h-3 text-primary-500" />
          过程可追溯
        </span>
      </div>
    </div>
  )
}
