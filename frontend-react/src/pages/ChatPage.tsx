import { useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import {
  ArrowLeft, Send, Bot, User,
  Wrench, CheckCircle, XCircle, Loader2, ChevronDown, ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import { LLM_PROVIDERS, GEMINI_MODELS, OPENROUTER_MODELS } from '@/lib/constants'
import { BackgroundOrbs } from '@/components/common/BackgroundOrbs'
import type { AgentTemplate } from '@/types'

// ---- Types ----
interface ToolCallLive {
  tool: string
  args: Record<string, unknown>
  result?: string
  status: 'running' | 'done' | 'error'
}

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  tool_calls?: ToolCallLive[]
  streaming?: boolean
}

// ---- Tool call card ----
function ToolCallCard({ tc }: { tc: ToolCallLive }) {
  const [open, setOpen] = useState(false)
  return (
    <div className={cn(
      'rounded-lg border px-3 py-2 text-[11px] font-mono transition-all',
      tc.status === 'running' ? 'border-ab-purple/30 bg-ab-purple/5 text-ab-purple' :
      tc.status === 'done' ? 'border-ab-green/20 bg-ab-green/5 text-ab-green' :
      'border-ab-red/20 bg-ab-red/5 text-ab-red',
    )}>
      <div className="flex items-center gap-2 cursor-pointer" onClick={() => setOpen(o => !o)}>
        {tc.status === 'running'
          ? <Loader2 className="h-3 w-3 animate-spin flex-shrink-0" />
          : tc.status === 'done'
          ? <CheckCircle className="h-3 w-3 flex-shrink-0" />
          : <XCircle className="h-3 w-3 flex-shrink-0" />
        }
        <Wrench className="h-3 w-3 flex-shrink-0 opacity-60" />
        <span className="font-semibold">{tc.tool}</span>
        {tc.status === 'running' && <span className="opacity-60 text-[9px] animate-pulse ml-auto">executing...</span>}
        {tc.status !== 'running' && (
          open ? <ChevronDown className="h-3 w-3 ml-auto" /> : <ChevronRight className="h-3 w-3 ml-auto" />
        )}
      </div>

      {open && tc.status !== 'running' && (
        <div className="mt-2 space-y-1.5">
          {Object.keys(tc.args).length > 0 && (
            <div>
              <div className="text-[9px] opacity-60 mb-0.5">ARGS</div>
              <pre className="text-[10px] opacity-80 whitespace-pre-wrap break-all leading-relaxed">
                {JSON.stringify(tc.args, null, 2)}
              </pre>
            </div>
          )}
          {tc.result && (
            <div>
              <div className="text-[9px] opacity-60 mb-0.5">RESULT</div>
              <pre className="text-[10px] opacity-80 whitespace-pre-wrap break-all leading-relaxed max-h-32 overflow-y-auto">
                {tc.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ChatPage() {
  const [params] = useSearchParams()
  const taskId = params.get('task_id')
  const importData = params.get('import')

  const [agent, setAgent] = useState<AgentTemplate | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [convId, setConvId] = useState<string | null>(null)
  const [provider, setProvider] = useState('gemini')
  const [model, setModel] = useState('')
  const messagesEnd = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Load agent info
  useEffect(() => {
    if (taskId) {
      api.get<any>(`/chat/${taskId}/info`).then(d => setAgent({
        agent_name: d.agent_name,
        model: d.model,
        system_prompt: d.system_prompt,
        mcps: d.selected_mcps,
        skills: d.selected_skills?.map((s: any) => s.skill_id) ?? [],
        llm_provider: 'gemini',
      })).catch(() => {})
    }
    if (importData) {
      try { setAgent(JSON.parse(decodeURIComponent(importData))) } catch { /* ignore */ }
    }
  }, [taskId, importData])

  const scrollToBottom = useCallback(() => {
    setTimeout(() => messagesEnd.current?.scrollIntoView({ behavior: 'smooth' }), 50)
  }, [])

  // ---- Streaming send ----
  const sendMessage = useCallback(async () => {
    if (!input.trim() || sending) return
    const text = input.trim()
    setInput('')
    setSending(true)

    // Add user message
    setMessages(prev => [...prev, { role: 'user', content: text }])
    scrollToBottom()

    // Add placeholder assistant message
    const assistantIdx = messages.length + 1
    setMessages(prev => [...prev, {
      role: 'assistant',
      content: '',
      tool_calls: [],
      streaming: true,
    }])

    const abort = new AbortController()
    abortRef.current = abort

    const url = taskId ? `/api/v1/chat/${taskId}/stream` : null

    if (!url) {
      setMessages(prev => {
        const next = [...prev]
        next[next.length - 1] = { role: 'assistant', content: 'No task ID provided. Please build an agent first.' }
        return next
      })
      setSending(false)
      return
    }

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          llm_provider: provider,
          model: model || undefined,
          conversation_id: convId || undefined,
        }),
        signal: abort.signal,
      })
      if (!response.ok) {
        const errText = await response.text()
        throw new Error(`HTTP ${response.status}: ${errText.slice(0, 200)}`)
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data:')) continue
          const jsonStr = trimmed.slice(5).trim()
          if (!jsonStr) continue

          let event: any
          try { event = JSON.parse(jsonStr) } catch { continue }

          const type = event.type

          if (type === 'tool_start') {
            setMessages(prev => {
              const next = [...prev]
              const last = { ...next[next.length - 1] } as ChatMessage
              last.tool_calls = [...(last.tool_calls ?? []), {
                tool: event.tool as string,
                args: event.args ?? {},
                status: 'running' as const,
              }]
              next[next.length - 1] = last
              return next
            })
            scrollToBottom()
          }

          else if (type === 'tool_end') {
            setMessages(prev => {
              const next = [...prev]
              const last = { ...next[next.length - 1] } as ChatMessage
              const tcs: ToolCallLive[] = [...(last.tool_calls ?? [])]
              for (let i = tcs.length - 1; i >= 0; i--) {
                const tc = tcs[i]
                if (tc && tc.tool === event.tool && tc.status === 'running') {
                  tcs[i] = { tool: tc.tool, args: tc.args ?? {}, result: event.result as string, status: 'done' as const }
                  break
                }
              }
              last.tool_calls = tcs
              next[next.length - 1] = last
              return next
            })
          }

          else if (type === 'text') {
            setMessages(prev => {
              const next = [...prev]
              const last = { ...next[next.length - 1] } as ChatMessage
              last.content = (last.content ?? '') + event.content
              next[next.length - 1] = last
              return next
            })
            scrollToBottom()
          }

          else if (type === 'done') {
            if (event.conversation_id) setConvId(event.conversation_id)
            setMessages(prev => {
              const next = [...prev]
              const last = { ...next[next.length - 1] } as ChatMessage
              last.streaming = false
              if (last.tool_calls) {
                last.tool_calls = last.tool_calls.map(tc =>
                  tc.status === 'running' ? { ...tc, tool: tc.tool, status: 'done' as const } : tc
                )
              }
              next[next.length - 1] = last
              return next
            })
            break
          }

          else if (type === 'error') {
            setMessages(prev => {
              const next = [...prev]
              const last = { ...next[next.length - 1] } as ChatMessage
              last.content = `Error: ${event.message}`
              last.streaming = false
              next[next.length - 1] = last
              return next
            })
            break
          }
        }
      }
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        setMessages(prev => {
          const next = [...prev]
          const last = { ...next[next.length - 1] } as ChatMessage
          last.content = `Error: ${e.message}`
          last.streaming = false
          next[next.length - 1] = last
          return next
        })
      }
    } finally {
      setSending(false)
      scrollToBottom()
    }
  }, [input, sending, taskId, convId, provider, messages.length, scrollToBottom])

  const models = provider === 'gemini' ? GEMINI_MODELS : OPENROUTER_MODELS

  return (
    <div className="relative flex h-screen flex-col overflow-hidden">
      <BackgroundOrbs />

      {/* Header */}
      <header className="relative z-10 flex items-center justify-between border-b border-white/[0.08] bg-card/80 px-6 py-3 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl gradient-primary shadow-lg shadow-ab-purple/20">
            <Bot className="h-5 w-5 text-white" />
          </div>
          <div>
            <h2 className="text-sm font-semibold">{agent?.agent_name ?? 'Loading Agent...'}</h2>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[11px] font-mono text-muted-foreground">{agent?.model ?? ''}</span>
              {agent?.mcps && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-ab-green/12 text-ab-green border border-ab-green/20">
                  {agent.mcps.length} MCP(s)
                </span>
              )}
              {sending && (
                <span className="flex items-center gap-1 text-[10px] text-ab-purple animate-pulse">
                  <Loader2 className="h-3 w-3 animate-spin" /> thinking...
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <select value={provider} onChange={(e) => setProvider(e.target.value)}
            className="rounded-lg border border-white/[0.08] bg-card px-2 py-1.5 text-[11px] font-mono text-foreground outline-none">
            {LLM_PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
          <select value={model} onChange={(e) => setModel(e.target.value)}
            className="rounded-lg border border-white/[0.08] bg-card px-2 py-1.5 text-[11px] font-mono text-foreground outline-none max-w-[200px]">
            {models.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
          <Link to="/chats" className="px-3 py-1.5 rounded-lg border border-white/[0.08] text-xs text-muted-foreground hover:text-foreground hover:bg-white/[0.04] transition-all">
            <ArrowLeft className="h-3.5 w-3.5 inline mr-1" /> Builder
          </Link>
        </div>
      </header>

      {/* Messages */}
      <div className="relative z-10 flex-1 overflow-y-auto px-6 py-6 space-y-4">
        {messages.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <Bot className="mx-auto mb-3 h-12 w-12 text-muted-foreground/30" />
              <h3 className="text-base font-medium text-foreground">{agent?.agent_name ?? 'Agent'}</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-md">
                Send a message to start the conversation. You'll see live tool calls as the agent works.
              </p>
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={cn('flex gap-3 max-w-[85%] animate-slide-up', msg.role === 'user' ? 'ml-auto flex-row-reverse' : '')}>
            <div className={cn('flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg text-sm',
              msg.role === 'user' ? 'bg-ab-blue/20 border border-ab-blue/30' : 'gradient-primary')}>
              {msg.role === 'user' ? <User className="h-4 w-4 text-ab-blue" /> : <Bot className="h-4 w-4 text-white" />}
            </div>
            <div className="space-y-2 min-w-0 max-w-full">
              {/* Tool calls — shown live */}
              {msg.tool_calls && msg.tool_calls.length > 0 && (
                <div className="space-y-1.5">
                  {msg.tool_calls.map((tc, j) => <ToolCallCard key={j} tc={tc} />)}
                </div>
              )}
              {/* Message text */}
              {(msg.content || msg.streaming) && (
                <div className={cn('rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap break-words',
                  msg.role === 'user'
                    ? 'bg-gradient-to-br from-ab-purple to-purple-700 text-white rounded-br-md'
                    : 'bg-card/90 border border-white/[0.08] text-foreground rounded-bl-md')}>
                  {msg.content}
                  {msg.streaming && !msg.content && (
                    <div className="flex gap-1">
                      <span className="h-2 w-2 rounded-full bg-ab-purple animate-bounce" />
                      <span className="h-2 w-2 rounded-full bg-ab-purple animate-bounce [animation-delay:0.15s]" />
                      <span className="h-2 w-2 rounded-full bg-ab-purple animate-bounce [animation-delay:0.3s]" />
                    </div>
                  )}
                  {msg.streaming && msg.content && (
                    <span className="inline-block w-0.5 h-4 ml-0.5 bg-ab-purple animate-pulse align-middle" />
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEnd} />
      </div>

      {/* Input */}
      <div className="relative z-10 border-t border-white/[0.08] bg-card/80 px-6 py-4 backdrop-blur-xl">
        <div className="mx-auto flex max-w-3xl items-end gap-3">
          <textarea value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
            placeholder="Type your message..." rows={1}
            className="flex-1 rounded-xl border border-white/[0.08] bg-card px-4 py-3 text-sm text-foreground outline-none resize-none max-h-28 transition-all placeholder:text-muted-foreground/50 focus:border-ab-purple" />
          <button onClick={sendMessage} disabled={sending || !input.trim()}
            className="flex h-11 w-11 items-center justify-center rounded-xl gradient-primary text-white transition-all hover:shadow-lg hover:shadow-ab-purple/30 hover:scale-105 disabled:opacity-50 disabled:hover:scale-100">
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </div>
  )
}
