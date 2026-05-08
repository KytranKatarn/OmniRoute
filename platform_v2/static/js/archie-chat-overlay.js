/**
 * ARCHIE Chat Overlay Widget
 * Self-contained floating chat bubble for admin users.
 * Uses .ac-overlay-* classes from archie-chat.css
 */
class ArchieOverlay {
    constructor() {
        this.conversationId = null;
        this.isExpanded = false;
        this.messages = [];
        this.isLoading = false;
        this.agentTarget = null;  // override to route to a specific agent
        this.agentLabel = 'A.R.C.H.I.E.';
        this.agentIcon = '\u{1F4AC}';
    }

    init() {
        this._createDOM();
        this._bindEvents();
        this._restoreState();
    }

    _createDOM() {
        // Floating bubble
        this.bubble = document.createElement('button');
        this.bubble.className = 'ac-overlay-bubble';
        this.bubble.textContent = this.agentIcon;
        this.bubble.title = 'Chat with ' + this.agentLabel;
        document.body.appendChild(this.bubble);

        // Chat window
        this.window = document.createElement('div');
        this.window.className = 'ac-overlay-window ac-overlay-hidden';

        // Build header
        const header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid #333;background:#111;flex-shrink:0;';

        const headerLeft = document.createElement('div');
        headerLeft.style.cssText = 'display:flex;align-items:center;gap:8px;';

        // Portrait thumbnail (hidden until configure() sets portraitUrl)
        this.portraitEl = document.createElement('img');
        this.portraitEl.style.cssText = 'width:28px;height:28px;border-radius:50%;object-fit:cover;border:1px solid #00e5ff44;display:none;';
        headerLeft.appendChild(this.portraitEl);

        const statusDot = document.createElement('span');
        statusDot.style.cssText = 'width:8px;height:8px;border-radius:50%;background:#00e5ff;display:inline-block;';
        this._statusDot = statusDot;

        const label = document.createElement('span');
        label.style.cssText = "font-family:'Orbitron',sans-serif;font-size:0.85rem;color:#00e5ff;font-weight:700;letter-spacing:1px;";
        label.textContent = this.agentLabel;
        this._headerLabel = label;

        headerLeft.appendChild(statusDot);
        headerLeft.appendChild(label);

        const headerRight = document.createElement('div');
        headerRight.style.cssText = 'display:flex;gap:6px;';

        this.expandBtn = document.createElement('button');
        this.expandBtn.className = 'ac-overlay-expand-btn';
        this.expandBtn.title = 'Open full chat';
        this.expandBtn.style.cssText = 'background:none;border:1px solid #444;color:#aaa;border-radius:4px;cursor:pointer;padding:2px 8px;font-size:0.75rem;';
        this.expandBtn.textContent = '\u2197';

        this.minBtn = document.createElement('button');
        this.minBtn.className = 'ac-overlay-min-btn';
        this.minBtn.title = 'Minimize';
        this.minBtn.style.cssText = 'background:none;border:1px solid #444;color:#aaa;border-radius:4px;cursor:pointer;padding:2px 8px;font-size:0.75rem;';
        this.minBtn.textContent = '\u2212';

        headerRight.appendChild(this.expandBtn);
        headerRight.appendChild(this.minBtn);
        header.appendChild(headerLeft);
        header.appendChild(headerRight);

        // Messages area
        this.messagesEl = document.createElement('div');
        this.messagesEl.className = 'ac-overlay-messages';
        this.messagesEl.style.cssText = 'flex:1;overflow-y:auto;padding:10px 14px;display:flex;flex-direction:column;gap:8px;';

        // Input area
        const inputRow = document.createElement('div');
        inputRow.style.cssText = 'display:flex;gap:6px;padding:10px 14px;border-top:1px solid #333;background:#111;flex-shrink:0;';

        this.inputEl = document.createElement('input');
        this.inputEl.className = 'ac-overlay-input';
        this.inputEl.type = 'text';
        this.inputEl.placeholder = 'Message A.R.C.H.I.E. ...';
        this.inputEl.style.cssText = 'flex:1;background:#1a1a1e;border:1px solid #333;border-radius:6px;padding:8px 10px;color:#e0e0e0;font-size:0.85rem;outline:none;';

        this.sendBtn = document.createElement('button');
        this.sendBtn.className = 'ac-overlay-send-btn';
        this.sendBtn.style.cssText = 'background:#00e5ff;border:none;border-radius:6px;padding:8px 14px;color:#000;font-weight:700;cursor:pointer;font-size:0.85rem;';
        this.sendBtn.textContent = 'Send';

        inputRow.appendChild(this.inputEl);
        inputRow.appendChild(this.sendBtn);

        // Assemble window
        this.window.appendChild(header);
        this.window.appendChild(this.messagesEl);
        this.window.appendChild(inputRow);
        document.body.appendChild(this.window);
    }

