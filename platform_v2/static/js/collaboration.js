/**
 * Collaboration Engine - Client-side JavaScript
 * Handles dual-AI chat modes, terminal integration, and collaboration controls
 */

// Global state
let currentChatMode = 'solo';  // 'solo', 'side-by-side', 'collab'
let collabSession = null;
let collabPollInterval = null;  // kept for fallback
let collabEventSource = null;   // SSE connection
let terminal = null;
let terminalFitAddon = null;

// Mode switching
function switchChatMode(mode) {
    currentChatMode = mode;

    // Update tab buttons
    document.querySelectorAll('.chat-mode-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Show/hide containers
    document.getElementById('solo-chat-container').style.display = mode === 'solo' ? 'flex' : 'none';
    document.getElementById('dual-chat-container').style.display = mode === 'side-by-side' ? 'flex' : 'none';
    document.getElementById('collab-container').style.display = mode === 'collab' ? 'flex' : 'none';
    var codeContainer = document.getElementById('code-container');
    if (codeContainer) codeContainer.style.display = mode === 'code' ? 'flex' : 'none';

    // Load collab state if switching to collab mode
    if (mode === 'collab') {
        loadCollabLearnings();
        // Pre-load history if sidebar is open
        if (historyVisible) {
            loadCollabHistory();
        }
    }

    // Initialize terminal iframe when switching to side-by-side
    if (mode === 'side-by-side') {
        initClaudeTerminalIframe();
    }
}

// Terminal initialization using xterm.js
function initTerminal() {
    const container = document.getElementById('claude-terminal');
    if (!container) return;

    // Check if xterm is loaded
    if (typeof Terminal === 'undefined') {
        const errorDiv = document.createElement('div');
        errorDiv.style.cssText = 'padding: 1rem; color: #ff4444;';
        errorDiv.textContent = 'xterm.js not loaded. Terminal unavailable.';
        container.appendChild(errorDiv);
        return;
    }

    terminal = new Terminal({
        cursorBlink: true,
        fontSize: 14,
        fontFamily: 'JetBrains Mono, Consolas, monospace',
        theme: {
            background: '#1a1a2e',
            foreground: '#00ff41',
            cursor: '#00ff41',
            selection: 'rgba(0, 255, 65, 0.3)'
        }
    });

    // Fit addon for responsive sizing
    if (typeof FitAddon !== 'undefined') {
        terminalFitAddon = new FitAddon.FitAddon();
        terminal.loadAddon(terminalFitAddon);
    }

    terminal.open(container);

    if (terminalFitAddon) {
        terminalFitAddon.fit();
    }

    // Connect to ttyd via WebSocket
    connectToTtyd();

    // Handle resize
    window.addEventListener('resize', () => {
        if (terminalFitAddon) {
            terminalFitAddon.fit();
        }
    });
}

function connectToTtyd() {
    const ttydHost = window.location.hostname;
    const ttydPort = 7681;
    const wsUrl = 'ws://' + ttydHost + ':' + ttydPort + '/ws';

    terminal.writeln('Connecting to Claude CLI...');

    try {
        const ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            terminal.writeln('\x1b[32mConnected!\x1b[0m');
            terminal.writeln('');
            updateClaudeStatus(true);
        };

        ws.onmessage = (event) => {
            terminal.write(event.data);
        };

        ws.onclose = () => {
            terminal.writeln('\x1b[31mDisconnected from Claude CLI\x1b[0m');
            updateClaudeStatus(false);
        };

        ws.onerror = (error) => {
            terminal.writeln('\x1b[31mConnection error. Is ttyd running?\x1b[0m');
            terminal.writeln('Start with: sudo systemctl start ttyd-claude');
            updateClaudeStatus(false);
        };

        // Send terminal input to WebSocket
        terminal.onData(data => {
            ws.send(data);
        });

    } catch (e) {
        terminal.writeln('\x1b[31mFailed to connect to terminal\x1b[0m');
        console.error('WebSocket error:', e);
        updateClaudeStatus(false);
    }
}

function updateClaudeStatus(online) {
    const dots = document.querySelectorAll('.claude-panel .status-dot');
    dots.forEach(function(dot) {
        dot.classList.toggle('offline', !online);
    });
}

