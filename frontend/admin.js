/* ============================================
   Admin Panel - MCP Management
   ============================================ */

const API = '/api/v1/admin';
let allMCPs = [];

document.addEventListener('DOMContentLoaded', () => loadMCPs());

async function loadMCPs() {
    const inactive = document.getElementById('showInactive').checked;
    try {
        const res = await fetch(`${API}/mcps?include_inactive=${inactive}`);
        if (!res.ok) throw new Error('Failed to load');
        const data = await res.json();
        allMCPs = data.mcps || [];
        populateFilters();
        renderTable();
        renderStats();
    } catch (e) {
        document.getElementById('mcpTableBody').innerHTML =
            `<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-muted);">Failed to load MCPs: ${esc(e.message)}</td></tr>`;
    }
}

function populateFilters() {
    const cats = [...new Set(allMCPs.map(m => m.category).filter(Boolean))].sort();
    const sel = document.getElementById('categoryFilter');
    const current = sel.value;
    sel.innerHTML = '<option value="">All categories</option>' +
        cats.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
    sel.value = current;
}

function renderStats() {
    const total = allMCPs.length;
    const shared = allMCPs.filter(m => !m.requires_user_config).length;
    const configurable = allMCPs.filter(m => m.requires_user_config).length;
    const embedded = allMCPs.filter(m => m.has_embedding).length;
    const active = allMCPs.filter(m => m.is_active).length;
    document.getElementById('statsBar').innerHTML =
        `<span>Total: <strong>${total}</strong></span>` +
        `<span>Active: <strong>${active}</strong></span>` +
        `<span>Shared: <strong>${shared}</strong></span>` +
        `<span>Configurable: <strong>${configurable}</strong></span>` +
        `<span>Embedded: <strong>${embedded}/${total}</strong></span>`;
}

function renderTable() {
    const search = document.getElementById('searchInput').value.toLowerCase();
    const catFilter = document.getElementById('categoryFilter').value;
    const typeFilter = document.getElementById('typeFilter').value;

    let filtered = allMCPs;
    if (search) filtered = filtered.filter(m =>
        m.mcp_name.toLowerCase().includes(search) ||
        (m.description || '').toLowerCase().includes(search)
    );
    if (catFilter) filtered = filtered.filter(m => m.category === catFilter);
    if (typeFilter === 'shared') filtered = filtered.filter(m => !m.requires_user_config);
    if (typeFilter === 'configurable') filtered = filtered.filter(m => m.requires_user_config);

    const tbody = document.getElementById('mcpTableBody');
    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-muted);">No MCPs match your filters</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(m => {
        const typeBadge = m.requires_user_config
            ? '<span class="badge configurable">configurable</span>'
            : '<span class="badge shared">shared</span>';
        const statusBadge = m.is_active === false
            ? ' <span class="badge inactive">inactive</span>'
            : '';
        const embBadge = m.has_embedding
            ? '<span class="badge shared">yes</span>'
            : '<span class="badge inactive">no</span>';
        const toolCount = (m.tools_provided || []).length;

        return `<tr>
            <td><strong>${esc(m.mcp_name)}</strong>${statusBadge}</td>
            <td style="font-family:var(--font-mono);font-size:0.78rem;color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(m.docker_image)}</td>
            <td>${m.category ? `<span class="mcp-card-category">${esc(m.category)}</span>` : '-'}</td>
            <td>${typeBadge}</td>
            <td>${toolCount}</td>
            <td>${embBadge}</td>
            <td><div class="actions-cell">
                <button class="btn-icon-sm" onclick="openEditModal(${m.id})" title="Edit">✏️</button>
                <button class="btn-icon-sm test" onclick="testMCP(${m.id})" title="Test">🧪</button>
                <button class="btn-icon-sm danger" onclick="deleteMCP(${m.id}, '${esc(m.mcp_name)}')" title="Deactivate">🗑️</button>
            </div></td>
        </tr>`;
    }).join('');
}

