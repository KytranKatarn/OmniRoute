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
    message = (message || '').trim();
    if (!message && !_pendingAttachment) return;
    // Crew switcher (COO consult): an explicit target prefixes the message so her {{CONSULT}}
    // rail routes to that department director; reset to A.R.C.H.I.E. after.
    const _crewSel = document.getElementById('ac-crew-switcher');
    if (_crewSel && _crewSel.value && message) {
      message = 'Consult ' + _crewSel.value + ': ' + message;
      _crewSel.value = '';
    }
    const att = _consumePendingAttachment();
    if (!message && att) message = 'Please take a look at this attachment.';
    this.inputEl.disabled = true;
    this.sendBtn.disabled = true;

    this._appendBubble('inbound', message, att ? ('📎 ' + att.filename) : '');
    this._scrollToBottom();
    this._streamingBubble = this._appendBubble('outbound', '', '');
    this._streamingBubble.querySelector('.ac-message-bubble').classList.add('ac-streaming-cursor');
    _setPresence('thinking');   // she's working on the reply -> header ring pulses

    try {
      const resp = await fetch('/api/chat/send_message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: att ? (att.block + message) : message,
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
            } else if (evt.type === 'approvals_list') {
              const items = evt.approvals || [];
              const wrap = _mk('div', 'ac-approvals-inline');
              const head = _mk('div', 'ac-approvals-inline-head');
              head.textContent = items.length ? ('Pending approvals (' + items.length + ')') : 'No pending approvals';
              wrap.appendChild(head);
              items.forEach(a => wrap.appendChild(_renderApprovalCard(a)));
              this.messageListEl.appendChild(wrap);
              if (!this._userScrolled) this._scrollToBottom();
            } else if (evt.type === 'approval_done') {
              this._appendToken('\n[' + (evt.verb === 'approve' ? 'Approved' : 'Denied') + ' ' + evt.approval_id + ': ' + (evt.ok ? 'done' : 'failed') + ']');
              loadApprovals();
            } else if (evt.type === 'token') {
              this._appendToken(evt.content);
              if (!this._userScrolled) this._scrollToBottom();
            } else if (evt.type === 'done') {
              const bubbleWrap = this._streamingBubble;   // capture before _finaliseStream nulls it
              const _replyText = (bubbleWrap
                ? bubbleWrap.querySelector('.ac-message-bubble').textContent : '').trim();
              this._finaliseStream();
              // attribution badge: who answered (⟨agent · model⟩), when both are present
              if (bubbleWrap && evt.agent_name && evt.model_used) {
                const meta = bubbleWrap.querySelector('.ac-message-meta');
                if (meta) {
                  const badge = _mk('span', 'ac-attrib');
                  badge.textContent = '⟨' + evt.agent_name + ' · ' + evt.model_used + '⟩';
                  meta.appendChild(badge);
                }
              }
              if (evt.conversation_id && !this.currentConvId) {
                this.currentConvId = evt.conversation_id;
                if (this.onConvCreated) this.onConvCreated(evt.conversation_id);
              }
              if (_voiceOn && _replyText) _speak(_replyText);   // she speaks (sets speaking -> idle)
              else _setPresence('idle');                        // otherwise back to idle
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
/* ── Approvals panel (COO Cockpit Slice 1) ──────────────────── */
// display_name + reason arrive pre-formatted from the platform (_code_fix_label,
// PR #2205). All text via textContent — XSS-safe. Approve/Deny are fail-CLOSED:
// the card is only removed on a real ok, otherwise it stays and flags an error.
function _renderApprovalCard(a) {
  const el = _mk('div', 'ac-approval-card');
  el.dataset.id = a.id;
  const title = _mk('div', 'ac-approval-title');
  title.textContent = a.display_name || a.action_type || a.id;
  const reason = _mk('div', 'ac-approval-reason');
  reason.textContent = a.reason || '';
  const btns = _mk('div', 'ac-approval-btns');
  const ok = _mk('button', 'ac-approval-approve');
  ok.type = 'button';
  ok.textContent = 'Approve';
  ok.addEventListener('click', () => _actApproval(a.id, 'approve', el));
  const no = _mk('button', 'ac-approval-deny');
  no.type = 'button';
  no.textContent = 'Deny';
  no.addEventListener('click', () => _actApproval(a.id, 'deny', el));
  btns.appendChild(ok);
  btns.appendChild(no);
  el.appendChild(title);
  el.appendChild(reason);
  el.appendChild(btns);
  return el;
}

async function loadMail() {
  // Mail HQ tab (COO command surface, Slice 3): owner/business inbox. XSS-safe (_mk+textContent).
  const listEl = document.getElementById('ac-mail-list');
  const readEl = document.getElementById('ac-mail-read');
  if (!listEl || !readEl) return;
  try {
    const r = await fetch('/api/mail/inbox?limit=40', { credentials: 'same-origin' });
    const d = r.ok ? await r.json() : { messages: [] };
    listEl.textContent = '';
    const msgs = Array.isArray(d.messages) ? d.messages : [];
    if (!msgs.length) { listEl.textContent = 'Inbox is empty (owner/business mailboxes).'; return; }
    msgs.forEach((m) => {
      const row = _mk('div', 'ac-mail-row' + (m.is_read ? '' : ' ac-mail-unread'));
      const pri = _mk('span', 'ac-mail-pri ac-mail-pri-' + (m.ai_priority || 'info'));
      pri.textContent = (m.ai_priority || 'info');
      const from = _mk('span', 'ac-mail-from'); from.textContent = m.from_address || '';
      const subj = _mk('div', 'ac-mail-subj'); subj.textContent = m.subject || '(no subject)';
      const prev = _mk('div', 'ac-mail-prev'); prev.textContent = m.body_preview || '';
      row.appendChild(pri); row.appendChild(from); row.appendChild(subj); row.appendChild(prev);
      row.addEventListener('click', () => _openMail(m.id));
      listEl.appendChild(row);
    });
  } catch (e) { listEl.textContent = 'Mail unavailable right now.'; }
}

async function _openMail(id) {
  const readEl = document.getElementById('ac-mail-read');
  if (!readEl) return;
  readEl.textContent = 'Loading message…';
  try {
    const r = await fetch('/api/mail/message/' + id, { credentials: 'same-origin' });
    const d = await r.json();
    const m = d && d.message;
    if (!m) { readEl.textContent = 'Message unavailable.'; return; }
    readEl.textContent = '';
    const h = _mk('div', 'ac-mail-read-head');
    h.textContent = (m.from_address || '') + '  —  ' + (m.subject || '');
    const body = _mk('div', 'ac-mail-read-body'); body.textContent = m.body_text || m.body_preview || '';
    const actions = _mk('div', 'ac-mail-actions');
    const draftBtn = _mk('button', 'ac-mail-btn'); draftBtn.textContent = '✍ Draft reply (R.E.S.O.L.V.E.)';
    const ta = _mk('textarea', 'ac-mail-reply'); ta.placeholder = 'Reply… (Queue sends it via the Approvals gate)';
    const queueBtn = _mk('button', 'ac-mail-btn'); queueBtn.textContent = '↗ Queue for send (gated)';
    const note = _mk('div', 'ac-mail-note');
    draftBtn.addEventListener('click', async () => {
      draftBtn.disabled = true; note.textContent = 'R.E.S.O.L.V.E. is drafting…';
      try {
        const rr = await fetch('/api/mail/draft-reply', { method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message_id: id }) });
        const dd = await rr.json();
        if (dd && dd.draft) { ta.value = dd.draft; note.textContent = 'Draft ready — edit, then Queue.'; }
        else note.textContent = 'Could not draft right now.';
      } catch (e) { note.textContent = 'Draft failed.'; }
      draftBtn.disabled = false;
    });
    queueBtn.addEventListener('click', async () => {
      if (!ta.value.trim()) { note.textContent = 'Write or draft a reply first.'; return; }
      queueBtn.disabled = true;
      try {
        const rr = await fetch('/api/mail/queue-reply', { method: 'POST', credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message_id: id, body: ta.value }) });
        const dd = await rr.json();
        note.textContent = (dd && dd.queued) ? '✓ Queued — approve it in the Approvals panel or Telegram to send.'
          : 'Could not queue the reply.';
      } catch (e) { note.textContent = 'Queue failed.'; }
      queueBtn.disabled = false;
    });
    actions.appendChild(draftBtn); actions.appendChild(queueBtn);
    readEl.appendChild(h); readEl.appendChild(body); readEl.appendChild(actions);
    readEl.appendChild(ta); readEl.appendChild(note);
  } catch (e) { readEl.textContent = 'Message unavailable.'; }
}