async function openClaudeTerminal() {
    const host = window.location.hostname;
    let url = 'http://' + host + ':7681';

    // Try to get SSO token
    try {
        const response = await fetch('/tools/consciousness/api/terminal/token', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await response.json();
        if (data.success && data.token) {
            url += '/?token=' + encodeURIComponent(data.token);
        }
    } catch (e) {
        console.debug('Token fetch failed, falling back to Basic Auth:', e.message);
    }

    window.open(url, 'claude-terminal', 'width=900,height=600,menubar=no,toolbar=no');
}

async function openCodexTerminal() {
    // Sandboxed Codex web terminal — same one-time-token SSO as the Claude terminal
    // (shared terminal_auth_tokens), fronted by the admin auth proxy on :7683.
    const host = window.location.hostname;
    let url = 'http://' + host + ':7683';
    try {
        const response = await fetch('/tools/consciousness/api/terminal/token', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await response.json();
        if (data.success && data.token) {
            url += '/?token=' + encodeURIComponent(data.token);
        }
    } catch (e) {
        console.debug('Token fetch failed, falling back to Basic Auth:', e.message);
    }
    window.open(url, 'codex-terminal', 'width=900,height=600,menubar=no,toolbar=no');
}

// Collaboration Functions
async function startCollaboration() {
    const topicInput = document.getElementById('collab-topic');
    const maxTurnsInput = document.getElementById('collab-max-turns');

    const topic = topicInput.value.trim();
    if (!topic) {
        alert('Please enter a topic for discussion');
        return;
    }

    const maxTurns = parseInt(maxTurnsInput.value) || 10;

    try {
        const response = await fetch('/tools/consciousness/api/collab/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic, max_turns: maxTurns })
        });

        const data = await response.json();

        if (data.success) {
            renderedMessageCount = 0;
            collabSession = {
                id: data.session_id,
                status: data.status,
                topic: topic,
                messages: []
            };

            // Switch to active view
            document.getElementById('collab-start-view').style.display = 'none';
            document.getElementById('collab-active-view').style.display = 'flex';

            // Start SSE stream (with polling fallback)
            startCollabStream();

            showNotification('Collaboration started!', 'success');
        } else {
            showNotification(data.error || 'Failed to start collaboration', 'error');
        }
    } catch (e) {
        console.error('Start collab error:', e);
        showNotification('Failed to start collaboration', 'error');
    }
}

function startCollabStream() {
    if (!collabSession) return;

    // Close existing SSE connection
    if (collabEventSource) {
        collabEventSource.close();
        collabEventSource = null;
    }

    // Try SSE first
    if (typeof EventSource !== 'undefined') {
        try {
            collabEventSource = new EventSource('/tools/consciousness/api/collab/stream/' + collabSession.id);

            collabEventSource.onmessage = function(event) {
                try {
                    var data = JSON.parse(event.data);
                    handleCollabSSEMessage(data);
                } catch (e) {
                    console.error('SSE parse error:', e);
                }
            };

            collabEventSource.onerror = function() {
                console.warn('SSE connection lost, falling back to polling');
                collabEventSource.close();
                collabEventSource = null;
                startCollabPoll();
            };

            return;
        } catch (e) {
            console.warn('SSE not available, using polling:', e);
        }
    }

    // Fallback: polling
    startCollabPoll();
}

function handleCollabSSEMessage(data) {
    if (!collabSession) return;

    if (data.type === 'message') {
        collabSession.messages.push(data);
        renderCollabMessage(data);
    } else if (data.type === 'status') {
        collabSession.status = data.status;
        updateCollabStatusUI(data.status, data.turn, data.max_turns);
    } else if (data.type === 'done') {
        collabSession.status = data.status;
        updateCollabStatusUI(data.status, 0, 0);
        if (collabEventSource) {
            collabEventSource.close();
            collabEventSource = null;
        }
        // Show export buttons when done
        var exportBtns = document.getElementById('collab-export-btns');
        if (exportBtns) exportBtns.style.display = 'flex';
        loadCollabLearnings();
    } else if (data.type === 'close') {
        if (collabEventSource) {
            collabEventSource.close();
            collabEventSource = null;
        }
    }
}

function renderCollabMessage(msg) {
    var messagesContainer = document.getElementById('collab-messages');

    // Remove old thinking indicator
    var oldThinking = messagesContainer.querySelector('.thinking-indicator');
    if (oldThinking) oldThinking.remove();

    var msgEl = document.createElement('div');
    msgEl.className = 'collab-message ' + msg.role;

    var roleLabel = msg.role === 'archie' ? 'A.R.C.H.I.E.' :
                   msg.role === 'claude' ? 'Claude' : 'You';
    var roleIcon = msg.role === 'archie' ? '\u{1F9E0}' :
                  msg.role === 'claude' ? '\u{1F916}' : '\u{1F464}';

    var roleEl = document.createElement('div');
    roleEl.className = 'role';
    roleEl.textContent = roleIcon + ' ' + roleLabel;
    msgEl.appendChild(roleEl);

    var contentEl = document.createElement('div');
    contentEl.className = 'content';
    // Content from our own AI backend, escaped via renderMarkdownSafe before markdown
    contentEl.textContent = msg.content;
    msgEl.appendChild(contentEl);

    var tsEl = document.createElement('div');
    tsEl.className = 'timestamp';
    tsEl.textContent = 'Turn ' + msg.turn;
    msgEl.appendChild(tsEl);

    messagesContainer.appendChild(msgEl);
    renderedMessageCount++;

    // Add thinking indicator if session is still active
    if (collabSession && collabSession.status === 'active') {
        var waitingFor = msg.role === 'archie' ? '\u{1F916} Claude is thinking' :
                        msg.role === 'claude' ? '\u{1F9E0} A.R.C.H.I.E. is thinking' :
                        'AIs are collaborating';
        var thinkingEl = document.createElement('div');
        thinkingEl.className = 'thinking-indicator';
        var dotsEl = document.createElement('div');
        dotsEl.className = 'dots';
        for (var j = 0; j < 3; j++) {
            var dot = document.createElement('div');
            dot.className = 'dot';
            dotsEl.appendChild(dot);
        }
        thinkingEl.appendChild(dotsEl);
        var textEl = document.createElement('span');
        textEl.textContent = waitingFor + '...';
        thinkingEl.appendChild(textEl);
        messagesContainer.appendChild(thinkingEl);
    }

    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function updateCollabStatusUI(status, turn, maxTurns) {
    if (turn > 0 && maxTurns > 0) {
        document.getElementById('turn-counter').textContent = 'Turn ' + turn + '/' + maxTurns;
    }

    var statusDot = document.querySelector('.collab-status-dot');
    var statusText = document.querySelector('.collab-status-text');
    if (statusDot) statusDot.className = 'status-dot collab-status-dot ' + status;
    if (statusText) statusText.textContent = status.charAt(0).toUpperCase() + status.slice(1);

    var btnPause = document.getElementById('btn-pause');
    var btnResume = document.getElementById('btn-resume');
    var btnStop = document.getElementById('btn-stop');
    var btnInterject = document.getElementById('btn-interject');
    if (btnPause) btnPause.style.display = status === 'active' ? 'inline-block' : 'none';
    if (btnResume) btnResume.style.display = status === 'paused' ? 'inline-block' : 'none';
    if (btnStop) btnStop.style.display = ['active', 'paused'].includes(status) ? 'inline-block' : 'none';
    if (btnInterject) btnInterject.style.display = ['active', 'paused'].includes(status) ? 'inline-block' : 'none';
}

// Polling fallback (used when SSE is unavailable)
function startCollabPoll() {
    if (collabPollInterval) {
        clearInterval(collabPollInterval);
    }
    collabPollInterval = setInterval(pollCollabStatus, 2000);
    pollCollabStatus();
}

async function pollCollabStatus() {
    if (!collabSession) return;

    try {
        var response = await fetch('/tools/consciousness/api/collab/status/' + collabSession.id);
        var data = await response.json();

        if (data.success) {
            var session = data.session;
            collabSession.status = session.status;
            collabSession.messages = session.messages;
            updateCollabUI(session);

            if (['completed', 'stopped', 'error'].includes(session.status)) {
                clearInterval(collabPollInterval);
                collabPollInterval = null;
                loadCollabLearnings();
            }
        }
    } catch (e) {
        console.error('Poll error:', e);
    }
}

// Track rendered message count to avoid re-rendering everything
let renderedMessageCount = 0;

function renderMarkdownSafe(text) {
    // Escape HTML entities first for safety, then apply markdown transforms.
    // Since content comes from our own AI backend (not user input), the
    // initial escaping is defense-in-depth.
    var safe = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    // Apply simple markdown: bold, italic, inline code, line breaks
    safe = safe
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code>$1</code>')
        .replace(/\n/g, '<br>');
    return safe;
}

function updateCollabUI(session) {
    var messagesContainer = document.getElementById('collab-messages');

    // Remove old thinking indicator if present
    var oldThinking = messagesContainer.querySelector('.thinking-indicator');
    if (oldThinking) oldThinking.remove();

    // Only render NEW messages (avoids flash/flicker on poll)
    var messages = session.messages;
    for (var i = renderedMessageCount; i < messages.length; i++) {
        var msg = messages[i];
        var msgEl = document.createElement('div');
        msgEl.className = 'collab-message ' + msg.role;

        var roleLabel = msg.role === 'archie' ? 'A.R.C.H.I.E.' :
                       msg.role === 'claude' ? 'Claude' : 'You';
        var roleIcon = msg.role === 'archie' ? '\u{1F9E0}' :
                      msg.role === 'claude' ? '\u{1F916}' : '\u{1F464}';

        var roleEl = document.createElement('div');
        roleEl.className = 'role';
        roleEl.textContent = roleIcon + ' ' + roleLabel;
        msgEl.appendChild(roleEl);

        var contentEl = document.createElement('div');
        contentEl.className = 'content';
        // Content is from our own AI backend, escaped before markdown transform
        contentEl.innerHTML = renderMarkdownSafe(msg.content);  // nosemgrep: innerHTML-safe-escaped
        msgEl.appendChild(contentEl);

        var tsEl = document.createElement('div');
        tsEl.className = 'timestamp';
        tsEl.textContent = 'Turn ' + msg.turn;
        msgEl.appendChild(tsEl);

        messagesContainer.appendChild(msgEl);
    }
    renderedMessageCount = messages.length;

    // Add thinking indicator if active - show whose turn it is
    if (session.status === 'active') {
        var lastMsg = messages[messages.length - 1];
        var waitingFor = 'AIs are collaborating';
        if (lastMsg) {
            if (lastMsg.role === 'user' || lastMsg.role === 'claude') {
                waitingFor = '\u{1F9E0} A.R.C.H.I.E. is thinking';
            } else if (lastMsg.role === 'archie') {
                waitingFor = '\u{1F916} Claude is thinking';
            }
        }

        var thinkingEl = document.createElement('div');
        thinkingEl.className = 'thinking-indicator';

        var dotsEl = document.createElement('div');
        dotsEl.className = 'dots';
        for (var j = 0; j < 3; j++) {
            var dot = document.createElement('div');
            dot.className = 'dot';
            dotsEl.appendChild(dot);
        }
        thinkingEl.appendChild(dotsEl);

        var textEl = document.createElement('span');
        textEl.textContent = waitingFor + '...';
        thinkingEl.appendChild(textEl);

        messagesContainer.appendChild(thinkingEl);
    }

    // Auto-scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    // Update turn counter
    document.getElementById('turn-counter').textContent =
        'Turn ' + session.current_turn + '/' + session.max_turns;

    // Update status
    var statusDot = document.querySelector('.collab-status-dot');
    var statusText = document.querySelector('.collab-status-text');

    statusDot.className = 'status-dot collab-status-dot ' + session.status;
    statusText.textContent = session.status.charAt(0).toUpperCase() + session.status.slice(1);

    // Update buttons
    document.getElementById('btn-pause').style.display =
        session.status === 'active' ? 'inline-block' : 'none';
    document.getElementById('btn-resume').style.display =
        session.status === 'paused' ? 'inline-block' : 'none';
    document.getElementById('btn-stop').style.display =
        ['active', 'paused'].includes(session.status) ? 'inline-block' : 'none';
    document.getElementById('btn-interject').style.display =
        ['active', 'paused'].includes(session.status) ? 'inline-block' : 'none';
}

async function pauseCollaboration() {
    if (!collabSession) return;

    try {
        await fetch('/tools/consciousness/api/collab/pause/' + collabSession.id, {
            method: 'POST'
        });
        showNotification('Collaboration paused', 'info');
    } catch (e) {
        console.error('Pause error:', e);
    }
}

async function resumeCollaboration() {
    if (!collabSession) return;

    try {
        await fetch('/tools/consciousness/api/collab/resume/' + collabSession.id, {
            method: 'POST'
        });
        showNotification('Collaboration resumed', 'info');
    } catch (e) {
        console.error('Resume error:', e);
    }
}

async function stopCollaboration() {
    if (!collabSession) return;

    if (!confirm('Stop the collaboration?')) return;

    try {
        await fetch('/tools/consciousness/api/collab/stop/' + collabSession.id, {
            method: 'POST'
        });
        showNotification('Collaboration stopped', 'info');
    } catch (e) {
        console.error('Stop error:', e);
    }
}

function showInterjectionModal() {
    document.getElementById('interjection-modal').classList.add('visible');
    var textEl = document.getElementById('interjection-text');
    textEl.focus();
    // Phase 9: Ctrl+Enter to send interjection
    textEl.onkeydown = function(e) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            submitInterjection();
        }
    };
}

