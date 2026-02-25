        // MCP Connections Page JavaScript
        // Manages MCP server connections

        // Global state
        let mcpServers = [];
        let nextServerId = 1;
        let availableAuthTypes = [];
        let selectedServerId = null;
        let activeTab = 'auth';
        let usageCharts = {}; // chart instances for cleanup

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Helper function to get a human-readable type display
        function getTypeDisplay(schema) {
            if (!schema) return 'any';
            if (schema.type === 'array') {
                if (schema.items) return `array<${schema.items.type || 'object'}>`;
                return 'array';
            }
            if (schema.type === 'object') return 'object';
            if (schema.enum) return `enum (${schema.enum.length} options)`;
            return schema.type || 'any';
        }

        // Initialize page
        async function initializeConnections() {
            await loadAuthTypes();
            await loadMcpServers();

            // Deep-link: select server from ?server= query param
            const params = new URLSearchParams(window.location.search);
            const requestedServer = params.get('server');
            if (requestedServer && mcpServers.find(s => s.id === requestedServer)) {
                selectedServerId = requestedServer;
            } else if (mcpServers.length > 0 && !selectedServerId) {
                sortMcpServers();
                selectedServerId = mcpServers[0].id;
            }

            renderMcpServers();
            updateMcpStatusDisplay();
        }

        initializeConnections();

        // Listen for OAuth callback messages from popup window
        window.addEventListener('message', async (event) => {
            if (event.origin !== window.location.origin) return;
            if (event.data && event.data.type === 'oauth_success') {
                const serverId = event.data.server_id;
                console.log('OAuth authorization successful for server:', serverId);
                await loadMcpServers();
                const server = mcpServers.find(s => s.id === serverId);
                let successMsg = `OAuth authorization successful for ${server ? server.name : serverId}!`;
                if (server) {
                    const promptsCount = server.prompts ? server.prompts.length : 0;
                    const toolsCount = server.tools ? server.tools.length : 0;
                    if (promptsCount > 0 || toolsCount > 0) {
                        successMsg += '\n\n';
                        if (promptsCount > 0) successMsg += `Prompts: ${promptsCount}\n`;
                        if (toolsCount > 0) successMsg += `Tools: ${toolsCount}`;
                    }
                }
                showError(successMsg, false);
                renderMcpServers();
            }
        });

        async function loadAuthTypes() {
            try {
                const response = await fetch('/api/mcp/auth-types');
                if (response.ok) {
                    const data = await response.json();
                    availableAuthTypes = data.auth_types || [];
                }
            } catch (error) {
                console.error('Error loading auth types:', error);
            }
        }

        // MCP Server Management Functions
        function addMcpServer() {
            const server = {
                id: `server-${nextServerId++}`,
                name: `MCP Server ${mcpServers.length + 1}`,
                url: '',
                enabled: true,
                headers: {}
            };
            mcpServers.push(server);
            selectedServerId = server.id;
            renderMcpServers();
            saveMcpServers();
        }

        function removeMcpServer(serverId) {
            if (!confirm('Remove this MCP server?')) return;
            mcpServers = mcpServers.filter(s => s.id !== serverId);
            if (selectedServerId === serverId) {
                selectedServerId = mcpServers.length > 0 ? mcpServers[0].id : null;
            }
            renderMcpServers();
            saveMcpServers();
            updateMcpStatusDisplay();
        }

        function updateServerField(serverId, field, value) {
            const server = mcpServers.find(s => s.id === serverId);
            if (server) {
                server[field] = value;
                if (field === 'name') {
                    // Update just the list item text without re-rendering everything
                    const listItems = document.querySelectorAll('.server-list-item');
                    listItems.forEach(item => {
                        if (item.getAttribute('onclick')?.includes(serverId)) {
                            const nameSpan = item.querySelector('.server-list-name');
                            if (nameSpan) nameSpan.textContent = value || 'Unnamed Server';
                        }
                    });
                    // Update detail header
                    const detailHeader = document.querySelector('.detail-header-left h2');
                    if (detailHeader) detailHeader.textContent = value || 'Unnamed Server';
                }
                saveMcpServers();
            }
        }

        function updateServerAuthType(serverId, authType) {
            const server = mcpServers.find(s => s.id === serverId);
            if (server) {
                server.auth_type = authType;
                server.auth_method = authType;
                server.auth_token = '';
                server.token = '';
                const authTypeConfig = availableAuthTypes.find(at => at.type === authType);
                if (authTypeConfig && authTypeConfig.user_inputs) {
                    authTypeConfig.user_inputs.forEach(input => {
                        if (input.default && (!server[input.field] || server[input.field] === '')) {
                            server[input.field] = input.default;
                        }
                    });
                }
                renderMcpServers();
                saveMcpServers();
            }
        }

        function addServerHeader(serverId) {
            const server = mcpServers.find(s => s.id === serverId);
            if (server) {
                if (!server.headers) server.headers = {};
                let headerNum = 1;
                while (server.headers[`X-Custom-Header-${headerNum}`]) headerNum++;
                server.headers[`X-Custom-Header-${headerNum}`] = '';
                renderMcpServers();
                saveMcpServers();
            }
        }

        function removeServerHeader(serverId, headerKey) {
            const server = mcpServers.find(s => s.id === serverId);
            if (server && server.headers) {
                delete server.headers[headerKey];
                renderMcpServers();
                saveMcpServers();
            }
        }

        function updateServerHeaderKey(serverId, oldKey, newKey) {
            const server = mcpServers.find(s => s.id === serverId);
            if (server && server.headers) {
                const value = server.headers[oldKey];
                delete server.headers[oldKey];
                server.headers[newKey] = value;
                saveMcpServers();
            }
        }

        function updateServerHeaderValue(serverId, headerKey, value) {
            const server = mcpServers.find(s => s.id === serverId);
            if (server && server.headers) {
                server.headers[headerKey] = value;
                saveMcpServers();
            }
        }

        function toggleServerCollapse(serverId) {
            const server = mcpServers.find(s => s.id === serverId);
            if (server) {
                server.collapsed = !server.collapsed;
                renderMcpServers();
                saveMcpServers();
            }
        }

        function sortMcpServers() {
            mcpServers.sort((a, b) => {
                const nameA = (a.name || '').toLowerCase();
                const nameB = (b.name || '').toLowerCase();
                return nameA.localeCompare(nameB);
            });
        }

        function renderMcpServers() {
            const container = document.getElementById('mcpServersList');
            if (mcpServers.length === 0) {
                container.innerHTML = '<div class="server-list-empty"><p>No MCP servers configured</p><p>Click "Add New Server" to get started.</p></div>';
                renderServerDetail();
                return;
            }

            sortMcpServers();

            container.innerHTML = mcpServers.map(server => {
                const isSelected = server.id === selectedServerId;
                const toolCount = server.tools ? server.tools.length : 0;
                const promptCount = server.prompts ? server.prompts.length : 0;
                const meta = [];
                if (toolCount > 0) meta.push(`${toolCount}T`);
                if (promptCount > 0) meta.push(`${promptCount}P`);

                return `
                    <div class="server-list-item ${isSelected ? 'selected' : ''}"
                         onclick="selectServer('${server.id}')">
                        <span class="server-status-dot enabled"></span>
                        <span class="server-list-name">${escapeHtml(server.name || 'Unnamed Server')}</span>
                        ${meta.length > 0 ? `<span class="server-list-meta">${meta.join(' ')}</span>` : ''}
                    </div>
                `;
            }).join('');

            renderServerDetail();
        }

        function selectServer(serverId) {
            selectedServerId = serverId;
            renderMcpServers();
        }

        function renderServerDetail() {
            const panel = document.getElementById('serverDetailPanel');
            const server = mcpServers.find(s => s.id === selectedServerId);

            if (!server) {
                panel.innerHTML = `
                    <div class="detail-empty">
                        <div class="detail-empty-icon">🔌</div>
                        <p>Select a server from the list to view its configuration</p>
                    </div>`;
                return;
            }

            panel.innerHTML = `
                <div class="detail-header">
                    <div class="detail-header-left">
                        <h2>${escapeHtml(server.name || 'Unnamed Server')}</h2>
                    </div>
                    <div class="detail-header-actions">
                        <button class="btn-icon" onclick="testSingleMcpConnection('${server.id}')" title="Test Connection">�</button>
                        <button class="btn-icon danger" onclick="removeMcpServer('${server.id}')" title="Delete Server">🗑️</button>
                    </div>
                </div>

                <div class="detail-tabs">
                    <button class="detail-tab ${activeTab === 'auth' ? 'active' : ''}" onclick="switchTab('auth')">🔐 Authentication</button>
                    <button class="detail-tab ${activeTab === 'tools' ? 'active' : ''}" onclick="switchTab('tools')">🛠️ Tools${server.tools && server.tools.length > 0 ? ` (${server.tools.length})` : ''}</button>
                    <button class="detail-tab ${activeTab === 'prompts' ? 'active' : ''}" onclick="switchTab('prompts')">📝 Prompts${server.prompts && server.prompts.length > 0 ? ` (${server.prompts.length})` : ''}</button>
                    <button class="detail-tab ${activeTab === 'usage' ? 'active' : ''}" onclick="switchTab('usage')">📊 Usage</button>
                </div>

                <div id="tabAuth" class="detail-tab-content ${activeTab === 'auth' ? 'active' : ''}"></div>
                <div id="tabTools" class="detail-tab-content ${activeTab === 'tools' ? 'active' : ''}"></div>
                <div id="tabPrompts" class="detail-tab-content ${activeTab === 'prompts' ? 'active' : ''}"></div>
                <div id="tabUsage" class="detail-tab-content ${activeTab === 'usage' ? 'active' : ''}"></div>
            `;

            renderAuthTab(server);
            if (activeTab === 'tools') renderToolsTab(server);
            if (activeTab === 'prompts') renderPromptsTab(server);
            if (activeTab === 'usage') renderUsageTab();
        }

        function switchTab(tab) {
            activeTab = tab;
            // Update tab buttons
            document.querySelectorAll('.detail-tab').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.detail-tab-content').forEach(el => el.classList.remove('active'));

            const tabMap = { 'auth': 'tabAuth', 'tools': 'tabTools', 'prompts': 'tabPrompts', 'usage': 'tabUsage' };
            const tabLabelMap = { 'auth': 'Authentication', 'tools': 'Tools', 'prompts': 'Prompts', 'usage': 'Usage' };
            const activeBtn = [...document.querySelectorAll('.detail-tab')].find(btn => btn.textContent.includes(tabLabelMap[tab]));
            if (activeBtn) activeBtn.classList.add('active');

            const content = document.getElementById(tabMap[tab]);
            if (content) content.classList.add('active');

            const server = mcpServers.find(s => s.id === selectedServerId);
            if (tab === 'tools' && server) renderToolsTab(server);
            if (tab === 'prompts' && server) renderPromptsTab(server);
            if (tab === 'usage') renderUsageTab();
        }

        function renderAuthTab(server) {
            const container = document.getElementById('tabAuth');
            if (!container) return;

            const authMethod = server.auth_method || server.auth_type || 'none';

            let authTypeOptions = '';
            if (availableAuthTypes && availableAuthTypes.length > 0) {
                authTypeOptions = availableAuthTypes.map(authType => {
                    const selected = (authMethod === authType.type) ? 'selected' : '';
                    return `<option value="${authType.type}" ${selected}>${authType.name}</option>`;
                }).join('');
            }

            let authSection = '';
            if (authMethod && authMethod !== 'none') {
                const authTypeConfig = availableAuthTypes.find(at => at.type === authMethod);
                if (authTypeConfig && authTypeConfig.user_inputs && authTypeConfig.user_inputs.length > 0) {
                    const authColor = authMethod === 'bearer' ? '#FFF8D6' :
                                    authMethod === 'url_token' ? '#E8F9FF' :
                                    authMethod === 'api_key' ? '#E8F9FF' :
                                    authMethod === 'basic' ? '#FFF0EC' : '#F4F4F4';
                    const authTextColor = authMethod === 'bearer' ? '#CC4820' :
                                        authMethod === 'url_token' ? '#3533FF' :
                                        authMethod === 'api_key' ? '#3533FF' :
                                        authMethod === 'basic' ? '#CC4820' : '#767676';

                    const inputFields = authTypeConfig.user_inputs.map(input => {
                        const value = server[input.field] || input.default || '';
                        return `
                            <div class="detail-section" style="margin-bottom: 12px;">
                                <label class="config-label">${input.label}${input.required ? ' *' : ''}</label>
                                <input type="${input.type || 'text'}"
                                       class="config-input"
                                       value="${value}"
                                       onchange="updateServerField('${server.id}', '${input.field}', this.value)"
                                       placeholder="${input.placeholder || ''}">
                                ${input.help_text ? `<div style="font-size: 10px; color: #929395; margin-top: 4px;">${input.help_text}</div>` : ''}
                            </div>
                        `;
                    }).join('');

                    authSection = `
                        <div class="detail-auth-box" style="background: ${authColor};">
                            <div style="font-size: 12px; font-weight: 600; color: ${authTextColor}; margin-bottom: 10px;">
                                &#128274; ${authTypeConfig.name}
                            </div>
                            ${inputFields}
                        </div>
                    `;
                }
            }

            // Headers
            const headerEntries = Object.entries(server.headers || {});
            let headersHtml = `
                <div class="detail-section">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <label class="config-label" style="margin-bottom: 0;">Custom Headers</label>
                        <button onclick="addServerHeader('${server.id}')"
                                style="padding: 4px 10px; background: #3533FF; color: white; border: none; border-radius: 4px; font-size: 11px; cursor: pointer;"
                                title="Add custom header">+ Add</button>
                    </div>
                    ${headerEntries.length > 0 ? headerEntries.map(([key, value]) => `
                        <div class="detail-headers-grid">
                            <input type="text" class="config-input" value="${escapeHtml(key)}"
                                   onchange="updateServerHeaderKey('${server.id}', '${escapeHtml(key)}', this.value)"
                                   placeholder="Header-Name">
                            <input type="text" class="config-input" value="${escapeHtml(value)}"
                                   onchange="updateServerHeaderValue('${server.id}', '${escapeHtml(key)}', this.value)"
                                   placeholder="Header value">
                            <button onclick="removeServerHeader('${server.id}', '${escapeHtml(key)}')"
                                    style="padding: 8px 10px; background: #FF5A26; color: white; border: none; border-radius: 4px; font-size: 12px; cursor: pointer;"
                                    title="Remove header">&times;</button>
                        </div>
                    `).join('') : '<div style="text-align: center; color: #929395; font-size: 12px; padding: 10px; background: #F4F4F4; border-radius: 4px;">No custom headers</div>'}
                </div>
            `;

            container.innerHTML = `
                ${server.description ? `
                <div class="detail-section">
                    <div style="background: #F4F4F4; padding: 10px; border-radius: 4px; font-size: 13px; color: #929395;">
                        ${escapeHtml(server.description)}
                    </div>
                </div>
                ` : ''}

                <div class="detail-section">
                    <label class="config-label">Server Name</label>
                    <input type="text" class="config-input" value="${escapeHtml(server.name || '')}"
                           onchange="updateServerField('${server.id}', 'name', this.value)"
                           placeholder="Enter server name">
                </div>

                <div class="detail-section">
                    <label class="config-label">Server URL</label>
                    <input type="text" class="config-input" value="${escapeHtml(server.url || '')}"
                           onchange="updateServerField('${server.id}', 'url', this.value)"
                           placeholder="Enter MCP server URL">
                </div>

                <div class="detail-section">
                    <label class="config-label">Notes</label>
                    <input type="text" class="config-input" value="${escapeHtml(server.notes || '')}"
                           onchange="updateServerField('${server.id}', 'notes', this.value)"
                           placeholder="Optional notes about this connection...">
                </div>

                <div class="detail-section">
                    <label class="config-label">Authentication Type</label>
                    <select class="config-input" onchange="updateServerAuthType('${server.id}', this.value)">
                        <option value="">None</option>
                        ${authTypeOptions}
                    </select>
                </div>

                ${authSection}
                ${headersHtml}
            `;
        }

        // ── Tools Tab ─────────────────────────────────────────────────────

        function renderToolsTab(server) {
            const container = document.getElementById('tabTools');
            if (!container) return;

            if (!server.tools || server.tools.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: #929395;">
                        <div style="font-size: 32px; margin-bottom: 12px;">🛠️</div>
                        <p>No tools available.</p>
                        <p style="font-size: 12px;">Test the connection to discover available tools.</p>
                    </div>`;
                return;
            }

            const isReadOnly = t => t.annotations && (t.annotations.readOnlyHint === true || t.annotations.readOnlyHint === 'True' || t.annotations.readOnlyHint === 'true');
            const isDestructive = t => t.annotations && (t.annotations.destructiveHint === true || t.annotations.destructiveHint === 'True' || t.annotations.destructiveHint === 'true');
            const readOnlyTools = server.tools.filter(t => isReadOnly(t));
            const destructiveTools = server.tools.filter(t => isDestructive(t));
            const otherTools = server.tools.filter(t => !isReadOnly(t) && !isDestructive(t));

            const renderToolGroup = (tools, title, borderColor, bgColor) => {
                if (tools.length === 0) return '';
                return `
                    <div style="margin-bottom: 16px;">
                        <div style="font-size: 12px; font-weight: 600; color: #767676; padding: 6px 10px; background: ${bgColor}; border-left: 3px solid ${borderColor}; border-radius: 4px; margin-bottom: 8px;">
                            ${title} (${tools.length})
                        </div>
                        ${tools.map(tool => `
                            <div class="tool-item" data-search="${escapeHtml((tool.name + ' ' + (tool.description || '')).toLowerCase())}" style="background: #FAFAFA; padding: 12px; border-radius: 6px; margin-bottom: 8px; border-left: 3px solid ${borderColor};">
                                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap;">
                                    <span style="font-weight: 600; font-size: 13px; color: #000;">${escapeHtml(tool.name)}</span>
                                    ${tool.annotations?.readOnlyHint ? '<span style="background: #D4F4FF; color: #3533FF; padding: 1px 6px; border-radius: 10px; font-size: 10px; font-weight: 500;">READ ONLY</span>' : ''}
                                    ${tool.annotations?.destructiveHint ? '<span style="background: #FFF0EC; color: #CC4820; padding: 1px 6px; border-radius: 10px; font-size: 10px; font-weight: 500;">DESTRUCTIVE</span>' : ''}
                                </div>
                                ${tool.description ? `<div style="color: #929395; font-size: 12px; margin-bottom: 6px; white-space: pre-wrap;">${escapeHtml(tool.description)}</div>` : ''}
                                ${tool.inputSchema && tool.inputSchema.properties ? `
                                    <div style="margin-top: 6px;">
                                        <div style="font-size: 11px; font-weight: 500; color: #767676; margin-bottom: 4px;">Parameters:</div>
                                        ${Object.entries(tool.inputSchema.properties).map(([key, value]) => {
                                            const isRequired = tool.inputSchema.required && tool.inputSchema.required.includes(key);
                                            const typeDisplay = getTypeDisplay(value);
                                            return `
                                            <div style="background: white; padding: 6px 8px; border-radius: 4px; margin-bottom: 3px; font-size: 11px;">
                                                <span style="font-weight: 500; color: #000;">${key}</span>
                                                <span style="color: #929395;"> (${typeDisplay})</span>
                                                ${isRequired ? '<span style="color: #FF5A26;"> *required</span>' : '<span style="color: #929395;"> optional</span>'}
                                                ${value.description ? `<div style="color: #929395; margin-top: 2px; white-space: pre-wrap;">${escapeHtml(value.description)}</div>` : ''}
                                            </div>`;
                                        }).join('')}
                                    </div>
                                ` : ''}
                            </div>
                        `).join('')}
                    </div>
                `;
            };

            let html = `
                <div class="models-search-box">
                    <input type="text" class="models-search-input" placeholder="Search tools..." oninput="filterTools(this.value)">
                    <span class="models-search-count">${server.tools.length} tool(s)</span>
                </div>
            `;
            html += '<div id="toolsListContainer">';
            html += renderToolGroup(readOnlyTools, 'Read-Only Tools', '#33B6FF', '#E8F9FF');
            html += renderToolGroup(destructiveTools, 'Destructive Tools', '#FF5A26', '#FFF0EC');
            html += renderToolGroup(otherTools, 'General Tools', '#4CD97A', '#EDFFF3');
            html += '</div>';
            container.innerHTML = html;
        }

        function filterTools(query) {
            const container = document.getElementById('toolsListContainer');
            if (!container) return;
            const q = query.toLowerCase().trim();
            const items = container.querySelectorAll('.tool-item');
            let visible = 0;
            items.forEach(item => {
                const searchData = item.getAttribute('data-search') || item.textContent.toLowerCase();
                const show = !q || searchData.includes(q);
                item.style.display = show ? '' : 'none';
                if (show) visible++;
            });
            // Hide group sections when all their items are hidden
            const groups = container.querySelectorAll(':scope > div');
            groups.forEach(group => {
                const groupItems = group.querySelectorAll('.tool-item');
                if (groupItems.length === 0) return;
                const anyVisible = Array.from(groupItems).some(i => i.style.display !== 'none');
                group.style.display = anyVisible ? '' : 'none';
            });
            const countEl = document.querySelector('#tabTools .models-search-count');
            if (countEl) countEl.textContent = q ? `${visible} / ${items.length} tool(s)` : `${items.length} tool(s)`;
        }
        window.filterTools = filterTools;

        // ── Prompts Tab ───────────────────────────────────────────────────

        function renderPromptsTab(server) {
            const container = document.getElementById('tabPrompts');
            if (!container) return;

            if (!server.prompts || server.prompts.length === 0) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 40px; color: #929395;">
                        <div style="font-size: 32px; margin-bottom: 12px;">📝</div>
                        <p>No prompts available.</p>
                        <p style="font-size: 12px;">Test the connection to discover available prompts.</p>
                    </div>`;
                return;
            }

            let html = `
                <div class="models-search-box">
                    <input type="text" class="models-search-input" placeholder="Search prompts..." oninput="filterPrompts(this.value)">
                    <span class="models-search-count">${server.prompts.length} prompt(s)</span>
                </div>
            `;
            html += '<div id="promptsListContainer">';
            server.prompts.forEach(prompt => {
                html += `
                    <div class="prompt-item" data-search="${escapeHtml(((prompt.title || prompt.name) + ' ' + (prompt.description || '')).toLowerCase())}" style="background: #FAFAFA; padding: 12px; border-radius: 6px; margin-bottom: 8px; border-left: 3px solid #33B6FF;">
                        <div style="font-weight: 600; font-size: 13px; color: #000; margin-bottom: 4px;">${escapeHtml(prompt.title || prompt.name)}</div>
                        ${prompt.description ? `<div style="color: #929395; font-size: 12px; margin-bottom: 6px; white-space: pre-wrap;">${escapeHtml(prompt.description)}</div>` : ''}
                        ${prompt.arguments && prompt.arguments.length > 0 ? `
                            <div style="margin-top: 6px;">
                                <div style="font-size: 11px; font-weight: 500; color: #767676; margin-bottom: 4px;">Arguments:</div>
                                ${prompt.arguments.map(arg => `
                                    <div style="background: white; padding: 6px 8px; border-radius: 4px; margin-bottom: 3px; font-size: 11px;">
                                        <span style="font-weight: 500; color: #000;">${escapeHtml(arg.name)}</span>
                                        ${arg.required ? '<span style="color: #FF5A26;"> *required</span>' : '<span style="color: #929395;"> optional</span>'}
                                        ${arg.description ? `<div style="color: #929395; margin-top: 2px;">${escapeHtml(arg.description)}</div>` : ''}
                                    </div>
                                `).join('')}
                            </div>
                        ` : ''}
                    </div>
                `;
            });
            html += '</div>';
            container.innerHTML = html;
        }

        function filterPrompts(query) {
            const container = document.getElementById('promptsListContainer');
            if (!container) return;
            const q = query.toLowerCase().trim();
            const items = container.querySelectorAll('.prompt-item');
            let visible = 0;
            items.forEach(item => {
                const searchData = item.getAttribute('data-search') || item.textContent.toLowerCase();
                const show = !q || searchData.includes(q);
                item.style.display = show ? '' : 'none';
                if (show) visible++;
            });
            const countEl = document.querySelector('#tabPrompts .models-search-count');
            if (countEl) countEl.textContent = q ? `${visible} / ${items.length} prompt(s)` : `${items.length} prompt(s)`;
        }
        window.filterPrompts = filterPrompts;

        // ── Usage Tab ─────────────────────────────────────────────────────

        async function renderUsageTab() {
            const container = document.getElementById('tabUsage');
            if (!container) return;

            // Default date range: last 30 days
            const endDate = new Date().toISOString().split('T')[0];
            const startDate = new Date(Date.now() - 30 * 86400000).toISOString().split('T')[0];

            container.innerHTML = `
                <div class="usage-filters">
                    <div class="usage-filter-group">
                        <label>Start Date</label>
                        <input type="date" id="usageStartDate" value="${startDate}">
                    </div>
                    <div class="usage-filter-group">
                        <label>End Date</label>
                        <input type="date" id="usageEndDate" value="${endDate}">
                    </div>
                    <button class="usage-refresh-btn" onclick="refreshUsageCharts()">🔄 Refresh</button>
                </div>
                <div id="usageTotals" class="usage-totals"></div>
                <div class="usage-charts">
                    <div class="usage-chart-container">
                        <h4>📈 Token Usage Over Time</h4>
                        <canvas id="usageDailyChart"></canvas>
                    </div>
                    <div class="usage-chart-container">
                        <h4>📊 Usage by Model</h4>
                        <canvas id="usageModelChart"></canvas>
                    </div>
                </div>
            `;

            await refreshUsageCharts();
        }

        async function refreshUsageCharts() {
            const startDate = document.getElementById('usageStartDate')?.value || '';
            const endDate = document.getElementById('usageEndDate')?.value || '';

            try {
                const params = new URLSearchParams();
                if (startDate) params.set('start_date', startDate);
                if (endDate) params.set('end_date', endDate);
                if (selectedServerId) params.set('server_id', selectedServerId);

                const resp = await fetch(`/api/usage-stats?${params}`);
                const data = await resp.json();
                if (!resp.ok) throw new Error(data.error || 'Failed to fetch stats');

                renderUsageTotals(data.totals);
                renderDailyChart(data.daily);
                renderModelChart(data.by_model);
            } catch (error) {
                console.error('Error loading usage stats:', error);
                const totals = document.getElementById('usageTotals');
                if (totals) totals.innerHTML = `<div style="color: #CC4820; padding: 12px;">Error loading stats: ${error.message}</div>`;
            }
        }

        function formatNumber(n) {
            if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
            if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
            return n.toString();
        }

        function renderUsageTotals(totals) {
            const container = document.getElementById('usageTotals');
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
            `;
        }

        function renderDailyChart(daily) {
            const canvas = document.getElementById('usageDailyChart');
            if (!canvas) return;

            // Destroy existing chart
            if (usageCharts.daily) usageCharts.daily.destroy();

            if (!daily || daily.length === 0) {
                canvas.parentElement.querySelector('h4').textContent = '📈 Token Usage Over Time (No data)';
                return;
            }

            const ctx = canvas.getContext('2d');
            usageCharts.daily = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: daily.map(d => d.date),
                    datasets: [
                        {
                            label: 'Input Tokens',
                            data: daily.map(d => d.input_tokens),
                            borderColor: '#3533FF',
                            backgroundColor: 'rgba(53, 51, 255, 0.1)',
                            fill: true,
                            tension: 0.3,
                        },
                        {
                            label: 'Output Tokens',
                            data: daily.map(d => d.output_tokens),
                            borderColor: '#4CD97A',
                            backgroundColor: 'rgba(76, 217, 122, 0.1)',
                            fill: true,
                            tension: 0.3,
                        },
                        {
                            label: 'Cache Read',
                            data: daily.map(d => d.cache_read),
                            borderColor: '#33B6FF',
                            backgroundColor: 'rgba(51, 182, 255, 0.1)',
                            fill: true,
                            tension: 0.3,
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
                            ticks: { callback: v => formatNumber(v) },
                        },
                        x: {
                            ticks: { maxTicksAutoSkip: true, maxRotation: 45 },
                        }
                    },
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: ctx => `${ctx.dataset.label}: ${formatNumber(ctx.raw)}`,
                            },
                        },
                        legend: { position: 'top' },
                    },
                },
            });
        }

        function renderModelChart(byModel) {
            const canvas = document.getElementById('usageModelChart');
            if (!canvas) return;

            if (usageCharts.model) usageCharts.model.destroy();

            if (!byModel || byModel.length === 0) {
                canvas.parentElement.querySelector('h4').textContent = '📊 Usage by Model (No data)';
                return;
            }

            const colors = ['#3533FF', '#4CD97A', '#FF5A26', '#33B6FF', '#CC8800', '#9B59B6', '#E74C3C', '#1ABC9C'];
            const ctx = canvas.getContext('2d');
            usageCharts.model = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: byModel.map(m => {
                        // Shorten model names for display
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
                        y: {
                            beginAtZero: true,
                            ticks: { callback: v => formatNumber(v) },
                        },
                    },
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: ctx => `${ctx.dataset.label}: ${formatNumber(ctx.raw)}`,
                                afterBody: (tooltipItems) => {
                                    const idx = tooltipItems[0].dataIndex;
                                    return `Requests: ${byModel[idx].requests}`;
                                },
                            },
                        },
                        legend: { position: 'top' },
                    },
                },
            });
        }

        async function saveMcpServers() {
            try {
                const response = await fetch('/api/mcp/credentials', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        servers: mcpServers.reduce((acc, server) => {
                            acc[server.id] = server;
                            return acc;
                        }, {})
                    })
                });
                if (!response.ok) {
                    console.error('Failed to save MCP credentials:', await response.text());
                }
            } catch (error) {
                console.error('Error saving MCP credentials:', error);
            }
        }

        async function loadMcpServers() {
            try {
                const response = await fetch('/api/mcp/credentials');
                if (response.ok) {
                    const data = await response.json();
                    const servers = data.servers || {};
                    mcpServers = Object.entries(servers).map(([id, server]) => ({...server, id}));

                    mcpServers.forEach(server => {
                        if (server.auth_method && !server.auth_type) server.auth_type = server.auth_method;
                        else if (server.auth_type && !server.auth_method) server.auth_method = server.auth_type;
                        // DB stores the token as 'auth_token'; config.json input fields
                        // reference 'token' — keep both in sync so the form renders it.
                        if (server.auth_token && !server.token) server.token = server.auth_token;
                        else if (server.token && !server.auth_token) server.auth_token = server.token;
                    });

                    mcpServers.forEach(server => {
                        const authType = server.auth_type || server.auth_method;
                        if (authType && authType !== 'none') {
                            const authTypeConfig = availableAuthTypes.find(at => at.type === authType);
                            if (authTypeConfig && authTypeConfig.user_inputs) {
                                authTypeConfig.user_inputs.forEach(input => {
                                    if (input.default && (!server[input.field] || server[input.field] === '')) {
                                        server[input.field] = input.default;
                                    }
                                });
                            }
                        }
                    });

                    mcpServers.forEach(server => {
                        const match = server.id.match(/server-(\d+)/);
                        if (match) nextServerId = Math.max(nextServerId, parseInt(match[1]) + 1);
                    });
                }
            } catch (error) {
                console.error('Error loading MCP credentials:', error);
            }
        }

        function updateMcpStatusDisplay() {
            const status = document.getElementById('mcpStatus');
            if (!status) return;
            const enabledServers = mcpServers.filter(s => s.enabled);
            if (enabledServers.length === 0) {
                status.className = 'status-indicator status-disconnected';
                status.innerHTML = '<span>&#9679;</span> No servers enabled';
            } else {
                status.className = 'status-indicator status-connected';
                status.innerHTML = `<span>&#9679;</span> ${enabledServers.length} server(s) enabled`;
            }
        }

        async function testSingleMcpConnection(serverId) {
            const server = mcpServers.find(s => s.id === serverId);
            if (!server) return;

            if (!server.url) {
                showError('Please enter server URL');
                return;
            }

            const authMethod = server.auth_method || server.auth_type || 'none';

            // For OAuth servers, force re-authorization
            if (authMethod === 'oauth2') {
                const serverCopy = { ...server };
                delete serverCopy.access_token;
                delete serverCopy.token;
                delete serverCopy.refresh_token;

                showError('Generating OAuth authorization URL with PKCE...', false);

                fetch('/api/generate-oauth-state', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ server_id: serverId })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.error) { showError(`Failed to generate OAuth URL: ${data.error}`); return; }
                    const authUrl = data.authorization_url;
                    if (!authUrl) { showError('No authorization URL returned from server'); return; }
                    showError('Opening OAuth authorization window...', false);
                    const width = 600, height = 700;
                    const left = (screen.width - width) / 2;
                    const top = (screen.height - height) / 2;
                    const authWindow = window.open(authUrl, 'oauth_auth',
                        `width=${width},height=${height},left=${left},top=${top},scrollbars=yes,resizable=yes`
                    );
                    if (!authWindow) {
                        showError('Please allow popups to complete OAuth authorization');
                    } else {
                        showError('Please authorize in the popup window. After authorization, the window will close automatically.', false);
                    }
                })
                .catch(error => showError(`Failed to generate OAuth state: ${error.message}`));
                return;
            }

            // Check required credentials for non-none auth
            if (authMethod !== 'none') {
                const authTypeConfig = availableAuthTypes.find(at => at.type === authMethod);
                if (authTypeConfig && authTypeConfig.user_inputs) {
                    const missingFields = authTypeConfig.user_inputs
                        .filter(input => input.required && !server[input.field])
                        .map(input => input.label);
                    if (missingFields.length > 0) {
                        showError(`${server.name} requires: ${missingFields.join(', ')}`);
                        return;
                    }
                }
            }

            try {
                showError(`Testing ${server.name}...`, false);
                const requestBody = {
                    server_id: serverId,
                    servers: [{
                        id: server.id, name: server.name, url: server.url,
                        auth_type: server.auth_type, auth_method: authMethod,
                        ...server
                    }]
                };

                if (server.token) {
                    requestBody.token = server.token;
                    requestBody.auth_token = server.token;
                }

                const response = await fetch('/api/test-mcp-single', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify(requestBody)
                });

                const result = await response.json();

                if (response.ok) {
                    server.prompts = result.prompts || [];
                    server.tools = result.tools || [];
                    server.lastValidated = new Date().toISOString();
                    saveMcpServers();
                    let successMsg = `${result.message}`;
                    if (result.prompts_count !== undefined) successMsg += `\n\nPrompts: ${result.prompts_count}`;
                    if (result.tools_count !== undefined) successMsg += `\nTools: ${result.tools_count}`;
                    showError(successMsg, false);
                    renderMcpServers();
                } else {
                    if (result.status === 'oauth_required' && result.authorization_url) {
                        showError('Opening OAuth authorization window...', false);
                        const width = 600, height = 700;
                        const left = (screen.width - width) / 2;
                        const top = (screen.height - height) / 2;
                        window.open(result.authorization_url, 'oauth_auth',
                            `width=${width},height=${height},left=${left},top=${top},scrollbars=yes,resizable=yes`
                        );
                    } else {
                        throw new Error(result.error || result.message || 'MCP connection test failed');
                    }
                }
            } catch (error) {
                showError(`Connection Failed: ${error.message}`);
            }
        }

        async function testAllMcpConnections() {
            const enabledServers = mcpServers.filter(s => s.enabled);
            if (enabledServers.length === 0) { showError('No enabled servers to test'); return; }
            showError(`Testing ${enabledServers.length} server(s)...`, false);

            try {
                const requestBody = {
                    servers: enabledServers.map(server => ({
                        id: server.id, name: server.name, url: server.url,
                        auth_type: server.auth_type || server.auth_method,
                        enabled: true, ...server
                    }))
                };

                const response = await fetch('/api/test-mcp-all', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify(requestBody)
                });

                const result = await response.json();

                if (response.ok) {
                    const successCount = result.results.filter(r => r.status === 'success').length;
                    const errorCount = result.results.filter(r => r.status === 'error').length;
                    result.results.forEach(serverResult => {
                        const server = mcpServers.find(s => s.id === serverResult.server_id);
                        if (server && serverResult.status === 'success' && serverResult.data) {
                            server.prompts = serverResult.data.prompts || [];
                            server.tools = serverResult.data.tools || [];
                            server.lastValidated = new Date().toISOString();
                        }
                    });
                    saveMcpServers();
                    renderMcpServers();
                    let message = `Tested ${result.tested_servers} server(s):\n  - ${successCount} successful\n`;
                    if (errorCount > 0) {
                        message += `  - ${errorCount} failed\n\nFailed servers:\n`;
                        result.results.filter(r => r.status === 'error')
                            .forEach(r => { message += `  - ${r.server_name}: ${r.error}\n`; });
                    }
                    showError(message, errorCount > 0);
                } else {
                    throw new Error(result.error || 'Failed to test servers');
                }
            } catch (error) {
                showError(`Test All Failed: ${error.message}`);
            }
        }

        // Error display
        function showError(message, isError = true) {
            // Create a floating notification
            let container = document.getElementById('errorContainer');
            if (!container) {
                container = document.createElement('div');
                container.id = 'errorContainer';
                container.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999; max-width: 400px;';
                document.body.appendChild(container);
            }
            const div = document.createElement('div');
            div.className = 'error-message';
            div.style.background = isError ? '#FFF0EC' : '#D4FFE2';
            div.style.color = isError ? '#CC4820' : '#3BB366';
            div.style.borderLeftColor = isError ? '#FF5A26' : '#4CD97A';
            div.style.padding = '12px';
            div.style.borderRadius = '6px';
            div.style.marginBottom = '8px';
            div.style.borderLeft = `3px solid ${isError ? '#FF5A26' : '#4CD97A'}`;
            div.style.fontSize = '13px';
            div.style.boxShadow = '0 2px 8px rgba(0,0,0,0.1)';
            div.textContent = message;
            container.innerHTML = '';
            container.appendChild(div);
            if (!message.includes('WARNING')) {
                setTimeout(() => { div.remove(); }, 5000);
            }
        }

        // MCP Capabilities Modal functions
        function viewMcpCapabilities(serverId) {
            const server = mcpServers.find(s => s.id === serverId);
            if (!server) return;

            const modal = document.getElementById('mcpCapabilitiesModal');
            const modalServerName = document.getElementById('modalServerName');
            const modalContent = document.getElementById('modalContent');

            modalServerName.textContent = `${server.name} - Capabilities`;

            let content = '';

            if (server.tools && server.tools.length > 0) {
                const _ro = t => t.annotations && (t.annotations.readOnlyHint === true || t.annotations.readOnlyHint === 'True' || t.annotations.readOnlyHint === 'true');
                const _dest = t => t.annotations && (t.annotations.destructiveHint === true || t.annotations.destructiveHint === 'True' || t.annotations.destructiveHint === 'true');
                const readOnlyTools = server.tools.filter(t => _ro(t));
                const destructiveTools = server.tools.filter(t => _dest(t));
                const otherTools = server.tools.filter(t => !_ro(t) && !_dest(t));

                const renderToolSection = (tools, title, emoji, borderColor, bgColor, category) => {
                    if (tools.length === 0) return '';
                    let section = `<div style="margin-bottom: 25px;">
                        <h4 class="subcategory-header" data-category="${category}" data-total="${tools.length}" style="color: #000000; font-size: 13px; font-weight: 600; padding: 8px 12px; background: ${bgColor}; border-left: 3px solid ${borderColor}; margin-bottom: 12px; border-radius: 4px;">
                            ${emoji} ${title} (${tools.length})
                        </h4>`;
                    tools.forEach(tool => {
                        const searchText = `${tool.name} ${tool.description || ''}`.replace(/[\r\n]+/g, ' ').replace(/["']/g, '').replace(/\s+/g, ' ').trim();
                        const isReadOnly = tool.annotations && (tool.annotations.readOnlyHint === true || tool.annotations.readOnlyHint === 'True' || tool.annotations.readOnlyHint === 'true');
                        const isDestructive = tool.annotations && (tool.annotations.destructiveHint === true || tool.annotations.destructiveHint === 'True' || tool.annotations.destructiveHint === 'true');
                        section += `
                            <div class="capability-item" data-type="tool" data-category="${category}" data-search="${escapeHtml(searchText.toLowerCase())}" style="background: #EDFFF3; padding: 15px; border-radius: 6px; margin-bottom: 12px; border-left: 3px solid ${borderColor};">
                                <div style="flex: 1;">
                                    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 5px; flex-wrap: wrap;">
                                        <div style="font-weight: 600; font-size: 14px; color: #000000;">${escapeHtml(tool.name)}</div>
                                        ${isReadOnly ? '<span style="background: #D4F4FF; color: #3533FF; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 500;">READ ONLY</span>' : ''}
                                        ${isDestructive ? '<span style="background: #FFF0EC; color: #CC4820; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 500;">DESTRUCTIVE</span>' : ''}
                                    </div>
                                    ${tool.description ? `<div style="color: #929395; font-size: 13px; margin-bottom: 8px; white-space: pre-wrap;">${escapeHtml(tool.description)}</div>` : ''}
                                    ${tool.inputSchema && tool.inputSchema.properties ? `
                                        <div style="margin-top: 10px;">
                                            <div style="font-size: 12px; font-weight: 500; color: #767676; margin-bottom: 5px;">Parameters:</div>
                                            ${Object.entries(tool.inputSchema.properties).map(([key, value]) => {
                                                const isRequired = tool.inputSchema.required && tool.inputSchema.required.includes(key);
                                                const typeDisplay = getTypeDisplay(value);
                                                return `
                                                <div style="background: white; padding: 8px; border-radius: 4px; margin-bottom: 4px; font-size: 12px;">
                                                    <span style="font-weight: 500; color: #000000;">${key}</span>
                                                    <span style="color: #929395; font-size: 11px;"> (${typeDisplay})</span>
                                                    ${isRequired ? '<span style="color: #FF5A26; font-size: 11px;"> *required</span>' : '<span style="color: #929395; font-size: 11px;"> optional</span>'}
                                                    ${value.description ? `<div style="color: #929395; margin-top: 2px; white-space: pre-wrap;">${escapeHtml(value.description)}</div>` : ''}
                                                </div>
                                            `}).join('')}
                                        </div>
                                    ` : ''}
                                </div>
                            </div>
                        `;
                    });
                    section += '</div>';
                    return section;
                };

                content += '<div style="margin-bottom: 30px;"><h3 style="color: #000000; border-bottom: 2px solid #4CD97A; padding-bottom: 8px; margin-bottom: 15px;">Tools (' + server.tools.length + ')</h3>';
                content += renderToolSection(readOnlyTools, 'Read-Only Tools', '', '#33B6FF', '#E8F9FF', 'readonly');
                content += renderToolSection(destructiveTools, 'Destructive Tools', '', '#FF5A26', '#FFF0EC', 'destructive');
                content += renderToolSection(otherTools, 'General Tools', '', '#4CD97A', '#EDFFF3', 'general');
                content += '</div>';
            }

            if (server.prompts && server.prompts.length > 0) {
                content += '<div><h3 style="color: #000000; border-bottom: 2px solid #33B6FF; padding-bottom: 8px; margin-bottom: 15px;">Prompts (' + server.prompts.length + ')</h3>';
                server.prompts.forEach(prompt => {
                    const searchText = `${prompt.title || prompt.name} ${prompt.description || ''}`.replace(/[\r\n]+/g, ' ').replace(/["']/g, '').replace(/\s+/g, ' ').trim();
                    content += `
                        <div class="capability-item" data-type="prompt" data-search="${escapeHtml(searchText.toLowerCase())}" style="background: #F4F4F4; padding: 15px; border-radius: 6px; margin-bottom: 12px; border-left: 3px solid #33B6FF;">
                            <div style="font-weight: 600; font-size: 14px; color: #000000; margin-bottom: 5px;">${escapeHtml(prompt.title || prompt.name)}</div>
                            ${prompt.description ? `<div style="color: #929395; font-size: 13px; margin-bottom: 8px; white-space: pre-wrap;">${escapeHtml(prompt.description)}</div>` : ''}
                            ${prompt.arguments && prompt.arguments.length > 0 ? `
                                <div style="margin-top: 10px;">
                                    <div style="font-size: 12px; font-weight: 500; color: #767676; margin-bottom: 5px;">Arguments:</div>
                                    ${prompt.arguments.map(arg => `
                                        <div style="background: white; padding: 8px; border-radius: 4px; margin-bottom: 4px; font-size: 12px;">
                                            <span style="font-weight: 500; color: #000000;">${escapeHtml(arg.name)}</span>
                                            ${arg.required ? '<span style="color: #FF5A26; font-size: 11px;"> *required</span>' : '<span style="color: #929395; font-size: 11px;"> optional</span>'}
                                        </div>
                                    `).join('')}
                                </div>
                            ` : ''}
                        </div>
                    `;
                });
                content += '</div>';
            }

            if (!content) {
                content = '<div style="text-align: center; padding: 40px; color: #929395;">No prompts or tools available. Please test the connection first.</div>';
            }

            modalContent.innerHTML = content;
            modal.classList.add('visible');
        }

        function closeMcpCapabilitiesModal() {
            document.getElementById('mcpCapabilitiesModal').classList.remove('visible');
            const searchInput = document.getElementById('capabilitiesSearch');
            if (searchInput) searchInput.value = '';
        }

        function filterCapabilities() {
            const searchInput = document.getElementById('capabilitiesSearch');
            const clearBtn = document.getElementById('clearSearchBtn');
            const searchTerm = searchInput.value.toLowerCase().trim();
            const items = document.querySelectorAll('.capability-item');
            clearBtn.style.display = searchTerm ? 'block' : 'none';
            items.forEach(item => {
                const searchData = item.getAttribute('data-search');
                item.style.display = (!searchTerm || searchData.includes(searchTerm)) ? '' : 'none';
            });
        }

        function clearCapabilitiesSearch() {
            const searchInput = document.getElementById('capabilitiesSearch');
            searchInput.value = '';
            filterCapabilities();
            searchInput.focus();
        }

        document.addEventListener('click', function(event) {
            const capabilitiesModal = document.getElementById('mcpCapabilitiesModal');
            if (event.target === capabilitiesModal) closeMcpCapabilitiesModal();
        });
