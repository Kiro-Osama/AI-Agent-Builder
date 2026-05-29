import { Outlet, useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Header } from './Header'
import { BackgroundOrbs } from '@/components/common/BackgroundOrbs'
import { useUIStore } from '@/stores/uiStore'
import { cn } from '@/lib/utils'

export function Layout() {
  const sidebarOpen = useUIStore((s) => s.sidebarOpen)
  const location = useLocation()
  const isChat = location.pathname.startsWith('/chat') || location.pathname.startsWith('/workflow-chat')

  return (
    <div className="relative min-h-screen">
      <BackgroundOrbs />
      {!isChat && <Sidebar />}

      <div
        className={cn(
          'relative z-10 flex min-h-screen flex-col transition-all duration-300',
          !isChat && (sidebarOpen ? 'ml-56' : 'ml-16'),
        )}
      >
        {!isChat && <Header />}
        <main className={cn('flex-1', !isChat && 'mx-auto w-full max-w-5xl px-6 py-8')}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