function hideInterjectionModal() {
    document.getElementById('interjection-modal').classList.remove('visible');
    document.getElementById('interjection-text').value = '';
}

async function submitInterjection() {
    if (!collabSession) return;

    const text = document.getElementById('interjection-text').value.trim();
    if (!text) return;

    try {
        await fetch('/tools/consciousness/api/collab/interject/' + collabSession.id, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        });

        hideInterjectionModal();
        showNotification('Message added to conversation', 'success');
    } catch (e) {
        console.error('Interjection error:', e);
    }
}

function newCollaboration() {
    // Reset to start view
    collabSession = null;
    renderedMessageCount = 0;
    if (collabPollInterval) {
        clearInterval(collabPollInterval);
        collabPollInterval = null;
    }
    if (collabEventSource) {
        collabEventSource.close();
        collabEventSource = null;
    }

    document.getElementById('collab-start-view').style.display = 'flex';
    document.getElementById('collab-active-view').style.display = 'none';
    document.getElementById('collab-topic').value = '';
    document.getElementById('collab-messages').textContent = '';
}

async function loadCollabLearnings() {
    try {
        const response = await fetch('/tools/consciousness/api/collab/learnings');
        const data = await response.json();

        if (data.success) {
            document.getElementById('learning-total').textContent = data.total_learnings || 0;
            document.getElementById('learning-week').textContent = data.learnings_last_week || 0;

            const topicsEl = document.getElementById('learning-topics');
            if (data.top_topics && data.top_topics.length > 0) {
                topicsEl.textContent = data.top_topics.slice(0, 3).join(', ');
            } else {
                topicsEl.textContent = 'None yet';
            }
        }
    } catch (e) {
        console.error('Load learnings error:', e);
    }
}

async function checkClaudeStatus() {
    try {
        const response = await fetch('/tools/consciousness/api/claude/status');
        const data = await response.json();

        if (data.success) {
            const claudeOk = data.claude && data.claude.status === 'healthy';
            const ttydOk = data.ttyd && data.ttyd.status === 'running';

            // Update status indicators
            const statusEl = document.getElementById('claude-cli-status');
            if (statusEl) {
                statusEl.textContent = '';
                const dot = document.createElement('span');
                dot.className = claudeOk && ttydOk ? 'status-dot' : 'status-dot offline';
                statusEl.appendChild(dot);
                const text = document.createTextNode(claudeOk && ttydOk ? ' Ready' : ' Offline');
                statusEl.appendChild(text);
            }
        }
    } catch (e) {
        console.error('Status check error:', e);
    }
}

// Utility functions
function showNotification(message, type) {
    type = type || 'info';
    // Use existing notification system if available
    if (typeof showFlashMessage === 'function') {
        showFlashMessage(message, type);
    } else {
        console.log('[' + type + '] ' + message);
    }
}

// Panel resize functionality
let isResizing = false;
let resizeHandle = null;

function initResizeHandle() {
    resizeHandle = document.querySelector('.resize-handle');
    if (!resizeHandle) return;

    resizeHandle.addEventListener('mousedown', startResize);
    document.addEventListener('mousemove', doResize);
    document.addEventListener('mouseup', stopResize);
}

function startResize(e) {
    isResizing = true;
    resizeHandle.style.background = 'var(--accent-primary, #00ff41)';
}

function doResize(e) {
    if (!isResizing) return;

    const container = document.getElementById('dual-chat-container');
    const leftPanel = container.querySelector('.chat-panel:first-child');
    const containerRect = container.getBoundingClientRect();

    const newWidth = e.clientX - containerRect.left;
    const percentage = (newWidth / containerRect.width) * 100;

    if (percentage > 20 && percentage < 80) {
        leftPanel.style.flex = '0 0 ' + percentage + '%';
    }
}

