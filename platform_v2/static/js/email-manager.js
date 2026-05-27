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
    var tabs = [['mailboxes', 'Mailboxes'], ['rules', 'Rules']];
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

    function renderRules(rules) {
      while (container.firstChild) container.removeChild(container.firstChild);

      // Create rule form
      var form = document.createElement('div');
      form.style.cssText = 'padding:10px;border-bottom:1px solid #1a1a2e;';

      function row(label, el_) {
        var wrap = document.createElement('div');
        wrap.style.cssText = 'margin-bottom:6px;';
        var lbl = document.createElement('div');
        lbl.style.cssText = 'font-size:9px;color:#64748b;text-transform:uppercase;margin-bottom:2px;';
        lbl.textContent = label;
        wrap.appendChild(lbl);
        wrap.appendChild(el_);
        return wrap;
      }

      function sel(opts) {
        var s = document.createElement('select');
        s.className = 'em-view-select';
        s.style.width = '100%';
        opts.forEach(function (o) {
          var opt = document.createElement('option');
          opt.value = o[0]; opt.textContent = o[1];
          s.appendChild(opt);
        });
        return s;
      }

      var nameInput = document.createElement('input');
      nameInput.className = 'em-search';
      nameInput.style.width = '100%';
      nameInput.placeholder = 'Rule name';

      var fieldSel = sel([['from_address','From Address'],['subject','Subject'],['to_address','To Address'],['body_preview','Body Preview']]);
      var opSel = sel([['contains','Contains'],['not_contains','Not Contains'],['equals','Equals'],['starts_with','Starts With'],['ends_with','Ends With']]);

      var valInput = document.createElement('input');
      valInput.className = 'em-search';
      valInput.style.width = '100%';
      valInput.placeholder = 'Value to match';

      var actionSel = sel([['set_priority','Set Priority'],['archive','Archive'],['star','Star'],['skip_triage','Skip Triage']]);
      var prioritySel = sel([['action','Action'],['review','Review'],['info','Info']]);
      var priorityRow = row('Priority', prioritySel);

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
        if (!name || !val) { alert('Name and value are required'); return; }
        apiPost('/api/email/rules', {
          name: name,
          condition_field: fieldSel.value,
          condition_op: opSel.value,
          condition_value: val,
          action_type: actionSel.value,
          action_value: actionSel.value === 'set_priority' ? prioritySel.value : null,
        }).then(function (r) {
          if (r.success) { nameInput.value = ''; valInput.value = ''; api('/api/email/rules').then(function (d) { renderRules(d.rules || []); }); }
          else alert('Error: ' + (r.error || 'unknown'));
        }).catch(function () { alert('Request failed'); });
      });

      form.appendChild(row('Rule Name', nameInput));
      form.appendChild(row('If field', fieldSel));
      form.appendChild(row('Operator', opSel));
      form.appendChild(row('Value', valInput));
      form.appendChild(row('Then', actionSel));
      form.appendChild(priorityRow);
      form.appendChild(addBtn);
      container.appendChild(form);

      if (!rules.length) {
        var empty = document.createElement('div');
        empty.className = 'em-list-empty';
        empty.textContent = 'No rules yet';
        container.appendChild(empty);
        return;
      }

      rules.forEach(function (r) {
        var row_ = document.createElement('div');
        row_.className = 'em-msg-row';
        row_.style.padding = '8px 10px';

        var top = document.createElement('div');
        top.className = 'em-msg-top';

        var name = document.createElement('span');
        name.className = 'em-msg-from-text';
        name.textContent = r.name;

        var status = document.createElement('span');
        status.className = 'em-priority-chip ' + (r.is_active ? 'em-priority-info' : 'em-priority-review');
        status.textContent = r.is_active ? 'active' : 'off';
        status.style.cursor = 'pointer';
        status.title = 'Toggle';
        status.addEventListener('click', function (e) {
          e.stopPropagation();
          apiPost('/api/email/rules/' + r.id, null, 'PATCH').then(function () {
            api('/api/email/rules').then(function (d) { renderRules(d.rules || []); });
          }).catch(function () {});
        });

        top.appendChild(name);
        top.appendChild(status);

        var desc = document.createElement('div');
        desc.className = 'em-msg-preview-text';
        desc.textContent = r.condition_field + ' ' + r.condition_op + ' "' + r.condition_value + '" → ' + r.action_type + (r.action_value ? ' (' + r.action_value + ')' : '');

        var delBtn = document.createElement('button');
        delBtn.className = 'em-text-btn';
        delBtn.style.color = '#ef4444';
        delBtn.textContent = 'Delete';
        delBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          if (!confirm('Delete rule "' + r.name + '"?')) return;
          apiDelete('/api/email/rules/' + r.id).then(function () {
            api('/api/email/rules').then(function (d) { renderRules(d.rules || []); });
          }).catch(function () {});
        });

        var acts = document.createElement('div');
        acts.className = 'em-msg-bottom';
        acts.style.marginTop = '4px';
        acts.appendChild(delBtn);

        row_.appendChild(top);
        row_.appendChild(desc);
        row_.appendChild(acts);
        container.appendChild(row_);
      });
    }

    // PATCH helper for rules toggle
    function apiPost(path, body, method) {
      return api(path, {
        method: method || 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      });
    }

    api('/api/email/rules').then(function (d) {
      renderRules(d.rules || []);
    }).catch(function () {
      var err = document.createElement('div');
      err.className = 'em-list-empty';
      err.textContent = 'Failed to load rules';
      container.appendChild(err);
    });
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
