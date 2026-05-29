import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { Layout } from '@/components/layout/Layout'
import { LoginPage } from '@/pages/LoginPage'
import { BuilderPage } from '@/pages/BuilderPage'
import { ChatPage } from '@/pages/ChatPage'
import { ChatHistoryPage } from '@/pages/ChatHistoryPage'
import { WorkflowChatPage } from '@/pages/WorkflowChatPage'
import { AdminPage } from '@/pages/AdminPage'

function AuthGuard({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)

  return (
    <Routes>
      <Route
        path="/login"
        element={isAuthenticated ? <Navigate to="/" replace /> : <LoginPage />}
      />
      <Route
        element={
          <AuthGuard>
            <Layout />
          </AuthGuard>
        }
      >
        <Route path="/" element={<BuilderPage />} />
        <Route path="/chats" element={<ChatHistoryPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/workflow-chat" element={<WorkflowChatPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
