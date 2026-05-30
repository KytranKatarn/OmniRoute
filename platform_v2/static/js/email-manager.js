/* Email HQ — Three-panel frontend
 *
 * HTML email bodies: parsed via DOMParser + DOMPurify, appended via
 * DOM methods (no bare innerHTML). textContent used everywhere else.
 */
(function () {
  'use strict';

  var BASE = '/tools/email-manager';

  // ── State ────────────────────────────────────────────────────────────
  var state = {
    currentMailboxId: null,
    currentMailboxName: 'All Mail',
    currentView: 'all',
    currentPage: 1,
    currentTotal: 0,
    currentMessageId: null,
    currentMsg: null,
    searchQuery: '',
    searchTimer: null,
    refreshTimer: null,
  };

  // ── API helpers ──────────────────────────────────────────────────────
  function api(path, opts) {
    return fetch(BASE + path, opts || {}).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function apiPost(path, body) {
    return api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
  }

  function apiDelete(path) {
    return api(path, { method: 'DELETE' });
  }

  // ── DOM helpers ──────────────────────────────────────────────────────
  function el(id) { return document.getElementById(id); }
  function setText(id, v) { var e = el(id); if (e) e.textContent = v != null ? v : ''; }
  function show(id) { var e = el(id); if (e) e.style.display = ''; }
  function hide(id) { var e = el(id); if (e) e.style.display = 'none'; }

  function lucideIcon(name, size) {
    var i = document.createElement('i');
    i.setAttribute('data-lucide', name);
    i.style.width = (size || 11) + 'px';
    i.style.height = (size || 11) + 'px';
    i.style.flexShrink = '0';
    return i;
  }

  function relativeTime(iso) {
    if (!iso) return '';
    var diff = Date.now() - new Date(iso).getTime();
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return Math.round(diff / 60000) + 'm';
    if (diff < 86400000) return Math.round(diff / 3600000) + 'h';
    if (diff < 604800000) return Math.round(diff / 86400000) + 'd';
    return new Date(iso).toLocaleDateString();
  }

  // ── Sidebar ──────────────────────────────────────────────────────────
  function loadSidebar() {
    api('/api/email/sidebar').then(function (d) {
      var container = el('em-mailbox-groups');
      if (!container) return;
      while (container.firstChild) container.removeChild(container.firstChild);

      var groups = d.groups || {};
      var mailboxes = d.mailboxes || [];

      if (!mailboxes.length) {
        var p = document.createElement('div');
        p.className = 'em-placeholder';
        p.textContent = 'No mailboxes provisioned';
        container.appendChild(p);
        return;
      }

      var groupKeys = Object.keys(groups).sort(function (a, b) {
        var order = { owner: 0, business: 1, human_agent: 100 };
        return (order[a] != null ? order[a] : 99) - (order[b] != null ? order[b] : 99) || a.localeCompare(b);
      });

      groupKeys.forEach(function (key) {
        var items = groups[key];
        if (!items || !items.length) return;

        var header = document.createElement('div');
        header.className = 'em-group-header';
        header.textContent = key.replace(/_/g, ' ').toUpperCase();
        container.appendChild(header);

        items.forEach(function (m) {
          var item = document.createElement('div');
          item.className = 'em-mailbox-item';
          item.dataset.mailboxId = m.id;

          var iconName = m.mailbox_type === 'owner' ? 'crown' : m.mailbox_type === 'business' ? 'briefcase' : m.mailbox_type === 'human_agent' ? 'user' : 'bot';
          item.appendChild(lucideIcon(iconName, 11));

          var name = document.createElement('span');
          name.className = 'em-mailbox-name';
          name.textContent = m.display_name || m.address;
          name.title = m.address;
          item.appendChild(name);

          if (m.unread_count && m.unread_count > 0) {
            var badge = document.createElement('span');
            badge.className = 'em-mailbox-unread';
            badge.textContent = m.unread_count;
            item.appendChild(badge);
          }

          if (!m.provisioned) item.style.opacity = '.4';

          item.addEventListener('click', function () {
            selectMailbox(m.id, m.display_name || m.address);
          });

          container.appendChild(item);
        });
      });

      if (window.lucide) window.lucide.createIcons();
    }).catch(function () {
      var c = el('em-mailbox-groups');
      if (c) { while (c.firstChild) c.removeChild(c.firstChild); var p = document.createElement('div'); p.className = 'em-placeholder'; p.textContent = 'Failed to load'; c.appendChild(p); }
    });
  }

  // ── Badge counts ─────────────────────────────────────────────────────
  function loadCounts() {
    api('/api/email/counts').then(function (d) {
      var bUnread = el('badge-unread');
      var bAction = el('badge-action');
      if (bUnread) bUnread.textContent = (d.unread || 0) > 0 ? d.unread : '';
      if (bAction) bAction.textContent = (d.action_items || 0) > 0 ? d.action_items : '';
    }).catch(function () {});
  }

  // ── Nav / view selection ─────────────────────────────────────────────
  function setActiveNav(view, mailboxId) {
    document.querySelectorAll('.em-nav-item').forEach(function (n) { n.classList.remove('em-nav-active'); });
    document.querySelectorAll('.em-mailbox-item').forEach(function (m) { m.classList.remove('em-mailbox-active'); });
    if (mailboxId) {
      var mItem = document.querySelector('[data-mailbox-id="' + mailboxId + '"]');
      if (mItem) mItem.classList.add('em-mailbox-active');
    } else {
      var navEl = el('nav-' + view);
      if (navEl) navEl.classList.add('em-nav-active');
    }
  }

  function selectView(view) {
    state.currentView = view;
    state.currentMailboxId = null;
    state.currentPage = 1;
    setActiveNav(view, null);

    if (view === 'manage') {
      setText('em-list-context', 'Mailbox Management');
      state.currentMailboxName = 'Manage';
      showManageView();
      slideTo('list');
      return;
    }

    var labels = { all: 'All Mail', unread: 'Unread', action: 'Action Items', starred: 'Starred' };
    setText('em-list-context', labels[view] || view);
    state.currentMailboxName = labels[view] || view;

    var path;
    if (view === 'action') path = '/api/email/views/action';
    else if (view === 'starred') path = '/api/email/views/starred';
    else if (view === 'unread') path = '/api/email/views/unread';
    else path = '/api/email/messages?view=inbox&page=1';

    loadMessagesByPath(path);
    slideTo('list');
  }

  function showManageView() {
    var list = el('em-message-list');
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);

    // Tab bar: Mailboxes | Rules
    var tabBar = document.createElement('div');
    tabBar.style.cssText = 'display:flex;gap:0;border-bottom:1px solid #1a1a2e;flex-shrink:0;';
    var tabs = [['mailboxes', 'Mailboxes'], ['rules', 'Rules'], ['sla', 'SLA']];
    tabs.forEach(function (t) {
      var tab = document.createElement('button');
      tab.className = 'em-text-btn';
      tab.dataset.manageTab = t[0];
      tab.textContent = t[1];
      tab.style.cssText = 'flex:1;padding:8px;border-radius:0;border-bottom:2px solid transparent;';
      tab.addEventListener('click', function () {
        tabBar.querySelectorAll('[data-manage-tab]').forEach(function (b) {
          b.style.borderBottomColor = 'transparent';
          b.style.color = '';
        });
        tab.style.borderBottomColor = '#00d4ff';
        tab.style.color = '#00d4ff';
        if (t[0] === 'rules') showRulesPanel(content);
        else if (t[0] === 'sla') showSlaPanel(content);
        else showMailboxesPanel(content);
      });
      if (t[0] === 'mailboxes') {
        tab.style.borderBottomColor = '#00d4ff';
        tab.style.color = '#00d4ff';
      }
      tabBar.appendChild(tab);
    });
    list.appendChild(tabBar);

    var content = document.createElement('div');
    content.style.cssText = 'flex:1;overflow-y:auto;';
    list.appendChild(content);
    list.style.display = 'flex';
    list.style.flexDirection = 'column';

    showMailboxesPanel(content);
    return;
  }

  function showMailboxesPanel(container) {
    while (container.firstChild) container.removeChild(container.firstChild);

    var loading = document.createElement('div');
    loading.className = 'em-list-empty';
    loading.textContent = 'Loading mailboxes…';
    container.appendChild(loading);

    var list = container;

    api('/api/email/mailboxes').then(function (d) {
      while (list.firstChild) list.removeChild(list.firstChild);
      (d.mailboxes || []).forEach(function (m) {
        var row = document.createElement('div');
        row.className = 'em-msg-row';
        row.style.padding = '8px 10px';

        var top = document.createElement('div');
        top.className = 'em-msg-top';

        var addr = document.createElement('span');
        addr.className = 'em-msg-from-text';
        addr.style.fontFamily = 'monospace';
        addr.style.fontSize = '10px';
        addr.textContent = m.address;

        var statusBadge = document.createElement('span');
        statusBadge.className = 'em-priority-chip ' + (m.provisioned ? 'em-priority-info' : 'em-priority-review');
        statusBadge.textContent = m.provisioned ? 'active' : 'pending';

        top.appendChild(addr);
        top.appendChild(statusBadge);

        var meta = document.createElement('div');
        meta.className = 'em-msg-preview-text';
        meta.textContent = (m.display_name || m.agent_name || '') + ' · ' + m.mailbox_type.replace(/_/g, ' ');

        var actions = document.createElement('div');
        actions.className = 'em-msg-bottom';
        actions.style.marginTop = '5px';

        if (!m.provisioned) {
          var provBtn = document.createElement('button');
          provBtn.className = 'em-text-btn';
          provBtn.style.color = '#22c55e';
          provBtn.textContent = 'Provision';
          (function (id, address) {
            provBtn.addEventListener('click', function (e) {
              e.stopPropagation();
              apiPost('/api/email/mailboxes/' + id + '/provision').then(function (r) {
                if (r.success) { loadSidebar(); showManageView(); }
                else alert('Failed: ' + (r.error || 'unknown'));
              }).catch(function () {});
            });
          }(m.id, m.address));
          actions.appendChild(provBtn);
        } else {
          var rotBtn = document.createElement('button');
          rotBtn.className = 'em-text-btn';
          rotBtn.textContent = 'Rotate pw';
          (function (id) {
            rotBtn.addEventListener('click', function (e) {
              e.stopPropagation();
              apiPost('/api/email/mailboxes/' + id + '/rotate-password').then(function (r) {
                if (!r.success) alert('Failed: ' + (r.error || 'unknown'));
              }).catch(function () {});
            });
          }(m.id));
          actions.appendChild(rotBtn);
        }

        row.appendChild(top);
        row.appendChild(meta);
        row.appendChild(actions);
        list.appendChild(row);
      });

      if (!d.mailboxes || !d.mailboxes.length) {
        var empty = document.createElement('div');
        empty.className = 'em-list-empty';
        empty.textContent = 'No mailboxes found';
        list.appendChild(empty);
      }

      // Bulk provision button at top
      var bulkRow = document.createElement('div');
      bulkRow.style.cssText = 'padding:8px 10px;border-bottom:1px solid #1a1a2e;';
      var bulkBtn = document.createElement('button');
      bulkBtn.className = 'em-sidebar-action';
      bulkBtn.style.width = '100%';
      bulkBtn.textContent = 'Provision All Pending AI Agents';
      bulkBtn.addEventListener('click', function () {
        apiPost('/api/email/mailboxes/provision-all-agents').then(function (r) {
          alert('Provisioned: ' + r.provisioned + ' | Failed: ' + r.failed);
          loadSidebar();
          showManageView();
        }).catch(function () {});
      });
      bulkRow.appendChild(bulkBtn);
      list.insertBefore(bulkRow, list.firstChild);

    }).catch(function () {
      while (list.firstChild) list.removeChild(list.firstChild);
      var err = document.createElement('div');
      err.className = 'em-list-empty';
      err.textContent = 'Failed to load mailboxes';
      list.appendChild(err);
    });
  }

  function selectMailbox(mailboxId, name) {
    state.currentMailboxId = mailboxId;
    state.currentMailboxName = name;
    state.currentView = 'inbox';
    state.currentPage = 1;
    // Clear read pane — old message should not persist across mailbox switches.
    state.currentMessageId = null;
    hide('em-read-content');
    show('em-read-empty');
    setActiveNav(null, mailboxId);
    setText('em-list-context', name);
    var viewSel = el('em-view-select');
    if (viewSel) viewSel.value = 'inbox';
    loadMessages();
    slideTo('list');
  }

  // ── Message list ─────────────────────────────────────────────────────
  function loadMessages() {
    var params = '?page=' + state.currentPage;
    if (state.currentMailboxId) params += '&mailbox_id=' + state.currentMailboxId;
    var viewSel = el('em-view-select');
    var selectedView = viewSel ? viewSel.value : 'inbox';
    if (selectedView !== 'inbox') params += '&view=' + selectedView;
    if (state.searchQuery) params += '&search=' + encodeURIComponent(state.searchQuery);
    loadMessagesByPath('/api/email/messages' + params);
  }

  function loadMessagesByPath(path) {
    var list = el('em-message-list');
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    var loading = document.createElement('div');
    loading.className = 'em-list-empty';
    loading.textContent = 'Loading…';
    list.appendChild(loading);

    api(path).then(function (d) {
      state.currentTotal = d.total || (d.messages || []).length;
      var messages = d.messages || [];
      renderMessageList(messages);
      renderPagination(d.total, d.page, d.page_size);
      // Auto-open the first message whenever the read pane is empty
      // (e.g. after switching mailboxes). Skip if user already has one open.
      if (messages.length && !state.currentMessageId) {
        selectMessage(messages[0].id);
      }
    }).catch(function () {
      while (list.firstChild) list.removeChild(list.firstChild);
      var err = document.createElement('div'); err.className = 'em-list-empty'; err.textContent = 'Failed to load'; list.appendChild(err);
    });
  }

  function renderMessageList(messages) {
    var list = el('em-message-list');
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);

    if (!messages.length) {
      var empty = document.createElement('div');
      empty.className = 'em-list-empty';
      empty.textContent = 'No messages';
      list.appendChild(empty);
      return;
    }

    messages.forEach(function (m) {
      var row = document.createElement('div');
      row.className = 'em-msg-row' + (m.is_read ? '' : ' em-msg-unread');
      if (m.id === state.currentMessageId) row.classList.add('em-msg-selected');
      row.dataset.messageId = m.id;

      var top = document.createElement('div');
      top.className = 'em-msg-top';
      var from = document.createElement('span');
      from.className = 'em-msg-from-text';
      from.textContent = m.from_address || '(unknown)';
      var time = document.createElement('span');
      time.className = 'em-msg-time-text';
      time.textContent = relativeTime(m.received_at);
      top.appendChild(from);
      top.appendChild(time);

      var subj = document.createElement('div');
      subj.className = 'em-msg-subject-text';
      subj.textContent = m.subject || '(no subject)';

      var preview = document.createElement('div');
      preview.className = 'em-msg-preview-text';
      preview.textContent = m.preview || '';

      var bottom = document.createElement('div');
      bottom.className = 'em-msg-bottom';

      var dot = document.createElement('span');
      dot.className = 'em-unread-dot';
      bottom.appendChild(dot);

      if (m.ai_priority) {
        var chip = document.createElement('span');
        chip.className = 'em-priority-chip em-priority-' + m.ai_priority;
        chip.textContent = m.ai_priority;
        bottom.appendChild(chip);
      }

      if (m.has_attachments) {
        var att = document.createElement('span');
        att.className = 'em-attachment-icon';
        att.appendChild(lucideIcon('paperclip', 10));
        bottom.appendChild(att);
      }

      if (m.thread_count && m.thread_count > 1) {
        var tc = document.createElement('span');
        tc.className = 'em-priority-chip';
        tc.style.cssText = 'background:#0d1f35;color:#7eb8f7;';
        tc.textContent = m.thread_count + ' msgs';
        bottom.appendChild(tc);
      }

      row.appendChild(top);
      row.appendChild(subj);
      row.appendChild(preview);
      row.appendChild(bottom);
      row.addEventListener('click', function () { selectMessage(m.id); });
      list.appendChild(row);
    });

    if (window.lucide) window.lucide.createIcons();
  }

  function renderPagination(total, page, pageSize) {
    var pag = el('em-pagination');
    if (!pag) return;
    var hasPages = total && pageSize && total > pageSize;
    pag.style.display = hasPages ? '' : 'none';
    if (!hasPages) return;
    setText('em-page-label', 'Page ' + (page || 1));
    var prevBtn = el('em-prev-btn');
    var nextBtn = el('em-next-btn');
    if (prevBtn) prevBtn.disabled = (page || 1) <= 1;
    if (nextBtn) nextBtn.disabled = (page || 1) * (pageSize || 50) >= (total || 0);
  }

  // ── Read pane ────────────────────────────────────────────────────────
  function selectMessage(messageId) {
    state.currentMessageId = messageId;
    var wasUnread = false;
    document.querySelectorAll('.em-msg-row').forEach(function (r) {
      r.classList.toggle('em-msg-selected', r.dataset.messageId == messageId);
      if (r.dataset.messageId == messageId) {
        if (r.classList.contains('em-msg-unread')) wasUnread = true;
        r.classList.remove('em-msg-unread');
      }
    });
    api('/api/email/messages/' + messageId).then(function (msg) {
      state.currentMsg = msg;
      renderReadPane(msg);
      slideTo('read');
      if (wasUnread) { loadCounts(); loadSidebar(); }
    }).catch(function () {
      hide('em-read-content');
      show('em-read-empty');
    });
  }

  function renderReadPane(msg) {
    hide('em-read-empty');
    show('em-read-content');

    setText('em-read-subject', msg.subject || '(no subject)');
    setText('em-read-from', msg.from_address || '');
    setText('em-read-date', msg.received_at ? new Date(msg.received_at).toLocaleString() : '');
    setText('em-read-mailbox', msg.mailbox_display_name || msg.mailbox_address || '');

    var toLine = el('em-read-to-line');
    if (toLine) toLine.textContent = msg.to_address ? 'To: ' + msg.to_address : '';

    if (msg.ai_priority) {
      show('em-ai-banner');
      var chip = el('em-ai-priority-label');
      if (chip) {
        chip.className = 'em-ai-priority-chip em-priority-' + msg.ai_priority;
        chip.textContent = msg.ai_priority.toUpperCase();
      }
      setText('em-ai-suggestion', msg.ai_suggestion || '');
    } else {
      hide('em-ai-banner');
    }

    renderBody(msg);

    var starLabel = el('em-star-label');
    var starBtn = el('em-star-btn');
    if (starLabel) starLabel.textContent = msg.is_starred ? 'Unstar' : 'Star';
    if (starBtn) starBtn.style.color = msg.is_starred ? '#f59e0b' : '';

    // Thread expansion button
    var threadBanner = el('em-thread-banner');
    if (threadBanner) {
      if (msg.thread_id) {
        threadBanner.style.display = '';
        var threadCount = msg.thread_count || '?';
        setText('em-thread-count', threadCount + ' messages in thread');
        threadBanner.dataset.threadId = msg.thread_id;
        var threadBody = el('em-thread-body');
        if (threadBody) { while (threadBody.firstChild) threadBody.removeChild(threadBody.firstChild); threadBody.style.display = 'none'; }
      } else {
        threadBanner.style.display = 'none';
      }
    }

    // Show Draft Reply only for owner/business mailboxes
    var draftBtn = el('em-draft-reply-btn');
    var draftLabel = el('em-draft-reply-label');
    if (draftBtn) {
      var showDraft = true;
      draftBtn.style.display = showDraft ? '' : 'none';
      if (draftLabel) draftLabel.textContent = 'Draft Reply';
      draftBtn.disabled = false;
    }

    // Reset Create Task button; re-surface a previously created task link if any.
    var taskBtn = el('em-create-task-btn');
    var taskLabel = el('em-create-task-label');
    if (taskBtn) { taskBtn.disabled = false; }
    if (taskLabel) taskLabel.textContent = 'Create Task';
    renderTaskLink(msg.created_task_id || null);
  }

  function renderBody(msg) {
    var bodyEl = el('em-read-body');
    if (!bodyEl) return;
    while (bodyEl.firstChild) bodyEl.removeChild(bodyEl.firstChild);

    if (msg.body_html && window.DOMPurify) {
      // Sanitize with DOMPurify, then parse into DOM nodes and append individually.
      // This avoids innerHTML on untrusted content while still rendering HTML email.
      var clean = DOMPurify.sanitize(msg.body_html, {
        FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form'],
        // Block inline style (CSS tracking pixels / url() exfil) and bare src on
        // non-img elements. Also block all remaining event handlers.
        FORBID_ATTR: [
          'onerror', 'onload', 'onclick', 'onmouseover', 'action',
          'style', 'background', 'dynsrc', 'lowsrc',
        ],
        // Strip external resource loads — images that phone home
        FORCE_BODY: true,
        ADD_TAGS: ['#text'],
      });
      var parser = new DOMParser();
      var parsed = parser.parseFromString(clean, 'text/html');
      var nodes = parsed.body.childNodes;
      for (var i = 0; i < nodes.length; i++) {
        bodyEl.appendChild(document.importNode(nodes[i], true));
      }
    } else if (msg.body_text) {
      bodyEl.textContent = msg.body_text;
    } else {
      var dim = document.createElement('span');
      dim.style.color = 'var(--archie-muted,#64748b)';
      dim.textContent = msg.preview || '(no content)';
      bodyEl.appendChild(dim);
    }
  }

  // ── Message actions ──────────────────────────────────────────────────
  function toggleStar() {
    if (!state.currentMessageId) return;
    apiPost('/api/email/messages/' + state.currentMessageId + '/star').then(function (d) {
      var label = el('em-star-label');
      var btn = el('em-star-btn');
      if (label) label.textContent = d.is_starred ? 'Unstar' : 'Star';
      if (btn) btn.style.color = d.is_starred ? '#f59e0b' : '';
      loadSidebar();
    }).catch(function () {});
  }

  function archiveMessage() {
    if (!state.currentMessageId) return;
    apiPost('/api/email/messages/' + state.currentMessageId + '/archive').then(function () {
      hide('em-read-content'); show('em-read-empty');
      state.currentMessageId = null;
      loadMessages(); loadCounts();
    }).catch(function () {});
  }

  function deleteMessage() {
    if (!state.currentMessageId) return;
    if (!confirm('Delete this message?')) return;
    apiDelete('/api/email/messages/' + state.currentMessageId).then(function () {
      hide('em-read-content'); show('em-read-empty');
      state.currentMessageId = null;
      loadMessages(); loadCounts();
    }).catch(function () {});
  }

  function triggerTriage() {
    if (!state.currentMessageId) return;
    var btn = el('em-triage-btn');
    if (btn) { btn.textContent = 'Triaging…'; btn.disabled = true; }
    apiPost('/api/email/messages/' + state.currentMessageId + '/triage').then(function () {
      setTimeout(function () {
        if (btn) { btn.textContent = 'Re-triage'; btn.disabled = false; }
        if (state.currentMessageId) selectMessage(state.currentMessageId);
      }, 3000);
    }).catch(function () {
      if (btn) { btn.textContent = 'Re-triage'; btn.disabled = false; }
    });
  }

  function markAllRead() {
    var ids = [];
    document.querySelectorAll('.em-msg-row.em-msg-unread').forEach(function (r) {
      if (r.dataset.messageId) ids.push(parseInt(r.dataset.messageId, 10));
    });
    if (!ids.length) return;
    apiPost('/api/email/messages/batch-read', { ids: ids }).then(function () {
      loadMessages(); loadCounts(); loadSidebar();
    }).catch(function () {});
  }

  function syncCurrent() {
    if (!state.currentMailboxId) return;
    var btn = el('em-sync-btn');
    if (btn) btn.style.opacity = '.4';
    apiPost('/api/email/sync/' + state.currentMailboxId).then(function () {
      loadMessages(); loadCounts(); loadSidebar();
    }).catch(function () {}).finally(function () {
      if (btn) btn.style.opacity = '';
    });
  }

  function showRulesPanel(container) {
    while (container.firstChild) container.removeChild(container.firstChild);

    var FIELD_LABELS = { from_address: 'From', subject: 'Subject', to_address: 'To', body_preview: 'Body' };
    var OP_LABELS = { contains: 'contains', not_contains: "doesn't contain", equals: 'equals', starts_with: 'starts with', ends_with: 'ends with' };
    var ACTION_LABELS = { set_priority: 'Set Priority', archive: 'Archive', star: 'Star', skip_triage: 'Skip Triage' };

    var allMailboxes = [];
    var filterMailboxId = null;
    var cachedRules = [];
    var listDiv = document.createElement('div');
    var statusDiv = document.createElement('div');
    statusDiv.style.cssText = 'font-size:11px;margin-top:5px;min-height:14px;';

    function setStatus(msg, ok) {
      statusDiv.textContent = msg;
      statusDiv.style.color = ok ? '#22c55e' : '#ef4444';
    }

    function reloadRules() {
      api('/api/email/rules').then(function (d) {
        cachedRules = d.rules || [];
        renderList(cachedRules);
      }).catch(function () {});
    }

    function renderList(rules) {
      while (listDiv.firstChild) listDiv.removeChild(listDiv.firstChild);
      var visible = filterMailboxId
        ? rules.filter(function (r) { return r.mailbox_id === filterMailboxId; })
        : rules;

      if (!visible.length) {
        var empty = document.createElement('div');
        empty.className = 'em-list-empty';
        empty.textContent = filterMailboxId ? 'No rules for this mailbox' : 'No rules yet';
        listDiv.appendChild(empty);
        return;
      }

      visible.forEach(function (r) {
        var item = document.createElement('div');
        item.className = 'em-msg-row';
        item.style.padding = '8px 10px';

        var top = document.createElement('div');
        top.className = 'em-msg-top';

        var nameSpan = document.createElement('span');
        nameSpan.className = 'em-msg-from-text';
        nameSpan.textContent = r.name;

        var badge = document.createElement('span');
        badge.className = 'em-priority-chip ' + (r.is_active ? 'em-priority-info' : 'em-priority-review');
        badge.textContent = r.is_active ? 'on' : 'off';
        badge.style.cursor = 'pointer';
        badge.title = 'Click to toggle';
        badge.addEventListener('click', function (e) {
          e.stopPropagation();
          api('/api/email/rules/' + r.id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: '{}' })
            .then(reloadRules).catch(function () {});
        });
        top.appendChild(nameSpan);
        top.appendChild(badge);

        var desc = document.createElement('div');
        desc.className = 'em-msg-preview-text';
        var condText = (FIELD_LABELS[r.condition_field] || r.condition_field) + ' '
          + (OP_LABELS[r.condition_op] || r.condition_op) + ' "' + r.condition_value + '"';
        var actText = (ACTION_LABELS[r.action_type] || r.action_type) + (r.action_value ? ': ' + r.action_value : '');
        desc.textContent = condText + ' → ' + actText;

        var bottom = document.createElement('div');
        bottom.className = 'em-msg-bottom';
        bottom.style.marginTop = '4px';

        var mbLabel = document.createElement('span');
        mbLabel.style.cssText = 'font-size:9px;color:#64748b;flex:1;';
        mbLabel.textContent = r.mailbox_address || 'all mailboxes';
        bottom.appendChild(mbLabel);

        var delBtn = document.createElement('button');
        delBtn.className = 'em-text-btn';
        delBtn.style.color = '#ef4444';
        delBtn.textContent = 'Delete';
        delBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          if (!confirm('Delete rule "' + r.name + '"?')) return;
          apiDelete('/api/email/rules/' + r.id).then(reloadRules).catch(function () {});
        });
        bottom.appendChild(delBtn);

        item.appendChild(top);
        item.appendChild(desc);
        item.appendChild(bottom);
        listDiv.appendChild(item);
      });
    }

    function buildForm() {
      var form = document.createElement('div');
      form.style.cssText = 'padding:10px;border-bottom:1px solid #1a1a2e;';

      function mkLabel(text) {
        var l = document.createElement('div');
        l.style.cssText = 'font-size:9px;color:#64748b;text-transform:uppercase;margin-bottom:2px;';
        l.textContent = text;
        return l;
      }
      function mkRow(label, input) {
        var w = document.createElement('div');
        w.style.marginBottom = '6px';
        w.appendChild(mkLabel(label));
        w.appendChild(input);
        return w;
      }
      function mkSel(opts) {
        var s = document.createElement('select');
        s.className = 'em-view-select';
        s.style.width = '100%';
        opts.forEach(function (o) { var op = document.createElement('option'); op.value = o[0]; op.textContent = o[1]; s.appendChild(op); });
        return s;
      }

      var nameInput = document.createElement('input');
      nameInput.className = 'em-search';
      nameInput.style.width = '100%';
      nameInput.placeholder = 'Rule name';

      var mbSel = document.createElement('select');
      mbSel.className = 'em-view-select';
      mbSel.style.width = '100%';
      var mbAllOpt = document.createElement('option');
      mbAllOpt.value = '';
      mbAllOpt.textContent = 'All mailboxes';
      mbSel.appendChild(mbAllOpt);
      allMailboxes.forEach(function (mb) {
        var o = document.createElement('option');
        o.value = mb.id;
        o.textContent = mb.address;
        mbSel.appendChild(o);
      });

      var fieldSel = mkSel([['from_address','From Address'],['subject','Subject'],['to_address','To Address'],['body_preview','Body Preview']]);
      var opSel = mkSel([['contains','Contains'],['not_contains','Not Contains'],['equals','Equals'],['starts_with','Starts With'],['ends_with','Ends With']]);

      var valInput = document.createElement('input');
      valInput.className = 'em-search';
      valInput.style.width = '100%';
      valInput.placeholder = 'Value to match';

      var actionSel = mkSel([['set_priority','Set Priority'],['archive','Archive'],['star','Star'],['skip_triage','Skip Triage']]);
      var prioritySel = mkSel([['action','Action'],['review','Review'],['info','Info']]);
      var priorityRow = mkRow('Priority', prioritySel);
      actionSel.addEventListener('change', function () {
        priorityRow.style.display = actionSel.value === 'set_priority' ? '' : 'none';
      });
      priorityRow.style.display = 'none';

      var addBtn = document.createElement('button');
      addBtn.className = 'em-sidebar-action';
      addBtn.style.cssText = 'width:100%;margin-top:6px;color:#22c55e;border-color:#22c55e;';
      addBtn.textContent = '+ Add Rule';
      addBtn.addEventListener('click', function () {
        var name = nameInput.value.trim();
        var val = valInput.value.trim();
        if (!name) { setStatus('Rule name is required', false); return; }
        if (!val) { setStatus('Match value is required', false); return; }
        setStatus('Saving…', true);
        addBtn.disabled = true;
        api('/api/email/rules', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: name,
            mailbox_id: mbSel.value ? parseInt(mbSel.value) : null,
            condition_field: fieldSel.value,
            condition_op: opSel.value,
            condition_value: val,
            action_type: actionSel.value,
            action_value: actionSel.value === 'set_priority' ? prioritySel.value : null,
          }),
        }).then(function (r) {
          addBtn.disabled = false;
          if (r.success) {
            nameInput.value = '';
            valInput.value = '';
            setStatus('Rule created', true);
            reloadRules();
          } else {
            setStatus('Error: ' + (r.error || 'unknown'), false);
          }
        }).catch(function () {
          addBtn.disabled = false;
          setStatus('Request failed', false);
        });
      });

      form.appendChild(mkRow('Rule Name', nameInput));
      if (allMailboxes.length) form.appendChild(mkRow('Mailbox', mbSel));
      form.appendChild(mkRow('If field', fieldSel));
      form.appendChild(mkRow('Operator', opSel));
      form.appendChild(mkRow('Value', valInput));
      form.appendChild(mkRow('Then', actionSel));
      form.appendChild(priorityRow);
      form.appendChild(addBtn);
      form.appendChild(statusDiv);
      container.appendChild(form);

      if (allMailboxes.length) {
        var filterBar = document.createElement('div');
        filterBar.style.cssText = 'padding:6px 10px;display:flex;align-items:center;gap:6px;border-bottom:1px solid #1a1a2e;';
        var filterLbl = document.createElement('span');
        filterLbl.style.cssText = 'font-size:9px;color:#64748b;text-transform:uppercase;white-space:nowrap;';
        filterLbl.textContent = 'Filter:';
        var filterSel = document.createElement('select');
        filterSel.className = 'em-view-select';
        filterSel.style.flex = '1';
        var allFOpt = document.createElement('option');
        allFOpt.value = '';
        allFOpt.textContent = 'All mailboxes';
        filterSel.appendChild(allFOpt);
        allMailboxes.forEach(function (mb) {
          var o = document.createElement('option');
          o.value = mb.id;
          o.textContent = mb.address;
          filterSel.appendChild(o);
        });
        filterSel.addEventListener('change', function () {
          filterMailboxId = filterSel.value ? parseInt(filterSel.value) : null;
          renderList(cachedRules);
        });
        filterBar.appendChild(filterLbl);
        filterBar.appendChild(filterSel);
        container.appendChild(filterBar);
      }

      container.appendChild(listDiv);
    }

    Promise.all([
      api('/api/email/rules').catch(function () { return { rules: [] }; }),
      api('/api/email/mailboxes').catch(function () { return { mailboxes: [] }; }),
    ]).then(function (results) {
      allMailboxes = (results[1].mailboxes || []).sort(function (a, b) {
        return (a.address || '').localeCompare(b.address || '');
      });
      cachedRules = results[0].rules || [];
      buildForm();
      renderList(cachedRules);
    }).catch(function () {
      var err = document.createElement('div');
      err.className = 'em-list-empty';
      err.textContent = 'Failed to load rules';
      container.appendChild(err);
    });
  }

  function showSlaPanel(container) {
    while (container.firstChild) container.removeChild(container.firstChild);

    var currentWindow = 30;

    function fmtHours(h) {
      if (h === null || h === undefined) return '—';
      if (h < 1) return Math.round(h * 60) + 'm';
      return h.toFixed(1) + 'h';
    }

    function renderDashboard(data) {
      while (container.firstChild) container.removeChild(container.firstChild);

      var s = data.summary;

      // Window toggle
      var toggleRow = document.createElement('div');
      toggleRow.style.cssText = 'display:flex;gap:6px;margin-bottom:10px;align-items:center;';
      var toggleLabel = document.createElement('span');
      toggleLabel.style.cssText = 'font-size:11px;color:#6b7280;';
      toggleLabel.textContent = 'Window:';
      toggleRow.appendChild(toggleLabel);
      [7, 30].forEach(function (w) {
        var btn = document.createElement('button');
        btn.className = 'em-text-btn';
        btn.textContent = w + 'd';
        btn.style.cssText = 'padding:2px 8px;font-size:11px;border-radius:3px;' +
          (w === currentWindow
            ? 'color:#00d4ff;border:1px solid #00d4ff;'
            : 'color:#9ca3af;border:1px solid #333;');
        btn.addEventListener('click', function () {
          if (w !== currentWindow) { currentWindow = w; loadData(); }
        });
        toggleRow.appendChild(btn);
      });
      container.appendChild(toggleRow);

      // Summary cards (2×2 grid)
      var cards = document.createElement('div');
      cards.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:10px;';
      [
        { label: 'Received (' + s.window_days + 'd)', value: s.total_received, color: '#00d4ff' },
        { label: 'Unread', value: s.total_unread, color: s.total_unread > 0 ? '#f59e0b' : '#22c55e' },
        { label: 'SLA Breach >24h', value: s.total_breach_24h, color: s.total_breach_24h > 0 ? '#ef4444' : '#22c55e' },
        { label: 'Avg Read Time', value: fmtHours(s.avg_read_hours), color: '#a78bfa' },
      ].forEach(function (c) {
        var card = document.createElement('div');
        card.style.cssText = 'background:#0d0d1a;border:1px solid #1a1a2e;border-radius:4px;padding:8px;text-align:center;';
        var val = document.createElement('div');
        val.style.cssText = 'font-size:20px;font-weight:bold;color:' + c.color + ';';
        val.textContent = c.value;
        var lbl = document.createElement('div');
        lbl.style.cssText = 'font-size:10px;color:#6b7280;margin-top:2px;';
        lbl.textContent = c.label;
        card.appendChild(val);
        card.appendChild(lbl);
        cards.appendChild(card);
      });
      container.appendChild(cards);

      // Per-mailbox table
      var tableWrap = document.createElement('div');
      tableWrap.style.cssText = 'overflow-x:auto;';
      var table = document.createElement('table');
      table.style.cssText = 'width:100%;border-collapse:collapse;font-size:11px;';

      var thead = document.createElement('thead');
      var hrow = document.createElement('tr');
      ['Mailbox', 'Recv', 'Unread', '>24h', '>48h', 'Avg'].forEach(function (h) {
        var th = document.createElement('th');
        th.style.cssText = 'text-align:left;padding:4px 6px;border-bottom:1px solid #1a1a2e;color:#6b7280;white-space:nowrap;';
        th.textContent = h;
        hrow.appendChild(th);
      });
      thead.appendChild(hrow);
      table.appendChild(thead);

      var tbody = document.createElement('tbody');
      if (!data.mailboxes || data.mailboxes.length === 0) {
        var emr = document.createElement('tr');
        var emc = document.createElement('td');
        emc.colSpan = 6;
        emc.style.cssText = 'padding:12px;text-align:center;color:#6b7280;';
        emc.textContent = 'No mailbox data';
        emr.appendChild(emc);
        tbody.appendChild(emr);
      } else {
        data.mailboxes.forEach(function (m) {
          var tr = document.createElement('tr');
          tr.style.borderBottom = '1px solid #111827';
          [
            { text: (m.display_name || m.address).split('@')[0], tip: m.address, color: '#e5e7eb', truncate: true },
            { text: m.received, color: '#9ca3af' },
            { text: m.unread, color: m.unread > 0 ? '#f59e0b' : '#9ca3af' },
            { text: m.breach_24h, color: m.breach_24h > 0 ? '#ef4444' : '#22c55e' },
            { text: m.breach_48h, color: m.breach_48h > 0 ? '#dc2626' : '#22c55e' },
            { text: fmtHours(m.avg_read_hours), color: '#a78bfa' },
          ].forEach(function (c) {
            var td = document.createElement('td');
            td.style.cssText = 'padding:4px 6px;white-space:nowrap;color:' + c.color + ';';
            if (c.truncate) {
              td.style.maxWidth = '90px';
              td.style.overflow = 'hidden';
              td.style.textOverflow = 'ellipsis';
              td.title = c.tip || '';
            }
            td.textContent = c.text;
            tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
      }
      table.appendChild(tbody);
      tableWrap.appendChild(table);
      container.appendChild(tableWrap);
    }

    function loadData() {
      while (container.firstChild) container.removeChild(container.firstChild);
      var loading = document.createElement('div');
      loading.className = 'em-list-empty';
      loading.textContent = 'Loading SLA data…';
      container.appendChild(loading);
      api('/api/email/sla/stats?window=' + currentWindow)
        .then(function (data) { renderDashboard(data); })
        .catch(function () {
          while (container.firstChild) container.removeChild(container.firstChild);
          var err = document.createElement('div');
          err.className = 'em-list-empty';
          err.textContent = 'Failed to load SLA data';
          container.appendChild(err);
        });
    }

    loadData();
  }

  function toggleThread() {
    var banner = el('em-thread-banner');
    if (!banner || !banner.dataset.threadId) return;
    var threadBody = el('em-thread-body');
    if (!threadBody) return;

    if (threadBody.style.display !== 'none' && threadBody.firstChild) {
      threadBody.style.display = 'none';
      setText('em-thread-toggle-label', 'View thread');
      return;
    }

    setText('em-thread-toggle-label', 'Loading…');
    api('/api/email/threads/' + banner.dataset.threadId).then(function (d) {
      while (threadBody.firstChild) threadBody.removeChild(threadBody.firstChild);
      (d.messages || []).forEach(function (m, i) {
        var wrap = document.createElement('div');
        wrap.style.cssText = 'border-top:1px solid #1a1a2e;padding:10px 0 6px;';

        var meta = document.createElement('div');
        meta.style.cssText = 'font-size:11px;color:#7eb8f7;margin-bottom:4px;';
        meta.textContent = (m.from_address || '') + ' · ' + (m.received_at ? new Date(m.received_at).toLocaleString() : '');

        var body = document.createElement('div');
        body.style.cssText = 'font-size:12px;color:#94a3b8;white-space:pre-wrap;';
        body.textContent = (m.body_text || m.preview || '').slice(0, 500);

        wrap.appendChild(meta);
        wrap.appendChild(body);
        threadBody.appendChild(wrap);
      });
      threadBody.style.display = '';
      setText('em-thread-toggle-label', 'Hide thread');
    }).catch(function () {
      setText('em-thread-toggle-label', 'View thread');
    });
  }

  function draftReply() {
    if (!state.currentMessageId) return;
    var btn = el('em-draft-reply-btn');
    var label = el('em-draft-reply-label');
    if (btn) { btn.disabled = true; }
    if (label) label.textContent = 'Drafting…';

    apiPost('/api/email/messages/' + state.currentMessageId + '/draft-reply').then(function (d) {
      if (label) label.textContent = 'AI Reply';
      if (btn) btn.disabled = false;
      if (d.draft) {
        var subjEl = el('em-read-subject');
        var fromEl = el('em-read-from');
        var dateEl = el('em-read-date');
        var quote = '\n\n---\nOn ' + (dateEl ? dateEl.textContent : '') + ', ' +
          (fromEl ? fromEl.textContent : '') + ' wrote:\n[See original message]';
        var subject = subjEl ? 'Re: ' + subjEl.textContent : '';
        var myMailbox = state.currentMsg && state.currentMsg.mailbox_address;
        openCompose(fromEl ? fromEl.textContent : '', subject, d.draft + quote, myMailbox);
        // Show agent attribution in compose status
        var statusEl = el('em-compose-status');
        if (statusEl) {
          statusEl.style.display = '';
          statusEl.style.color = '#22c55e';
          statusEl.textContent = '✦ Drafted by ' + (d.agent || 'R.E.S.O.L.V.E.');
        }
      } else {
        alert('Could not generate draft: ' + (d.error || 'unknown'));
      }
    }).catch(function () {
      if (label) label.textContent = 'AI Reply';
      if (btn) btn.disabled = false;
      alert('Dispatch failed — agent may be offline');
    });
  }

  function renderTaskLink(taskId) {
    var span = el('em-task-link');
    if (!span) return;
    while (span.firstChild) span.removeChild(span.firstChild);
    if (!taskId) { span.style.display = 'none'; return; }
    span.appendChild(document.createTextNode('✓ Task '));
    var link = document.createElement('a');
    link.href = '/tools/consciousness#devhq';
    link.target = '_blank';
    link.rel = 'noopener';
    link.style.color = '#38bdf8';
    link.textContent = '#' + taskId;
    span.appendChild(link);
    span.style.display = '';
  }

  function createTaskFromEmail() {
    if (!state.currentMessageId) return;
    var btn = el('em-create-task-btn');
    var label = el('em-create-task-label');
    if (btn) btn.disabled = true;
    if (label) label.textContent = 'Creating…';

    apiPost('/api/email/messages/' + state.currentMessageId + '/create-task').then(function (d) {
      if (label) label.textContent = 'Create Task';
      if (btn) btn.disabled = false;
      if (d.success && d.task_id) {
        if (state.currentMsg) state.currentMsg.created_task_id = d.task_id;
        renderTaskLink(d.task_id);
      } else {
        alert('Could not create task: ' + (d.error || 'unknown'));
      }
    }).catch(function () {
      if (label) label.textContent = 'Create Task';
      if (btn) btn.disabled = false;
      alert('Dispatch failed — agent may be offline');
    });
  }

  function replyMessage() {
    var fromEl = el('em-read-from');
    var subjEl = el('em-read-subject');
    var dateEl = el('em-read-date');
    var bodyEl = el('em-read-body');
    var quote = bodyEl ? '\n\n---\nOn ' + (dateEl ? dateEl.textContent : '') + ', ' +
      (fromEl ? fromEl.textContent : '') + ' wrote:\n' + (bodyEl.textContent || '').slice(0, 2000) : '';
    var myMailbox = state.currentMsg && state.currentMsg.mailbox_address;
    openCompose(fromEl ? fromEl.textContent : '', subjEl ? 'Re: ' + subjEl.textContent : '', quote, myMailbox);
  }

  function forwardMessage() {
    var subjEl = el('em-read-subject');
    var fromEl = el('em-read-from');
    var dateEl = el('em-read-date');
    var bodyEl = el('em-read-body');
    var quote = bodyEl ? '\n\n---\n-------- Forwarded Message --------\nFrom: ' +
      (fromEl ? fromEl.textContent : '') + '\nDate: ' + (dateEl ? dateEl.textContent : '') +
      '\n\n' + (bodyEl.textContent || '').slice(0, 2000) : '';
    openCompose('', subjEl ? 'Fwd: ' + subjEl.textContent : '', quote);
  }

  // ── Provision owner inbox ─────────────────────────────────────────────
  function provisionOwner() {
    if (!confirm('Provision kytran@kytranempowerment.com with 10 GB quota?')) return;
    var btn = el('em-provision-owner-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Provisioning…'; }
    apiPost('/api/email/mailboxes/provision-owner').then(function (d) {
      if (d.success) {
        if (btn) btn.textContent = '✓ Provisioned';
        loadSidebar();
      } else {
        if (btn) { btn.disabled = false; btn.textContent = 'Provision kytran@ inbox'; }
        alert('Failed: ' + (d.error || 'unknown'));
      }
    }).catch(function () {
      if (btn) { btn.disabled = false; btn.textContent = 'Provision kytran@ inbox'; }
      alert('Request failed — check server logs');
    });
  }

  // ── Compose modal ─────────────────────────────────────────────────────
  function openCompose(toAddr, subject, quotedBody, fromAddr) {
    api('/api/email/compose/mailboxes').then(function (d) {
      var sel = el('em-compose-from');
      if (!sel) return;
      while (sel.firstChild) sel.removeChild(sel.firstChild);
      (d.mailboxes || []).forEach(function (m) {
        var opt = document.createElement('option');
        opt.value = m.address;
        opt.textContent = m.display_name ? m.display_name + ' <' + m.address + '>' : m.address;
        sel.appendChild(opt);
      });
      if (fromAddr) sel.value = fromAddr;
    }).catch(function () {});

    var toEl = el('em-compose-to');
    var subjEl = el('em-compose-subject');
    var bodyEl = el('em-compose-body');
    var statusEl = el('em-compose-status');
    var sendBtn = el('em-compose-send');

    if (toEl) toEl.value = toAddr || '';
    if (subjEl) subjEl.value = subject || '';
    if (bodyEl) bodyEl.value = quotedBody || '';
    if (statusEl) { statusEl.style.display = 'none'; statusEl.textContent = ''; }
    if (sendBtn) sendBtn.disabled = false;

    var modal = el('em-compose-modal');
    if (modal) modal.classList.add('active');
  }

  function closeCompose() {
    var modal = el('em-compose-modal');
    if (modal) modal.classList.remove('active');
  }

  function sendCompose() {
    var fromAddr = (el('em-compose-from') || {}).value || '';
    var toAddr = ((el('em-compose-to') || {}).value || '').trim();
    var subject = ((el('em-compose-subject') || {}).value || '').trim();
    var body = ((el('em-compose-body') || {}).value || '').trim();
    var statusEl = el('em-compose-status');
    var sendBtn = el('em-compose-send');

    if (!toAddr || !subject) {
      if (statusEl) { statusEl.style.display = ''; statusEl.style.color = '#ef4444'; statusEl.textContent = 'To and Subject are required.'; }
      return;
    }

    if (sendBtn) sendBtn.disabled = true;
    if (statusEl) { statusEl.style.display = ''; statusEl.style.color = '#64748b'; statusEl.textContent = 'Sending…'; }

    apiPost('/api/email/compose/send', { from_address: fromAddr, to_address: toAddr, subject: subject, body: body })
      .then(function (d) {
        if (d.success) {
          if (statusEl) { statusEl.style.color = '#22c55e'; statusEl.textContent = '✓ Sent'; }
          setTimeout(closeCompose, 1200);
        } else {
          if (statusEl) { statusEl.style.color = '#ef4444'; statusEl.textContent = d.error || 'Send failed'; }
          if (sendBtn) sendBtn.disabled = false;
        }
      }).catch(function () {
        if (statusEl) { statusEl.style.color = '#ef4444'; statusEl.textContent = 'Network error'; }
        if (sendBtn) sendBtn.disabled = false;
      });
  }

  // ── Pagination ────────────────────────────────────────────────────────
  function prevPage() { if (state.currentPage <= 1) return; state.currentPage--; loadMessages(); }
  function nextPage() { state.currentPage++; loadMessages(); }

  // ── Search (debounced 350ms) ──────────────────────────────────────────
  function onSearch(value) {
    state.searchQuery = value;
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(function () { state.currentPage = 1; loadMessages(); }, 350);
  }

  // ── Mobile / Fold 5 panel sliding ─────────────────────────────────────
  function slideTo(panel) {
    var workspace = document.querySelector('.em-workspace');
    if (!workspace) return;
    workspace.classList.remove('em-panel--list', 'em-panel--read');
    if (panel === 'list') workspace.classList.add('em-panel--list');
    if (panel === 'read') workspace.classList.add('em-panel--read');
  }

  // ── Toast notifications ───────────────────────────────────────────────
  function showToast(msg, type) {
    var t = document.createElement('div');
    t.className = 'em-toast em-toast--' + (type || 'info');
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () {
      t.style.opacity = '0';
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 400);
    }, 3500);
  }

  // ── Manual bulk refresh ───────────────────────────────────────────────
  function refreshAllMailboxes() {
    var btn = el('em-refresh-btn');
    var icon = el('em-refresh-icon');
    if (btn && btn.dataset.syncing) return; // debounce — ignore double-clicks
    if (btn) btn.dataset.syncing = '1';

    // Spin the icon while running
    if (icon) icon.style.animation = 'em-spin 1s linear infinite';

    api('/api/email/sync/bulk', { method: 'POST' })
      .then(function (d) {
        loadSidebar();
        loadCounts();
        var msg = d.new_messages > 0
          ? '↻ Synced ' + d.synced + ' mailbox' + (d.synced !== 1 ? 'es' : '') +
            ' — ' + d.new_messages + ' new message' + (d.new_messages !== 1 ? 's' : '')
          : '↻ All mailboxes up to date (' + d.synced + ' checked)';
        showToast(msg, 'success');
      })
      .catch(function () {
        showToast('Sync failed — check logs', 'error');
      })
      .finally(function () {
        if (icon) icon.style.animation = '';
        if (btn) delete btn.dataset.syncing;
      });
  }

  // ── Auto-refresh ──────────────────────────────────────────────────────
  function startRefresh() {
    state.refreshTimer = setInterval(function () { loadCounts(); loadSidebar(); }, 30000);
  }

  // ── SSE — real-time new-mail push (T3279) ─────────────────────────────
  function initSSE() {
    if (!window.EventSource) return;
    try {
      var src = new EventSource(BASE + '/api/email/stream');
      src.onmessage = function (e) {
        try {
          var d = JSON.parse(e.data);
          if (d.type === 'newMail') {
            loadCounts();
            loadSidebar();
            if (state.currentMailboxId === d.mailbox_id) {
              loadMessages();
            }
          }
        } catch (_) {}
      };
      src.onerror = function () {
        // Browser auto-reconnects; no action needed
      };
    } catch (_) {}
  }

  // ── Wire events ───────────────────────────────────────────────────────
  function wireEvents() {
    document.querySelectorAll('.em-nav-item[data-view]').forEach(function (item) {
      item.addEventListener('click', function () { selectView(item.dataset.view); });
    });

    var viewSel = el('em-view-select');
    if (viewSel) viewSel.addEventListener('change', function () { state.currentPage = 1; loadMessages(); });

    var searchEl = el('em-search');
    if (searchEl) searchEl.addEventListener('input', function () { onSearch(searchEl.value); });

    function wire(id, fn) { var e = el(id); if (e) e.addEventListener('click', fn); }

    wire('em-mark-all-btn', markAllRead);
    wire('em-sync-btn', syncCurrent);
    wire('em-prev-btn', prevPage);
    wire('em-next-btn', nextPage);
    wire('em-star-btn', toggleStar);
    wire('em-archive-btn', archiveMessage);
    wire('em-delete-btn', deleteMessage);
    wire('em-triage-btn', triggerTriage);
    wire('em-thread-toggle', toggleThread);
    wire('em-reply-btn', replyMessage);
    wire('em-forward-btn', forwardMessage);
    wire('em-draft-reply-btn', draftReply);
    wire('em-create-task-btn', createTaskFromEmail);
    wire('em-provision-owner-btn', provisionOwner);
    wire('em-refresh-btn', refreshAllMailboxes);
    wire('em-compose-open', function () { openCompose(); });
    wire('em-compose-close', closeCompose);
    wire('em-compose-cancel', closeCompose);
    wire('em-compose-send', sendCompose);

    var modal = el('em-compose-modal');
    if (modal) modal.addEventListener('click', function (e) { if (e.target === modal) closeCompose(); });
  }

  // ── Init ──────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    wireEvents();
    loadSidebar();
    loadCounts();
    selectView('all');
    startRefresh();
    initSSE();
  });

}());