function openAddModal() {
    document.getElementById('modalTitle').textContent = 'Add New MCP';
    document.getElementById('editId').value = '';
    document.getElementById('fName').value = '';
    document.getElementById('fImage').value = '';
    document.getElementById('fCategory').value = '';
    document.getElementById('fDesc').value = '';
    document.getElementById('fTools').value = '[]';
    document.getElementById('fRunConfig').value = '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{}}';
    document.getElementById('fRequiresConfig').value = 'false';
    document.getElementById('fConfigSchema').value = '[]';
    document.getElementById('mcpModal').classList.add('open');
}

function openEditModal(id) {
    const m = allMCPs.find(x => x.id === id);
    if (!m) return;
    document.getElementById('modalTitle').textContent = `Edit: ${m.mcp_name}`;
    document.getElementById('editId').value = id;
    document.getElementById('fName').value = m.mcp_name;
    document.getElementById('fImage').value = m.docker_image;
    document.getElementById('fCategory').value = m.category || '';
    document.getElementById('fDesc').value = m.description || '';
    document.getElementById('fTools').value = JSON.stringify(m.tools_provided || [], null, 2);
    document.getElementById('fRunConfig').value = JSON.stringify(m.run_config || {}, null, 2);
    document.getElementById('fRequiresConfig').value = m.requires_user_config ? 'true' : 'false';
    document.getElementById('fConfigSchema').value = JSON.stringify(m.config_schema || [], null, 2);
    document.getElementById('mcpModal').classList.add('open');
}

function closeModal() {
    document.getElementById('mcpModal').classList.remove('open');
}

async function saveMCP() {
    const editId = document.getElementById('editId').value;
    const body = {
        mcp_name: document.getElementById('fName').value.trim(),
        docker_image: document.getElementById('fImage').value.trim(),
        description: document.getElementById('fDesc').value.trim(),
        category: document.getElementById('fCategory').value.trim() || null,
        requires_user_config: document.getElementById('fRequiresConfig').value === 'true',
    };

    try {
        body.tools_provided = JSON.parse(document.getElementById('fTools').value || '[]');
    } catch { body.tools_provided = []; }
    try {
        body.run_config = JSON.parse(document.getElementById('fRunConfig').value || '{}');
    } catch { body.run_config = {}; }
    try {
        body.config_schema = JSON.parse(document.getElementById('fConfigSchema').value || '[]');
    } catch { body.config_schema = []; }

    if (!body.mcp_name || !body.docker_image || !body.description) {
        showToast('Name, Image, and Description are required', 'error');
        return;
    }

    try {
        const url = editId ? `${API}/mcps/${editId}` : `${API}/mcps`;
        const method = editId ? 'PUT' : 'POST';
        const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Save failed');

        showToast(editId ? 'MCP updated' : 'MCP created', 'success');
        closeModal();
        await loadMCPs();
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

async function deleteMCP(id, name) {
    if (!confirm(`Deactivate "${name}"? It will be hidden from the catalog.`)) return;
    try {
        const res = await fetch(`${API}/mcps/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Delete failed');
        showToast(`${name} deactivated`, 'success');
        await loadMCPs();
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    }
}

async function testMCP(id) {
    const m = allMCPs.find(x => x.id === id);
    if (!m) return;

    showToast(`Testing ${m.mcp_name}...`, 'success');
    try {
        const res = await fetch(`${API}/mcps/${id}/test`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok') {
            showToast(`${m.mcp_name}: ${data.tools_count} tools discovered`, 'success');
        } else if (data.status === 'skipped') {
            showToast(`${m.mcp_name}: ${data.reason}`, 'error');
        } else {
            showToast(`${m.mcp_name}: ${data.error || 'Test failed'}`, 'error');
        }
    } catch (e) {
        showToast(`Test error: ${e.message}`, 'error');
    }
}

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3500);
}

function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}
