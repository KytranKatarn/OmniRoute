/**
 * Google Work Suite — Frontend Logic
 * IIFE, no globals except window.* helpers exposed intentionally.
 */
(function () {
  'use strict';

  const API_BASE = '/tools/google-work-suite';

  // ── State ────────────────────────────────────────────────────────────────
  let _currentAccountId = null;
  let _emails = [];
  let _currentEmail = null;
  let _rules = [];
  let _activeTab = 'inbox';
  let _currentPage = 1;
  let _totalEmails = 0;
  const PER_PAGE = 20;

  // ── Helpers ──────────────────────────────────────────────────────────────

  /**
   * Generic fetch wrapper.
   * @param {string} method
   * @param {string} path  — relative to API_BASE
   * @param {Object|null} body
   * @returns {Promise<Object>}
   */
  async function api(method, path, body) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    };
    if (body !== undefined && body !== null) {
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(API_BASE + path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || data.message || `HTTP ${res.status}`);
    }
    return data;
  }

  /** Clear all child nodes of an element. */
  function clearEl(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  /** Show a brief toast message. */
  function toast(msg, isError) {
    const el = document.getElementById('gwsToast');
    if (!el) return;
    el.textContent = msg;
    el.style.display = 'block';
    el.classList.toggle('gws-toast--error', !!isError);
    clearTimeout(el._timer);
    el._timer = setTimeout(() => { el.style.display = 'none'; }, 3500);
  }

  /** Get the current user id from the data attr set by Jinja. */
  function getCurrentUserId() {
    const wrapper = document.querySelector('.gws-wrapper');
    return wrapper ? wrapper.dataset.userId || 'me' : 'me';
  }

  // ── Account Management ───────────────────────────────────────────────────

  window.connectAccount = function (ownerType) {
    const userId = getCurrentUserId();
    window.location.href =
      API_BASE + '/oauth/authorize?owner_type=' + encodeURIComponent(ownerType) +
      '&owner_id=' + encodeURIComponent(userId);
  };

  window.loadAccounts = async function () {
    try {
      const data = await api('GET', '/api/accounts');
      const accounts = Array.isArray(data) ? data : (data.accounts || []);
      const sel = document.getElementById('gwsAccountSelect');
      if (!sel) return;
      clearEl(sel);

      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = accounts.length ? '— select account —' : '— no accounts connected —';
      sel.appendChild(placeholder);

      accounts.forEach(function (acct) {
        const opt = document.createElement('option');
        opt.value = acct.id;
        opt.textContent = acct.email || acct.name || acct.id;
        sel.appendChild(opt);
      });

      if (accounts.length > 0) {
        selectAccount(accounts[0].id);
        sel.value = accounts[0].id;
      }
    } catch (err) {
      toast('Failed to load accounts: ' + err.message, true);
    }
  };

  window.selectAccount = function (id) {
    _currentAccountId = id || null;
    if (_currentAccountId) {
      loadInbox(1);
      loadRules();
    }
  };

  // ── Inbox ─────────────────────────────────────────────────────────────────

  window.loadInbox = async function (page) {
    if (!_currentAccountId) return;
    _currentPage = page || 1;
    try {
      const data = await api('GET',
        '/api/inbox/' + encodeURIComponent(_currentAccountId) +
        '?page=' + _currentPage + '&per_page=' + PER_PAGE
      );
      _emails = Array.isArray(data) ? data : (data.emails || []);
      _totalEmails = data.total || _emails.length;
      renderEmailList();
      updatePageInfo();
    } catch (err) {
      toast('Failed to load inbox: ' + err.message, true);
    }
  };

  function updatePageInfo() {
    const el = document.getElementById('gwsPageInfo');
    if (!el) return;
    const start = (_currentPage - 1) * PER_PAGE + 1;
    const end = Math.min(_currentPage * PER_PAGE, _totalEmails);
    el.textContent = _totalEmails > 0
      ? start + '–' + end + ' of ' + _totalEmails
      : 'No messages';
  }

  window.prevPage = function () {
    if (_currentPage > 1) loadInbox(_currentPage - 1);
  };

  window.nextPage = function () {
    if (_currentPage * PER_PAGE < _totalEmails) loadInbox(_currentPage + 1);
  };

  function renderEmailList() {
    const list = document.getElementById('gwsEmailList');
    if (!list) return;
    clearEl(list);

    if (_emails.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'gws-empty-state';
      const icon = document.createElement('p');
      icon.textContent = 'Your inbox is empty.';
      empty.appendChild(icon);
      list.appendChild(empty);
      return;
    }

    _emails.forEach(function (email) {
      const item = document.createElement('div');
      item.className = 'gws-email-item' + (email.is_read ? '' : ' unread');
      item.setAttribute('role', 'listitem');
      item.setAttribute('tabindex', '0');
      item.dataset.gmailId = email.gmail_id || email.id;

      // Unread dot
      if (!email.is_read) {
        const dot = document.createElement('span');
        dot.className = 'gws-unread-dot';
        dot.setAttribute('aria-label', 'Unread');
        item.appendChild(dot);
      }

      // Main content column
      const col = document.createElement('div');
      col.className = 'gws-email-item-col';

      const top = document.createElement('div');
      top.className = 'gws-email-item-top';

      const sender = document.createElement('span');
      sender.className = 'gws-email-item-sender';
      sender.textContent = email.sender || email.from || '(unknown)';
      top.appendChild(sender);

      const time = document.createElement('span');
      time.className = 'gws-email-item-time';
      time.textContent = formatEmailDate(email.date || email.received_at);
      top.appendChild(time);
      col.appendChild(top);

      const subject = document.createElement('span');
      subject.className = 'gws-email-item-subject';
      subject.textContent = email.subject || '(no subject)';
      col.appendChild(subject);

      const snippet = document.createElement('span');
      snippet.className = 'gws-email-item-snippet';
      const raw = email.snippet || email.body_preview || '';
      snippet.textContent = raw.length > 100 ? raw.slice(0, 100) + '…' : raw;
      col.appendChild(snippet);
      item.appendChild(col);

      // Star
      if (email.is_starred) {
        const star = document.createElement('span');
        star.className = 'gws-star';
        star.textContent = '★';
        item.appendChild(star);
      }

      const gmailId = email.gmail_id || email.id;
      item.addEventListener('click', function () { viewEmail(gmailId); });
      item.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') viewEmail(gmailId);
      });

      list.appendChild(item);
    });
  }

  function formatEmailDate(raw) {
    if (!raw) return '';
    try {
      const d = new Date(raw);
      const now = new Date();
      const isSameDay =
        d.getFullYear() === now.getFullYear() &&
        d.getMonth() === now.getMonth() &&
        d.getDate() === now.getDate();
      if (isSameDay) {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      }
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    } catch (_) {
      return raw;
    }
  }

  window.viewEmail = async function (gmailId) {
    if (!_currentAccountId) return;

    // Highlight selected item
    document.querySelectorAll('.gws-email-item').forEach(function (el) {
      el.classList.toggle('selected', el.dataset.gmailId === String(gmailId));
    });

    try {
      const data = await api('GET',
        '/api/email/' + encodeURIComponent(_currentAccountId) +
        '/' + encodeURIComponent(gmailId)
      );
      _currentEmail = data;
      renderEmailDetail(data);
    } catch (err) {
      toast('Failed to load email: ' + err.message, true);
    }
  };

  function renderEmailDetail(email) {
    const panel = document.getElementById('gwsEmailDetail');
    if (!panel) return;
    clearEl(panel);

    // Header
    const header = document.createElement('div');
    header.className = 'gws-email-header';

    const subj = document.createElement('h2');
    subj.className = 'gws-email-subject';
    subj.textContent = email.subject || '(no subject)';
    header.appendChild(subj);

    const meta = document.createElement('div');
    meta.className = 'gws-email-meta';

    [
      ['From', email.sender || email.from],
      ['To', Array.isArray(email.to) ? email.to.join(', ') : (email.to || '')],
      ['Date', email.date || email.received_at],
    ].forEach(function (pair) {
      if (!pair[1]) return;
      const row = document.createElement('div');
      row.className = 'gws-email-meta-row';
      const label = document.createElement('span');
      label.className = 'gws-email-meta-label';
      label.textContent = pair[0] + ':';
      const val = document.createElement('span');
      val.className = 'gws-email-meta-val';
      val.textContent = pair[1];
      row.appendChild(label);
      row.appendChild(val);
      meta.appendChild(row);
    });
    header.appendChild(meta);
    panel.appendChild(header);

    // Body — use textContent, never innerHTML
    const body = document.createElement('div');
    body.className = 'gws-email-body';
    const pre = document.createElement('pre');
    pre.className = 'gws-email-body-text';
    pre.textContent = email.body || email.body_text || '(no content)';
    body.appendChild(pre);
    panel.appendChild(body);

    // Action buttons
    const actions = document.createElement('div');
    actions.className = 'gws-email-actions';

    const replyBtn = document.createElement('button');
    replyBtn.className = 'gws-btn gws-btn-primary';
    replyBtn.textContent = 'Reply';
    const gId = email.gmail_id || email.id;
    replyBtn.addEventListener('click', function () { openCompose(gId); });
    actions.appendChild(replyBtn);

    const fwdBtn = document.createElement('button');
    fwdBtn.className = 'gws-btn gws-btn-secondary';
    fwdBtn.textContent = 'Forward';
    fwdBtn.addEventListener('click', function () { forwardEmail(email); });
    actions.appendChild(fwdBtn);

    panel.appendChild(actions);
  }

  function forwardEmail(email) {
    openCompose(null);
    const subj = document.getElementById('gwsComposeSubject');
    const body = document.getElementById('gwsComposeBody');
    if (subj) subj.value = 'Fwd: ' + (email.subject || '');
    if (body) {
      body.value =
        '\n\n---------- Forwarded message ----------\n' +
        'From: ' + (email.sender || email.from || '') + '\n' +
        'Date: ' + (email.date || '') + '\n' +
        'Subject: ' + (email.subject || '') + '\n\n' +
        (email.body || email.body_text || '');
    }
  }

  window.syncInbox = async function () {
    if (!_currentAccountId) { toast('Select an account first.', true); return; }
    try {
      toast('Syncing…');
      await api('POST', '/api/email/sync/' + encodeURIComponent(_currentAccountId), {});
      toast('Inbox synced.');
      loadInbox(_currentPage);
    } catch (err) {
      toast('Sync failed: ' + err.message, true);
    }
  };

  // ── Compose ───────────────────────────────────────────────────────────────

  let _replyToId = null;

  window.openCompose = function (replyToId) {
    _replyToId = replyTo(replyToId);
    const modal = document.getElementById('gwsComposeModal');
    if (!modal) return;

    // Clear fields
    ['gwsComposeTo', 'gwsComposeSubject', 'gwsComposeBody'].forEach(function (id) {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });

    // Pre-fill for reply
    if (replyToId && _currentEmail) {
      const to = document.getElementById('gwsComposeTo');
      const sub = document.getElementById('gwsComposeSubject');
      const bod = document.getElementById('gwsComposeBody');
      if (to) to.value = _currentEmail.sender || _currentEmail.from || '';
      if (sub) sub.value = 'Re: ' + (_currentEmail.subject || '');
      if (bod) {
        bod.value =
          '\n\n---------- Original message ----------\n' +
          (_currentEmail.body || _currentEmail.body_text || '');
      }
    }

    modal.style.display = 'flex';
    const first = document.getElementById('gwsComposeTo');
    if (first) first.focus();
  };

  // helper — return same value (avoids closure confusion with param name)
  function replyTo(id) { return id || null; }

  window.closeCompose = function () {
    const modal = document.getElementById('gwsComposeModal');
    if (modal) modal.style.display = 'none';
    _replyToId = null;
  };

  window.sendEmail = async function (asDraft) {
    if (!_currentAccountId) { toast('Select an account first.', true); return; }
    const to = (document.getElementById('gwsComposeTo') || {}).value || '';
    const subject = (document.getElementById('gwsComposeSubject') || {}).value || '';
    const body = (document.getElementById('gwsComposeBody') || {}).value || '';

    if (!to && !asDraft) { toast('Please enter a recipient.', true); return; }

    try {
      await api('POST', '/api/email/send', {
        account_id: _currentAccountId,
        to,
        subject,
        body,
        as_draft: asDraft,
        reply_to_id: _replyToId,
      });
      closeCompose();
      toast(asDraft ? 'Draft saved.' : 'Email sent.');
    } catch (err) {
      toast('Failed to send: ' + err.message, true);
    }
  };

  // ── Tabs ──────────────────────────────────────────────────────────────────

  window.setTab = function (tab) {
    _activeTab = tab;

    const inboxPanel = document.getElementById('gwsInboxTab');
    const rulesPanel = document.getElementById('gwsRulesTab');
    const inboxBtn = document.getElementById('gwsTabInbox');
    const rulesBtn = document.getElementById('gwsTabRules');

    if (inboxPanel) inboxPanel.style.display = tab === 'inbox' ? '' : 'none';
    if (rulesPanel) rulesPanel.style.display = tab === 'rules' ? '' : 'none';

    if (inboxBtn) {
      inboxBtn.classList.toggle('active', tab === 'inbox');
      inboxBtn.setAttribute('aria-selected', String(tab === 'inbox'));
    }
    if (rulesBtn) {
      rulesBtn.classList.toggle('active', tab === 'rules');
      rulesBtn.setAttribute('aria-selected', String(tab === 'rules'));
    }

    if (tab === 'rules' && _currentAccountId) loadRules();
  };

  // ── Rules ─────────────────────────────────────────────────────────────────

  window.loadRules = async function () {
    if (!_currentAccountId) return;
    try {
      const data = await api('GET', '/api/rules/' + encodeURIComponent(_currentAccountId));
      _rules = Array.isArray(data) ? data : (data.rules || []);
      renderRuleList();
    } catch (err) {
      toast('Failed to load rules: ' + err.message, true);
    }
  };

  function renderRuleList() {
    const list = document.getElementById('gwsRuleList');
    if (!list) return;
    clearEl(list);

    if (_rules.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'gws-empty-state';
      const p = document.createElement('p');
      p.textContent = 'No rules yet. Create one to automate email handling.';
      empty.appendChild(p);
      list.appendChild(empty);
      return;
    }

    _rules.forEach(function (rule) {
      const card = document.createElement('div');
      card.className = 'gws-rule-card';

      const info = document.createElement('div');
      info.className = 'gws-rule-card-info';

      const name = document.createElement('span');
      name.className = 'gws-rule-card-name';
      name.textContent = rule.name || '(unnamed)';
      info.appendChild(name);

      const meta = document.createElement('span');
      meta.className = 'gws-rule-card-meta';
      const conds = [];
      if (rule.conditions) {
        if (rule.conditions.from) conds.push('from: ' + rule.conditions.from);
        if (rule.conditions.subject_contains) conds.push('subject: ' + rule.conditions.subject_contains);
        if (rule.conditions.body_contains) conds.push('body: ' + rule.conditions.body_contains);
      }
      meta.textContent = conds.length ? conds.join(' | ') : 'No conditions';
      info.appendChild(meta);
      card.appendChild(info);

      const acts = document.createElement('div');
      acts.className = 'gws-rule-card-actions';

      const toggle = document.createElement('button');
      toggle.className = 'gws-btn gws-btn-icon' + (rule.is_active ? ' active' : '');
      toggle.title = rule.is_active ? 'Active — click to disable' : 'Inactive — click to enable';
      toggle.textContent = rule.is_active ? 'ON' : 'OFF';
      toggle.addEventListener('click', function () { toggleRule(rule.id, !rule.is_active); });
      acts.appendChild(toggle);

      const del = document.createElement('button');
      del.className = 'gws-btn gws-btn-danger';
      del.textContent = 'Delete';
      del.addEventListener('click', function () { deleteRule(rule.id); });
      acts.appendChild(del);

      card.appendChild(acts);
      list.appendChild(card);
    });
  }

  async function toggleRule(ruleId, active) {
    if (!_currentAccountId) return;
    try {
      await api('PATCH',
        '/api/rules/' + encodeURIComponent(_currentAccountId) +
        '/' + encodeURIComponent(ruleId),
        { is_active: active }
      );
      loadRules();
    } catch (err) {
      toast('Failed to update rule: ' + err.message, true);
    }
  }

  window.openRuleModal = function () {
    const modal = document.getElementById('gwsRuleModal');
    if (!modal) return;
    ['gwsRuleName', 'gwsRuleFrom', 'gwsRuleSubject', 'gwsRuleBody',
     'gwsRuleTemplate', 'gwsRuleForward', 'gwsRuleLabel'].forEach(function (id) {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    const cb = document.getElementById('gwsRuleAutoReply');
    if (cb) cb.checked = false;
    modal.style.display = 'flex';
    const first = document.getElementById('gwsRuleName');
    if (first) first.focus();
  };

  window.closeRuleModal = function () {
    const modal = document.getElementById('gwsRuleModal');
    if (modal) modal.style.display = 'none';
  };

  window.saveRule = async function () {
    if (!_currentAccountId) { toast('Select an account first.', true); return; }

    const name = (document.getElementById('gwsRuleName') || {}).value || '';
    if (!name.trim()) { toast('Please enter a rule name.', true); return; }

    const conditions = {};
    const fromVal = (document.getElementById('gwsRuleFrom') || {}).value || '';
    const subjectVal = (document.getElementById('gwsRuleSubject') || {}).value || '';
    const bodyVal = (document.getElementById('gwsRuleBody') || {}).value || '';
    if (fromVal.trim()) conditions.from = fromVal.trim();
    if (subjectVal.trim()) conditions.subject_contains = subjectVal.trim();
    if (bodyVal.trim()) conditions.body_contains = bodyVal.trim();

    const actions = {};
    const autoReply = document.getElementById('gwsRuleAutoReply');
    if (autoReply && autoReply.checked) {
      actions.auto_reply = true;
      const tpl = (document.getElementById('gwsRuleTemplate') || {}).value || '';
      if (tpl.trim()) actions.auto_reply_template = tpl.trim();
    }
    const fwd = (document.getElementById('gwsRuleForward') || {}).value || '';
    if (fwd.trim()) actions.forward_to = fwd.trim();
    const lbl = (document.getElementById('gwsRuleLabel') || {}).value || '';
    if (lbl.trim()) actions.label = lbl.trim();

    try {
      await api('POST', '/api/rules/' + encodeURIComponent(_currentAccountId), {
        name: name.trim(),
        conditions,
        actions,
      });
      closeRuleModal();
      toast('Rule saved.');
      loadRules();
    } catch (err) {
      toast('Failed to save rule: ' + err.message, true);
    }
  };

  window.deleteRule = async function (ruleId) {
    if (!_currentAccountId) return;
    if (!window.confirm('Delete this rule?')) return;
    try {
      await api('DELETE',
        '/api/rules/' + encodeURIComponent(_currentAccountId) +
        '/' + encodeURIComponent(ruleId)
      );
      toast('Rule deleted.');
      loadRules();
    } catch (err) {
      toast('Failed to delete rule: ' + err.message, true);
    }
  };

  // ── Init ──────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    loadAccounts();

    // Toggle auto-reply template field visibility
    const autoReplyCb = document.getElementById('gwsRuleAutoReply');
    const tplField = document.getElementById('gwsRuleTemplateField');
    if (autoReplyCb && tplField) {
      tplField.style.display = 'none';
      autoReplyCb.addEventListener('change', function () {
        tplField.style.display = autoReplyCb.checked ? '' : 'none';
      });
    }

    // Close modals on overlay click
    ['gwsComposeModal', 'gwsRuleModal'].forEach(function (id) {
      const modal = document.getElementById(id);
      if (!modal) return;
      modal.addEventListener('click', function (e) {
        if (e.target === modal) {
          modal.style.display = 'none';
        }
      });
    });

    // Close modals on Escape
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        document.querySelectorAll('.gws-modal-overlay').forEach(function (m) {
          m.style.display = 'none';
        });
      }
    });
  });

  // Expose helpers for external use if needed
  window.toast = toast;

}());
