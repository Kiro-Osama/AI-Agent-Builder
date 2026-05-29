import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import {
  Wrench, Zap, Settings2, GitBranch,
  RefreshCw, Copy, Download, RotateCcw, MessageSquare,
  Search, Check, Package, FlaskConical, Target, Container,
  ClipboardList, Hammer, SearchCode,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useBuildStore, useCatalogStore } from '@/stores/buildStore'
import { api } from '@/lib/api'
import { LLM_PROVIDERS, GEMINI_MODELS, OPENROUTER_MODELS, TOPOLOGIES, PIPELINE_NODES } from '@/lib/constants'
import type { MCP } from '@/types'

/* ───────────────────────────────────────────── */
/* Helpers                                        */
/* ───────────────────────────────────────────── */

const NODE_ICONS: Record<string, React.ElementType> = {
  query_analyzer: Search,
  similarity_retriever: SearchCode,
  needs_assessment: ClipboardList,
  skill_creator: Hammer,
  sandbox_validator: FlaskConical,
  ai_final_filter: Target,
  docker_mcp_runner: Container,
  template_builder: ClipboardList,
  final_output: Package,
}

function SelectField({
  label, value, onChange, options, disabled,
}: {
  label: string; value: string; onChange: (v: string) => void
  options: { value: string; label: string }[]; disabled?: boolean
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</label>
      <select
        value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}
        className="rounded-lg border border-border bg-white/[0.04] px-3 py-2 text-sm text-foreground outline-none transition-all focus:border-ab-purple disabled:opacity-40 cursor-pointer"
      >
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}