async function loadComs() {
  // COMs tab (COO command surface, Slice 2): Telegram ops feed + config/migration header.
  // XSS-safe by construction — every dynamic value is written via _mk + textContent (never
  // innerHTML), which the browser renders as inert text, so feed content needs no HTML sanitization.
  const header = document.getElementById('ac-coms-header');
  const feed = document.getElementById('ac-coms-feed');
  if (!header || !feed) return;
  try {
    const r = await fetch('/api/coms/overview?limit=60', { credentials: 'same-origin' });
    const d = r.ok ? await r.json() : { messages: [], config: {}, migration: {} };
    header.textContent = '';
    const status = _mk('span', 'ac-coms-status');
    status.textContent = d.config && d.config.bot_token_set ? '● Telegram connected' : '○ Telegram not configured';
    header.appendChild(status);
    if (d.migration && d.migration.progress) {
      const mig = _mk('span', 'ac-coms-mig');
      mig.textContent = '  ·  ' + (d.migration.progress.migrated || 0) + '/' + (d.migration.progress.total || 0) +
        ' senders migrated (' + (d.migration.progress.percentage || 0) + '%)';
      header.appendChild(mig);
    }
    feed.textContent = '';
    const msgs = Array.isArray(d.messages) ? d.messages : [];
    if (!msgs.length) {
      const empty = _mk('div', 'ac-coms-empty');
      empty.textContent = 'No Telegram messages logged yet.';
      feed.appendChild(empty);
      return;
    }
    msgs.forEach((m) => {
      const row = _mk('div', 'ac-coms-row');
      const meta = _mk('div', 'ac-coms-meta');
      meta.textContent = (m.source_agent || m.source_module || 'system') + ' · ' + (m.category || '') +
        ' · ' + (m.status || '');
      const body = _mk('div', 'ac-coms-body');
      body.textContent = m.title ? (m.title + ' — ' + (m.message || '')) : (m.message || '');
      const time = _mk('div', 'ac-coms-time');
      time.textContent = m.created_at || '';
      row.appendChild(meta);
      row.appendChild(body);
      row.appendChild(time);
      feed.appendChild(row);
    });
  } catch (e) {
    header.textContent = 'COMs unavailable right now.';
  }
}


