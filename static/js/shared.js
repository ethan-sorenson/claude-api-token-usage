/**
 * Shared JavaScript functions used by both main app and comparison pages.
 * 
 * Dependencies (must be defined by the page-specific JS):
 *   - mcpServers: Array of MCP server objects
 *   - showError(message, isError): Error display function
 *   - marked (optional): Markdown parser library
 */

// ── Navigation Menu ────────────────────────────────────────────────

function toggleNavMenu() {
    const drawer = document.getElementById('navDrawer');
    const overlay = document.getElementById('navOverlay');
    const trigger = document.getElementById('navMenuTrigger');
    const isOpen = drawer.classList.contains('open');

    if (isOpen) {
        drawer.classList.remove('open');
        overlay.classList.remove('visible');
        trigger.classList.remove('open');
    } else {
        drawer.classList.add('open');
        overlay.classList.add('visible');
        trigger.classList.add('open');
    }
}

// Close menu on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        const drawer = document.getElementById('navDrawer');
        if (drawer && drawer.classList.contains('open')) {
            toggleNavMenu();
        }
    }
});

// ── Markdown Preview ──────────────────────────────────────────────

let isMarkdownPreviewActive = false;

function toggleMarkdownPreview() {
    isMarkdownPreviewActive = !isMarkdownPreviewActive;
    const textarea = document.getElementById('userInput');
    const preview = document.getElementById('markdownPreview');
    const toggleBtn = document.querySelector('.markdown-toggle');

    if (isMarkdownPreviewActive) {
        textarea.style.display = 'none';
        preview.style.display = 'block';
        toggleBtn.classList.add('active');
        toggleBtn.textContent = '✏️ Edit';
        updateMarkdownPreview();
    } else {
        textarea.style.display = 'block';
        preview.style.display = 'none';
        toggleBtn.classList.remove('active');
        toggleBtn.textContent = '👁️ Preview';
    }
}

function updateMarkdownPreview() {
    if (!isMarkdownPreviewActive) return;

    const textarea = document.getElementById('userInput');
    const preview = document.getElementById('markdownPreview');
    const text = textarea.value;

    if (typeof marked !== 'undefined') {
        preview.innerHTML = marked.parse(text);
    } else {
        preview.innerHTML = text.replace(/\n/g, '<br>');
    }
}

// ── Utilities ─────────────────────────────────────────────────────

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function copyToClipboard(elementId) {
    const element = document.getElementById(elementId);
    const text = element.textContent;
    navigator.clipboard.writeText(text).then(() => {
        showError('✅ Copied to clipboard!', false);
    }).catch(err => {
        showError('Failed to copy to clipboard');
        console.error('Copy error:', err);
    });
}

function closeMessageDetailsModal() {
    document.getElementById('messageDetailsModal').style.display = 'none';
}

// ── MCP Prompts ───────────────────────────────────────────────────

function showMcpPromptsDialog() {
    const enabledServersWithPrompts = mcpServers.filter(s =>
        s.enabled && s.prompts && s.prompts.length > 0
    );

    if (enabledServersWithPrompts.length === 0) {
        showError('No prompts available. Please enable and test MCP connections first.');
        return;
    }

    const modal = document.createElement('div');
    modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 2000; display: flex; align-items: center; justify-content: center; padding: 20px;';

    const dialog = document.createElement('div');
    dialog.style.cssText = 'background: white; border-radius: 12px; padding: 0; width: 90%; max-width: 900px; height: 85vh; display: flex; flex-direction: column; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);';

    let html = '<div style="padding: 20px 24px; border-bottom: 2px solid #E2E2E4; display: flex; justify-content: space-between; align-items: center;">';
    html += '<h2 style="margin: 0; color: #000000; font-size: 24px;">📝 MCP Prompts</h2>';
    html += '<button onclick="document.body.removeChild(this.closest(\'[style*=fixed]\'))" style="padding: 8px 20px; background: #929395; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500; transition: background 0.2s;" onmouseover="this.style.background=\'#767676\'" onmouseout="this.style.background=\'#929395\'">✕ Close</button>';
    html += '</div>';

    html += '<div style="padding: 16px 24px; border-bottom: 1px solid #E2E2E4;">';
    html += '<input type="text" id="promptSearchInput" placeholder="🔍 Search prompts..." style="width: 100%; padding: 12px 16px; border: 2px solid #C7C9CA; border-radius: 8px; font-size: 14px; transition: border-color 0.2s;" onfocus="this.style.borderColor=\'#3533FF\'" onblur="this.style.borderColor=\'#C7C9CA\'" oninput="filterPrompts(this.value)">';
    html += '</div>';

    html += '<div id="promptsList" style="flex: 1; overflow-y: auto; padding: 16px 24px;">';

    enabledServersWithPrompts.forEach(server => {
        html += `<div class="server-prompts-section" style="margin-bottom: 24px;">`;
        html += `<h3 style="color: #3533FF; font-size: 16px; margin-bottom: 12px; display: flex; align-items: center; gap: 8px;">`;
        html += `<span>🔌</span> ${escapeHtml(server.name)} <span style="font-size: 12px; color: #929395; font-weight: 400;">(${server.prompts.length} prompts)</span>`;
        html += `</h3>`;

        server.prompts.forEach((prompt, idx) => {
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

    // Close the prompts dialog
    const modals = document.querySelectorAll('[style*="position: fixed"]');
    modals.forEach(modal => {
        if (modal.textContent.includes('MCP Prompts') || modal.querySelector('#promptsList')) {
            document.body.removeChild(modal);
        }
    });

    if (prompt.arguments && prompt.arguments.length > 0) {
        showPromptArgumentsDialog(server, prompt);
    } else {
        await usePrompt(serverId, prompt.name, {});
    }
}

function showPromptArgumentsDialog(server, prompt) {
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
        showError('🔄 Loading prompt...', false);

        const response = await fetch('/api/mcp/get-prompt', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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

        let promptText = '';

        if (result.messages && result.messages.length > 0) {
            result.messages.forEach(msg => {
                if (msg.role && msg.content) {
                    let msgText = '';
                    if (typeof msg.content === 'string') {
                        msgText = msg.content;
                    } else if (msg.content.type === 'text' && msg.content.text) {
                        msgText = msg.content.text;
                    } else if (Array.isArray(msg.content)) {
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
            promptText = result.description;
        } else if (typeof result === 'string') {
            promptText = result;
        }

        promptText = promptText.trim();

        if (!promptText) {
            console.error('Empty prompt content. Full result:', result);
            throw new Error('No prompt content returned. Check console for details.');
        }

        const userInput = document.getElementById('userInput');
        userInput.value = promptText;
        userInput.focus();

        const server = mcpServers.find(s => s.id === serverId);
        const prompt = server?.prompts?.find(p => p.name === promptName);
        const promptTitle = prompt?.title || prompt?.name || promptName;

        showError(`✅ Prompt "${promptTitle}" loaded`, false);

    } catch (error) {
        showError(`Error loading prompt: ${error.message}`);
        console.error('Load prompt error:', error);
    }
}
