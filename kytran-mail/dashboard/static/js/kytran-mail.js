/* Kytran Mail — Dashboard Interactivity (IIFE) */
(function () {
    'use strict';

    /** HTML-escape a string safely */
    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s || '';
        return d.innerHTML;
    }

    /** Show a toast notification */
    function toast(message, type) {
        var container = document.getElementById('toast-container');
        if (!container) return;
        var el = document.createElement('div');
        el.className = 'km-toast';
        if (type === 'success') el.className += ' success';
        if (type === 'error') el.className += ' error';
        el.textContent = message;
        container.appendChild(el);
        setTimeout(function () {
            if (el.parentNode) el.parentNode.removeChild(el);
        }, 4000);
    }

    /** Switch between tabs */
    function switchTab(name) {
        // Update tab buttons
        var tabs = document.querySelectorAll('.km-tab');
        for (var i = 0; i < tabs.length; i++) {
            if (tabs[i].getAttribute('data-tab') === name) {
                tabs[i].classList.add('active');
            } else {
                tabs[i].classList.remove('active');
            }
        }
        // Update tab panels
        var panels = document.querySelectorAll('.km-tab-panel');
        for (var j = 0; j < panels.length; j++) {
            if (panels[j].id === 'tab-' + name) {
                panels[j].classList.add('active');
            } else {
                panels[j].classList.remove('active');
            }
        }
        // Load data for active tab
        if (name === 'dashboard') loadStatus();
        if (name === 'mailboxes') loadMailboxes();
        if (name === 'settings') loadStatus();
    }

    /** GET /api/status and update stat cards */
    function loadStatus() {
        fetch('/api/status')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var elMailboxes = document.getElementById('stat-mailboxes');
                var elStorage = document.getElementById('stat-storage');
                var elQueue = document.getElementById('stat-queue');
                var elStatus = document.getElementById('stat-status');

                if (elMailboxes) elMailboxes.textContent = data.mailbox_count != null ? data.mailbox_count : '--';
                if (elStorage) elStorage.textContent = data.storage || '--';
                if (elQueue) elQueue.textContent = data.queue_size != null ? data.queue_size : '0';

                if (elStatus) {
                    var online = data.stalwart_online;
                    elStatus.textContent = online ? 'ONLINE' : 'OFFLINE';
                    elStatus.className = 'value ' + (online ? 'online' : 'offline');
                }

                // Settings tab DKIM / relay
                var elDkim = document.getElementById('settings-dkim');
                if (elDkim) elDkim.textContent = data.dkim_status || '--';

                var elRelay = document.getElementById('settings-relay');
                if (elRelay) elRelay.textContent = data.relay_host || 'None configured';
            })
            .catch(function () {
                toast('Failed to load status', 'error');
            });
    }

    /** GET /api/mailboxes and build table rows with safe DOM methods */
    function loadMailboxes() {
        fetch('/api/mailboxes')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var mailboxes = data.mailboxes || [];
                var tbody = document.getElementById('mailbox-tbody');
                var countEl = document.getElementById('mailbox-count');

                if (countEl) countEl.textContent = 'Mailboxes (' + mailboxes.length + ')';
                if (!tbody) return;

                // Clear existing rows
                while (tbody.firstChild) {
                    tbody.removeChild(tbody.firstChild);
                }

                for (var i = 0; i < mailboxes.length; i++) {
                    var mb = mailboxes[i];
                    var tr = document.createElement('tr');

                    var tdName = document.createElement('td');
                    tdName.textContent = mb.name || '';
                    tr.appendChild(tdName);

                    var tdEmail = document.createElement('td');
                    tdEmail.textContent = mb.email || '';
                    tr.appendChild(tdEmail);

                    var tdDisplay = document.createElement('td');
                    tdDisplay.textContent = mb.display_name || '';
                    tr.appendChild(tdDisplay);

                    var tdStatus = document.createElement('td');
                    var badge = document.createElement('span');
                    var isActive = mb.enabled !== false;
                    badge.className = 'km-badge ' + (isActive ? 'active' : 'disabled');
                    badge.textContent = isActive ? 'ACTIVE' : 'DISABLED';
                    tdStatus.appendChild(badge);
                    tr.appendChild(tdStatus);

                    var tdStorage = document.createElement('td');
                    tdStorage.textContent = mb.storage || '--';
                    tr.appendChild(tdStorage);

                    var tdActions = document.createElement('td');
                    var actionsDiv = document.createElement('div');
                    actionsDiv.className = 'km-actions';

                    // Toggle button
                    var btnToggle = document.createElement('button');
                    btnToggle.className = 'km-btn-sm ' + (isActive ? 'warn' : 'ok');
                    btnToggle.textContent = isActive ? 'DISABLE' : 'ENABLE';
                    (function (name, enabled) {
                        btnToggle.addEventListener('click', function () {
                            toggleMailbox(name, enabled);
                        });
                    })(mb.name, !isActive);
                    actionsDiv.appendChild(btnToggle);

                    // Reset password button
                    var btnReset = document.createElement('button');
                    btnReset.className = 'km-btn-sm';
                    btnReset.textContent = 'RESET PW';
                    (function (name) {
                        btnReset.addEventListener('click', function () {
                            resetPassword(name);
                        });
                    })(mb.name);
                    actionsDiv.appendChild(btnReset);

                    // Delete button
                    var btnDelete = document.createElement('button');
                    btnDelete.className = 'km-btn-sm danger';
                    btnDelete.textContent = 'DELETE';
                    (function (name) {
                        btnDelete.addEventListener('click', function () {
                            deleteMailbox(name);
                        });
                    })(mb.name);
                    actionsDiv.appendChild(btnDelete);

                    tdActions.appendChild(actionsDiv);
                    tr.appendChild(tdActions);

                    tbody.appendChild(tr);
                }
            })
            .catch(function () {
                toast('Failed to load mailboxes', 'error');
            });
    }

    /** POST /api/mailboxes — create a new mailbox from modal form */
    function createMailbox() {
        var name = document.getElementById('new-name').value.trim();
        var displayName = document.getElementById('new-display-name').value.trim();
        var password = document.getElementById('new-password').value;
        var quota = parseInt(document.getElementById('new-quota').value, 10) || 1024;

        if (!name) { toast('Name is required', 'error'); return; }
        if (!password || password.length < 8) { toast('Password must be at least 8 characters', 'error'); return; }

        fetch('/api/mailboxes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                display_name: displayName,
                password: password,
                quota_mb: quota
            })
        })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (res.ok) {
                    toast('Mailbox created: ' + name, 'success');
                    closeModal();
                    loadMailboxes();
                    loadStatus();
                } else {
                    toast(res.data.error || 'Failed to create mailbox', 'error');
                }
            })
            .catch(function () {
                toast('Network error creating mailbox', 'error');
            });
    }

    /** DELETE /api/mailboxes/<name> */
    function deleteMailbox(name) {
        if (!confirm('Delete mailbox "' + name + '"? This cannot be undone.')) return;

        fetch('/api/mailboxes/' + encodeURIComponent(name), {
            method: 'DELETE'
        })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (res.ok) {
                    toast('Mailbox deleted: ' + name, 'success');
                    loadMailboxes();
                    loadStatus();
                } else {
                    toast(res.data.error || 'Failed to delete mailbox', 'error');
                }
            })
            .catch(function () {
                toast('Network error deleting mailbox', 'error');
            });
    }

    /** POST /api/mailboxes/<name>/password — reset password */
    function resetPassword(name) {
        var newPw = prompt('Enter new password for "' + name + '" (min 8 chars):');
        if (!newPw) return;
        if (newPw.length < 8) { toast('Password must be at least 8 characters', 'error'); return; }

        fetch('/api/mailboxes/' + encodeURIComponent(name) + '/password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: newPw })
        })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (res.ok) {
                    toast('Password reset for: ' + name, 'success');
                } else {
                    toast(res.data.error || 'Failed to reset password', 'error');
                }
            })
            .catch(function () {
                toast('Network error resetting password', 'error');
            });
    }

    /** POST /api/mailboxes/<name>/toggle — enable/disable */
    function toggleMailbox(name, enabled) {
        var action = enabled ? 'enable' : 'disable';
        if (!confirm(action.charAt(0).toUpperCase() + action.slice(1) + ' mailbox "' + name + '"?')) return;

        fetch('/api/mailboxes/' + encodeURIComponent(name) + '/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: enabled })
        })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
            .then(function (res) {
                if (res.ok) {
                    toast('Mailbox ' + action + 'd: ' + name, 'success');
                    loadMailboxes();
                } else {
                    toast(res.data.error || 'Failed to ' + action + ' mailbox', 'error');
                }
            })
            .catch(function () {
                toast('Network error toggling mailbox', 'error');
            });
    }

    /** Show the create mailbox modal */
    function showCreateModal() {
        document.getElementById('new-name').value = '';
        document.getElementById('new-display-name').value = '';
        document.getElementById('new-password').value = '';
        document.getElementById('new-quota').value = '1024';
        document.getElementById('create-modal').classList.add('active');
    }

    /** Close the create mailbox modal */
    function closeModal() {
        document.getElementById('create-modal').classList.remove('active');
    }

    // Escape key closes modal
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeModal();
    });

    // Auto-load on DOM ready
    document.addEventListener('DOMContentLoaded', function () {
        loadStatus();
        // Auto-refresh status every 30 seconds
        setInterval(loadStatus, 30000);
    });

    // Export to window.kmail
    window.kmail = {
        switchTab: switchTab,
        loadStatus: loadStatus,
        loadMailboxes: loadMailboxes,
        createMailbox: createMailbox,
        deleteMailbox: deleteMailbox,
        resetPassword: resetPassword,
        toggleMailbox: toggleMailbox,
        showCreateModal: showCreateModal,
        closeModal: closeModal,
        toast: toast,
        esc: esc
    };
})();