function stopResize() {
    isResizing = false;
    if (resizeHandle) {
        resizeHandle.style.background = '';
    }
}

// Claude Code terminal iframe management
let claudeTerminalLoaded = false;

async function initClaudeTerminalIframe() {
    if (claudeTerminalLoaded) return;

    var iframe = document.getElementById('claude-terminal-iframe');
    var offline = document.getElementById('claude-terminal-offline');
    if (!iframe) return;

    var host = window.location.hostname;
    var ttydUrl = 'http://' + host + ':7681';

    // Try to get SSO token
    try {
        const response = await fetch('/tools/consciousness/api/terminal/token', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {'Content-Type': 'application/json'}
        });
        const data = await response.json();
        if (data.success && data.token) {
            ttydUrl += '/?token=' + encodeURIComponent(data.token);
        }
    } catch (e) {
        console.debug('Token fetch failed, falling back to Basic Auth:', e.message);
    }

    iframe.src = ttydUrl;
    claudeTerminalLoaded = true;

    iframe.onload = function() {
        if (offline) offline.style.display = 'none';
    };
    iframe.onerror = function() {
        if (offline) offline.style.display = 'flex';
    };

    // Check if ttyd is reachable after a short delay
    // Note: cross-origin iframes (different port) won't have contentDocument,
    // so we only check contentWindow which is always available for loaded iframes
    setTimeout(function() {
        if (!iframe.contentWindow) {
            if (offline) offline.style.display = 'flex';
        }
    }, 5000);
}

function reconnectClaudeTerminal() {
    claudeTerminalLoaded = false;
    var iframe = document.getElementById('claude-terminal-iframe');
    if (iframe) iframe.src = '';
    initClaudeTerminalIframe();
}

async function syncContextToClaude() {
    // Gather ARCHIE's recent conversation context and send to Claude proxy
    try {
        var messages = document.querySelectorAll('#archie-side-messages .chat-message');
        var context = [];
        messages.forEach(function(msg) {
            var role = msg.querySelector('.role');
            var content = msg.querySelector('.content');
            if (role && content) {
                context.push(role.textContent + ': ' + content.textContent);
            }
        });

        if (context.length === 0) {
            showNotification('No conversation context to sync', 'info');
            return;
        }

        var summary = context.slice(-6).join('\n');

        var response = await fetch('/tools/consciousness/api/claude/sync-context', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ context: summary })
        });
        var data = await response.json();
        if (data.success) {
            showNotification('Context synced to Claude', 'success');
        } else {
            showNotification('Sync failed: ' + (data.error || 'Unknown'), 'error');
        }
    } catch (e) {
        showNotification('Context sync error: ' + e.message, 'error');
    }
}

// =========================================================================
// Joint Work Mode & Work Products
// =========================================================================

let currentCollabMode = 'discuss'; // 'discuss' or 'joint'
let workProductsPollInterval = null;

function setCollabMode(mode) {
    currentCollabMode = mode;
    var discussBtn = document.getElementById('collab-mode-discuss');
    var jointBtn = document.getElementById('collab-mode-joint');
    var startBtn = document.getElementById('btn-start-collab');

    if (discussBtn) {
        discussBtn.classList.toggle('active', mode === 'discuss');
    }
    if (jointBtn) {
        jointBtn.classList.toggle('active', mode === 'joint');
    }
    if (startBtn) {
        startBtn.textContent = mode === 'joint' ? 'Start Joint Work' : 'Start Collaboration';
    }
}

// Override startCollaboration to support both modes
var _originalStartCollaboration = startCollaboration;
startCollaboration = async function() {
    if (currentCollabMode === 'joint') {
        await startJointCollaboration();
    } else {
        await _originalStartCollaboration();
    }
};

async function startJointCollaboration() {
    var topicInput = document.getElementById('collab-topic');
    var maxTurnsInput = document.getElementById('collab-max-turns');

    var topic = topicInput.value.trim();
    if (!topic) {
        alert('Please enter a topic for joint work');
        return;
    }

    var maxTurns = parseInt(maxTurnsInput.value) || 10;

    try {
        var response = await fetch('/tools/consciousness/api/collab/joint/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic: topic, max_turns: maxTurns })
        });

        var data = await response.json();

        if (data.success) {
            renderedMessageCount = 0;
            collabSession = {
                id: data.session_id,
                status: data.status,
                topic: topic,
                messages: [],
                isJoint: true
            };

            // Switch to active view
            document.getElementById('collab-start-view').style.display = 'none';
            document.getElementById('collab-active-view').style.display = 'flex';

            // Update title for joint mode
            var titleEl = document.getElementById('collab-active-title');
            if (titleEl) titleEl.textContent = 'Joint Work in Progress';

            // Show work products panel and toggle button
            var toggleBtn = document.getElementById('btn-toggle-products');
            if (toggleBtn) toggleBtn.style.display = 'inline-block';
            showWorkProducts();

            // Start SSE stream
            startCollabStream();

            // Poll for work products
            startWorkProductsPoll();

            showNotification('Joint collaboration started!', 'success');
        } else {
            showNotification(data.error || 'Failed to start joint work', 'error');
        }
    } catch (e) {
        console.error('Start joint collab error:', e);
        showNotification('Failed to start joint collaboration', 'error');
    }
}

function showWorkProducts() {
    var panel = document.getElementById('work-products-panel');
    if (panel) panel.style.display = 'flex';
}

function hideWorkProducts() {
    var panel = document.getElementById('work-products-panel');
    if (panel) panel.style.display = 'none';
}

function toggleWorkProducts() {
    var panel = document.getElementById('work-products-panel');
    if (!panel) return;
    if (panel.style.display === 'none' || panel.style.display === '') {
        showWorkProducts();
    } else {
        hideWorkProducts();
    }
}

function startWorkProductsPoll() {
    if (workProductsPollInterval) {
        clearInterval(workProductsPollInterval);
    }
    workProductsPollInterval = setInterval(loadWorkProducts, 5000);
    // Load immediately too
    loadWorkProducts();
}

function stopWorkProductsPoll() {
    if (workProductsPollInterval) {
        clearInterval(workProductsPollInterval);
        workProductsPollInterval = null;
    }
}

async function loadWorkProducts() {
    if (!collabSession || !collabSession.id) return;

    try {
        var response = await fetch('/tools/consciousness/api/collab/work-products/' + collabSession.id);
        var data = await response.json();

        if (data.success) {
            renderWorkProducts(data.products || []);
        }
    } catch (e) {
        console.error('Load work products error:', e);
    }
}

