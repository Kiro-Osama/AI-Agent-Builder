import { create } from 'zustand'
import type { PipelineStatus, AgentTemplate, MCP, Skill, EmbeddingStatus } from '@/types'
import { api } from '@/lib/api'

interface BuildState {
  // Build form
  activeTab: 'ai' | 'manual' | 'workflow'
  setActiveTab: (tab: 'ai' | 'manual' | 'workflow') => void

  // Pipeline
  taskId: string | null
  pipelineStatus: PipelineStatus | null
  building: boolean
  submitAIBuild: (query: string, opts: Record<string, unknown>) => Promise<void>
  submitManualBuild: (data: Record<string, unknown>) => Promise<void>
  submitWorkflowBuild: (data: Record<string, unknown>) => Promise<void>
  pollPipeline: () => Promise<boolean>
  reset: () => void

  // Result
  result: AgentTemplate | null
}

export const useBuildStore = create<BuildState>()((set, get) => ({
  activeTab: 'ai',
  setActiveTab: (tab) => set({ activeTab: tab }),

  taskId: null,
  pipelineStatus: null,
  building: false,
  result: null,

  submitAIBuild: async (query, opts) => {
    set({ building: true, result: null, pipelineStatus: null })
    try {
      const res = await api.post<{ task_id: string }>('/build', { query, ...opts })
      set({ taskId: res.task_id })
    } catch (e) {
      set({ building: false })
      throw e
    }
  },

  submitManualBuild: async (data) => {
    set({ building: true, result: null, pipelineStatus: null })
    try {
      const res = await api.post<{ task_id: string; status: string; template: AgentTemplate }>('/build/manual', data)
      set({ taskId: res.task_id })
      // Manual build completes immediately — use the returned template directly
      if (res.status === 'completed' && res.template) {
        const agents = (res.template as any)?.agents
        const agentTemplate = agents?.[0] ? {
          agent_name: agents[0].agent_name,
          model: agents[0].assigned_openrouter_model,
          system_prompt: agents[0].system_prompt,
          mcps: agents[0].selected_mcps || [],
          skills: (agents[0].selected_skills || []).map((s: any) => s.skill_id),
          llm_provider: (data as any).llm_provider,
        } : res.template
        set({ result: agentTemplate, building: false })
      }
    } catch (e) {
      set({ building: false })
      throw e
    }
  },

  submitWorkflowBuild: async (data) => {
    set({ building: true, result: null, pipelineStatus: null })
    try {
      const res = await api.post<{ task_id: string }>('/workflow/build', data, 60_000)
      set({ taskId: res.task_id })
    } catch (e) {
      set({ building: false })
      throw e
    }
  },

  pollPipeline: async () => {
    const { taskId } = get()
    if (!taskId) return true
    try {
      const status = await api.get<PipelineStatus>(`/status/${taskId}`)
      set({ pipelineStatus: status })
      if (status.status === 'completed' && status.result_template) {
        set({ result: status.result_template, building: false })
        return true
      }
      if (status.status === 'failed' || status.status === 'error') {
        set({ building: false })
        return true
      }
      return false
    } catch {
      return false
    }
  },

  reset: () =>
    set({
      taskId: null,
      pipelineStatus: null,
      building: false,
      result: null,
    }),
}))

// ---- Catalog Store ----

interface CatalogState {
  mcps: MCP[]
  skills: Skill[]
  embeddingStatus: EmbeddingStatus | null
  loadingMcps: boolean
  loadingSkills: boolean
  showDashboard: boolean
  fetchMCPs: () => Promise<void>
  fetchSkills: () => Promise<void>
  fetchEmbeddingStatus: () => Promise<void>
  runEmbeddings: () => Promise<void>
  toggleDashboard: () => void
}

export const useCatalogStore = create<CatalogState>()((set) => ({
  mcps: [],
  skills: [],
  embeddingStatus: null,
  loadingMcps: false,
  loadingSkills: false,
  showDashboard: false,

  fetchMCPs: async () => {
    set({ loadingMcps: true })
    try {
      const data = await api.get<{ mcps: MCP[] }>('/admin/mcps')
      set({ mcps: Array.isArray(data?.mcps) ? data.mcps : [] })
    } catch { /* ignore */ }
    set({ loadingMcps: false })
  },

  fetchSkills: async () => {
    set({ loadingSkills: true })
    try {
      const data = await api.get<{ skills: Skill[] }>('/skills')
      set({ skills: Array.isArray(data?.skills) ? data.skills : [] })
    } catch { /* ignore */ }
    set({ loadingSkills: false })
  },

  fetchEmbeddingStatus: async () => {
    try {
      const data = await api.get<EmbeddingStatus>('/embeddings/status')
      set({ embeddingStatus: data })
    } catch { /* ignore */ }
  },

  runEmbeddings: async () => {
    await api.post('/embeddings/generate')
  },

  toggleDashboard: () => set((s) => ({ showDashboard: !s.showDashboard })),
}))