async function loadApprovals() {
  const listEl = document.getElementById('ac-approvals-list');
  const countEl = document.getElementById('ac-approvals-count');
  if (!listEl) return;
  try {
    const r = await fetch('/api/approvals/pending');
    if (!r.ok) return;
    const data = await r.json();
    const approvals = data.approvals || [];
    listEl.textContent = '';
    if (!approvals.length) {
      const empty = _mk('div', 'ac-approvals-empty');
      empty.textContent = 'No pending approvals';
      listEl.appendChild(empty);
    } else {
      approvals.forEach(a => listEl.appendChild(_renderApprovalCard(a)));
    }
    if (countEl) countEl.textContent = approvals.length;
  } catch (_) { /* fail-soft: leave the last-rendered panel in place */ }
}

async function _actApproval(id, verb, el) {
  el.classList.remove('ac-error');
  el.classList.add('ac-busy');
  try {
    const r = await fetch(`/api/approvals/${encodeURIComponent(id)}/${verb}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    const out = await r.json().catch(() => ({}));
    if (r.ok && out.ok) {
      el.remove();          // only clear the card on a REAL success
      loadApprovals();      // refresh the right-rail count
    } else {
      el.classList.remove('ac-busy');
      el.classList.add('ac-error');   // fail-CLOSED: card stays pending
    }
  } catch (_) {
    el.classList.remove('ac-busy');
    el.classList.add('ac-error');
  }
}

/* ── Attachments (COO Cockpit Slice 2) ──────────────────────── */
// The pending attachment's `block` is prepended to the outgoing message so it
// rides the DHQ prompt; the bubble shows the typed text + a "📎 filename" meta.
let _pendingAttachment = null;   // { block, filename, chars, truncated }

function _showAttachChip(a) {
  const chip = document.getElementById('ac-attach-chip');
  if (!chip) return;
  chip.textContent = '';
  const label = _mk('span', 'ac-attach-chip-label');
  label.textContent = '📎 ' + a.filename + (a.chars ? ' (' + a.chars + ' chars' + (a.truncated ? ', truncated' : '') + ')' : '');
  const x = _mk('button', 'ac-attach-chip-x'); x.type = 'button'; x.textContent = '×';
  x.addEventListener('click', () => {
    _pendingAttachment = null; chip.style.display = 'none'; chip.textContent = '';
  });
  chip.appendChild(label); chip.appendChild(x);
  chip.style.display = 'flex';
}

async function _onAttachSelected(ev) {
  const file = ev.target.files && ev.target.files[0];
  ev.target.value = '';               // allow re-selecting the same file
  if (!file) return;
  const chip = document.getElementById('ac-attach-chip');
  if (chip) { chip.style.display = 'flex'; chip.textContent = 'Reading ' + file.name + '…'; }
  try {
    const fd = new FormData(); fd.append('file', file);
    const r = await fetch('/api/chat/attach', { method: 'POST', body: fd });
    const out = await r.json().catch(() => ({}));
    if (r.ok && out.ok) { _pendingAttachment = out; _showAttachChip(out); }
    else { _pendingAttachment = null; if (chip) chip.textContent = out.error || 'Could not attach file'; }
  } catch (_) {
    _pendingAttachment = null; if (chip) chip.textContent = 'Could not attach file';
  }
}

// consume + clear the pending attachment; returns the object or null
function _consumePendingAttachment() {
  const a = _pendingAttachment; _pendingAttachment = null;
  const chip = document.getElementById('ac-attach-chip');
  if (chip) { chip.style.display = 'none'; chip.textContent = ''; }
  return a;
}

/* ── Voice: TTS playback + mic STT (COO Cockpit Slice 3) ───── */
// Voice is fail-SOFT everywhere: TTS failure -> no audio (text stays); mic
// denied/STT failure -> no transcript (owner types). Audio never leaves the
// cluster (whisper is hub-local). She speaks in her canonical Kokoro voice.
let _voiceOn = false;
let _mediaRecorder = null;
let _audioChunks = [];

function _setPresence(state) {
  // idle | thinking | speaking | listening -> body + avatar ring + header label
  document.body.dataset.presence = state;
  const av = document.getElementById('ac-avatar');
  if (av) av.dataset.presence = state;
  const label = document.getElementById('ac-presence-label');
  if (label) {
    label.textContent = ({ idle: 'online', thinking: 'thinking…', speaking: 'speaking…', listening: 'listening…' })[state] || 'online';
  }
  const vt = document.getElementById('ac-voice-toggle');
  if (vt) vt.classList.toggle('ac-speaking', state === 'speaking');
}

// Load her avatar into the persona header; on any error fall back to the CSS monogram.
function _loadAvatar() {
  const img = document.getElementById('ac-avatar-img');
  const av = document.getElementById('ac-avatar');
  if (!img || !av) return;
  img.onerror = () => { av.classList.add('ac-avatar-mono-on'); img.style.display = 'none'; };
  img.onload = () => { av.classList.remove('ac-avatar-mono-on'); };
  img.src = '/api/archie/avatar?ts=' + Date.now();
}

async function _speak(text) {
  try {
    const r = await fetch('/api/voice/synthesize', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }),
    });
    const out = await r.json().catch(() => ({}));
    if (!out.success || !out.audio_base64) return;    // fail-soft: no audio, no error
    _setPresence('speaking');
    const audio = new Audio('data:audio/wav;base64,' + out.audio_base64);
    audio.onended = () => _setPresence('idle');
    audio.onerror = () => _setPresence('idle');
    audio.play().catch(() => _setPresence('idle'));
  } catch (_) { _setPresence('idle'); }
}

async function _toggleMic(btn) {
  if (_mediaRecorder && _mediaRecorder.state === 'recording') { _mediaRecorder.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _mediaRecorder = new MediaRecorder(stream);
    _audioChunks = [];
    _mediaRecorder.ondataavailable = e => { if (e.data && e.data.size) _audioChunks.push(e.data); };
    _mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      btn.classList.remove('ac-recording');
      _setPresence('idle');
      const blob = new Blob(_audioChunks, { type: 'audio/webm' });
      const fd = new FormData();
      fd.append('audio', blob, 'clip.webm');
      try {
        const r = await fetch('/api/voice/transcribe', { method: 'POST', body: fd });
        const out = await r.json().catch(() => ({}));
        if (out.text) {                     // fill the input; owner edits + sends (spec default)
          const inp = document.getElementById('ac-input');
          inp.value = (inp.value ? inp.value + ' ' : '') + out.text;
          inp.focus();
        }
      } catch (_) { /* fail-soft */ }
    };
    _mediaRecorder.start();
    btn.classList.add('ac-recording');
    _setPresence('listening');
  } catch (_) { /* mic denied -> owner types */ }
}

async function _loadCrew() {
  // Populate the crew switcher (COO consult) from the platform crew directory; fail-soft.
  try {
    const r = await fetch('/api/coo/agents', { credentials: 'same-origin' });
    if (!r.ok) return;
    const d = await r.json();
    const sel = document.getElementById('ac-crew-switcher');
    if (!sel || !Array.isArray(d.agents)) return;
    d.agents.forEach((a) => {
      if (!a || !a.name) return;
      const opt = _mk('option');
      opt.value = a.name;                                  // textContent-only -> XSS-safe
      opt.textContent = a.department ? (a.name + ' — ' + a.department) : a.name;
      sel.appendChild(opt);
    });
  } catch (_) { /* fail-soft: switcher stays A.R.C.H.I.E.-only */ }
}

async function _loadActions() {
  // Populate the Tools & Actions bar (Slice 4) from the platform's CURATED SAFE catalog.
  // Each chip fills the input with a run-request and clicks the real send button, so the
  // {{ACTION}} rail fires through the normal chat flow (result arrives as a poll follow-up).
  const bar = document.getElementById('ac-actions-bar');
  if (!bar) return;
  try {
    const r = await fetch('/api/actions/catalog', { credentials: 'same-origin' });
    if (!r.ok) return;
    const d = await r.json();
    if (!Array.isArray(d.actions)) return;
    d.actions.forEach((a) => {
      if (!a || !a.key) return;
      const chip = _mk('button', 'ac-action-chip');
      chip.type = 'button';
      chip.textContent = '⚡ ' + (a.label || a.key);   // textContent-only -> XSS-safe
      chip.title = a.description || '';
      chip.addEventListener('click', () => {
        const input = document.getElementById('ac-input');
        const send = document.getElementById('ac-send-btn');
        if (input && send) { input.value = 'Run the ' + (a.label || a.key) + ' action'; send.click(); }
      });
      bar.appendChild(chip);
    });
  } catch (_) { /* fail-soft: no action chips */ }
}

document.addEventListener('DOMContentLoaded', () => {
  const layout = document.getElementById('ac-layout');
  if (!layout) return;
  _loadAvatar();   // her face in the persona header (fail-soft -> monogram)
  _loadCrew();     // crew switcher (COO consult) -> department directors
  _loadActions();  // Tools & Actions bar (Slice 4) -> curated safe diagnostics

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
    if (tabId === 'collaboration' && window.acCollab) window.acCollab.onOpen();
    if (tabId === 'coms') loadComs();
    if (tabId === 'mail') loadMail();
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

  // Attachments: 📎 opens the file picker; a selection uploads + shows a chip.
  const _attachBtn = document.getElementById('ac-attach-btn');
  const _attachInput = document.getElementById('ac-attach-input');
  if (_attachBtn && _attachInput) {
    _attachBtn.addEventListener('click', () => _attachInput.click());
    _attachInput.addEventListener('change', _onAttachSelected);
  }

  // Voice: 🎤 mic (record -> transcribe -> fill input) + 🔊 TTS toggle (persisted).
  const _micBtn = document.getElementById('ac-mic-btn');
  if (_micBtn) _micBtn.addEventListener('click', () => _toggleMic(_micBtn));
  const _voiceToggle = document.getElementById('ac-voice-toggle');
  if (_voiceToggle) {
    _voiceOn = localStorage.getItem('ac_voice_on') === '1';
    _voiceToggle.setAttribute('aria-pressed', _voiceOn ? 'true' : 'false');
    _voiceToggle.addEventListener('click', () => {
      _voiceOn = !_voiceOn;
      localStorage.setItem('ac_voice_on', _voiceOn ? '1' : '0');
      _voiceToggle.setAttribute('aria-pressed', _voiceOn ? 'true' : 'false');
    });
  }
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

  // Approvals right-rail panel: load now + refresh every 30s.
  loadApprovals();
  setInterval(loadApprovals, 30000);

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

/* ── Collaboration tab (#4285) — Kytran + A.R.C.H.I.E. + Claude trio.
   Real-time scratchpad: POSTs to /api/collab/message (ephemeral — NOT saved to
   Chat/History). Health-gated on tab open via /api/claude/health. Exposes
   window.acCollab.onOpen() (called by the onLcarsTabSwitch wrapper).
   SECURITY: every value below is written via element.textContent — the XSS-safe
   DOM sink that never parses HTML (no innerHTML anywhere here). ── */
(function () {
  var listEl = document.getElementById('ac-collab-list');
  var inputEl = document.getElementById('ac-collab-input');
  var sendEl = document.getElementById('ac-collab-send');
  var dotEl = document.getElementById('ac-collab-dot');
  var bannerEl = document.getElementById('ac-collab-banner');
  var bannerTextEl = document.getElementById('ac-collab-banner-text');
  if (!listEl || !inputEl || !sendEl) return;

  var _online = false;
  var _busy = false;

  function _now() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  // who: 'kytran' | 'archie' | 'claude' | 'system' (+ optional ' thinking')
  function _bubble(who, label, text) {
    var wrap = _mk('div', 'ac-collab-msg ' + who);
    var name = _mk('div', 'ac-collab-name');
    name.textContent = label;
    var bub = _mk('div', 'ac-collab-bubble');
    bub.textContent = text;
    var meta = _mk('div', 'ac-collab-meta');
    meta.textContent = _now();
    wrap.appendChild(name);
    wrap.appendChild(bub);
    wrap.appendChild(meta);
    listEl.appendChild(wrap);
    listEl.scrollTop = listEl.scrollHeight;
    return wrap;
  }

  function _setBanner(state, text) {
    // state: 'online' | 'offline' | 'checking'
    if (dotEl) dotEl.className = 'ac-collab-dot ' + state;
    if (bannerEl) bannerEl.className = 'ac-collab-banner ' + state;
    if (bannerTextEl) bannerTextEl.textContent = text;
  }

  function _setEnabled(on) {
    _online = on;
    inputEl.disabled = !on;
    sendEl.disabled = !on || _busy;
  }

  function onOpen() {
    // Re-check health every time the tab opens — the proxy may come up/down.
    _setBanner('checking', 'Checking Claude bridge…');
    inputEl.disabled = true;
    sendEl.disabled = true;
    fetch('/api/claude/health')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d && d.status === 'healthy') {
          _setBanner('online', 'Claude bridge online · ' + (d.mode || 'proxy'));
          _setEnabled(true);
        } else {
          _setBanner('offline', 'Claude bridge offline — start the Claude proxy to collaborate.');
          _setEnabled(false);
        }
      })
      .catch(function () {
        _setBanner('offline', 'Claude bridge unreachable.');
        _setEnabled(false);
      });
  }

  function send() {
    var msg = inputEl.value.trim();
    if (!msg || _busy || !_online) return;
    inputEl.value = '';
    inputEl.style.height = 'auto';
    _bubble('kytran', 'Kytran', msg);

    _busy = true;
    sendEl.disabled = true;
    var thinking = _bubble('claude thinking', 'Claude', 'thinking…');

    fetch('/api/collab/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg }),
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (thinking && thinking.parentNode) thinking.parentNode.removeChild(thinking);
        if (!d || d.available === false) {
          _bubble('system', 'System', (d && d.note) || 'Claude bridge is offline.');
          _setBanner('offline', 'Claude bridge offline.');
          _setEnabled(false);
          return;
        }
        if (d.archie) _bubble('archie', 'A.R.C.H.I.E.', d.archie);
        if (d.claude) _bubble('claude', 'Claude', d.claude);
      })
      .catch(function (e) {
        if (thinking && thinking.parentNode) thinking.parentNode.removeChild(thinking);
        _bubble('system', 'System', 'Collaboration request failed — try again.');
        console.error('collab send failed:', e);
      })
      .finally(function () {
        _busy = false;
        sendEl.disabled = !_online;
      });
  }

  sendEl.addEventListener('click', send);
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  inputEl.addEventListener('input', function (e) {
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  });

  window.acCollab = { onOpen: onOpen };
})();

/* ── Skills rail (#5334) — the PLATFORM invokable-skills registry in the right rail.
   Lists the same generated registry archie-tui lists (#5333): known-tool delegates
   (no LLM) + every LLM capability in CAPABILITY_DEPARTMENT_MAP. Click dispatches
   through DHQ as delegation_source='cockpit' and polls the task row.

   Distinct from the curated {{ACTION:<key>}} rail, which is a hand-picked SAFE
   subset A.R.C.H.I.E. emits herself and runs synchronously. This one is
   user-picked and async.

   SECURITY: every value from the registry is written via textContent — the
   XSS-safe sink that never parses HTML. No innerHTML anywhere here. ── */
(function () {
  var listEl = document.getElementById('ac-skills-list');
  var filterEl = document.getElementById('ac-skills-filter');
  var statusEl = document.getElementById('ac-skills-status');
  if (!listEl || !filterEl || !statusEl) return;

  var _skills = [];
  var _loaded = false;      // a reply arrived — including an EMPTY one
  var _busy = false;
  var _pollTimer = null;
  var MAX_ROWS = 12;        // a viewport, not all 237 rows

  function _setStatus(text) { statusEl.textContent = text || ''; }

  function _visible() {
    var f = (filterEl.value || '').trim().toLowerCase();
    if (!f) return _skills;
    return _skills.filter(function (s) {
      return (s.capability || '').toLowerCase().indexOf(f) !== -1 ||
             (s.home_department || '').toLowerCase().indexOf(f) !== -1 ||
             (s.director_agent || '').toLowerCase().indexOf(f) !== -1;
    });
  }

  function render() {
    listEl.textContent = '';
    if (!_loaded) { _setStatus('Loading registry…'); return; }
    if (!_skills.length) { _setStatus('registry empty — is the hub reachable?'); return; }

    var vis = _visible();
    if (!vis.length) { _setStatus('(no match)'); return; }

    vis.slice(0, MAX_ROWS).forEach(function (s) {
      var row = document.createElement('button');
      row.type = 'button';
      row.className = 'ac-skill-row' + (s.kind === 'known_tool' ? ' tool' : '');
      row.disabled = _busy;

      var name = document.createElement('span');
      name.className = 'ac-skill-cap';
      name.textContent = s.capability;                       // XSS-safe
      row.appendChild(name);

      var owner = document.createElement('span');
      owner.className = 'ac-skill-owner';
      owner.textContent = s.kind === 'known_tool'
        ? 'no LLM'
        : (s.director_agent || s.home_department || '');      // XSS-safe
      row.appendChild(owner);

      row.title = (s.description || s.capability) + (s.kind === 'known_tool'
        ? ' — runs directly, no LLM time'
        : ' — routed via DHQ');
      row.addEventListener('click', function () { invoke(s.capability); });
      listEl.appendChild(row);
    });

    if (vis.length > MAX_ROWS) {
      var more = document.createElement('div');
      more.className = 'ac-skills-more';
      more.textContent = '… ' + (vis.length - MAX_ROWS) + ' more (type to filter)';
      listEl.appendChild(more);
    }
    if (!_busy) _setStatus(_skills.length + ' skills');
  }

  function invoke(capability) {
    if (_busy) return;
    _busy = true;
    _setStatus('dispatching ' + capability + '…');
    render();
    fetch('/api/skills/invoke', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ capability: capability })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        _busy = false;
        if (!res.ok || res.d.error) {
          _setStatus('failed: ' + (res.d.error || 'dispatch error'));
          render();
          return;
        }
        _setStatus('task #' + res.d.task_id + ' ' + (res.d.status || 'queued'));
        render();
        pollTask(res.d.task_id);
      })
      .catch(function () { _busy = false; _setStatus('dispatch failed'); render(); });
  }

  function pollTask(taskId) {
    if (!taskId) return;
    if (_pollTimer) clearInterval(_pollTimer);
    var tries = 0;
    _pollTimer = setInterval(function () {
      tries++;
      // Give up POLLING after ~2 min — the task keeps running on the cluster;
      // only the rail stops watching. Live Dispatch still shows it.
      if (tries > 40) { clearInterval(_pollTimer); _pollTimer = null; return; }
      fetch('/api/delegation/' + taskId + '/status')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d) return;
          _setStatus('task #' + taskId + ' ' + (d.status || '?'));
          if (d.status === 'completed' || d.status === 'blocked' || d.status === 'failed') {
            clearInterval(_pollTimer); _pollTimer = null;
          }
        })
        .catch(function () {});
    }, 3000);
  }

  filterEl.addEventListener('input', render);

  fetch('/api/skills')
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) {
      _loaded = true;                                  // an empty reply is still a reply
      _skills = (d && d.skills) || [];
      render();
    })
    .catch(function () { _loaded = true; _skills = []; render(); });
})();