function renderWorkProducts(products) {
    var container = document.getElementById('work-products-list');
    var countEl = document.getElementById('wp-count');
    if (!container) return;

    if (countEl) countEl.textContent = products.length;

    // Clear and rebuild
    container.textContent = '';

    if (products.length === 0) {
        var emptyEl = document.createElement('div');
        emptyEl.style.cssText = 'padding: 1rem; text-align: center; color: var(--archie-text-muted); font-size: 0.8rem;';
        emptyEl.textContent = 'Work products will appear here as the collaboration progresses...';
        container.appendChild(emptyEl);
        return;
    }

    products.forEach(function(product) {
        var card = document.createElement('div');
        card.className = 'work-product-card';
        card.dataset.productId = product.id;

        // Type badge
        var typeBadge = document.createElement('span');
        typeBadge.className = 'wp-type ' + (product.product_type || 'analysis');
        typeBadge.textContent = product.product_type || 'analysis';
        card.appendChild(typeBadge);

        // Author
        var authorEl = document.createElement('span');
        authorEl.className = 'wp-author';
        authorEl.textContent = ' by ' + (product.author || 'unknown');
        authorEl.style.marginLeft = '0.3rem';
        card.appendChild(authorEl);

        // Title
        var titleEl = document.createElement('div');
        titleEl.className = 'wp-title';
        titleEl.textContent = product.title || 'Untitled';
        card.appendChild(titleEl);

        // Content preview (truncated)
        var contentEl = document.createElement('div');
        contentEl.className = 'wp-content-preview';
        var contentText = product.content || '';
        contentEl.textContent = contentText.length > 300 ? contentText.substring(0, 300) + '...' : contentText;
        card.appendChild(contentEl);

        // Click to expand
        contentEl.addEventListener('click', function() {
            card.classList.toggle('expanded');
            if (card.classList.contains('expanded')) {
                contentEl.textContent = contentText;
            } else {
                contentEl.textContent = contentText.length > 300 ? contentText.substring(0, 300) + '...' : contentText;
            }
        });

        // Actions
        var actionsEl = document.createElement('div');
        actionsEl.className = 'wp-actions';

        if (product.approved) {
            var approvedBtn = document.createElement('button');
            approvedBtn.className = 'approved';
            approvedBtn.textContent = 'Approved';
            actionsEl.appendChild(approvedBtn);
        } else {
            var approveBtn = document.createElement('button');
            approveBtn.textContent = 'Approve';
            approveBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                approveWorkProduct(product.id);
            });
            actionsEl.appendChild(approveBtn);
        }

        // Save to KB button
        var saveKbBtn = document.createElement('button');
        saveKbBtn.className = 'wp-save-kb-btn';
        saveKbBtn.textContent = 'Save to KB';
        saveKbBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            saveWorkProductToKB(product.id);
        });
        actionsEl.appendChild(saveKbBtn);

        if (product.version && product.version > 1) {
            var verEl = document.createElement('span');
            verEl.style.cssText = 'font-size: 0.65rem; color: var(--archie-text-muted); padding: 0.2rem 0.4rem;';
            verEl.textContent = 'v' + product.version;
            actionsEl.appendChild(verEl);
        }

        card.appendChild(actionsEl);
        container.appendChild(card);
    });
}

async function approveWorkProduct(productId) {
    try {
        var response = await fetch('/tools/consciousness/api/collab/work-products/' + productId + '/approve', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        var data = await response.json();

        if (data.success) {
            showNotification('Work product approved', 'success');
            loadWorkProducts(); // Refresh
        } else {
            showNotification('Approval failed', 'error');
        }
    } catch (e) {
        showNotification('Approval error: ' + e.message, 'error');
    }
}

// Override newCollaboration to clean up joint mode state + template state
var _originalNewCollaboration = newCollaboration;
newCollaboration = function() {
    stopWorkProductsPoll();
    hideWorkProducts();

    var titleEl = document.getElementById('collab-active-title');
    if (titleEl) titleEl.textContent = 'Collaboration in Progress';

    var toggleBtn = document.getElementById('btn-toggle-products');
    if (toggleBtn) toggleBtn.style.display = 'none';

    var wpList = document.getElementById('work-products-list');
    if (wpList) wpList.textContent = '';

    // Reset template selection
    selectedTemplate = null;
    document.querySelectorAll('.template-card').forEach(function(c) {
        c.classList.remove('selected');
    });

    // Reset read-only mode
    collabReadOnly = false;
    var banner = document.getElementById('collab-readonly-banner');
    if (banner) banner.style.display = 'none';

    _originalNewCollaboration();
};

// =========================================================================
// Voice Controller — STT (Web Speech API) + Auto-TTS
// =========================================================================

var voiceListening = false;
var speechRecognition = null;
var silenceTimer = null;
var SILENCE_TIMEOUT = 8000; // 8 seconds of silence before auto-send

function toggleVoiceInput() {
    if (voiceListening) {
        stopVoiceInput();
    } else {
        startVoiceInput();
    }
}

function startVoiceInput() {
    // Check browser support
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        showNotification('Speech recognition not supported in this browser', 'error');
        return;
    }

    speechRecognition = new SpeechRecognition();
    speechRecognition.continuous = true;
    speechRecognition.interimResults = true;
    speechRecognition.lang = 'en-US';

    var statusEl = document.getElementById('voice-status');
    var statusText = document.getElementById('voice-status-text');
    var inputEl = document.getElementById('archie-chat-input');
    var waveformEl = document.getElementById('voice-waveform');

    // Create waveform bars
    if (waveformEl) {
        waveformEl.textContent = '';
        for (var i = 0; i < 5; i++) {
            var bar = document.createElement('div');
            bar.className = 'bar';
            waveformEl.appendChild(bar);
        }
    }

    speechRecognition.onstart = function() {
        voiceListening = true;
        updateMicButton(true);
        if (statusEl) statusEl.style.display = 'flex';
        if (statusText) statusText.textContent = 'Listening...';
        if (inputEl) inputEl.placeholder = 'Listening... (click Mic or press Escape to stop)';
    };

    speechRecognition.onresult = function(event) {
        // Clear existing silence timer on new speech
        clearTimeout(silenceTimer);

        var transcript = '';
        for (var i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
        }

        // Show interim text in input
        if (inputEl) inputEl.value = transcript;
        if (statusText) statusText.textContent = 'Listening...';

        // Reset silence timer — auto-send after SILENCE_TIMEOUT ms of silence
        silenceTimer = setTimeout(function() {
            if (inputEl && inputEl.value.trim()) {
                sendArchieMessage();
                // Clear input for next utterance but keep listening
                if (inputEl) inputEl.value = '';
            }
        }, SILENCE_TIMEOUT);
    };

    speechRecognition.onerror = function(event) {
        console.error('Speech recognition error:', event.error);
        if (event.error !== 'no-speech' && event.error !== 'aborted') {
            showNotification('Voice input error: ' + event.error, 'error');
            stopVoiceInput();
        }
    };

    speechRecognition.onend = function() {
        // Auto-restart for continuous mode (unless user explicitly stopped)
        if (voiceListening) {
            try {
                speechRecognition.start();
            } catch (e) {
                // Browser may block rapid restarts
                stopVoiceInput();
            }
        }
    };

    try {
        speechRecognition.start();
    } catch (e) {
        showNotification('Could not start voice input: ' + e.message, 'error');
    }

    // Listen for Escape key to stop
    document.addEventListener('keydown', _voiceEscapeHandler);
}

