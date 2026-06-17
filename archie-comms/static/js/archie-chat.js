/* archie-chat.js - Command Center JS (Sub-A #2349)
 * Security: all dynamic content uses textContent, not innerHTML.
 * Four classes: SessionManager, MessageStream, StatusPanel, FocusMode
 */

/* Utility: create element with optional className */
function _mk(tag, cls) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  return el;
}

/* ── SessionManager ─────────────────────────────────────── */
class SessionManager {
  constructor({ listEl, onSelect }) {
    this.listEl = listEl;
    this.onSelect = onSelect;
    this.activeId = null;
    this.sessions = [];
  }

  async load() {
    try {
      const resp = await fetch('/api/chat/conversations');
      if (!resp.ok) return;
      const data = await resp.json();
      this.sessions = data.conversations || [];
      this._render();
      if (this.sessions.length && !this.activeId) this.select(this.sessions[0].id);
    } catch (e) { console.error('SessionManager.load:', e); }
  }

  select(id) {
    this.activeId = id;
    this._render();
    this.onSelect(id);
  }

  async createNew() {
    try {
      const resp = await fetch('/api/chat/new', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: 'New conversation' }),
      });
      if (!resp.ok) return;
      const data = await resp.json();
      await this.load();
      if (data.conversation_id) this.select(data.conversation_id);
    } catch (e) { console.error('SessionManager.createNew:', e); }
  }

  markActive(id) { this.activeId = id; this._render(); }

  _render() {
    this.listEl.textContent = '';
    this.sessions.forEach(s => {
      const item = _mk('div', 'ac-session-item' + (s.id === this.activeId ? ' active' : ''));
      const title = _mk('div', 'ac-session-title');
      title.textContent = s.title || 'Conversation';
      const date = _mk('div', 'ac-session-date');
      date.textContent = s.updated_at ? new Date(s.updated_at).toLocaleDateString() : '';
      item.appendChild(title);
      item.appendChild(date);
      // Delete (×) — stopPropagation so it doesn't also trigger select()
      const del = _mk('button', 'ac-session-delete');
      del.type = 'button';
      del.textContent = '×';
      del.title = 'Delete conversation';
      del.setAttribute('aria-label', 'Delete conversation');
      del.addEventListener('click', (e) => { e.stopPropagation(); this._delete(s.id); });
      item.appendChild(del);
      item.addEventListener('click', () => this.select(s.id));
      this.listEl.appendChild(item);
    });
  }

  async _delete(id) {
    if (!window.confirm('Delete this conversation? This cannot be undone.')) return;
    try {
      const resp = await fetch('/api/chat/conversations/' + id, { method: 'DELETE' });
      if (!resp.ok) { console.error('delete failed', resp.status); return; }
      if (this.activeId === id) this.activeId = null;
      // load() re-renders the list and auto-selects the first remaining when activeId is null
      await this.load();
    } catch (e) { console.error('SessionManager._delete:', e); }
  }
}

/* ── MessageStream ──────────────────────────────────────── */
class MessageStream {
  constructor({ messageListEl, inputEl, sendBtn, jumpBtn, onConvCreated }) {
    this.messageListEl = messageListEl;
    this.inputEl = inputEl;
    this.sendBtn = sendBtn;
    this.jumpBtn = jumpBtn;
    this.onConvCreated = onConvCreated;
    this.currentConvId = null;
    this._userScrolled = false;
    this._streamingBubble = null;

    messageListEl.addEventListener('scroll', () => {
      const el = messageListEl;
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      this._userScrolled = !atBottom;
      if (jumpBtn) jumpBtn.classList.toggle('visible', this._userScrolled);
    });
    if (jumpBtn) {
      jumpBtn.addEventListener('click', () => {
        this._scrollToBottom();
        this._userScrolled = false;
        jumpBtn.classList.remove('visible');
      });
    }
  }

  async loadHistory(convId) {
    this.currentConvId = convId;
    this._summaryScheduled = false;
    this.messageListEl.textContent = '';
    try {
      const resp = await fetch('/api/chat/messages?conversation_id=' + convId);
      if (!resp.ok) return;
      const data = await resp.json();
      (data.messages || []).forEach(m => this._appendMessage(m));
      this._scrollToBottom();
    } catch (e) { console.error('loadHistory:', e); }
  }

