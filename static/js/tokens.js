        // LLM AI Tokens Page JavaScript
        // Manages API tokens for AI language models

        let aiTokens = [];
        let selectedTokenId = null;
        let activeTokenTab = 'info';
        let modelsCache = {}; // token_id -> fetched models
        let allowedModelsCache = []; // saved allowed models from DB
        let systemPromptEditor = null;

        function ensureSystemPromptEditor(callback) {
            if (systemPromptEditor) { if (callback) callback(); return; }
            const textarea = document.getElementById('tokenSystemPrompt');
            if (!textarea) return;
            systemPromptEditor = new EasyMDE({
                element: textarea,
                placeholder: "Optional instructions sent with every message (e.g. 'You are a helpful ERP assistant. Always respond concisely.')...",
                spellChecker: false,
                autosave: { enabled: false },
                toolbar: ['bold', 'italic', '|', 'unordered-list', 'ordered-list', '|', 'preview', 'guide'],
                status: false,
                minHeight: '100px',
            });
            if (callback) callback();
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function initializeTokens() {
            await loadTokens();
            if (aiTokens.length > 0 && !selectedTokenId) {
                selectedTokenId = aiTokens[0].id;
            }
            renderTokens();
        }

        initializeTokens();

        async function loadTokens() {
            try {
                const response = await fetch('/api/tokens');
                if (response.ok) {
                    const data = await response.json();
                    aiTokens = data.tokens || [];
                }
            } catch (error) {
                console.error('Error loading tokens:', error);
            }
        }

        function selectToken(tokenId) {
            selectedTokenId = tokenId;
            activeTokenTab = 'info';
            renderTokens();
        }

        function renderTokens() {
            const listContainer = document.getElementById('tokensList');
            const status = document.getElementById('tokenStatus');

            if (aiTokens.length === 0) {
                listContainer.innerHTML = '<div class="server-list-empty"><p>No AI tokens configured</p><p>Click "Add New Token" to get started.</p></div>';
                status.className = 'status-indicator status-disconnected';
                status.innerHTML = '<span>&#9679;</span> No tokens configured';
                renderTokenDetail();
                return;
            }

            status.className = 'status-indicator status-connected';
            status.innerHTML = `<span>&#9679;</span> ${aiTokens.length} token(s) configured`;

            listContainer.innerHTML = aiTokens.map(token => {
                const isSelected = token.id === selectedTokenId;
                const providerShort = {
                    'anthropic': 'Claude',
                    'openai': 'GPT',
                    'google': 'Gemini',
                    'mistral': 'Mistral'
                }[token.provider] || token.provider;

                return `
                    <div class="server-list-item ${isSelected ? 'selected' : ''}"
                         onclick="selectToken('${token.id}')">
                        <span class="server-status-dot enabled"></span>
                        <span class="server-list-name">${escapeHtml(token.name || 'Unnamed Token')}</span>
                        <span class="server-list-meta">${providerShort}</span>
                    </div>
                `;
            }).join('');

            renderTokenDetail();
        }

        function renderTokenDetail() {
            const panel = document.getElementById('tokenDetailPanel');
            const token = aiTokens.find(t => t.id === selectedTokenId);

            if (!token) {
                panel.innerHTML = `
                    <div class="detail-empty">
                        <div class="detail-empty-icon">🔑</div>
                        <p>Select a token from the list to view its configuration</p>
                    </div>`;
                return;
            }

            const providerDisplay = {
                'anthropic': '🟣 Anthropic (Claude)',
                'openai': '🟢 OpenAI (GPT)',
                'google': '🔵 Google (Gemini)',
                'mistral': '🟠 Mistral'
            }[token.provider] || '⚪ ' + token.provider;

            panel.innerHTML = `
                <div class="detail-header">
                    <div class="detail-header-left">
                        <h2>${escapeHtml(token.name || 'Unnamed Token')}</h2>
                    </div>
                    <div class="detail-header-actions">
                        <button class="btn-icon" onclick="editToken('${token.id}')" title="Edit Token">✏️</button>
                        <button class="btn-icon" onclick="checkTokenCredit('${token.id}')" title="Check Credit">💳</button>
                        <button class="btn-icon danger" onclick="deleteToken('${token.id}')" title="Delete Token">🗑️</button>
                    </div>
                </div>

                <div class="detail-tabs">
                    <button class="detail-tab ${activeTokenTab === 'info' ? 'active' : ''}" onclick="switchTokenTab('info')">ℹ️ Info</button>
                    <button class="detail-tab ${activeTokenTab === 'models' ? 'active' : ''}" onclick="switchTokenTab('models')">🤖 Models</button>
                    <button class="detail-tab ${activeTokenTab === 'usage' ? 'active' : ''}" onclick="switchTokenTab('usage')">📊 Usage</button>
                </div>

                <div id="tabInfo" class="detail-tab-content ${activeTokenTab === 'info' ? 'active' : ''}"></div>
                <div id="tabModels" class="detail-tab-content ${activeTokenTab === 'models' ? 'active' : ''}"></div>
                <div id="tabUsage" class="detail-tab-content ${activeTokenTab === 'usage' ? 'active' : ''}"></div>
            `;

            renderInfoTab(token, providerDisplay);
            if (activeTokenTab === 'models') renderModelsTab(token);
            if (activeTokenTab === 'usage') renderTokenUsageTab(token);
        }

        function switchTokenTab(tab) {
            activeTokenTab = tab;
            document.querySelectorAll('.detail-tab').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.detail-tab-content').forEach(el => el.classList.remove('active'));

            const tabMap = { 'info': 'tabInfo', 'models': 'tabModels', 'usage': 'tabUsage' };
            const tabLabelMap = { 'info': 'Info', 'models': 'Models', 'usage': 'Usage' };
            const activeBtn = [...document.querySelectorAll('.detail-tab')].find(btn => btn.textContent.includes(tabLabelMap[tab]));
            if (activeBtn) activeBtn.classList.add('active');

            const content = document.getElementById(tabMap[tab]);
            if (content) content.classList.add('active');

            const token = aiTokens.find(t => t.id === selectedTokenId);
            if (tab === 'models' && token) renderModelsTab(token);
            if (tab === 'usage' && token) renderTokenUsageTab(token);
        }

        function renderInfoTab(token, providerDisplay) {
            const container = document.getElementById('tabInfo');
            if (!container) return;

            const maskedKey = token.key_preview || '••••••••';
            const createdDate = token.created_at ? new Date(token.created_at).toLocaleDateString() : 'Unknown';

            container.innerHTML = `
                <div class="detail-section">
                    <label class="config-label">Provider</label>
                    <div style="font-size: 14px; font-weight: 500; padding: 8px 0;">${providerDisplay}</div>
                </div>
                <div class="detail-section">
                    <label class="config-label">API Key</label>
                    <div style="font-size: 14px; font-family: monospace; color: #767676; padding: 8px 0;">${maskedKey}</div>
                </div>
                ${token.notes ? `
                <div class="detail-section">
                    <label class="config-label">Notes</label>
                    <div style="font-size: 13px; color: #767676; padding: 8px 0;">${escapeHtml(token.notes)}</div>
                </div>` : ''}
                <div class="detail-section">
                    <label class="config-label">System Prompt (Baseline)</label>
                    ${token.system_prompt ? `
                    <div style="font-size: 13px; color: #313131; padding: 10px 12px; background: #F4F4F4; border-radius: 6px; white-space: pre-wrap; line-height: 1.6; border-left: 3px solid #3533FF;">${escapeHtml(token.system_prompt)}</div>` : `
                    <div style="font-size: 13px; color: #929395; padding: 8px 0; font-style: italic;">None — click ✏️ Edit to add one</div>`}
                </div>
                <div class="detail-section">
                    <label class="config-label">Added</label>
                    <div style="font-size: 13px; color: #767676; padding: 8px 0;">${createdDate}</div>
                </div>
            `;
        }

        // ── Models Tab ────────────────────────────────────────────────────

        async function renderModelsTab(token) {
            const container = document.getElementById('tabModels');
            if (!container) return;

            container.innerHTML = '<div style="text-align: center; padding: 30px; color: #929395;">Loading models...</div>';

            try {
                const allowedResp = await fetch('/api/models');
                const allowedData = await allowedResp.json();
                allowedModelsCache = allowedData.models || [];

                const tokenAllowed = allowedModelsCache.filter(m => m.token_id === token.id);
                const cachedModels = modelsCache[token.id];

                let html = `
                    <div class="models-token-section" id="models-section-${token.id}">
                        <div class="models-token-header">
                            <div style="display: flex; align-items: center; gap: 10px;">
                                <h4>${escapeHtml(token.name)}</h4>
                                <span class="provider-badge ${token.provider}">${token.provider}</span>
                            </div>
                            <div style="display: flex; gap: 8px; align-items: center;">
                                ${tokenAllowed.length > 0 ? `<span style="font-size: 11px; color: #929395;">${tokenAllowed.filter(m => m.enabled).length} enabled</span>` : ''}
                                <button class="models-fetch-btn" onclick="fetchModelsForToken('${token.id}')" id="fetchBtn-${token.id}">
                                    ${cachedModels ? '🔄 Refresh' : '📥 Fetch Models'}
                                </button>
                            </div>
                        </div>
                        ${cachedModels ? `
                        <div class="models-search-box">
                            <input type="text" class="models-search-input" id="modelsSearch-${token.id}"
                                   placeholder="🔍 Filter models..." oninput="filterModels('${token.id}', this.value)">
                            <span class="models-search-count" id="modelsCount-${token.id}">${cachedModels.length} models</span>
                        </div>` : ''}
                        <div class="models-list" id="models-list-${token.id}">
                            ${renderModelsList(token.id, cachedModels, tokenAllowed)}
                        </div>
                        ${cachedModels ? `
                        <div class="models-actions">
                            <button class="models-save-btn" onclick="saveModelsForToken('${token.id}')">💾 Save Selection</button>
                            <div class="models-select-actions">
                                <button onclick="selectAllModels('${token.id}', true)">Select All</button>
                                <button onclick="selectAllModels('${token.id}', false)">Deselect All</button>
                            </div>
                        </div>` : ''}
                    </div>
                `;
                container.innerHTML = html;
            } catch (error) {
                console.error('Error loading models tab:', error);
                container.innerHTML = `<div style="color: #CC4820; padding: 20px;">Error loading models: ${error.message}</div>`;
            }
        }

        function renderModelsList(tokenId, fetchedModels, allowedModels) {
            if (!fetchedModels) {
                if (allowedModels && allowedModels.length > 0) {
                    return allowedModels.map(m => `
                        <div class="model-item">
                            <input type="checkbox" ${m.enabled ? 'checked' : ''}
                                   onchange="toggleModelEnabled(${m.id}, this.checked)"
                                   data-model-id="${escapeHtml(m.model_id)}">
                            <span class="model-name">${escapeHtml(m.display_name)}</span>
                            <span class="model-id">${escapeHtml(m.model_id)}</span>
                            ${m.context_window ? `<span class="model-context">${(m.context_window / 1000).toFixed(0)}K ctx</span>` : ''}
                            <span class="model-cost">
                                <input type="number" step="0.01" min="0" placeholder="In"
                                       value="${m.input_price != null ? m.input_price : ''}"
                                       data-cost-field="input"
                                       data-model-db-id="${m.id}"
                                       onchange="updateModelCost(${m.id}, 'input_price', this.value)"
                                       title="Input cost per 1M tokens" class="cost-input">
                                <input type="number" step="0.01" min="0" placeholder="Out"
                                       value="${m.output_price != null ? m.output_price : ''}"
                                       data-cost-field="output"
                                       data-model-db-id="${m.id}"
                                       onchange="updateModelCost(${m.id}, 'output_price', this.value)"
                                       title="Output cost per 1M tokens" class="cost-input">
                                <span class="cost-label">$/1M</span>
                            </span>
                        </div>
                    `).join('');
                }
                return '<div class="models-list-empty">Click "Fetch Models" to query available models from this provider.</div>';
            }

            const allowedMap = {};
            allowedModels.forEach(m => { allowedMap[m.model_id] = m; });
            const enabledSet = new Set(allowedModels.filter(m => m.enabled).map(m => m.model_id));

            return fetchedModels.map(m => {
                const existing = allowedMap[m.model_id];
                const isChecked = existing ? enabledSet.has(m.model_id) : false;
                // Use existing saved price if available, otherwise use fetched price from provider
                const inputPrice = existing && existing.input_price != null ? existing.input_price : (m.input_price != null ? m.input_price : '');
                const outputPrice = existing && existing.output_price != null ? existing.output_price : (m.output_price != null ? m.output_price : '');
                return `
                    <div class="model-item">
                        <input type="checkbox" ${isChecked ? 'checked' : ''}
                               data-token-id="${tokenId}"
                               data-model-id="${escapeHtml(m.model_id)}"
                               data-display-name="${escapeHtml(m.display_name)}"
                               data-provider="${escapeHtml(m.provider)}"
                               data-context="${m.context_window || ''}">
                        <span class="model-name">${escapeHtml(m.display_name)}</span>
                        <span class="model-id">${escapeHtml(m.model_id)}</span>
                        ${m.context_window ? `<span class="model-context">${(m.context_window / 1000).toFixed(0)}K ctx</span>` : ''}
                        <span class="model-cost">
                            <input type="number" step="0.01" min="0" placeholder="In"
                                   value="${inputPrice}"
                                   data-cost-field="input"
                                   title="Input cost per 1M tokens" class="cost-input">
                            <input type="number" step="0.01" min="0" placeholder="Out"
                                   value="${outputPrice}"
                                   data-cost-field="output"
                                   title="Output cost per 1M tokens" class="cost-input">
                            <span class="cost-label">$/1M</span>
                        </span>
                    </div>
                `;
            }).join('');
        }

        function filterModels(tokenId, query) {
            const container = document.getElementById(`models-list-${tokenId}`);
            const countEl = document.getElementById(`modelsCount-${tokenId}`);
            if (!container) return;
            const items = container.querySelectorAll('.model-item');
            const q = query.toLowerCase().trim();
            let visible = 0;
            items.forEach(item => {
                const name = (item.querySelector('.model-name')?.textContent || '').toLowerCase();
                const id = (item.querySelector('.model-id')?.textContent || '').toLowerCase();
                const match = !q || name.includes(q) || id.includes(q);
                item.style.display = match ? '' : 'none';
                if (match) visible++;
            });
            if (countEl) countEl.textContent = `${visible} of ${items.length} models`;
        }
        window.filterModels = filterModels;

        async function fetchModelsForToken(tokenId) {
            const btn = document.getElementById(`fetchBtn-${tokenId}`);
            const listContainer = document.getElementById(`models-list-${tokenId}`);
            if (btn) { btn.disabled = true; btn.textContent = '⏳ Fetching...'; }

            try {
                const resp = await fetch(`/api/tokens/${tokenId}/available-models`);
                const data = await resp.json();
                if (!resp.ok) throw new Error(data.error || 'Failed to fetch models');

                modelsCache[tokenId] = data.models || [];
                showError(`Found ${modelsCache[tokenId].length} models from ${data.provider}`, false);

                const token = aiTokens.find(t => t.id === tokenId);
                if (token) renderModelsTab(token);
            } catch (error) {
                console.error('Error fetching models:', error);
                if (listContainer) {
                    listContainer.innerHTML = `<div style="color: #CC4820; padding: 12px; font-size: 13px;">Error: ${error.message}</div>`;
                }
                if (btn) { btn.disabled = false; btn.textContent = '📥 Fetch Models'; }
            }
        }

        async function saveModelsForToken(tokenId) {
            const section = document.getElementById(`models-section-${tokenId}`);
            if (!section) return;

            const checkboxes = section.querySelectorAll('.model-item input[type="checkbox"]');
            const models = [];
            checkboxes.forEach(cb => {
                if (cb.checked) {
                    const row = cb.closest('.model-item');
                    const inputPriceEl = row ? row.querySelector('.cost-input[data-cost-field="input"]') : null;
                    const outputPriceEl = row ? row.querySelector('.cost-input[data-cost-field="output"]') : null;
                    models.push({
                        model_id: cb.dataset.modelId,
                        display_name: cb.dataset.displayName || cb.dataset.modelId,
                        provider: cb.dataset.provider || '',
                        context_window: cb.dataset.context ? parseInt(cb.dataset.context) : null,
                        input_price: inputPriceEl && inputPriceEl.value !== '' ? parseFloat(inputPriceEl.value) : null,
                        output_price: outputPriceEl && outputPriceEl.value !== '' ? parseFloat(outputPriceEl.value) : null,
                        enabled: true,
                    });
                }
            });

            try {
                await fetch(`/api/models/token/${tokenId}`, { method: 'DELETE' });
                const resp = await fetch('/api/models', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token_id: tokenId, models }),
                });
                const data = await resp.json();
                if (!resp.ok) throw new Error(data.error || 'Failed to save');

                showError(`Saved ${models.length} allowed models`, false);
                const allowedResp = await fetch('/api/models');
                const allowedData = await allowedResp.json();
                allowedModelsCache = allowedData.models || [];
            } catch (error) {
                showError(`Error saving models: ${error.message}`);
            }
        }

        function selectAllModels(tokenId, checked) {
            const section = document.getElementById(`models-section-${tokenId}`);
            if (!section) return;
            section.querySelectorAll('.model-item input[type="checkbox"]').forEach(cb => {
                cb.checked = checked;
            });
        }

        async function toggleModelEnabled(modelId, enabled) {
            try {
                const resp = await fetch(`/api/models/${modelId}/toggle`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled }),
                });
                if (!resp.ok) {
                    const data = await resp.json();
                    throw new Error(data.error || 'Failed to toggle');
                }
            } catch (error) {
                showError(`Error toggling model: ${error.message}`);
            }
        }

        async function updateModelCost(modelId, field, value) {
            try {
                const payload = {};
                payload[field] = value === '' ? null : parseFloat(value);
                const resp = await fetch(`/api/models/${modelId}/cost`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (!resp.ok) {
                    const data = await resp.json();
                    throw new Error(data.error || 'Failed to update cost');
                }
            } catch (error) {
                showError(`Error updating cost: ${error.message}`);
            }
        }

        function showAddTokenDialog() {
            document.getElementById('tokenModalTitle').textContent = 'Add New Token';
            document.getElementById('tokenEditId').value = '';
            document.getElementById('tokenName').value = '';
            document.getElementById('tokenProvider').value = '';
            document.getElementById('tokenKey').value = '';
            document.getElementById('tokenNotes').value = '';
            document.getElementById('tokenKey').required = true;
            document.getElementById('tokenSystemPrompt').value = '';
            document.getElementById('tokenModal').classList.add('visible');
            // Delay EasyMDE init so the browser paints the modal before CodeMirror measures it
            setTimeout(() => ensureSystemPromptEditor(() => systemPromptEditor.value('')), 50);
        }

        function editToken(tokenId) {
            const token = aiTokens.find(t => t.id === tokenId);
            if (!token) return;

            document.getElementById('tokenModalTitle').textContent = 'Edit Token';
            document.getElementById('tokenEditId').value = token.id;
            document.getElementById('tokenName').value = token.name || '';
            document.getElementById('tokenProvider').value = token.provider || '';
            document.getElementById('tokenKey').value = '';
            document.getElementById('tokenKey').placeholder = 'Leave blank to keep existing key';
            document.getElementById('tokenKey').required = false;
            document.getElementById('tokenNotes').value = token.notes || '';
            document.getElementById('tokenSystemPrompt').value = token.system_prompt || '';
            document.getElementById('tokenModal').classList.add('visible');
            const sp = token.system_prompt || '';
            setTimeout(() => ensureSystemPromptEditor(() => systemPromptEditor.value(sp)), 50);
        }

        function closeTokenModal() {
            document.getElementById('tokenModal').classList.remove('visible');
            document.getElementById('tokenKey').placeholder = 'sk-ant-...';
            document.getElementById('tokenKey').required = true;
        }

        async function saveToken(event) {
            event.preventDefault();

            const editId = document.getElementById('tokenEditId').value;
            const name = document.getElementById('tokenName').value.trim();
            const provider = document.getElementById('tokenProvider').value;
            const key = document.getElementById('tokenKey').value.trim();
            const notes = document.getElementById('tokenNotes').value.trim();
            const system_prompt = systemPromptEditor ? systemPromptEditor.value().trim() : document.getElementById('tokenSystemPrompt').value.trim();

            if (!name || !provider) {
                showError('Name and provider are required');
                return;
            }

            if (!editId && !key) {
                showError('API key is required for new tokens');
                return;
            }

            const payload = { name, provider, notes, system_prompt };
            if (key) payload.key = key;

            try {
                let response;
                if (editId) {
                    response = await fetch(`/api/tokens/${editId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                } else {
                    response = await fetch('/api/tokens', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                }

                if (response.ok) {
                    const result = await response.json();
                    closeTokenModal();
                    await loadTokens();
                    if (!editId && result.id) selectedTokenId = result.id;
                    renderTokens();
                    showError(editId ? 'Token updated successfully' : 'Token added successfully', false);
                } else {
                    const err = await response.json();
                    showError(err.error || 'Failed to save token');
                }
            } catch (error) {
                showError(`Error saving token: ${error.message}`);
            }
        }

        async function deleteToken(tokenId) {
            const token = aiTokens.find(t => t.id === tokenId);
            if (!confirm(`Delete token "${token?.name || tokenId}"? This cannot be undone.`)) return;

            try {
                const response = await fetch(`/api/tokens/${tokenId}`, { method: 'DELETE' });
                if (response.ok) {
                    await loadTokens();
                    renderTokens();
                    showError('Token deleted', false);
                } else {
                    const err = await response.json();
                    showError(err.error || 'Failed to delete token');
                }
            } catch (error) {
                showError(`Error deleting token: ${error.message}`);
            }
        }

        async function checkTokenCredit(tokenId) {
            const token = aiTokens.find(t => t.id === tokenId);
            if (!token) return;

            try {
                showError(`Checking credit for ${token.name}...`, false);
                const response = await fetch('/api/check-credit-by-token', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ token_id: tokenId })
                });

                const result = await response.json();
                if (response.ok) {
                    if (result.credit_status === 'exhausted') {
                        showError(`${token.name}: Credit exhausted!`);
                    } else if (result.valid) {
                        const rl = result.rate_limits || {};
                        const parts = [];
                        if (rl.requests_remaining) parts.push(`${Number(rl.requests_remaining).toLocaleString()} requests remaining`);
                        if (rl.input_tokens_remaining) parts.push(`${Number(rl.input_tokens_remaining).toLocaleString()} input tokens remaining`);
                        showError(`${token.name}: Active ✓` + (parts.length ? ' — ' + parts.join(', ') : ''), false);
                    } else {
                        showError(`${token.name}: Credit check completed`, false);
                    }
                } else {
                    showError(result.error || 'Credit check failed');
                }
            } catch (error) {
                showError(`Error checking credit: ${error.message}`);
            }
        }

        // Error display
        function showError(message, isError = true) {
            let container = document.getElementById('errorContainer');
            if (!container) {
                container = document.createElement('div');
                container.id = 'errorContainer';
                container.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999; max-width: 400px;';
                document.body.appendChild(container);
            }
            const div = document.createElement('div');
            div.style.background = isError ? '#FFF0EC' : '#D4FFE2';
            div.style.color = isError ? '#CC4820' : '#3BB366';
            div.style.padding = '12px';
            div.style.borderRadius = '6px';
            div.style.marginBottom = '8px';
            div.style.borderLeft = `3px solid ${isError ? '#FF5A26' : '#4CD97A'}`;
            div.style.fontSize = '13px';
            div.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)';
            div.textContent = message;
            container.innerHTML = '';
            container.appendChild(div);
            setTimeout(() => { div.remove(); }, 5000);
        }

        // ── Usage Tab ─────────────────────────────────────────────────────

        let tokenUsageCharts = {};

        function formatNumber(n) {
            if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
            if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
            return n.toString();
        }

        function formatCost(n) {
            if (n == null) return '—';
            if (n >= 1000) return '$' + (n / 1000).toFixed(1) + 'K';
            if (n >= 1) return '$' + n.toFixed(2);
            if (n >= 0.01) return '$' + n.toFixed(3);
            if (n > 0) return '$' + n.toFixed(4);
            return '$0.00';
        }

        async function renderTokenUsageTab(token) {
            const container = document.getElementById('tabUsage');
            if (!container) return;

            const endDate = new Date().toISOString().split('T')[0];
            const startDate = new Date(Date.now() - 30 * 86400000).toISOString().split('T')[0];

            container.innerHTML = `
                <div class="usage-filters">
                    <div class="usage-filter-group">
                        <label>Start Date</label>
                        <input type="date" id="tokenUsageStartDate" value="${startDate}">
                    </div>
                    <div class="usage-filter-group">
                        <label>End Date</label>
                        <input type="date" id="tokenUsageEndDate" value="${endDate}">
                    </div>
                    <button class="usage-refresh-btn" onclick="refreshTokenUsageCharts()">🔄 Refresh</button>
                </div>
                <div id="tokenUsageTotals" class="usage-totals"></div>
                <div class="usage-charts">
                    <div class="usage-chart-container">
                        <h4>📈 Token Usage Over Time</h4>
                        <canvas id="tokenUsageDailyChart"></canvas>
                    </div>
                    <div class="usage-chart-container">
                        <h4>� Daily Cost</h4>
                        <canvas id="tokenUsageDailyCostChart"></canvas>
                    </div>
                    <div class="usage-chart-container">
                        <h4>📊 Usage by Model</h4>
                        <canvas id="tokenUsageModelChart"></canvas>
                    </div>
                    <div class="usage-chart-container">
                        <h4>💵 Cost by Model</h4>
                        <canvas id="tokenUsageCostModelChart"></canvas>
                    </div>
                </div>
            `;

            await refreshTokenUsageCharts();
        }

        async function refreshTokenUsageCharts() {
            const startDate = document.getElementById('tokenUsageStartDate')?.value || '';
            const endDate = document.getElementById('tokenUsageEndDate')?.value || '';

            try {
                const params = new URLSearchParams();
                if (startDate) params.set('start_date', startDate);
                if (endDate) params.set('end_date', endDate);
                if (selectedTokenId) params.set('token_id', selectedTokenId);

                const resp = await fetch(`/api/usage-stats?${params}`);
                const data = await resp.json();
                if (!resp.ok) throw new Error(data.error || 'Failed to fetch stats');

                renderTokenUsageTotals(data.totals);
                renderTokenDailyChart(data.daily);
                renderTokenDailyCostChart(data.daily);
                renderTokenModelChart(data.by_model);
                renderTokenCostModelChart(data.by_model);
            } catch (error) {
                console.error('Error loading usage stats:', error);
                const totals = document.getElementById('tokenUsageTotals');
                if (totals) totals.innerHTML = `<div style="color: #CC4820; padding: 12px;">Error loading stats: ${error.message}</div>`;
            }
        }

        function renderTokenUsageTotals(totals) {
            const container = document.getElementById('tokenUsageTotals');
            if (!container) return;

            container.innerHTML = `
                <div class="usage-total-card">
                    <div class="total-value">${formatNumber(totals.total_requests)}</div>
                    <div class="total-label">API Requests</div>
                </div>
                <div class="usage-total-card">
                    <div class="total-value">${formatNumber(totals.total_sessions)}</div>
                    <div class="total-label">Sessions</div>
                </div>
                <div class="usage-total-card">
                    <div class="total-value">${formatNumber(totals.total_input)}</div>
                    <div class="total-label">Input Tokens</div>
                </div>
                <div class="usage-total-card">
                    <div class="total-value">${formatNumber(totals.total_output)}</div>
                    <div class="total-label">Output Tokens</div>
                </div>
                <div class="usage-total-card">
                    <div class="total-value">${formatNumber(totals.total_cache_read)}</div>
                    <div class="total-label">Cache Read</div>
                </div>
                <div class="usage-total-card usage-total-cost">
                    <div class="total-value">${formatCost(totals.total_cost)}</div>
                    <div class="total-label">Estimated Cost</div>
                </div>
            `;
        }

        function renderTokenDailyChart(daily) {
            const canvas = document.getElementById('tokenUsageDailyChart');
            if (!canvas) return;

            if (tokenUsageCharts.daily) tokenUsageCharts.daily.destroy();

            if (!daily || daily.length === 0) {
                canvas.parentElement.querySelector('h4').textContent = '📈 Token Usage Over Time (No data)';
                return;
            }

            const ctx = canvas.getContext('2d');
            tokenUsageCharts.daily = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: daily.map(d => d.date),
                    datasets: [
                        {
                            label: 'Input Tokens',
                            data: daily.map(d => d.input_tokens),
                            borderColor: '#3533FF',
                            backgroundColor: 'rgba(53, 51, 255, 0.1)',
                            fill: true, tension: 0.3,
                        },
                        {
                            label: 'Output Tokens',
                            data: daily.map(d => d.output_tokens),
                            borderColor: '#4CD97A',
                            backgroundColor: 'rgba(76, 217, 122, 0.1)',
                            fill: true, tension: 0.3,
                        },
                        {
                            label: 'Cache Read',
                            data: daily.map(d => d.cache_read),
                            borderColor: '#33B6FF',
                            backgroundColor: 'rgba(51, 182, 255, 0.1)',
                            fill: true, tension: 0.3,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { intersect: false, mode: 'index' },
                    scales: {
                        y: { beginAtZero: true, ticks: { callback: v => formatNumber(v) } },
                        x: { ticks: { maxTicksAutoSkip: true, maxRotation: 45 } },
                    },
                    plugins: {
                        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${formatNumber(ctx.raw)}` } },
                        legend: { position: 'top' },
                    },
                },
            });
        }

        function renderTokenDailyCostChart(daily) {
            const canvas = document.getElementById('tokenUsageDailyCostChart');
            if (!canvas) return;

            if (tokenUsageCharts.dailyCost) tokenUsageCharts.dailyCost.destroy();

            if (!daily || daily.length === 0 || !daily.some(d => d.cost > 0)) {
                canvas.parentElement.querySelector('h4').textContent = '💰 Daily Cost (No data)';
                return;
            }

            const ctx = canvas.getContext('2d');
            tokenUsageCharts.dailyCost = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: daily.map(d => d.date),
                    datasets: [
                        {
                            label: 'Estimated Cost',
                            data: daily.map(d => d.cost || 0),
                            borderColor: '#CC8800',
                            backgroundColor: 'rgba(204, 136, 0, 0.1)',
                            fill: true, tension: 0.3,
                            pointRadius: 3,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { intersect: false, mode: 'index' },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { callback: v => formatCost(v) },
                        },
                        x: { ticks: { maxTicksAutoSkip: true, maxRotation: 45 } },
                    },
                    plugins: {
                        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${formatCost(ctx.raw)}` } },
                        legend: { position: 'top' },
                    },
                },
            });
        }

        function renderTokenCostModelChart(byModel) {
            const canvas = document.getElementById('tokenUsageCostModelChart');
            if (!canvas) return;

            if (tokenUsageCharts.costModel) tokenUsageCharts.costModel.destroy();

            // Filter to models that have a cost
            const withCost = (byModel || []).filter(m => m.cost != null && m.cost > 0);
            if (withCost.length === 0) {
                canvas.parentElement.querySelector('h4').textContent = '💵 Cost by Model (No data)';
                return;
            }

            // Sort by cost descending
            withCost.sort((a, b) => b.cost - a.cost);

            const colors = ['#CC8800', '#3533FF', '#4CD97A', '#FF5A26', '#33B6FF', '#9B59B6', '#E74C3C', '#1ABC9C'];
            const ctx = canvas.getContext('2d');
            tokenUsageCharts.costModel = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: withCost.map(m => {
                        const name = m.model || 'Unknown';
                        return name.length > 25 ? name.substring(0, 22) + '...' : name;
                    }),
                    datasets: [
                        {
                            label: 'Estimated Cost',
                            data: withCost.map(m => m.cost),
                            backgroundColor: withCost.map((_, i) => colors[i % colors.length] + '99'),
                            borderColor: withCost.map((_, i) => colors[i % colors.length]),
                            borderWidth: 1,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { callback: v => formatCost(v) },
                        },
                    },
                    plugins: {
                        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${formatCost(ctx.raw)}` } },
                        legend: { display: false },
                    },
                },
            });
        }
        function renderTokenModelChart(byModel) {
            const canvas = document.getElementById('tokenUsageModelChart');
            if (!canvas) return;

            if (tokenUsageCharts.model) tokenUsageCharts.model.destroy();

            if (!byModel || byModel.length === 0) {
                canvas.parentElement.querySelector('h4').textContent = '📊 Usage by Model (No data)';
                return;
            }

            const colors = ['#3533FF', '#4CD97A', '#FF5A26', '#33B6FF', '#CC8800', '#9B59B6', '#E74C3C', '#1ABC9C'];
            const ctx = canvas.getContext('2d');
            tokenUsageCharts.model = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: byModel.map(m => {
                        const name = m.model || 'Unknown';
                        return name.length > 25 ? name.substring(0, 22) + '...' : name;
                    }),
                    datasets: [
                        {
                            label: 'Input Tokens',
                            data: byModel.map(m => m.input_tokens),
                            backgroundColor: colors.map(c => c + '99'),
                            borderColor: colors,
                            borderWidth: 1,
                        },
                        {
                            label: 'Output Tokens',
                            data: byModel.map(m => m.output_tokens),
                            backgroundColor: colors.map(c => c + '44'),
                            borderColor: colors.map(c => c + '99'),
                            borderWidth: 1,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { beginAtZero: true, ticks: { callback: v => formatNumber(v) } },
                    },
                    plugins: {
                        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${formatNumber(ctx.raw)}` } },
                        legend: { position: 'top' },
                    },
                },
            });
        }
