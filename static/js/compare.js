        // Initialize Mermaid
        mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' });
        let mermaidIdCounter = 0;

        async function renderMermaidBlocks(container) {
            const codeBlocks = container.querySelectorAll('code.language-mermaid');
            for (const code of codeBlocks) {
                const pre = code.parentElement;
                const mermaidDiv = document.createElement('div');
                mermaidDiv.className = 'mermaid-diagram';
                const id = 'mermaid-' + (++mermaidIdCounter);
                try {
                    const { svg } = await mermaid.render(id, code.textContent.trim());
                    mermaidDiv.innerHTML = svg;
                    pre.replaceWith(mermaidDiv);
                } catch (e) {
                    console.warn('Mermaid render failed:', e);
                    const errSvg = document.getElementById(id);
                    if (errSvg) errSvg.remove();
                }
            }
        }

        // ── Global State ─────────────────────────────────────────────

        let mcpServers = [];
        let allTokens = [];
        let allModels = [];
        let dynamicModels = null;

        let leftConfig  = { servers: [], enabled_servers: [], token_id: null, model_id: null, provider: null };
        let rightConfig = { servers: [], enabled_servers: [], token_id: null, model_id: null, provider: null };
        let leftPricing  = { inputPrice: 3.0 / 1000000, outputPrice: 15.0 / 1000000 };
        let rightPricing = { inputPrice: 3.0 / 1000000, outputPrice: 15.0 / 1000000 };

        let comparisonSessionId = null;
        let leftSessionId = null;
        let rightSessionId = null;
        let comparisonData = {
            left:  { messages: [], totalTokens: 0, totalTime: 0, totalCost: 0, conversationHistory: [] },
            right: { messages: [], totalTokens: 0, totalTime: 0, totalCost: 0, conversationHistory: [] }
        };

        // ── JSON Formatter ───────────────────────────────────────────

        function formatJSON(obj) {
            const json = JSON.stringify(obj, null, 2);
            return json.replace(/(&|<|>|"|')/g, (match) => {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[match];
            }).replace(/"([^"]+)":/g, '<span style="color: #3533FF; font-weight: 600;">"$1"</span>:')
              .replace(/: "([^"]*)"/g, ': <span style="color: #4CD97A;">"$1"</span>')
              .replace(/: (true|false)/g, ': <span style="color: #33B6FF; font-weight: 600;">$1</span>')
              .replace(/: (null)/g, ': <span style="color: #929395; font-weight: 600;">$1</span>')
              .replace(/: (-?\d+\.?\d*)/g, ': <span style="color: #FF5A26;">$1</span>');
        }

        // ── Tool Usage Renderer ──────────────────────────────────────

        function renderToolUsage(toolUsage) {
            if (!toolUsage || toolUsage.length === 0) return null;

            const toolDiv = document.createElement('div');
            toolDiv.className = 'tool-usage';
            toolDiv.style.marginTop = '10px';

            const header = document.createElement('div');
            header.className = 'tool-usage-header';

            const headerText = document.createElement('span');
            headerText.textContent = '🛠️ Tools Used';

            const toolCount = document.createElement('span');
            toolCount.className = 'tool-count';
            toolCount.textContent = toolUsage.filter(t => t.type === 'tool_use').length;

            header.appendChild(headerText);
            header.appendChild(toolCount);

            const toolContentDiv = document.createElement('div');
            toolContentDiv.className = 'tool-usage-content';

            // Group tool_use with their corresponding tool_result
            const toolCalls = [];
            toolUsage.forEach(tool => {
                if (tool.type === 'tool_use') {
                    toolCalls.push({ use: tool, result: null });
                } else if (tool.type === 'tool_result' && toolCalls.length > 0) {
                    const lastToolWithoutResult = toolCalls.slice().reverse().find(t => !t.result);
                    if (lastToolWithoutResult) lastToolWithoutResult.result = tool;
                }
            });

            toolCalls.forEach(toolCall => {
                const toolItem = document.createElement('div');
                toolItem.className = 'tool-item';

                const toolName = document.createElement('div');
                toolName.className = 'tool-name';
                toolName.innerHTML = `<span>&#9679;</span> ${escapeHtml(toolCall.use.name)}`;
                toolItem.appendChild(toolName);

                if (toolCall.use.input && Object.keys(toolCall.use.input).length > 0) {
                    const inputLabel = document.createElement('div');
                    inputLabel.style.cssText = 'font-size: 11px; font-weight: 600; color: #929395; margin: 8px 0 4px 0; text-transform: uppercase; letter-spacing: 0.5px;';
                    inputLabel.textContent = '↳ Input';
                    toolItem.appendChild(inputLabel);

                    const params = document.createElement('div');
                    params.className = 'tool-params';
                    params.innerHTML = formatJSON(toolCall.use.input);
                    toolItem.appendChild(params);
                }

                if (toolCall.result) {
                    const outputLabel = document.createElement('div');
                    outputLabel.style.cssText = 'font-size: 11px; font-weight: 600; color: #4CD97A; margin: 12px 0 4px 0; text-transform: uppercase; letter-spacing: 0.5px;';
                    outputLabel.textContent = '↳ Output';
                    toolItem.appendChild(outputLabel);

                    const output = document.createElement('div');
                    output.className = 'tool-output';

                    let outputParts = [];
                    if (Array.isArray(toolCall.result.content)) {
                        outputParts = toolCall.result.content.map(c => {
                            let raw = '';
                            if (typeof c === 'object' && c.type === 'text') raw = c.text;
                            else if (typeof c === 'string') raw = c;
                            else return { parsed: c };
                            try { return { parsed: JSON.parse(raw) }; } catch (_) {}
                            return { text: raw };
                        });
                    } else if (typeof toolCall.result.content === 'string') {
                        try { outputParts = [{ parsed: JSON.parse(toolCall.result.content) }]; }
                        catch (_) { outputParts = [{ text: toolCall.result.content }]; }
                    } else {
                        outputParts = [{ parsed: toolCall.result.content }];
                    }

                    outputParts.forEach(part => {
                        const fragment = document.createElement('div');
                        if (part.parsed !== undefined) {
                            fragment.innerHTML = formatJSON(part.parsed);
                        } else {
                            fragment.textContent = part.text;
                        }
                        output.appendChild(fragment);
                    });

                    toolItem.appendChild(output);
                }

                toolContentDiv.appendChild(toolItem);
            });

            header.addEventListener('click', () => {
                toolContentDiv.classList.toggle('expanded');
            });

            toolDiv.appendChild(header);
            toolDiv.appendChild(toolContentDiv);
            return toolDiv;
        }

        // ── Token & Model Loading ─────────────────────────────────────

        async function loadAvailableModels() {
            try {
                const resp = await fetch('/api/models?enabled_only=true');
                if (!resp.ok) return;
                const data = await resp.json();
                const models = data.models || [];
                if (models.length > 0) {
                    allModels = models;
                    dynamicModels = {};
                    models.forEach(m => {
                        dynamicModels[m.model_id] = {
                            name: m.display_name,
                            context: m.context_window || 200000,
                            inputPrice: m.input_price || 0,
                            outputPrice: m.output_price || 0,
                            provider: m.provider,
                            token_id: m.token_id,
                        };
                    });
                }
            } catch (error) {
                console.error('Failed to load models:', error);
            }
        }

        async function loadAvailableTokens() {
            try {
                const response = await fetch('/api/tokens');
                if (!response.ok) return;
                const data = await response.json();
                allTokens = data.tokens || [];
                renderClientSelectors();
            } catch (error) {
                console.error('Failed to load tokens:', error);
            }
        }

        function renderClientSelectors() {
            ['left', 'right'].forEach(side => {
                const container = document.getElementById(`${side}ClientSelector`);
                if (!container) return;

                const config = side === 'left' ? leftConfig : rightConfig;

                if (allTokens.length === 0) {
                    container.innerHTML = `<a href="/tokens" style="color: #3533FF; font-size:11px;">Add AI clients</a>`;
                    return;
                }

                const tokenOptions = allTokens.map(t =>
                    `<option value="${t.id}" ${String(t.id) === String(config.token_id || '') ? 'selected' : ''}>${escapeHtml(t.name)} (${t.provider})</option>`
                ).join('');

                const hasToken = !!config.token_id;

                container.innerHTML = `
                    <select id="${side}TokenSelect" title="AI Client" style="flex:1; min-width:0;" onchange="onTokenSelected('${side}')">
                        <option value="">AI Client...</option>
                        ${tokenOptions}
                    </select>
                    <select id="${side}ModelSelect" title="Model" style="flex:1; min-width:0;" onchange="onModelSelected('${side}')" ${!hasToken ? 'disabled' : ''}>
                        <option value="">Model...</option>
                    </select>
                `;

                if (hasToken) {
                    populateModelsForToken(side, config.token_id, config.model_id);
                }
            });
        }

        async function onTokenSelected(side) {
            const select = document.getElementById(`${side}TokenSelect`);
            const tokenId = select.value;
            const config = side === 'left' ? leftConfig : rightConfig;
            config.token_id = tokenId || null;
            config.model_id = null;
            config.provider = null;

            const modelSelect = document.getElementById(`${side}ModelSelect`);
            if (tokenId) {
                populateModelsForToken(side, tokenId, null);
            } else {
                modelSelect.innerHTML = '<option value="">Select model...</option>';
                modelSelect.disabled = true;
                updatePanelLabel(side);
            }
        }
        window.onTokenSelected = onTokenSelected;

        function populateModelsForToken(side, tokenId, preselectedModelId = null) {
            const modelSelect = document.getElementById(`${side}ModelSelect`);
            if (!modelSelect) return;

            const tokenModels = allModels.filter(m => String(m.token_id) === String(tokenId));

            if (tokenModels.length === 0) {
                modelSelect.innerHTML = '<option value="">No models configured</option>';
                modelSelect.disabled = true;
                return;
            }

            modelSelect.innerHTML = tokenModels.map(m =>
                `<option value="${m.model_id}" ${m.model_id === preselectedModelId ? 'selected' : ''}>${escapeHtml(m.display_name)}</option>`
            ).join('');
            modelSelect.disabled = false;

            if (!preselectedModelId || !modelSelect.querySelector(`option[value="${preselectedModelId}"]`)) {
                modelSelect.selectedIndex = 0;
            }

            onModelSelected(side);
        }

        function onModelSelected(side) {
            const modelSelect = document.getElementById(`${side}ModelSelect`);
            if (!modelSelect) return;

            const modelId = modelSelect.value;
            const config = side === 'left' ? leftConfig : rightConfig;
            config.model_id = modelId || null;

            if (dynamicModels && dynamicModels[modelId]) {
                const modelConfig = dynamicModels[modelId];
                config.provider = modelConfig.provider;
                const pricing = {
                    inputPrice:  (modelConfig.inputPrice  || 0) / 1000000,
                    outputPrice: (modelConfig.outputPrice || 0) / 1000000,
                };
                if (side === 'left') leftPricing = pricing;
                else rightPricing = pricing;
            }
            updatePanelLabel(side);
        }
        window.onModelSelected = onModelSelected;

        function updatePanelLabel(side) {
            const prefix = side === 'left' ? 'left' : 'right';
            const nameSpan = document.getElementById(`${prefix}PanelName`);
            if (!nameSpan) return;

            const tokenSelect = document.getElementById(`${prefix}TokenSelect`);
            const modelSelect = document.getElementById(`${prefix}ModelSelect`);

            const parts = [];
            if (tokenSelect && tokenSelect.value) {
                const opt = tokenSelect.options[tokenSelect.selectedIndex];
                if (opt) parts.push(opt.text);
            }
            if (modelSelect && modelSelect.value) {
                const opt = modelSelect.options[modelSelect.selectedIndex];
                if (opt) parts.push(opt.text);
            }

            nameSpan.textContent = parts.length ? '— ' + parts.join(' / ') : '';
        }

        // ── MCP Server Loading ────────────────────────────────────────

        async function loadMcpServers() {
            try {
                const response = await fetch('/api/mcp/credentials');
                if (response.ok) {
                    const data = await response.json();
                    mcpServers = Object.entries(data.servers || {}).map(([id, server]) => ({ ...server, id }));
                    mcpServers.forEach(server => {
                        if (server.auth_method && !server.auth_type) server.auth_type = server.auth_method;
                        else if (server.auth_type && !server.auth_method) server.auth_method = server.auth_type;
                    });
                    renderMcpSelectors();
                }
            } catch (error) {
                console.error('Failed to load MCP servers:', error);
            }
        }

        function renderMcpSelectors() {
            const leftSelector  = document.getElementById('leftMcpSelector');
            const rightSelector = document.getElementById('rightMcpSelector');

            if (mcpServers.length === 0) {
                const noMsg = '<a href="/connections" style="color: #3533FF; font-size:11px;">Add MCP</a>';
                leftSelector.innerHTML  = noMsg;
                rightSelector.innerHTML = noMsg;
                return;
            }

            const optionsHtml = '<option value="">No MCP</option>' +
                mcpServers.map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');

            const leftSelected  = leftConfig.enabled_servers?.[0]  || '';
            const rightSelected = rightConfig.enabled_servers?.[0] || '';

            leftSelector.innerHTML = `
                <select id="leftMcpSelect" title="MCP Server" style="width:100%; min-width:0;" onchange="updateMcpConfig('left', this.value)">
                    ${optionsHtml}
                </select>
            `;
            rightSelector.innerHTML = `
                <select id="rightMcpSelect" title="MCP Server" style="width:100%; min-width:0;" onchange="updateMcpConfig('right', this.value)">
                    ${optionsHtml}
                </select>
            `;

            if (leftSelected)  document.getElementById('leftMcpSelect').value  = leftSelected;
            if (rightSelected) document.getElementById('rightMcpSelect').value = rightSelected;
        }

        function updateMcpConfig(side, serverId) {
            const config = side === 'left' ? leftConfig : rightConfig;
            config.servers = [];
            config.enabled_servers = [];
            if (serverId) {
                const server = mcpServers.find(s => s.id === serverId);
                if (server) {
                    config.servers = [server];
                    config.enabled_servers = [serverId];
                }
            }
        }

        // ── New Comparison ────────────────────────────────────────────

        function startNewComparison() {
            comparisonSessionId = `comparison_${Date.now()}`;
            leftSessionId  = `${comparisonSessionId}_left`;
            rightSessionId = `${comparisonSessionId}_right`;

            // Preserve token/model but reset MCP server selections
            leftConfig  = { ...leftConfig,  servers: [], enabled_servers: [] };
            rightConfig = { ...rightConfig, servers: [], enabled_servers: [] };

            comparisonData = {
                left:  { messages: [], totalTokens: 0, totalTime: 0, totalCost: 0, conversationHistory: [] },
                right: { messages: [], totalTokens: 0, totalTime: 0, totalCost: 0, conversationHistory: [] }
            };

            // Clear note field
            const noteInput = document.getElementById('comparisonNote');
            if (noteInput) noteInput.value = '';

            document.getElementById('leftMessages').innerHTML  = '';
            document.getElementById('rightMessages').innerHTML = '';

            updateMetrics('left');
            updateMetrics('right');
            updateComparisonSummary();
            updateComparisonSessionInfo();
            renderMcpSelectors();

            showError('New comparison started!', false);
        }

        function resetComparison() {
            if (comparisonData.left.messages.length > 0 || comparisonData.right.messages.length > 0) {
                if (!confirm('Reset the current comparison? All unsaved progress will be lost.')) return;
            }

            comparisonData = {
                left:  { messages: [], totalTokens: 0, totalTime: 0, totalCost: 0, conversationHistory: [] },
                right: { messages: [], totalTokens: 0, totalTime: 0, totalCost: 0, conversationHistory: [] }
            };

            document.getElementById('leftMessages').innerHTML  = '';
            document.getElementById('rightMessages').innerHTML = '';

            updateMetrics('left');
            updateMetrics('right');
            updateComparisonSummary();
            updateComparisonSessionInfo();

            showError('Comparison reset!', false);
        }
        window.resetComparison = resetComparison;

        // ── Send Flow ─────────────────────────────────────────────────

        async function sendComparison() {
            const userMessage = document.getElementById('userInput').value.trim();

            if (!leftConfig.token_id && !rightConfig.token_id) {
                showError('Please select an AI Client for at least one configuration');
                return;
            }

            if (!userMessage) {
                showError('Please enter a message');
                return;
            }

            if (!comparisonSessionId) startNewComparison();

            addMessage('left',  'user', userMessage);
            addMessage('right', 'user', userMessage);
            document.getElementById('userInput').value = '';

            const promises = [];
            if (leftConfig.token_id) {
                promises.push(sendToConfig('left', userMessage));
            } else {
                addMessage('left', 'assistant', '(No AI Client selected for Config A)');
            }
            if (rightConfig.token_id) {
                promises.push(sendToConfig('right', userMessage));
            } else {
                addMessage('right', 'assistant', '(No AI Client selected for Config B)');
            }

            await Promise.all(promises);
            updateComparisonSummary();
        }

        async function sendToConfig(side, userMessage) {
            const config    = side === 'left' ? leftConfig  : rightConfig;
            const pricing   = side === 'left' ? leftPricing : rightPricing;
            const sessionId = side === 'left' ? leftSessionId : rightSessionId;
            const data      = comparisonData[side];

            const loadingId = addMessage(side, 'assistant', '<div class="loading"></div>');
            const startTime = Date.now();

            try {
                // Use server-provided conversation history when available (preserves tool call context)
                let messages;
                if (data.conversationHistory.length > 0) {
                    messages = [...data.conversationHistory, { role: 'user', content: userMessage }];
                } else {
                    // Reconstruct from stored messages (fallback / first load of saved session)
                    messages = [];
                    data.messages.forEach(msg => {
                        messages.push({ role: 'user', content: msg.userMessage });
                        if (msg.response && msg.response.content) {
                            const text = msg.response.content
                                .filter(b => b.type === 'text')
                                .map(b => b.text)
                                .join('\n\n');
                            messages.push({ role: 'assistant', content: text });
                        }
                    });
                    messages.push({ role: 'user', content: userMessage });
                }

                const payload = {
                    model:            config.model_id || 'claude-sonnet-4-20250514',
                    max_tokens:       8000,
                    messages:         messages,
                    session_id:       sessionId,
                    servers:          config.servers,
                    enabled_servers:  config.enabled_servers,
                };

                if (config.token_id) payload.token_id = config.token_id;
                if (config.provider) payload.provider  = config.provider;

                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify(payload)
                });

                const duration = (Date.now() - startTime) / 1000;

                if (!response.ok) {
                    const error = await response.json();
                    removeMessage(side, loadingId);
                    addMessage(side, 'assistant', `❌ Error: ${error.error || 'Unknown error'}`);
                    return;
                }

                const result = await response.json();
                removeMessage(side, loadingId);

                // Update conversation history from server (preserves tool call role alternation)
                if (result.conversation_history && result.conversation_history.length > 0) {
                    data.conversationHistory = result.conversation_history;
                } else {
                    data.conversationHistory.push(
                        { role: 'user', content: userMessage },
                        { role: 'assistant', content: result.content || [] }
                    );
                }

                // Process content blocks into segments (text + tools interleaved, with thinking)
                const contentSegments = processContentBlocks(result.content || []);
                addMessage(side, 'assistant', contentSegments);

                // Dynamic cost calculation using per-side model pricing
                const inputTokens  = result.usage?.input_tokens  || 0;
                const outputTokens = result.usage?.output_tokens || 0;
                const tokens = inputTokens + outputTokens;
                const cost   = (inputTokens * pricing.inputPrice) + (outputTokens * pricing.outputPrice);

                data.totalTokens += tokens;
                data.totalTime   += duration;
                data.totalCost   += cost;
                data.messages.push({
                    timestamp:   new Date().toISOString(),
                    userMessage,
                    response:    result,
                    duration,
                    tokens,
                    cost
                });

                updateMetrics(side);
                await saveComparisonSession();

            } catch (error) {
                removeMessage(side, loadingId);
                addMessage(side, 'assistant', `❌ Error: ${error.message}`);
                console.error(`Error sending to ${side}:`, error);
            }
        }

        function processContentBlocks(blocks) {
            const segments = [];
            let current = { content: '', tools: [], thinking: '' };

            for (const block of blocks) {
                if (block.type === 'text') {
                    if (current.tools.length > 0) {
                        segments.push(current);
                        current = { content: '', tools: [], thinking: '' };
                    }
                    current.content += block.text;
                } else if (block.type === 'thinking') {
                    current.thinking += block.thinking || '';
                } else if (block.type === 'mcp_tool_use' || block.type === 'tool_use') {
                    current.tools.push({ type: 'tool_use', name: block.name, input: block.input });
                } else if (block.type === 'mcp_tool_result' || block.type === 'tool_result') {
                    current.tools.push({ type: 'tool_result', tool_use_id: block.tool_use_id, content: block.content });
                }
            }

            if (current.content || current.tools.length > 0 || current.thinking) {
                segments.push(current);
            }

            if (segments.length === 0) {
                segments.push({ content: '(No text response)', tools: [], thinking: '' });
            }

            return segments;
        }

        // ── Message Rendering ─────────────────────────────────────────

        function addMessage(side, role, content, toolUsage = []) {
            const container = document.getElementById(side === 'left' ? 'leftMessages' : 'rightMessages');
            const messageDiv = document.createElement('div');
            const messageId  = `${side}-msg-${Date.now()}-${Math.random()}`;
            messageDiv.id        = messageId;
            messageDiv.className = `message message-${role}`;

            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content';

            if (role === 'assistant' && Array.isArray(content)) {
                // Segment-based format (new)
                content.forEach((segment, index) => {
                    if (segment.thinking && segment.thinking.trim()) {
                        const thinkingDiv = document.createElement('div');
                        thinkingDiv.style.cssText = 'background: #E8F9FF; border-left: 3px solid #33B6FF; padding: 12px; margin: 10px 0; border-radius: 4px; font-size: 13px; color: #3533FF;';
                        thinkingDiv.innerHTML = `<div style="font-weight: 600; margin-bottom: 6px;">🤔 Thinking</div><div style="opacity: 0.9; white-space: pre-wrap;">${escapeHtml(segment.thinking)}</div>`;
                        contentDiv.appendChild(thinkingDiv);
                    }

                    if (segment.content && segment.content.trim()) {
                        const textDiv = document.createElement('div');
                        textDiv.innerHTML = marked.parse(segment.content);
                        renderMermaidBlocks(textDiv);
                        if (index > 0) textDiv.style.marginTop = '15px';
                        contentDiv.appendChild(textDiv);
                    }

                    if (segment.tools && segment.tools.length > 0) {
                        const toolDiv = renderToolUsage(segment.tools);
                        if (toolDiv) contentDiv.appendChild(toolDiv);
                    }
                });
            } else if (role === 'assistant' && typeof content === 'string' && !content.includes('loading')) {
                // Plain string (error message, etc.)
                const textDiv = document.createElement('div');
                textDiv.innerHTML = marked.parse(content);
                renderMermaidBlocks(textDiv);
                contentDiv.appendChild(textDiv);
                if (toolUsage.length > 0) {
                    const toolDiv = renderToolUsage(toolUsage);
                    if (toolDiv) contentDiv.appendChild(toolDiv);
                }
            } else if (role === 'user') {
                const textDiv = document.createElement('div');
                textDiv.textContent = content;
                textDiv.style.whiteSpace = 'pre-wrap';
                contentDiv.appendChild(textDiv);
            } else {
                // Loading spinner or raw HTML (e.g. from old saved sessions)
                contentDiv.innerHTML = content;
            }

            messageDiv.appendChild(contentDiv);
            container.appendChild(messageDiv);
            container.scrollTop = container.scrollHeight;
            return messageId;
        }

        function removeMessage(side, messageId) {
            const element = document.getElementById(messageId);
            if (element) element.remove();
        }

        function renderMessages(side) {
            const container = document.getElementById(side === 'left' ? 'leftMessages' : 'rightMessages');
            container.innerHTML = '';

            const messages = comparisonData[side].messages || [];
            messages.forEach(msg => {
                if (msg.userMessage) addMessage(side, 'user', msg.userMessage);
                if (msg.response && msg.response.content) {
                    const segments = processContentBlocks(msg.response.content);
                    addMessage(side, 'assistant', segments);
                }
            });
        }

        // ── Metrics ───────────────────────────────────────────────────

        function updateMetrics(side) {
            const data = comparisonData[side];
            document.getElementById(`${side}Tokens`).textContent = data.totalTokens.toLocaleString();
            document.getElementById(`${side}Time`).textContent   = `${data.totalTime.toFixed(2)}s`;
            document.getElementById(`${side}Cost`).textContent   = `$${data.totalCost.toFixed(4)}`;
            updateMessageCounts();
        }

        function updateMessageCounts() {
            document.getElementById('leftMessageCount').textContent  = comparisonData.left.messages.length;
            document.getElementById('rightMessageCount').textContent = comparisonData.right.messages.length;
        }

        function updateComparisonSummary() {
            const metricsContainer = document.getElementById('sidebarComparisonMetrics');
            const left  = comparisonData.left;
            const right = comparisonData.right;

            const tokenDiff  = Math.abs(left.totalTokens - right.totalTokens);
            const tokenWinner = left.totalTokens < right.totalTokens ? '🟢 A' : '🔵 B';
            const tokenColor  = left.totalTokens < right.totalTokens ? '#4CD97A' : '#33B6FF';
            const tokenBg     = left.totalTokens < right.totalTokens ? '#EDFFF3' : '#E8F9FF';

            const timeDiff  = Math.abs(left.totalTime - right.totalTime);
            const timeWinner = left.totalTime < right.totalTime ? '🟢 A' : '🔵 B';
            const timeColor  = left.totalTime < right.totalTime ? '#4CD97A' : '#33B6FF';
            const timeBg     = left.totalTime < right.totalTime ? '#EDFFF3' : '#E8F9FF';

            const costDiff  = Math.abs(left.totalCost - right.totalCost);
            const costWinner = left.totalCost < right.totalCost ? '🟢 A' : '🔵 B';
            const costColor  = left.totalCost < right.totalCost ? '#4CD97A' : '#33B6FF';
            const costBg     = left.totalCost < right.totalCost ? '#EDFFF3' : '#E8F9FF';

            metricsContainer.innerHTML = `
                <div class="comparison-summary-card tokens" style="background: ${tokenBg}; border-left: 4px solid ${tokenColor};">
                    <div class="summary-label" style="color: ${tokenColor};">Token Difference</div>
                    <div class="summary-value">${tokenDiff.toLocaleString()}</div>
                    <div style="font-size: 12px; color: ${tokenColor}; margin-top: 5px; font-weight: 600;">${tokenWinner} wins</div>
                </div>
                <div class="comparison-summary-card time" style="background: ${timeBg}; border-left: 4px solid ${timeColor};">
                    <div class="summary-label" style="color: ${timeColor};">Time Difference</div>
                    <div class="summary-value">${timeDiff.toFixed(2)}s</div>
                    <div style="font-size: 12px; color: ${timeColor}; margin-top: 5px; font-weight: 600;">${timeWinner} wins</div>
                </div>
                <div class="comparison-summary-card cost" style="background: ${costBg}; border-left: 4px solid ${costColor};">
                    <div class="summary-label" style="color: ${costColor};">Cost Difference</div>
                    <div class="summary-value">$${costDiff.toFixed(4)}</div>
                    <div style="font-size: 12px; color: ${costColor}; margin-top: 5px; font-weight: 600;">${costWinner} wins</div>
                </div>
            `;
        }

        // ── Session Management ────────────────────────────────────────

        function updateComparisonSessionInfo() {
            const infoDiv = document.getElementById('currentSessionInfo');
            const noteContainer = document.getElementById('sessionNoteContainer');
            if (!infoDiv) return;

            if (comparisonSessionId) {
                const leftMsgCount  = comparisonData.left.messages.length;
                const rightMsgCount = comparisonData.right.messages.length;
                const messageCount  = Math.max(leftMsgCount, rightMsgCount);
                const totalTokens   = comparisonData.left.totalTokens + comparisonData.right.totalTokens;
                const lastMsg = comparisonData.left.messages.length > 0
                    ? comparisonData.left.messages[comparisonData.left.messages.length - 1]
                    : comparisonData.right.messages.length > 0
                        ? comparisonData.right.messages[comparisonData.right.messages.length - 1]
                        : null;
                const lastSaved = lastMsg ? new Date(lastMsg.timestamp).toLocaleTimeString() : 'Not saved yet';
                infoDiv.innerHTML = `
                    <div style="font-weight: 600; margin-bottom: 4px; font-size: 12px; color: #000000;">${comparisonSessionId}</div>
                    <div style="font-size: 11px; color: #929395; margin-bottom: 4px;">${messageCount} exchanges · ${totalTokens.toLocaleString()} tokens</div>
                    <div style="font-size: 10px; color: #4CD97A; display: flex; align-items: center; justify-content: center; gap: 4px;">
                        <span style="font-size: 14px;"></span> Auto-saved ${lastMsg ? 'at ' + lastSaved : ''}
                    </div>
                `;
                if (noteContainer) noteContainer.style.display = 'block';
            } else {
                infoDiv.innerHTML = 'No active session';
                if (noteContainer) noteContainer.style.display = 'none';
            }
        }

        async function saveComparisonSession() {
            if (!comparisonSessionId) return;
            try {
                const noteInput = document.getElementById('comparisonNote');
                const comparisonNote = noteInput ? noteInput.value.trim() : '';

                const sessionData = {
                    session_id:       comparisonSessionId,
                    timestamp:        new Date().toISOString(),
                    type:             'comparison',
                    note:             comparisonNote,
                    left_session_id:  leftSessionId,
                    right_session_id: rightSessionId,
                    left_config:      leftConfig,
                    right_config:     rightConfig,
                    left_data:        comparisonData.left,
                    right_data:       comparisonData.right,
                    summary: {
                        token_difference: Math.abs(comparisonData.left.totalTokens - comparisonData.right.totalTokens),
                        time_difference:  Math.abs(comparisonData.left.totalTime   - comparisonData.right.totalTime),
                        cost_difference:  Math.abs(comparisonData.left.totalCost   - comparisonData.right.totalCost)
                    }
                };

                const resp = await fetch('/api/sessions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(sessionData)
                });
                if (!resp.ok) {
                    const errData = await resp.json().catch(() => ({}));
                    console.error('Save comparison failed:', resp.status, errData);
                }
                updateComparisonSessionInfo();
            } catch (error) {
                console.error('Failed to save comparison session:', error);
            }
        }

        async function showComparisonHistory() {
            try {
                const response = await fetch('/api/sessions');
                const data = await response.json();
                const sessions = data.sessions || [];

                const comparisonSessions = sessions.filter(s =>
                    s.type === 'comparison' &&
                    s.id &&
                    s.id.startsWith('comparison_') &&
                    !s.id.includes('_left') &&
                    !s.id.includes('_right')
                );

                if (comparisonSessions.length === 0) {
                    showError('No comparison sessions found', false);
                    return;
                }

                const fullSessions = await Promise.all(
                    comparisonSessions.map(async (s) => {
                        const fullResponse = await fetch(`/api/sessions/${s.id}`);
                        return await fullResponse.json();
                    })
                );

                displayComparisonSessions(fullSessions);
                document.getElementById('loadModal').style.display = 'block';
            } catch (error) {
                console.error('Failed to load comparison sessions:', error);
                showError('Failed to load comparison sessions');
            }
        }

        function displayComparisonSessions(sessions) {
            const sessionList = document.getElementById('sessionList');

            let html = `<input type="text" id="comparisonSearchInput" placeholder="🔍 Search by session ID or note..."
                style="width: 100%; padding: 12px 16px; border: 2px solid #C7C9CA; border-radius: 8px; font-size: 14px; margin-bottom: 15px; transition: border-color 0.2s;"
                onfocus="this.style.borderColor='#3533FF'" onblur="this.style.borderColor='#C7C9CA'"
                oninput="filterComparisonSessions(this.value)">`;

            html += sessions.map(session => {
                const date = new Date(session.timestamp);
                const leftNames  = (session.left_config?.servers  || []).map(s => s.name).filter(Boolean);
                const rightNames = (session.right_config?.servers || []).map(s => s.name).filter(Boolean);
                const leftName   = leftNames.length  > 0 ? leftNames.join(', ')  : 'Baseline';
                const rightName  = rightNames.length > 0 ? rightNames.join(', ') : 'Baseline';

                // Show AI client labels if available
                const leftToken  = allTokens.find(t => String(t.id) === String(session.left_config?.token_id));
                const rightToken = allTokens.find(t => String(t.id) === String(session.right_config?.token_id));
                const leftClient  = leftToken  ? `${leftToken.name} / ${session.left_config?.model_id  || ''}` : (session.left_config?.model_id  || 'N/A');
                const rightClient = rightToken ? `${rightToken.name} / ${session.right_config?.model_id || ''}` : (session.right_config?.model_id || 'N/A');

                const leftTokens  = session.left_data?.totalTokens  || 0;
                const rightTokens = session.right_data?.totalTokens || 0;
                const leftTime    = session.left_data?.totalTime    || 0;
                const rightTime   = session.right_data?.totalTime   || 0;
                const leftCost    = session.left_data?.totalCost    || 0;
                const rightCost   = session.right_data?.totalCost   || 0;
                const messageCount = session.left_data?.messages?.length || 0;

                const noteDisplay = session.note
                    ? `<div style="font-size: 12px; color: #3533FF; margin-top: 8px; padding: 6px 10px; background: #E8F9FF; border-radius: 6px; display: inline-block; font-weight: 500;">📝 ${escapeHtml(session.note)}</div>`
                    : '';

                return `
                    <div class="session-item" data-session-id="${(session.session_id || '').toLowerCase()}" data-note="${(session.note || '').toLowerCase()}">
                        <div onclick="loadComparison('${session.session_id}')">
                            <div class="session-header-row" style="padding-right: 100px;">
                                <span class="session-id">${escapeHtml(session.session_id)}</span>
                                <span class="session-timestamp">${date.toLocaleDateString()} ${date.toLocaleTimeString()}</span>
                            </div>
                            ${noteDisplay}
                            <div class="comparison-configs">
                                <div>
                                    <div class="config-label">Config A: ${escapeHtml(leftClient)}</div>
                                    <div style="color: #767676; font-size: 12px; margin-top: 2px;">MCP: ${escapeHtml(leftName)}</div>
                                    <div style="color: #929395; margin-top: 4px;">${leftTokens.toLocaleString()} tokens · ${leftTime.toFixed(2)}s · $${leftCost.toFixed(4)}</div>
                                </div>
                                <div class="vs-divider">VS</div>
                                <div>
                                    <div class="config-label">Config B: ${escapeHtml(rightClient)}</div>
                                    <div style="color: #767676; font-size: 12px; margin-top: 2px;">MCP: ${escapeHtml(rightName)}</div>
                                    <div style="color: #929395; margin-top: 4px;">${rightTokens.toLocaleString()} tokens · ${rightTime.toFixed(2)}s · $${rightCost.toFixed(4)}</div>
                                </div>
                            </div>
                            <div class="comparison-stats">
                                <div class="stat-item"><span class="stat-label">Messages:</span><span class="stat-value">${messageCount}</span></div>
                                <div class="stat-item"><span class="stat-label">Token Diff:</span><span class="stat-value">${Math.abs(leftTokens - rightTokens).toLocaleString()}</span></div>
                                <div class="stat-item"><span class="stat-label">Time Diff:</span><span class="stat-value">${Math.abs(leftTime - rightTime).toFixed(2)}s</span></div>
                                <div class="stat-item"><span class="stat-label">Cost Diff:</span><span class="stat-value">$${Math.abs(leftCost - rightCost).toFixed(4)}</span></div>
                            </div>
                        </div>
                        <button onclick="event.stopPropagation(); deleteComparisonSession('${session.session_id}', this.closest('.session-item'))"
                                style="position: absolute; top: 20px; right: 20px; padding: 6px 12px; background: #FF5A26; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 500; transition: background 0.2s;"
                                onmouseover="this.style.background='#CC4820'"
                                onmouseout="this.style.background='#FF5A26'"
                                title="Delete this comparison session">
                            🗑️ Delete
                        </button>
                    </div>
                `;
            }).join('');

            sessionList.innerHTML = html;
        }

        function filterComparisonSessions(searchTerm) {
            const items = document.querySelectorAll('.session-item');
            const term  = searchTerm.toLowerCase();
            items.forEach(item => {
                const sessionId = item.getAttribute('data-session-id') || '';
                const note      = item.getAttribute('data-note') || '';
                item.style.display = (sessionId.includes(term) || note.includes(term)) ? 'block' : 'none';
            });
        }

        async function deleteComparisonSession(sessionId, sessionElement) {
            if (!confirm(`Are you sure you want to delete comparison session "${sessionId}"?\n\nThis action cannot be undone.`)) return;

            try {
                const response = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
                if (!response.ok) throw new Error('Failed to delete comparison session');

                sessionElement.style.opacity   = '0';
                sessionElement.style.transform = 'translateX(-20px)';
                sessionElement.style.transition = 'opacity 0.3s, transform 0.3s';

                setTimeout(() => {
                    sessionElement.remove();
                    const remaining = document.querySelectorAll('.session-item');
                    if (remaining.length === 0) {
                        const list = document.getElementById('sessionList');
                        if (list) list.innerHTML = '<div style="text-align: center; padding: 40px; color: #929395; font-size: 14px;">No comparison sessions available</div>';
                    }
                }, 300);

                showError(`✅ Comparison session "${sessionId}" deleted successfully`, false);
            } catch (error) {
                showError(`Error deleting comparison session: ${error.message}`);
                console.error('Delete comparison session error:', error);
            }
        }
        window.deleteComparisonSession = deleteComparisonSession;

        async function loadComparison(sessionId) {
            try {
                const response = await fetch(`/api/sessions/${sessionId}`);
                const session  = await response.json();

                comparisonSessionId = session.session_id;
                leftSessionId       = session.left_session_id;
                rightSessionId      = session.right_session_id;

                leftConfig  = session.left_config  || { servers: [], enabled_servers: [], token_id: null, model_id: null, provider: null };
                rightConfig = session.right_config || { servers: [], enabled_servers: [], token_id: null, model_id: null, provider: null };

                comparisonData.left  = { ...(session.left_data  || { messages: [], totalTokens: 0, totalTime: 0, totalCost: 0 }), conversationHistory: [] };
                comparisonData.right = { ...(session.right_data || { messages: [], totalTokens: 0, totalTime: 0, totalCost: 0 }), conversationHistory: [] };

                const noteInput = document.getElementById('comparisonNote');
                if (noteInput && session.note) noteInput.value = session.note;

                // Re-render selectors with restored configuration
                renderClientSelectors();
                renderMcpSelectors();

                // Restore pricing based on restored model selections
                ['left', 'right'].forEach(side => {
                    const config = side === 'left' ? leftConfig : rightConfig;
                    if (config.model_id && dynamicModels && dynamicModels[config.model_id]) {
                        const mc = dynamicModels[config.model_id];
                        const pricing = { inputPrice: (mc.inputPrice || 0) / 1000000, outputPrice: (mc.outputPrice || 0) / 1000000 };
                        if (side === 'left') leftPricing = pricing;
                        else rightPricing = pricing;
                    }
                });

                renderMessages('left');
                renderMessages('right');
                updateMetrics('left');
                updateMetrics('right');
                updateComparisonSummary();
                updateComparisonSessionInfo();
                updatePanelLabel('left');
                updatePanelLabel('right');

                closeLoadModal();
                showError('Comparison session loaded successfully!', false);
            } catch (error) {
                console.error('Failed to load comparison:', error);
                showError('Failed to load comparison session');
            }
        }

        function closeLoadModal() {
            document.getElementById('loadModal').style.display = 'none';
        }

        window.onclick = function(event) {
            const modal = document.getElementById('loadModal');
            if (event.target === modal) closeLoadModal();
        };

        // ── Error Display ─────────────────────────────────────────────

        function showError(message, isError = true) {
            const container = document.getElementById('errorContainer');
            container.innerHTML = `<div class="error-message" style="background: ${isError ? '#FFF0EC' : '#D4FFE2'}; color: ${isError ? '#CC4820' : '#3BB366'}; border-left-color: ${isError ? '#FF5A26' : '#4CD97A'}">${escapeHtml(message)}</div>`;
            setTimeout(() => { container.innerHTML = ''; }, 3000);
        }

        // ── Input Handlers ────────────────────────────────────────────

        function handleKeyPress(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendComparison();
            }
        }

        // ── Message History & Details ─────────────────────────────────

        function showMessageHistory(side) {
            const modal   = document.getElementById('messageHistoryModal');
            const content = document.getElementById('messageHistoryContent');
            const title   = document.getElementById('historyModalTitle');

            const data       = comparisonData[side];
            const configName = side === 'left' ? '🟢 Configuration A' : '🔵 Configuration B';
            title.textContent = `${configName} - Message History`;

            if (!data.messages || data.messages.length === 0) {
                content.innerHTML = '<p style="text-align: center; color: #929395; padding: 40px;">No messages yet. Send a message to start.</p>';
                modal.style.display = 'block';
                return;
            }

            const bgColor     = side === 'left' ? '#EDFFF3' : '#E8F9FF';
            const borderColor = side === 'left' ? '#4CD97A' : '#33B6FF';

            let html = '<div style="display: flex; flex-direction: column; gap: 12px;">';
            data.messages.forEach((msg, index) => {
                const timestamp       = new Date(msg.timestamp).toLocaleString();
                const userPreview     = msg.userMessage.substring(0, 80) + (msg.userMessage.length > 80 ? '...' : '');
                const assistantBlocks = msg.response?.content?.filter(b => b.type === 'text').map(b => b.text).join(' ') || '';
                const assistantPreview = assistantBlocks.substring(0, 80) + (assistantBlocks.length > 80 ? '...' : '') || 'No response';

                html += `
                    <div style="background: ${bgColor}; border: 2px solid ${borderColor}; border-left: 4px solid ${borderColor}; border-radius: 8px; padding: 15px; cursor: pointer; transition: transform 0.2s;"
                         onclick="showMessageDetails('${side}', ${index})"
                         onmouseover="this.style.transform='scale(1.02)'"
                         onmouseout="this.style.transform='scale(1)'">
                        <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 10px;">
                            <div style="font-weight: 600; font-size: 14px; color: #000000;">Message #${index + 1}</div>
                            <div style="font-size: 11px; color: #929395;">${timestamp}</div>
                        </div>
                        <div style="margin-bottom: 8px;">
                            <div style="font-size: 11px; font-weight: 600; color: #929395; margin-bottom: 4px;">USER:</div>
                            <div style="font-size: 12px; color: #767676;">${escapeHtml(userPreview)}</div>
                        </div>
                        <div>
                            <div style="font-size: 11px; font-weight: 600; color: #929395; margin-bottom: 4px;">ASSISTANT:</div>
                            <div style="font-size: 12px; color: #767676;">${escapeHtml(assistantPreview)}</div>
                        </div>
                        <div style="display: flex; gap: 15px; margin-top: 10px; font-size: 11px; color: #929395;">
                            <span>⏱️ ${msg.duration.toFixed(2)}s</span>
                            <span>📊 ${msg.tokens.toLocaleString()} tokens</span>
                            <span>💰 $${msg.cost.toFixed(4)}</span>
                        </div>
                    </div>
                `;
            });
            html += '</div>';
            content.innerHTML = html;
            modal.style.display = 'block';
        }

        function closeMessageHistoryModal() {
            document.getElementById('messageHistoryModal').style.display = 'none';
        }

        function showMessageDetails(side, messageIndex) {
            const data    = comparisonData[side];
            const message = data.messages[messageIndex];
            if (!message) { showError('Message not found'); return; }

            const modal   = document.getElementById('messageDetailsModal');
            const content = document.getElementById('messageDetailsContent');

            const configName = side === 'left' ? '🟢 Configuration A' : '🔵 Configuration B';
            const timestamp  = new Date(message.timestamp).toLocaleString();

            const usedMcpServers = new Set();
            let toolCount = 0;
            if (message.response?.content) {
                message.response.content.forEach(block => {
                    if (block.type === 'tool_use' || block.type === 'mcp_tool_use') {
                        toolCount++;
                        if (block.name && block.name.includes('_')) {
                            usedMcpServers.add(block.name.split('_')[0]);
                        }
                    }
                });
            }
            const mcpServersList = Array.from(usedMcpServers).sort().join(', ') || 'None';

            const config = side === 'left' ? leftConfig : rightConfig;
            const clientName = (() => {
                const token = allTokens.find(t => String(t.id) === String(config.token_id));
                return token ? `${token.name} (${token.provider})` : 'N/A';
            })();

            let html = `
                <div style="margin-bottom: 20px; padding: 12px; background: ${side === 'left' ? '#EDFFF3' : '#E8F9FF'}; border-radius: 6px; border-left: 4px solid ${side === 'left' ? '#4CD97A' : '#33B6FF'};">
                    <h3 style="margin: 0 0 5px 0; font-size: 16px;">${configName}</h3>
                    <div style="font-size: 12px; color: #929395;">Message #${messageIndex + 1}</div>
                </div>

                <div style="margin-bottom: 20px;">
                    <h3 style="margin: 0 0 10px 0; color: #000000;">Overview</h3>
                    <div style="background: #F4F4F4; padding: 12px; border-radius: 6px;">
                        <div style="display: grid; grid-template-columns: 150px 1fr; gap: 8px; font-size: 13px;">
                            <div style="font-weight: 600; color: #929395;">Timestamp:</div>
                            <div>${timestamp}</div>
                            <div style="font-weight: 600; color: #929395;">AI Client:</div>
                            <div>${escapeHtml(clientName)}</div>
                            <div style="font-weight: 600; color: #929395;">Model:</div>
                            <div>${escapeHtml(message.response?.model || config.model_id || 'N/A')}</div>
                            <div style="font-weight: 600; color: #929395;">Duration:</div>
                            <div>${message.duration.toFixed(3)}s</div>
                            <div style="font-weight: 600; color: #929395;">Message ID:</div>
                            <div style="font-family: monospace; font-size: 11px;">${message.response?.id || 'N/A'}</div>
                            <div style="font-weight: 600; color: #929395;">Stop Reason:</div>
                            <div>${message.response?.stop_reason || 'N/A'}</div>
                            <div style="font-weight: 600; color: #929395;">MCP Servers:</div>
                            <div>${escapeHtml(mcpServersList)} ${toolCount > 0 ? '(' + toolCount + ' tools)' : ''}</div>
                        </div>
                    </div>
                </div>

                <div style="margin-bottom: 20px;">
                    <h3 style="margin: 0 0 10px 0; color: #000000;">Token Usage</h3>
                    <div style="background: #EDFFF3; padding: 12px; border-radius: 6px;">
                        <div style="display: grid; grid-template-columns: 150px 1fr; gap: 8px; font-size: 13px;">
                            <div style="font-weight: 600; color: #3BB366;">Input Tokens:</div>
                            <div>${(message.response?.usage?.input_tokens || 0).toLocaleString()}</div>
                            <div style="font-weight: 600; color: #3BB366;">Output Tokens:</div>
                            <div>${(message.response?.usage?.output_tokens || 0).toLocaleString()}</div>
                            <div style="font-weight: 600; color: #3BB366;">Cache Read:</div>
                            <div>${message.response?.usage?.cache_read_input_tokens || 0}</div>
                            <div style="font-weight: 600; color: #3BB366;">Cache Creation:</div>
                            <div>${message.response?.usage?.cache_creation_input_tokens || 0}</div>
                            <div style="font-weight: 600; color: #3BB366;">Total:</div>
                            <div style="font-weight: 600;">${message.tokens.toLocaleString()}</div>
                            <div style="font-weight: 600; color: #3BB366;">Cost:</div>
                            <div style="font-weight: 600;">$${message.cost.toFixed(4)}</div>
                        </div>
                    </div>
                </div>

                <div style="margin-bottom: 20px;">
                    <h3 style="margin: 0 0 10px 0; color: #000000;">User Message</h3>
                    <div style="background: #F4F4F4; padding: 12px; border-radius: 6px;">
                        <pre style="margin: 0; white-space: pre-wrap; word-wrap: break-word; font-size: 13px; line-height: 1.6;">${escapeHtml(message.userMessage)}</pre>
                    </div>
                </div>

                <div style="margin-bottom: 20px;">
                    <h3 style="margin: 0 0 10px 0; color: #000000;">Response Content</h3>
                    <div style="background: #F4F4F4; padding: 12px; border-radius: 6px; position: relative;">
                        <button onclick="copyToClipboard('response-content-${side}-${messageIndex}')" style="position: absolute; top: 8px; right: 8px; padding: 4px 8px; background: #3533FF; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px;">Copy</button>
                        <pre id="response-content-${side}-${messageIndex}" style="margin: 0; overflow-x: auto; font-size: 11px; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(JSON.stringify(message.response?.content || [], null, 2))}</pre>
                    </div>
                </div>

                <div style="margin-bottom: 20px;">
                    <h3 style="margin: 0 0 10px 0; color: #000000;">Full Response</h3>
                    <div style="background: #F4F4F4; padding: 12px; border-radius: 6px; position: relative;">
                        <button onclick="copyToClipboard('response-full-${side}-${messageIndex}')" style="position: absolute; top: 8px; right: 8px; padding: 4px 8px; background: #3533FF; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 11px;">Copy</button>
                        <pre id="response-full-${side}-${messageIndex}" style="margin: 0; overflow-x: auto; font-size: 11px; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word;">${escapeHtml(JSON.stringify(message.response || {}, null, 2))}</pre>
                    </div>
                </div>
            `;

            content.innerHTML = html;
            modal.style.display = 'block';
        }

        // ── Initialization ────────────────────────────────────────────

        async function initializeCompare() {
            await loadAvailableModels();
            await Promise.all([loadAvailableTokens(), loadMcpServers()]);
            startNewComparison();
        }

        initializeCompare();
