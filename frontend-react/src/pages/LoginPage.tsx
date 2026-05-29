import { useState } from 'react'
import { Zap, ArrowRight, Shield } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { api } from '@/lib/api'
import { BackgroundOrbs } from '@/components/common/BackgroundOrbs'
import { toast } from 'sonner'

export function LoginPage() {
  const [key, setKey] = useState('')
  const [loading, setLoading] = useState(false)
  const login = useAuthStore((s) => s.login)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!key.trim()) {
      toast.error('Please enter an API key')
      return
    }
    setLoading(true)
    // Log in immediately — health check is non-blocking
    login(key.trim())
    // Check API connectivity in background
    api.healthCheck().then((ok) => {
      if (ok) toast.success('Welcome to Agent Builder V5 ⚡')
      else toast.warning('Logged in — API server may be offline', { description: 'Check docker compose status' })
    }).catch(() => {
      toast.warning('Logged in — API server unreachable')
    }).finally(() => setLoading(false))
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center">
      <BackgroundOrbs />

      <div className="relative z-10 w-full max-w-md px-4">
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl gradient-primary shadow-lg shadow-ab-purple/30">
            <Zap className="h-8 w-8 text-white" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight">
            Agent Builder <span className="gradient-text font-extrabold">V5</span>
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Dynamic AI Agent Configuration Platform
          </p>
        </div>

        {/* Login Card */}
        <div className="glass rounded-2xl p-8">
          <div className="mb-6 flex items-center gap-2 text-sm text-muted-foreground">
            <Shield className="h-4 w-4 text-ab-purple" />
            <span>Authenticate to continue</span>
          </div>

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-muted-foreground">
                API Key
              </label>
              <input
                type="password"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="Enter your API key..."
                className="w-full rounded-lg border border-border bg-white/[0.04] px-4 py-3 text-sm text-foreground outline-none transition-all placeholder:text-muted-foreground/50 focus:border-ab-purple focus:ring-2 focus:ring-ab-purple/20"
                autoFocus
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="group flex w-full items-center justify-center gap-2 rounded-lg gradient-primary px-4 py-3 text-sm font-semibold text-white transition-all hover:shadow-lg hover:shadow-ab-purple/30 disabled:opacity-50"
            >
              {loading ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              ) : (
                <>
                  <span>Sign In</span>
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                </>
              )}
            </button>
          </form>

          <p className="mt-4 text-center text-xs text-muted-foreground">
            Use any key to authenticate. Connection to the API server is verified on login.
          </p>
        </div>
      </div>
    </div>
  )
}
