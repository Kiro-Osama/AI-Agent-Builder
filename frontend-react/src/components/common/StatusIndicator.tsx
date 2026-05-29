import { cn } from '@/lib/utils'

interface StatusIndicatorProps {
  status: 'online' | 'offline' | 'checking'
  label?: string
  className?: string
}

export function StatusIndicator({ status, label, className }: StatusIndicatorProps) {
  return (
    <div className={cn('flex items-center gap-2 text-sm text-muted-foreground', className)}>
      <span
        className={cn(
          'h-2 w-2 rounded-full',
          status === 'online' && 'bg-ab-green',
          status === 'offline' && 'bg-ab-red',
          status === 'checking' && 'bg-ab-yellow animate-pulse-glow',
        )}
      />
      <span>{label ?? status}</span>
    </div>
  )
}
