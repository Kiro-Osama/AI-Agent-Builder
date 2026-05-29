import { useState, useEffect, useCallback } from 'react'
import { Settings, Plus, Search, Trash2, Edit, TestTube } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import type { MCP } from '@/types'

export function AdminPage() {
  const [mcps, setMcps] = useState<MCP[]>([])
  const [search, setSearch] = useState('')
  const [catFilter, setCatFilter] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [form, setForm] = useState({ name: '', image: '', desc: '', category: '', tools: '[]', runConfig: '{}', requiresConfig: false, configSchema: '[]' })

  const loadMCPs = useCallback(async () => {
    try {
      const data = await api.get<{ mcps: MCP[] }>('/admin/mcps?include_inactive=true')
      setMcps(Array.isArray(data?.mcps) ? data.mcps : [])
    } catch { toast.error('Failed to load MCPs') }
  }, [])

  useEffect(() => { loadMCPs() }, [loadMCPs])

  const categories = [...new Set(mcps.map(m => m.category).filter(Boolean))]
  const filtered = mcps.filter(m => {
    if (search && !m.mcp_name.toLowerCase().includes(search.toLowerCase()) && !m.description.toLowerCase().includes(search.toLowerCase())) return false
    if (catFilter && m.category !== catFilter) return false
    return true
  })

  const openAdd = () => { setEditId(null); setForm({ name: '', image: '', desc: '', category: '', tools: '[]', runConfig: '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{}}', requiresConfig: false, configSchema: '[]' }); setModalOpen(true) }
  const openEdit = (m: MCP) => { setEditId(m.id); setForm({ name: m.mcp_name, image: m.docker_image, desc: m.description, category: m.category, tools: JSON.stringify(m.tools_provided, null, 2), runConfig: JSON.stringify(m.run_config, null, 2), requiresConfig: m.requires_config, configSchema: JSON.stringify(m.config_schema || [], null, 2) }); setModalOpen(true) }

  const saveMCP = async () => {
    try {
      const body = { mcp_name: form.name, docker_image: form.image, description: form.desc, category: form.category, tools_provided: JSON.parse(form.tools), run_config: JSON.parse(form.runConfig), requires_config: form.requiresConfig, config_schema: JSON.parse(form.configSchema) }
      if (editId) { await api.put(`/admin/mcps/${editId}`, body) } else { await api.post('/admin/mcps', body) }
      toast.success(editId ? 'MCP updated' : 'MCP added')
      setModalOpen(false); loadMCPs()
    } catch (e: unknown) { toast.error(e instanceof Error ? e.message : 'Save failed') }
  }

  const deleteMCP = async (id: number) => {
    if (!confirm('Delete this MCP?')) return
    try { await api.delete(`/admin/mcps/${id}`); toast.success('Deleted'); loadMCPs() } catch { toast.error('Delete failed') }
  }

  return (
    <div className="space-y-6">
      <section className="glass rounded-2xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><Settings className="h-5 w-5 text-ab-purple" /> MCP Catalog Management</h2>
          <button onClick={openAdd} className="flex items-center gap-1.5 px-4 py-2 rounded-lg gradient-primary text-white text-sm font-semibold hover:shadow-lg hover:shadow-ab-purple/30 transition-all"><Plus className="h-4 w-4" /> Add MCP</button>
        </div>

        {/* Stats */}
        <div className="flex gap-4 mb-4 text-sm text-muted-foreground">
          <span>Total: <strong className="text-foreground">{mcps.length}</strong></span>
          <span>Active: <strong className="text-ab-green">{mcps.filter(m => m.is_active).length}</strong></span>
          <span>Embedded: <strong className="text-ab-cyan">{mcps.filter(m => m.has_embedding).length}</strong></span>
        </div>

        {/* Filters */}
        <div className="flex gap-3 mb-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search MCPs..."
              className="w-full rounded-lg border border-border bg-white/[0.04] pl-9 pr-3 py-2 text-sm outline-none focus:border-ab-purple" />
          </div>
          <select value={catFilter} onChange={(e) => setCatFilter(e.target.value)}
            className="rounded-lg border border-border bg-white/[0.04] px-3 py-2 text-sm outline-none">
            <option value="">All categories</option>
            {categories.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border">
              <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Name</th>
              <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Image</th>
              <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Category</th>
              <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Tools</th>
              <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Status</th>
              <th className="px-3 py-2 text-right text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Actions</th>
            </tr></thead>
            <tbody>
              {filtered.map((m) => (
                <tr key={m.id} className="border-b border-white/[0.04] hover:bg-white/[0.02] transition-colors">
                  <td className="px-3 py-3 font-medium">{m.mcp_name}</td>
                  <td className="px-3 py-3 font-mono text-xs text-muted-foreground">{m.docker_image}</td>
                  <td className="px-3 py-3"><span className="px-2 py-0.5 rounded text-[10px] font-semibold uppercase bg-ab-purple/15 text-ab-purple">{m.category}</span></td>
                  <td className="px-3 py-3 text-muted-foreground">{m.tools_provided?.length ?? 0}</td>
                  <td className="px-3 py-3">
                    <span className={cn('px-2 py-0.5 rounded-full text-[10px] font-semibold',
                      m.is_active ? 'bg-ab-green/15 text-ab-green border border-ab-green/30' : 'bg-ab-red/15 text-ab-red border border-ab-red/30')}>
                      {m.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex justify-end gap-1">
                      <button onClick={() => openEdit(m)} className="p-1.5 rounded-lg hover:bg-white/[0.06] text-muted-foreground hover:text-foreground transition-all"><Edit className="h-3.5 w-3.5" /></button>
                      <button onClick={() => deleteMCP(m.id)} className="p-1.5 rounded-lg hover:bg-ab-red/10 text-muted-foreground hover:text-ab-red transition-all"><Trash2 className="h-3.5 w-3.5" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setModalOpen(false)}>
          <div className="w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-2xl border border-border bg-card p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold mb-4">{editId ? 'Edit MCP' : 'Add New MCP'}</h3>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="MCP Name" value={form.name} onChange={(v) => setForm(f => ({ ...f, name: v }))} placeholder="mcp-example" />
                <Field label="Category" value={form.category} onChange={(v) => setForm(f => ({ ...f, category: v }))} placeholder="devops" />
              </div>
              <Field label="Docker Image" value={form.image} onChange={(v) => setForm(f => ({ ...f, image: v }))} placeholder="mcp/example:latest" />
              <TextareaField label="Description" value={form.desc} onChange={(v) => setForm(f => ({ ...f, desc: v }))} rows={2} />
              <TextareaField label="Tools (JSON array)" value={form.tools} onChange={(v) => setForm(f => ({ ...f, tools: v }))} rows={3} mono />
              <TextareaField label="Run Config (JSON)" value={form.runConfig} onChange={(v) => setForm(f => ({ ...f, runConfig: v }))} rows={3} mono />
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button onClick={() => setModalOpen(false)} className="px-4 py-2 rounded-lg border border-border text-sm text-muted-foreground hover:text-foreground transition-all">Cancel</button>
              <button onClick={saveMCP} className="px-4 py-2 rounded-lg gradient-primary text-white text-sm font-semibold transition-all hover:shadow-lg hover:shadow-ab-purple/30">Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div>
      <label className="block mb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="w-full rounded-lg border border-border bg-white/[0.04] px-3 py-2 text-sm outline-none focus:border-ab-purple" />
    </div>
  )
}

function TextareaField({ label, value, onChange, rows = 3, mono }: { label: string; value: string; onChange: (v: string) => void; rows?: number; mono?: boolean }) {
  return (
    <div>
      <label className="block mb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{label}</label>
      <textarea value={value} onChange={(e) => onChange(e.target.value)} rows={rows}
        className={cn('w-full rounded-lg border border-border bg-white/[0.04] px-3 py-2 text-sm outline-none resize-y focus:border-ab-purple', mono && 'font-mono text-xs')} />
    </div>
  )
}
