/* ============================================
   Agent Builder V5 - Dashboard JavaScript
   ============================================ */

const API_BASE = '/api/v1';
const FETCH_TIMEOUT_MS = 30000;
let currentTaskId = null;
let pollInterval = null;

/** Avoid hung UI when API/proxy is slow or unreachable */
async function fetchWithTimeout(url, options = {}, timeoutMs = FETCH_TIMEOUT_MS) {
    const ctrl = new AbortController();
    const id = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
        return await fetch(url, { ...options, signal: ctrl.signal });
    } finally {
        clearTimeout(id);
    }
}

// -----------------------------------------------
// Initialization
// -----------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    checkAPIHealth();
    loadMCPs();
    loadSkills();
    loadEmbeddingStatus();
    setupCharCounter();
    const lp = document.getElementById('llmProviderSelect');
    if (lp) {
        lp.addEventListener('change', syncAiProviderUi);
        syncAiProviderUi();
    }
    const mlp = document.getElementById('manualLlmProvider');
    if (mlp) {
        mlp.addEventListener('change', syncManualProviderUi);
        syncManualProviderUi();
    }
    const wflp = document.getElementById('wfLlmProvider');
    if (wflp) {
        wflp.addEventListener('change', syncWfProviderUi);
        syncWfProviderUi();
    }
});

function syncAiProviderUi() {
    const prov = document.getElementById('llmProviderSelect');
    const grp = document.getElementById('aiModelGroup');
    if (!prov || !grp) return;
    const ollama = prov.value === 'ollama' || prov.value === 'ollama_remote';
    const sel = grp.querySelector('select');
    if (sel) sel.disabled = ollama;
    grp.style.opacity = ollama ? '0.5' : '1';
}

function syncManualProviderUi() {
    const prov = document.getElementById('manualLlmProvider');
    const grp = document.getElementById('manualModelGroup');
    if (!prov || !grp) return;
    const ollama = prov.value === 'ollama' || prov.value === 'ollama_remote';
    const sel = grp.querySelector('select');
    if (sel) sel.disabled = ollama;
    grp.style.opacity = ollama ? '0.5' : '1';
}

function syncWfProviderUi() {
    const prov = document.getElementById('wfLlmProvider');
    const grp = document.getElementById('wfModelGroup');
    if (!prov || !grp) return;
    const ollama = prov.value === 'ollama' || prov.value === 'ollama_remote';
    const sel = grp.querySelector('select');
    if (sel) sel.disabled = ollama;
    grp.style.opacity = ollama ? '0.5' : '1';
}

function setupCharCounter() {
    const textarea = document.getElementById('queryInput');
    const counter = document.getElementById('charCount');
    textarea.addEventListener('input', () => {
        counter.textContent = textarea.value.length;
    });
}

// -----------------------------------------------
// API Health Check
// -----------------------------------------------
async function checkAPIHealth() {
    const statusEl = document.getElementById('apiStatus');
    const dot = statusEl.querySelector('.status-dot');
    const text = statusEl.querySelector('span:last-child');

    try {
        const res = await fetch('/health');
        if (res.ok) {
            dot.classList.add('online');
            dot.classList.remove('offline');
            text.textContent = 'API Online';
        } else {
            throw new Error('API not healthy');
        }
    } catch (e) {
        dot.classList.add('offline');
        dot.classList.remove('online');
        text.textContent = 'API Offline';
    }
}

