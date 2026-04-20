import { useState, useRef } from 'react'
import { Send, Paperclip, X, FileText } from 'lucide-react'
import { cn, formatBytes } from '@/lib/utils'

/**
 * Chat input area with file attachments.
 *
 * Props:
 *   onSend: ({ message, files }) => void
 *   loading: boolean
 *   disabled: boolean
 */
export function ChatInput({ onSend, loading = false, disabled = false }) {
  const [text, setText] = useState('')
  const [files, setFiles] = useState([])
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef(null)
  const textareaRef = useRef(null)

  const send = () => {
    const trimmed = text.trim()
    if (!trimmed && files.length === 0) return
    if (loading || disabled) return
    onSend({ message: trimmed, files })
    setText('')
    setFiles([])
    // Reset textarea height
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const onTextChange = (e) => {
    setText(e.target.value)
    // Auto-resize
    const t = e.target
    t.style.height = 'auto'
    t.style.height = Math.min(t.scrollHeight, 200) + 'px'
  }

  const addFiles = (incoming) => {
    const arr = Array.from(incoming || [])
    if (!arr.length) return
    setFiles((cur) => [...cur, ...arr])
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        addFiles(e.dataTransfer.files)
      }}
      className={cn(
        'border rounded-xl bg-white transition-colors',
        dragOver ? 'border-primary-400 bg-primary-50/50' : 'border-ink-200',
      )}
    >
      {/* File chips */}
      {files.length > 0 && (
        <div className="px-3 pt-3 flex flex-wrap gap-2">
          {files.map((f, i) => (
            <div
              key={i}
              className="inline-flex items-center gap-2 pl-2 pr-1 py-1 rounded-md bg-ink-100 border border-ink-200 text-xs"
            >
              <FileText className="w-3.5 h-3.5 text-primary-500" />
              <span className="text-ink-700 max-w-[180px] truncate">{f.name}</span>
              <span className="text-ink-400">{formatBytes(f.size)}</span>
              <button
                onClick={() => setFiles((cur) => cur.filter((_, idx) => idx !== i))}
                className="ml-1 text-ink-400 hover:text-red-500"
                title="移除"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Textarea */}
      <textarea
        ref={textareaRef}
        value={text}
        onChange={onTextChange}
        onKeyDown={onKeyDown}
        disabled={disabled}
        placeholder="发送消息（Shift+Enter 换行）⋯ 可拖拽文件到此处"
        rows={1}
        className="w-full resize-none border-0 outline-none px-4 py-3 text-sm bg-transparent placeholder:text-ink-400 disabled:opacity-50"
      />

      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 pb-2">
        <button
          onClick={() => fileRef.current?.click()}
          disabled={disabled}
          className="p-2 rounded-md text-ink-500 hover:bg-ink-100 hover:text-primary-600 disabled:opacity-50 disabled:cursor-not-allowed"
          title="附加文件"
        >
          <Paperclip className="w-4 h-4" />
        </button>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".docx,.pdf,.xlsx,.xls,.md,.txt"
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />

        <button
          onClick={send}
          disabled={loading || disabled || (!text.trim() && files.length === 0)}
          className={cn(
            'inline-flex items-center gap-1.5 px-4 h-8 rounded-lg text-sm font-medium transition-colors',
            'bg-primary-600 text-white hover:bg-primary-700',
            'disabled:opacity-40 disabled:cursor-not-allowed',
          )}
        >
          {loading ? (
            <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
          ) : (
            <Send className="w-3.5 h-3.5" />
          )}
          发送
        </button>
      </div>
    </div>
  )
}
