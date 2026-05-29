import { useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { ArrowLeft, Send, Bot, User, GitBranch, BarChart2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import { BackgroundOrbs } from '@/components/common/BackgroundOrbs'
import { LLM_PROVIDERS } from '@/lib/constants'
import type { WorkflowInfo, WorkflowChatResponse } from '@/types'

interface WFMessage { role: 'user' | 'agent'; content: string; agentName?: string; path?: string; toolCount?: number }

export function WorkflowChatPage() {
  const [params] = useSearchParams()
  const workflowId = params.get('workflow_id')
  const [wfInfo, setWfInfo] = useState<WorkflowInfo | null>(null)
  const [messages, setMessages] = useState<WFMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [convId, setConvId] = useState<string | null>(null)
  const [provider, setProvider] = useState('gemini')
  const [panelOpen, setPanelOpen] = useState(true)
  const [sharedState, setSharedState] = useState<Record<string, unknown>>({})
  const messagesEnd = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!workflowId) return
    api.get<WorkflowInfo>(`/workflow/${workflowId}/chat/info`).then(setWfInfo).catch(() => {})
  }, [workflowId])

  const scrollToBottom = useCallback(() => {
    setTimeout(() => messagesEnd.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }, [])

  const sendMessage = useCallback(async () => {
    if (!input.trim() || sending || !workflowId) return
    setMessages(prev => [...prev, { role: 'user', content: input.trim() }])
    setInput(''); setSending(true); scrollToBottom()
    try {
      const res = await api.post<WorkflowChatResponse>(`/workflow/${workflowId}/chat`, {
        message: input.trim(), conversation_id: convId, llm_provider: provider,
      }, 120_000)
      setConvId(res.conversation_id)
      const agentName = wfInfo?.agents.find(a => a.role === res.responding_agent)?.agent_name ?? res.responding_agent
      const path = res.execution_path.map(r => wfInfo?.agents.find(a => a.role === r)?.agent_name ?? r).join(' → ')
      setMessages(prev => [...prev, { role: 'agent', content: res.response, agentName, path, toolCount: res.tool_calls_count }])
      setSharedState(res.shared_state || {})
    } catch (e: unknown) {
      setMessages(prev => [...prev, { role: 'agent', content: `Error: ${e instanceof Error ? e.message : 'Unknown'}` }])
    } finally { setSending(false); scrollToBottom() }
  }, [input, sending, workflowId, convId, provider, wfInfo, scrollToBottom])

  const topoBadgeColor: Record<string, string> = {
    sequential: 'bg-ab-blue/15 text-blue-400',
    parallel: 'bg-ab-green/15 text-ab-green',
    supervisor: 'bg-ab-purple/15 text-purple-400',
    swarm: 'bg-ab-yellow/15 text-ab-yellow',
  }

  if (!workflowId) return (
    <div className="flex h-screen items-center justify-center"><p className="text-muted-foreground">No workflow ID. Go back and build a workflow first.</p></div>
  )

  return (
    <div className="relative flex h-screen flex-col overflow-hidden">
      <BackgroundOrbs />

      {/* Header */}
      <header className="relative z-10 flex items-center justify-between border-b border-white/[0.08] bg-card/80 px-6 py-3 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl gradient-primary"><GitBranch className="h-5 w-5 text-white" /></div>
          <div>
            <h2 className="text-sm font-semibold">{wfInfo?.name ?? 'Loading...'}</h2>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={cn('px-2 py-0.5 rounded text-[10px] font-bold uppercase', topoBadgeColor[wfInfo?.topology ?? ''] ?? 'bg-white/5 text-muted-foreground')}>{wfInfo?.topology}</span>
              <span className="text-[11px] text-muted-foreground">{wfInfo?.agents.length ?? 0} agents</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <select value={provider} onChange={(e) => setProvider(e.target.value)}
            className="rounded-lg border border-white/[0.08] bg-card px-2 py-1.5 text-[11px] font-mono text-foreground outline-none">
            {LLM_PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
          <Link to="/" className="px-3 py-1.5 rounded-lg border border-white/[0.08] text-xs text-muted-foreground hover:text-foreground transition-all">
            <ArrowLeft className="h-3.5 w-3.5 inline mr-1" /> Builder
          </Link>
        </div>
      </header>

      {/* Topology Bar */}
      {wfInfo && (
        <div className="relative z-10 flex items-center gap-2 border-b border-white/[0.08] bg-white/[0.02] px-6 py-2 overflow-x-auto">
          {wfInfo.agents.map((a, i) => (
            <div key={a.role} className="flex items-center gap-2">
              <span className="whitespace-nowrap rounded-full border border-white/[0.08] bg-white/[0.04] px-3 py-1 text-[11px] font-semibold">{a.agent_name || a.role}</span>
              {i < wfInfo.agents.length - 1 && <span className="text-muted-foreground text-xs">→</span>}
            </div>
          ))}
        </div>
      )}

      <div className="relative z-10 flex flex-1 overflow-hidden">
        {/* Messages */}
        <div className="flex flex-1 flex-col">
          <div className="flex-1 overflow-y-auto px-6 py-6 space-y-4">
            {messages.length === 0 && (
              <div className="flex h-full items-center justify-center text-center">
                <div><GitBranch className="mx-auto mb-3 h-12 w-12 text-muted-foreground/30" /><h3 className="text-base font-medium">{wfInfo?.name ?? 'Workflow'}</h3><p className="text-sm text-muted-foreground mt-1">Send a message to route through agents.</p></div>
              </div>
            )}
            {messages.map((msg, i) => (
              <div key={i} className={cn('flex gap-3 max-w-[85%] animate-slide-up', msg.role === 'user' ? 'ml-auto flex-row-reverse' : '')}>
                <div className={cn('flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg', msg.role === 'user' ? 'bg-ab-blue/20 border border-ab-blue/30' : 'gradient-primary')}>
                  {msg.role === 'user' ? <User className="h-4 w-4 text-ab-blue" /> : <Bot className="h-4 w-4 text-white" />}
                </div>
                <div className="min-w-0 space-y-1">
                  {msg.agentName && <div className="text-[10px] font-bold uppercase tracking-wider text-ab-purple">{msg.agentName} {msg.toolCount ? <span className="text-ab-green">🔧 {msg.toolCount}</span> : null}</div>}
                  <div className={cn('rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap break-words',
                    msg.role === 'user' ? 'bg-gradient-to-br from-ab-purple to-purple-700 text-white rounded-br-md' : 'bg-card/90 border border-white/[0.08] rounded-bl-md')}>
                    {msg.content}
                  </div>
                  {msg.path && <div className="text-[10px] font-mono text-muted-foreground">Path: {msg.path}</div>}
                </div>
              </div>
            ))}
            {sending && <div className="flex gap-3 animate-slide-up"><div className="flex h-8 w-8 items-center justify-center rounded-lg gradient-primary"><Bot className="h-4 w-4 text-white" /></div><div className="rounded-2xl bg-card/90 border border-white/[0.08] px-4 py-3 rounded-bl-md"><div className="flex gap-1"><span className="h-2 w-2 rounded-full bg-ab-purple animate-bounce" /><span className="h-2 w-2 rounded-full bg-ab-purple animate-bounce [animation-delay:0.15s]" /><span className="h-2 w-2 rounded-full bg-ab-purple animate-bounce [animation-delay:0.3s]" /></div></div></div>}
            <div ref={messagesEnd} />
          </div>
          <div className="border-t border-white/[0.08] bg-card/80 px-6 py-4 backdrop-blur-xl">
            <div className="mx-auto flex max-w-3xl items-end gap-3">
              <textarea value={input} onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
                placeholder="Type your message..." rows={1}
                className="flex-1 rounded-xl border border-white/[0.08] bg-card px-4 py-3 text-sm outline-none resize-none max-h-28 focus:border-ab-purple" />
              <button onClick={sendMessage} disabled={sending} className="flex h-11 w-11 items-center justify-center rounded-xl gradient-primary text-white hover:shadow-lg hover:shadow-ab-purple/30 disabled:opacity-50"><Send className="h-4 w-4" /></button>
              <button onClick={() => setPanelOpen(p => !p)} className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/[0.08] text-muted-foreground hover:text-foreground"><BarChart2 className="h-4 w-4" /></button>
            </div>
          </div>
        </div>

        {/* Side Panel */}
        {panelOpen && (
          <div className="w-72 border-l border-white/[0.08] bg-card/50 backdrop-blur-xl overflow-y-auto p-4">
            <h3 className="text-[11px] font-bold uppercase tracking-wider text-ab-purple mb-3">Shared State</h3>
            {Object.keys(sharedState).length === 0 ? (
              <p className="text-xs text-muted-foreground text-center py-8">State will appear during conversation.</p>
            ) : (
              Object.entries(sharedState).map(([key, val]) => (
                <div key={key} className="mb-3">
                  <div className="text-[10px] font-bold uppercase text-ab-purple tracking-wider mb-1">{key}</div>
                  <div className="rounded-lg bg-black/20 p-2 text-xs font-mono text-muted-foreground break-words max-h-28 overflow-y-auto">
                    {typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val)}
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}
