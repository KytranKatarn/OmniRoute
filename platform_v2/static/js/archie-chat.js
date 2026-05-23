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
    this.voiceMode = false;
    this.pendingImages = [];   // base64 data-URIs waiting to be sent
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
    var sidebarToggle = document.getElementById('ac-sidebar-toggle');

    if (sendBtn) sendBtn.addEventListener('click', function() { self.sendMessage(); });
    if (newChatBtn) newChatBtn.addEventListener('click', function() { self.newConversation(); });
    if (targetSelect) targetSelect.addEventListener('change', function() { self.setAgentTarget(); });
    if (flightToggle) flightToggle.addEventListener('click', function() { self.toggleFlightDeck(); });
    if (flightClose) flightClose.addEventListener('click', function() { self.toggleFlightDeck(); });
    if (sidebarToggle) sidebarToggle.addEventListener('click', function() { self.toggleSidebar(); });
    var voiceBtn = document.getElementById('ac-voice-btn');
    if (voiceBtn) voiceBtn.addEventListener('click', function() { self.toggleVoiceMode(); });

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

    // Restore last active conversation from localStorage
    var savedConv = localStorage.getItem('archie-chat-conversation');
    if (savedConv) this.conversationId = savedConv;

    // Image upload: paste + clip button
    this._initImageUpload(input, sendBtn);

    this.loadConversations();
  }

  /* ── API Helper ────────────────────────────────────── */

  async chatApi(endpoint, options) {
    try {
      // Use AbortController for 3-minute timeout (orchestration can be slow)
      var controller = new AbortController();
      var timeoutId = setTimeout(function() { controller.abort(); }, 180000);

      var resp = await fetch('/tools/archie-chat' + endpoint, {
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        ...options
      });
      clearTimeout(timeoutId);

      var data = await resp.json();
      if (!resp.ok) {
        console.error('Chat API error:', data);
        var errMsg = (data.error && data.error.message) ? data.error.message : (data.error || 'Request failed');
        return { error: errMsg };
      }
      return data;
    } catch (err) {
      console.error('Chat API fetch error:', err);
      if (err.name === 'AbortError') {
        return { error: 'Request timed out. A.R.C.H.I.E. may still be processing — try again in a moment.' };
      }
      return { error: err.message || 'Network error' };
    }
  }

  /* ── Messaging ─────────────────────────────────────── */

  async sendMessage() {
    var input = document.getElementById('ac-message-input');
    var sendBtn = document.getElementById('ac-send-btn');
    if (!input || this.sending) return;

    var message = input.value.trim();
    var hasImages = this.pendingImages.length > 0;
    if (!message && !hasImages) return;

    this.sending = true;
    if (sendBtn) sendBtn.disabled = true;
    input.value = '';
    input.style.height = 'auto';

    // Snapshot and clear pending images
    var imagesToSend = this.pendingImages.slice();
    this.pendingImages = [];
    this._clearImagePreviews();

    // Show user message immediately (with image thumbnails if any)
    this.renderMessage({
      role: 'user',
      content: message || '📎 [image]',
      created_at: new Date().toISOString(),
      images: imagesToSend
    });

    // Show thinking indicator
    this.showThinking(true);
    this.showFlightDeckProcessing();

    var payload = {
      message: message || '(image attached)',
      conversation_id: this.conversationId,
      agent_target: this.agentTarget,
      include_thinking: true,
      voice_mode: this.voiceMode,
      images: imagesToSend.length ? imagesToSend : undefined
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
      if (data.conversation_id) {
        this.conversationId = data.conversation_id;
        localStorage.setItem('archie-chat-conversation', data.conversation_id);
      }

      // Agent info comes as nested object: data.agent = {name, display_name, station}
      var agent = data.agent || {};
      this.renderMessage({
        role: 'assistant',
        content: data.response || data.content || '',
        agent_display_name: agent.display_name || agent.name || 'A.R.C.H.I.E.',
        station_code: agent.station || 'COMMAND',
        thinking_steps: data.thinking_steps || [],
        duration_ms: data.duration_ms || 0,
        created_at: data.created_at || new Date().toISOString()
      });

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
      // Handle both new message format (agent_display_name) and history format (agent_used)
      var station = msg.station_code || 'COMMAND';
      var name = msg.agent_display_name || msg.agent_used || 'A.R.C.H.I.E.';
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

      // Text content (markdown rendered for assistant messages)
      var text2 = document.createElement('div');
      text2.className = 'ac-message-text';
      text2.innerHTML = this._renderMarkdown(msg.content);
      bubble2.appendChild(text2);

      // Inline flight deck icon + expandable steps (per message)
      var steps = msg.thinking_steps || [];
      if (steps.length > 0) {
        var totalMs = 0;
        for (var s = 0; s < steps.length; s++) totalMs += (steps[s].duration_ms || 0);

        var fdBtn = document.createElement('button');
        fdBtn.className = 'ac-inline-fd-btn';
        fdBtn.title = 'Flight Deck — ' + steps.length + ' steps, ' + this.formatDuration(totalMs);
        fdBtn.textContent = '\u26A1 ' + this.formatDuration(totalMs);

        var fdPanel = document.createElement('div');
        fdPanel.className = 'ac-inline-fd-panel ac-hidden';

        var self = this;
        for (var s = 0; s < steps.length; s++) {
          var step = steps[s];
          var stepType = step.step_type || step.label || '';
          var sColor = this._stepColor(stepType);
          var dur = step.duration_ms || 0;
          var dataSummary = this._formatStepData(step.data, stepType);

          var row = document.createElement('div');
          row.className = 'ac-inline-fd-row';

          var dot = document.createElement('span');
          dot.className = 'ac-inline-fd-dot';
          dot.style.background = sColor;
          row.appendChild(dot);

          var lbl = document.createElement('span');
          lbl.className = 'ac-inline-fd-label';
          lbl.style.color = sColor;
          lbl.textContent = step.label || stepType;
          row.appendChild(lbl);

          var durEl = document.createElement('span');
          durEl.className = 'ac-inline-fd-dur';
          durEl.textContent = this.formatDuration(dur);
          row.appendChild(durEl);

          if (dataSummary) {
            var dataEl = document.createElement('span');
            dataEl.className = 'ac-inline-fd-data';
            dataEl.textContent = dataSummary;
            row.appendChild(dataEl);
          }

          fdPanel.appendChild(row);
        }

        fdBtn.addEventListener('click', function() {
          fdPanel.classList.toggle('ac-hidden');
        });

        bubble2.appendChild(fdBtn);
        bubble2.appendChild(fdPanel);
      }

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
      var dur = step.duration_ms || 0;
      totalMs += dur;

      // Determine color based on step type
      var stepType = step.step_type || step.label || '';
      var color = this._stepColor(stepType);

      // Format data object into a readable summary
      var dataSummary = this._formatStepData(step.data, stepType);

      var card = document.createElement('div');
      card.className = 'ac-step-card';

      var border = document.createElement('div');
      border.className = 'ac-step-border';
      border.style.background = color;
      card.appendChild(border);

      var content = document.createElement('div');
      content.className = 'ac-step-content';

      var header = document.createElement('div');
      header.className = 'ac-step-header';

      var stepName = document.createElement('span');
      stepName.className = 'ac-step-name';
      stepName.style.color = color;
      stepName.textContent = step.label || stepType || 'Step';
      header.appendChild(stepName);

      var stepDur = document.createElement('span');
      stepDur.className = 'ac-step-duration';
      stepDur.textContent = this.formatDuration(dur);
      header.appendChild(stepDur);

      content.appendChild(header);

      if (dataSummary) {
        var stepData = document.createElement('div');
        stepData.className = 'ac-step-data';
        stepData.textContent = dataSummary;
        content.appendChild(stepData);
      }

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

    // Flight deck panel no longer auto-opens — steps are shown inline per message
    // The panel still works via the yellow toggle button for a full overview
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
      var id = c.conversation_uuid || c.uuid || c.id;
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

    // Auto-load saved conversation on first load
    if (this.conversationId && !this._initialLoaded) {
      this._initialLoaded = true;
      this.switchConversation(this.conversationId);
    }
  }

  async switchConversation(uuid) {
    this.conversationId = uuid;
    localStorage.setItem('archie-chat-conversation', uuid);

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
    localStorage.removeItem('archie-chat-conversation');

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

    // On small screens (<= 1024px), use ac-force-show to overlay
    var isSmallScreen = window.innerWidth <= 1024;
    var isVisible;

    if (isSmallScreen) {
      isVisible = deck.classList.toggle('ac-force-show');
    } else {
      var isHidden = deck.classList.toggle('ac-hidden');
      isVisible = !isHidden;
    }

    // Toggle button: show when deck hidden, hide when deck visible
    if (toggle) {
      toggle.style.display = isVisible ? 'none' : 'flex';
    }
  }

  toggleSidebar() {
    var sidebar = document.getElementById('ac-sidebar');
    if (!sidebar) return;
    var isVisible = sidebar.classList.toggle('ac-force-show');
    // Close sidebar when a conversation is clicked (bind once)
    if (isVisible && !sidebar._closeHandler) {
      sidebar._closeHandler = function(e) {
        if (e.target.closest('.ac-conversation-item')) {
          sidebar.classList.remove('ac-force-show');
        }
      };
      sidebar.addEventListener('click', sidebar._closeHandler);
    }
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

  /* ── Markdown Rendering ───────────────────────────── */

  _renderMarkdown(text) {
    if (!text) return '';
    var html = text
        // Escape HTML first
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        // Code blocks (```)
        .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="ac-code-block"><code>$2</code></pre>')
        // Inline code
        .replace(/`([^`]+)`/g, '<code class="ac-code-inline">$1</code>')
        // Bold
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        // Italic
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        // Headers
        .replace(/^### (.+)$/gm, '<h4 class="ac-md-h4">$1</h4>')
        .replace(/^## (.+)$/gm, '<h3 class="ac-md-h3">$1</h3>')
        .replace(/^# (.+)$/gm, '<h2 class="ac-md-h2">$1</h2>')
        // Numbered lists
        .replace(/^\d+\.\s+(.+)$/gm, '<li class="ac-md-li">$1</li>')
        // Bullet lists
        .replace(/^[-*]\s+(.+)$/gm, '<li class="ac-md-li">$1</li>')
        // Wrap consecutive li elements in ul/ol
        .replace(/(<li class="ac-md-li">[\s\S]*?<\/li>\n?)+/g, '<ul class="ac-md-list">$&</ul>')
        // Paragraphs (double newlines)
        .replace(/\n\n/g, '</p><p>')
        // Single newlines within paragraphs
        .replace(/\n/g, '<br>');
    return '<p>' + html + '</p>';
  }

  /* ── Voice Mode ──────────────────────────────────── */

  toggleVoiceMode() {
    this.voiceMode = !this.voiceMode;
    var btn = document.getElementById('ac-voice-btn');
    if (btn) {
        btn.classList.toggle('ac-voice-active', this.voiceMode);
        btn.title = this.voiceMode ? 'Concise mode ON (click to turn off)' : 'Toggle concise mode';
        btn.querySelector('.ac-voice-icon').textContent = this.voiceMode ? '⚡' : '💬';
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

  _stepColor(stepType) {
    var colors = {
      'intent_parse': '#00e5ff',
      'language_detect': '#22d3ee',
      'creed_check': '#10b981',
      'route_decision': '#fbbf24',
      'gpu_check': '#f97316',
      'agent_select': '#8b5cf6',
      'welfare_check': '#f472b6',
      'execute': '#a3e635',
      'fallback': '#ef4444',
      'translate_response': '#818cf8'
    };
    return colors[stepType] || '#00e5ff';
  }

  _formatStepData(data, stepType) {
    if (!data) return '';
    if (typeof data === 'string') return data;
    // Extract the most useful info from the data object
    var parts = [];
    if (data.intent_type || data.intent) parts.push(data.intent_type || data.intent);
    if (data.confidence) parts.push(Math.round(data.confidence * 100) + '%');
    if (data.detected_lang) parts.push(data.detected_lang);
    if (data.preferred_lang) parts.push('pref: ' + data.preferred_lang);
    if (data.approved !== undefined) parts.push(data.approved ? 'approved' : 'blocked');
    if (data.provider) parts.push(data.provider);
    if (data.model_name || data.model) parts.push(data.model_name || data.model);
    if (data.tier) parts.push(data.tier);
    if (data.agent_name) parts.push(data.agent_name);
    if (data.station) parts.push(data.station);
    if (data.score) parts.push('score: ' + (typeof data.score === 'number' ? data.score.toFixed(2) : data.score));
    if (data.healthy !== undefined) parts.push(data.healthy ? 'healthy' : 'stressed');
    if (data.vram_free) parts.push(data.vram_free);
    if (data.station_override) parts.push('→ ' + data.station_override);
    if (data.agent_override) parts.push('→ ' + data.agent_override);
    if (parts.length === 0) {
      // Fallback: show first few key-value pairs
      var keys = Object.keys(data).slice(0, 3);
      for (var k = 0; k < keys.length; k++) {
        var v = data[keys[k]];
        if (v !== null && v !== undefined && typeof v !== 'object') {
          parts.push(keys[k] + ': ' + String(v).substring(0, 30));
        }
      }
    }
    return parts.join(' · ');
  }

  /* ── Image Upload ────────────────────────────────────── */

  _initImageUpload(input, sendBtn) {
    var self = this;

    // Paste handler: intercept clipboard images
    if (input) {
      input.addEventListener('paste', function(e) {
        var items = (e.clipboardData || {}).items || [];
        for (var i = 0; i < items.length; i++) {
          if (items[i].type.startsWith('image/')) {
            e.preventDefault();
            self._handleImageFile(items[i].getAsFile());
            break;
          }
        }
      });
    }

    // Inject clip button + hidden file input beside the send button
    if (sendBtn && sendBtn.parentElement) {
      var fileInput = document.createElement('input');
      fileInput.type = 'file';
      fileInput.accept = 'image/*';
      fileInput.multiple = false;
      fileInput.style.display = 'none';
      fileInput.id = 'ac-image-file-input';
      fileInput.addEventListener('change', function() {
        if (fileInput.files && fileInput.files[0]) {
          self._handleImageFile(fileInput.files[0]);
          fileInput.value = '';
        }
      });

      var clipBtn = document.createElement('button');
      clipBtn.id = 'ac-image-clip-btn';
      clipBtn.type = 'button';
      clipBtn.title = 'Attach image (or paste)';
      clipBtn.textContent = '📎';
      clipBtn.style.cssText = [
        'background:none;border:1px solid rgba(255,255,255,0.15);border-radius:6px;',
        'color:#94a3b8;cursor:pointer;font-size:1rem;padding:0 8px;height:36px;',
        'transition:color .15s,border-color .15s;flex-shrink:0;'
      ].join('');
      clipBtn.addEventListener('mouseenter', function() { clipBtn.style.color = '#00e5ff'; clipBtn.style.borderColor = '#00e5ff'; });
      clipBtn.addEventListener('mouseleave', function() { clipBtn.style.color = '#94a3b8'; clipBtn.style.borderColor = 'rgba(255,255,255,0.15)'; });
      clipBtn.addEventListener('click', function() { fileInput.click(); });

      sendBtn.parentElement.insertBefore(clipBtn, sendBtn);
      sendBtn.parentElement.appendChild(fileInput);

      // Preview strip above input row
      var previewStrip = document.createElement('div');
      previewStrip.id = 'ac-image-preview-strip';
      previewStrip.style.cssText = 'display:none;gap:6px;flex-wrap:wrap;padding:6px 12px 0;';
      sendBtn.parentElement.parentElement.insertBefore(previewStrip, sendBtn.parentElement);
    }
  }

  _handleImageFile(file) {
    if (!file || !file.type.startsWith('image/')) return;
    if (this.pendingImages.length >= 4) return; // max 4
    var self = this;
    var reader = new FileReader();
    reader.onload = function(e) {
      self.pendingImages.push(e.target.result);
      self._renderImagePreviews();
    };
    reader.readAsDataURL(file);
  }

  _renderImagePreviews() {
    var self = this;
    var strip = document.getElementById('ac-image-preview-strip');
    if (!strip) return;
    strip.textContent = '';
    if (!this.pendingImages.length) { strip.style.display = 'none'; return; }
    strip.style.display = 'flex';
    this.pendingImages.forEach(function(src, idx) {
      var wrap = document.createElement('div');
      wrap.style.cssText = 'position:relative;display:inline-block;';
      var img = document.createElement('img');
      img.src = src;
      img.style.cssText = 'width:48px;height:48px;object-fit:cover;border-radius:4px;border:1px solid rgba(255,255,255,0.2);';
      var rm = document.createElement('button');
      rm.textContent = '×';
      rm.type = 'button';
      rm.style.cssText = 'position:absolute;top:-4px;right:-4px;width:16px;height:16px;border-radius:50%;background:#ef4444;border:none;color:#fff;font-size:10px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;';
      rm.addEventListener('click', function() {
        self.pendingImages.splice(idx, 1);
        self._renderImagePreviews();
      });
      wrap.appendChild(img);
      wrap.appendChild(rm);
      strip.appendChild(wrap);
    });
  }

  _clearImagePreviews() {
    var strip = document.getElementById('ac-image-preview-strip');
    if (strip) { strip.textContent = ''; strip.style.display = 'none'; }
  }
}

/* ── Initialize ──────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', function() {
  window.archieChat = new ArchieChatUI();
  window.archieChat.init();
});
