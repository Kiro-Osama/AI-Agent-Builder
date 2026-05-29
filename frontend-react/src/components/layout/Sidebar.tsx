import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  MessageSquare,
  Shield,
  Settings,
  Zap,
  ChevronLeft,
  ChevronRight,
  LogOut,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useUIStore } from '@/stores/uiStore'
import { useAuthStore } from '@/stores/authStore'

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Builder' },
  { to: '/chats', icon: MessageSquare, label: 'Chat' },
  { to: '/admin', icon: Settings, label: 'Admin' },
]

export function Sidebar() {
  const { sidebarOpen, toggleSidebar } = useUIStore()
  const logout = useAuthStore((s) => s.logout)
  const location = useLocation()

  // Hide sidebar on individual chat/workflow-chat pages (with query params), not on /chats list
  if ((location.pathname === '/chat' || location.pathname.startsWith('/workflow-chat'))) {
    return null
  }

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-40 flex h-screen flex-col border-r border-border bg-card/80 backdrop-blur-xl transition-all duration-300',
        sidebarOpen ? 'w-56' : 'w-16',
      )}
    >
      {/* Logo */}
      <div className="flex h-16 items-center gap-3 border-b border-border px-4">
        <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg gradient-primary">
          <Zap className="h-5 w-5 text-white" />
        </div>
        {sidebarOpen && (
          <div className="overflow-hidden">
            <h1 className="text-sm font-bold tracking-tight">
              Agent Builder <span className="gradient-text font-extrabold">V5</span>
            </h1>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-2 py-4">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                'group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200',
                isActive
                  ? 'bg-ab-purple/15 text-ab-purple'
                  : 'text-muted-foreground hover:bg-white/[0.04] hover:text-foreground',
              )
            }
            end={item.to === '/'}
          >
            <item.icon className="h-5 w-5 flex-shrink-0" />
            {sidebarOpen && <span>{item.label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="space-y-1 border-t border-border px-2 py-3">
        <button
          onClick={logout}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted-foreground transition-all hover:bg-ab-red/10 hover:text-ab-red"
        >
          <LogOut className="h-5 w-5 flex-shrink-0" />
          {sidebarOpen && <span>Logout</span>}
        </button>

        <button
          onClick={toggleSidebar}
          className="flex w-full items-center justify-center rounded-lg p-2 text-muted-foreground transition-all hover:bg-white/[0.04] hover:text-foreground"
        >
          {sidebarOpen ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
      </div>
    </aside>
  )
}
