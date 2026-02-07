/**
 * Collaboration Engine - Client-side JavaScript
 * Handles dual-AI chat modes, terminal integration, and collaboration controls
 */

// Global state
let currentChatMode = 'solo';  // 'solo', 'side-by-side', 'collab'
let collabSession = null;
let collabPollInterval = null;
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

    // Initialize terminal for side-by-side mode
    if (mode === 'side-by-side' && !terminal) {
        initTerminal();
    }

    // Load collab state if switching to collab mode
    if (mode === 'collab') {
        loadCollabLearnings();
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
    const statusDot = document.querySelector('.claude-panel .status-dot');
    if (statusDot) {
        statusDot.classList.toggle('offline', !online);
    }
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
            collabSession = {
                id: data.session_id,
                status: data.status,
                topic: topic,
                messages: []
            };

            // Switch to active view
            document.getElementById('collab-start-view').style.display = 'none';
            document.getElementById('collab-active-view').style.display = 'flex';

            // Start polling for updates
            startCollabPoll();

            showNotification('Collaboration started!', 'success');
        } else {
            showNotification(data.error || 'Failed to start collaboration', 'error');
        }
    } catch (e) {
        console.error('Start collab error:', e);
        showNotification('Failed to start collaboration', 'error');
    }
}

function startCollabPoll() {
    if (collabPollInterval) {
        clearInterval(collabPollInterval);
    }

    // Poll every 2 seconds
    collabPollInterval = setInterval(pollCollabStatus, 2000);

    // Immediate first poll
    pollCollabStatus();
}

async function pollCollabStatus() {
    if (!collabSession) return;

    try {
        const response = await fetch('/tools/consciousness/api/collab/status/' + collabSession.id);
        const data = await response.json();

        if (data.success) {
            const session = data.session;
            collabSession.status = session.status;
            collabSession.messages = session.messages;

            // Update UI
            updateCollabUI(session);

            // Stop polling if completed/stopped/error
            if (['completed', 'stopped', 'error'].includes(session.status)) {
                clearInterval(collabPollInterval);
                collabPollInterval = null;
                loadCollabLearnings();  // Refresh learning stats
            }
        }
    } catch (e) {
        console.error('Poll error:', e);
    }
}

function updateCollabUI(session) {
    // Update messages using safe DOM methods
    const messagesContainer = document.getElementById('collab-messages');
    messagesContainer.textContent = '';  // Clear safely

    for (const msg of session.messages) {
        const msgEl = document.createElement('div');
        msgEl.className = 'collab-message ' + msg.role;

        const roleLabel = msg.role === 'archie' ? 'A.R.C.H.I.E.' :
                         msg.role === 'claude' ? 'Claude' : 'You';
        const roleIcon = msg.role === 'archie' ? '🧠' :
                        msg.role === 'claude' ? '🤖' : '👤';

        // Create role element
        const roleEl = document.createElement('div');
        roleEl.className = 'role';
        roleEl.textContent = roleIcon + ' ' + roleLabel;
        msgEl.appendChild(roleEl);

        // Create content element (safely set text)
        const contentEl = document.createElement('div');
        contentEl.className = 'content';
        contentEl.textContent = msg.content;
        msgEl.appendChild(contentEl);

        // Create timestamp element
        const tsEl = document.createElement('div');
        tsEl.className = 'timestamp';
        tsEl.textContent = 'Turn ' + msg.turn;
        msgEl.appendChild(tsEl);

        messagesContainer.appendChild(msgEl);
    }

    // Auto-scroll to bottom
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    // Add thinking indicator if active
    if (session.status === 'active') {
        const thinkingEl = document.createElement('div');
        thinkingEl.className = 'thinking-indicator';

        const dotsEl = document.createElement('div');
        dotsEl.className = 'dots';
        for (let i = 0; i < 3; i++) {
            const dot = document.createElement('div');
            dot.className = 'dot';
            dotsEl.appendChild(dot);
        }
        thinkingEl.appendChild(dotsEl);

        const textEl = document.createElement('span');
        textEl.textContent = 'AIs are collaborating...';
        thinkingEl.appendChild(textEl);

        messagesContainer.appendChild(thinkingEl);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // Update turn counter
    document.getElementById('turn-counter').textContent =
        'Turn ' + session.current_turn + '/' + session.max_turns;

    // Update status
    const statusDot = document.querySelector('.collab-status-dot');
    const statusText = document.querySelector('.collab-status-text');

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
    if (collabPollInterval) {
        clearInterval(collabPollInterval);
        collabPollInterval = null;
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
