/* archie-chat.js — A.R.C.H.I.E. Chat Module UI */
/* All dynamic content is escaped via escHtml() (textContent-based) before DOM insertion */
"use strict";

const STATION_COLORS = {
  COMMAND: '#00e5ff', ANALYTICS: '#8b5cf6', CREATIVE: '#f472b6',
  ENGINEERING: '#fbbf24', COMMUNICATIONS: '#22d3ee', RESEARCH: '#10b981',
  SECURITY: '#ef4444', LOGISTICS: '#f97316', DIPLOMATIC: '#818cf8',
  OPERATIONS: '#a3e635'
};

class ArchieChatUI {
  constructor() {
    this.conversationId = null;
    this.agentTarget = 'auto';
    this.sending = false;
  }

  /* ── Init ──────────────────────────────────────────── */

  init() {
    var self = this;
    var sendBtn = document.getElementById('ac-send-btn');
    var input = document.getElementById('ac-message-input');
    var newChatBtn = document.getElementById('ac-new-chat-btn');
    var targetSelect = document.getElementById('ac-target-select');
    var flightToggle = document.getElementById('ac-flight-deck-toggle');
    var flightClose = document.getElementById('ac-flight-deck-close');

    if (sendBtn) sendBtn.addEventListener('click', function() { self.sendMessage(); });
    if (newChatBtn) newChatBtn.addEventListener('click', function() { self.newConversation(); });
    if (targetSelect) targetSelect.addEventListener('change', function() { self.setAgentTarget(); });
    if (flightToggle) flightToggle.addEventListener('click', function() { self.toggleFlightDeck(); });
    if (flightClose) flightClose.addEventListener('click', function() { self.toggleFlightDeck(); });

    if (input) {
      input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          self.sendMessage();
        }
      });
      input.addEventListener('input', function() {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 160) + 'px';
        if (sendBtn) sendBtn.disabled = !input.value.trim();
      });
    }

    this.loadConversations();
  }

  /* ── API Helper ────────────────────────────────────── */

  async chatApi(endpoint, options) {
    try {
      var resp = await fetch('/tools/archie-chat' + endpoint, {
        headers: { 'Content-Type': 'application/json' },
        ...options
      });
      var data = await resp.json();
      if (!resp.ok) {
        console.error('Chat API error:', data);
        return { error: data.error || 'Request failed' };
      }
      return data;
    } catch (err) {
      console.error('Chat API fetch error:', err);
      return { error: err.message || 'Network error' };
    }
  }

  /* ── Messaging ─────────────────────────────────────── */

  async sendMessage() {
    var input = document.getElementById('ac-message-input');
    var sendBtn = document.getElementById('ac-send-btn');
    if (!input || this.sending) return;

    var message = input.value.trim();
    if (!message) return;

    this.sending = true;
    if (sendBtn) sendBtn.disabled = true;
    input.value = '';
    input.style.height = 'auto';

    // Show user message immediately
    this.renderMessage({ role: 'user', content: message, created_at: new Date().toISOString() });

    // Show thinking indicator
    this.showThinking(true);
    this.showFlightDeckProcessing();

    var payload = {
      message: message,
      conversation_id: this.conversationId,
      agent_target: this.agentTarget,
      include_thinking: true
    };

    var data = await this.chatApi('/api/v1/chat/message', {
      method: 'POST',
      body: JSON.stringify(payload)
    });

    this.showThinking(false);

    if (data.error) {
      this.renderMessage({
        role: 'assistant',
        content: 'Sorry, an error occurred: ' + data.error,
        agent_display_name: 'System',
        station_code: 'COMMAND',
        created_at: new Date().toISOString()
      });
    } else {
      if (data.conversation_id) this.conversationId = data.conversation_id;

      this.renderMessage({
        role: 'assistant',
        content: data.response || data.content || '',
        agent_display_name: data.agent_display_name || data.agent_name || 'ARCHIE',
        station_code: data.station_code || 'COMMAND',
        created_at: data.created_at || new Date().toISOString()
      });

      if (data.thinking_steps && data.thinking_steps.length > 0) {
        this.renderThinkingSteps(data.thinking_steps);
      }

      this.loadConversations();
    }

    this.sending = false;
    if (sendBtn) sendBtn.disabled = !input.value.trim();
    input.focus();
  }

  renderMessage(msg) {
    var container = document.getElementById('ac-messages');
    if (!container) return;

    var div = document.createElement('div');
    div.className = 'ac-message ' + (msg.role === 'user' ? 'ac-message-user' : 'ac-message-assistant');

    if (msg.role === 'user') {
      // Build user message using safe DOM methods
      var bubble = document.createElement('div');
      bubble.className = 'ac-message-bubble';
      var text = document.createElement('div');
      text.className = 'ac-message-text';
      text.textContent = msg.content;
      bubble.appendChild(text);
      div.appendChild(bubble);
    } else {
      var station = msg.station_code || 'COMMAND';
      var name = msg.agent_display_name || 'ARCHIE';
      var initials = this.getAgentInitials(name);
      var color = this.getStationColor(station);

      // Avatar
      var avatar = document.createElement('div');
      avatar.className = 'ac-agent-avatar';
      avatar.setAttribute('data-station', station);
      avatar.style.borderColor = color;
      var initialsSpan = document.createElement('span');
      initialsSpan.className = 'ac-avatar-initials';
      initialsSpan.textContent = initials;
      avatar.appendChild(initialsSpan);
      div.appendChild(avatar);

      // Bubble
      var bubble2 = document.createElement('div');
      bubble2.className = 'ac-message-bubble';

      // Meta
      var meta = document.createElement('div');
      meta.className = 'ac-message-meta';
      var nameSpan = document.createElement('span');
      nameSpan.className = 'ac-agent-name';
      nameSpan.textContent = name;
      meta.appendChild(nameSpan);
      var badge = document.createElement('span');
      badge.className = 'ac-station-badge';
      badge.setAttribute('data-station', station);
      badge.style.color = color;
      badge.style.borderColor = color;
      badge.textContent = station;
      meta.appendChild(badge);
      bubble2.appendChild(meta);

      // Text content
      var text2 = document.createElement('div');
      text2.className = 'ac-message-text';
      text2.textContent = msg.content;
      bubble2.appendChild(text2);
      div.appendChild(bubble2);
    }

    // Insert before thinking indicator if present
    var thinking = document.getElementById('ac-thinking-indicator');
    if (thinking && thinking.parentNode === container) {
      container.insertBefore(div, thinking);
    } else {
      container.appendChild(div);
    }

    this.scrollToBottom();
  }

  renderThinkingSteps(steps) {
    var stepsEl = document.getElementById('ac-flight-deck-steps');
    var totalEl = document.getElementById('ac-flight-deck-total');
    if (!stepsEl) return;

    // Clear and rebuild with safe DOM methods
    stepsEl.textContent = '';
    var totalMs = 0;

    for (var i = 0; i < steps.length; i++) {
      var step = steps[i];
      var station = step.station || 'COMMAND';
      var color = this.getStationColor(station);
      var dur = step.duration_ms || 0;
      totalMs += dur;

      var card = document.createElement('div');
      card.className = 'ac-step-card';
      card.setAttribute('data-station', station);

      var border = document.createElement('div');
      border.className = 'ac-step-border';
      border.style.background = color;
      card.appendChild(border);

      var content = document.createElement('div');
      content.className = 'ac-step-content';

      var stepName = document.createElement('div');
      stepName.className = 'ac-step-name';
      stepName.textContent = step.name || step.step || 'Step';
      content.appendChild(stepName);

      var stepData = document.createElement('div');
      stepData.className = 'ac-step-data';
      stepData.textContent = step.data || step.summary || '';
      content.appendChild(stepData);

      var stepDur = document.createElement('div');
      stepDur.className = 'ac-step-duration';
      stepDur.textContent = this.formatDuration(dur);
      content.appendChild(stepDur);

      card.appendChild(content);
      stepsEl.appendChild(card);
    }

    if (totalEl) {
      totalEl.textContent = '';
      var label = document.createElement('span');
      label.className = 'ac-total-label';
      label.textContent = 'Total';
      totalEl.appendChild(label);
      var durSpan = document.createElement('span');
      durSpan.className = 'ac-total-duration';
      durSpan.textContent = this.formatDuration(totalMs);
      totalEl.appendChild(durSpan);
    }

    // Show flight deck
    var deck = document.getElementById('ac-flight-deck');
    if (deck) deck.classList.remove('ac-hidden');
    var toggle = document.getElementById('ac-flight-deck-toggle');
    if (toggle) toggle.classList.add('ac-hidden');
  }

  /* ── Conversations ─────────────────────────────────── */

  async loadConversations() {
    var data = await this.chatApi('/api/v1/chat/conversations', { method: 'GET' });
    var list = document.getElementById('ac-conversation-list');
    if (!list) return;

    var conversations = data.conversations || data || [];
    if (!Array.isArray(conversations) || conversations.length === 0) {
      list.textContent = '';
      var empty = document.createElement('div');
      empty.className = 'ac-conversation-empty';
      empty.textContent = 'No conversations yet';
      list.appendChild(empty);
      return;
    }

    var self = this;
    list.textContent = '';

    for (var i = 0; i < conversations.length; i++) {
      var c = conversations[i];
      var id = c.uuid || c.id;
      var active = (id === this.conversationId) ? ' ac-conversation-active' : '';
      var title = c.title || c.summary || 'Untitled';

      var item = document.createElement('div');
      item.className = 'ac-conversation-item' + active;
      item.setAttribute('data-conversation-id', id);

      var titleSpan = document.createElement('span');
      titleSpan.className = 'ac-conversation-title';
      titleSpan.textContent = title;
      item.appendChild(titleSpan);

      item.addEventListener('click', (function(cid) {
        return function() { self.switchConversation(cid); };
      })(id));

      list.appendChild(item);
    }
  }

  async switchConversation(uuid) {
    this.conversationId = uuid;

    // Highlight in sidebar
    document.querySelectorAll('.ac-conversation-item').forEach(function(el) {
      el.classList.toggle('ac-conversation-active',
        el.getAttribute('data-conversation-id') === uuid);
    });

    // Load messages
    var data = await this.chatApi('/api/v1/chat/conversations/' + encodeURIComponent(uuid) + '/messages', { method: 'GET' });
    var container = document.getElementById('ac-messages');
    if (!container) return;

    container.textContent = '';

    var messages = data.messages || data || [];
    if (Array.isArray(messages)) {
      for (var i = 0; i < messages.length; i++) {
        this.renderMessage(messages[i]);
      }
    }
  }

  newConversation() {
    this.conversationId = null;

    var container = document.getElementById('ac-messages');
    if (container) container.textContent = '';

    var stepsEl = document.getElementById('ac-flight-deck-steps');
    var totalEl = document.getElementById('ac-flight-deck-total');
    if (stepsEl) stepsEl.textContent = '';
    if (totalEl) totalEl.textContent = '';

    document.querySelectorAll('.ac-conversation-item').forEach(function(el) {
      el.classList.remove('ac-conversation-active');
    });

    var input = document.getElementById('ac-message-input');
    if (input) input.focus();
  }

  /* ── UI Controls ───────────────────────────────────── */

  toggleFlightDeck() {
    var deck = document.getElementById('ac-flight-deck');
    var toggle = document.getElementById('ac-flight-deck-toggle');
    if (!deck) return;
    deck.classList.toggle('ac-hidden');
    if (toggle) toggle.classList.toggle('ac-hidden');
  }

  setAgentTarget() {
    var select = document.getElementById('ac-target-select');
    if (select) this.agentTarget = select.value;
  }

  showThinking(visible) {
    var indicator = document.getElementById('ac-thinking-indicator');
    if (!indicator && visible) {
      var container = document.getElementById('ac-messages');
      if (!container) return;
      indicator = document.createElement('div');
      indicator.id = 'ac-thinking-indicator';
      indicator.className = 'ac-thinking-indicator';

      var dots = document.createElement('div');
      dots.className = 'ac-thinking-dots';
      dots.appendChild(document.createElement('span'));
      dots.appendChild(document.createElement('span'));
      dots.appendChild(document.createElement('span'));
      indicator.appendChild(dots);

      var label = document.createElement('span');
      label.className = 'ac-thinking-label';
      label.textContent = 'Thinking...';
      indicator.appendChild(label);

      container.appendChild(indicator);
    }
    if (indicator) indicator.style.display = visible ? 'flex' : 'none';
    if (visible) this.scrollToBottom();
  }

  showFlightDeckProcessing() {
    var stepsEl = document.getElementById('ac-flight-deck-steps');
    var totalEl = document.getElementById('ac-flight-deck-total');
    if (stepsEl) {
      stepsEl.textContent = '';
      var card = document.createElement('div');
      card.className = 'ac-step-card';

      var border = document.createElement('div');
      border.className = 'ac-step-border';
      border.style.background = '#00e5ff';
      card.appendChild(border);

      var content = document.createElement('div');
      content.className = 'ac-step-content';
      var name = document.createElement('div');
      name.className = 'ac-step-name';
      name.textContent = 'Processing...';
      content.appendChild(name);
      var data = document.createElement('div');
      data.className = 'ac-step-data';
      data.textContent = 'Routing through orchestration pipeline';
      content.appendChild(data);

      card.appendChild(content);
      stepsEl.appendChild(card);
    }
    if (totalEl) totalEl.textContent = '';
  }

  scrollToBottom() {
    var container = document.getElementById('ac-messages');
    if (container) {
      requestAnimationFrame(function() {
        container.scrollTop = container.scrollHeight;
      });
    }
  }

  /* ── Helpers ───────────────────────────────────────── */

  escHtml(str) {
    if (str == null) return '';
    var div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
  }

  formatDuration(ms) {
    if (ms == null || ms === 0) return '0ms';
    if (ms >= 1000) return (ms / 1000).toFixed(1) + 's';
    return Math.round(ms) + 'ms';
  }

  getAgentInitials(displayName) {
    if (!displayName) return '??';
    var parts = displayName.trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return displayName.substring(0, 2).toUpperCase();
  }

  getStationColor(stationCode) {
    return STATION_COLORS[stationCode] || '#00e5ff';
  }
}

/* ── Initialize ──────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', function() {
  window.archieChat = new ArchieChatUI();
  window.archieChat.init();
});
