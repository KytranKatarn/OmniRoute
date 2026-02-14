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

    // Load collab state if switching to collab mode
    if (mode === 'collab') {
        loadCollabLearnings();
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
                        msg.role === 'claude' ? '\u{1F9E0} ARCHIE is thinking' :
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
    if (statusDot) statusDot.className = 'status-dot ' + status;
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
                waitingFor = '\u{1F9E0} ARCHIE is thinking';
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

    statusDot.className = 'status-dot ' + session.status;
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
    document.getElementById('interjection-text').focus();
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

// Override newCollaboration to clean up joint mode state
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

    _originalNewCollaboration();
};

// =========================================================================
// Voice Controller — STT (Web Speech API) + Auto-TTS
// =========================================================================

var voiceModeEnabled = false;
var voiceListening = false;
var speechRecognition = null;

function toggleVoiceMode() {
    voiceModeEnabled = !voiceModeEnabled;
    var btn = document.getElementById('voice-mode-toggle');
    if (btn) {
        btn.classList.toggle('active', voiceModeEnabled);
    }
    if (voiceModeEnabled) {
        showNotification('Voice mode on — responses will be spoken', 'info');
    }
}

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
    speechRecognition.continuous = false;
    speechRecognition.interimResults = true;
    speechRecognition.lang = 'en-US';

    var micBtn = document.getElementById('voice-mic-btn');
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
        if (micBtn) micBtn.classList.add('listening');
        if (statusEl) statusEl.style.display = 'flex';
        if (statusText) statusText.textContent = 'Listening...';
        if (inputEl) inputEl.placeholder = 'Listening...';
    };

    speechRecognition.onresult = function(event) {
        var transcript = '';
        var isFinal = false;
        for (var i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
            if (event.results[i].isFinal) {
                isFinal = true;
            }
        }

        if (inputEl) inputEl.value = transcript;
        if (statusText) statusText.textContent = isFinal ? 'Processing...' : 'Listening...';

        if (isFinal && transcript.trim()) {
            stopVoiceInput();
            // Auto-send
            sendArchieMessage();
        }
    };

    speechRecognition.onerror = function(event) {
        console.error('Speech recognition error:', event.error);
        if (event.error !== 'no-speech') {
            showNotification('Voice input error: ' + event.error, 'error');
        }
        stopVoiceInput();
    };

    speechRecognition.onend = function() {
        stopVoiceInput();
    };

    try {
        speechRecognition.start();
    } catch (e) {
        showNotification('Could not start voice input: ' + e.message, 'error');
    }
}

function stopVoiceInput() {
    voiceListening = false;
    if (speechRecognition) {
        try { speechRecognition.stop(); } catch(e) {}
        speechRecognition = null;
    }
    var micBtn = document.getElementById('voice-mic-btn');
    var statusEl = document.getElementById('voice-status');
    var inputEl = document.getElementById('archie-chat-input');

    if (micBtn) micBtn.classList.remove('listening');
    if (statusEl) statusEl.style.display = 'none';
    if (inputEl) inputEl.placeholder = 'Talk to A.R.C.H.I.E....';
}

async function speakResponse(text) {
    if (!voiceModeEnabled || !text) return;

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
});
