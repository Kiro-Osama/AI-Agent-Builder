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
});

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

    const payload = {
        query: query,
        preferred_model: document.getElementById('modelSelect').value || null,
        max_mcps: parseInt(document.getElementById('maxMcps').value),
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
            return `
            <div class="mcp-card">
                <div class="mcp-card-header">
                    <div class="mcp-card-title-row">
                        <span class="mcp-card-name">${escapeHtml(mcp.mcp_name)}</span>
                        <span class="mcp-embed-badge ${badgeClass}">${badgeLabel}</span>
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
