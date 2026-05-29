// ---- MCP Types ----
export interface MCPTool {
  name: string
  description: string
}

export interface MCP {
  id: number
  mcp_name: string
  docker_image: string
  description: string
  tools_provided: MCPTool[]
  category: string
  run_config: Record<string, unknown>
  requires_config: boolean
  config_schema: unknown[]
  is_active: boolean
  has_embedding: boolean
}

// ---- Skill Types ----
export interface Skill {
  id: number
  skill_id: string
  display_name: string
  description: string
  tags: string[]
  source: string
}

// ---- Pipeline Types ----
export type PipelineNodeStatus = 'pending' | 'active' | 'completed' | 'error'

export interface PipelineNodeData {
  status: PipelineNodeStatus
  search_queries?: string[]
  mcps?: Array<{ name: string; score: number }>
  skills?: Array<{ name: string; score: number }>
  selected_mcps?: string[]
  selected_skills?: string[]
  created_skill?: { id: string; name: string; description: string }
  docker_results?: Array<{ name: string; status: string; port?: number }>
  agent_name?: string
  model?: string
  warning?: string
  [key: string]: unknown
}

export interface PipelineStatus {
  task_id: string
  status: string
  progress: number
  current_node: string
  processing_log: any[]
  result_template?: AgentTemplate
  error?: string
}

// ---- Agent Template ----
export interface AgentTemplate {
  agent_name: string
  model: string
  system_prompt: string
  mcps: Array<{
    mcp_name: string
    docker_image: string
    run_config: Record<string, unknown>
  }>
  skills: string[]
  llm_provider?: string
}

// ---- Chat Types ----
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  tool_calls?: ToolCall[]
  images?: Array<{ data: string; media_type: string }>
}

export interface ToolCall {
  tool: string
  args: Record<string, unknown>
  result: string
  success: boolean
}

export interface ChatResponse {
  response: string
  tool_calls: ToolCall[]
  model: string
  conversation_id: string
}

// ---- Workflow Types ----
export interface WorkflowAgent {
  role: string
  agent_name: string
  sub_task: string
  mcps?: string[]
  skills?: string[]
}

export interface WorkflowInfo {
  workflow_id: string
  name: string
  description?: string
  topology: string
  agents: WorkflowAgent[]
  user_query?: string
}

export interface WorkflowChatResponse {
  response: string
  conversation_id: string
  current_agent: string
  responding_agent: string
  execution_path: string[]
  tool_calls_count: number
  shared_state: Record<string, unknown>
}

// ---- Dashboard ----
export interface DashboardAgent {
  task_id: string
  agent_name: string
  model: string
  created_at: string
  mcps_count: number
  skills_count: number
}

export interface DashboardWorkflow {
  workflow_id: string
  name: string
  topology: string
  agent_count: number
  created_at: string
}

// ---- Embedding ----
export interface EmbeddingStatus {
  total_mcps: number
  embedded_mcps: number
  total_skills: number
  embedded_skills: number
  status: string
}