// -----------------------------------------------
// Submit Build
// -----------------------------------------------
async function submitBuild() {
    const query = document.getElementById('queryInput').value.trim();
    if (!query || query.length < 5) {
        showToast('Please enter a task description (min 5 characters)', 'error');
        return;
    }

    const btn = document.getElementById('buildBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span><span>Submitting...</span>';

    const provEl = document.getElementById('llmProviderSelect');
    const llmProv = provEl ? provEl.value : 'openrouter';
    const useOllama = llmProv === 'ollama' || llmProv === 'ollama_remote';
    const payload = {
        query: query,
        llm_provider: llmProv,
        preferred_model: useOllama ? null : (document.getElementById('modelSelect').value || null),
        max_mcps: parseInt(document.getElementById('maxMcps').value, 10),
        max_skills: parseInt(document.getElementById('maxSkills').value, 10),
        enable_skill_creation: document.getElementById('enableSkills').checked,
    };

    try {
        const res = await fetch(`${API_BASE}/build`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Build request failed');
        }

        const data = await res.json();
        currentTaskId = data.task_id;

        showToast('Build submitted successfully!', 'success');
        showPipelineSection(currentTaskId);
        startPolling(currentTaskId);

    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">⚡</span><span>Build Agent</span>';
    }
}

// -----------------------------------------------
// Pipeline Polling
// -----------------------------------------------
function showPipelineSection(taskId) {
    document.getElementById('pipelineSection').classList.remove('hidden');
    document.getElementById('resultSection').classList.add('hidden');
    document.getElementById('taskIdDisplay').textContent = `Task: ${taskId}`;

    document.querySelectorAll('.node').forEach(n => {
        n.classList.remove('active', 'completed');
    });
    document.querySelectorAll('.node-details').forEach(el => { el.innerHTML = ''; });

    document.getElementById('progressBar').style.width = '0%';
    document.getElementById('progressLabel').textContent = '0%';
}

function startPolling(taskId) {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(() => pollStatus(taskId), 2000);
}

async function pollStatus(taskId) {
    try {
        const res = await fetch(`${API_BASE}/status/${taskId}`);
        if (!res.ok) return;

        const data = await res.json();
        updatePipelineUI(data);

        if (data.status === 'completed' || data.status === 'failed') {
            clearInterval(pollInterval);
            pollInterval = null;

            if (data.status === 'completed' && data.result_template) {
                showResult(data.result_template);
            } else if (data.status === 'failed') {
                showToast('Pipeline failed. Check logs for details.', 'error');
            }
        }
    } catch (e) {
        console.error('Poll error:', e);
    }
}

function updatePipelineUI(data) {
    const progress = Math.round(data.progress * 100);
    document.getElementById('progressBar').style.width = `${progress}%`;
    document.getElementById('progressLabel').textContent = `${progress}%`;

    const nodeOrder = [
        'query_analyzer', 'similarity_retriever', 'needs_assessment',
        'skill_creator', 'sandbox_validator', 'ai_final_filter',
        'docker_mcp_runner', 'template_builder', 'final_output',
    ];

    const currentIdx = nodeOrder.indexOf(data.current_node);

    document.querySelectorAll('.node').forEach((nodeEl) => {
        const nodeName = nodeEl.dataset.node;
        const nodeIdx = nodeOrder.indexOf(nodeName);

        nodeEl.classList.remove('active', 'completed');

        if (nodeIdx < currentIdx) {
            nodeEl.classList.add('completed');
        } else if (nodeIdx === currentIdx) {
            if (data.status === 'completed') {
                nodeEl.classList.add('completed');
            } else {
                nodeEl.classList.add('active');
            }
        }
    });

    renderNodeDetails(data.processing_log || []);
}

function renderNodeDetails(logs) {
    for (const entry of logs) {
        if (!entry.details || entry.node === 'pipeline') continue;
        const el = document.getElementById(`details-${entry.node}`);
        if (!el) continue;

        const d = entry.details;
        let html = '';

        switch (entry.node) {
            case 'query_analyzer':
                if (d.sub_queries && d.sub_queries.length) {
                    html = `<div class="detail-label">${escapeHtml(d.summary)}</div>` +
                        d.sub_queries.map(q => `<span class="detail-tag query-tag">${escapeHtml(q)}</span>`).join('');
                }
                break;

            case 'similarity_retriever':
                html = `<div class="detail-label">${escapeHtml(d.summary)}</div>`;
                if (d.mcps_found && d.mcps_found.length) {
                    html += '<div class="detail-group"><span class="detail-group-title">MCPs:</span>' +
                        d.mcps_found.map(m =>
                            `<span class="detail-tag mcp-tag">${escapeHtml(m.name)} <small>${(m.similarity * 100).toFixed(0)}%</small></span>`
                        ).join('') + '</div>';
                }
                if (d.skills_found && d.skills_found.length) {
                    html += '<div class="detail-group"><span class="detail-group-title">Skills:</span>' +
                        d.skills_found.map(s =>
                            `<span class="detail-tag skill-tag">${escapeHtml(s.name || s.id)} <small>${(s.similarity * 100).toFixed(0)}%</small></span>`
                        ).join('') + '</div>';
                }
                break;

            case 'needs_assessment':
                html = `<div class="detail-label">${escapeHtml(d.summary)}</div>`;
                if (d.action === 'create_skill' && d.missing_capabilities && d.missing_capabilities.length) {
                    html += '<div class="detail-group"><span class="detail-group-title">Missing:</span>' +
                        d.missing_capabilities.map(c =>
                            `<span class="detail-tag missing-tag">${escapeHtml(c)}</span>`
                        ).join('') + '</div>';
                }
                break;

            case 'skill_creator':
                html = `<div class="detail-label">${escapeHtml(d.summary)}</div>`;
                if (d.created_skills && d.created_skills.length) {
                    html += d.created_skills.map(s =>
                        `<div class="detail-created-skill">
                            <strong>${escapeHtml(s.name)}</strong>
                            <span class="detail-skill-desc">${escapeHtml(s.description)}</span>
                        </div>`
                    ).join('');
                }
                break;

            case 'sandbox_validator':
                html = `<div class="detail-label">${escapeHtml(d.summary)}</div>`;
                break;

            case 'ai_final_filter':
                html = `<div class="detail-label">${escapeHtml(d.summary)}</div>`;
                if (d.selected_mcps && d.selected_mcps.length) {
                    html += '<div class="detail-group"><span class="detail-group-title">MCPs:</span>' +
                        d.selected_mcps.map(n => `<span class="detail-tag mcp-tag selected">${escapeHtml(n)}</span>`).join('') + '</div>';
                }
                if (d.selected_skills && d.selected_skills.length) {
                    html += '<div class="detail-group"><span class="detail-group-title">Skills:</span>' +
                        d.selected_skills.map(n => `<span class="detail-tag skill-tag selected">${escapeHtml(n)}</span>`).join('') + '</div>';
                }
                break;

            case 'docker_mcp_runner':
                html = `<div class="detail-label">${escapeHtml(d.summary)}</div>`;
                if (d.mcps && d.mcps.length) {
                    html += d.mcps.map(m =>
                        `<div class="detail-docker-item">
                            <span class="detail-tag mcp-tag">${escapeHtml(m.name)}</span>
                            <code>${escapeHtml(m.image)}</code>
                        </div>`
                    ).join('');
                }
                break;

            case 'template_builder':
                html = `<div class="detail-label">${escapeHtml(d.summary)}</div>`;
                if (d.agent_name && d.agent_name !== '?') {
                    html += `<div class="detail-agent-item">
                        <strong>${escapeHtml(d.agent_name)}</strong>
                        <code>${escapeHtml(d.model || '?')}</code>
                        <small>${d.mcps_count || 0} MCPs · ${d.skills_count || 0} skills</small>
                    </div>`;
                }
                if (d.has_warning) html += '<div class="detail-warning">Built with fallback template</div>';
                break;

            case 'final_output':
                html = `<div class="detail-label">${escapeHtml(d.summary)}</div>`;
                break;
        }

        if (html) el.innerHTML = html;
    }
}

// -----------------------------------------------
// Show Result
// -----------------------------------------------
function showResult(template) {
    document.getElementById('resultSection').classList.remove('hidden');
    document.getElementById('templateOutput').textContent = JSON.stringify(template, null, 2);
    showToast('🎉 Agent template ready!', 'success');
}

function copyTemplate() {
    const text = document.getElementById('templateOutput').textContent;
    navigator.clipboard.writeText(text).then(() => {
        showToast('Template copied to clipboard!', 'success');
    });
}

function newBuild() {
    currentTaskId = null;
    document.getElementById('pipelineSection').classList.add('hidden');
    document.getElementById('resultSection').classList.add('hidden');
    document.getElementById('queryInput').value = '';
    document.getElementById('charCount').textContent = '0';
    document.getElementById('queryInput').focus();
}

function chatWithAgent() {
    if (currentTaskId) {
        window.open(`/chat.html?task_id=${currentTaskId}`, '_blank');
    } else {
        showToast('No agent to chat with', 'error');
    }
}

// -----------------------------------------------
// Embedding catalog status & run
// -----------------------------------------------
async function loadEmbeddingStatus() {
    const pill = document.getElementById('embedStatusPill');
    const dot = document.getElementById('embedStatusDot');
    const text = document.getElementById('embedStatusText');
    const summary = document.getElementById('embedSummaryLine');
    if (!pill || !text) return;

    try {
        const res = await fetch(`${API_BASE}/embeddings/status`);
        if (!res.ok) throw new Error('Could not load embedding status');

        const data = await res.json();

        const gemini = data.gemini_api_configured;
        const mc = data.mcps || {};
        const sk = data.skills || {};
        const mOk = `${mc.with_embedding || 0}/${mc.total_active || 0}`;
        const sOk = `${sk.with_embedding || 0}/${sk.total_with_description || 0}`;
        const mTot = mc.total_active || 0;
        const sDesc = sk.total_with_description || 0;

        if (!gemini) {
            dot.className = 'embed-status-dot neutral';
            text.textContent = 'Gemini API key not set';
        } else if (mTot === 0 && sDesc === 0) {
            dot.className = 'embed-status-dot neutral';
            text.textContent = 'No MCPs or skills to index';
        } else if (data.catalog_complete) {
            dot.className = 'embed-status-dot complete';
            text.textContent = `Complete · MCPs ${mOk} · Skills ${sOk}`;
        } else {
            dot.className = 'embed-status-dot incomplete';
            text.textContent = `Incomplete · MCPs ${mOk} · Skills ${sOk}`;
        }

        if (summary) {
            const missM = mc.without_embedding || 0;
            const missS = sk.without_embedding || 0;
            summary.textContent =
                `Active MCPs: ${mc.total_active || 0} — embedded: ${mc.with_embedding || 0}` +
                (missM ? ` (${missM} missing)` : '') +
                ` · Skills (with description): ${sk.total_with_description || 0} — embedded: ${sk.with_embedding || 0}` +
                (missS ? ` (${missS} missing)` : '') +
                (!gemini ? ' · Add GEMINI_API_KEY to .env' : '');
        }
    } catch (e) {
        dot.className = 'embed-status-dot incomplete';
        text.textContent = 'Status unavailable';
        if (summary) summary.textContent = e.message || '';
    }
}

async function runEmbeddings() {
    const btn = document.getElementById('embedRunBtn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Generating…';
    }

    try {
        const res = await fetch(
            `${API_BASE}/embeddings/run?only_missing=true&include_mcps=true&include_skills=true`,
            { method: 'POST' }
        );
        const data = await res.json().catch(() => ({}));

        if (!res.ok) {
            const msg = data.detail || data.message || 'Request failed';
            throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }

        const em = data.embedded_mcps ?? 0;
        const es = data.embedded_skills ?? 0;
        const errN = (data.errors || []).length;

        showToast(
            `Embeddings updated: +${em} MCPs, +${es} skills` + (errN ? ` · ${errN} error(s)` : ''),
            errN ? 'error' : 'success'
        );

        await loadEmbeddingStatus();
        await loadMCPs();
    } catch (e) {
        showToast(`Embeddings: ${e.message}`, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Generate embeddings';
        }
    }
}

// -----------------------------------------------
// Load MCPs
// -----------------------------------------------
async function loadMCPs() {
    const grid = document.getElementById('mcpsGrid');

    try {
        const res = await fetch(`${API_BASE}/mcps`);
        if (!res.ok) throw new Error('Failed to load MCPs');

        const data = await res.json();
        const mcps = data.mcps || [];

        if (mcps.length === 0) {
            grid.innerHTML = '<div class="loading-placeholder">No MCPs found. Run Alembic migrations (002_seed_mcps) and ensure the API has started.</div>';
            return;
        }

        grid.innerHTML = mcps.map(mcp => {
            const emb = mcp.has_embedding === true;
            const badgeClass = emb ? 'ok' : 'missing';
            const badgeLabel = emb ? 'Embedded' : 'No embedding';
            const configBadge = mcp.requires_user_config
                ? '<span class="mcp-embed-badge missing" style="font-size:0.6rem;">needs config</span>'
                : '<span class="mcp-embed-badge ok" style="font-size:0.6rem;">shared</span>';
            return `
            <div class="mcp-card">
                <div class="mcp-card-header">
                    <div class="mcp-card-title-row">
                        <span class="mcp-card-name">${escapeHtml(mcp.mcp_name)}</span>
                        <span class="mcp-embed-badge ${badgeClass}">${badgeLabel}</span>
                        ${configBadge}
                    </div>
                    ${mcp.category ? `<span class="mcp-card-category">${escapeHtml(mcp.category)}</span>` : ''}
                </div>
                <div class="mcp-card-desc">${escapeHtml(truncate(mcp.description, 120))}</div>
                <div class="mcp-card-tools">
                    ${(mcp.tools_provided || []).map(t =>
                        `<span class="tool-tag">${escapeHtml(t.name)}</span>`
                    ).join('')}
                </div>
            </div>
        `;
        }).join('');

    } catch (e) {
        grid.innerHTML = `<div class="loading-placeholder">⚠️ Could not load MCPs: ${e.message}</div>`;
    }
}

// -----------------------------------------------
// Load & Seed Skills
// -----------------------------------------------
async function loadSkills() {
    const grid = document.getElementById('skillsGrid');
    const summary = document.getElementById('skillsSummary');
    if (!grid) return;

    grid.innerHTML = '<div class="loading-placeholder">Fetching skills…</div>';

    try {
        const res = await fetchWithTimeout(`${API_BASE}/skills`);
        if (!res.ok) throw new Error('Failed to load skills');

        const data = await res.json();
        const skills = data.skills || [];

        if (summary) {
            const total = skills.length;
            const embedded = skills.filter(s => s.has_embedding).length;
            const cats = data.categories || [];
            summary.textContent = total === 0
                ? 'No skills in database. Click "Seed Skills from Disk" to import.'
                : `${total} skill${total !== 1 ? 's' : ''} · ${embedded} embedded · Categories: ${cats.join(', ') || 'none'}`;
        }

        if (skills.length === 0) {
            grid.innerHTML = '<div class="loading-placeholder">No skills found. Seed them from disk using the button above.</div>';
            return;
        }

        grid.innerHTML = skills.map(skill => {
            const emb = skill.has_embedding === true;
            const embClass = emb ? 'ok' : 'missing';
            const embLabel = emb ? 'Embedded' : 'No embedding';
            const srcBadge = skill.source === 'seeded'
                ? '<span class="skill-source-badge seeded">seeded</span>'
                : skill.source === 'pipeline'
                    ? '<span class="skill-source-badge pipeline">pipeline</span>'
                    : '';
            const catBadge = skill.category
                ? `<span class="skill-category-badge">${escapeHtml(skill.category)}</span>`
                : '';

            return `
            <div class="skill-card">
                <div class="skill-card-header">
                    <span class="skill-card-name">${escapeHtml(skill.skill_name || skill.skill_id)}</span>
                    <div class="skill-badges">
                        ${catBadge}
                        ${srcBadge}
                        <span class="mcp-embed-badge ${embClass}">${embLabel}</span>
                    </div>
                </div>
                <div class="skill-card-desc">${escapeHtml(truncate(skill.description, 150))}</div>
                <div class="skill-card-meta">
                    <span class="skill-status ${skill.status}">${escapeHtml(skill.status)}</span>
                </div>
            </div>
            `;
        }).join('');

    } catch (e) {
        const msg = e.name === 'AbortError' ? `Request timed out after ${FETCH_TIMEOUT_MS / 1000}s (check API on port 8000 or nginx proxy).` : e.message;
        grid.innerHTML = `<div class="loading-placeholder">Could not load skills: ${escapeHtml(msg)}</div>`;
    }
}

async function seedSkills() {
    const btn = document.getElementById('seedSkillsBtn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span class="btn-seed-icon">⏳</span> Seeding…';
    }

    try {
        const res = await fetchWithTimeout(`${API_BASE}/skills/seed`, { method: 'POST' }, 120000);
        const data = await res.json().catch(() => ({}));

        if (!res.ok) {
            const msg = data.detail || 'Seed request failed';
            throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }

        const ins = data.inserted ?? 0;
        const upd = data.updated ?? 0;
        const embQueued = data.embeddings?.status === 'queued';
        const emb = data.embeddings?.embedded_skills ?? 0;
        const errN = (data.embeddings?.errors || []).length;

        showToast(
            embQueued
                ? `Skills seeded: +${ins} new, ${upd} updated. Embeddings running in background — refresh in a minute or use Generate embeddings.`
                : `Skills seeded: +${ins} new, ${upd} updated, ${emb} embedded` + (errN ? ` · ${errN} error(s)` : ''),
            errN ? 'error' : 'success'
        );

        await loadSkills();
        await loadEmbeddingStatus();
    } catch (e) {
        showToast(`Seed failed: ${e.message}`, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<span class="btn-seed-icon">🌱</span> Seed Skills from Disk';
        }
    }
}

// -----------------------------------------------
// Build Tab Switching
// -----------------------------------------------
function switchBuildTab(tab) {
    document.getElementById('tabAI').classList.toggle('active', tab === 'ai');
    document.getElementById('tabManual').classList.toggle('active', tab === 'manual');
    document.getElementById('tabWorkflow').classList.toggle('active', tab === 'workflow');
    document.getElementById('aiBuildContent').classList.toggle('hidden', tab !== 'ai');
    document.getElementById('manualBuildContent').classList.toggle('hidden', tab !== 'manual');
    document.getElementById('workflowBuildContent').classList.toggle('hidden', tab !== 'workflow');
    if (tab === 'manual') {
        populateManualPickers();
    }
}

// -----------------------------------------------
// Manual Build
// -----------------------------------------------
let _allMCPsCache = [];
let _allSkillsCache = [];

async function populateManualPickers() {
    try {
        const [mcpRes, skillRes] = await Promise.all([
            fetch(`${API_BASE}/mcps`),
            fetch(`${API_BASE}/skills`),
        ]);
        if (mcpRes.ok) {
            const d = await mcpRes.json();
            _allMCPsCache = d.mcps || [];
        }
        if (skillRes.ok) {
            const d = await skillRes.json();
            _allSkillsCache = d.skills || [];
        }
    } catch (e) {
        console.error('Failed to populate pickers:', e);
    }
    renderManualMCPs(_allMCPsCache);
    renderManualSkills(_allSkillsCache);
}

function renderManualMCPs(mcps) {
    const list = document.getElementById('manualMCPList');
    if (!list) return;
    if (mcps.length === 0) {
        list.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:0.82rem;">No MCPs available</div>';
        return;
    }
    list.innerHTML = mcps.map(m => {
        const configTag = m.requires_user_config ? '<span class="badge-config">needs config</span>' : '';
        return `<label class="picker-item">
            <input type="checkbox" value="${m.id}" data-name="${escapeHtml(m.mcp_name)}">
            <span class="picker-item-name">${escapeHtml(m.mcp_name)}</span>
            ${configTag}
            <span class="picker-item-meta">${escapeHtml(m.category || '')}</span>
        </label>`;
    }).join('');
}

function renderManualSkills(skills) {
    const list = document.getElementById('manualSkillList');
    if (!list) return;
    if (skills.length === 0) {
        list.innerHTML = '<div style="padding:12px;color:var(--text-muted);font-size:0.82rem;">No skills available</div>';
        return;
    }
    list.innerHTML = skills.map(s => {
        return `<label class="picker-item">
            <input type="checkbox" value="${escapeHtml(s.skill_id)}">
            <span class="picker-item-name">${escapeHtml(s.skill_name || s.skill_id)}</span>
            <span class="picker-item-meta">${escapeHtml(s.category || '')}</span>
        </label>`;
    }).join('');
}

function filterManualMCPs() {
    const q = (document.getElementById('mcpSearchManual').value || '').toLowerCase();
    const filtered = q ? _allMCPsCache.filter(m =>
        m.mcp_name.toLowerCase().includes(q) || (m.description || '').toLowerCase().includes(q)
    ) : _allMCPsCache;
    renderManualMCPs(filtered);
}

function filterManualSkills() {
    const q = (document.getElementById('skillSearchManual').value || '').toLowerCase();
    const filtered = q ? _allSkillsCache.filter(s =>
        (s.skill_name || '').toLowerCase().includes(q) || (s.skill_id || '').toLowerCase().includes(q)
    ) : _allSkillsCache;
    renderManualSkills(filtered);
}

async function submitManualBuild() {
    const agentName = document.getElementById('manualAgentName').value.trim() || 'Custom_Agent';
    const systemPrompt = document.getElementById('manualSystemPrompt').value.trim();
    const model = document.getElementById('manualModel').value;

    const mcpCheckboxes = document.querySelectorAll('#manualMCPList input[type="checkbox"]:checked');
    const skillCheckboxes = document.querySelectorAll('#manualSkillList input[type="checkbox"]:checked');

    const selectedMcpIds = Array.from(mcpCheckboxes).map(cb => parseInt(cb.value));
    const selectedSkillIds = Array.from(skillCheckboxes).map(cb => cb.value);

    if (selectedMcpIds.length === 0 && selectedSkillIds.length === 0) {
        showToast('Select at least one MCP or skill', 'error');
        return;
    }

    const btn = document.getElementById('manualBuildBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span><span>Building...</span>';

    try {
        const res = await fetch(`${API_BASE}/build/manual`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                agent_name: agentName,
                system_prompt: systemPrompt || 'You are a helpful AI assistant.',
                selected_mcp_ids: selectedMcpIds,
                selected_skill_ids: selectedSkillIds,
                model: model,
                llm_provider: (document.getElementById('manualLlmProvider') || { value: 'openrouter' }).value,
            }),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Manual build failed');
        }

        const data = await res.json();
        currentTaskId = data.task_id;
        showToast(`Agent "${agentName}" built! ${data.mcps_count} MCPs, ${data.skills_count} skills`, 'success');
        showResult(data.template);
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">🔧</span><span>Build Agent (Manual)</span>';
    }
}