    _bindEvents() {
        this.bubble.addEventListener('click', () => this.toggle());
        this.minBtn.addEventListener('click', () => this.collapse());
        this.expandBtn.addEventListener('click', () => this.expand());
        this.sendBtn.addEventListener('click', () => this.sendMessage());
        this.inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });
    }

    configure({ agentTarget, label, icon, portraitUrl } = {}) {
        if (agentTarget) this.agentTarget = agentTarget;
        if (label) {
            this.agentLabel = label;
            if (this._headerLabel) this._headerLabel.textContent = label;
            if (this.bubble) this.bubble.title = 'Chat with ' + label;
            if (this.inputEl) this.inputEl.placeholder = 'Message ' + label + ' ...';
        }
        if (icon) {
            this.agentIcon = icon;
            if (this.bubble && !portraitUrl) this.bubble.textContent = icon;
        }
        if (portraitUrl && this.portraitEl) {
            this.portraitEl.src = portraitUrl;
            this.portraitEl.style.display = 'block';
            if (this._statusDot) this._statusDot.style.display = 'none';
            if (this.bubble) {
                this.bubble.textContent = '';
                const img = document.createElement('img');
                img.src = portraitUrl;
                img.style.cssText = 'width:28px;height:28px;border-radius:50%;object-fit:cover;';
                this.bubble.appendChild(img);
            }
        }
        // Reset conversation when reconfiguring agent
        this.conversationId = null;
    }

    _restoreState() {
        const state = localStorage.getItem('archie-overlay-state');
        if (state === 'expanded') {
            this._showWindow();
        }
    }

    toggle() {
        if (this.isExpanded) {
            this.collapse();
        } else {
            this._showWindow();
            localStorage.setItem('archie-overlay-state', 'expanded');
        }
    }

    collapse() {
        this.isExpanded = false;
        this.window.classList.add('ac-overlay-hidden');
        this.bubble.style.display = 'flex';
        localStorage.setItem('archie-overlay-state', 'collapsed');
    }

    expand() {
        let url = '/tools/archie-chat';
        if (this.conversationId) {
            url += '?conversation=' + encodeURIComponent(this.conversationId);
        }
        window.location.href = url;
    }

    _showWindow() {
        this.isExpanded = true;
        this.window.classList.remove('ac-overlay-hidden');
        this.bubble.style.display = 'none';
        this.inputEl.focus();
    }

    async sendMessage() {
        const text = this.inputEl.value.trim();
        if (!text || this.isLoading) return;

        this.inputEl.value = '';
        this.renderMessage('user', text);
        this.isLoading = true;
        this.sendBtn.disabled = true;

        // Show typing indicator
        const typingEl = document.createElement('div');
        typingEl.style.cssText = 'color:#666;font-size:0.8rem;font-style:italic;padding:4px 0;';
        typingEl.textContent = 'A.R.C.H.I.E. is thinking...';
        this.messagesEl.appendChild(typingEl);
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;

        try {
            const body = { message: text, include_thinking: false };
            if (this.conversationId) {
                body.conversation_id = this.conversationId;
            }
            if (this.agentTarget) {
                body.agent_target = this.agentTarget;
            }

            const resp = await fetch('/tools/archie-chat/api/v1/chat/message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            const data = await resp.json();
            typingEl.remove();

            if (data.success) {
                if (data.conversation_id) {
                    this.conversationId = data.conversation_id;
                }
                this.renderMessage('assistant', data.response || data.message || '...');
            } else {
                this.renderMessage('system', 'Error: ' + (data.error || 'Unknown error'));
            }
        } catch (err) {
            typingEl.remove();
            this.renderMessage('system', 'Connection error: ' + err.message);
        } finally {
            this.isLoading = false;
            this.sendBtn.disabled = false;
        }
    }

    renderMessage(role, text) {
        const el = document.createElement('div');
        const isUser = role === 'user';
        const isSystem = role === 'system';

        el.style.cssText = 'padding:8px 10px;border-radius:8px;font-size:0.82rem;line-height:1.4;max-width:88%;word-wrap:break-word;'
            + (isUser
                ? 'background:#1a3a4a;color:#e0e0e0;align-self:flex-end;border:1px solid #00e5ff33;'
                : isSystem
                    ? 'background:#3a1a1a;color:#ff6b6b;align-self:flex-start;border:1px solid #ff6b6b33;'
                    : 'background:#1a1a2e;color:#e0e0e0;align-self:flex-start;border:1px solid #33335533;');

        el.textContent = text;
        this.messagesEl.appendChild(el);
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (!window.location.pathname.startsWith('/tools/archie-chat')) {
        window.archieOverlay = new ArchieOverlay();
        window.archieOverlay.init();
    }
});