  async send(message, terminalContext = null, isPlanRequest = false) {
    if (!message.trim()) return;
    this.inputEl.disabled = true;
    this.sendBtn.disabled = true;

    this._appendBubble('inbound', message, '');
    this._scrollToBottom();
    this._streamingBubble = this._appendBubble('outbound', '', '');
    this._streamingBubble.querySelector('.ac-message-bubble').classList.add('ac-streaming-cursor');

    try {
      const resp = await fetch('/api/chat/send_message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          conversation_id: this.currentConvId,
          terminal_context: terminalContext,
          is_plan_request: isPlanRequest,
        }),
      });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.type === 'delegation_queued') {
              new DelegationCard({
                messageListEl: this.messageListEl,
                taskId: evt.task_id,
                capability: evt.capability,
                reason: evt.reason,
              });
              if (!this._userScrolled) this._scrollToBottom();
            } else if (evt.type === 'delegation_failed') {
              this._appendToken('\n[Delegation failed: ' + (evt.reason || 'unknown') + ']');
            } else if (evt.type === 'token') {
              this._appendToken(evt.content);
              if (!this._userScrolled) this._scrollToBottom();
            } else if (evt.type === 'done') {
              this._finaliseStream();
              if (evt.conversation_id && !this.currentConvId) {
                this.currentConvId = evt.conversation_id;
                if (this.onConvCreated) this.onConvCreated(evt.conversation_id);
              }
            } else if (evt.type === 'error') {
              this._appendToken('\n[Error: ' + evt.message + ']');
              this._finaliseStream();
            }
          } catch (_) {}
        }
      }
    } catch (e) {
      console.error('send failed:', e);
      this._appendToken('\n[Connection error. Please try again.]');
      this._finaliseStream();
    } finally {
      this.inputEl.disabled = false;
      this.sendBtn.disabled = false;
      this.inputEl.focus();
    }
  }

  _appendMessage(msg) {
    const direction = msg.direction === 'inbound' ? 'inbound' : 'outbound';
    const extra = msg.channel === 'telegram' ? ' telegram' : '';
    const date = msg.created_at
      ? new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : '';
    const metaText = date + (msg.channel === 'telegram' ? ' · via Telegram' : '');
    return this._appendBubble(direction + extra, msg.content || '', metaText);
  }

  _appendBubble(direction, text, metaText) {
    const wrap = _mk('div', 'ac-message ' + direction);
    const bubble = _mk('div', 'ac-message-bubble');
    bubble.textContent = text;
    const meta = _mk('div', 'ac-message-meta');
    meta.textContent = metaText;
    wrap.appendChild(bubble);
    wrap.appendChild(meta);
    this.messageListEl.appendChild(wrap);
    return wrap;
  }

  _appendToken(token) {
    if (!this._streamingBubble) return;
    const bubble = this._streamingBubble.querySelector('.ac-message-bubble');
    bubble.textContent += token;
  }

  _finaliseStream() {
    if (!this._streamingBubble) return;
    const bubble = this._streamingBubble.querySelector('.ac-message-bubble');
    bubble.classList.remove('ac-streaming-cursor');
    const meta = this._streamingBubble.querySelector('.ac-message-meta');
    meta.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    this._streamingBubble = null;
    this._scheduleSummary();
  }

  _scheduleSummary() {
    if (this._summaryScheduled) return;  // guard: only one listener at a time
    this._summaryScheduled = true;
    const convId = this.currentConvId;
    if (!convId) return;
    const self = this;
    document.addEventListener('visibilitychange', function once() {
      if (document.visibilityState === 'hidden') {
        navigator.sendBeacon('/api/chat/sessions/' + convId + '/summarize');
        document.removeEventListener('visibilitychange', once);
        self._summaryScheduled = false;
      }
    });
  }

  _scrollToBottom() { this.messageListEl.scrollTop = this.messageListEl.scrollHeight; }
}

