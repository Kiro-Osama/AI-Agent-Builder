import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, MessageSquare, GitBranch, Clock, Zap, Search, Play, RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

interface AgentEntry {
  type: 'agent'
  task_id: string
  name: string
  query: string
  status: string
  model: string
  mcps_count: number
  skills_count: number
  created_at: string
}

interface WorkflowEntry {
  type: 'workflow'
  workflow_id: string
  name: string
  query: string
  status: string
  topology: string
  agents_count: number
  agent_names: string[]
  created_at: string
}

function timeAgo(dateStr: string) {
  if (!dateStr) return '—'
  const diff = Date.now() - new Date(dateStr).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

export function ChatHistoryPage() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<AgentEntry[]>([])
  const [workflows, setWorkflows] = useState<WorkflowEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const data = await api.get<{ agents: AgentEntry[]; workflows: WorkflowEntry[] }>('/dashboard')
      setAgents(data.agents ?? [])
      setWorkflows(data.workflows ?? [])
    } catch {
      toast.error('Failed to load chat history')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const q = search.toLowerCase()
  const filteredAgents = agents.filter(e =>
    !q || e.name?.toLowerCase().includes(q) || e.query?.toLowerCase().includes(q)
  )
  const filteredWorkflows = workflows.filter(e =>
    !q || e.name?.toLowerCase().includes(q) || e.query?.toLowerCase().includes(q)
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <MessageSquare className="h-6 w-6 text-ab-purple" />
            Chat History
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Resume conversations with your built agents
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg glass glass-hover text-sm text-muted-foreground hover:text-foreground transition-all"
        >
          <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} /> Refresh
        </button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search by agent name or query..."
          className="w-full rounded-xl border border-border bg-white/[0.04] pl-10 pr-4 py-2.5 text-sm outline-none focus:border-ab-purple transition-all"
        />
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground gap-3">
          <RefreshCw className="h-5 w-5 animate-spin" />
          Loading history...
        </div>
      ) : (agents.length === 0 && workflows.length === 0) ? (
        <div className="glass rounded-2xl p-12 text-center">
          <Bot className="h-12 w-12 text-muted-foreground/30 mx-auto mb-3" />
          <h3 className="text-base font-medium">No builds yet</h3>
          <p className="text-sm text-muted-foreground mt-1">Build your first agent to start chatting</p>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Agent builds */}
          {filteredAgents.length > 0 && (
            <section>
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                <Bot className="h-4 w-4" /> Agents ({filteredAgents.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {filteredAgents.map(entry => (
                  <AgentCard
                    key={entry.task_id}
                    title={entry.name}
                    subtitle={entry.model}
                    query={entry.query}
                    status={entry.status}
                    createdAt={entry.created_at}
                    badges={[
                      { icon: <Zap className="h-3 w-3" />, label: `${entry.mcps_count} MCPs` },
                      { icon: <span>🧠</span>, label: `${entry.skills_count} Skills` },
                    ]}
                    onChat={() => navigate(`/chat?task_id=${entry.task_id}`)}
                  />
                ))}
              </div>
            </section>
          )}

          {/* Workflow builds */}
          {filteredWorkflows.length > 0 && (
            <section>
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
                <GitBranch className="h-4 w-4" /> Workflows ({filteredWorkflows.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {filteredWorkflows.map(entry => (
                  <AgentCard
                    key={entry.workflow_id}
                    title={entry.name}
                    subtitle={entry.topology}
                    query={entry.query}
                    status={entry.status}
                    createdAt={entry.created_at}
                    isWorkflow
                    badges={[
                      { icon: <GitBranch className="h-3 w-3" />, label: `${entry.agents_count} agents` },
                    ]}
                    onChat={() => navigate(`/workflow-chat?workflow_id=${entry.workflow_id}`)}
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}

function AgentCard({
  title, subtitle, query, status, createdAt,
  badges, onChat, isWorkflow,
}: {
  title: string
  subtitle?: string
  query: string
  status: string
  createdAt: string
  badges: { icon: React.ReactNode; label: string }[]
  onChat: () => void
  isWorkflow?: boolean
}) {
  const truncate = (s: string, n = 90) => s?.length > n ? s.slice(0, n) + '…' : s

  return (
    <div className="glass glass-hover rounded-2xl p-4 flex flex-col gap-3 transition-all hover:-translate-y-0.5 group cursor-default">
      {/* Top */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <div className={cn(
            'flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl',
            isWorkflow ? 'bg-ab-cyan/10 border border-ab-cyan/20' : 'gradient-primary shadow-lg shadow-ab-purple/20',
          )}>
            {isWorkflow
              ? <GitBranch className="h-4 w-4 text-ab-cyan" />
              : <Bot className="h-4 w-4 text-white" />
            }
          </div>
          <div className="min-w-0">
            <p className="font-semibold text-sm truncate">{title}</p>
            {subtitle && (
              <p className="text-[10px] font-mono text-muted-foreground truncate">{subtitle}</p>
            )}
          </div>
        </div>
        <span className={cn(
          'px-2 py-0.5 rounded-full text-[10px] font-semibold flex-shrink-0 border',
          status === 'completed' ? 'bg-ab-green/15 text-ab-green border-ab-green/20' :
          status === 'failed' ? 'bg-ab-red/15 text-ab-red border-ab-red/20' :
          'bg-ab-purple/15 text-ab-purple border-ab-purple/20',
        )}>
          {status}
        </span>
      </div>

      {/* Query */}
      <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2 flex-1 min-h-[2.5rem]">
        {truncate(query ?? '')}
      </p>

      {/* Stats */}
      <div className="flex items-center gap-3 text-[11px] text-muted-foreground flex-wrap">
        {badges.map((b, i) => (
          <span key={i} className="flex items-center gap-1">{b.icon} {b.label}</span>
        ))}
        <span className="ml-auto flex items-center gap-1">
          <Clock className="h-3 w-3" /> {timeAgo(createdAt)}
        </span>
      </div>

      {/* Action */}
      {status === 'completed' && (
        <button
          onClick={onChat}
          className="w-full flex items-center justify-center gap-2 py-2 rounded-xl gradient-primary text-white text-xs font-semibold transition-all hover:shadow-lg hover:shadow-ab-purple/30 translate-y-1 opacity-0 group-hover:opacity-100 group-hover:translate-y-0 duration-200"
        >
          <Play className="h-3.5 w-3.5" /> Resume Chat
        </button>
      )}
    </div>
  )
}
