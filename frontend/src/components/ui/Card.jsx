import { cn } from '@/lib/utils'

export function Card({ className, children, ...props }) {
  return (
    <div
      className={cn(
        'rounded-xl border border-ink-200 bg-white transition-shadow duration-200 hover:shadow-soft',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export function CardHeader({ className, children }) {
  return <div className={cn('p-5 pb-3 border-b border-ink-100', className)}>{children}</div>
}

export function CardTitle({ className, children }) {
  return <h3 className={cn('text-base font-semibold text-ink-800', className)}>{children}</h3>
}

export function CardDescription({ className, children }) {
  return <p className={cn('text-xs text-ink-500 mt-1', className)}>{children}</p>
}

export function CardContent({ className, children }) {
  return <div className={cn('p-5', className)}>{children}</div>
}

export function CardFooter({ className, children }) {
  return <div className={cn('px-5 pb-5 pt-2 flex items-center', className)}>{children}</div>
}
