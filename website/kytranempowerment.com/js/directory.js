/* Directory — Agent roster with live status polling
   Polls the canonical public directory endpoint — single source of truth
   for avatars + bios + titles. Static fallback only fires if the API is
   unreachable (local dev, outage). */
var Directory = {
    API_URL: '/data/directory-fallback.json',
    LIVE_URL: 'https://platform.kytranempowerment.com/api/public/directory/live',
    FALLBACK_URL: 'https://platform.kytranempowerment.com/api/public/directory',
    POLL_INTERVAL: 30000,
    agents: [],
    _pollTimer: null,

    init: function () {
        var self = this;
        fetch(this.API_URL, {cache: 'no-cache'})
            .then(function (r) {
                if (!r.ok) throw new Error(r.status);
                return r.json();
            })
            .then(function (data) {
                self.agents = data.agents || data;
                self._fixAvatarPaths(self.agents);
                self.renderFilters();
                self.applyFilters();
                self.startLivePolling();
            })
            .catch(function (err) {
                console.warn('[directory] Live API unreachable, using static fallback:', err.message);
                fetch(self.FALLBACK_URL)
                    .then(function (r) {
                        if (!r.ok) throw new Error(r.status);
                        return r.json();
                    })
                    .then(function (data) {
                        self.agents = data.agents || data;
                        self._fixAvatarPaths(self.agents);
                        self.renderFilters();
                        self.applyFilters();
                    })
                    .catch(function () { self.showOfflineNotice(); });
            });
    },

    /** Normalize avatar URLs. Live API returns fully-qualified https URLs;
        only rewrite legacy relative paths found in the static fallback. */
    _fixAvatarPaths: function (agents) {
        agents.forEach(function (a) {
            if (!a.avatar_url) return;
            // Absolute URLs (from live API) are already correct — leave alone.
            if (/^https?:\/\//i.test(a.avatar_url)) return;
            // Legacy fallback paths — rewrite to local /assets/portraits/ dir.
            if (a.avatar_url.indexOf('/static/media/portraits/') !== -1) {
                a.avatar_url = a.avatar_url.replace('/static/media/portraits/', '/assets/portraits/');
            }
        });
    },

    _clearChildren: function (el) {
        while (el.firstChild) el.removeChild(el.firstChild);
    },

    renderAgents: function (agents) {
        var grid = document.getElementById('directoryGrid');
        if (!grid) return;
        this._clearChildren(grid);

        agents.forEach(function (agent) {
            var isDirector = agent.agent_type === 'director' || agent.agent_type === 'ai_director';
            var accent = isDirector ? '#00e5ff' : '#8b5cf6';

            // Horizontal card — avatar left, name/type/department stacked
            // right, per Directory.dc.html. Full detail (bio, email, status)
            // lives in the click-through profile modal below.
            var card = document.createElement('div');
            card.className = 'agent-card';
            card.style.setProperty('--agent-accent', accent);
            card.setAttribute('data-department', agent.department || '');
            card.setAttribute('data-type', agent.agent_type || '');

            var avatarWrap = document.createElement('div');
            avatarWrap.className = 'agent-card__avatar';

            var displayName = agent.acronym || agent.full_name || agent.display_name || '?';
            var initial = displayName.replace(/\./g, '').slice(0, 2).toUpperCase();
            if (agent.avatar_thumb_url || agent.avatar_url) {
                var img = document.createElement('img');
                // Same-origin thumb (~20KB) preferred over cross-origin full-res.
                // Full-res only loads on card click (rendered in modal).
                img.src = agent.avatar_thumb_url || agent.avatar_url;
                img.alt = agent.full_name || agent.acronym || 'Agent';
                img.loading = 'lazy';
                img.decoding = 'async';
                img.onerror = function () {
                    var ph = document.createElement('div');
                    ph.className = 'agent-card__avatar-placeholder';
                    ph.textContent = initial;
                    this.replaceWith(ph);
                };
                avatarWrap.appendChild(img);
            } else {
                var placeholder = document.createElement('div');
                placeholder.className = 'agent-card__avatar-placeholder';
                placeholder.textContent = initial;
                avatarWrap.appendChild(placeholder);
            }

            var statusDot = document.createElement('span');
            var state = agent.shift_state || 'off_duty';
            statusDot.className = 'agent-card__status agent-card__status--' + state;
            statusDot.setAttribute('data-agent-id', agent.id || '');
            statusDot.setAttribute('data-live-status', state);
            avatarWrap.appendChild(statusDot);

            card.appendChild(avatarWrap);

            var body = document.createElement('div');
            body.className = 'agent-card__body';

            var nameEl = document.createElement('div');
            nameEl.className = 'agent-card__name';
            nameEl.textContent = agent.acronym || agent.full_name || agent.display_name || 'Unknown';
            body.appendChild(nameEl);

            var typeEl = document.createElement('div');
            typeEl.className = 'agent-card__type';
            typeEl.textContent = isDirector ? 'Director' : (agent.agent_type === 'human' ? 'Human' : 'Staff Agent');
            body.appendChild(typeEl);

            if (agent.department) {
                var deptEl = document.createElement('div');
                deptEl.className = 'agent-card__department';
                deptEl.textContent = agent.department;
                body.appendChild(deptEl);
            }

            card.appendChild(body);

            // Click to open the full-detail profile modal (title, bio,
            // email, live status — an enhancement over the static mock).
            card.style.cursor = 'pointer';
            card.addEventListener('click', function () {
                Directory.openProfile(agent);
            });

            grid.appendChild(card);
        });
    },

    openProfile: function (agent) {
        // Remove existing modal if any
        var existing = document.getElementById('agentProfileModal');
        if (existing) existing.remove();

        var overlay = document.createElement('div');
        overlay.id = 'agentProfileModal';
        overlay.className = 'dir-modal';
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) overlay.remove();
        });

        var panel = document.createElement('div');
        panel.className = 'dir-modal__panel';

        // Close button
        var closeBtn = document.createElement('button');
        closeBtn.className = 'dir-modal__close';
        closeBtn.textContent = '\u00D7';
        closeBtn.addEventListener('click', function () { overlay.remove(); });
        panel.appendChild(closeBtn);

        // Avatar (large)
        var avatarWrap = document.createElement('div');
        avatarWrap.className = 'dir-modal__avatar';
        var initial = (agent.full_name || agent.acronym || '?').charAt(0).toUpperCase();
        if (agent.avatar_thumb_url || agent.avatar_url) {
            var img = document.createElement('img');
            img.src = agent.avatar_thumb_url || agent.avatar_url;
            img.alt = agent.full_name || agent.acronym || 'Agent';
            img.onerror = function () {
                var ph = document.createElement('div');
                ph.className = 'dir-modal__avatar-fallback';
                ph.textContent = initial;
                this.replaceWith(ph);
            };
            avatarWrap.appendChild(img);
        } else {
            var placeholder = document.createElement('div');
            placeholder.className = 'dir-modal__avatar-fallback';
            placeholder.textContent = initial;
            avatarWrap.appendChild(placeholder);
        }
        panel.appendChild(avatarWrap);

        // Name / Acronym
        if (agent.acronym) {
            var acr = document.createElement('h2');
            acr.className = 'dir-modal__acronym';
            acr.textContent = agent.acronym;
            panel.appendChild(acr);
            if (agent.acronym_expansion) {
                var exp = document.createElement('p');
                exp.className = 'dir-modal__expansion';
                exp.textContent = agent.acronym_expansion;
                panel.appendChild(exp);
            }
        } else {
            var nameH = document.createElement('h2');
            nameH.className = 'dir-modal__name';
            nameH.textContent = agent.full_name || agent.display_name || 'Unknown';
            panel.appendChild(nameH);
        }

        // Bio — humanize the modal by showing the agent's backstory/description
        if (agent.bio) {
            var bioHeading = document.createElement('h3');
            bioHeading.className = 'dir-modal__bio-heading';
            bioHeading.textContent = agent.worker_type === 'ai' ? 'About' : 'Bio';
            panel.appendChild(bioHeading);

            var bioEl = document.createElement('p');
            bioEl.className = 'dir-modal__bio';
            bioEl.textContent = agent.bio;
            panel.appendChild(bioEl);
        }

        // Info rows
        var fields = [
            { label: 'Title', value: agent.title },
            { label: 'Department', value: agent.department },
            { label: 'Type', value: agent.agent_type },
            { label: 'Status', value: agent.shift_state },
            { label: 'Email', value: agent.email, isEmail: true },
        ];

        var infoGrid = document.createElement('div');
        infoGrid.className = 'dir-modal__info';
        fields.forEach(function (f) {
            if (!f.value) return;
            var row = document.createElement('div');
            row.className = 'dir-modal__row';

            var label = document.createElement('span');
            label.className = 'dir-modal__label';
            label.textContent = f.label;
            row.appendChild(label);

            var val = document.createElement('span');
            val.className = 'dir-modal__value';
            if (f.isEmail) {
                var a = document.createElement('a');
                a.href = 'mailto:' + f.value;
                a.textContent = f.value;
                a.style.color = 'var(--accent, #00e5ff)';
                val.appendChild(a);
            } else if (f.label === 'Status') {
                var badge = document.createElement('span');
                badge.className = 'dir-modal__status dir-modal__status--' + f.value;
                badge.textContent = f.value.replace('_', ' ');
                val.appendChild(badge);
            } else {
                val.textContent = f.value;
            }
            row.appendChild(val);
            infoGrid.appendChild(row);
        });
        panel.appendChild(infoGrid);

        overlay.appendChild(panel);
        document.body.appendChild(overlay);

        // Close on Escape
        var escHandler = function (e) {
            if (e.key === 'Escape') {
                overlay.remove();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    },

    /* Filter UI matches Directory.dc.html: a search box, a pill row for
       type (All/Directors/Staff), a chip row for department, and a result
       count. State lives on Directory itself (query/type/dept) so pill and
       chip active-states can be re-rendered on every change. */
    filterState: { query: '', type: 'all', dept: 'All' },

    renderFilters: function () {
        var self = this;

        // Never hardcode a roster count in HTML — update from the real
        // fetched list (see today's "13 agents" / "50+ agents" copy bugs).
        var heroSub = document.getElementById('directoryHeroSubtitle');
        if (heroSub) {
            var deptSet = {};
            this.agents.forEach(function (a) { if (a.department) deptSet[a.department] = true; });
            var deptCount = Object.keys(deptSet).length;
            heroSub.textContent = this.agents.length + ' agents across ' + deptCount + ' departments — powering intelligent automation';
        }

        var container = document.getElementById('directoryFilters');
        if (!container) return;
        this._clearChildren(container);

        var topRow = document.createElement('div');
        topRow.className = 'directory-filters__top';

        var search = document.createElement('input');
        search.type = 'text';
        search.className = 'directory-search';
        search.placeholder = 'Search agents or departments…';
        search.id = 'directorySearch';
        search.value = this.filterState.query;
        topRow.appendChild(search);

        var typeRow = document.createElement('div');
        typeRow.className = 'directory-type-pills';
        [
            { v: 'all', l: 'All' },
            { v: 'director', l: 'Directors' },
            { v: 'staff', l: 'Staff' }
        ].forEach(function (t) {
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'directory-pill' + (self.filterState.type === t.v ? ' directory-pill--active' : '');
            btn.textContent = t.l;
            btn.addEventListener('click', function () {
                self.filterState.type = t.v;
                self.renderFilters();
                self.applyFilters();
            });
            typeRow.appendChild(btn);
        });
        topRow.appendChild(typeRow);
        container.appendChild(topRow);

        var depts = ['All'];
        this.agents.forEach(function (a) {
            if (a.department && depts.indexOf(a.department) === -1) depts.push(a.department);
        });
        depts.sort(function (a, b) { return a === 'All' ? -1 : b === 'All' ? 1 : a.localeCompare(b); });

        var deptRow = document.createElement('div');
        deptRow.className = 'directory-dept-chips';
        depts.forEach(function (d) {
            var chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'directory-chip' + (self.filterState.dept === d ? ' directory-chip--active' : '');
            chip.textContent = d;
            chip.addEventListener('click', function () {
                self.filterState.dept = d;
                self.renderFilters();
                self.applyFilters();
            });
            deptRow.appendChild(chip);
        });
        container.appendChild(deptRow);

        var count = document.createElement('div');
        count.className = 'directory-result-count';
        count.id = 'directoryResultCount';
        container.appendChild(count);

        this.bindEvents();
    },

    applyFilters: function () {
        var self = this;
        var searchInput = document.getElementById('directorySearch');
        this.filterState.query = searchInput ? searchInput.value.toLowerCase() : '';
        var q = this.filterState.query.trim();

        var filtered = this.agents.filter(function (a) {
            if (self.filterState.type !== 'all' && a.agent_type !== self.filterState.type) return false;
            if (self.filterState.dept !== 'All' && a.department !== self.filterState.dept) return false;
            if (q) {
                var haystack = [
                    a.full_name || '', a.display_name || '', a.acronym || '',
                    a.acronym_expansion || '', a.title || '', a.department || ''
                ].join(' ').toLowerCase();
                if (haystack.indexOf(q) === -1) return false;
            }
            return true;
        });

        var countEl = document.getElementById('directoryResultCount');
        if (countEl) countEl.textContent = filtered.length + ' shown';

        this.renderAgents(filtered);
    },

    bindEvents: function () {
        var self = this;
        var search = document.getElementById('directorySearch');
        if (!search) return;
        search.addEventListener('input', function () { self.applyFilters(); });
    },

    startLivePolling: function () {
        var self = this;
        this._pollTimer = setInterval(function () {
            fetch(self.LIVE_URL)
                .then(function (r) {
                    if (!r.ok) throw new Error(r.status);
                    return r.json();
                })
                .then(function (data) {
                    // /api/public/directory/live returns {success, agents: [{id, code_name, shift_state, current_mood, wellness_status}]}
                    var statuses = (data && data.agents) || data.statuses || data;
                    if (!Array.isArray(statuses)) return;
                    statuses.forEach(function (s) {
                        var dots = document.querySelectorAll('[data-agent-id="' + s.id + '"]');
                        dots.forEach(function (dot) {
                            dot.className = 'agent-card__status agent-card__status--' + (s.shift_state || 'off_duty');
                            dot.setAttribute('data-live-status', s.shift_state || 'off_duty');
                        });
                    });
                    // Update internal state
                    self.agents.forEach(function (a) {
                        statuses.forEach(function (s) {
                            if (String(a.id) === String(s.id)) {
                                a.shift_state = s.shift_state;
                                if (s.current_mood) a.current_mood = s.current_mood;
                            }
                        });
                    });
                })
                .catch(function () { /* silent fail on poll */ });
        }, this.POLL_INTERVAL);
    },

    showOfflineNotice: function () {
        var notice = document.getElementById('directoryNotice');
        if (notice) notice.classList.add('visible');
    },

    destroy: function () {
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    }
};

document.addEventListener('DOMContentLoaded', function () {
    Directory.init();
});