/* ── StatusPanel ────────────────────────────────────────── */
class StatusPanel {
  constructor({ agentsEl, platformEl, repairBayEl }) {
    this.agentsEl = agentsEl;
    this.platformEl = platformEl;
    this.repairBayEl = repairBayEl;
    this._timer = null;
  }

  start() { this.refresh(); this._timer = setInterval(() => this.refresh(), 10000); }
  stop() { if (this._timer) clearInterval(this._timer); }

  async refresh() {
    try {
      const resp = await fetch('/api/status');
      if (!resp.ok) return;
      const data = await resp.json();
      this._renderAgents(data.agents || []);
      this._renderPlatform(data.platform || {});
    } catch (_) {}
    try {
      const repairResp = await fetch('/api/repair/count');
      if (repairResp.ok) {
        const repairData = await repairResp.json();
        this._renderRepairBay(repairData.count || 0);
      }
    } catch (_) {}
  }

  _renderAgents(agents) {
    if (!this.agentsEl) return;
    this.agentsEl.textContent = '';
    if (!agents.length) {
      const row = _mk('div', 'ac-agent-row');
      row.style.color = '#556677';
      row.textContent = 'No active agents';
      this.agentsEl.appendChild(row);
      return;
    }
    agents.forEach(a => {
      const row = _mk('div', 'ac-agent-row');
      const dotCls = ['working', 'deployed'].includes(a.shift_state) ? 'working'
        : a.shift_state === 'active' ? 'active' : 'idle';
      const dot = _mk('div', 'ac-agent-dot ' + dotCls);
      const name = _mk('span', 'ac-agent-name');
      name.textContent = a.display_name || a.name || '';
      row.appendChild(dot);
      row.appendChild(name);
      this.agentsEl.appendChild(row);
    });
  }

  _renderPlatform(platform) {
    if (!this.platformEl) return;
    this.platformEl.textContent = '';
    Object.entries(platform).forEach(([key, val]) => {
      const row = _mk('div', 'ac-health-row');
      const label = _mk('span');
      label.textContent = key.toUpperCase();
      const dotCls = val === 'healthy' ? 'healthy'
        : String(val).startsWith('error') ? 'error' : 'warning';
      const dot = _mk('div', 'ac-health-dot ' + dotCls);
      row.appendChild(label);
      row.appendChild(dot);
      this.platformEl.appendChild(row);
    });
  }

  _renderRepairBay(count) {
    if (!this.repairBayEl) return;
    this.repairBayEl.textContent = '';
    const row = _mk('div', 'ac-repair-bay-row');
    row.title = 'Open Repair Bay';
    const icon = _mk('span');
    icon.textContent = count > 0 ? '⧳' : '●';
    icon.style.color = count > 0 ? '#ffc800' : '#00ff88';
    icon.style.marginRight = '4px';
    const label = _mk('span');
    label.textContent = `${count} proposal${count !== 1 ? 's' : ''} pending`;
    row.appendChild(icon);
    row.appendChild(label);
    row.addEventListener('click', () => {
      window.open('http://192.168.1.200:3000/tools/repair-bay', '_blank');
    });
    this.repairBayEl.appendChild(row);
  }
}

/* ── FocusMode ──────────────────────────────────────────── */
class FocusMode {
  constructor({ layoutEl, toggleEl }) {
    this.layoutEl = layoutEl;
    this.toggleEl = toggleEl;
    this.focused = localStorage.getItem('ac-focus-mode') === 'true';
    this._apply();
    toggleEl.addEventListener('click', () => this.toggle());
  }
  toggle() {
    this.focused = !this.focused;
    localStorage.setItem('ac-focus-mode', this.focused);
    this._apply();
  }
  _apply() {
    this.layoutEl.classList.toggle('focus-mode', this.focused);
    this.toggleEl.title = this.focused ? 'Exit Focus Mode' : 'Focus Mode';
    this.toggleEl.textContent = this.focused ? '⊞' : '⊟';
  }
}

