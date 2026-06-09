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
  let _currentLabel = 'INBOX';
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
      _currentLabel = 'INBOX';
      loadLabels();
      if (_activeTab === 'inbox') loadInbox(1);
      if (_activeTab === 'rules') loadRules();
      if (_activeTab === 'calendar') loadCalendarEvents(_currentAccountId);
      if (_activeTab === 'drive') loadDriveFiles(_currentAccountId);
      if (_activeTab !== 'inbox') loadInbox(1);
    }
  };

  // ── Labels ──────────────────────────────────────────────────────────────

  window.loadLabels = async function () {
    if (!_currentAccountId) return;
    try {
      var data = await api('GET', '/api/labels/' + encodeURIComponent(_currentAccountId));
      var labels = data.labels || [];

      // Update system label counts
      var systemIds = ['INBOX', 'STARRED', 'SENT', 'DRAFT', 'IMPORTANT', 'SPAM', 'TRASH'];
      systemIds.forEach(function (id) {
        var el = document.getElementById('gwsCount' + id);
        if (!el) return;
        var lbl = labels.find(function (l) { return l.id === id; });
        if (lbl && lbl.messagesUnread > 0) {
          el.textContent = lbl.messagesUnread;
          el.style.display = '';
        } else if (lbl && lbl.messagesTotal > 0 && (id === 'DRAFT' || id === 'SPAM' || id === 'TRASH')) {
          el.textContent = lbl.messagesTotal;
          el.style.display = '';
        } else {
          el.textContent = '';
          el.style.display = 'none';
        }
      });

      // Render custom labels
      var customContainer = document.getElementById('gwsCustomLabels');
      if (customContainer) {
        clearEl(customContainer);
        labels.filter(function (l) { return l.type === 'user'; })
          .sort(function (a, b) { return a.name.localeCompare(b.name); })
          .forEach(function (lbl) {
            var div = document.createElement('div');
            div.className = 'gws-label-item';
            if (_currentLabel === lbl.id) div.classList.add('active');
            div.setAttribute('data-label', lbl.id);
            div.addEventListener('click', function () { switchLabel(lbl.id); });
            var icon = document.createElement('i');
            icon.setAttribute('data-lucide', 'tag');
            div.appendChild(icon);
            var span = document.createElement('span');
            span.textContent = lbl.name;
            div.appendChild(span);
            customContainer.appendChild(div);
          });
        if (typeof lucide !== 'undefined') lucide.createIcons();
      }

      // Highlight active label
      document.querySelectorAll('.gws-label-item').forEach(function (el) {
        el.classList.toggle('active', el.getAttribute('data-label') === _currentLabel);
      });
    } catch (err) {
      // Labels are non-critical, silently fail
    }
  };

  window.switchLabel = function (label) {
    _currentLabel = label;
    document.querySelectorAll('.gws-label-item').forEach(function (el) {
      el.classList.toggle('active', el.getAttribute('data-label') === label);
    });
    loadInbox(1);
  };

  // ── Inbox ─────────────────────────────────────────────────────────────────

  window.loadInbox = async function (page) {
    if (!_currentAccountId) return;
    _currentPage = page || 1;
    try {
      var labelParam = _currentLabel ? '&label=' + encodeURIComponent(_currentLabel) : '';
      const data = await api('GET',
        '/api/inbox/' + encodeURIComponent(_currentAccountId) +
        '?page=' + _currentPage + '&per_page=' + PER_PAGE + labelParam
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

      // Status badges (analyzed, saved to KB)
      var badges = document.createElement('div');
      badges.className = 'gws-email-badges';
      if (email.ai_priority) {
        var ab = document.createElement('span');
        ab.className = 'gws-email-badge-ai';
        if (email.ai_priority === 'critical' || email.ai_priority === 'high') ab.classList.add('high');
        ab.textContent = email.ai_priority.toUpperCase();
        ab.title = 'AI Analyzed: ' + (email.ai_category || '') + ' / ' + (email.ai_sentiment || '');
        badges.appendChild(ab);
      }
      if (email.filed_to_kb) {
        var kb = document.createElement('span');
        kb.className = 'gws-email-badge-kb';
        kb.textContent = 'KB';
        kb.title = 'Saved to Knowledge Base';
        badges.appendChild(kb);
      }
      if (badges.children.length) item.appendChild(badges);

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

    // Body — prefer HTML, fall back to plain text
    const bodyDiv = document.createElement('div');
    bodyDiv.className = 'gws-email-body';
    const bodyContent = email.body_html || email.body_plain || email.body || email.body_text || '';
    if (email.body_html) {
      const iframe = document.createElement('iframe');
      iframe.className = 'gws-email-iframe';
      iframe.sandbox = 'allow-same-origin';
      iframe.srcdoc = bodyContent;
      iframe.style.width = '100%';
      iframe.style.border = 'none';
      iframe.style.minHeight = '300px';
      iframe.style.background = '#1a1a2e';
      iframe.onload = function () {
        try {
          const doc = iframe.contentDocument;
          doc.body.style.color = '#e0e0e0';
          doc.body.style.fontFamily = 'sans-serif';
          doc.body.style.fontSize = '14px';
          doc.body.style.background = '#1a1a2e';
          iframe.style.height = doc.body.scrollHeight + 20 + 'px';
        } catch (_) {}
      };
      bodyDiv.appendChild(iframe);
    } else if (bodyContent) {
      const pre = document.createElement('pre');
      pre.className = 'gws-email-body-text';
      pre.textContent = bodyContent;
      bodyDiv.appendChild(pre);
    } else {
      const empty = document.createElement('p');
      empty.className = 'gws-muted';
      empty.textContent = '(no content)';
      bodyDiv.appendChild(empty);
    }
    panel.appendChild(bodyDiv);

    // Attachments
    if (email.attachments && email.attachments.length > 0) {
      const attDiv = document.createElement('div');
      attDiv.className = 'gws-email-attachments';
      const attLabel = document.createElement('span');
      attLabel.className = 'gws-email-meta-label';
      attLabel.textContent = 'Attachments:';
      attDiv.appendChild(attLabel);
      email.attachments.forEach(function (att) {
        const chip = document.createElement('span');
        chip.className = 'gws-attachment-chip';
        chip.textContent = att.filename + ' (' + Math.round((att.size || 0) / 1024) + ' KB)';
        attDiv.appendChild(chip);
      });
      panel.appendChild(attDiv);
    }

    // Action buttons
    const actions = document.createElement('div');
    actions.className = 'gws-email-actions';

    const gId = email.gmail_id || email.id;

    const markReadBtn = document.createElement('button');
    markReadBtn.className = 'gws-btn gws-btn-secondary';
    markReadBtn.textContent = 'Mark as Read';
    markReadBtn.addEventListener('click', function () { markAsRead(gId); });
    actions.appendChild(markReadBtn);

    const replyBtn = document.createElement('button');
    replyBtn.className = 'gws-btn gws-btn-primary';
    replyBtn.textContent = 'Reply';
    replyBtn.addEventListener('click', function () { openCompose(gId); });
    actions.appendChild(replyBtn);

    const fwdBtn = document.createElement('button');
    fwdBtn.className = 'gws-btn gws-btn-secondary';
    fwdBtn.textContent = 'Forward';
    fwdBtn.addEventListener('click', function () { forwardEmail(email); });
    actions.appendChild(fwdBtn);

    const analyzeBtn = document.createElement('button');
    analyzeBtn.className = 'gws-btn gws-btn-secondary';
    analyzeBtn.textContent = 'AI Analyze';
    analyzeBtn.addEventListener('click', function () { analyzeEmailAction(gId); });
    actions.appendChild(analyzeBtn);

    const kbBtn = document.createElement('button');
    kbBtn.className = 'gws-btn gws-btn-secondary';
    kbBtn.textContent = 'Save to KB';
    kbBtn.addEventListener('click', function () { fileToKB(gId); });
    actions.appendChild(kbBtn);

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'gws-btn gws-btn-ghost';
    deleteBtn.textContent = 'Delete';
    deleteBtn.style.color = '#ef4444';
    deleteBtn.addEventListener('click', function () { trashEmail(gId); });
    actions.appendChild(deleteBtn);

    panel.appendChild(actions);

    // Show AI analysis badge if already analyzed
    if (email.ai_priority || email.ai_sentiment) {
      var aiBar = document.createElement('div');
      aiBar.className = 'gws-ai-bar';
      var badges = [];
      if (email.ai_priority) badges.push('Priority: ' + email.ai_priority.toUpperCase());
      if (email.ai_sentiment) badges.push('Sentiment: ' + email.ai_sentiment);
      if (email.ai_category) badges.push('Category: ' + email.ai_category);
      if (email.ai_summary) badges.push(email.ai_summary);
      badges.forEach(function(txt) {
        var badge = document.createElement('span');
        badge.className = 'gws-ai-badge';
        if (txt.indexOf('critical') >= 0 || txt.indexOf('urgent') >= 0) badge.classList.add('gws-ai-urgent');
        if (txt.indexOf('high') >= 0) badge.classList.add('gws-ai-high');
        badge.textContent = txt;
        aiBar.appendChild(badge);
      });
      header.appendChild(aiBar);
    }
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

  window.analyzeEmailAction = async function (gmailId) {
    if (!_currentAccountId) return;
    try {
      toast('Analyzing...');
      var data = await api('POST', '/api/email/' + encodeURIComponent(_currentAccountId) +
        '/' + encodeURIComponent(gmailId) + '/analyze', {});
      if (data.success) {
        toast('Analysis: ' + (data.priority || '') + ' / ' + (data.category || ''));
        viewEmail(gmailId);
      } else {
        toast('Analysis failed: ' + (data.error || ''), true);
      }
    } catch (err) {
      toast('Analysis failed: ' + err.message, true);
    }
  };

  window.fileToKB = async function (gmailId) {
    if (!_currentAccountId) return;
    try {
      var data = await api('POST', '/api/email/' + encodeURIComponent(_currentAccountId) +
        '/' + encodeURIComponent(gmailId) + '/file-kb', {});
      if (data.success) {
        toast('Saved to Knowledge Base (#' + data.kb_id + ')');
      } else {
        toast('Failed: ' + (data.error || ''), true);
      }
    } catch (err) {
      toast('Failed: ' + err.message, true);
    }
  };

  window.markAsRead = async function (gmailId) {
    if (!_currentAccountId) return;
    try {
      await api('POST', '/api/email/' + encodeURIComponent(_currentAccountId) +
        '/' + encodeURIComponent(gmailId) + '/read', {});
      toast('Marked as read.');
      _emails.forEach(function (e) {
        if ((e.gmail_id || e.id) === gmailId) e.is_read = true;
      });
      renderEmailList();
    } catch (err) {
      toast('Failed: ' + err.message, true);
    }
  };

  window.trashEmail = async function (gmailId) {
    if (!_currentAccountId) return;
    if (!confirm('Move this email to trash?')) return;
    try {
      await api('DELETE', '/api/email/' + encodeURIComponent(_currentAccountId) +
        '/' + encodeURIComponent(gmailId), {});
      toast('Email deleted.');
      _emails = _emails.filter(function (e) { return (e.gmail_id || e.id) !== gmailId; });
      renderEmailList();
      var panel = document.getElementById('gwsEmailDetail');
      if (panel) {
        clearEl(panel);
        var empty = document.createElement('div');
        empty.className = 'gws-empty-state';
        var p = document.createElement('p');
        p.textContent = 'Select an email to read it.';
        empty.appendChild(p);
        panel.appendChild(empty);
      }
    } catch (err) {
      toast('Delete failed: ' + err.message, true);
    }
  };

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

    const panels = {
      inbox: 'gwsInboxTab',
      rules: 'gwsRulesTab',
      calendar: 'gwsCalendarTab',
      drive: 'gwsDriveTab',
    };
    const buttons = {
      inbox: 'gwsTabInbox',
      rules: 'gwsTabRules',
      calendar: 'gwsTabCalendar',
      drive: 'gwsTabDrive',
    };

    Object.keys(panels).forEach(function (key) {
      const panel = document.getElementById(panels[key]);
      if (panel) panel.style.display = key === tab ? '' : 'none';
      const btn = document.getElementById(buttons[key]);
      if (btn) {
        btn.classList.toggle('active', key === tab);
        btn.setAttribute('aria-selected', String(key === tab));
      }
    });

    if (tab === 'rules' && _currentAccountId) loadRules();
    if (tab === 'calendar' && _currentAccountId) loadCalendarEvents(_currentAccountId);
    if (tab === 'drive' && _currentAccountId) loadDriveFiles(_currentAccountId);
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

  // ── Calendar ──────────────────────────────────────────────────────────────

  var _calendarWeekStart = null;

  window.loadCalendarEvents = function (accountId, weekStart) {
    if (!accountId) accountId = _currentAccountId;
    if (!weekStart) {
      var now = new Date();
      var day = now.getDay();
      var diff = now.getDate() - day + (day === 0 ? -6 : 1);
      weekStart = new Date(now.setDate(diff));
      weekStart.setHours(0, 0, 0, 0);
    }
    _calendarWeekStart = weekStart;
    var endDate = new Date(weekStart);
    endDate.setDate(endDate.getDate() + 7);
    var weekLabel = document.getElementById('gwsCalendarWeekLabel');
    if (weekLabel) {
      weekLabel.textContent =
        weekStart.toLocaleDateString() + ' \u2014 ' +
        new Date(endDate - 86400000).toLocaleDateString();
    }
    api('GET',
      '/api/calendar/' + encodeURIComponent(accountId) +
      '/events?time_min=' + weekStart.toISOString() +
      '&time_max=' + endDate.toISOString()
    ).then(renderWeekView).catch(function (err) {
      toast('Failed to load calendar: ' + err.message, true);
    });
  };

  function renderWeekView(data) {
    var grid = document.getElementById('gwsCalendarGrid');
    if (!grid) return;
    clearEl(grid);
    var events = data.events || data || [];
    var days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

    var headerRow = document.createElement('div');
    headerRow.className = 'gws-calendar-header-row';
    days.forEach(function (d, i) {
      var dayDate = new Date(_calendarWeekStart);
      dayDate.setDate(dayDate.getDate() + i);
      var cell = document.createElement('div');
      cell.className = 'gws-calendar-day-header';
      cell.textContent = d + ' ' + dayDate.getDate();
      headerRow.appendChild(cell);
    });
    grid.appendChild(headerRow);

    var dayColumns = [[], [], [], [], [], [], []];
    events.forEach(function (ev) {
      var startVal = ev.start ? (ev.start.dateTime || ev.start.date || ev.start) : null;
      if (!startVal) return;
      var start = new Date(startVal);
      var dayIdx = (start.getDay() + 6) % 7;
      if (dayIdx >= 0 && dayIdx < 7) dayColumns[dayIdx].push(ev);
    });

    var bodyRow = document.createElement('div');
    bodyRow.className = 'gws-calendar-body-row';
    dayColumns.forEach(function (dayEvents) {
      var col = document.createElement('div');
      col.className = 'gws-calendar-day-col';
      dayEvents.forEach(function (ev) {
        var block = document.createElement('div');
        block.className = 'gws-calendar-event';
        var startVal = ev.start ? (ev.start.dateTime || ev.start.date || ev.start) : null;
        var startDate = startVal ? new Date(startVal) : null;
        var time = document.createElement('span');
        time.className = 'gws-calendar-event-time';
        time.textContent = startDate
          ? startDate.getHours() + ':' + String(startDate.getMinutes()).padStart(2, '0')
          : '';
        var title = document.createElement('span');
        title.textContent = ev.summary || 'No title';
        block.appendChild(time);
        block.appendChild(title);
        block.onclick = function () { openEventModal(ev); };
        col.appendChild(block);
      });
      bodyRow.appendChild(col);
    });
    grid.appendChild(bodyRow);
  }

  window.navigateWeek = function (dir) {
    if (dir === 0) { _calendarWeekStart = null; loadCalendarEvents(); return; }
    var ws = new Date(_calendarWeekStart);
    ws.setDate(ws.getDate() + (dir * 7));
    loadCalendarEvents(null, ws);
  };

  window.openEventModal = function (event) {
    var modal = document.getElementById('gwsEventModal');
    if (!modal) return;
    var titleEl = document.getElementById('gwsEventTitle');
    var idEl = document.getElementById('gwsEventId');
    var summaryEl = document.getElementById('gwsEventSummary');
    var startEl = document.getElementById('gwsEventStart');
    var endEl = document.getElementById('gwsEventEnd');
    var locationEl = document.getElementById('gwsEventLocation');
    var descEl = document.getElementById('gwsEventDescription');
    var attendeesEl = document.getElementById('gwsEventAttendees');
    var deleteBtn = document.getElementById('gwsEventDeleteBtn');

    if (event) {
      titleEl.textContent = 'Edit Event';
      idEl.value = event.id || '';
      summaryEl.value = event.summary || '';
      var startVal = event.start ? (event.start.dateTime || event.start.date) : '';
      var endVal = event.end ? (event.end.dateTime || event.end.date) : '';
      startEl.value = startVal ? startVal.slice(0, 16) : '';
      endEl.value = endVal ? endVal.slice(0, 16) : '';
      locationEl.value = event.location || '';
      descEl.value = event.description || '';
      var attendees = (event.attendees || []).map(function (a) { return a.email || a; }).join(', ');
      attendeesEl.value = attendees;
      if (deleteBtn) deleteBtn.style.display = '';
    } else {
      titleEl.textContent = 'New Event';
      idEl.value = '';
      summaryEl.value = '';
      startEl.value = '';
      endEl.value = '';
      locationEl.value = '';
      descEl.value = '';
      attendeesEl.value = '';
      if (deleteBtn) deleteBtn.style.display = 'none';
    }
    modal.style.display = '';
  };

  window.closeEventModal = function () {
    var modal = document.getElementById('gwsEventModal');
    if (modal) modal.style.display = 'none';
  };

  window.saveCalendarEvent = async function () {
    if (!_currentAccountId) return;
    var eventId = document.getElementById('gwsEventId').value;
    var summary = document.getElementById('gwsEventSummary').value;
    var startVal = document.getElementById('gwsEventStart').value;
    var endVal = document.getElementById('gwsEventEnd').value;
    var location = document.getElementById('gwsEventLocation').value;
    var description = document.getElementById('gwsEventDescription').value;
    var attendeesRaw = document.getElementById('gwsEventAttendees').value;

    if (!summary || !startVal || !endVal) {
      toast('Title, start and end are required', true);
      return;
    }
    var attendees = attendeesRaw
      ? attendeesRaw.split(',').map(function (e) { return e.trim(); }).filter(Boolean)
      : [];
    var body = {
      summary: summary,
      start: startVal,
      end: endVal,
      location: location,
      description: description,
      attendees: attendees,
    };
    try {
      if (eventId) {
        await api('PUT', '/api/calendar/' + encodeURIComponent(_currentAccountId) + '/events/' + eventId, body);
        toast('Event updated');
      } else {
        await api('POST', '/api/calendar/' + encodeURIComponent(_currentAccountId) + '/events', body);
        toast('Event created');
      }
      closeEventModal();
      loadCalendarEvents(_currentAccountId, _calendarWeekStart);
    } catch (err) {
      toast('Failed to save event: ' + err.message, true);
    }
  };

  window.deleteCalendarEvent = async function (eventId) {
    if (!_currentAccountId || !eventId) return;
    if (!confirm('Delete this event?')) return;
    try {
      await api('DELETE', '/api/calendar/' + encodeURIComponent(_currentAccountId) + '/events/' + eventId);
      toast('Event deleted');
      closeEventModal();
      loadCalendarEvents(_currentAccountId, _calendarWeekStart);
    } catch (err) {
      toast('Failed to delete event: ' + err.message, true);
    }
  };

  // ── Drive ─────────────────────────────────────────────────────────────────

  var _driveFolderStack = [{ id: 'root', name: 'My Drive' }];

  window.loadDriveFiles = function (accountId, folderId) {
    if (!accountId) accountId = _currentAccountId;
    var currentFolder = _driveFolderStack[_driveFolderStack.length - 1];
    if (!folderId) folderId = currentFolder ? currentFolder.id : 'root';
    renderBreadcrumb();
    api('GET', '/api/drive/' + encodeURIComponent(accountId) + '/files?folder_id=' + encodeURIComponent(folderId))
      .then(renderDriveFiles)
      .catch(function (err) {
        toast('Failed to load drive: ' + err.message, true);
      });
  };

  function renderDriveFiles(data) {
    var container = document.getElementById('gwsDriveFiles');
    if (!container) return;
    clearEl(container);
    var files = data.files || data || [];

    if (files.length === 0) {
      var empty = document.createElement('div');
      empty.className = 'gws-empty-state';
      var p = document.createElement('p');
      p.textContent = 'This folder is empty.';
      empty.appendChild(p);
      container.appendChild(empty);
      return;
    }

    files.forEach(function (file) {
      var row = document.createElement('div');
      row.className = 'gws-drive-file-row';

      var icon = document.createElement('div');
      icon.className = 'gws-drive-file-icon';
      var mimeType = file.mimeType || '';
      if (mimeType.indexOf('folder') !== -1) icon.textContent = '\uD83D\uDCC1';
      else if (mimeType.indexOf('document') !== -1) icon.textContent = '\uD83D\uDCC4';
      else if (mimeType.indexOf('spreadsheet') !== -1) icon.textContent = '\uD83D\uDCCA';
      else if (mimeType.indexOf('image') !== -1) icon.textContent = '\uD83D\uDDBC';
      else icon.textContent = '\uD83D\uDCCE';

      var name = document.createElement('div');
      name.className = 'gws-drive-file-name';
      name.textContent = file.name || file.id;

      var date = document.createElement('div');
      date.className = 'gws-drive-file-date';
      date.textContent = file.modifiedTime ? new Date(file.modifiedTime).toLocaleDateString() : '';

      var shareBtn = document.createElement('button');
      shareBtn.className = 'gws-btn-sm';
      shareBtn.textContent = 'Share';
      (function (fid) {
        shareBtn.onclick = function (e) { e.stopPropagation(); shareDriveFile(fid); };
      }(file.id));

      row.appendChild(icon);
      row.appendChild(name);
      row.appendChild(date);
      row.appendChild(shareBtn);

      if (mimeType.indexOf('folder') !== -1) {
        (function (fid, fname) {
          row.onclick = function () { navigateDriveFolder(fid, fname); };
        }(file.id, file.name));
      } else {
        (function (fid) {
          row.onclick = function () { previewDriveFile(fid); };
        }(file.id));
      }
      container.appendChild(row);
    });
  }

  window.navigateDriveFolder = function (folderId, folderName) {
    _driveFolderStack.push({ id: folderId, name: folderName });
    loadDriveFiles(_currentAccountId, folderId);
  };

  function renderBreadcrumb() {
    var bc = document.getElementById('gwsDriveBreadcrumb');
    if (!bc) return;
    clearEl(bc);
    _driveFolderStack.forEach(function (folder, idx) {
      var span = document.createElement('span');
      span.textContent = folder.name;
      if (idx < _driveFolderStack.length - 1) {
        (function (capturedIdx, capturedId) {
          span.onclick = function () {
            _driveFolderStack = _driveFolderStack.slice(0, capturedIdx + 1);
            loadDriveFiles(_currentAccountId, capturedId);
          };
        }(idx, folder.id));
        var sep = document.createElement('span');
        sep.textContent = ' / ';
        bc.appendChild(span);
        bc.appendChild(sep);
      } else {
        span.style.color = 'var(--gws-accent, #0cf)';
        bc.appendChild(span);
      }
    });
  }

  window.previewDriveFile = async function (fileId) {
    var preview = document.getElementById('gwsDrivePreview');
    if (!preview) return;
    try {
      var data = await api('GET', '/api/drive/' + encodeURIComponent(_currentAccountId) + '/files/' + encodeURIComponent(fileId));
      clearEl(preview);
      var title = document.createElement('div');
      title.style.cssText = 'font-weight:700;margin-bottom:0.5rem;color:var(--gws-accent,#0cf);';
      title.textContent = data.name || fileId;
      preview.appendChild(title);
      if (data.webViewLink) {
        var link = document.createElement('a');
        link.href = data.webViewLink;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = 'Open in Google Drive';
        link.style.cssText = 'color:var(--gws-accent,#0cf);font-size:0.65rem;';
        preview.appendChild(link);
      }
      if (data.content) {
        var pre = document.createElement('pre');
        pre.style.cssText = 'font-size:0.6rem;white-space:pre-wrap;margin-top:0.5rem;';
        pre.textContent = data.content;
        preview.appendChild(pre);
      }
    } catch (err) {
      toast('Failed to preview file: ' + err.message, true);
    }
  };

  window.uploadDriveFile = function (input) {
    if (!input.files || !input.files[0] || !_currentAccountId) return;
    var file = input.files[0];
    var reader = new FileReader();
    reader.onload = async function (e) {
      var b64 = e.target.result.split(',')[1];
      try {
        await api('POST', '/api/drive/' + encodeURIComponent(_currentAccountId) + '/files', {
          name: file.name,
          type: 'upload',
          content: b64,
          mime_type: file.type || 'application/octet-stream',
          folder_id: _driveFolderStack[_driveFolderStack.length - 1].id,
        });
        toast('File uploaded');
        loadDriveFiles(_currentAccountId);
      } catch (err) {
        toast('Upload failed: ' + err.message, true);
      }
    };
    reader.readAsDataURL(file);
    input.value = '';
  };

  window.createDriveItem = async function (type) {
    if (!type || !_currentAccountId) return;
    var label = type === 'folder' ? 'Folder name:' : 'File name:';
    var name = prompt(label);
    if (!name) return;
    try {
      await api('POST', '/api/drive/' + encodeURIComponent(_currentAccountId) + '/files', {
        name: name,
        type: type,
        folder_id: _driveFolderStack[_driveFolderStack.length - 1].id,
      });
      toast((type === 'folder' ? 'Folder' : 'File') + ' created');
      loadDriveFiles(_currentAccountId);
    } catch (err) {
      toast('Failed to create: ' + err.message, true);
    }
  };

  window.shareDriveFile = function (fileId) {
    var modal = document.getElementById('gwsShareModal');
    if (!modal) return;
    document.getElementById('gwsShareFileId').value = fileId;
    document.getElementById('gwsShareEmail').value = '';
    document.getElementById('gwsShareRole').value = 'reader';
    modal.style.display = '';
  };

  window.closeShareModal = function () {
    var modal = document.getElementById('gwsShareModal');
    if (modal) modal.style.display = 'none';
  };

  window.submitShare = async function () {
    if (!_currentAccountId) return;
    var fileId = document.getElementById('gwsShareFileId').value;
    var email = document.getElementById('gwsShareEmail').value;
    var role = document.getElementById('gwsShareRole').value;
    if (!email) { toast('Email is required', true); return; }
    try {
      await api('POST',
        '/api/drive/' + encodeURIComponent(_currentAccountId) +
        '/files/' + encodeURIComponent(fileId) + '/share',
        { email: email, role: role }
      );
      toast('Shared with ' + email);
      closeShareModal();
    } catch (err) {
      toast('Failed to share: ' + err.message, true);
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