function _voiceEscapeHandler(e) {
    if (e.key === 'Escape' && voiceListening) {
        stopVoiceInput();
    }
}

function stopVoiceInput() {
    voiceListening = false;
    clearTimeout(silenceTimer);
    if (speechRecognition) {
        try { speechRecognition.abort(); } catch(e) {}
        speechRecognition = null;
    }

    updateMicButton(false);

    var statusEl = document.getElementById('voice-status');
    var inputEl = document.getElementById('archie-chat-input');
    if (statusEl) statusEl.style.display = 'none';
    if (inputEl) inputEl.placeholder = 'Talk to A.R.C.H.I.E....';

    document.removeEventListener('keydown', _voiceEscapeHandler);
}

function updateMicButton(active) {
    var btn = document.getElementById('voice-input-btn');
    if (btn) {
        btn.classList.toggle('listening', active);
        btn.title = active ? 'Stop listening (click or press Escape)' : 'Start voice input';
    }
}

async function speakResponse(text) {
    if (!voiceEnabled || !text) return;

    // Strip markdown formatting for cleaner speech
    var cleanText = text
        .replace(/\*\*(.*?)\*\*/g, '$1')
        .replace(/\*(.*?)\*/g, '$1')
        .replace(/`{1,3}[^`]*`{1,3}/g, '')
        .replace(/#{1,6}\s/g, '')
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
        .replace(/\n{2,}/g, '. ')
        .replace(/\n/g, ' ')
        .trim();

    if (!cleanText) return;

    // Truncate very long responses for TTS
    if (cleanText.length > 500) {
        cleanText = cleanText.substring(0, 500) + '... That is a summary of the full response.';
    }

    try {
        var response = await fetch('/tools/archie-chat/api/voice/synthesize', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({ text: cleanText, use_cache: true })
        });
        var data = await response.json();

        if (data.success && data.audio_base64) {
            var audioBlob = Uint8Array.from(atob(data.audio_base64), function(c) { return c.charCodeAt(0); });
            var blob = new Blob([audioBlob], { type: 'audio/wav' });
            var url = URL.createObjectURL(blob);
            var audio = new Audio(url);
            currentAudio = audio;
            audio.onended = function() {
                currentAudio = null;
                URL.revokeObjectURL(url);
            };
            audio.onerror = function() {
                currentAudio = null;
                URL.revokeObjectURL(url);
            };
            await audio.play();
        }
    } catch (e) {
        console.debug('Auto-TTS error:', e);
    }
}

// =========================================================================
// Collaboration Templates
// =========================================================================

const COLLAB_TEMPLATES = [
    {
        id: 'code-review',
        name: 'Code Review',
        icon: '\uD83D\uDD0D',
        description: 'Review code for bugs, quality, and best practices',
        prompt: 'Review this code and identify issues, improvements, and best practices:\n\n[paste code here]',
        mode: 'joint',
        maxTurns: 8,
        systemHint: 'Focus on code quality, potential bugs, and actionable improvements.'
    },
    {
        id: 'brainstorm',
        name: 'Brainstorm',
        icon: '\uD83D\uDCA1',
        description: 'Generate and refine ideas collaboratively',
        prompt: 'Brainstorm ideas for: [describe your goal]',
        mode: 'discuss',
        maxTurns: 12,
        systemHint: 'Be creative and build on each other\'s ideas.'
    },
    {
        id: 'debug',
        name: 'Debug Analysis',
        icon: '\uD83D\uDC1B',
        description: 'Diagnose and solve a technical problem',
        prompt: 'Help debug this issue:\n\nSymptom: [describe what\'s happening]\nExpected: [what should happen]\nContext: [relevant code/config]',
        mode: 'joint',
        maxTurns: 10,
        systemHint: 'Systematic debugging: reproduce, isolate, diagnose, fix.'
    },
    {
        id: 'architecture',
        name: 'Architecture Design',
        icon: '\uD83C\uDFD7\uFE0F',
        description: 'Design system architecture or component structure',
        prompt: 'Design the architecture for: [describe the system/feature]\n\nConstraints: [list any constraints]',
        mode: 'joint',
        maxTurns: 10,
        systemHint: 'Focus on scalability, maintainability, and clear boundaries.'
    },
    {
        id: 'knowledge',
        name: 'Knowledge Synthesis',
        icon: '\uD83D\uDCDA',
        description: 'Research and synthesize knowledge on a topic',
        prompt: 'Research and synthesize knowledge about: [topic]',
        mode: 'discuss',
        maxTurns: 8,
        systemHint: 'Combine perspectives for comprehensive understanding.'
    },
    {
        id: 'freeform',
        name: 'Freeform',
        icon: '\u270F\uFE0F',
        description: 'Start with your own topic',
        prompt: '',
        mode: 'discuss',
        maxTurns: 10,
        systemHint: ''
    }
];

let selectedTemplate = null;

function renderTemplates() {
    var container = document.getElementById('collab-templates');
    if (!container) return;

    container.textContent = '';
    COLLAB_TEMPLATES.forEach(function(tpl) {
        var card = document.createElement('div');
        card.className = 'template-card';
        card.dataset.templateId = tpl.id;
        if (selectedTemplate && selectedTemplate.id === tpl.id) {
            card.classList.add('selected');
        }

        var iconEl = document.createElement('div');
        iconEl.className = 'template-icon';
        iconEl.textContent = tpl.icon;
        card.appendChild(iconEl);

        var nameEl = document.createElement('div');
        nameEl.className = 'template-name';
        nameEl.textContent = tpl.name;
        card.appendChild(nameEl);

        var descEl = document.createElement('div');
        descEl.className = 'template-desc';
        descEl.textContent = tpl.description;
        card.appendChild(descEl);

        card.addEventListener('click', function() {
            applyTemplate(tpl);
        });

        container.appendChild(card);
    });
}

function applyTemplate(tpl) {
    selectedTemplate = tpl;

    // Fill topic
    var topicEl = document.getElementById('collab-topic');
    if (topicEl && tpl.prompt) {
        topicEl.value = tpl.prompt;
        topicEl.focus();
    }

    // Set mode
    setCollabMode(tpl.mode);

    // Set max turns
    var turnsEl = document.getElementById('collab-max-turns');
    if (turnsEl) {
        turnsEl.value = tpl.maxTurns;
    }

    // Highlight selected card
    document.querySelectorAll('.template-card').forEach(function(c) {
        c.classList.toggle('selected', c.dataset.templateId === tpl.id);
    });
}

// Override startCollaboration to include systemHint
var _templateStartCollaboration = startCollaboration;
startCollaboration = async function() {
    // Inject systemHint into fetch body if a template is selected
    if (selectedTemplate && selectedTemplate.systemHint && currentCollabMode !== 'joint') {
        // For discuss mode, override the original to pass systemHint
        var topicInput = document.getElementById('collab-topic');
        var maxTurnsInput = document.getElementById('collab-max-turns');
        var topic = topicInput.value.trim();
        if (!topic) {
            alert('Please enter a topic for discussion');
            return;
        }
        var maxTurns = parseInt(maxTurnsInput.value) || 10;

        try {
            var response = await fetch('/tools/consciousness/api/collab/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    topic: topic,
                    max_turns: maxTurns,
                    system_hint: selectedTemplate.systemHint
                })
            });
            var data = await response.json();
            if (data.success) {
                renderedMessageCount = 0;
                collabSession = {
                    id: data.session_id,
                    status: data.status,
                    topic: topic,
                    messages: []
                };
                document.getElementById('collab-start-view').style.display = 'none';
                document.getElementById('collab-active-view').style.display = 'flex';
                startCollabStream();
                showNotification('Collaboration started!', 'success');
            } else {
                showNotification(data.error || 'Failed to start collaboration', 'error');
            }
        } catch (e) {
            console.error('Start collab error:', e);
            showNotification('Failed to start collaboration', 'error');
        }
    } else if (selectedTemplate && selectedTemplate.systemHint && currentCollabMode === 'joint') {
        // For joint mode, override to pass systemHint
        var topicInput = document.getElementById('collab-topic');
        var maxTurnsInput = document.getElementById('collab-max-turns');
        var topic = topicInput.value.trim();
        if (!topic) {
            alert('Please enter a topic for joint work');
            return;
        }
        var maxTurns = parseInt(maxTurnsInput.value) || 10;

        try {
            var response = await fetch('/tools/consciousness/api/collab/joint/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    topic: topic,
                    max_turns: maxTurns,
                    system_hint: selectedTemplate.systemHint
                })
            });
            var data = await response.json();
            if (data.success) {
                renderedMessageCount = 0;
                collabSession = {
                    id: data.session_id,
                    status: data.status,
                    topic: topic,
                    messages: [],
                    isJoint: true
                };
                document.getElementById('collab-start-view').style.display = 'none';
                document.getElementById('collab-active-view').style.display = 'flex';
                var titleEl = document.getElementById('collab-active-title');
                if (titleEl) titleEl.textContent = 'Joint Work in Progress';
                var toggleBtn = document.getElementById('btn-toggle-products');
                if (toggleBtn) toggleBtn.style.display = 'inline-block';
                showWorkProducts();
                startCollabStream();
                startWorkProductsPoll();
                showNotification('Joint collaboration started!', 'success');
            } else {
                showNotification(data.error || 'Failed to start joint work', 'error');
            }
        } catch (e) {
            console.error('Start joint collab error:', e);
            showNotification('Failed to start joint collaboration', 'error');
        }
    } else {
        await _templateStartCollaboration();
    }
};

// =========================================================================
// History Browser
// =========================================================================

let historyVisible = false;
let historyFilter = 'all';
let collabReadOnly = false;

function toggleCollabHistory() {
    historyVisible = !historyVisible;
    var sidebar = document.getElementById('collab-history-sidebar');
    var toggleBtn = document.getElementById('btn-history-toggle');

    if (sidebar) {
        sidebar.classList.toggle('collapsed', !historyVisible);
    }
    if (toggleBtn) {
        toggleBtn.classList.toggle('active', historyVisible);
    }

    if (historyVisible) {
        loadCollabHistory();
    }
    // Phase 9: Persist history sidebar state
    localStorage.setItem('collabHistoryVisible', historyVisible ? '1' : '0');
}

function setHistoryFilter(filter) {
    historyFilter = filter;
    document.querySelectorAll('.filter-pill').forEach(function(pill) {
        pill.classList.toggle('active', pill.dataset.filter === filter);
    });
    loadCollabHistory();
}

async function loadCollabHistory() {
    var searchInput = document.getElementById('history-search-input');
    var search = searchInput ? searchInput.value.trim() : '';
    var params = new URLSearchParams();
    if (search) params.set('search', search);
    if (historyFilter && historyFilter !== 'all') params.set('status', historyFilter);

    try {
        var response = await fetch('/tools/consciousness/api/collab/sessions?' + params.toString());
        var data = await response.json();

        if (data.success) {
            renderHistoryList(data.sessions || []);
        }
    } catch (e) {
        console.error('Load history error:', e);
    }
}

function renderHistoryList(sessions) {
    var container = document.getElementById('history-list');
    if (!container) return;

    container.textContent = '';

    if (sessions.length === 0) {
        var emptyEl = document.createElement('div');
        emptyEl.style.cssText = 'padding: 1rem; text-align: center; color: var(--text-muted, #888); font-size: 0.8rem;';
        emptyEl.textContent = 'No sessions found';
        container.appendChild(emptyEl);
        return;
    }

    sessions.forEach(function(session) {
        var item = document.createElement('div');
        item.className = 'history-item';
        if (collabSession && collabSession.id === session.id) {
            item.classList.add('active');
        }

        // Topic
        var topicEl = document.createElement('div');
        topicEl.className = 'history-item-topic';
        topicEl.textContent = session.topic || 'Untitled';
        item.appendChild(topicEl);

        // Meta row: status dot + date + message count
        var metaEl = document.createElement('div');
        metaEl.className = 'history-item-meta';

        var dot = document.createElement('span');
        dot.className = 'history-status-dot ' + (session.status || 'completed');
        metaEl.appendChild(dot);

        var dateText = '';
        if (session.created_at) {
            dateText = ArchieTime.format(session.created_at, 'short');
        }
        var dateEl = document.createElement('span');
        dateEl.textContent = dateText;
        metaEl.appendChild(dateEl);

        var msgCount = session.message_count || (session.messages ? session.messages.length : 0);
        var countEl = document.createElement('span');
        countEl.textContent = msgCount + ' msgs';
        metaEl.appendChild(countEl);

        var turnsEl = document.createElement('span');
        turnsEl.textContent = (session.current_turn || 0) + '/' + (session.max_turns || 10);
        metaEl.appendChild(turnsEl);

        item.appendChild(metaEl);

        // Actions
        var actionsEl = document.createElement('div');
        actionsEl.className = 'history-item-actions';

        var viewBtn = document.createElement('button');
        viewBtn.textContent = 'View';
        viewBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            viewCollabSession(session.id);
        });
        actionsEl.appendChild(viewBtn);

        if (session.status === 'stopped' || session.status === 'completed') {
            var continueBtn = document.createElement('button');
            continueBtn.className = 'btn-continue';
            continueBtn.textContent = 'Continue';
            continueBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                continueCollabSession(session.id);
            });
            actionsEl.appendChild(continueBtn);
        }

        item.appendChild(actionsEl);

        // Click item to view
        item.addEventListener('click', function() {
            viewCollabSession(session.id);
        });

        container.appendChild(item);
    });
}

async function viewCollabSession(sessionId) {
    try {
        var response = await fetch('/tools/consciousness/api/collab/status/' + sessionId);
        var data = await response.json();

        if (!data.success) {
            showNotification('Failed to load session', 'error');
            return;
        }

        var session = data.session;

        // Set read-only mode
        collabReadOnly = true;
        collabSession = {
            id: session.id,
            status: session.status,
            topic: session.topic,
            messages: session.messages || []
        };

        // Show active view in read-only
        document.getElementById('collab-start-view').style.display = 'none';
        document.getElementById('collab-active-view').style.display = 'flex';

        var banner = document.getElementById('collab-readonly-banner');
        if (banner) banner.style.display = 'block';

        var titleEl = document.getElementById('collab-active-title');
        if (titleEl) titleEl.textContent = session.topic || 'Past Session';

        // Show export buttons
        var exportBtns = document.getElementById('collab-export-btns');
        if (exportBtns) exportBtns.style.display = 'flex';

        // Clear and render messages
        var messagesContainer = document.getElementById('collab-messages');
        messagesContainer.textContent = '';
        renderedMessageCount = 0;

        (session.messages || []).forEach(function(msg) {
            renderCollabMessage(msg);
        });

        // Update status bar
        updateCollabStatusUI(session.status, session.current_turn, session.max_turns);

        // Hide control buttons in read-only
        var btnPause = document.getElementById('btn-pause');
        var btnResume = document.getElementById('btn-resume');
        var btnStop = document.getElementById('btn-stop');
        var btnInterject = document.getElementById('btn-interject');
        if (btnPause) btnPause.style.display = 'none';
        if (btnResume) btnResume.style.display = 'none';
        if (btnStop) btnStop.style.display = 'none';
        if (btnInterject) btnInterject.style.display = 'none';

        // Load work products if any
        if (session.work_products && session.work_products.length > 0) {
            var toggleBtn = document.getElementById('btn-toggle-products');
            if (toggleBtn) toggleBtn.style.display = 'inline-block';
            renderWorkProducts(session.work_products);
            showWorkProducts();
        }

        // Update history list selection
        document.querySelectorAll('.history-item').forEach(function(item) {
            item.classList.remove('active');
        });
        // Highlight is handled on next reload

        showNotification('Viewing session: ' + (session.topic || '').substring(0, 40), 'info');
    } catch (e) {
        console.error('View session error:', e);
        showNotification('Failed to load session', 'error');
    }
}

async function continueCollabSession(sessionId) {
    if (!confirm('Continue this collaboration? New turns will be added.')) return;

    try {
        var response = await fetch('/tools/consciousness/api/collab/continue/' + sessionId, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        var data = await response.json();

        if (data.success) {
            // First load the full session to get existing messages
            collabReadOnly = false;
            var banner = document.getElementById('collab-readonly-banner');
            if (banner) banner.style.display = 'none';

            // Load existing messages
            var statusResp = await fetch('/tools/consciousness/api/collab/status/' + sessionId);
            var statusData = await statusResp.json();

            if (statusData.success) {
                var session = statusData.session;
                renderedMessageCount = 0;
                collabSession = {
                    id: session.id,
                    status: 'active',
                    topic: session.topic,
                    messages: session.messages || []
                };

                document.getElementById('collab-start-view').style.display = 'none';
                document.getElementById('collab-active-view').style.display = 'flex';

                var titleEl = document.getElementById('collab-active-title');
                if (titleEl) titleEl.textContent = 'Continuing: ' + (session.topic || '').substring(0, 50);

                // Show export buttons
                var exportBtns = document.getElementById('collab-export-btns');
                if (exportBtns) exportBtns.style.display = 'flex';

                // Render existing messages
                var messagesContainer = document.getElementById('collab-messages');
                messagesContainer.textContent = '';
                (session.messages || []).forEach(function(msg) {
                    renderCollabMessage(msg);
                });

                // Start SSE for new messages
                startCollabStream();

                showNotification('Collaboration resumed!', 'success');
            }
        } else {
            showNotification(data.error || 'Failed to continue', 'error');
        }
    } catch (e) {
        console.error('Continue session error:', e);
        showNotification('Failed to continue session', 'error');
    }
}

// =========================================================================
// Export & Share Functions
// =========================================================================

function buildCollabMarkdown() {
    if (!collabSession) return '';

    var lines = [];
    lines.push('# AI Collaboration: ' + (collabSession.topic || 'Untitled'));
    var dateIso = collabSession.created_at || new Date().toISOString();
    var dateLocal = (typeof ArchieTime !== 'undefined') ? ArchieTime.format(dateIso, 'datetime') : dateIso;
    lines.push('**Date**: ' + dateLocal +
        ' | **Status**: ' + (collabSession.status || 'unknown') +
        ' | **Messages**: ' + (collabSession.messages ? collabSession.messages.length : 0));
    lines.push('');
    lines.push('---');
    lines.push('');
    lines.push('## Conversation');
    lines.push('');

    (collabSession.messages || []).forEach(function(msg) {
        var roleLabel = msg.role === 'archie' ? 'A.R.C.H.I.E.' :
                       msg.role === 'claude' ? 'Claude' : 'User';
        var roleIcon = msg.role === 'archie' ? '\uD83E\uDDE0' :
                      msg.role === 'claude' ? '\uD83E\uDD16' : '\uD83D\uDC64';
        var modelInfo = msg.model_used ? ' (' + msg.model_used : '';
        if (msg.duration_ms) modelInfo += ', ' + msg.duration_ms + 'ms';
        if (modelInfo) modelInfo += ')';

        lines.push('### Turn ' + msg.turn);
        lines.push('**' + roleIcon + ' ' + roleLabel + '**' + modelInfo);
        lines.push(msg.content);
        lines.push('');
    });

    lines.push('---');
    lines.push('*Exported from A.R.C.H.I.E. Platform*');

    return lines.join('\n');
}

function exportCollabMarkdown() {
    var md = buildCollabMarkdown();
    if (!md) {
        showNotification('No session to export', 'error');
        return;
    }

    var blob = new Blob([md], { type: 'text/markdown' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    var safeTopic = (collabSession.topic || 'collaboration').replace(/[^a-z0-9]/gi, '_').substring(0, 40);
    a.download = 'collab_' + safeTopic + '.md';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showNotification('Exported as Markdown', 'success');
}

function copyCollabToClipboard() {
    var md = buildCollabMarkdown();
    if (!md) {
        showNotification('No session to copy', 'error');
        return;
    }

    navigator.clipboard.writeText(md).then(function() {
        showNotification('Copied to clipboard', 'success');
    }).catch(function() {
        // Fallback
        var textarea = document.createElement('textarea');
        textarea.value = md;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        showNotification('Copied to clipboard', 'success');
    });
}

async function saveWorkProductToKB(productId) {
    if (!confirm('Save this work product to the Knowledge Base?')) return;

    try {
        var response = await fetch('/tools/consciousness/api/collab/work-products/' + productId + '/save-to-kb', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        var data = await response.json();

        if (data.success) {
            showNotification('Saved to Knowledge Base! (ID: ' + data.kb_id + ')', 'success');
        } else {
            showNotification(data.error || 'Failed to save', 'error');
        }
    } catch (e) {
        console.error('Save to KB error:', e);
        showNotification('Failed to save to Knowledge Base', 'error');
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Check if we're on the consciousness dashboard
    if (!document.getElementById('solo-chat-container')) return;

    // Initialize resize handle
    initResizeHandle();

    // Check Claude status periodically
    checkClaudeStatus();
    setInterval(checkClaudeStatus, 30000);

    // Load learning stats
    loadCollabLearnings();

    // Render collaboration templates
    renderTemplates();

    // Phase 9: Restore collaboration history sidebar state
    if (localStorage.getItem('collabHistoryVisible') === '1') {
        toggleCollabHistory();
    }
});
