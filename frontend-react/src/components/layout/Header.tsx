import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { StatusIndicator } from '@/components/common/StatusIndicator'
import { Database } from 'lucide-react'

export function Header() {
  const [apiStatus, setApiStatus] = useState<'checking' | 'online' | 'offline'>('checking')

  useEffect(() => {
    const check = async () => {
      const ok = await api.healthCheck()
      setApiStatus(ok ? 'online' : 'offline')
    }
    check()
    const interval = setInterval(check, 30_000)
    return () => clearInterval(interval)
  }, [])

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-background/80 px-6 backdrop-blur-xl">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Database className="h-3.5 w-3.5" />
          <span>Vector Index</span>
        </div>
      </div>
      <StatusIndicator
        status={apiStatus}
        label={apiStatus === 'online' ? 'API Online' : apiStatus === 'offline' ? 'API Offline' : 'Checking...'}
      />
    </header>
  )
}