/* ───────────────────────────────────────────── */
/* BuilderPage                                    */
/* ───────────────────────────────────────────── */
export function BuilderPage() {
  const navigate = useNavigate()
  const {
    activeTab, setActiveTab, building, taskId, pipelineStatus, result,
    submitAIBuild, submitManualBuild, submitWorkflowBuild, pollPipeline, reset,
  } = useBuildStore()
  const { mcps, skills, fetchMCPs, fetchSkills, fetchEmbeddingStatus, embeddingStatus, runEmbeddings } = useCatalogStore()

  /* ── AI Build state ── */
  const [query, setQuery] = useState('')
  const [provider, setProvider] = useState('gemini')
  const [model, setModel] = useState('')
  const [maxMcps, setMaxMcps] = useState('5')
  const [maxSkills, setMaxSkills] = useState('8')
  const [enableSkills, setEnableSkills] = useState(true)

  /* ── Manual Build state ── */
  const [manualName, setManualName] = useState('Custom_Agent')
  const [manualProvider, setManualProvider] = useState('gemini')
  const [manualModel, setManualModel] = useState('')
  const [manualPrompt, setManualPrompt] = useState('You are a helpful AI assistant. Use your tools when needed to complete tasks.')
  const [selectedMCPs, setSelectedMCPs] = useState<number[]>([])
  const [selectedSkills, setSelectedSkills] = useState<string[]>([])
  const [mcpSearch, setMcpSearch] = useState('')
  const [skillSearch, setSkillSearch] = useState('')

  /* ── Workflow Build state ── */
  const [wfQuery, setWfQuery] = useState('')
  const [wfProvider, setWfProvider] = useState('gemini')
  const [wfModel, setWfModel] = useState('')
  const [wfTopology, setWfTopology] = useState('auto')
  const [wfMaxMcps, setWfMaxMcps] = useState('3')
  const [wfMaxSkills, setWfMaxSkills] = useState('8')
  const [wfAwaitApproval, setWfAwaitApproval] = useState(true)

  /* ── Catalog search ── */
  const [mcpCatalogSearch, setMcpCatalogSearch] = useState('')
  const [skillsCatalogSearch, setSkillsCatalogSearch] = useState('')
  const [embRunning, setEmbRunning] = useState(false)

  const charCount = query.length

  useEffect(() => {
    fetchMCPs(); fetchSkills(); fetchEmbeddingStatus()
  }, [fetchMCPs, fetchSkills, fetchEmbeddingStatus])

  /* Pipeline polling */
  useEffect(() => {
    if (!taskId || !building) return
    const id = setInterval(async () => {
      const done = await pollPipeline()
      if (done) clearInterval(id)
    }, 2000)
    return () => clearInterval(id)
  }, [taskId, building, pollPipeline])

  const models = provider === 'gemini' ? GEMINI_MODELS : OPENROUTER_MODELS
  const manualModels = manualProvider === 'gemini' ? GEMINI_MODELS : OPENROUTER_MODELS
  const wfModels = wfProvider === 'gemini' ? GEMINI_MODELS : OPENROUTER_MODELS

  /* ── Handlers ── */
  const handleAIBuild = useCallback(async () => {
    if (!query.trim()) { toast.error('Please describe your agent task'); return }
    try {
      await submitAIBuild(query, {
        llm_provider: provider, model_preference: model || undefined,
        max_mcps: parseInt(maxMcps), max_skills: parseInt(maxSkills),
        enable_skill_creation: enableSkills,
      })
      toast.success('Build started!')
    } catch (e: unknown) { toast.error(e instanceof Error ? e.message : 'Build failed') }
  }, [query, provider, model, maxMcps, maxSkills, enableSkills, submitAIBuild])

  const handleManualBuild = useCallback(async () => {
    if (!manualName.trim()) { toast.error('Please enter an agent name'); return }
    if (!selectedMCPs.length && !selectedSkills.length) { toast.error('Select at least one MCP or skill'); return }
    try {
      await submitManualBuild({
        agent_name: manualName, llm_provider: manualProvider,
        model: manualModel || 'gemini-2.0-flash',
        system_prompt: manualPrompt,
        selected_mcp_ids: selectedMCPs,
        selected_skill_ids: selectedSkills,
      })
      toast.success('Manual build started!')
    } catch (e: unknown) { toast.error(e instanceof Error ? e.message : 'Build failed') }
  }, [manualName, manualProvider, manualModel, manualPrompt, selectedMCPs, selectedSkills, submitManualBuild])

  const handleWorkflowBuild = useCallback(async () => {
    if (!wfQuery.trim()) { toast.error('Please describe the workflow task'); return }
    try {
      await submitWorkflowBuild({
        query: wfQuery, llm_provider: wfProvider,
        model_preference: wfModel || undefined, topology_preference: wfTopology,
        sub_build_max_mcps: parseInt(wfMaxMcps), sub_build_max_skills: parseInt(wfMaxSkills),
        await_plan_approval: wfAwaitApproval,
      })
      toast.success('Workflow build started!')
    } catch (e: unknown) { toast.error(e instanceof Error ? e.message : 'Build failed') }
  }, [wfQuery, wfProvider, wfModel, wfTopology, wfMaxMcps, wfMaxSkills, wfAwaitApproval, submitWorkflowBuild])

  const toggleMCP = (id: number) => setSelectedMCPs(prev => prev.includes(id) ? prev.filter(n => n !== id) : [...prev, id])
  const toggleSkill = (id: string) => setSelectedSkills(prev => prev.includes(id) ? prev.filter(n => n !== id) : [...prev, id])

  const filteredMcps = mcps.filter(m => m.is_active && (!mcpSearch || m.mcp_name.toLowerCase().includes(mcpSearch.toLowerCase()) || (m.description ?? '').toLowerCase().includes(mcpSearch.toLowerCase())))
  const filteredSkills = skills.filter(s => !skillSearch || s.display_name.toLowerCase().includes(skillSearch.toLowerCase()))
  const catalogMcps = mcps.filter(m => m.is_active && (!mcpCatalogSearch || m.mcp_name.toLowerCase().includes(mcpCatalogSearch.toLowerCase()) || m.description.toLowerCase().includes(mcpCatalogSearch.toLowerCase())))
  const catalogSkills = skills.filter(s => !skillsCatalogSearch || s.display_name.toLowerCase().includes(skillsCatalogSearch.toLowerCase()))

  const handleRunEmbeddings = async () => {
    setEmbRunning(true)
    try { await runEmbeddings(); await fetchEmbeddingStatus(); toast.success('Embeddings generated!') }
    catch { toast.error('Failed to generate embeddings') }
    finally { setEmbRunning(false) }
  }

  return (
    <div className="space-y-6">

      {/* ── Build Section ── */}
      <section className="glass rounded-2xl p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <Wrench className="h-5 w-5 text-ab-purple" /> Build New Agent
          </h2>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 p-1 rounded-xl bg-white/[0.03] border border-white/[0.05] mb-6">
          {[
            { id: 'ai' as const, label: 'AI Build', Icon: Zap },
            { id: 'manual' as const, label: 'Manual Build', Icon: Settings2 },
            { id: 'workflow' as const, label: 'Workflow Build', Icon: GitBranch },
          ].map(({ id, label, Icon }) => (
            <button key={id} onClick={() => setActiveTab(id)}
              className={cn(
                'flex-1 flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium transition-all duration-200',
                activeTab === id
                  ? 'gradient-primary text-white shadow-lg shadow-ab-purple/20'
                  : 'text-muted-foreground hover:text-foreground hover:bg-white/[0.04]',
              )}>
              <Icon className="h-4 w-4" />{label}
            </button>
          ))}
        </div>

        {/* ── AI Build ── */}
        {activeTab === 'ai' && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">Describe the task. The system will find the right MCPs, create skills, and build your agent.</p>
            <div className="relative">
              <textarea
                value={query} onChange={(e) => setQuery(e.target.value)} rows={4}
                placeholder="Example: I need an agent that can scan a website for vulnerabilities and generate a detailed security report..."
                className="w-full rounded-xl border border-border bg-white/[0.04] px-4 py-3 text-sm text-foreground outline-none transition-all placeholder:text-muted-foreground/50 focus:border-ab-purple focus:ring-2 focus:ring-ab-purple/20 resize-none"
              />
              <span className="absolute bottom-3 right-3 text-[11px] font-mono text-muted-foreground/60">{charCount}/5000</span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <SelectField label="LLM Provider" value={provider} onChange={(v) => { setProvider(v); setModel('') }} options={LLM_PROVIDERS.map(p => ({ value: p.value, label: p.label }))} />
              <SelectField label="Model" value={model} onChange={setModel} options={models.map(m => ({ value: m.value, label: m.label }))} disabled={provider === 'ollama' || provider === 'ollama_remote'} />
              <SelectField label="Max MCPs" value={maxMcps} onChange={setMaxMcps} options={['0', '3', '5', '10'].map(v => ({ value: v, label: v }))} />
              <SelectField label="Max Skills" value={maxSkills} onChange={setMaxSkills} options={['0', '3', '5', '8', '12', '20'].map(v => ({ value: v, label: v }))} />
              <div className="flex flex-col gap-1.5">
                <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Skill Creation</label>
                <button onClick={() => setEnableSkills(p => !p)}
                  className={cn('relative h-9 w-14 rounded-full border transition-all', enableSkills ? 'bg-ab-purple/20 border-ab-purple' : 'bg-white/[0.04] border-border')}>
                  <span className={cn('absolute top-1 h-7 w-7 rounded-full transition-all', enableSkills ? 'left-7 bg-ab-purple' : 'left-0.5 bg-muted-foreground/50')} />
                </button>
              </div>
            </div>
            <button onClick={handleAIBuild} disabled={building}
              className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl gradient-primary text-white font-semibold transition-all hover:shadow-lg hover:shadow-ab-purple/30 hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-50 disabled:hover:translate-y-0 disabled:cursor-not-allowed">
              {building
                ? <><div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" /> Building...</>
                : <><Zap className="h-4 w-4" /> Build Agent</>}
            </button>
          </div>
        )}

        {/* ── Manual Build ── */}
        {activeTab === 'manual' && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">Build an agent manually by selecting MCPs, skills, and writing a system prompt.</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="flex flex-col gap-1.5">
                <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Agent Name</label>
                <input value={manualName} onChange={(e) => setManualName(e.target.value)} placeholder="My_Custom_Agent"
                  className="rounded-lg border border-border bg-white/[0.04] px-3 py-2.5 text-sm outline-none focus:border-ab-purple" />
              </div>
              <SelectField label="LLM Provider" value={manualProvider} onChange={(v) => { setManualProvider(v); setManualModel('') }} options={LLM_PROVIDERS.map(p => ({ value: p.value, label: p.label }))} />
              <SelectField label="Model" value={manualModel} onChange={setManualModel} options={manualModels.map(m => ({ value: m.value, label: m.label }))} disabled={manualProvider === 'ollama' || manualProvider === 'ollama_remote'} />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">System Prompt</label>
              <textarea value={manualPrompt} onChange={(e) => setManualPrompt(e.target.value)} rows={4}
                className="rounded-xl border border-border bg-white/[0.04] px-4 py-3 text-sm outline-none focus:border-ab-purple resize-none" />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* MCP Picker */}
              <div>
                <label className="block mb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Select MCPs ({selectedMCPs.length} selected)</label>
                <div className="relative mb-2"><Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <input value={mcpSearch} onChange={(e) => setMcpSearch(e.target.value)} placeholder="Search MCPs..."
                    className="w-full rounded-lg border border-border bg-white/[0.04] pl-8 pr-3 py-2 text-xs outline-none focus:border-ab-purple" />
                </div>
                <div className="max-h-40 overflow-y-auto space-y-1 rounded-xl border border-border bg-white/[0.02] p-2">
                  {filteredMcps.length === 0
                    ? <p className="text-center text-xs text-muted-foreground py-4">No MCPs available</p>
                    : filteredMcps.map(m => (
                    <button key={m.id} onClick={() => toggleMCP(m.id)}
                      className={cn('w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs text-left transition-all',
                        selectedMCPs.includes(m.id) ? 'bg-ab-purple/15 text-ab-purple' : 'hover:bg-white/[0.04] text-foreground')}>
                      <Check className={cn('h-3 w-3 flex-shrink-0', selectedMCPs.includes(m.id) ? 'opacity-100' : 'opacity-0')} />
                      {m.mcp_name}
                    </button>
                  ))}
                </div>
              </div>
              {/* Skill Picker */}
              <div>
                <label className="block mb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Select Skills ({selectedSkills.length} selected)</label>
                <div className="relative mb-2"><Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <input value={skillSearch} onChange={(e) => setSkillSearch(e.target.value)} placeholder="Search skills..."
                    className="w-full rounded-lg border border-border bg-white/[0.04] pl-8 pr-3 py-2 text-xs outline-none focus:border-ab-purple" />
                </div>
                <div className="max-h-40 overflow-y-auto space-y-1 rounded-xl border border-border bg-white/[0.02] p-2">
                  {filteredSkills.length === 0
                    ? <p className="text-center text-xs text-muted-foreground py-4">No skills available</p>
                    : filteredSkills.map(s => (
                      <button key={s.id} onClick={() => toggleSkill(s.skill_id)}
                        className={cn('w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs text-left transition-all',
                          selectedSkills.includes(s.skill_id) ? 'bg-ab-purple/15 text-ab-purple' : 'hover:bg-white/[0.04] text-foreground')}>
                        <Check className={cn('h-3 w-3 flex-shrink-0', selectedSkills.includes(s.skill_id) ? 'opacity-100' : 'opacity-0')} />
                        {s.display_name}
                      </button>
                    ))}
                </div>
              </div>
            </div>
            <button onClick={handleManualBuild} disabled={building}
              className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl gradient-primary text-white font-semibold transition-all hover:shadow-lg hover:shadow-ab-purple/30 hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed">
              {building ? <><div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" /> Building...</> : <><Settings2 className="h-4 w-4" /> Build Agent (Manual)</>}
            </button>
          </div>
        )}

        {/* ── Workflow Build ── */}
        {activeTab === 'workflow' && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">Describe a complex task. The system will decompose it into multiple agents and choose a topology.</p>
            <textarea value={wfQuery} onChange={(e) => setWfQuery(e.target.value)} rows={4}
              placeholder="Example: Build a full-stack app review system: one agent audits the frontend UX, another checks backend performance, a third reviews security..."
              className="w-full rounded-xl border border-border bg-white/[0.04] px-4 py-3 text-sm outline-none focus:border-ab-purple resize-none placeholder:text-muted-foreground/50" />
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <SelectField label="LLM Provider" value={wfProvider} onChange={(v) => { setWfProvider(v); setWfModel('') }} options={LLM_PROVIDERS.map(p => ({ value: p.value, label: p.label }))} />
              <SelectField label="Topology" value={wfTopology} onChange={setWfTopology} options={TOPOLOGIES.map(t => ({ value: t.value, label: t.label }))} />
              <SelectField label="Max MCPs / Agent" value={wfMaxMcps} onChange={setWfMaxMcps} options={['0', '2', '3', '5', '10'].map(v => ({ value: v, label: v }))} />
              <SelectField label="Max Skills / Agent" value={wfMaxSkills} onChange={setWfMaxSkills} options={['0', '3', '5', '8', '12'].map(v => ({ value: v, label: v }))} />
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={wfAwaitApproval} onChange={(e) => setWfAwaitApproval(e.target.checked)} className="accent-ab-purple" />
              <span className="text-sm text-muted-foreground">Review proposed plan before building agents (human-in-the-loop)</span>
            </label>
            <button onClick={handleWorkflowBuild} disabled={building}
              className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl gradient-primary text-white font-semibold transition-all hover:shadow-lg hover:shadow-ab-purple/30 hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed">
              {building ? <><div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" /> Building...</> : <><GitBranch className="h-4 w-4" /> Build Workflow</>}
            </button>
          </div>
        )}
      </section>

      {/* ── Pipeline Progress ── */}
      {(building || pipelineStatus) && !result && (
        <section className="glass rounded-2xl p-6">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-lg font-semibold">⚙️ Pipeline Progress</h2>
            <span className="font-mono text-xs text-muted-foreground bg-white/[0.04] px-2 py-1 rounded-md">{taskId?.slice(0, 12)}...</span>
          </div>
          <div className="relative h-1.5 rounded-full bg-white/[0.06] mb-6 overflow-hidden">
            <div className="h-full rounded-full gradient-primary transition-all duration-700 ease-out relative"
              style={{ width: `${pipelineStatus?.progress ?? 0}%` }}>
              <div className="absolute inset-0 bg-gradient-to-r from-transparent to-white/20 animate-shimmer" />
            </div>
            <span className="absolute -top-5 right-0 text-[11px] font-mono text-ab-purple">{pipelineStatus?.progress ?? 0}%</span>
          </div>
          <div className="space-y-1.5">
            {PIPELINE_NODES.map((node, nodeIdx) => {
              const currentIdx = PIPELINE_NODES.findIndex(n => n.key === pipelineStatus?.current_node)
              let status: 'pending' | 'active' | 'completed' | 'error' = 'pending'
              
              if (pipelineStatus) {
                if (pipelineStatus.status === 'failed' || pipelineStatus.status === 'error') {
                  if (nodeIdx === currentIdx) status = 'error'
                  else if (nodeIdx < currentIdx) status = 'completed'
                } else if (pipelineStatus.status === 'completed') {
                  status = 'completed'
                } else {
                  if (nodeIdx < currentIdx) status = 'completed'
                  else if (nodeIdx === currentIdx) status = 'active'
                }
              }

              const Icon = NODE_ICONS[node.key] ?? Package
              return (
                <div key={node.key} className={cn('flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-300',
                  status === 'active' && 'bg-ab-purple/10 border border-ab-purple/30',
                  status === 'completed' && 'bg-ab-green/5 border border-ab-green/20',
                  (status === 'pending' || !status) && 'bg-white/[0.02] border border-transparent',
                  status === 'error' && 'bg-ab-red/10 border border-ab-red/20',
                )}>
                  <Icon className={cn('h-4 w-4 flex-shrink-0',
                    status === 'active' && 'text-ab-purple animate-pulse',
                    status === 'completed' && 'text-ab-green',
                    status === 'pending' && 'text-muted-foreground/40',
                  )} />
                  <span className="flex-1 text-sm font-medium">{node.label}</span>
                  <span className="text-sm">
                    {status === 'completed' ? '✅' : status === 'active' ? '⚙️' : status === 'error' ? '❌' : '⏳'}
                  </span>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {/* ── Result ── */}
      {result && (
        <section className="glass rounded-2xl p-6 border-ab-green/20">
          <div className="flex items-center justify-between mb-5">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <span className="text-xl">🎉</span> Agent Template Ready
            </h2>
            <div className="flex gap-2">
              <button onClick={() => navigate(`/chat?task_id=${taskId}`)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg gradient-primary text-white text-sm font-semibold hover:shadow-lg hover:shadow-ab-purple/30 transition-all">
                <MessageSquare className="h-3.5 w-3.5" /> Chat
              </button>
              <button onClick={() => { navigator.clipboard.writeText(JSON.stringify(result, null, 2)); toast.success('Copied to clipboard') }}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg glass glass-hover text-sm text-muted-foreground hover:text-foreground transition-all">
                <Copy className="h-3.5 w-3.5" /> Copy
              </button>
              <button onClick={() => {
                const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }))
                a.download = `${result.agent_name}.json`; a.click()
              }}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg glass glass-hover text-sm text-muted-foreground hover:text-foreground transition-all">
                <Download className="h-3.5 w-3.5" /> Download
              </button>
              <button onClick={reset}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg glass glass-hover text-sm text-muted-foreground hover:text-foreground transition-all">
                <RotateCcw className="h-3.5 w-3.5" /> New
              </button>
            </div>
          </div>
          <pre className="max-h-96 overflow-auto rounded-xl bg-background border border-border p-5 text-xs font-mono text-ab-cyan leading-relaxed">
            {JSON.stringify(result, null, 2)}
          </pre>
        </section>
      )}

      {/* ── Embedding Toolbar ── */}
      <section className="glass rounded-2xl p-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 text-sm">
            <span className="text-muted-foreground font-medium">Vector Index</span>
            {embeddingStatus && (
              <div className="flex gap-3 text-xs text-muted-foreground">
                <span>MCPs: <strong className="text-foreground">{embeddingStatus.embedded_mcps}/{embeddingStatus.total_mcps}</strong></span>
                <span>Skills: <strong className="text-foreground">{embeddingStatus.embedded_skills}/{embeddingStatus.total_skills}</strong></span>
              </div>
            )}
          </div>
          <button onClick={handleRunEmbeddings} disabled={embRunning}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg glass glass-hover text-xs font-medium text-muted-foreground hover:text-foreground transition-all disabled:opacity-50">
            {embRunning ? <div className="h-3 w-3 animate-spin rounded-full border border-muted-foreground border-t-foreground" /> : <RefreshCw className="h-3 w-3" />}
            Generate Embeddings
          </button>
        </div>
      </section>

      {/* ── MCP Catalog ── */}
      <section className="glass rounded-2xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">🧰 Available MCPs</h2>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input value={mcpCatalogSearch} onChange={(e) => setMcpCatalogSearch(e.target.value)} placeholder="Search..."
                className="rounded-lg border border-border bg-white/[0.04] pl-8 pr-3 py-1.5 text-xs outline-none focus:border-ab-purple w-40" />
            </div>
            <button onClick={fetchMCPs} className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg glass glass-hover text-xs text-muted-foreground hover:text-foreground">
              <RefreshCw className="h-3 w-3" /> Refresh
            </button>
          </div>
        </div>
        {catalogMcps.length === 0
          ? <p className="text-center text-sm text-muted-foreground py-8">No MCPs loaded.</p>
          : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {catalogMcps.map((mcp) => <MCPCard key={mcp.id} mcp={mcp} />)}
            </div>
          )}
      </section>

      {/* ── Skills Catalog ── */}
      <section className="glass rounded-2xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">🧠 Skills Catalog</h2>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <input value={skillsCatalogSearch} onChange={(e) => setSkillsCatalogSearch(e.target.value)} placeholder="Search..."
                className="rounded-lg border border-border bg-white/[0.04] pl-8 pr-3 py-1.5 text-xs outline-none focus:border-ab-purple w-40" />
            </div>
            <button onClick={() => api.post('/skills/seed').then(() => { fetchSkills(); toast.success('Skills seeded!') }).catch(() => toast.error('Seed failed'))}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-ab-green/10 border border-ab-green/20 text-xs text-ab-green hover:bg-ab-green/20 transition-all">
              🌱 Seed Skills
            </button>
            <button onClick={fetchSkills} className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg glass glass-hover text-xs text-muted-foreground hover:text-foreground">
              <RefreshCw className="h-3 w-3" /> Refresh
            </button>
          </div>
        </div>
        {catalogSkills.length === 0
          ? <p className="text-center text-sm text-muted-foreground py-8">No skills available. Click "Seed Skills" to load from disk.</p>
          : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {catalogSkills.map((skill) => (
                <div key={skill.id} className="rounded-xl glass glass-hover p-4 transition-all hover:-translate-y-0.5">
                  <span className="font-semibold text-sm">{skill.display_name}</span>
                  <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2 mt-1">{skill.description}</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {skill.tags?.slice(0, 3).map(t => (
                      <span key={t} className="px-1.5 py-0.5 rounded text-[10px] bg-ab-purple/10 text-ab-purple border border-ab-purple/15">{t}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
      </section>
    </div>
  )
}

function MCPCard({ mcp }: { mcp: MCP }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="rounded-xl glass glass-hover p-4 transition-all hover:-translate-y-0.5">
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="font-semibold text-sm leading-tight">{mcp.mcp_name}</span>
        <span className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-ab-purple/15 text-ab-purple flex-shrink-0">{mcp.category}</span>
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2 mb-3">{mcp.description}</p>
      <div className="flex flex-wrap gap-1">
        {(expanded ? mcp.tools_provided : mcp.tools_provided?.slice(0, 3))?.map((t) => (
          <span key={t.name} className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-ab-cyan/10 text-ab-cyan border border-ab-cyan/15">{t.name}</span>
        ))}
        {!expanded && (mcp.tools_provided?.length ?? 0) > 3 && (
          <button onClick={() => setExpanded(true)} className="px-1.5 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground transition-colors">
            +{mcp.tools_provided.length - 3} more
          </button>
        )}
        {expanded && (
          <button onClick={() => setExpanded(false)} className="px-1.5 py-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground transition-colors">
            show less
          </button>
        )}
      </div>
    </div>
  )
}