/* ── TerminalDrawer ─────────────────────────────────────── */
class TerminalDrawer {
  constructor({ overlayEl, drawerEl, iframeEl, statusDotEl, closeBtn, triggerBtn }) {
    this.overlayEl = overlayEl;
    this.drawerEl = drawerEl;
    this.iframeEl = iframeEl;
    this.statusDotEl = statusDotEl;
    this._open = false;
    this._pollTimer = null;
    this._lastSnapshot = null;
    this._loaded = false;

    overlayEl.addEventListener('click', () => this.close());
    closeBtn.addEventListener('click', () => this.close());
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && this._open) this.close(); });
    if (triggerBtn) triggerBtn.addEventListener('click', () => this.open());

    iframeEl.addEventListener('load', () => {
      this._loaded = true;
      if (this.statusDotEl) this.statusDotEl.classList.add('connected');
    });
    iframeEl.addEventListener('error', () => {
      if (this.statusDotEl) this.statusDotEl.classList.remove('connected');
    });
  }

  isOpen() { return this._open; }

  getSnapshot() {
    if (!this._lastSnapshot) return null;
    return this._lastSnapshot.join('\n');
  }

  async open() {
    if (this._open) return;
    this._open = true;
    this.overlayEl.classList.add('open');
    this.drawerEl.classList.add('open');
    document.body.style.overflow = 'hidden';

    if (!this._loaded && this.iframeEl.dataset.src) {
      await this._loadIframe();
    }

    this._pollSnapshot();
    this._pollTimer = setInterval(() => this._pollSnapshot(), 5000);
  }

  close() {
    if (!this._open) return;
    this._open = false;
    this.overlayEl.classList.remove('open');
    this.drawerEl.classList.remove('open');
    document.body.style.overflow = '';

    if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null; }
  }

  async _loadIframe() {
    try {
      const resp = await fetch('/api/terminal/token', { method: 'POST' });
      if (!resp.ok) { console.error('TerminalDrawer: token mint failed', resp.status); return; }
      const data = await resp.json();
      this.iframeEl.src = data.url;
    } catch (e) { console.error('TerminalDrawer._loadIframe:', e); }
  }

  async _pollSnapshot() {
    try {
      const resp = await fetch('/api/terminal/snapshot');
      if (!resp.ok) return;
      const data = await resp.json();
      this._lastSnapshot = data.lines || [];
    } catch (_) {}
  }
}

/* ── Delegation helpers ─────────────────────────────────────── */

const _DELEGATE_KEYWORD_MAP = [
  [/health|healthy|vps|platform|status/i, 'health_check'],
  [/\bqa\b|test suite|suite|probe/i, 'run_qa_suite'],
  [/dep.*drift|drift|dependency/i, 'check_dep_drift'],
  [/misroute|rout(e|ing)/i, 'run_misroute_audit'],
  [/review|code|forge/i, 'code_review'],
  [/doc(umentation|s)?/i, 'documentation'],
  [/analyz|intel|watch/i, 'analyze'],
  [/secur|vigil/i, 'security'],
  [/summar/i, 'summarize'],
  [/research|darwin/i, 'research'],
];

