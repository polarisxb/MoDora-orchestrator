import { useState, useRef } from 'react'
import { Upload, FileText, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatBytes } from '@/lib/utils'

/**
 * Drag-and-drop or click-to-upload zone for one or more files.
 *
 * Props:
 *   accept       — file accept string, e.g. ".docx,.pdf"
 *   multiple     — allow selecting multiple files
 *   files        — controlled value (array of File)
 *   onFilesChange— (files: File[]) => void
 */
export function FileDropzone({
  accept,
  multiple = false,
  files = [],
  onFilesChange,
  hint,
  className,
}) {
  const inputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)

  const handleFiles = (incoming) => {
    const arr = Array.from(incoming || [])
    if (!arr.length) return
    onFilesChange?.(multiple ? [...files, ...arr] : [arr[0]])
  }

  const removeFile = (idx) => {
    onFilesChange?.(files.filter((_, i) => i !== idx))
  }

  return (
    <div className={className}>
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          handleFiles(e.dataTransfer.files)
        }}
        className={cn(
          'border border-dashed rounded-xl p-8 cursor-pointer transition-all duration-200',
          'flex flex-col items-center justify-center text-center',
          dragOver
            ? 'border-primary-400 bg-primary-50/60 scale-[1.01]'
            : 'border-ink-300 hover:border-primary-300 hover:bg-ink-50/50',
        )}
      >
        <div className={cn(
          'w-10 h-10 rounded-lg flex items-center justify-center mb-3 transition-colors',
          dragOver
            ? 'bg-primary-100 text-primary-600'
            : 'bg-ink-100 text-ink-500',
        )}>
          <Upload className="w-5 h-5" />
        </div>
        <p className="text-sm text-ink-700 font-medium">
          点击或拖拽文件到此处
        </p>
        {hint && <p className="text-xs text-ink-400 mt-1">{hint}</p>}
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {files.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {files.map((f, i) => (
            <li
              key={i}
              className="flex items-center gap-3 px-3 py-2 bg-white border border-ink-200 rounded-md text-sm"
            >
              <FileText className="w-4 h-4 text-primary-500 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="truncate text-ink-800">{f.name}</div>
                <div className="text-xs text-ink-500">{formatBytes(f.size)}</div>
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  removeFile(i)
                }}
                className="text-ink-400 hover:text-red-500"
              >
                <X className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
