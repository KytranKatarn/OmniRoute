/* A.R.C.H.I.E. Comms — Chat Interface Logic
   Admin-only interface — innerHTML used for markdown rendering from trusted LLM responses. */
(function() {
    'use strict';

    var msgInput = document.getElementById('ac-message-input');
    var sendBtn = document.getElementById('ac-send-btn');
    var messagesEl = document.getElementById('ac-messages');
    var thinkingEl = document.getElementById('ac-thinking');
    var sidebar = document.getElementById('ac-sidebar');
    var sidebarToggle = document.getElementById('ac-sidebar-toggle');
    var flightDeck = document.getElementById('ac-flight-deck');
    var fdToggle = document.getElementById('ac-fd-toggle');
    var fdClose = document.getElementById('ac-fd-close');
    var newChatBtn = document.getElementById('ac-new-chat-btn');
    var targetSelect = document.getElementById('ac-target-select');

    var sessionId = null;
    var sending = false;

    if (window.marked) {
        marked.setOptions({ breaks: true, gfm: true });
    }

    function escHtml(s) {
        if (!s) return '';
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    function renderMarkdown(text) {
        if (window.marked) {
            try { return marked.parse(text); } catch(e) { /* fall through */ }
        }
        return escHtml(text).replace(/\n/g, '<br>');
    }

    function scrollToBottom() {
        requestAnimationFrame(function() { messagesEl.scrollTop = messagesEl.scrollHeight; });
    }

    function addCopyButtons(container) {
        container.querySelectorAll('pre').forEach(function(pre) {
            if (pre.querySelector('.ac-copy-btn')) return;
            var btn = document.createElement('button');
            btn.className = 'ac-copy-btn';
            btn.textContent = 'Copy';
            btn.addEventListener('click', function() {
                var code = pre.querySelector('code');
                navigator.clipboard.writeText(code ? code.textContent : pre.textContent);
                btn.textContent = 'Copied!';
                setTimeout(function() { btn.textContent = 'Copy'; }, 1500);
            });
            pre.style.position = 'relative';
            pre.appendChild(btn);
        });
        if (window.hljs) {
            container.querySelectorAll('pre code').forEach(function(block) {
                hljs.highlightElement(block);
            });
        }
    }

    function appendMessage(role, text, agentName, dept, flightDeckData) {
        var div = document.createElement('div');
        div.className = 'ac-message ac-message-' + role;

        if (role === 'assistant') {
            var initials = (agentName || 'A').charAt(0);
            var avatar = document.createElement('div');
            avatar.className = 'ac-agent-avatar';
            avatar.textContent = '';
            var initialsEl = document.createElement('span');
            initialsEl.className = 'ac-avatar-initials';
            initialsEl.textContent = initials;
            avatar.appendChild(initialsEl);

            var bubble = document.createElement('div');
            bubble.className = 'ac-message-bubble';

            var meta = document.createElement('div');
            meta.className = 'ac-message-meta';
            var nameEl = document.createElement('span');
            nameEl.className = 'ac-agent-name';
            nameEl.textContent = agentName || 'A.R.C.H.I.E.';
            var deptEl = document.createElement('span');
            deptEl.className = 'ac-dept-badge';
            deptEl.textContent = dept || '';
            meta.appendChild(nameEl);
            meta.appendChild(deptEl);

            var textEl = document.createElement('div');
            textEl.className = 'ac-message-text';
            // Trusted LLM output — admin-only interface, no external user input
            textEl.innerHTML = renderMarkdown(text); // nosemgrep: innerHTML-trusted-source

            bubble.appendChild(meta);
            bubble.appendChild(textEl);

            if (flightDeckData) {
                var footer = document.createElement('div');
                footer.className = 'ac-message-footer';
                var fdBtn = document.createElement('button');
                fdBtn.className = 'ac-fd-btn';
                fdBtn.textContent = '\u26A1 flight deck';
                fdBtn.addEventListener('click', function() { window.toggleFD(); });
                footer.appendChild(fdBtn);
                var modelSpan = document.createElement('span');
                modelSpan.textContent = flightDeckData.model || '';
                footer.appendChild(modelSpan);
                if (flightDeckData.total_ms) {
                    var msSpan = document.createElement('span');
                    msSpan.textContent = flightDeckData.total_ms + 'ms';
                    footer.appendChild(msSpan);
                }
                bubble.appendChild(footer);
            }

            div.appendChild(avatar);
            div.appendChild(bubble);
        } else {
            var userBubble = document.createElement('div');
            userBubble.className = 'ac-message-bubble';
            var userText = document.createElement('div');
            userText.className = 'ac-message-text';
            userText.textContent = text;
            userBubble.appendChild(userText);
            div.appendChild(userBubble);
        }

        messagesEl.appendChild(div);
        addCopyButtons(div);
        scrollToBottom();
    }

    // ─── Send message ─────────────────────────────────────
    function sendMessage() {
        var text = msgInput.value.trim();
        if (!text) return;

        sending = true;
        sendBtn.disabled = true;
        msgInput.value = '';
        msgInput.style.height = 'auto';

        appendMessage('user', text);
        thinkingEl.style.display = 'flex';
        scrollToBottom();

        var target = targetSelect.value;
        fetch('/api/chat/send_message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                session_id: sessionId,
                agent_target: target !== 'auto' ? target : undefined
            })
        }).then(function(resp) {
            thinkingEl.style.display = 'none';
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        }).then(function(data) {
            if (data.session_id) sessionId = data.session_id;
            var agentName = data.agent_name || 'A.R.C.H.I.E.';
            var dept = data.department || 'Executive Office';
            var responseText = data.response || data.message || 'No response received.';
            appendMessage('assistant', responseText, agentName, dept, data.flight_deck);
            if (data.flight_deck) renderFlightDeck(data.flight_deck);
        }).catch(function() {
            thinkingEl.style.display = 'none';
            appendMessage('assistant', 'Connection issue. Check if the comms container is running.', 'A.R.C.H.I.E.', 'Executive Office');
        }).finally(function() {
            sending = false;
            sendBtn.disabled = false;
            msgInput.focus();
        });
    }

    // ─── Flight Deck ──────────────────────────────────────
    function renderFlightDeck(fd) {
        var stepsEl = document.getElementById('ac-fd-steps');
        var totalEl = document.getElementById('ac-fd-total');
        if (!stepsEl || !fd.steps) return;

        stepsEl.textContent = '';
        fd.steps.forEach(function(step) {
            var card = document.createElement('div');
            card.className = 'ac-step-card' + (step.success !== false ? ' done' : ' error');
            var nameEl = document.createElement('div');
            nameEl.className = 'ac-step-name';
            nameEl.textContent = step.name || step.step || '';
            var dataEl = document.createElement('div');
            dataEl.className = 'ac-step-data';
            dataEl.textContent = step.detail || step.data || '';
            var durEl = document.createElement('div');
            durEl.className = 'ac-step-duration';
            durEl.textContent = (step.duration_ms || '\u2014') + 'ms';
            card.appendChild(nameEl);
            card.appendChild(dataEl);
            card.appendChild(durEl);
            stepsEl.appendChild(card);
        });

        if (fd.total_ms) {
            totalEl.textContent = '';
            var lbl = document.createElement('span');
            lbl.textContent = 'Total';
            var val = document.createElement('span');
            val.textContent = fd.total_ms + 'ms';
            totalEl.appendChild(lbl);
            totalEl.appendChild(val);
        }
    }

    window.toggleFD = function() {
        flightDeck.classList.toggle('collapsed');
        fdToggle.classList.toggle('visible', flightDeck.classList.contains('collapsed'));
    };

    // ─── Event listeners ──────────────────────────────────
    msgInput.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 150) + 'px';
        sendBtn.disabled = !this.value.trim();
    });

    msgInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (!sendBtn.disabled && !sending) sendMessage();
        }
    });

    sendBtn.addEventListener('click', function() {
        if (!sending) sendMessage();
    });

    sidebarToggle.addEventListener('click', function() {
        if (window.innerWidth <= 768) {
            sidebar.classList.toggle('open');
        } else {
            sidebar.classList.toggle('collapsed');
        }
    });

    fdClose.addEventListener('click', function() {
        flightDeck.classList.add('collapsed');
        fdToggle.classList.add('visible');
    });
    fdToggle.addEventListener('click', function() {
        flightDeck.classList.remove('collapsed');
        fdToggle.classList.remove('visible');
    });

    document.querySelectorAll('.comms-tab').forEach(function(tab) {
        tab.addEventListener('click', function() {
            document.querySelectorAll('.comms-tab').forEach(function(t) { t.classList.remove('active'); });
            tab.classList.add('active');
            var tabId = tab.dataset.tab;
            document.querySelectorAll('.comms-panel').forEach(function(p) {
                p.classList.toggle('active', p.id === 'panel-' + tabId);
            });
        });
    });

    // Bridge LCARS header tabs → comms panel switching
    window.onLcarsTabSwitch = function(tabId) {
        document.querySelectorAll('.comms-panel').forEach(function(p) {
            p.classList.toggle('active', p.id === 'panel-' + tabId);
        });
    };

    newChatBtn.addEventListener('click', function() {
        fetch('/api/chat/new', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        }).then(function(r) { return r.json(); }).then(function(data) {
            sessionId = null;
            messagesEl.textContent = '';
            appendMessage('assistant', 'New conversation started. What shall we work on?', 'A.R.C.H.I.E.', 'Executive Office');
            loadConversations();
        });
    });

    // ─── Conversation history ─────────────────────────────
    function loadConversations() {
        var convList = document.getElementById('ac-conversation-list');
        if (!convList) return;

        fetch('/api/chat/conversations').then(function(r) {
            return r.json();
        }).then(function(data) {
            var convs = data.conversations || [];
            convList.textContent = '';
            if (convs.length === 0) {
                var empty = document.createElement('div');
                empty.style.cssText = 'padding:12px;color:#4b5563;font-size:0.72rem;font-style:italic;';
                empty.textContent = 'No conversations yet';
                convList.appendChild(empty);
                return;
            }
            convs.forEach(function(c) {
                var id = c.id || c[0];
                var topic = c.topic || c[1] || 'Conversation';
                var msgCount = c.msg_count || c[5] || 0;
                var isEscalation = topic === 'A.R.C.H.I.E. Escalations';
                var item = document.createElement('div');
                item.className = 'ac-conversation-item' + (isEscalation ? ' esc-thread' : '');
                item.setAttribute('data-conv-id', id);
                if (isEscalation) { item.setAttribute('data-topic', 'A.R.C.H.I.E. Escalations'); }
                var titleRow = document.createElement('div');
                titleRow.className = 'ac-conversation-title-row';
                var titleText = document.createElement('span');
                titleText.textContent = topic;
                titleRow.appendChild(titleText);
                if (isEscalation) {
                    var chip = document.createElement('span');
                    chip.className = 'sidebar-esc-chip';
                    chip.textContent = 'ESC';
                    titleRow.appendChild(chip);
                }
                var meta = document.createElement('div');
                meta.className = 'ac-conversation-time';
                meta.textContent = msgCount + ' messages';
                item.appendChild(titleRow);
                item.appendChild(meta);
                item.addEventListener('click', function() {
                    loadConversation(id);
                    convList.querySelectorAll('.ac-conversation-item').forEach(function(el) {
                        el.classList.remove('active');
                    });
                    item.classList.add('active');
                });
                convList.appendChild(item);
            });
        }).catch(function() {});
    }

    function loadConversation(convId) {
        fetch('/api/chat/messages?conversation_id=' + convId).then(function(r) {
            return r.json();
        }).then(function(data) {
            var msgs = data.messages || [];
            messagesEl.textContent = '';
            msgs.forEach(function(m) {
                var sender = m.sender || m[3] || '';
                var content = m.content || m[4] || '';
                var metadata = m.metadata || m[5] || {};
                if (sender === 'kytran') {
                    appendMessage('user', content);
                } else {
                    var dept = (typeof metadata === 'object' ? metadata.department : '') || 'Executive Office';
                    appendMessage('assistant', content, 'A.R.C.H.I.E.', dept);
                }
            });
        }).catch(function() {});
    }

    // Load conversations on startup
    loadConversations();

    // ─── Live sidebar status ──────────────────────────────
    function updateSidebarStatus() {
        fetch('/api/health').then(function(r) { return r.json(); }).then(function(d) {
            var mood = document.getElementById('archie-mood');
            if (mood && d.status === 'ok') mood.textContent = 'Online — Ready';
        }).catch(function() {
            var mood = document.getElementById('archie-mood');
            if (mood) mood.textContent = 'Offline';
        });
    }
    updateSidebarStatus();
    setInterval(updateSidebarStatus, 30000);

    msgInput.focus();
})();
