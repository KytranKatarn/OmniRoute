/* Directory — Agent roster with live status polling */
var Directory = {
    API_URL: 'https://api.kytranempowerment.com/api/directory',
    LIVE_URL: 'https://api.kytranempowerment.com/api/directory/live-status',
    POLL_INTERVAL: 30000,
    agents: [],
    _pollTimer: null,

    init: function () {
        var self = this;
        fetch(this.API_URL)
            .then(function (r) {
                if (!r.ok) throw new Error(r.status);
                return r.json();
            })
            .then(function (data) {
                self.agents = data.agents || data;
                self.renderFilters();
                self.renderAgents(self.agents);
                self.startLivePolling();
                self.bindEvents();
            })
            .catch(function () {
                fetch('/data/directory-fallback.json')
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        self.agents = data.agents || data;
                        self.renderFilters();
                        self.renderAgents(self.agents);
                        self.bindEvents();
                        self.showOfflineNotice();
                    })
                    .catch(function () {
                        self.showOfflineNotice();
                    });
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
            var card = document.createElement('div');
            card.className = 'agent-card';
            card.setAttribute('data-department', agent.department || '');
            card.setAttribute('data-type', agent.agent_type || '');

            // Avatar wrapper
            var avatarWrap = document.createElement('div');
            avatarWrap.className = 'agent-card__avatar';

            if (agent.avatar_url) {
                var img = document.createElement('img');
                img.src = agent.avatar_url;
                img.alt = agent.full_name || agent.acronym || 'Agent';
                avatarWrap.appendChild(img);
            } else {
                var placeholder = document.createElement('div');
                placeholder.className = 'agent-card__avatar-placeholder';
                var initial = (agent.full_name || agent.acronym || '?').charAt(0).toUpperCase();
                placeholder.textContent = initial;
                avatarWrap.appendChild(placeholder);
            }

            // Status dot
            var statusDot = document.createElement('span');
            var state = agent.shift_state || 'off_duty';
            statusDot.className = 'agent-card__status agent-card__status--' + state;
            statusDot.setAttribute('data-agent-id', agent.id || '');
            statusDot.setAttribute('data-live-status', state);
            avatarWrap.appendChild(statusDot);

            card.appendChild(avatarWrap);

            // Name section
            if (agent.acronym) {
                var acronymEl = document.createElement('div');
                acronymEl.className = 'agent-card__acronym';
                acronymEl.textContent = agent.acronym;
                card.appendChild(acronymEl);

                if (agent.acronym_expansion) {
                    var expEl = document.createElement('div');
                    expEl.className = 'agent-card__expansion';
                    expEl.textContent = agent.acronym_expansion;
                    card.appendChild(expEl);
                }
            } else {
                var nameEl = document.createElement('div');
                nameEl.className = 'agent-card__name';
                nameEl.textContent = agent.full_name || agent.display_name || 'Unknown';
                card.appendChild(nameEl);
            }

            // Title
            if (agent.title) {
                var titleEl = document.createElement('div');
                titleEl.className = 'agent-card__title';
                titleEl.textContent = agent.title;
                card.appendChild(titleEl);
            }

            // Type badge
            if (agent.agent_type) {
                var typeEl = document.createElement('span');
                var typeClass = 'agent-card__type';
                var t = agent.agent_type.toLowerCase();
                if (t === 'director' || t === 'ai_director') typeClass += ' agent-card__type--director';
                else if (t === 'human') typeClass += ' agent-card__type--human';
                else typeClass += ' agent-card__type--staff';
                typeEl.className = typeClass;
                typeEl.textContent = agent.agent_type;
                card.appendChild(typeEl);
            }

            // Department
            if (agent.department) {
                var deptEl = document.createElement('div');
                deptEl.className = 'agent-card__department';
                deptEl.textContent = agent.department;
                card.appendChild(deptEl);
            }

            grid.appendChild(card);
        });
    },

    renderFilters: function () {
        var container = document.getElementById('directoryFilters');
        if (!container) return;
        this._clearChildren(container);

        // Search input
        var search = document.createElement('input');
        search.type = 'text';
        search.className = 'directory-search';
        search.placeholder = 'Search agents...';
        search.id = 'directorySearch';
        container.appendChild(search);

        // Department select
        var depts = [];
        this.agents.forEach(function (a) {
            if (a.department && depts.indexOf(a.department) === -1) depts.push(a.department);
        });
        depts.sort();

        var deptSelect = document.createElement('select');
        deptSelect.className = 'directory-filter';
        deptSelect.id = 'directoryDeptFilter';
        var allDeptOpt = document.createElement('option');
        allDeptOpt.value = '';
        allDeptOpt.textContent = 'All Departments';
        deptSelect.appendChild(allDeptOpt);
        depts.forEach(function (d) {
            var opt = document.createElement('option');
            opt.value = d;
            opt.textContent = d;
            deptSelect.appendChild(opt);
        });
        container.appendChild(deptSelect);

        // Type select
        var types = [];
        this.agents.forEach(function (a) {
            if (a.agent_type && types.indexOf(a.agent_type) === -1) types.push(a.agent_type);
        });
        types.sort();

        var typeSelect = document.createElement('select');
        typeSelect.className = 'directory-filter';
        typeSelect.id = 'directoryTypeFilter';
        var allTypeOpt = document.createElement('option');
        allTypeOpt.value = '';
        allTypeOpt.textContent = 'All Types';
        typeSelect.appendChild(allTypeOpt);
        types.forEach(function (t) {
            var opt = document.createElement('option');
            opt.value = t;
            opt.textContent = t;
            typeSelect.appendChild(opt);
        });
        container.appendChild(typeSelect);
    },

    applyFilters: function () {
        var searchVal = (document.getElementById('directorySearch').value || '').toLowerCase();
        var deptVal = document.getElementById('directoryDeptFilter').value;
        var typeVal = document.getElementById('directoryTypeFilter').value;

        var filtered = this.agents.filter(function (a) {
            if (deptVal && a.department !== deptVal) return false;
            if (typeVal && a.agent_type !== typeVal) return false;
            if (searchVal) {
                var haystack = [
                    a.full_name || '', a.display_name || '', a.acronym || '',
                    a.acronym_expansion || '', a.title || '', a.department || ''
                ].join(' ').toLowerCase();
                if (haystack.indexOf(searchVal) === -1) return false;
            }
            return true;
        });

        this.renderAgents(filtered);
    },

    bindEvents: function () {
        var self = this;
        var filtersContainer = document.getElementById('directoryFilters');
        if (!filtersContainer) return;

        filtersContainer.addEventListener('input', function () { self.applyFilters(); });
        filtersContainer.addEventListener('change', function () { self.applyFilters(); });
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
                    var statuses = data.statuses || data;
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
                            if (String(a.id) === String(s.id)) a.shift_state = s.shift_state;
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