function _parseDelegateCommand(text) {
  const structuredMatch = text.match(/capability=([^\s"]+)/i);
  const reasonMatch = text.match(/reason="([^"]+)"|reason=([^\s]+)/i);
  if (structuredMatch) {
    return {
      capability: structuredMatch[1],
      reason: reasonMatch ? (reasonMatch[1] || reasonMatch[2]) : text,
    };
  }
  for (const [pattern, capability] of _DELEGATE_KEYWORD_MAP) {
    if (pattern.test(text)) return { capability, reason: text };
  }
  return { capability: 'general', reason: text };
}

/* ── DelegationCard ─────────────────────────────────────────── */
class DelegationCard {
  constructor({ messageListEl, taskId, capability, reason }) {
    this.messageListEl = messageListEl;
    this.taskId = taskId;
    this.capability = capability;
    this._startedAt = Date.now();
    this._pollTimer = null;
    this._el = this._render(reason, 'pending');
    messageListEl.appendChild(this._el);
    this.startPolling();
  }

  startPolling() {
    let polls = 0;
    const MAX_POLLS = 20;
    this._pollTimer = setInterval(async () => {
      polls++;
      try {
        const resp = await fetch(`/api/delegation/${this.taskId}/status`);
        if (!resp.ok) return;
        const data = await resp.json();
        this._update(data.status, data.work_notes);
        if (['completed', 'blocked', 'failed'].includes(data.status)) {
          clearInterval(this._pollTimer);
        }
      } catch (_) {}
      if (polls >= MAX_POLLS) {
        clearInterval(this._pollTimer);
        this._update('blocked', 'Timed out — check Dev HQ for results.');
      }
    }, 5000);
  }

  _render(reason, status) {
    const card = _mk('div', `ac-delegation-card ${status}`);
    const header = _mk('div', 'ac-delegation-header');

    const icon = _mk('span', 'ac-delegation-status-icon');
    icon.textContent = status === 'done' ? '✓' : status === 'blocked' ? '✗' : '⟳';

    const cap = _mk('span', 'ac-delegation-capability');
    cap.textContent = this.capability;

    const state = _mk('span', 'ac-delegation-state');
    state.textContent = status;

    const dur = _mk('span', 'ac-delegation-duration');
    dur.id = `ac-del-dur-${this.taskId}`;

    header.appendChild(icon);
    header.appendChild(cap);
    header.appendChild(state);
    header.appendChild(dur);

    const reasonEl = _mk('div', 'ac-delegation-reason');
    reasonEl.textContent = reason;

    const result = _mk('div', 'ac-delegation-result');
    result.id = `ac-del-result-${this.taskId}`;

    card.appendChild(header);
    card.appendChild(reasonEl);
    card.appendChild(result);
    return card;
  }

  _update(status, workNotes) {
    const cssStatus = status === 'completed' ? 'done'
      : (status === 'blocked' || status === 'failed') ? 'blocked' : 'pending';
    this._el.className = `ac-delegation-card ${cssStatus}`;

    const icon = this._el.querySelector('.ac-delegation-status-icon');
    const state = this._el.querySelector('.ac-delegation-state');
    if (icon) icon.textContent = cssStatus === 'done' ? '✓' : cssStatus === 'blocked' ? '✗' : '⟳';
    if (state) state.textContent = status;

    const dur = document.getElementById(`ac-del-dur-${this.taskId}`);
    if (dur && cssStatus !== 'pending') {
      const secs = Math.round((Date.now() - this._startedAt) / 1000);
      dur.textContent = ` [${secs}s]`;
    }

    const resultEl = document.getElementById(`ac-del-result-${this.taskId}`);
    if (resultEl && workNotes) {
      resultEl.textContent = workNotes.length > 200
        ? workNotes.slice(0, 200) + '…' : workNotes;
    }
  }
}

/* ── Boot ───────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  const layout = document.getElementById('ac-layout');
  if (!layout) return;

  let sessions, stream, terminalDrawer;
  stream = new MessageStream({
    messageListEl: document.getElementById('ac-message-list'),
    inputEl: document.getElementById('ac-input'),
    sendBtn: document.getElementById('ac-send-btn'),
    jumpBtn: document.getElementById('ac-jump-latest'),
    onConvCreated: id => sessions && sessions.markActive(id),
  });
  sessions = new SessionManager({
    listEl: document.getElementById('ac-session-list'),
    onSelect: id => stream.loadHistory(id),
  });

  // ── History tab (#4263) ─────────────────────────────────
  // Full conversation archive (incl. archived). Lazy-loaded when the History tab
  // opens; click an entry to open it in the Chat tab. Security: textContent only.
  const historyListEl = document.getElementById('ac-history-list');
  const historySearchEl = document.getElementById('ac-history-search');
  let _historyCache = [];

  const _fmtHistDate = (s) => {
    if (!s) return '';
    try {
      return new Date(s).toLocaleString([], {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      });
    } catch (e) { return ''; }
  };

  function _renderHistory(list) {
    if (!historyListEl) return;
    historyListEl.textContent = '';
    if (!list.length) {
      const empty = _mk('div', 'ac-history-empty');
      empty.textContent = 'No conversations found.';
      historyListEl.appendChild(empty);
      return;
    }
    list.forEach(c => {
      const item = _mk('div', 'ac-history-item');
      const title = _mk('div', 'ac-history-title');
      title.textContent = c.title || c.first_msg || c.topic || 'Conversation';
      const meta = _mk('div', 'ac-history-meta');
      const n = c.msg_count || 0;
      meta.textContent = n + (n === 1 ? ' msg' : ' msgs') + ' · ' +
        _fmtHistDate(c.updated_at) + (c.status === 'archived' ? ' · archived' : '');
      item.appendChild(title);
      item.appendChild(meta);
      item.addEventListener('click', () => {
        if (window.lcarsHeaderSwitchTab) window.lcarsHeaderSwitchTab('chat');
        stream.loadHistory(c.id);
        if (sessions) sessions.markActive(c.id);
      });
      historyListEl.appendChild(item);
    });
  }

  function _applyHistoryFilter() {
    const q = ((historySearchEl && historySearchEl.value) || '').trim().toLowerCase();
    const filtered = !q ? _historyCache : _historyCache.filter(c =>
      ((c.title || '') + ' ' + (c.first_msg || '') + ' ' + (c.topic || ''))
        .toLowerCase().indexOf(q) >= 0);
    _renderHistory(filtered);
  }

  async function loadHistoryList() {
    if (!historyListEl) return;
    try {
      const resp = await fetch('/api/chat/history');
      if (!resp.ok) return;
      const data = await resp.json();
      _historyCache = data.conversations || [];
      _applyHistoryFilter();
    } catch (e) { console.error('loadHistoryList:', e); }
  }

  if (historySearchEl) historySearchEl.addEventListener('input', _applyHistoryFilter);

  // Lazy-load the history list when the History tab is opened (preserve any prior hook).
  const _prevTabSwitch = window.onLcarsTabSwitch;
  window.onLcarsTabSwitch = function (tabId) {
    if (typeof _prevTabSwitch === 'function') { try { _prevTabSwitch(tabId); } catch (e) {} }
    if (tabId === 'history') loadHistoryList();
  };

  const status = new StatusPanel({
    agentsEl: document.getElementById('ac-agents'),
    platformEl: document.getElementById('ac-platform'),
    repairBayEl: document.getElementById('ac-repair-bay'),
  });

  new FocusMode({
    layoutEl: layout,
    toggleEl: document.getElementById('ac-focus-toggle'),
  });

  const overlayEl = document.getElementById('ac-terminal-overlay');
  const drawerEl = document.getElementById('ac-terminal-drawer');
  if (overlayEl && drawerEl) {
    terminalDrawer = new TerminalDrawer({
      overlayEl,
      drawerEl,
      iframeEl: document.getElementById('ac-terminal-iframe'),
      statusDotEl: document.querySelector('.ac-terminal-status-dot'),
      closeBtn: document.getElementById('ac-terminal-close'),
      triggerBtn: document.querySelector('.ac-terminal-trigger'),
    });
  }

  function _fireCodingDelegation(capability, reason) {
    const wrap = _mk('div', 'ac-message inbound');
    const bubble = _mk('div', 'ac-message-bubble');
    const cmdLabel = capability === 'run_qa_suite' ? '/test'
      : '/' + capability.replace('_', ' ');
    bubble.textContent = reason !== capability ? `${cmdLabel} ${reason}` : cmdLabel;
    const meta = _mk('div', 'ac-message-meta');
    meta.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    wrap.appendChild(bubble);
    wrap.appendChild(meta);
    stream.messageListEl.appendChild(wrap);
    fetch('/api/delegation/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ capability, reason }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.task_id) {
          new DelegationCard({
            messageListEl: stream.messageListEl,
            taskId: data.task_id,
            capability: data.capability || capability,
            reason: data.reason || reason,
          });
          stream._scrollToBottom();
        }
      })
      .catch(e => console.error('coding shortcut failed:', e));
  }

  const doSend = () => {
    const input = document.getElementById('ac-input');
    const msg = input.value.trim();
    if (!msg || input.disabled) return;

    // /plan — feature planning
    if (msg.startsWith('/plan ') || msg === '/plan') {
      input.value = '';
      input.style.height = 'auto';
      const feature = msg.slice('/plan'.length).trim();
      if (!feature) return;
      stream.send(feature, null, true);
      return;
    }

    // Coding shortcuts
    const _INSTANT = { '/test': 'run_qa_suite' };
    const _PREFIX = { '/review ': 'code_review', '/debug ': 'debug' };

    for (const [cmd, cap] of Object.entries(_INSTANT)) {
      if (msg === cmd) {
        input.value = ''; input.style.height = 'auto';
        _fireCodingDelegation(cap, cap); return;
      }
    }
    for (const [prefix, cap] of Object.entries(_PREFIX)) {
      if (msg.startsWith(prefix)) {
        input.value = ''; input.style.height = 'auto';
        _fireCodingDelegation(cap, msg.slice(prefix.length).trim() || cap); return;
      }
    }

    // /delegate command — bypass ARCHIE's LLM entirely
    if (msg.startsWith('/delegate ') || msg === '/delegate') {
      input.value = '';
      input.style.height = 'auto';
      const cmdText = msg.slice('/delegate'.length).trim();
      if (!cmdText) return;
      const { capability, reason } = _parseDelegateCommand(cmdText);
      const wrap = _mk('div', 'ac-message inbound');
      const bubble = _mk('div', 'ac-message-bubble');
      bubble.textContent = msg;
      const meta = _mk('div', 'ac-message-meta');
      meta.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      wrap.appendChild(bubble);
      wrap.appendChild(meta);
      stream.messageListEl.appendChild(wrap);
      fetch('/api/delegation/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ capability, reason }),
      })
        .then(r => r.json())
        .then(data => {
          if (data.task_id) {
            new DelegationCard({
              messageListEl: stream.messageListEl,
              taskId: data.task_id,
              capability: data.capability || capability,
              reason: data.reason || reason,
            });
            stream._scrollToBottom();
          }
        })
        .catch(e => console.error('delegation submit failed:', e));
      return;
    }

    // /engine — drive the Building Machine (archie_engine) from the cockpit
    if (msg.startsWith('/engine ') || msg === '/engine') {
      input.value = ''; input.style.height = 'auto';
      const task = msg.slice('/engine'.length).trim();
      if (!task) return;
      const uw = _mk('div', 'ac-message inbound');
      const ub = _mk('div', 'ac-message-bubble'); ub.textContent = '/engine ' + task;
      const um = _mk('div', 'ac-message-meta');
      um.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      uw.appendChild(ub); uw.appendChild(um); stream.messageListEl.appendChild(uw);
      const pw = _mk('div', 'ac-message outbound');
      const pb = _mk('div', 'ac-message-bubble'); pb.textContent = '⧗ Building Machine working…';
      pw.appendChild(pb); stream.messageListEl.appendChild(pw); stream._scrollToBottom();
      fetch('/api/engine/message', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: task }),
      })
        .then(r => r.json())
        .then(d => {
          pb.textContent = d.response || '(no response)';
          if (d.dispatch_target) {
            const m2 = _mk('div', 'ac-message-meta');
            m2.textContent = 'engine · ' + d.dispatch_target + (d.intent ? ' · ' + d.intent : '');
            pw.appendChild(m2);
          }
          stream._scrollToBottom();
        })
        .catch(e => { pb.textContent = 'Building Machine error.'; console.error('engine call failed:', e); });
      return;
    }

    // Normal message
    input.value = '';
    input.style.height = 'auto';
    stream.send(msg, terminalDrawer && terminalDrawer.isOpen() ? terminalDrawer.getSnapshot() : null);
  };

  document.getElementById('ac-send-btn').addEventListener('click', doSend);
  document.getElementById('ac-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
  });
  document.getElementById('ac-input').addEventListener('input', e => {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  });
  document.getElementById('ac-new-session').addEventListener('click', () => sessions.createNew());

  sessions.load();
  status.start();

  document.querySelectorAll('.ac-quick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const cmd = btn.dataset.cmd;
      const inp = document.getElementById('ac-input');
      if (!cmd) return;
      if (cmd === '/test') {
        inp.value = '/test';
        doSend();
      } else {
        inp.value = cmd;
        inp.focus();
        inp.setSelectionRange(inp.value.length, inp.value.length);
      }
    });
  });
});

/* ── Live Dispatch Feed (Phase 2) — watch the agent team + Claude/Codex work.
   Self-contained: polls /api/dispatch/feed every 10s, renders into
   #ac-dispatch-feed. All textContent (XSS-safe). ── */
(function () {
  var el = document.getElementById('ac-dispatch-feed');
  if (!el) return;
  function fmtDur(ms) {
    if (ms == null) return '';
    return ms < 1000 ? ms + 'ms' : (ms / 1000).toFixed(1) + 's';
  }
  // SECURITY: every value below is written via element.textContent — the
  // XSS-safe DOM sink that never parses HTML (no innerHTML anywhere here).
  // clamp() is purely a layout guard (truncate over-long fields), NOT a
  // sanitizer — textContent already neutralizes any markup.
  function clamp(v, n) {
    var s = v == null ? '' : String(v);
    return s.length > n ? s.slice(0, n - 1) + '…' : s;
  }
  function render(feed) {
    el.textContent = '';
    if (!feed || !feed.length) {
      var e = document.createElement('div');
      e.className = 'ac-feed-row';
      e.style.color = '#556677';
      e.textContent = 'No recent activity';
      el.appendChild(e);
      return;
    }
    feed.forEach(function (f) {
      var cls = 'ac-feed-row';
      if (f.origin === 'claude') cls += ' claude';
      else if (f.origin === 'codex') cls += ' codex';
      if (!f.success) cls += ' fail';
      var row = document.createElement('div');
      row.className = cls;
      var dot = document.createElement('span');
      dot.className = 'ac-feed-dot' + (f.success ? '' : ' fail');
      row.appendChild(dot);
      var main = document.createElement('div');
      main.className = 'ac-feed-main';
      var top = document.createElement('div');
      top.className = 'ac-feed-top';
      var ag = document.createElement('span');
      ag.className = 'ac-feed-agent';
      ag.textContent = clamp(f.agent || '?', 24);
      top.appendChild(ag);
      var cap = document.createElement('span');
      cap.className = 'ac-feed-cap';
      cap.textContent = clamp(f.capability || '', 32);
      top.appendChild(cap);
      main.appendChild(top);
      var sub = document.createElement('div');
      sub.className = 'ac-feed-sub';
      sub.textContent = [clamp(f.model, 18), fmtDur(f.duration_ms), clamp(f.module, 18)]
        .filter(Boolean)
        .join(' · ');
      main.appendChild(sub);
      row.appendChild(main);
      el.appendChild(row);
    });
  }
  function poll() {
    fetch('/api/dispatch/feed')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) render(d.feed || []); })
      .catch(function () {});
  }
  poll();
  setInterval(poll, 10000);
})();

/* ── Building Machine status (Phase 3) — polls /api/engine/status into the
   right-rail "Building Machine" card. textContent (XSS-safe). ── */
(function () {
  var el = document.getElementById('ac-engine-status');
  if (!el) return;
  function render(d) {
    el.textContent = '';
    var row = document.createElement('div');
    row.className = 'ac-engine-row';
    var dot = document.createElement('span');
    dot.className = 'ac-engine-dot' + (d && d.online ? ' on' : ' off');
    row.appendChild(dot);
    var label = document.createElement('span');
    label.className = 'ac-engine-label';
    label.textContent = d && d.online ? ('online · hub ' + (d.hub_status || '?')) : 'offline';
    row.appendChild(label);
    el.appendChild(row);
    if (d && d.skills && d.skills.length) {
      var s = document.createElement('div');
      s.className = 'ac-engine-skills';
      s.textContent = d.skills.length + ' skills: ' + d.skills.slice(0, 6).join(', ');
      el.appendChild(s);
    }
  }
  function poll() {
    fetch('/api/engine/status')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) render(d); })
      .catch(function () {});
  }
  poll();
  setInterval(poll, 15000);
})();
