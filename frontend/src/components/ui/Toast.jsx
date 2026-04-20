import { createContext, useContext, useState, useCallback } from 'react'
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react'
import { cn } from '@/lib/utils'

const ToastContext = createContext(null)

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const push = useCallback((toast) => {
    const id = Date.now() + Math.random()
    setToasts((cur) => [...cur, { id, type: 'info', ...toast }])
    setTimeout(() => {
      setToasts((cur) => cur.filter((t) => t.id !== id))
    }, toast.duration || 4000)
  }, [])

  const api = {
    success: (msg) => push({ type: 'success', message: msg }),
    error: (msg) => push({ type: 'error', message: msg, duration: 6000 }),
    info: (msg) => push({ type: 'info', message: msg }),
  }

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map((t) => (
          <ToastItem
            key={t.id}
            {...t}
            onClose={() => setToasts((cur) => cur.filter((x) => x.id !== t.id))}
          />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}

const ICONS = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
}

const STYLES = {
  success: 'bg-emerald-50 border-emerald-200 text-emerald-800',
  error: 'bg-red-50 border-red-200 text-red-800',
  info: 'bg-blue-50 border-blue-200 text-blue-800',
}

function ToastItem({ type, message, onClose }) {
  const Icon = ICONS[type] || Info
  return (
    <div
      className={cn(
        'flex items-start gap-3 min-w-[320px] max-w-md p-4 rounded-lg shadow-lg border pointer-events-auto animate-fade-in',
        STYLES[type],
      )}
    >
      <Icon className="w-5 h-5 shrink-0 mt-0.5" />
      <div className="flex-1 text-sm">{message}</div>
      <button onClick={onClose} className="opacity-50 hover:opacity-100">
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}
