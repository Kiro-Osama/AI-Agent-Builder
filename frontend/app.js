/* ============================================
   Agent Builder V5 - Dashboard JavaScript
   ============================================ */

const API_BASE = '/api/v1';
let currentTaskId = null;
let pollInterval = null;

// -----------------------------------------------
// Initialization
// -----------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    checkAPIHealth();
    loadMCPs();
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

    // Reset all nodes
    document.querySelectorAll('.node').forEach(n => {
        n.classList.remove('active', 'completed');
    });

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
            grid.innerHTML = '<div class="loading-placeholder">No MCPs found. Run seed migration to add sample MCPs.</div>';
            return;
        }

        grid.innerHTML = mcps.map(mcp => `
            <div class="mcp-card">
                <div class="mcp-card-header">
                    <span class="mcp-card-name">${escapeHtml(mcp.mcp_name)}</span>
                    ${mcp.category ? `<span class="mcp-card-category">${escapeHtml(mcp.category)}</span>` : ''}
                </div>
                <div class="mcp-card-desc">${escapeHtml(truncate(mcp.description, 120))}</div>
                <div class="mcp-card-tools">
                    ${(mcp.tools_provided || []).map(t =>
                        `<span class="tool-tag">${escapeHtml(t.name)}</span>`
                    ).join('')}
                </div>
            </div>
        `).join('');

    } catch (e) {
        grid.innerHTML = `<div class="loading-placeholder">⚠️ Could not load MCPs: ${e.message}</div>`;
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