// -----------------------------------------------
// Utilities
// -----------------------------------------------
function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

function truncate(str, len) {
    if (!str) return '';
    return str.length > len ? str.substring(0, len) + '...' : str;
}

// -----------------------------------------------
// Workflow Build
// -----------------------------------------------
let currentWorkflowId = null;
let wfPollInterval = null;

async function submitWorkflowBuild() {
    const query = document.getElementById('wfQueryInput').value.trim();
    if (!query || query.length < 10) {
        showToast('Please enter a detailed task description (min 10 characters)', 'error');
        return;
    }

    const btn = document.getElementById('wfBuildBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span><span>Submitting...</span>';

    const wfProvEl = document.getElementById('wfLlmProvider');
    const wfLlmProv = wfProvEl ? wfProvEl.value : 'openrouter';
    const wfOllama = wfLlmProv === 'ollama' || wfLlmProv === 'ollama_remote';
    const awaitChk = document.getElementById('wfAwaitPlanApproval');
    const wfMcpsEl = document.getElementById('wfSubBuildMaxMcps');
    const wfSkillsEl = document.getElementById('wfSubBuildMaxSkills');
    const payload = {
        query: query,
        topology_hint: document.getElementById('wfTopology').value || 'auto',
        llm_provider: wfLlmProv,
        preferred_model: wfOllama ? null : (document.getElementById('wfModel').value || null),
        await_plan_approval: !!(awaitChk && awaitChk.checked),
        sub_build_max_mcps: wfMcpsEl ? parseInt(wfMcpsEl.value, 10) : 3,
        sub_build_max_skills: wfSkillsEl ? parseInt(wfSkillsEl.value, 10) : 8,
    };

    try {
        const res = await fetch(`${API_BASE}/workflow/build`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Workflow build failed');
        }

        const data = await res.json();
        currentWorkflowId = data.workflow_id;

        showToast('Workflow build submitted!', 'success');
        showWorkflowPipeline(currentWorkflowId);
        startWorkflowPolling(currentWorkflowId);

    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">🔀</span><span>Build Workflow</span>';
    }
}

function showWorkflowPipeline(wfId) {
    document.getElementById('wfPipelineSection').classList.remove('hidden');
    document.getElementById('wfResultSection').classList.add('hidden');
    document.getElementById('wfIdDisplay').textContent = `Workflow: ${wfId}`;
    document.getElementById('wfAgentsProgress').innerHTML = '<div class="loading-placeholder">Planning workflow...</div>';
    document.getElementById('wfStatusLabel').textContent = 'Queued';
    document.getElementById('wfTopologyBadge').textContent = '';
    const planPanel = document.getElementById('wfPlanReviewPanel');
    if (planPanel) planPanel.classList.add('hidden');
    const revIn = document.getElementById('wfPlanReviseInput');
    if (revIn) revIn.value = '';
}

function startWorkflowPolling(wfId) {
    if (wfPollInterval) clearInterval(wfPollInterval);
    wfPollInterval = setInterval(() => pollWorkflowStatus(wfId), 3000);
}

async function pollWorkflowStatus(wfId) {
    try {
        const res = await fetch(`${API_BASE}/workflow/${wfId}`);
        if (!res.ok) return;

        const data = await res.json();
        updateWorkflowPipelineUI(data);

        if (
            data.status === 'ready' ||
            data.status === 'failed' ||
            data.status === 'cancelled'
        ) {
            clearInterval(wfPollInterval);
            wfPollInterval = null;

            if (data.status === 'ready') {
                showWorkflowResult(data);
            } else if (data.status === 'cancelled') {
                showToast('Workflow cancelled.', 'error');
            } else {
                showToast(`Workflow build failed: ${data.error_log || 'Unknown error'}`, 'error');
            }
        }
    } catch (e) {
        console.error('Workflow poll error:', e);
    }
}

async function submitWfPlanDecision(action) {
    if (!currentWorkflowId) {
        showToast('No workflow in progress', 'error');
        return;
    }
    const wfId = currentWorkflowId;
    const feedbackEl = document.getElementById('wfPlanReviseInput');
    const feedback = feedbackEl ? feedbackEl.value.trim() : '';

    if (action === 'revise' && !feedback) {
        showToast('Describe what to change before requesting a revised plan', 'error');
        return;
    }

    const wfProvEl = document.getElementById('wfLlmProvider');
    const wfLlmProv = wfProvEl ? wfProvEl.value : 'openrouter';
    const wfOllama = wfLlmProv === 'ollama' || wfLlmProv === 'ollama_remote';
    const payload = {
        action,
        feedback: action === 'revise' ? feedback : null,
        topology_hint: document.getElementById('wfTopology').value || 'auto',
        llm_provider: wfLlmProv,
        preferred_model: wfOllama ? null : (document.getElementById('wfModel').value || null),
    };

    const btns = ['wfPlanApproveBtn', 'wfPlanReviseBtn', 'wfPlanRejectBtn']
        .map((id) => document.getElementById(id))
        .filter(Boolean);
    btns.forEach((b) => { b.disabled = true; });

    try {
        const res = await fetch(`${API_BASE}/workflow/${wfId}/plan/decision`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Plan decision failed');
        }
        await res.json();
        if (action === 'approve') {
            showToast('Building agents…', 'success');
        } else if (action === 'revise') {
            showToast('Re-planning with your feedback…', 'success');
            if (feedbackEl) feedbackEl.value = '';
        } else {
            showToast('Workflow cancelled', 'success');
        }
        if (!wfPollInterval) startWorkflowPolling(wfId);
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    } finally {
        btns.forEach((b) => { b.disabled = false; });
    }
}

function updateWorkflowPipelineUI(data) {
    const statusLabel = document.getElementById('wfStatusLabel');
    const topoBadge = document.getElementById('wfTopologyBadge');
    const agentsDiv = document.getElementById('wfAgentsProgress');
    const planPanel = document.getElementById('wfPlanReviewPanel');
    const planReasoning = document.getElementById('wfPlanReasoning');

    const statusMap = {
        queued: 'Queued',
        planning: 'Planning...',
        awaiting_plan_approval: 'Awaiting your approval',
        building: 'Building Agents...',
        ready: 'Ready',
        failed: 'Failed',
        cancelled: 'Cancelled',
    };

    statusLabel.textContent = statusMap[data.status] || data.status;
    statusLabel.className = `wf-status-label wf-status-${data.status}`;

    if (data.topology) {
        topoBadge.textContent = data.topology;
        topoBadge.className = `wf-topology-badge topo-${data.topology}`;
    }

    if (planPanel) {
        if (data.status === 'awaiting_plan_approval') {
            planPanel.classList.remove('hidden');
            if (planReasoning) {
                planReasoning.textContent = data.description || '(No planner summary)';
            }
        } else {
            planPanel.classList.add('hidden');
        }
    }

    const agentBuilds = data.agent_build_status || [];
    if (agentBuilds.length === 0 && data.status === 'planning') {
        agentsDiv.innerHTML = '<div class="loading-placeholder">AI is decomposing the task into agents...</div>';
        return;
    }

    if (agentBuilds.length === 0 && data.agents && data.agents.length) {
        const hint = data.status === 'awaiting_plan_approval'
            ? '<div class="loading-placeholder" style="margin-bottom:10px">Proposed roles below — approve or request changes above.</div>'
            : '';
        agentsDiv.innerHTML = hint + data.agents.map(a => `
            <div class="wf-agent-card">
                <div class="wf-agent-header">
                    <span class="wf-agent-role">${escapeHtml(a.role || '')}</span>
                    <span class="wf-agent-name">${escapeHtml(a.agent_name || '')}</span>
                </div>
                <div class="wf-agent-task">${escapeHtml(a.sub_task || '')}</div>
                <span class="wf-agent-status pending">${data.status === 'awaiting_plan_approval' ? 'Planned' : 'Pending'}</span>
            </div>
        `).join('');
        return;
    }

    agentsDiv.innerHTML = agentBuilds.map(ab => {
        const statusClass = ab.status === 'completed' ? 'completed' :
                           ab.status === 'failed' ? 'failed' :
                           ab.status === 'processing' ? 'active' : 'pending';
        const statusIcon = ab.status === 'completed' ? '✅' :
                          ab.status === 'failed' ? '❌' :
                          ab.status === 'processing' ? '⚙️' : '⏳';
        const nodeLabel = ab.current_node ? ` (${ab.current_node})` : '';
        return `
            <div class="wf-agent-card wf-agent-${statusClass}">
                <div class="wf-agent-header">
                    <span class="wf-agent-role">${escapeHtml(ab.role || '')}</span>
                    <span class="wf-agent-name">${escapeHtml(ab.agent_name || '')}</span>
                    <span class="wf-agent-status ${statusClass}">${statusIcon} ${escapeHtml(ab.status)}${nodeLabel}</span>
                </div>
            </div>
        `;
    }).join('');
}

function showWorkflowResult(data) {
    document.getElementById('wfResultSection').classList.remove('hidden');

    const agents = data.agents || [];
    const config = data.workflow_config || {};

    document.getElementById('wfResultDetails').innerHTML = `
        <div class="wf-result-meta">
            <div class="wf-result-meta-item">
                <span class="wf-result-meta-label">Workflow</span>
                <span class="wf-result-meta-value">${escapeHtml(data.name || data.workflow_id)}</span>
            </div>
            <div class="wf-result-meta-item">
                <span class="wf-result-meta-label">Topology</span>
                <span class="wf-topology-badge topo-${data.topology}">${escapeHtml(data.topology)}</span>
            </div>
            <div class="wf-result-meta-item">
                <span class="wf-result-meta-label">Agents</span>
                <span class="wf-result-meta-value">${agents.length}</span>
            </div>
        </div>
        <div class="wf-result-agents">
            ${agents.map((a, i) => `
                <div class="wf-result-agent-card">
                    <div class="wf-result-agent-header">
                        <span class="wf-result-agent-idx">${i + 1}</span>
                        <span class="wf-result-agent-name">${escapeHtml(a.agent_name || a.role)}</span>
                        <span class="wf-result-agent-role">${escapeHtml(a.role)}</span>
                    </div>
                    <div class="wf-result-agent-task">${escapeHtml(a.sub_task || '')}</div>
                    <div class="wf-result-agent-meta">
                        ${(a.selected_mcps || []).length} MCPs · ${(a.selected_skills || []).length} skills
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function chatWithWorkflow() {
    if (currentWorkflowId) {
        window.open(`/workflow-chat.html?workflow_id=${currentWorkflowId}`, '_blank');
    } else {
        showToast('No workflow to chat with', 'error');
    }
}
