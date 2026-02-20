        console.log('Script is loading...');

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
                    // Clean up any error SVG mermaid may have injected into the DOM
                    const errSvg = document.getElementById(id);
                    if (errSvg) errSvg.remove();
                    // Leave original code block visible
                }
            }
        }

        // Global state
        let conversationHistory = [];
        let totalInputTokens = 0;
        let totalOutputTokens = 0;
        let CONTEXT_WINDOW = 200000;
        let INPUT_PRICE = 3.00 / 1000000; // per token
        let OUTPUT_PRICE = 15.00 / 1000000; // per token

        // MCP servers state (loaded from backend for selection)
        let mcpServers = [];
        let availableAuthTypes = [];

        // Model definitions (fallback if no models configured in DB)
        const MODEL_CONFIGS = {
            'claude-sonnet-4-20250514': { name: 'Claude Sonnet 4', context: 200000, inputPrice: 3.00, outputPrice: 15.00, provider: 'anthropic' },
            'claude-opus-4-20250514': { name: 'Claude Opus 4', context: 200000, inputPrice: 15.00, outputPrice: 75.00, provider: 'anthropic' },
            'claude-haiku-3-5-20241022': { name: 'Claude Haiku 3.5', context: 200000, inputPrice: 0.80, outputPrice: 4.00, provider: 'anthropic' },
        };
        
        // Dynamic models loaded from DB
        let dynamicModels = null; // null = not loaded yet
        let allModels = []; // All enabled models from DB (unfiltered)
        
        // Session state
        let currentSessionId = null;
        let sessionMessages = []; // Stores full API requests and responses
        let lastTurnInputTokens = 0; // Input tokens from the previous turn (for delta annotation)

        // Initialize app
        async function initializeApp() {
            checkProtocol();
            await loadAuthTypes();
            await loadAvailableTokens();
            await loadAvailableMcpServers();
            await loadAvailableModels();
            
            // Load saved API key from session storage
            const savedApiKey = sessionStorage.getItem('apiKey');
            if (savedApiKey) {
                document.getElementById('apiKey').value = savedApiKey;
            }
            
            // Load saved context window
            const contextWindow = sessionStorage.getItem('contextWindow');
            if (contextWindow) {
                document.getElementById('contextWindow').value = contextWindow;
                CONTEXT_WINDOW = parseInt(contextWindow);
            }
            
            // Start with a new session
            currentSessionId = 'session_' + Date.now();
            updateSessionInfo();
        }
        
        // Start initialization
        initializeApp();

        // Listen for OAuth callback messages from popup window
        window.addEventListener('message', async (event) => {
            if (event.origin !== window.location.origin) return;
            if (event.data && event.data.type === 'oauth_success') {
                console.log('OAuth authorization successful for server:', event.data.server_id);
                await loadAvailableMcpServers();
                showError('OAuth authorization successful! MCP servers refreshed.', false);
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

        // ── Token & MCP Loading for Chat Controls ──────────────────

        async function loadAvailableTokens() {
            try {
                const response = await fetch('/api/tokens');
                if (!response.ok) return;
                const data = await response.json();
                const tokens = data.tokens || [];
                
                const select = document.getElementById('apiTokenSelect');
                // Preserve current selection
                const currentVal = select.value;
                select.innerHTML = '<option value="">Select AI Client...</option>';
                
                tokens.forEach(token => {
                    const opt = document.createElement('option');
                    opt.value = token.id;
                    opt.textContent = `${token.name} (${token.provider})`;
                    select.appendChild(opt);
                });
                
                // Restore selection
                if (currentVal && select.querySelector(`option[value="${currentVal}"]`)) {
                    select.value = currentVal;
                }
            } catch (error) {
                console.error('Error loading tokens:', error);
            }
        }

        async function onTokenSelected() {
            const select = document.getElementById('apiTokenSelect');
            const tokenId = select.value;
            const apiKeyInput = document.getElementById('apiKey');
            const modelSelect = document.getElementById('modelSelect');
            
            if (!tokenId) {
                apiKeyInput.value = '';
                modelSelect.innerHTML = '<option value="">Select an AI Client first</option>';
                modelSelect.disabled = true;
                return;
            }
            
            // Fetch the actual key for the selected token
            try {
                const resp = await fetch(`/api/tokens/${tokenId}/key`);
                if (resp.ok) {
                    const data = await resp.json();
                    apiKeyInput.value = data.key;
                    sessionStorage.setItem('apiKey', data.key);
                } else {
                    showError('Failed to load API key for selected token');
                }
            } catch (error) {
                showError('Error loading token key: ' + error.message);
            }
            
            // Populate models for this token
            populateModelsForToken(tokenId);
        }
        window.onTokenSelected = onTokenSelected;

        async function loadAvailableMcpServers() {
            try {
                const response = await fetch('/api/mcp/credentials');
                if (!response.ok) return;
                const data = await response.json();
                const servers = data.servers || {};
                
                // Convert to array
                mcpServers = Object.entries(servers).map(([id, server]) => ({...server, id}));
                
                // Normalize auth fields
                mcpServers.forEach(server => {
                    if (server.auth_method && !server.auth_type) server.auth_type = server.auth_method;
                    else if (server.auth_type && !server.auth_method) server.auth_method = server.auth_type;
                    if (server.auth_token && !server.token) server.token = server.auth_token;
                    else if (server.token && !server.auth_token) server.auth_token = server.token;
                });
                
                renderMcpDropdown();
            } catch (error) {
                console.error('Error loading MCP servers for chat:', error);
            }
        }

        // Track which MCP servers are currently selected (by id)
        let selectedMcpIds = new Set();

        function renderMcpDropdown() {
            const dropdown = document.getElementById('mcpServerDropdown');
            const listContainer = document.getElementById('mcpSelectedList');
            if (!dropdown || !listContainer) return;

            if (mcpServers.length === 0) {
                dropdown.innerHTML = '<option value="">No servers configured</option>';
                dropdown.disabled = true;
                listContainer.innerHTML = '<span class="mcp-no-servers">No servers configured. <a href="/connections">Add</a></span>';
                return;
            }

            // Build dropdown with only unselected servers
            const available = mcpServers.filter(s => !selectedMcpIds.has(s.id));
            dropdown.disabled = available.length === 0;
            dropdown.innerHTML = available.length === 0
                ? '<option value="">All MCPs selected</option>'
                : '<option value="">Select MCP to add...</option>' +
                  available.map(s => `<option value="${s.id}">${escapeHtml(s.name || s.id)}</option>`).join('');

            // Build read-only selected list
            const selected = mcpServers.filter(s => selectedMcpIds.has(s.id));
            if (selected.length === 0) {
                listContainer.innerHTML = '<span class="mcp-no-servers">No MCPs selected</span>';
            } else {
                listContainer.innerHTML = selected.map(s => `
                    <div class="mcp-selected-item" title="${escapeHtml(s.url || '')}">
                        <a class="mcp-selected-name" href="/connections?server=${encodeURIComponent(s.id)}" target="_blank">${escapeHtml(s.name || s.id)}</a>
                        <button class="mcp-remove-btn" onclick="removeMcpSelection('${s.id}')" title="Remove">&times;</button>
                    </div>
                `).join('');
            }
        }

        function addMcpFromDropdown(select) {
            const id = select.value;
            if (!id) return;
            selectedMcpIds.add(id);
            renderMcpDropdown();
        }
        window.addMcpFromDropdown = addMcpFromDropdown;

        function removeMcpSelection(id) {
            selectedMcpIds.delete(id);
            renderMcpDropdown();
        }
        window.removeMcpSelection = removeMcpSelection;

        function getSelectedMcpServers() {
            return mcpServers.filter(s => selectedMcpIds.has(s.id));
        }

        function getSelectedModel() {
            const select = document.getElementById('modelSelect');
            return select ? select.value : 'claude-sonnet-4-20250514';
        }

        async function loadAvailableModels() {
            try {
                const resp = await fetch('/api/models?enabled_only=true');
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
                    return;
                }
            } catch (error) {
                console.error('Error loading models from API:', error);
            }

            // Fallback to hardcoded MODEL_CONFIGS
            dynamicModels = null;
            allModels = Object.entries(MODEL_CONFIGS).map(([id, cfg]) => ({
                model_id: id,
                display_name: cfg.name,
                context_window: cfg.context,
                input_price: cfg.inputPrice,
                output_price: cfg.outputPrice,
                provider: cfg.provider,
                token_id: null,
            }));
        }

        function populateModelsForToken(tokenId) {
            const select = document.getElementById('modelSelect');
            if (!select) return;

            // Filter models belonging to this token
            const tokenModels = allModels.filter(m => String(m.token_id) === String(tokenId));

            if (tokenModels.length === 0) {
                select.innerHTML = '<option value="">No models configured</option>';
                select.disabled = true;
                return;
            }

            select.innerHTML = '';
            select.disabled = false;

            tokenModels.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.model_id;
                opt.textContent = m.display_name;
                select.appendChild(opt);
            });

            // Select first model and trigger update
            if (select.options.length > 0) {
                select.selectedIndex = 0;
                onModelSelected();
            }
        }

        function onModelSelected() {
            const modelId = getSelectedModel();
            // Try dynamic models first, then fallback
            const config = (dynamicModels && dynamicModels[modelId]) || MODEL_CONFIGS[modelId];
            if (config) {
                CONTEXT_WINDOW = config.context || 200000;
                INPUT_PRICE = (config.inputPrice || 0) / 1000000;
                OUTPUT_PRICE = (config.outputPrice || 0) / 1000000;
                document.getElementById('contextWindow').value = CONTEXT_WINDOW;
                updateMetrics();
                // Update pricing display
                const pricingEl = document.getElementById('pricingInfo');
                if (pricingEl) {
                    if (config.inputPrice > 0 || config.outputPrice > 0) {
                        pricingEl.innerHTML = `<strong>Pricing (${config.name}):</strong><br>Input: $${(config.inputPrice || 0).toFixed(2)} / 1M tokens<br>Output: $${(config.outputPrice || 0).toFixed(2)} / 1M tokens`;
                    } else {
                        pricingEl.innerHTML = `<strong>${config.name}</strong><br><span style="color: #929395;">Set pricing in MCP Connections &gt; Models tab</span>`;
                    }
                }
            }
        }
        window.onModelSelected = onModelSelected;

        function updateContextWindow() {
            const input = document.getElementById('contextWindow');
            const value = parseInt(input.value) || 200000;
            CONTEXT_WINDOW = value;
            updateMetrics();
            sessionStorage.setItem('contextWindow', value);
        }

        function checkProtocol() {
            if (window.location.port !== '5000' && window.location.hostname === 'localhost') {
                showError('INFO: This app is designed to run on the Flask backend. Start with "python app.py" and open http://localhost:5000', true);
            } else if (window.location.protocol === 'file:') {
                showError('WARNING: Please run the Flask server with "python app.py" and open http://localhost:5000 instead of opening this file directly.', true);
            }
        }

        function saveToSession() {
            sessionStorage.setItem('apiKey', document.getElementById('apiKey').value);
        }

        function handleKeyPress(event) {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendMessage();
            }
        }
        
        // Expose handleKeyPress immediately
        window.handleKeyPress = handleKeyPress;

        function displayPrompts(prompts) {
            const promptsSection = document.getElementById('promptsSection');
            const promptsList = document.getElementById('promptsList');
            
            if (!prompts || prompts.length === 0) {
                promptsSection.style.display = 'none';
                return;
            }
            
            // Clear existing prompts
            promptsList.innerHTML = '';
            
            // Add each prompt as a clickable button
            prompts.forEach(prompt => {
                const promptBtn = document.createElement('button');
                promptBtn.className = 'scenario-btn';
                promptBtn.textContent = prompt.title || prompt.name || 'Untitled Prompt';
                promptBtn.title = prompt.description || '';
                promptBtn.onclick = () => usePrompt(prompt);
                promptsList.appendChild(promptBtn);
            });
            
            promptsSection.style.display = 'block';
        }

        function usePrompt(prompt) {
            const userInput = document.getElementById('userInput');
            // Set the prompt name or a message requesting to use the prompt
            userInput.value = `Use the "${prompt.name || prompt.title}" prompt`;
            userInput.focus();
        }

        async function sendMessage(customMessage = null, skipToolSelection = false) {
            console.log('sendMessage called with:', customMessage);
            const apiKey = document.getElementById('apiKey').value;
            const userInput = document.getElementById('userInput');
            const message = customMessage || userInput.value.trim();
            console.log('Message:', message, 'API Key exists:', !!apiKey);

            if (!apiKey) {
                showError('Please select an AI token from the dropdown above');
                return;
            }

            if (!message) {
                showError('Please enter a message');
                return;
            }

            saveToSession();
            clearError();

            // Add user message to UI
            addMessageToUI('user', message);
            if (!customMessage) userInput.value = '';

            // Add to conversation history
            conversationHistory.push({
                role: 'user',
                content: message
            });

            // Read sampling parameters from sidebar controls
            const _temperature = parseFloat(document.getElementById('paramTemp')?.value ?? 1.0);
            const _topP = parseFloat(document.getElementById('paramTopP')?.value ?? 1.0);
            const _maxTokens = parseInt(document.getElementById('paramMaxTokens')?.value ?? 8000) || 8000;
            const _stopSeqRaw = (document.getElementById('paramStopSeqs')?.value || '').trim();
            const _stopSequences = _stopSeqRaw ? _stopSeqRaw.split('\n').map(s => s.trim()).filter(Boolean) : [];

            // Prepare API request
            const requestBody = {
                model: getSelectedModel(),
                max_tokens: _maxTokens,
                messages: conversationHistory
            };

            // Add selected MCP servers from checkboxes
            const selectedServers = getSelectedMcpServers();
            if (selectedServers.length > 0) {
                requestBody.servers = selectedServers.map(server => ({
                    id: server.id,
                    name: server.name || 'Unnamed Server',
                    url: server.url,
                    auth_type: server.auth_type || server.auth_method || 'bearer_token',
                    auth_token: server.auth_token || server.token || ''
                }));
            }

            // Show loading
            const loadingId = addLoadingMessage();

            try {
                // Call our Flask backend instead of Anthropic API directly
                const backendPayload = {
                    api_key: apiKey,
                    model: requestBody.model,
                    max_tokens: requestBody.max_tokens,
                    messages: JSON.parse(JSON.stringify(requestBody.messages)),
                    session_id: currentSessionId,  // Add session ID for backend tracking
                    stream: true,
                    temperature: _temperature,
                    top_p: _topP,
                };
                if (_stopSequences.length > 0) {
                    backendPayload.stop_sequences = _stopSequences;
                }

                // Include token_id so the backend can resolve the correct provider
                const tokenSelect = document.getElementById('apiTokenSelect');
                if (tokenSelect && tokenSelect.value) {
                    backendPayload.token_id = tokenSelect.value;
                }

                // Include provider from the selected model's metadata
                const modelId = getSelectedModel();
                const modelConfig = (dynamicModels && dynamicModels[modelId]) || MODEL_CONFIGS[modelId];
                if (modelConfig && modelConfig.provider) {
                    backendPayload.provider = modelConfig.provider;
                }

                // Add MCP servers if present in original request
                if (requestBody.servers) {
                    backendPayload.servers = requestBody.servers;
                }

                // Debug: Log the payload being sent
                console.log('=== SENDING TO BACKEND ===');
                console.log('Servers:', JSON.stringify(backendPayload.servers, null, 2));
                console.log('Sampling params: temp=' + _temperature + ' top_p=' + _topP + ' max_tokens=' + _maxTokens);
                console.log('=========================');

                // Capture previous turn's input count for delta annotation
                const prevInputTokens = lastTurnInputTokens;

                // Start timing the request
                const requestStartTime = Date.now();

                const response = await fetch('/api/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    credentials: 'include',
                    body: JSON.stringify(backendPayload)
                });

                if (!response.ok) {
                    removeLoadingMessage(loadingId);
                    const error = await response.json();
                    console.error('API Response Error:', error);
                    throw new Error(error.error?.message || error.error || `API request failed with status ${response.status}`);
                }

                // Branch: SSE stream (Mistral MCP, Anthropic streaming, etc.) vs JSON
                const contentType = response.headers.get('content-type') || '';
                let result;
                if (contentType.includes('text/event-stream')) {
                    result = await readSSEStream(response, loadingId);
                } else {
                    removeLoadingMessage(loadingId);
                    result = await response.json();
                    // Attach perf for non-streaming (no TTFT available)
                    result.perf = { ttft_ms: null, total_ms: Date.now() - requestStartTime, tps: null };
                }

                // Ensure result.content is always present (derive from history if needed)
                if (!result.content && result.conversation_history) {
                    const lastAssistant = result.conversation_history.slice().reverse().find(m => m.role === 'assistant');
                    result.content = (lastAssistant && lastAssistant.content) || [];
                }
                
                // Process content blocks to create segments with text and associated tools
                const contentSegments = [];
                if (result.content && result.content.length > 0) {
                    let currentSegment = { content: '', tools: [], thinking: '' };
                    
                    for (const block of result.content) {
                        if (block.type === 'text') {
                            // If we have accumulated tools, close the current segment and start a new one
                            if (currentSegment.tools.length > 0) {
                                contentSegments.push(currentSegment);
                                currentSegment = { content: '', tools: [], thinking: '' };
                            }
                            currentSegment.content += block.text;
                        } else if (block.type === 'thinking') {
                            // Add thinking to current segment
                            currentSegment.thinking += block.thinking || '';
                        } else if (block.type === 'mcp_tool_use' || block.type === 'tool_use') {
                            // Add tool use to current segment
                            currentSegment.tools.push({
                                type: 'tool_use',
                                name: block.name,
                                input: block.input
                            });
                        } else if (block.type === 'mcp_tool_result' || block.type === 'tool_result') {
                            // Add tool result to current segment
                            currentSegment.tools.push({
                                type: 'tool_result',
                                tool_use_id: block.tool_use_id,
                                content: block.content
                            });
                        }
                    }
                    
                    // Add the last segment if it has content
                    if (currentSegment.content || currentSegment.tools.length > 0 || currentSegment.thinking) {
                        contentSegments.push(currentSegment);
                    }
                }
                
                // If no segments were created, add a default empty response
                if (contentSegments.length === 0) {
                    contentSegments.push({ content: '(No text response)', tools: [], thinking: '' });
                }

                // Add assistant message with segmented content
                addMessageToUI('assistant', contentSegments, 0, [], false, false,
                    result.stop_reason, result.perf, result.tool_chain);

                // Attach the frozen SSE event log chip to the completed message
                if (result.sseEventLog && result.sseEventLog.length > 0) {
                    const lastMsgContent = document.querySelector(
                        '#messages .message-assistant:last-child .message-content'
                    );
                    if (lastMsgContent) lastMsgContent.appendChild(buildSseLogChip(result.sseEventLog));
                }

                // Update conversation history.
                // Prefer the server's authoritative conversation_history which
                // has correct role alternation (tool_result in user messages,
                // not in assistant messages), preventing Anthropic 400 errors
                // on subsequent turns when MCP tool calls were made.
                if (result.conversation_history && result.conversation_history.length > 0) {
                    conversationHistory = result.conversation_history;
                } else {
                    conversationHistory.push({
                        role: 'assistant',
                        content: result.content || []
                    });
                }

                // Update session metrics
                const usage = result.usage || {};
                const currentInputTokens = usage.input_tokens || 0;
                const currentOutputTokens = usage.output_tokens || 0;
                const currentCost = (currentInputTokens * 0.000003) + (currentOutputTokens * 0.000015);
                
                totalInputTokens += currentInputTokens;
                totalOutputTokens += currentOutputTokens;

                const deltaFromPrev = prevInputTokens > 0 ? currentInputTokens - prevInputTokens : 0;
                lastTurnInputTokens = currentInputTokens;

                updateMetrics();
                
                const requestDuration = Date.now() - requestStartTime;
                console.log(`API Request completed in ${(requestDuration / 1000).toFixed(2)}s (${requestDuration}ms)`);

                // Store full API request and response in session
                sessionMessages.push({
                    timestamp: new Date().toISOString(),
                    request: backendPayload,
                    response: result,
                    duration_ms: requestDuration,
                    duration_seconds: (requestDuration / 1000).toFixed(2),
                    perf: result.perf || null,
                    stop_reason: result.stop_reason || null,
                    tool_chain: result.tool_chain || [],
                    sampling_params: {
                        temperature: _temperature,
                        top_p: _topP,
                        max_tokens: _maxTokens,
                        stop_sequences: _stopSequences,
                    },
                });

                // Auto-save session if one is active
                if (currentSessionId) {
                    await saveCurrentSession();
                }

                // Update breakdown and session info
                addToBreakdown(sessionMessages.length, currentInputTokens, currentOutputTokens, undefined, deltaFromPrev);
                updateSessionInfo();

            } catch (error) {
                removeLoadingMessage(loadingId);
                
                // Provide helpful error message based on error type
                if (error.message === 'Failed to fetch' || error.name === 'TypeError') {
                    showError(`Server Error: Unable to connect to the Flask backend. Make sure you're running the server with 'python app.py' and accessing http://localhost:5000`);
                } else {
                    showError(`Error: ${error.message}`);
                }
                console.error('API Error:', error);
            }
        }

        function addMessageToUI(role, content, tokens = 0, toolUsage = [], wasTruncated = false, wasPaused = false, stopReason = null, perfMetrics = null, toolChain = null) {
            const messagesDiv = document.getElementById('messages');
            const messageDiv = document.createElement('div');
            messageDiv.className = `message message-${role}`;

            const messageContentDiv = document.createElement('div');
            messageContentDiv.className = 'message-content';

            // Handle both old format (string) and new format (content blocks/segments)
            if (Array.isArray(content)) {
                // New format: content segments with text, thinking, and tools
                content.forEach((segment, index) => {
                    // Display thinking if present (collapsible, collapsed by default)
                    if (segment.thinking && segment.thinking.trim()) {
                        const thinkingBlock = document.createElement('div');
                        thinkingBlock.className = 'thinking-block';

                        const thinkingHeader = document.createElement('div');
                        thinkingHeader.className = 'thinking-header';
                        thinkingHeader.innerHTML = `<span style="font-size: 15px;">&#129300;</span> Thinking<span class="thinking-chevron">&#9660;</span>`;

                        const thinkingContent = document.createElement('div');
                        thinkingContent.className = 'thinking-content';
                        thinkingContent.textContent = segment.thinking;

                        thinkingHeader.addEventListener('click', () => {
                            thinkingBlock.classList.toggle('expanded');
                            thinkingContent.classList.toggle('expanded');
                        });

                        thinkingBlock.appendChild(thinkingHeader);
                        thinkingBlock.appendChild(thinkingContent);
                        messageContentDiv.appendChild(thinkingBlock);
                    }

                    // Display text content if present
                    if (segment.content && segment.content.trim()) {
                        const textDiv = document.createElement('div');
                        if (role === 'assistant') {
                            textDiv.innerHTML = marked.parse(segment.content);
                            renderMermaidBlocks(textDiv);
                        } else {
                            textDiv.textContent = segment.content;
                            textDiv.style.whiteSpace = 'pre-wrap';
                        }
                        if (index > 0) {
                            textDiv.style.marginTop = '15px';
                        }
                        messageContentDiv.appendChild(textDiv);
                    }

                    // Display tools after this segment's text
                    if (segment.tools && segment.tools.length > 0) {
                        const toolDiv = renderToolUsage(segment.tools);
                        if (toolDiv) {
                            messageContentDiv.appendChild(toolDiv);
                        }
                    }
                });
            } else {
                // Old format: simple string content
                const textDiv = document.createElement('div');
                if (role === 'assistant' && content) {
                    textDiv.innerHTML = marked.parse(content);
                    renderMermaidBlocks(textDiv);
                } else {
                    textDiv.textContent = content || '(No text response)';
                    textDiv.style.whiteSpace = 'pre-wrap';
                }
                messageContentDiv.appendChild(textDiv);

                // Add tool usage at the end (old behavior for backwards compatibility)
                if (toolUsage && toolUsage.length > 0) {
                    const toolDiv = renderToolUsage(toolUsage);
                    if (toolDiv) {
                        messageContentDiv.appendChild(toolDiv);
                    }
                }
            }

            // Add truncation warning if response was cut off
            if (wasTruncated) {
                const truncatedWarning = document.createElement('div');
                truncatedWarning.style.cssText = 'background: #FFF8D6; border-left: 3px solid #FFEB55; padding: 10px; margin-top: 10px; border-radius: 4px; font-size: 13px; color: #CC4820;';
                truncatedWarning.innerHTML = `&#9888; <strong>Response Truncated</strong><br><span style="font-size: 12px;">This response was cut off at ${tokens} tokens. The model reached the maximum token limit before completing its response.</span>`;
                messageContentDiv.appendChild(truncatedWarning);
            }

            // Add pause indicator if conversation paused for tool execution
            if (wasPaused) {
                const pausedInfo = document.createElement('div');
                pausedInfo.style.cssText = 'background: #D4F4FF; border-left: 3px solid #33B6FF; padding: 10px; margin-top: 10px; border-radius: 4px; font-size: 13px; color: #3533FF;';
                pausedInfo.innerHTML = `&#9209; <strong>Conversation Paused</strong><br><span style="font-size: 12px;">Claude paused mid-conversation to wait for tool execution results. The backend will automatically continue processing with the tool results.</span>`;
                messageContentDiv.appendChild(pausedInfo);
            }

            if (tokens > 0) {
                const badge = document.createElement('div');
                badge.className = 'token-badge';
                badge.textContent = ` ${tokens} tokens`;
                messageContentDiv.appendChild(badge);
            }

            // Feature 2: Stop reason badge
            if (role === 'assistant' && stopReason) {
                const STOP_LABELS = {
                    'end_turn':       '✓ Complete',
                    'max_tokens':     '⚠ Max Tokens',
                    'stop_sequence':  '◼ Stop Seq',
                    'tool_use':       '⚙ Tool Use',
                    'content_filter': '⛔ Filtered',
                };
                const badge = document.createElement('span');
                badge.className = `stop-badge stop-badge-${stopReason}`;
                badge.textContent = STOP_LABELS[stopReason] || stopReason;
                messageContentDiv.appendChild(badge);
            }

            // Feature 1: Performance strip
            if (role === 'assistant' && perfMetrics) {
                const strip = document.createElement('div');
                strip.className = 'perf-strip';
                const parts = [];
                if (perfMetrics.ttft_ms !== null && perfMetrics.ttft_ms !== undefined) {
                    parts.push(`TTFT <span class="perf-val">${(perfMetrics.ttft_ms / 1000).toFixed(2)}s</span>`);
                }
                if (perfMetrics.tps !== null && perfMetrics.tps !== undefined) {
                    parts.push(`<span class="perf-val">${perfMetrics.tps}</span> tok/s`);
                }
                if (perfMetrics.total_ms) {
                    parts.push(`Total <span class="perf-val">${(perfMetrics.total_ms / 1000).toFixed(2)}s</span>`);
                }
                if (parts.length > 0) {
                    strip.innerHTML = parts.join('<span style="color:#E2E2E4">  |  </span>');
                    messageContentDiv.appendChild(strip);
                }
            }

            // Feature 4: Tool chain timeline (for _run_tool_loop paths — explicit tool_chain)
            if (role === 'assistant' && toolChain && toolChain.length > 0) {
                const timeline = renderToolChainTimeline(toolChain);
                if (timeline) messageContentDiv.appendChild(timeline);
            }

            messageDiv.appendChild(messageContentDiv);
            messagesDiv.appendChild(messageDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }

        // Feature 3: Toggle sampling parameter panel
        function toggleParamPanel() {
            const panel = document.getElementById('paramPanel');
            const chevron = document.getElementById('paramChevron');
            if (!panel) return;
            const isOpen = panel.style.display !== 'none';
            panel.style.display = isOpen ? 'none' : 'block';
            if (chevron) chevron.style.transform = isOpen ? '' : 'rotate(180deg)';
        }
        window.toggleParamPanel = toggleParamPanel;

        // Feature 4: Render tool chain timeline DOM element
        function renderToolChainTimeline(toolChain) {
            if (!toolChain || toolChain.length === 0) return null;

            const container = document.createElement('div');
            container.className = 'tool-chain-timeline';

            const header = document.createElement('div');
            header.className = 'tool-chain-timeline-header';
            header.innerHTML = `⛓ Tool Chain  <span style="background:#3533FF;color:white;padding:1px 7px;border-radius:10px;font-size:10px;">${toolChain.length}</span>`;

            const stepsDiv = document.createElement('div');
            stepsDiv.className = 'tc-steps';
            stepsDiv.style.display = 'none';

            header.addEventListener('click', () => {
                stepsDiv.style.display = stepsDiv.style.display === 'none' ? 'flex' : 'none';
            });

            // Build steps: [User] → [LLM] → [tool] → [result] → ... → [LLM] → [Answer]
            let prevIteration = 0;
            toolChain.forEach((step, i) => {
                if (step.iteration !== prevIteration) {
                    // New iteration: add LLM node
                    const stepRow = document.createElement('div');
                    stepRow.className = 'tc-step';
                    if (i === 0) {
                        const userNode = document.createElement('span');
                        userNode.className = 'tc-node tc-node-user';
                        userNode.textContent = 'User';
                        stepRow.appendChild(userNode);
                        const arrow = document.createElement('span');
                        arrow.className = 'tc-arrow';
                        arrow.textContent = '→';
                        stepRow.appendChild(arrow);
                    }
                    const llmNode = document.createElement('span');
                    llmNode.className = 'tc-node tc-node-llm';
                    llmNode.textContent = `LLM (iter ${step.iteration})`;
                    stepRow.appendChild(llmNode);
                    stepsDiv.appendChild(stepRow);
                    prevIteration = step.iteration;
                }

                // Tool call node
                const toolRow = document.createElement('div');
                toolRow.className = 'tc-step';
                toolRow.style.paddingLeft = '20px';

                const arrowT = document.createElement('span');
                arrowT.className = 'tc-arrow';
                arrowT.textContent = '→';
                toolRow.appendChild(arrowT);

                const toolNode = document.createElement('span');
                toolNode.className = 'tc-node tc-node-tool';
                toolNode.textContent = `⚙ ${step.tool_name}`;
                toolNode.title = 'Click to view input';

                const inputDetail = document.createElement('div');
                inputDetail.className = 'tc-detail';
                inputDetail.textContent = typeof step.tool_input === 'string'
                    ? step.tool_input
                    : JSON.stringify(step.tool_input, null, 2);
                toolNode.addEventListener('click', () => inputDetail.classList.toggle('expanded'));

                toolRow.appendChild(toolNode);
                stepsDiv.appendChild(toolRow);
                stepsDiv.appendChild(inputDetail);

                // Result node
                const resultRow = document.createElement('div');
                resultRow.className = 'tc-step';
                resultRow.style.paddingLeft = '20px';

                const arrowR = document.createElement('span');
                arrowR.className = 'tc-arrow';
                arrowR.textContent = '→';
                resultRow.appendChild(arrowR);

                const resultNode = document.createElement('span');
                resultNode.className = 'tc-node tc-node-result';
                resultNode.textContent = '✓ Result';
                resultNode.title = 'Click to view output';

                const resultDetail = document.createElement('div');
                resultDetail.className = 'tc-detail';
                resultDetail.textContent = step.tool_result || '(empty)';
                resultNode.addEventListener('click', () => resultDetail.classList.toggle('expanded'));

                resultRow.appendChild(resultNode);
                stepsDiv.appendChild(resultRow);
                stepsDiv.appendChild(resultDetail);
            });

            // Final answer node
            const finalRow = document.createElement('div');
            finalRow.className = 'tc-step';
            const arrowF = document.createElement('span');
            arrowF.className = 'tc-arrow';
            arrowF.textContent = '→';
            finalRow.appendChild(arrowF);
            const finalNode = document.createElement('span');
            finalNode.className = 'tc-node tc-node-final';
            finalNode.textContent = '✓ Answer';
            finalRow.appendChild(finalNode);
            stepsDiv.appendChild(finalRow);

            container.appendChild(header);
            container.appendChild(stepsDiv);
            return container;
        }

        function formatJSON(obj) {
            const json = JSON.stringify(obj, null, 2);
            return json.replace(/(&|<|>|"|')/g, (match) => {
                return {
                    '&': '&amp;',
                    '<': '&lt;',
                    '>': '&gt;',
                    '"': '&quot;',
                    "'": '&#39;'
                }[match];
            }).replace(/"([^"]+)":/g, '<span style="color: #3533FF; font-weight: 600;">"$1"</span>:')
              .replace(/: "([^"]*)"/g, ': <span style="color: #4CD97A;">"$1"</span>')
              .replace(/: (true|false)/g, ': <span style="color: #33B6FF; font-weight: 600;">$1</span>')
              .replace(/: (null)/g, ': <span style="color: #929395; font-weight: 600;">$1</span>')
              .replace(/: (-?\d+\.?\d*)/g, ': <span style="color: #FF5A26;">$1</span>');
        }

        // ── SSE Event Log helpers ──────────────────────────────────────────────

        /**
         * Build the innerHTML string for one row of the SSE event log.
         * Used both during live streaming (appendEventRow) and when rendering
         * the frozen chip that persists on the completed assistant message.
         */
        function buildEventRowHtml(entry) {
            const { ms, type, event, isTTFT } = entry;
            const timeStr = ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
            let detail = '';

            switch (type) {
                case 'message_start': {
                    const id    = (event.message?.id    || '').slice(0, 16);
                    const model = (event.message?.model || '').replace('claude-', '');
                    detail = `id: ${id}  model: ${model}`;
                    break;
                }
                case 'content_block_start': {
                    const cbType = event.content_block?.type || '';
                    const extra  = cbType === 'tool_use'
                        ? `  name: ${escapeHtml(event.content_block?.name || '')}`
                        : '';
                    detail = `#${event.index}  type: ${cbType}${extra}`;
                    break;
                }
                case 'content_block_delta': {
                    const delta = event.delta || {};
                    const raw   = delta.text || delta.thinking || delta.partial_json || '';
                    const preview = raw.length > 40
                        ? escapeHtml(raw.slice(0, 40)) + '…'
                        : escapeHtml(raw);
                    detail = `#${event.index}  &quot;${preview}&quot;`;
                    break;
                }
                case 'content_block_stop':
                    detail = `#${event.index}`;
                    break;
                case 'message_delta':
                    detail = `stop: ${event.delta?.stop_reason || '—'}  out: ${event.usage?.output_tokens ?? '?'} tok`;
                    break;
                case 'stream_end':
                    detail = '✓ complete';
                    break;
                case 'progress':
                    detail = escapeHtml(event.text || '');
                    break;
                case 'error':
                    detail = escapeHtml(String(event.error || 'unknown error'));
                    break;
                default:
                    detail = escapeHtml(JSON.stringify(event).slice(0, 60));
            }

            const ttftMark = isTTFT ? '<span class="sse-ttft">★ TTFT</span>' : '';
            return `<span class="sse-time">${timeStr}</span><span class="sse-badge">${type}</span><span class="sse-detail">${detail}</span>${ttftMark}`;
        }

        /**
         * Build a frozen, collapsible event-log chip to attach to a completed
         * assistant message after streaming finishes.
         */
        function buildSseLogChip(eventLog) {
            const wrapper = document.createElement('div');
            wrapper.style.cssText = 'margin-top: 8px;';

            const toggle = document.createElement('button');
            toggle.className = 'sse-log-toggle';
            toggle.textContent = `📡 ${eventLog.length} events`;

            const panel = document.createElement('div');
            panel.className = 'sse-log-panel';
            panel.style.display = 'none';

            eventLog.forEach(entry => {
                const row = document.createElement('div');
                row.className = `sse-row sse-type-${entry.type.replace(/_/g, '-')}`;
                row.innerHTML = buildEventRowHtml(entry);
                panel.appendChild(row);
            });

            toggle.onclick = () => {
                const isOpen = panel.style.display !== 'none';
                panel.style.display = isOpen ? 'none' : 'block';
                toggle.textContent = isOpen
                    ? `📡 ${eventLog.length} events`
                    : `📡 ${eventLog.length} events ▲`;
                toggle.classList.toggle('active', !isOpen);
                if (!isOpen) panel.scrollTop = panel.scrollHeight;
            };

            wrapper.appendChild(toggle);
            wrapper.appendChild(panel);
            return wrapper;
        }

        function renderToolUsage(toolUsage) {
            if (!toolUsage || toolUsage.length === 0) return null;
            
            const toolDiv = document.createElement('div');
            toolDiv.className = 'tool-usage';
            toolDiv.style.marginTop = '10px';
            
            const header = document.createElement('div');
            header.className = 'tool-usage-header';
            
            const headerText = document.createElement('span');
            headerText.textContent = ' Tools Used';
            
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
                    // Associate result with the last tool_use that doesn't have a result yet
                    const lastToolWithoutResult = toolCalls.reverse().find(t => !t.result);
                    if (lastToolWithoutResult) {
                        lastToolWithoutResult.result = tool;
                    }
                    toolCalls.reverse();
                }
            });

            // Render each tool call with its input and output
            toolCalls.forEach(toolCall => {
                const toolItem = document.createElement('div');
                toolItem.className = 'tool-item';
                
                const toolName = document.createElement('div');
                toolName.className = 'tool-name';
                toolName.innerHTML = `<span>&#9679;</span> ${toolCall.use.name}`;
                toolItem.appendChild(toolName);

                // Input section
                if (toolCall.use.input && Object.keys(toolCall.use.input).length > 0) {
                    const inputLabel = document.createElement('div');
                    inputLabel.style.cssText = 'font-size: 11px; font-weight: 600; color: #929395; margin: 8px 0 4px 0; text-transform: uppercase; letter-spacing: 0.5px;';
                    inputLabel.textContent = ' Input';
                    toolItem.appendChild(inputLabel);
                    
                    const params = document.createElement('div');
                    params.className = 'tool-params';
                    params.innerHTML = formatJSON(toolCall.use.input);
                    toolItem.appendChild(params);
                }

                // Output section
                if (toolCall.result) {
                    const outputLabel = document.createElement('div');
                    outputLabel.style.cssText = 'font-size: 11px; font-weight: 600; color: #4CD97A; margin: 12px 0 4px 0; text-transform: uppercase; letter-spacing: 0.5px;';
                    outputLabel.textContent = ' Output';
                    toolItem.appendChild(outputLabel);
                    
                    const output = document.createElement('div');
                    output.className = 'tool-output';
                    
                    // Extract text parts from content, unescaping nested JSON strings
                    let outputParts = [];
                    if (Array.isArray(toolCall.result.content)) {
                        outputParts = toolCall.result.content.map(c => {
                            let raw = '';
                            if (typeof c === 'object' && c.type === 'text') raw = c.text;
                            else if (typeof c === 'string') raw = c;
                            else return { parsed: c };
                            // Try to parse the text as JSON to unescape it
                            try { return { parsed: JSON.parse(raw) }; } catch (_) {}
                            return { text: raw };
                        });
                    } else if (typeof toolCall.result.content === 'string') {
                        try { outputParts = [{ parsed: JSON.parse(toolCall.result.content) }]; }
                        catch (_) { outputParts = [{ text: toolCall.result.content }]; }
                    } else {
                        outputParts = [{ parsed: toolCall.result.content }];
                    }

                    // Render each part with JSON formatting or plain text
                    outputParts.forEach(part => {
                        if (part.parsed !== undefined) {
                            const fragment = document.createElement('div');
                            fragment.innerHTML = formatJSON(part.parsed);
                            output.appendChild(fragment);
                        } else {
                            const fragment = document.createElement('div');
                            fragment.textContent = part.text;
                            output.appendChild(fragment);
                        }
                    });
                    
                    toolItem.appendChild(output);
                }
                
                toolContentDiv.appendChild(toolItem);
            });
            
            // Toggle functionality
            header.addEventListener('click', () => {
                toolContentDiv.classList.toggle('expanded');
            });

            toolDiv.appendChild(header);
            toolDiv.appendChild(toolContentDiv);
            
            return toolDiv;
        }

        function addLoadingMessage() {
            const messagesDiv = document.getElementById('messages');
            const messageDiv = document.createElement('div');
            const id = 'loading-' + Date.now();
            messageDiv.id = id;
            messageDiv.className = 'message message-assistant';
            messageDiv.innerHTML = `
                <div class="message-content">
                    <span class="loading"></span> Thinking...
                </div>
            `;
            messagesDiv.appendChild(messageDiv);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
            return id;
        }

        function removeLoadingMessage(id) {
            const element = document.getElementById(id);
            if (element) element.remove();
        }

        /**
         * Read an SSE response stream from a fetch() call, updating the loading
         * spinner as progress events arrive, and returning the stream_end payload
         * (which mirrors the JSON response structure).
         *
         * Also populates finalResult.sseEventLog with every raw SSE event so the
         * caller can attach a frozen event-log chip to the completed message.
         */
        async function readSSEStream(response, loadingId) {
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let finalResult = null;
            const crumbs   = [];  // progress breadcrumbs shown in the loading bubble
            const eventLog = [];  // every raw SSE event, for the event-log panel

            // Performance tracking
            const streamStartTime = Date.now();
            let firstTokenMs = null;
            let deltaCount = 0;
            let sseLogVisible = false;
            let sseReady = false; // true once initPanel succeeds

            function addBreadcrumb(text) {
                // Avoid consecutive duplicates
                if (crumbs.length > 0 && crumbs[crumbs.length - 1] === text) return;
                crumbs.push(text);
                renderCrumbs();
            }

            // Targets .sse-crumbs-area if it exists, falls back to .message-content
            function renderCrumbs() {
                const el = document.getElementById(loadingId);
                if (!el) return;
                const area = el.querySelector('.sse-crumbs-area') || el.querySelector('.message-content');
                if (!area) return;
                const parts = crumbs.map((text, i) => {
                    const isLast = i === crumbs.length - 1;
                    if (isLast) {
                        return `<div class="progress-crumb active"><span class="loading"></span>${text}</div>`;
                    }
                    return `<div class="progress-crumb done">${text}</div>`;
                }).join('');
                area.innerHTML = `<div class="progress-crumbs">${parts}</div>`;
                const messagesDiv = document.getElementById('messages');
                if (messagesDiv) messagesDiv.scrollTop = messagesDiv.scrollHeight;
            }

            // Append one row to the live panel — non-fatal, never interrupts the stream
            function appendEventRow(entry) {
                if (!sseReady) return;
                try {
                    const panel = document.getElementById(`${loadingId}-sse-panel`);
                    if (!panel) return;
                    const row = document.createElement('div');
                    row.className = `sse-row sse-type-${entry.type.replace(/_/g, '-')}`;
                    row.innerHTML = buildEventRowHtml(entry);
                    panel.appendChild(row);
                    if (panel.style.display !== 'none') panel.scrollTop = panel.scrollHeight;
                } catch (e) { /* non-fatal — UI log failures must never kill the stream */ }
            }

            try {
                // ── Initialise the two-zone layout in the loading bubble ─────────
                // Runs inside try so finally always cleans up.  Wrapped in its own
                // try/catch so a DOM error here is non-fatal and the stream still runs.
                try {
                    const el = document.getElementById(loadingId);
                    if (el) {
                        el.querySelector('.message-content').innerHTML = `
                            <div class="sse-crumbs-area"><span class="loading"></span> Thinking...</div>
                            <div class="sse-controls-area">
                                <button class="sse-log-toggle" id="${loadingId}-sse-btn">📡 Events</button>
                                <div class="sse-log-panel" id="${loadingId}-sse-panel" style="display:none;"></div>
                            </div>`;
                        const btn = document.getElementById(`${loadingId}-sse-btn`);
                        if (btn) {
                            btn.onclick = () => {
                                sseLogVisible = !sseLogVisible;
                                const panel = document.getElementById(`${loadingId}-sse-panel`);
                                const b     = document.getElementById(`${loadingId}-sse-btn`);
                                if (!panel || !b) return;
                                panel.style.display = sseLogVisible ? 'block' : 'none';
                                b.classList.toggle('active', sseLogVisible);
                                b.textContent = sseLogVisible ? '📡 Events \u25b2' : '📡 Events';
                                if (sseLogVisible) panel.scrollTop = panel.scrollHeight;
                            };
                            sseReady = true;
                        }
                    }
                } catch (e) { console.warn('SSE panel init failed (non-fatal):', e); }

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop(); // keep incomplete last line
                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        let event;
                        try { event = JSON.parse(line.slice(6)); }
                        catch { continue; }

                        // Mark the very first delta so buildEventRowHtml can stamp ★ TTFT
                        const isTTFT = (event.type === 'content_block_delta' && firstTokenMs === null);

                        if (event.type === 'content_block_delta') {
                            if (firstTokenMs === null) firstTokenMs = Date.now() - streamStartTime;
                            deltaCount++;
                        } else if (event.type === 'progress') {
                            addBreadcrumb(event.text);
                        } else if (event.type === 'content_block_start' &&
                                   event.content_block?.type === 'tool_use') {
                            addBreadcrumb(`Calling ${event.content_block.name}...`);
                        } else if (event.type === 'error') {
                            throw new Error(event.error || 'Streaming error');
                        } else if (event.type === 'stream_end') {
                            finalResult = event;
                        }

                        // Record and render — appendEventRow is non-fatal
                        const entry = { ms: Date.now() - streamStartTime, type: event.type, event, isTTFT };
                        eventLog.push(entry);
                        appendEventRow(entry);
                    }
                }
            } finally {
                removeLoadingMessage(loadingId);
            }

            if (!finalResult) throw new Error('Stream ended without a result');

            // Attach performance metrics and the frozen event log to the result
            const totalMs = Date.now() - streamStartTime;
            const generationMs = (firstTokenMs !== null) ? (totalMs - firstTokenMs) : 0;
            const tps = (generationMs > 100 && deltaCount > 0)
                ? (deltaCount / generationMs * 1000).toFixed(1)
                : null;
            finalResult.perf = {
                ttft_ms: firstTokenMs,
                total_ms: totalMs,
                tps,
            };
            finalResult.sseEventLog = eventLog;
            return finalResult;
        }

        function updateMetrics() {
            const total = totalInputTokens + totalOutputTokens;
            const percentage = ((total / CONTEXT_WINDOW) * 100).toFixed(2);
            const cost = (totalInputTokens * INPUT_PRICE + totalOutputTokens * OUTPUT_PRICE).toFixed(4);

            document.getElementById('totalTokens').textContent = total.toLocaleString();
            document.getElementById('usagePercent').textContent = percentage + '%';
            document.getElementById('totalCost').textContent = '$' + cost;

            const contextFill = document.getElementById('contextFill');
            contextFill.style.width = Math.min(percentage, 100) + '%';
            
            if (percentage > 0) {
                document.getElementById('contextText').textContent = `${percentage}%`;
            }
        }

        function addToBreakdown(messageNum, inputTokens, outputTokens, overrideIndex, deltaFromPrev = 0) {
            const breakdownDiv = document.getElementById('breakdown');
            const card = document.createElement('div');
            card.className = 'message-breakdown';
            card.style.cursor = 'pointer';
            card.title = 'Click to view API call details';

            // Store the message index for lookup
            const messageIndex = overrideIndex !== undefined ? overrideIndex : sessionMessages.length - 1;
            card.onclick = () => showMessageDetails(messageIndex);

            const displayNum = messageNum;

            // Pull extra metadata from the corresponding sessionMessage
            const msg = sessionMessages[messageIndex];
            const stopReason = msg?.stop_reason || null;
            const perf = msg?.perf || null;
            const temp = msg?.sampling_params?.temperature;
            const STOP_LABELS = {
                'end_turn': '✓', 'max_tokens': '⚠', 'stop_sequence': '◼',
                'tool_use': '⚙', 'content_filter': '⛔',
            };
            const stopBadge = stopReason
                ? `<span class="stop-badge stop-badge-${stopReason}" style="font-size:10px;padding:2px 6px;">${STOP_LABELS[stopReason] || ''} ${stopReason}</span>`
                : '';
            const perfLine = (perf && perf.total_ms)
                ? `<div class="cost-estimate" style="margin-top:4px;">⏱ ${(perf.total_ms/1000).toFixed(2)}s${perf.tps ? '  ' + perf.tps + ' tok/s' : ''}</div>`
                : '';
            const tempLine = (temp !== undefined && temp !== null)
                ? `<div class="cost-estimate">🌡 temp ${temp.toFixed(2)}</div>`
                : '';

            const deltaLine = (deltaFromPrev > 0)
                ? `<div style="display:flex;justify-content:space-between;font-size:10px;color:#929395;padding:1px 4px 5px 8px;border-left:2px solid rgba(53,51,255,0.25);margin:0 0 4px 0;">
                       <span>↑ +${deltaFromPrev.toLocaleString()} new tokens</span>
                       <span style="color:#3533FF;font-weight:600;">${((deltaFromPrev / inputTokens) * 100).toFixed(0)}% new</span>
                   </div>`
                : '';

            card.innerHTML = `
                <div style="font-weight: 600; margin-bottom: 6px; color: #313131; display:flex; justify-content:space-between; align-items:center;">
                    <span>Message #${displayNum}</span>
                    ${stopBadge}
                </div>
                <div class="breakdown-row">
                    <span class="breakdown-label">Input:</span>
                    <span class="breakdown-value">${inputTokens.toLocaleString()}</span>
                </div>
                ${deltaLine}
                <div class="breakdown-row">
                    <span class="breakdown-label">Output:</span>
                    <span class="breakdown-value">${outputTokens.toLocaleString()}</span>
                </div>
                <div class="breakdown-row" style="border-top: 1px solid #E2E2E4; padding-top: 5px;">
                    <span class="breakdown-label">Total:</span>
                    <span class="breakdown-value">${(inputTokens + outputTokens).toLocaleString()}</span>
                </div>
                <div class="cost-estimate">
                    Cost: $${(inputTokens * INPUT_PRICE + outputTokens * OUTPUT_PRICE).toFixed(4)}
                </div>
                ${perfLine}
                ${tempLine}
            `;

            breakdownDiv.prepend(card);
        }

        function resetConversation() {
            if (confirm('Reset conversation and start new session? Current session will be saved first.')) {
                try {
                    // Save current session if exists
                    if (currentSessionId && conversationHistory.length > 0) {
                        saveCurrentSession();
                    }
                    
                    // Create new session
                    currentSessionId = 'session_' + Date.now();
                    conversationHistory = [];
                    totalInputTokens = 0;
                    totalOutputTokens = 0;
                    sessionMessages = [];
                    lastTurnInputTokens = 0;

                    document.getElementById('messages').innerHTML = `
                        <div class="message message-assistant">
                            <div class="message-content">
                                <p>New session started! I'm ready to help you.</p>
                                <p style="margin-top: 10px; font-size: 13px; opacity: 0.8;">Session ID: ${currentSessionId}</p>
                            </div>
                        </div>
                    `;
                    document.getElementById('breakdown').innerHTML = '';
                    clearError();
                    updateMetrics();
                    updateSessionInfo();
                    console.log('New session started:', currentSessionId);
                } catch (error) {
                    console.error('Error resetting conversation:', error);
                    showError('Error resetting conversation: ' + error.message);
                }
            }
        }

        async function checkCredit() {
            const apiKey = document.getElementById('apiKey').value;
            if (!apiKey) {
                showError('Please select an API token first.');
                return;
            }
            try {
                const btn = event && event.target;
                if (btn) { btn.disabled = true; btn.textContent = 'Checking...'; }

                const resp = await fetch('/api/check-credit', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_key: apiKey }),
                });
                const data = await resp.json();

                if (btn) { btn.disabled = false; btn.textContent = 'Check Credit'; }

                if (data.error) {
                    showError('Credit check failed: ' + data.error);
                    return;
                }

                let msg = '';
                if (data.credit_status === 'exhausted') {
                    msg = '\u26a0\ufe0f Credit Exhausted — ' + data.message;
                } else {
                    msg = '\u2705 API Key Valid — Credit Active';
                    const rl = data.rate_limits || {};
                    const parts = [];
                    if (rl.requests_remaining !== undefined && rl.requests_limit !== undefined)
                        parts.push('Requests: ' + Number(rl.requests_remaining).toLocaleString() + ' / ' + Number(rl.requests_limit).toLocaleString() + ' remaining');
                    if (rl.input_tokens_remaining !== undefined && rl.input_tokens_limit !== undefined)
                        parts.push('Input tokens: ' + Number(rl.input_tokens_remaining).toLocaleString() + ' / ' + Number(rl.input_tokens_limit).toLocaleString() + ' remaining');
                    if (rl.output_tokens_remaining !== undefined && rl.output_tokens_limit !== undefined)
                        parts.push('Output tokens: ' + Number(rl.output_tokens_remaining).toLocaleString() + ' / ' + Number(rl.output_tokens_limit).toLocaleString() + ' remaining');
                    if (rl.tokens_remaining !== undefined && rl.tokens_limit !== undefined)
                        parts.push('Tokens (total): ' + Number(rl.tokens_remaining).toLocaleString() + ' / ' + Number(rl.tokens_limit).toLocaleString() + ' remaining');
                    if (parts.length > 0) msg += '\n' + parts.join('\n');
                }
                alert(msg);
            } catch (err) {
                showError('Credit check error: ' + err.message);
            }
        }

        // Make functions globally accessible
        window.resetConversation = resetConversation;
        window.checkCredit = checkCredit;

        // ============================================================================
        // SESSION MANAGEMENT FUNCTIONS
        // ============================================================================

        function startNewSession() {
            if (conversationHistory.length > 0) {
                if (!confirm('Start a new session? Current conversation will be saved automatically.')) {
                    return;
                }
                // Auto-save current session before starting new one
                if (currentSessionId) {
                    saveCurrentSession();
                }
            }
            
            // Generate new session ID
            currentSessionId = 'session_' + Date.now();
            
            // Reset conversation state
            conversationHistory = [];
            totalInputTokens = 0;
            totalOutputTokens = 0;
            sessionMessages = [];
            lastTurnInputTokens = 0;

            // Clear note field
            const noteInput = document.getElementById('sessionNote');
            if (noteInput) noteInput.value = '';

            // Clear UI
            document.getElementById('messages').innerHTML = `
                <div class="message message-assistant">
                    <div class="message-content">
                        <p>New session started! I'm ready to help you.</p>
                        <p style="margin-top: 10px; font-size: 13px; opacity: 0.8;">Session ID: ${currentSessionId}</p>
                    </div>
                </div>
            `;
            document.getElementById('breakdown').innerHTML = '';
            clearError();
            updateMetrics();
            updateSessionInfo();
            
            showError(` New session started: ${currentSessionId}`, false);
        }

        async function saveCurrentSession(showNotification = false) {
            if (!currentSessionId) {
                if (showNotification) showError('No active session to save');
                return;
            }

            try {
                // Get note from input field if exists
                const noteInput = document.getElementById('sessionNote');
                const sessionNote = noteInput ? noteInput.value.trim() : '';
                
                const sessionData = {
                    session_id: currentSessionId,
                    timestamp: new Date().toISOString(),
                    conversation_history: conversationHistory,
                    total_input_tokens: totalInputTokens,
                    total_output_tokens: totalOutputTokens,
                    messages: sessionMessages,
                    token_id: document.getElementById('apiTokenSelect').value || '',
                    model: getSelectedModel(),
                    note: sessionNote
                };

                const response = await fetch('/api/sessions', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(sessionData)
                });

                if (response.ok) {
                    if (showNotification) {
                        showError(`Session saved successfully`, false);
                    }
                    // Update the session info to reflect the save
                    updateSessionInfo();
                } else {
                    const error = await response.json();
                    showError(`Failed to save session: ${error.error}`);
                }
            } catch (error) {
                showError(`Error saving session: ${error.message}`);
                console.error('Save session error:', error);
            }
        }

        async function showLoadSessionDialog() {
            try {
                // Fetch sessions and tokens in parallel
                const [sessionsResp, tokensResp] = await Promise.all([
                    fetch('/api/sessions'),
                    fetch('/api/tokens')
                ]);
                if (!sessionsResp.ok) {
                    throw new Error('Failed to load sessions list');
                }

                const data = await sessionsResp.json();
                // Filter out comparison sessions (those starting with "comparison")
                const sessions = (data.sessions || []).filter(s => !s.id.startsWith('comparison'));

                if (sessions.length === 0) {
                    showError('No saved sessions found');
                    return;
                }

                // Build token ID → display name map
                const tokenMap = {};
                if (tokensResp.ok) {
                    const tokensData = await tokensResp.json();
                    (tokensData.tokens || []).forEach(t => {
                        tokenMap[String(t.id)] = `${t.name} (${t.provider})`;
                    });
                }

                // Create modal dialog with larger size
                const modal = document.createElement('div');
                modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 2000; display: flex; align-items: center; justify-content: center; padding: 20px;';
                
                const dialog = document.createElement('div');
                dialog.style.cssText = 'background: white; border-radius: 12px; padding: 0; width: 90%; max-width: 1200px; height: 85vh; display: flex; flex-direction: column; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);';
                
                // Header with title and close button
                let html = '<div style="padding: 20px 24px; border-bottom: 2px solid #E2E2E4; display: flex; justify-content: space-between; align-items: center;">';
                html += '<h2 style="margin: 0; color: #000000; font-size: 24px;">Load Session</h2>';
                html += '<button onclick="document.body.removeChild(this.closest(\'[style*=fixed]\'))" style="padding: 8px 20px; background: #929395; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500; transition: background 0.2s;" onmouseover="this.style.background=\'#767676\'" onmouseout="this.style.background=\'#929395\'"> Close</button>';
                html += '</div>';
                
                // Search bar
                html += '<div style="padding: 16px 24px; border-bottom: 1px solid #E2E2E4;">';
                html += '<input type="text" id="sessionSearchInput" placeholder=" Search by session ID or note..." style="width: 100%; padding: 12px 16px; border: 2px solid #C7C9CA; border-radius: 8px; font-size: 14px; transition: border-color 0.2s;" onfocus="this.style.borderColor=\'#3533FF\'" onblur="this.style.borderColor=\'#C7C9CA\'" oninput="filterSessions(this.value)">';
                html += '</div>';
                
                // Sessions list
                html += '<div id="sessionsList" style="flex: 1; overflow-y: auto; padding: 16px 24px;">';
                
                sessions.forEach(session => {
                    const date = new Date(session.timestamp).toLocaleString();
                    const noteDisplay = session.note ? `<div style="font-size: 12px; color: #3533FF; margin-top: 8px; padding: 6px 10px; background: #E8F9FF; border-radius: 6px; display: inline-block; font-weight: 500;"> ${session.note}</div>` : '';
                    const modelName = session.model && ((dynamicModels && dynamicModels[session.model]) || MODEL_CONFIGS[session.model])
                        ? ((dynamicModels && dynamicModels[session.model]) || MODEL_CONFIGS[session.model]).name
                        : (session.model || '');
                    const modelDisplay = modelName ? `<span style="background: #F0E6FF; color: #7C3AED; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500;">${modelName}</span>` : '';
                    const tokenName = session.token_id && tokenMap[String(session.token_id)] ? tokenMap[String(session.token_id)] : '';
                    const tokenDisplay = tokenName ? `<span style="background: #FFF8D6; color: #CC4820; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500;">🔑 ${tokenName}</span>` : '';
                    html += `
                        <div class="session-item" data-session-id="${session.id.toLowerCase()}" data-note="${(session.note || '').toLowerCase()}" 
                             style="padding: 16px; background: #F4F4F4; border-radius: 8px; margin-bottom: 12px; border: 2px solid transparent; transition: all 0.2s; position: relative;" 
                             onmouseover="this.style.borderColor='#3533FF'; this.style.background='#ffffff'; this.style.boxShadow='0 4px 6px -1px rgba(0,0,0,0.1)'" 
                             onmouseout="this.style.borderColor='transparent'; this.style.background='#F4F4F4'; this.style.boxShadow='none'">
                            <div style="cursor: pointer;" onclick="loadSession('${session.id}'); document.body.removeChild(this.closest('[style*=fixed]'))">
                                <div style="font-weight: 600; color: #000000; font-size: 15px; margin-bottom: 6px; padding-right: 100px;">${session.id}</div>
                                <div style="font-size: 13px; color: #929395; margin-bottom: 8px;">
                                    ${date}  ${session.message_count} messages  ${session.total_tokens.toLocaleString()} tokens
                                </div>
                                ${(modelDisplay || tokenDisplay) ? `<div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px;">${modelDisplay}${tokenDisplay}</div>` : ''}
                                ${noteDisplay}
                            </div>
                            <button onclick="event.stopPropagation(); deleteSession('${session.id}', this.closest('.session-item'))" 
                                    style="position: absolute; top: 16px; right: 16px; padding: 6px 12px; background: #FF5A26; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 12px; font-weight: 500; transition: background 0.2s;" 
                                    onmouseover="this.style.background='#CC4820'" 
                                    onmouseout="this.style.background='#FF5A26'"
                                    title="Delete this session">
                                 Delete
                            </button>
                        </div>
                    `;
                });
                
                html += '</div>';
                
                dialog.innerHTML = html;
                modal.appendChild(dialog);
                document.body.appendChild(modal);
                
            } catch (error) {
                showError(`Error loading sessions: ${error.message}`);
                console.error('Load sessions error:', error);
            }
        }

        function filterSessions(searchTerm) {
            const term = searchTerm.toLowerCase().trim();
            const sessionItems = document.querySelectorAll('.session-item');
            
            sessionItems.forEach(item => {
                const sessionId = item.getAttribute('data-session-id');
                const note = item.getAttribute('data-note');
                
                if (sessionId.includes(term) || note.includes(term)) {
                    item.style.display = 'block';
                } else {
                    item.style.display = 'none';
                }
            });
        }

        async function loadSession(sessionId) {
            try {
                // Save current session if exists
                if (currentSessionId && conversationHistory.length > 0) {
                    await saveCurrentSession();
                }

                const response = await fetch(`/api/sessions/${sessionId}`);
                if (!response.ok) {
                    throw new Error('Failed to load session');
                }

                const sessionData = await response.json();
                
                // Restore session state
                currentSessionId = sessionData.session_id;
                conversationHistory = sessionData.conversation_history || [];
                totalInputTokens = sessionData.total_input_tokens || 0;
                totalOutputTokens = sessionData.total_output_tokens || 0;
                sessionMessages = sessionData.messages || [];

                // Restore MCP servers if the session used them
                if (sessionData.servers && sessionData.servers.length > 0) {
                    await loadAvailableMcpServers();
                }

                // Restore token selection if the session tracked it
                if (sessionData.token_id) {
                    const tokenSelect = document.getElementById('apiTokenSelect');
                    if (tokenSelect.querySelector(`option[value="${sessionData.token_id}"]`)) {
                        tokenSelect.value = sessionData.token_id;
                        await onTokenSelected();
                    }
                }

                // Restore model selection if the session tracked it
                if (sessionData.model) {
                    const modelSelect = document.getElementById('modelSelect');
                    if (modelSelect && modelSelect.querySelector(`option[value="${sessionData.model}"]`)) {
                        modelSelect.value = sessionData.model;
                        onModelSelected();
                    }
                }

                // Restore note if exists, otherwise clear it
                const noteInput = document.getElementById('sessionNote');
                if (noteInput) {
                    noteInput.value = sessionData.note || '';
                }

                // Clear and rebuild UI
                document.getElementById('messages').innerHTML = '';
                document.getElementById('breakdown').innerHTML = '';

                // Helper: convert content blocks array to UI segments
                function buildContentSegments(content) {
                    let contentBlocks = [];
                    if (Array.isArray(content)) {
                        let currentTextBlock = '';
                        let currentTools = [];
                        let currentThinking = '';
                        for (const block of content) {
                            if (block.type === 'thinking') {
                                currentThinking += block.thinking || '';
                            } else if (block.type === 'text') {
                                if (currentTools.length > 0) {
                                    contentBlocks.push({ content: currentTextBlock, tools: currentTools, thinking: currentThinking });
                                    currentTextBlock = '';
                                    currentTools = [];
                                    currentThinking = '';
                                }
                                currentTextBlock += block.text || '';
                            } else if (block.type === 'tool_use' || block.type === 'mcp_tool_use') {
                                currentTools.push({ type: 'tool_use', name: block.name, input: block.input });
                            } else if (block.type === 'tool_result' || block.type === 'mcp_tool_result') {
                                currentTools.push({ type: 'tool_result', content: block.content });
                            }
                        }
                        if (currentTextBlock || currentTools.length > 0 || currentThinking) {
                            contentBlocks.push({ content: currentTextBlock, tools: currentTools, thinking: currentThinking });
                        }
                    } else if (typeof content === 'string') {
                        contentBlocks = [{ content: content, tools: [], thinking: '' }];
                    }
                    return contentBlocks;
                }

                // Render chat bubbles from conversationHistory (authoritative message sequence)
                // Deduplicate consecutive user messages with identical content (old mutation bug)
                let prevUserContent = null;
                for (const msg of conversationHistory) {
                    if (msg.role === 'user') {
                        const text = typeof msg.content === 'string'
                            ? msg.content
                            : Array.isArray(msg.content)
                                ? msg.content.map(b => b.text || '').join('')
                                : String(msg.content || '');
                        if (text === prevUserContent) continue; // skip duplicate
                        prevUserContent = text;
                        addMessageToUI('user', text);
                    } else if (msg.role === 'assistant') {
                        prevUserContent = null; // reset after assistant reply
                        const contentBlocks = buildContentSegments(msg.content);
                        const segments = contentBlocks.length > 0 ? contentBlocks : [{ content: '(No text)', tools: [] }];
                        addMessageToUI('assistant', segments, 0, null, false, false);
                    }
                }

                // Build breakdown cards from sessionMessages (has per-request token details)
                if (sessionMessages.length > 0) {
                    sessionMessages.forEach((msg, index) => {
                        const inputTokens = msg.response?.usage?.input_tokens || 0;
                        const outputTokens = msg.response?.usage?.output_tokens || 0;
                        if (inputTokens > 0 || outputTokens > 0) {
                            addToBreakdown(index + 1, inputTokens, outputTokens, index);
                        }
                    });
                } else if (totalInputTokens > 0 || totalOutputTokens > 0) {
                    // No per-request detail — show session-level totals
                    addToBreakdown(1, totalInputTokens, totalOutputTokens);
                }

                updateMetrics();
                updateSessionInfo();
                showError(`Session loaded: ${sessionId}`, false);

            } catch (error) {
                showError(`Error loading session: ${error.message}`);
                console.error('Load session error:', error);
            }
        }

        function updateSessionInfo() {
            const infoDiv = document.getElementById('currentSessionInfo');
            const noteContainer = document.getElementById('sessionNoteContainer');
            
            if (currentSessionId) {
                // Count only genuine user ↔ assistant exchanges, not internal tool-loop messages
                const userMessages = conversationHistory.filter(m => {
                    if (m.role !== 'user') return false;
                    // Exclude tool_result entries (tool loop internals packed as user messages)
                    if (Array.isArray(m.content) && m.content.length > 0 && m.content[0].type === 'tool_result') return false;
                    return true;
                }).length;
                const messageCount = userMessages;
                const totalTokens = totalInputTokens + totalOutputTokens;
                const lastSaved = sessionMessages.length > 0 ? new Date(sessionMessages[sessionMessages.length - 1].timestamp).toLocaleTimeString() : 'Not saved yet';
                infoDiv.innerHTML = `
                    <div style="font-weight: 600; margin-bottom: 4px; font-size: 12px; color: #000000;">${currentSessionId}</div>
                    <div style="font-size: 11px; color: #929395; margin-bottom: 4px;">${messageCount} messages  ${totalTokens.toLocaleString()} tokens</div>
                    <div style="font-size: 10px; color: #4CD97A; display: flex; align-items: center; justify-content: center; gap: 4px;">
                        <span style="font-size: 14px;"></span> Auto-saved ${sessionMessages.length > 0 ? 'at ' + lastSaved : ''}
                    </div>
                `;
                // Show note container when session is active
                if (noteContainer) {
                    noteContainer.style.display = 'block';
                }
            } else {
                infoDiv.innerHTML = 'No active session';
                // Hide note container when no active session
                if (noteContainer) {
                    noteContainer.style.display = 'none';
                }
            }
        }

        // Make session functions globally accessible
        window.startNewSession = startNewSession;
        window.saveCurrentSession = saveCurrentSession;
        window.showLoadSessionDialog = showLoadSessionDialog;
        window.loadSession = loadSession;

        async function deleteSession(sessionId, sessionElement) {
            // Confirm deletion
            if (!confirm(`Are you sure you want to delete session "${sessionId}"?\n\nThis action cannot be undone.`)) {
                return;
            }

            try {
                const response = await fetch(`/api/sessions/${sessionId}`, {
                    method: 'DELETE'
                });

                if (!response.ok) {
                    throw new Error('Failed to delete session');
                }

                // Remove the session element from the UI with animation
                sessionElement.style.opacity = '0';
                sessionElement.style.transform = 'translateX(-20px)';
                sessionElement.style.transition = 'opacity 0.3s, transform 0.3s';
                
                setTimeout(() => {
                    sessionElement.remove();
                    
                    // Check if there are any sessions left
                    const remainingSessions = document.querySelectorAll('.session-item');
                    if (remainingSessions.length === 0) {
                        const sessionsList = document.getElementById('sessionsList');
                        if (sessionsList) {
                            sessionsList.innerHTML = '<div style="text-align: center; padding: 40px; color: #929395; font-size: 14px;">No sessions available</div>';
                        }
                    }
                }, 300);

                showError(`Session "${sessionId}" deleted successfully`, false);

            } catch (error) {
                showError(`Error deleting session: ${error.message}`);
                console.error('Delete session error:', error);
            }
        }
        window.deleteSession = deleteSession;

        // ============================================================================
        // MCP PROMPTS DIALOG
        // ============================================================================

        function showMcpPromptsDialog() {
            // Get selected servers with prompts
            const selectedServers = getSelectedMcpServers();
            const serversWithPrompts = selectedServers.filter(s => 
                s.prompts && s.prompts.length > 0
            );

            if (serversWithPrompts.length === 0) {
                showError('No prompts available. Select MCP servers with prompts and test connections on the Connections page first.');
                return;
            }

            // Create modal dialog
            const modal = document.createElement('div');
            modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 2000; display: flex; align-items: center; justify-content: center; padding: 20px;';
            
            const dialog = document.createElement('div');
            dialog.style.cssText = 'background: white; border-radius: 12px; padding: 0; width: 90%; max-width: 900px; height: 85vh; display: flex; flex-direction: column; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);';
            
            // Header
            let html = '<div style="padding: 20px 24px; border-bottom: 2px solid #E2E2E4; display: flex; justify-content: space-between; align-items: center;">';
            html += '<h2 style="margin: 0; color: #000000; font-size: 24px;"> MCP Prompts</h2>';
            html += '<button onclick="document.body.removeChild(this.closest(\'[style*=fixed]\'))" style="padding: 8px 20px; background: #929395; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500; transition: background 0.2s;" onmouseover="this.style.background=\'#767676\'" onmouseout="this.style.background=\'#929395\'"> Close</button>';
            html += '</div>';
            
            // Search bar
            html += '<div style="padding: 16px 24px; border-bottom: 1px solid #E2E2E4;">';
            html += '<input type="text" id="promptSearchInput" placeholder=" Search prompts..." style="width: 100%; padding: 12px 16px; border: 2px solid #C7C9CA; border-radius: 8px; font-size: 14px; transition: border-color 0.2s;" onfocus="this.style.borderColor=\'#3533FF\'" onblur="this.style.borderColor=\'#C7C9CA\'" oninput="filterPrompts(this.value)">';
            html += '</div>';
            
            // Prompts list
            html += '<div id="promptsList" style="flex: 1; overflow-y: auto; padding: 16px 24px;">';
            
            serversWithPrompts.forEach(server => {
                html += `<div class="server-prompts-section" style="margin-bottom: 24px;">`;
                html += `<h3 style="color: #3533FF; font-size: 16px; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">`;
                html += `<span>&#9679;</span> ${escapeHtml(server.name)} <span style="font-size: 12px; color: #929395; font-weight: 400;">(${server.prompts.length} prompts)</span>`;
                html += `</h3>`;
                
                server.prompts.forEach((prompt, idx) => {
                    const promptId = `${server.id}_${idx}`;
                    const searchText = `${prompt.title || prompt.name} ${prompt.description || ''} ${server.name}`.toLowerCase();
                    
                    html += `
                        <div class="prompt-item" data-search="${escapeHtml(searchText)}" 
                             style="padding: 16px; background: #F4F4F4; border-radius: 8px; margin-bottom: 12px; border: 2px solid transparent; transition: all 0.2s; cursor: pointer;" 
                             onmouseover="this.style.borderColor='#3533FF'; this.style.background='#ffffff'; this.style.boxShadow='0 4px 6px -1px rgba(0,0,0,0.1)'" 
                             onmouseout="this.style.borderColor='transparent'; this.style.background='#F4F4F4'; this.style.boxShadow='none'"
                             onclick="selectPrompt('${server.id}', ${idx})">
                            <div style="font-weight: 600; color: #000000; font-size: 15px; margin-bottom: 6px;">${escapeHtml(prompt.title || prompt.name)}</div>
                            ${prompt.description ? `<div style="font-size: 13px; color: #929395; margin-bottom: 8px; white-space: pre-wrap;">${escapeHtml(prompt.description)}</div>` : ''}
                            ${prompt.arguments && prompt.arguments.length > 0 ? `
                                <div style="margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px;">
                                    ${prompt.arguments.map(arg => `
                                        <span style="background: white; padding: 4px 8px; border-radius: 4px; font-size: 11px; color: #767676; border: 1px solid #E2E2E4;">
                                            ${escapeHtml(arg.name)}${arg.required ? '<span style="color: #FF5A26;"> *</span>' : ''}
                                        </span>
                                    `).join('')}
                                </div>
                            ` : ''}
                        </div>
                    `;
                });
                
                html += '</div>';
            });
            
            html += '</div>';
            
            dialog.innerHTML = html;
            modal.appendChild(dialog);
            document.body.appendChild(modal);
        }

        function filterPrompts(searchTerm) {
            const term = searchTerm.toLowerCase().trim();
            const promptItems = document.querySelectorAll('.prompt-item');
            
            promptItems.forEach(item => {
                const searchText = item.getAttribute('data-search') || '';
                if (term === '' || searchText.includes(term)) {
                    item.style.display = '';
                } else {
                    item.style.display = 'none';
                }
            });
        }

        async function selectPrompt(serverId, promptIndex) {
            const server = mcpServers.find(s => s.id === serverId);
            if (!server || !server.prompts || !server.prompts[promptIndex]) {
                showError('Prompt not found');
                return;
            }

            const prompt = server.prompts[promptIndex];
            
            // Close the prompts dialog immediately
            const modals = document.querySelectorAll('[style*="position: fixed"]');
            modals.forEach(modal => {
                if (modal.textContent.includes('MCP Prompts') || modal.querySelector('#promptsList')) {
                    document.body.removeChild(modal);
                }
            });

            // If prompt has arguments, show a dialog to collect them
            if (prompt.arguments && prompt.arguments.length > 0) {
                showPromptArgumentsDialog(server, prompt);
            } else {
                // No arguments, use prompt directly
                await usePrompt(serverId, prompt.name, {});
            }
        }

        function showPromptArgumentsDialog(server, prompt) {
            // Create modal for argument input
            const modal = document.createElement('div');
            modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 2001; display: flex; align-items: center; justify-content: center; padding: 20px;';
            
            const dialog = document.createElement('div');
            dialog.style.cssText = 'background: white; border-radius: 12px; padding: 24px; width: 90%; max-width: 600px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);';
            
            let html = `<h2 style="margin: 0 0 16px 0; color: #000000; font-size: 20px;">${escapeHtml(prompt.title || prompt.name)}</h2>`;
            if (prompt.description) {
                html += `<p style="color: #929395; font-size: 14px; margin-bottom: 20px;">${escapeHtml(prompt.description)}</p>`;
            }
            
            html += '<form id="promptArgsForm" style="display: flex; flex-direction: column; gap: 16px;">';
            
            prompt.arguments.forEach(arg => {
                html += `
                    <div>
                        <label style="display: block; font-weight: 500; color: #000000; font-size: 14px; margin-bottom: 6px;">
                            ${escapeHtml(arg.name)}
                            ${arg.required ? '<span style="color: #FF5A26;">*</span>' : '<span style="color: #929395; font-size: 12px;">(optional)</span>'}
                        </label>
                        ${arg.description ? `<div style="font-size: 12px; color: #929395; margin-bottom: 6px;">${escapeHtml(arg.description)}</div>` : ''}
                        <input type="text" name="${escapeHtml(arg.name)}" ${arg.required ? 'required' : ''} 
                               style="width: 100%; padding: 10px 12px; border: 2px solid #C7C9CA; border-radius: 6px; font-size: 14px;"
                               placeholder="Enter ${escapeHtml(arg.name)}...">
                    </div>
                `;
            });
            
            html += '<div style="display: flex; gap: 12px; margin-top: 8px;">';
            html += '<button type="button" onclick="document.body.removeChild(this.closest(\'[style*=fixed]\'))" style="flex: 1; padding: 12px; background: #E2E2E4; color: #000000; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500;">Cancel</button>';
            html += '<button type="submit" style="flex: 1; padding: 12px; background: #3533FF; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500;">Use Prompt</button>';
            html += '</div>';
            html += '</form>';
            
            dialog.innerHTML = html;
            modal.appendChild(dialog);
            document.body.appendChild(modal);
            
            // Handle form submission
            document.getElementById('promptArgsForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                const args = {};
                formData.forEach((value, key) => {
                    if (value) args[key] = value;
                });
                
                document.body.removeChild(modal);
                await usePrompt(server.id, prompt.name, args);
            });
        }

        async function usePrompt(serverId, promptName, args) {
            try {
                showError(' Loading prompt...', false);
                
                // Fetch the prompt content from the MCP server
                const response = await fetch('/api/mcp/get-prompt', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        server_id: serverId,
                        prompt_name: promptName,
                        arguments: args
                    })
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.error || 'Failed to get prompt');
                }

                const result = await response.json();
                console.log('Prompt result:', result);
                console.log('Result keys:', Object.keys(result));
                console.log('Result JSON:', JSON.stringify(result, null, 2));
                
                // Extract prompt text from the messages
                let promptText = '';
                
                if (result.messages && result.messages.length > 0) {
                    // Concatenate all messages
                    result.messages.forEach(msg => {
                        if (msg.role && msg.content) {
                            let msgText = '';
                            if (typeof msg.content === 'string') {
                                msgText = msg.content;
                            } else if (msg.content.type === 'text' && msg.content.text) {
                                // Handle object format: { type: 'text', text: '...' }
                                msgText = msg.content.text;
                            } else if (Array.isArray(msg.content)) {
                                // Handle array format
                                msg.content.forEach(c => {
                                    if (c.type === 'text' && c.text) {
                                        msgText += c.text + '\n';
                                    } else if (typeof c === 'string') {
                                        msgText += c + '\n';
                                    }
                                });
                            }
                            if (msgText) {
                                promptText += msgText.trim() + '\n\n';
                            }
                        }
                    });
                } else if (result.description) {
                    // Fallback to description if no messages
                    promptText = result.description;
                } else if (typeof result === 'string') {
                    // Handle if result is a plain string
                    promptText = result;
                }
                
                promptText = promptText.trim();
                
                if (!promptText) {
                    console.error('Empty prompt content. Full result:', result);
                    throw new Error('No prompt content returned. Check console for details.');
                }
                
                // Insert the prompt text into the user input
                const userInput = document.getElementById('userInput');
                userInput.value = promptText;
                userInput.focus();
                
                // Get prompt title from cache
                const server = mcpServers.find(s => s.id === serverId);
                const prompt = server?.prompts?.find(p => p.name === promptName);
                const promptTitle = prompt?.title || prompt?.name || promptName;
                
                showError(` Prompt "${promptTitle}" loaded`, false);
                
            } catch (error) {
                showError(`Error loading prompt: ${error.message}`);
                console.error('Load prompt error:', error);
            }
        }

        window.showMcpPromptsDialog = showMcpPromptsDialog;
        window.selectPrompt = selectPrompt;
        window.filterPrompts = filterPrompts;

        // ============================================================================
        // MESSAGE DETAILS MODAL
        // ============================================================================

        function showMessageDetails(messageIndex) {
            const message = sessionMessages[messageIndex];
            if (!message) {
                showError('Message not found');
                return;
            }

            const modal = document.getElementById('messageDetailsModal');
            const content = document.getElementById('messageDetailsContent');

            // Sanitize sensitive data
            const sanitizedRequest = JSON.parse(JSON.stringify(message.request));
            if (sanitizedRequest.api_key) sanitizedRequest.api_key = '***HIDDEN***';

            // Derived values
            const timestamp = new Date(message.timestamp).toLocaleString();
            const duration = message.duration_seconds || 'N/A';
            const perf = message.perf || {};
            const sp = message.sampling_params || {};
            const toolChain = message.tool_chain || [];

            let mcpServersList = 'None';
            if (message.request.servers?.length > 0) {
                mcpServersList = message.request.servers.map(s => s.name || s.id).join(', ');
            }
            let toolCount = 0;
            if (Array.isArray(message.response.content)) {
                toolCount = message.response.content.filter(b => b.type === 'mcp_tool_use' || b.type === 'tool_use').length;
            }

            const usage = message.response.usage || {};
            const provider = message.response.provider || (message.request.provider || 'anthropic');

            // cURL generator
            const curlBody = JSON.stringify(sanitizedRequest, null, 2).replace(/'/g, "'\\''");
            const curlCmd = `curl http://localhost:5000/api/chat \\\n  -H "Content-Type: application/json" \\\n  -d '${curlBody}'`;

            // Tab helper — inline function used in onclick
            const tabs = ['overview', 'params', 'request', 'response', 'toolchain'];

            // Build HTML with tabs
            let html = `
            <div class="modal-tabs" id="detailsTabs-${messageIndex}">
                <div class="modal-tab active" onclick="switchDetailTab('${messageIndex}','overview')">Overview</div>
                <div class="modal-tab" onclick="switchDetailTab('${messageIndex}','params')">Parameters</div>
                <div class="modal-tab" onclick="switchDetailTab('${messageIndex}','request')">Request</div>
                <div class="modal-tab" onclick="switchDetailTab('${messageIndex}','response')">Response</div>
                <div class="modal-tab" onclick="switchDetailTab('${messageIndex}','toolchain')">Tool Chain${toolChain.length > 0 ? ' <span style=\'background:#3533FF;color:white;border-radius:10px;padding:1px 6px;font-size:10px;\'>'+toolChain.length+'</span>' : ''}</div>
            </div>

            <!-- OVERVIEW TAB -->
            <div id="tab-${messageIndex}-overview" class="modal-tab-content active">
                <div style="background:#F4F4F4;padding:12px;border-radius:6px;margin-bottom:16px;">
                    <div style="display:grid;grid-template-columns:160px 1fr;gap:8px;font-size:13px;">
                        <div style="font-weight:600;color:#929395;">Timestamp</div><div>${timestamp}</div>
                        <div style="font-weight:600;color:#929395;">Total Duration</div><div>${duration}s (${message.duration_ms || 'N/A'}ms)</div>
                        ${perf.ttft_ms != null ? `<div style="font-weight:600;color:#929395;">TTFT</div><div><span style="color:#3533FF;font-weight:700;">${(perf.ttft_ms/1000).toFixed(2)}s</span></div>` : ''}
                        ${perf.tps != null ? `<div style="font-weight:600;color:#929395;">Generation Speed</div><div><span style="color:#3533FF;font-weight:700;">${perf.tps} tok/s</span></div>` : ''}
                        <div style="font-weight:600;color:#929395;">Model</div><div>${message.response.model || 'N/A'}</div>
                        <div style="font-weight:600;color:#929395;">Provider</div><div>${provider}</div>
                        <div style="font-weight:600;color:#929395;">Message ID</div><div style="font-family:monospace;font-size:11px;">${message.response.id || 'N/A'}</div>
                        <div style="font-weight:600;color:#929395;">Stop Reason</div>
                        <div><span class="stop-badge stop-badge-${message.stop_reason || 'end_turn'}">${message.stop_reason || message.response.stop_reason || 'N/A'}</span></div>
                        <div style="font-weight:600;color:#929395;">MCP Servers</div><div>${mcpServersList}${toolCount > 0 ? ' (' + toolCount + ' tools)' : ''}</div>
                    </div>
                </div>
                <div style="background:#EDFFF3;padding:12px;border-radius:6px;">
                    <div style="font-weight:600;font-size:13px;margin-bottom:8px;color:#3BB366;">Token Usage</div>
                    <div style="display:grid;grid-template-columns:160px 1fr;gap:6px;font-size:13px;">
                        <div style="color:#929395;">Input</div><div style="font-weight:600;">${(usage.input_tokens||0).toLocaleString()}</div>
                        <div style="color:#929395;">Output</div><div style="font-weight:600;">${(usage.output_tokens||0).toLocaleString()}</div>
                        <div style="color:#929395;">Cache Read</div><div>${(usage.cache_read_input_tokens||0).toLocaleString()}</div>
                        <div style="color:#929395;">Cache Created</div><div>${(usage.cache_creation_input_tokens||0).toLocaleString()}</div>
                        <div style="color:#929395;border-top:1px solid #B8F5CB;padding-top:4px;">Total</div>
                        <div style="font-weight:700;border-top:1px solid #B8F5CB;padding-top:4px;">${((usage.input_tokens||0)+(usage.output_tokens||0)).toLocaleString()}</div>
                    </div>
                </div>
            </div>

            <!-- PARAMS TAB -->
            <div id="tab-${messageIndex}-params" class="modal-tab-content">
                <div style="background:#F4F4F4;padding:12px;border-radius:6px;margin-bottom:16px;">
                    <div style="font-weight:600;font-size:13px;margin-bottom:10px;color:#313131;">Sampling Parameters Used</div>
                    <div style="display:grid;grid-template-columns:160px 1fr;gap:8px;font-size:13px;">
                        <div style="color:#929395;">Temperature</div>
                        <div><span style="font-weight:700;color:#3533FF;">${sp.temperature != null ? sp.temperature.toFixed(2) : 'default'}</span>
                        ${provider === 'anthropic' && sp.temperature > 1.0 ? ' <span style="color:#CC4820;font-size:11px;">(clipped to 1.0 for Anthropic)</span>' : ''}</div>
                        <div style="color:#929395;">Top-P</div>
                        <div style="font-weight:700;color:#3533FF;">${sp.top_p != null ? sp.top_p.toFixed(2) : 'default'}</div>
                        <div style="color:#929395;">Max Tokens</div>
                        <div style="font-weight:700;color:#3533FF;">${sp.max_tokens != null ? sp.max_tokens.toLocaleString() : 'N/A'}</div>
                        <div style="color:#929395;">Stop Sequences</div>
                        <div style="font-family:monospace;font-size:12px;">${sp.stop_sequences?.length > 0 ? sp.stop_sequences.map(s => `<code>${escapeHtml(s)}</code>`).join(', ') : 'none'}</div>
                    </div>
                </div>
                <div style="background:#F4F4F4;padding:12px;border-radius:6px;">
                    <div style="font-weight:600;font-size:13px;margin-bottom:8px;color:#313131;">Provider Notes</div>
                    <div style="font-size:12px;color:#767676;line-height:1.6;">
                        <b>Temperature:</b> Anthropic 0–1.0, OpenAI 0–2.0, Mistral 0–1.0. Values &gt;1.0 are clipped for Anthropic and Mistral.<br>
                        <b>Top-P:</b> 0–1.0 for all providers. Controls nucleus sampling — lower = more focused.<br>
                        <b>Stop sequences:</b> Anthropic uses <code>stop_sequences</code> key; OpenAI and Mistral use <code>stop</code>.
                    </div>
                </div>
            </div>

            <!-- REQUEST TAB -->
            <div id="tab-${messageIndex}-request" class="modal-tab-content">
                <div style="margin-bottom:10px;display:flex;gap:8px;flex-wrap:wrap;">
                    <button onclick="copyToClipboard('req-json-${messageIndex}')" style="padding:5px 12px;background:#3533FF;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;">Copy JSON</button>
                    <button onclick="copyToClipboard('req-curl-${messageIndex}')" style="padding:5px 12px;background:#313131;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;">Copy as cURL</button>
                </div>
                <div style="background:#F4F4F4;padding:12px;border-radius:6px;margin-bottom:12px;position:relative;">
                    <pre id="req-json-${messageIndex}" style="margin:0;overflow-x:auto;font-size:11px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;">${JSON.stringify(sanitizedRequest, null, 2)}</pre>
                </div>
                <div style="font-size:12px;font-weight:600;color:#929395;margin-bottom:6px;">cURL Command</div>
                <div style="background:#313131;border-radius:6px;padding:12px;position:relative;">
                    <pre id="req-curl-${messageIndex}" style="margin:0;overflow-x:auto;font-size:11px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;color:#E2E2E4;">${escapeHtml(curlCmd)}</pre>
                </div>
            </div>

            <!-- RESPONSE TAB -->
            <div id="tab-${messageIndex}-response" class="modal-tab-content">
                <div style="margin-bottom:10px;">
                    <button onclick="copyToClipboard('resp-json-${messageIndex}')" style="padding:5px 12px;background:#3533FF;color:white;border:none;border-radius:4px;cursor:pointer;font-size:12px;">Copy JSON</button>
                </div>
                <div style="background:#F4F4F4;padding:12px;border-radius:6px;position:relative;">
                    <pre id="resp-json-${messageIndex}" style="margin:0;overflow-x:auto;font-size:11px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;">${JSON.stringify(message.response, null, 2)}</pre>
                </div>
            </div>

            <!-- TOOL CHAIN TAB -->
            <div id="tab-${messageIndex}-toolchain" class="modal-tab-content">
            `;

            if (toolChain.length === 0) {
                // Try to derive from content blocks (Anthropic native/client-side MCP)
                const contentTools = (message.response.content || []).filter(
                    b => b.type === 'mcp_tool_use' || b.type === 'tool_use'
                );
                if (contentTools.length === 0) {
                    html += `<div style="padding:20px;text-align:center;color:#929395;font-size:13px;">No tool calls were made in this request.</div>`;
                } else {
                    html += `<div style="font-size:12px;color:#929395;margin-bottom:12px;">Tool calls detected via content blocks (iteration order not tracked for this provider path).</div>`;
                    contentTools.forEach((b, i) => {
                        const inputStr = JSON.stringify(b.input || {}, null, 2);
                        html += `
                        <div style="background:#F4F4F4;padding:12px;border-radius:6px;margin-bottom:10px;">
                            <div style="font-weight:600;color:#FF5A26;margin-bottom:6px;">⚙ ${escapeHtml(b.name || 'unknown')}</div>
                            <div style="font-size:11px;color:#929395;margin-bottom:4px;">INPUT</div>
                            <pre style="background:white;border:1px solid #E2E2E4;border-radius:4px;padding:8px;font-size:11px;overflow:auto;max-height:150px;margin:0;">${escapeHtml(inputStr)}</pre>
                        </div>`;
                    });
                }
            } else {
                let prevIter = 0;
                toolChain.forEach((step, i) => {
                    if (step.iteration !== prevIter) {
                        prevIter = step.iteration;
                        html += `<div style="font-size:11px;font-weight:700;color:#929395;text-transform:uppercase;letter-spacing:0.5px;margin:${i>0?'16px':0} 0 8px 0;">Iteration ${step.iteration}</div>`;
                    }
                    const inputStr = typeof step.tool_input === 'string' ? step.tool_input : JSON.stringify(step.tool_input, null, 2);
                    html += `
                    <div style="background:#F4F4F4;padding:12px;border-radius:6px;margin-bottom:10px;">
                        <div style="font-weight:600;color:#FF5A26;margin-bottom:8px;">⚙ ${escapeHtml(step.tool_name)}</div>
                        <div style="font-size:11px;color:#929395;margin-bottom:4px;">INPUT</div>
                        <pre style="background:white;border:1px solid #E2E2E4;border-radius:4px;padding:8px;font-size:11px;overflow:auto;max-height:120px;margin:0 0 8px 0;">${escapeHtml(inputStr)}</pre>
                        <div style="font-size:11px;color:#4CD97A;margin-bottom:4px;">OUTPUT</div>
                        <pre style="background:#EDFFF3;border:1px solid #B8F5CB;border-radius:4px;padding:8px;font-size:11px;overflow:auto;max-height:120px;margin:0;">${escapeHtml(step.tool_result || '(empty)')}</pre>
                    </div>`;
                });
            }

            html += `</div>`; // close toolchain tab

            content.innerHTML = html;
            modal.style.display = 'block';
        }

        // Switch tabs in message details modal
        function switchDetailTab(msgIdx, tabName) {
            const tabsEl = document.getElementById(`detailsTabs-${msgIdx}`);
            if (!tabsEl) return;
            // Update tab headers
            tabsEl.querySelectorAll('.modal-tab').forEach((t, i) => {
                const names = ['overview','params','request','response','toolchain'];
                t.classList.toggle('active', names[i] === tabName);
            });
            // Update tab content panels
            ['overview','params','request','response','toolchain'].forEach(name => {
                const el = document.getElementById(`tab-${msgIdx}-${name}`);
                if (el) el.classList.toggle('active', name === tabName);
            });
        }
        window.switchDetailTab = switchDetailTab;

        function closeMessageDetailsModal() {
            document.getElementById('messageDetailsModal').style.display = 'none';
        }

        function copyToClipboard(elementId) {
            const element = document.getElementById(elementId);
            const text = element.textContent;
            navigator.clipboard.writeText(text).then(() => {
                showError('Copied to clipboard!', false);
            }).catch(err => {
                showError('Failed to copy to clipboard');
                console.error('Copy error:', err);
            });
        }

        // Make functions globally accessible
        window.showMessageDetails = showMessageDetails;
        window.closeMessageDetailsModal = closeMessageDetailsModal;
        window.copyToClipboard = copyToClipboard;

        function showError(message, isError = true) {
            const container = document.getElementById('errorContainer');
            const div = document.createElement('div');
            div.className = isError ? 'error-message' : 'error-message';
            div.style.background = isError ? '#FFF0EC' : '#D4FFE2';
            div.style.color = isError ? '#CC4820' : '#3BB366';
            div.style.borderLeftColor = isError ? '#FF5A26' : '#4CD97A';
            div.textContent = message;
            container.innerHTML = '';
            container.appendChild(div);
            
            // Don't auto-dismiss if it contains WARNING or server instructions
            if (!message.includes('WARNING') && !message.includes('python -m http.server')) {
                setTimeout(() => {
                    div.remove();
                }, 5000);
            }
        }

        function clearError() {
            document.getElementById('errorContainer').innerHTML = '';
        }

        function runScenario(scenario) {
            const scenarios = {
                'simple': 'Hi! What is 2 + 2?',
                'analysis': 'Can you explain how context windows work in AI models and why they matter?',
                'mcp-invoices': 'Show me recent customer invoices from Business Central',
                'mcp-opportunities': 'What open sales opportunities do we have?'
            };

            const message = scenarios[scenario];
            if (message) {
                document.getElementById('userInput').value = message;
                sendMessage(message);
            }
        }

        async function debugMcpUrl() {
            const url = document.getElementById('mcpUrl').value;
            
            if (!url) {
                showError('Please enter MCP URL first');
                return;
            }

            const debugButton = event.target;
            const originalText = debugButton.textContent;
            debugButton.textContent = 'Debugging...';
            debugButton.disabled = true;

            try {
                const response = await fetch('/api/debug-mcp-url', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        mcp_url: url // Keep full URL with token for debugging
                    })
                });

                const result = await response.json();
                
                if (response.ok) {
                    let debugMsg = ' MCP URL Debug Results:\n\n';
                    
                    result.results.tests.forEach((test, index) => {
                        const icon = test.success ? '' : '';
                        debugMsg += `${icon} ${test.test}:\n`;
                        debugMsg += `   Status: ${test.status || 'N/A'}\n`;
                        debugMsg += `   Message: ${test.message}\n`;
                        if (test.response_preview) {
                            debugMsg += `   Response: ${test.response_preview}\n`;
                        }
                        debugMsg += '\n';
                    });
                    
                    debugMsg += ' Recommendations:\n';
                    result.recommendations.forEach(rec => {
                        debugMsg += ` ${rec}\n`;
                    });
                    
                    showError(debugMsg, false);
                } else {
                    showError(` Debug Failed: ${result.error || 'Unknown error'}`);
                }
            } catch (error) {
                showError(` Debug Error: ${error.message}`);
                console.error('Debug Exception:', error);
            } finally {
                debugButton.textContent = originalText;
                debugButton.disabled = false;
            }
        }

        // Helper function to escape HTML to prevent injection and preserve formatting
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Helper function to get a human-readable type display
        function getTypeDisplay(schema) {
            if (!schema) return 'any';
            
            if (schema.type === 'array') {
                if (schema.items) {
                    const itemType = schema.items.type || 'object';
                    return `array<${itemType}>`;
                }
                return 'array';
            }
            
            if (schema.type === 'object') {
                return 'object';
            }
            
            if (schema.enum) {
                return `enum (${schema.enum.length} options)`;
            }
            
            return schema.type || 'any';
        }

        function viewMcpCapabilities(serverId) {
            const server = mcpServers.find(s => s.id === serverId);
            if (!server) return;

            const modal = document.getElementById('mcpCapabilitiesModal');
            const modalServerName = document.getElementById('modalServerName');
            const modalContent = document.getElementById('modalContent');

            modalServerName.textContent = `${server.name} - Capabilities`;

            let content = '';

            // Display Tools
            if (server.tools && server.tools.length > 0) {
                // Categorize tools
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
                                                const hasNestedSchema = (value.type === 'array' && value.items) || (value.type === 'object' && value.properties);
                                                
                                                return `
                                                <div style="background: white; padding: 8px; border-radius: 4px; margin-bottom: 4px; font-size: 12px;">
                                                    <span style="font-weight: 500; color: #000000;">${key}</span>
                                                    <span style="color: #929395; font-size: 11px;"> (${typeDisplay})</span>
                                                    ${isRequired ? '<span style="color: #FF5A26; font-size: 11px;"> *required</span>' : '<span style="color: #929395; font-size: 11px;"> optional</span>'}
                                                    ${value.description ? `<div style="color: #929395; margin-top: 2px; white-space: pre-wrap;">${escapeHtml(value.description)}</div>` : ''}
                                                    ${hasNestedSchema ? `<div style="margin-top: 4px; padding-left: 10px; border-left: 2px solid #E2E2E4; color: #929395; font-size: 11px; font-style: italic;">Complex nested structure - see tool documentation</div>` : ''}
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
                
                content += '<div style="margin-bottom: 30px;"><h3 style="color: #000000; border-bottom: 2px solid #4CD97A; padding-bottom: 8px; margin-bottom: 15px;"> Tools (' + server.tools.length + ')</h3>';
                content += renderToolSection(readOnlyTools, 'Read-Only Tools', '', '#33B6FF', '#E8F9FF', 'readonly');
                content += renderToolSection(destructiveTools, 'Destructive Tools', '', '#FF5A26', '#FFF0EC', 'destructive');
                content += renderToolSection(otherTools, 'General Tools', '', '#4CD97A', '#EDFFF3', 'general');
                content += '</div>';
            }

            // Display Prompts
            if (server.prompts && server.prompts.length > 0) {
                content += '<div><h3 style="color: #000000; border-bottom: 2px solid #33B6FF; padding-bottom: 8px; margin-bottom: 15px;"> Prompts (' + server.prompts.length + ')</h3>';
                server.prompts.forEach(prompt => {
                    // Clean search text: remove newlines, quotes, and extra spaces
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
                                            ${arg.description ? `<div style="color: #929395; margin-top: 2px; white-space: pre-wrap;">${escapeHtml(arg.description)}</div>` : ''}
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
                content = '<div style="text-align: center; padding: 40px; color: #929395;">No prompts or tools available. Please validate the connection first.</div>';
            }

            modalContent.innerHTML = content;
            modal.setAttribute('data-current-server-id', serverId);
            modal.style.display = 'block';
        }

        function closeMcpCapabilitiesModal() {
            document.getElementById('mcpCapabilitiesModal').style.display = 'none';
            // Clear search on close
            const searchInput = document.getElementById('capabilitiesSearch');
            if (searchInput) {
                searchInput.value = '';
            }
        }

        function filterCapabilities() {
            const searchInput = document.getElementById('capabilitiesSearch');
            const clearBtn = document.getElementById('clearSearchBtn');
            const searchTerm = searchInput.value.toLowerCase().trim();
            const items = document.querySelectorAll('.capability-item');
            
            // Show/hide clear button
            clearBtn.style.display = searchTerm ? 'block' : 'none';
            
            let visibleCount = 0;
            let visibleToolsCount = 0;
            let totalToolsCount = 0;
            let visiblePromptsCount = 0;
            let totalPromptsCount = 0;
            
            // Track subcategory counts
            const categoryTotals = {};
            const categoryVisible = {};
            
            items.forEach(item => {
                const searchData = item.getAttribute('data-search');
                const itemType = item.getAttribute('data-type');
                const category = item.getAttribute('data-category');
                const isTool = itemType === 'tool';
                
                // Count totals
                if (isTool) {
                    totalToolsCount++;
                    if (category) {
                        categoryTotals[category] = (categoryTotals[category] || 0) + 1;
                    }
                } else {
                    totalPromptsCount++;
                }
                
                // Filter and count visible
                if (!searchTerm || searchData.includes(searchTerm)) {
                    item.style.display = '';
                    visibleCount++;
                    if (isTool) {
                        visibleToolsCount++;
                        if (category) {
                            categoryVisible[category] = (categoryVisible[category] || 0) + 1;
                        }
                    } else {
                        visiblePromptsCount++;
                    }
                } else {
                    item.style.display = 'none';
                }
            });
            
            // Update section headers with counts
            if (searchTerm) {
                const toolsHeader = Array.from(document.querySelectorAll('h3')).find(h => h.textContent.includes(' Tools'));
                const promptsHeader = Array.from(document.querySelectorAll('h3')).find(h => h.textContent.includes(' Prompts'));
                
                if (toolsHeader && totalToolsCount > 0) {
                    toolsHeader.innerHTML = ` Tools (${visibleToolsCount} out of ${totalToolsCount})`;
                }
                if (promptsHeader && totalPromptsCount > 0) {
                    promptsHeader.innerHTML = ` Prompts (${visiblePromptsCount} out of ${totalPromptsCount})`;
                }
                
                // Update subcategory headers
                const subcategoryHeaders = document.querySelectorAll('.subcategory-header');
                subcategoryHeaders.forEach(header => {
                    const category = header.getAttribute('data-category');
                    const total = parseInt(header.getAttribute('data-total'));
                    const visible = categoryVisible[category] || 0;
                    const text = header.textContent;
                    const emoji = text.split(' ')[0];
                    const title = text.substring(text.indexOf(' ') + 1, text.lastIndexOf('(') - 1);
                    header.innerHTML = `${emoji} ${title} (${visible} out of ${total})`;
                });
            }
            
            // Show "no results" message if nothing matches
            const modalContent = document.getElementById('modalContent');
            let noResultsMsg = document.getElementById('noResultsMessage');
            
            if (visibleCount === 0 && searchTerm) {
                if (!noResultsMsg) {
                    noResultsMsg = document.createElement('div');
                    noResultsMsg.id = 'noResultsMessage';
                    noResultsMsg.style.cssText = 'text-align: center; padding: 40px; color: #929395; font-size: 14px;';
                    noResultsMsg.innerHTML = ' No matching tools or prompts found';
                    modalContent.appendChild(noResultsMsg);
                }
                noResultsMsg.style.display = 'block';
            } else if (noResultsMsg) {
                noResultsMsg.style.display = 'none';
            }
        }

        function clearCapabilitiesSearch() {
            const searchInput = document.getElementById('capabilitiesSearch');
            searchInput.value = '';
            
            // Restore original headers before filtering
            const items = document.querySelectorAll('.capability-item');
            let totalToolsCount = 0;
            let totalPromptsCount = 0;
            
            items.forEach(item => {
                const itemType = item.getAttribute('data-type');
                if (itemType === 'tool') {
                    totalToolsCount++;
                } else {
                    totalPromptsCount++;
                }
            });
            
            const toolsHeader = Array.from(document.querySelectorAll('h3')).find(h => h.textContent.includes(' Tools'));
            const promptsHeader = Array.from(document.querySelectorAll('h3')).find(h => h.textContent.includes(' Prompts'));
            
            if (toolsHeader && totalToolsCount > 0) {
                toolsHeader.innerHTML = ` Tools (${totalToolsCount})`;
            }
            if (promptsHeader && totalPromptsCount > 0) {
                promptsHeader.innerHTML = ` Prompts (${totalPromptsCount})`;
            }
            
            // Restore subcategory headers
            const subcategoryHeaders = document.querySelectorAll('.subcategory-header');
            subcategoryHeaders.forEach(header => {
                const total = parseInt(header.getAttribute('data-total'));
                const text = header.textContent;
                const emoji = text.split(' ')[0];
                const title = text.substring(text.indexOf(' ') + 1, text.lastIndexOf('(') - 1);
                header.innerHTML = `${emoji} ${title} (${total})`;
            });
            
            filterCapabilities();
            searchInput.focus();
        }

        // Close modal when clicking outside
        document.addEventListener('click', function(event) {
            const capabilitiesModal = document.getElementById('mcpCapabilitiesModal');
            
            if (event.target === capabilitiesModal) {
                closeMcpCapabilitiesModal();
            }
        });

        // Make all onclick functions globally accessible
        window.viewMcpCapabilities = viewMcpCapabilities;
        window.closeMcpCapabilitiesModal = closeMcpCapabilitiesModal;
        window.filterCapabilities = filterCapabilities;
        window.clearCapabilitiesSearch = clearCapabilitiesSearch;
        window.sendMessage = sendMessage;
        window.runScenario = runScenario;
        window.updateContextWindow = updateContextWindow;
        console.log('Script loaded successfully. sendMessage type:', typeof sendMessage);
