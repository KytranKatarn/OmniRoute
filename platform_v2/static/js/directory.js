/* ==========================================================================
   EMPLOYEE DIRECTORY — Kytran Empowerment
   Loads team data, renders full pyramid org chart with all agents.
   All dynamic content is sanitized via escHtml()/escAttr() before DOM insertion.
   ========================================================================== */

const DEPT_COLORS = {
    'Analytics & Intelligence': '#8b5cf6',
    'Engineering': '#fbbf24',
    'Creative & Design': '#f472b6',
    'Communications & Marketing': '#22d3ee',
    'Research & Development': '#10b981',
    'Security & Compliance': '#ef4444',
    'Operations & Infrastructure': '#f97316',
    'Logistics & Supply Chain': '#a3e635',
    'Diplomatic & Human Relations': '#818cf8',
    'Medical & Wellness': '#ec4899',
    'Customer Experience': '#06b6d4',
    'Documentation & Knowledge': '#d4a843',
};

const PROFICIENCY_COLORS = {
    5: '#10b981',
    4: '#00e5ff',
    3: '#fbbf24',
    2: '#f97316',
    1: '#ef4444',
};

let directoryData = null;
let orgChartNodes = null;
let isAuthenticated = false;
window.agentStatus = {};

document.addEventListener('DOMContentLoaded', init);

async function init() {
    const wrapper = document.querySelector('.dir-wrapper');
    isAuthenticated = wrapper && wrapper.dataset.authenticated === 'true';
    await Promise.all([loadDirectory(), loadOrgChart()]);
    setupFilters();
    if (isAuthenticated) {
        loadAgentStatus();
        setInterval(loadAgentStatus, 30000);
    }
}

/* ---------- DIRECTORY DATA ---------- */

async function loadDirectory() {
    try {
        const resp = await fetch('/api/directory');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error || 'Failed to load');
        directoryData = data;
        renderHeroStats(data.statistics);
        populateDeptFilter(data.departments);
    } catch (err) {
        console.error('Directory load error:', err);
    }
}

/* ---------- LIVE STATUS ---------- */

async function loadAgentStatus() {
    try {
        const resp = await fetch('/api/directory/status');
        if (!resp.ok) return;
        const data = await resp.json();
        window.agentStatus = data.status || {};
        updateStatusIndicators();
        updateHeroOnlineCount();
    } catch (e) {
        // Status is a progressive enhancement
    }
}

function updateStatusIndicators() {
    document.querySelectorAll('[data-agent-id]').forEach(el => {
        const agentId = el.dataset.agentId;
        const status = window.agentStatus[agentId];
        const dot = el.querySelector('.dir-status-dot, .dir-org-node-dot');
        if (status && status.is_online) {
            dot?.classList.add('online');
            dot?.classList.remove('offline');
        } else {
            dot?.classList.add('offline');
            dot?.classList.remove('online');
        }
    });
}

function updateHeroOnlineCount() {
    const onlineCount = Object.values(window.agentStatus).filter(s => s.is_online).length;
    const el = document.getElementById('statOnlineNow');
    if (el) el.textContent = onlineCount;
}

function renderHeroStats(stats) {
    const el = (id) => document.getElementById(id);
    if (el('statTotalMembers')) el('statTotalMembers').textContent = stats.total_members || 0;
    if (el('statDepartments')) el('statDepartments').textContent = stats.total_departments || 0;
    if (el('statOnlineNow')) el('statOnlineNow').textContent = '--';
}

function populateDeptFilter(departments) {
    const sel = document.getElementById('dirDeptFilter');
    if (!sel) return;
    departments.forEach(dept => {
        const opt = document.createElement('option');
        opt.value = dept;
        opt.textContent = dept;
        sel.appendChild(opt);
    });
}

/* ---------- ORG CHART ---------- */

async function loadOrgChart() {
    try {
        const resp = await fetch('/api/directory/org-chart');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error || 'Failed to load');
        orgChartNodes = data.nodes;
        renderOrgChart(data.nodes);
        renderAccordion(data.nodes);
    } catch (err) {
        const el = document.getElementById('orgChart');
        if (el) {
            el.textContent = '';
            const div = document.createElement('div');
            div.className = 'dir-org-loading';
            div.style.color = '#ef4444';
            div.textContent = 'Failed to load org chart';
            el.appendChild(div);
        }
    }
}

function renderOrgChart(nodes) {
    const chart = document.getElementById('orgChart');
    if (!chart) return;
    chart.textContent = '';

    // --- Identify special nodes ---
    const archie = nodes.find(n =>
        (n.reports_to === null || n.reports_to === undefined) &&
        (/^archie$/i.test(n.name || '') || /^A\.R\.C\.H\.I\.E\.$/i.test(n.display_name || ''))
    );
    const vigil = nodes.find(n => /^vigil$/i.test(n.name || '') || /^vigil/i.test(n.display_name || ''));
    const skipIds = new Set([archie, vigil].filter(Boolean).map(n => n.id));

    // --- Group remaining nodes by department ---
    const deptMap = {};  // department name -> { head: node|null, members: [] }
    nodes.forEach(n => {
        if (skipIds.has(n.id)) return;
        const dept = n.department || 'Unassigned';
        if (!deptMap[dept]) deptMap[dept] = { head: null, members: [] };
        if (n.is_head) {
            deptMap[dept].head = n;
        } else {
            deptMap[dept].members.push(n);
        }
    });

    // Sort departments by DEPT_COLORS order, then alphabetically for unknown
    const knownDepts = Object.keys(DEPT_COLORS);
    const deptOrder = knownDepts.filter(d => deptMap[d]).concat(
        Object.keys(deptMap).filter(d => !knownDepts.includes(d)).sort()
    );

    // --- LEVEL 1: CEO (Kytran) ---
    const kytranNode = { full_name: 'Kytran', title: 'CEO & Founder', employee_type: 'Human', department: 'Executive', id: 0 };
    const l1 = document.createElement('div');
    l1.className = 'dir-org-level dir-org-level-ceo';
    l1.appendChild(createOrgNode(kytranNode, 'ceo'));
    chart.appendChild(l1);

    // Connector L1 -> L2
    chart.appendChild(createConnector('solid'));

    // --- LEVEL 2: ARCHIE ---
    const l2 = document.createElement('div');
    l2.className = 'dir-org-level dir-org-level-director';
    const archieData = archie || { full_name: 'A.R.C.H.I.E.', title: 'AI Director / Co-Owner', employee_type: 'AI', department: 'Command', id: 2 };
    const archieNode = createOrgNode(archieData, 'director');
    l2.appendChild(archieNode);
    chart.appendChild(l2);

    // --- LEVEL 3: Vigil (advisory, dashed line to ARCHIE, offset right) ---
    const vigilWrap = document.createElement('div');
    vigilWrap.className = 'dir-vigil-branch';
    const vigilConnector = document.createElement('div');
    vigilConnector.className = 'dir-vigil-connector';
    vigilWrap.appendChild(vigilConnector);
    const vigilData = vigil || { full_name: 'Vigil', title: 'Ethics Officer', employee_type: 'AI', department: 'Command', id: 3 };
    const vigilNode = createOrgNode(vigilData, 'vigil');
    vigilNode.classList.add('dir-org-node-vigil');
    vigilWrap.appendChild(vigilNode);
    chart.appendChild(vigilWrap);

    // Connector L2 -> L4 (departments)
    chart.appendChild(createConnector('solid'));
    chart.appendChild(createHorizontalConnector(deptOrder.length));
    chart.appendChild(createDeptDropLines(deptOrder.length));

    // --- LEVEL 4: Department heads ---
    const l4 = document.createElement('div');
    l4.className = 'dir-org-level dir-org-level-heads';
    deptOrder.forEach(dept => {
        const color = getDeptColor(dept);
        const info = deptMap[dept];
        const head = info.head || { full_name: dept, title: 'Department Head', department: dept, id: 0 };
        const headNode = createOrgNode(Object.assign({}, head, { department: dept }), 'dept', color);

        // Department label above the head node
        const wrapper = document.createElement('div');
        wrapper.className = 'dir-org-dept-head-wrap';
        const deptLabel = document.createElement('div');
        deptLabel.className = 'dir-org-dept-label';
        deptLabel.style.color = color;
        deptLabel.textContent = dept;
        wrapper.appendChild(deptLabel);

        headNode.classList.add('dir-org-node-head');
        wrapper.appendChild(headNode);
        l4.appendChild(wrapper);
    });
    chart.appendChild(l4);

    // --- LEVEL 5: Department members (below each head) ---
    const l5 = document.createElement('div');
    l5.className = 'dir-org-level dir-org-level-members';
    deptOrder.forEach(dept => {
        const color = getDeptColor(dept);
        const info = deptMap[dept];
        const col = document.createElement('div');
        col.className = 'dir-org-dept-col';
        col.dataset.department = dept;

        if (info.members.length > 0) {
            const miniConn = document.createElement('div');
            miniConn.className = 'dir-org-mini-connector';
            miniConn.style.borderColor = color + '44';
            col.appendChild(miniConn);

            info.members.forEach(m => {
                col.appendChild(createMemberBadge(m, 'dept', color));
            });
        }
        l5.appendChild(col);
    });
    chart.appendChild(l5);
}

function getDeptColor(dept) {
    return DEPT_COLORS[dept] || '#64748b';
}

function createOrgNode(person, nodeType, explicitColor) {
    // nodeType: 'ceo', 'director', 'vigil', 'dept'
    let color;
    if (nodeType === 'ceo') color = '#f59e0b';
    else if (nodeType === 'director') color = '#00e5ff';
    else if (nodeType === 'vigil') color = '#00e5ff';
    else if (explicitColor) color = explicitColor;
    else color = getDeptColor(person.department || '');
    const name = person.full_name || person.display_name || person.name || 'Unknown';
    const initials = getInitials(name);
    const title = person.title || '';
    const agentId = person.id || 0;
    const nodeClass = nodeType === 'ceo' ? 'role-ceo' : (nodeType === 'director' ? 'role-director' : '');

    const node = document.createElement('div');
    node.className = 'dir-org-node ' + nodeClass;
    node.style.borderColor = color;
    node.dataset.agentId = String(agentId);
    if (agentId) node.addEventListener('click', () => openProfile(agentId));

    const portraitEl = document.createElement('div');
    portraitEl.className = 'dir-org-node-portrait';
    portraitEl.style.background = color + '33';
    portraitEl.style.border = '2px solid ' + color;

    if (person.avatar_url) {
        const img = document.createElement('img');
        img.src = person.avatar_url;
        img.alt = name;
        img.loading = 'lazy';
        img.className = 'dir-org-node-portrait-img';
        portraitEl.appendChild(img);
    } else {
        portraitEl.textContent = initials;
    }
    node.appendChild(portraitEl);

    const nameDiv = document.createElement('div');
    nameDiv.className = 'dir-org-node-name';
    if (isAuthenticated) {
        const dot = document.createElement('span');
        dot.className = 'dir-org-node-dot offline';
        nameDiv.appendChild(dot);
    }
    nameDiv.appendChild(document.createTextNode(name));
    node.appendChild(nameDiv);

    const titleDiv = document.createElement('div');
    titleDiv.className = 'dir-org-node-title';
    titleDiv.textContent = title;
    node.appendChild(titleDiv);

    return node;
}

function createMemberBadge(person, nodeType, explicitColor) {
    const color = explicitColor || getDeptColor(person.department || '');
    const name = person.full_name || person.display_name || person.name || 'Unknown';
    const title = person.title || '';
    const agentId = person.id || 0;

    const badge = document.createElement('div');
    badge.className = 'dir-org-member-badge';
    badge.dataset.agentId = String(agentId);
    badge.style.borderColor = color + '44';
    if (agentId) badge.addEventListener('click', () => openProfile(agentId));

    if (person.avatar_url) {
        const img = document.createElement('img');
        img.src = person.avatar_url;
        img.alt = name;
        img.loading = 'lazy';
        img.className = 'dir-org-badge-avatar';
        badge.appendChild(img);
    } else {
        const initialsEl = document.createElement('div');
        initialsEl.className = 'dir-org-badge-initials';
        initialsEl.style.background = color + '22';
        initialsEl.style.color = color;
        initialsEl.textContent = getInitials(name);
        badge.appendChild(initialsEl);
    }

    const info = document.createElement('div');
    info.className = 'dir-org-badge-info';

    const nameEl = document.createElement('div');
    nameEl.className = 'dir-org-badge-name';
    if (isAuthenticated) {
        const dot = document.createElement('span');
        dot.className = 'dir-status-dot offline';
        dot.style.width = '6px';
        dot.style.height = '6px';
        dot.style.marginRight = '4px';
        nameEl.appendChild(dot);
    }
    nameEl.appendChild(document.createTextNode(name));
    info.appendChild(nameEl);

    const titleEl = document.createElement('div');
    titleEl.className = 'dir-org-badge-title';
    titleEl.style.color = color;
    titleEl.textContent = title;
    info.appendChild(titleEl);

    badge.appendChild(info);
    return badge;
}

function createConnector(style) {
    const c = document.createElement('div');
    c.className = 'dir-org-connector';
    if (style === 'dashed') c.classList.add('dir-org-connector-dashed');
    return c;
}

function createHorizontalConnector(count) {
    const c = document.createElement('div');
    c.className = 'dir-org-connector-horizontal';
    // Width spans across the department columns
    return c;
}

function createDeptDropLines(count) {
    const wrap = document.createElement('div');
    wrap.className = 'dir-org-drop-lines';
    for (let i = 0; i < count; i++) {
        const line = document.createElement('div');
        line.className = 'dir-org-drop-line';
        wrap.appendChild(line);
    }
    return wrap;
}

/* ---------- MOBILE ACCORDION ---------- */

function renderAccordion(nodes) {
    const container = document.getElementById('dirAccordion');
    if (!container) return;
    container.textContent = '';

    const archie = nodes.find(n =>
        (n.reports_to === null || n.reports_to === undefined) &&
        (/^archie$/i.test(n.name || '') || /^A\.R\.C\.H\.I\.E\.$/i.test(n.display_name || ''))
    );
    const vigil = nodes.find(n => /^vigil$/i.test(n.name || '') || /^vigil/i.test(n.display_name || ''));
    const skipIds = new Set([archie, vigil].filter(Boolean).map(n => n.id));

    // Leadership accordion item
    const leadershipColor = '#00e5ff';
    const leadershipItem = createAccordionItem(leadershipColor, 'Leadership', [
        { full_name: 'Kytran', title: 'CEO & Founder', employee_type: 'Human', id: 0 },
        archie || { full_name: 'A.R.C.H.I.E.', title: 'AI Director / Co-Owner', id: 2 },
        vigil || { full_name: 'Vigil', title: 'Ethics Officer', id: 3 }
    ], true);
    container.appendChild(leadershipItem);

    // Group by department
    const deptMap = {};
    nodes.forEach(n => {
        if (skipIds.has(n.id)) return;
        const dept = n.department || 'Unassigned';
        if (!deptMap[dept]) deptMap[dept] = [];
        deptMap[dept].push(n);
    });

    // Sort departments by DEPT_COLORS order
    const knownDepts = Object.keys(DEPT_COLORS);
    const deptOrder = knownDepts.filter(d => deptMap[d]).concat(
        Object.keys(deptMap).filter(d => !knownDepts.includes(d)).sort()
    );

    deptOrder.forEach(dept => {
        const color = getDeptColor(dept);
        // Put head first
        const members = deptMap[dept].sort((a, b) => (b.is_head ? 1 : 0) - (a.is_head ? 1 : 0));
        container.appendChild(createAccordionItem(color, dept, members, false));
    });
}

function createAccordionItem(accentColor, label, members, startOpen) {
    const color = accentColor || '#64748b';
    const item = document.createElement('div');
    item.className = 'dir-acc-item' + (startOpen ? ' open' : '');

    const header = document.createElement('button');
    header.className = 'dir-acc-header';
    header.addEventListener('click', () => item.classList.toggle('open'));

    const accent = document.createElement('span');
    accent.className = 'dir-acc-accent';
    accent.style.background = color;
    header.appendChild(accent);

    const labelEl = document.createElement('span');
    labelEl.className = 'dir-acc-label';
    labelEl.textContent = label;
    header.appendChild(labelEl);

    const countEl = document.createElement('span');
    countEl.className = 'dir-acc-count';
    countEl.textContent = members.length;
    header.appendChild(countEl);

    const chevron = document.createElement('span');
    chevron.className = 'dir-acc-chevron';
    chevron.textContent = '\u25BC';
    header.appendChild(chevron);

    item.appendChild(header);

    const body = document.createElement('div');
    body.className = 'dir-acc-body';
    members.forEach(m => {
        body.appendChild(createMemberBadge(m, 'dept', color));
    });
    item.appendChild(body);

    return item;
}

/* ---------- FILTERS ---------- */

function setupFilters() {
    const search = document.getElementById('dirSearch');
    const deptFilter = document.getElementById('dirDeptFilter');
    const statusFilter = document.getElementById('dirStatusFilter');

    if (search) search.addEventListener('input', debounce(applyFilters, 250));
    if (deptFilter) deptFilter.addEventListener('change', applyFilters);
    if (statusFilter) statusFilter.addEventListener('change', applyFilters);
}

function applyFilters() {
    const searchVal = (document.getElementById('dirSearch')?.value || '').toLowerCase().trim();
    const deptVal = document.getElementById('dirDeptFilter')?.value || 'all';
    const hasFilter = searchVal || deptVal !== 'all';

    // Filter org chart nodes — dim non-matching
    document.querySelectorAll('.dir-org-node, .dir-org-member-badge').forEach(el => {
        if (!hasFilter) {
            el.classList.remove('dir-filtered-out');
            return;
        }
        const name = (el.querySelector('.dir-org-node-name, .dir-org-badge-name')?.textContent || '').toLowerCase();
        const title = (el.querySelector('.dir-org-node-title, .dir-org-badge-title')?.textContent || '').toLowerCase();
        const department = (el.closest('[data-department]')?.dataset.department || '').toLowerCase();
        // Also check parent dept-head-wrap label
        const deptLabel = (el.closest('.dir-org-dept-head-wrap')?.querySelector('.dir-org-dept-label')?.textContent || '').toLowerCase();
        const haystack = name + ' ' + title + ' ' + department + ' ' + deptLabel;

        let match = true;
        if (searchVal && !haystack.includes(searchVal)) match = false;
        if (deptVal !== 'all' && !haystack.includes(deptVal.toLowerCase())) match = false;

        el.classList.toggle('dir-filtered-out', !match);
    });

    // Filter accordion items
    document.querySelectorAll('.dir-acc-item .dir-org-member-badge').forEach(el => {
        if (!hasFilter) {
            el.classList.remove('dir-filtered-out');
            return;
        }
        const name = (el.querySelector('.dir-org-badge-name')?.textContent || '').toLowerCase();
        const title = (el.querySelector('.dir-org-badge-title')?.textContent || '').toLowerCase();
        const haystack = name + ' ' + title;

        let match = true;
        if (searchVal && !haystack.includes(searchVal)) match = false;
        el.classList.toggle('dir-filtered-out', !match);
    });
}

/* ---------- PROFILE PANEL ---------- */

let _profileEscHandler = null;

async function openProfile(employeeId) {
    if (!employeeId) return;
    const panel = document.getElementById('profilePanel');
    const overlay = document.getElementById('profileOverlay');
    const nameEl = document.getElementById('profileName');
    if (!panel) return;

    nameEl.textContent = 'Loading...';
    _resetProfileSections();
    panel.classList.add('active');
    if (overlay) overlay.classList.add('active');

    _profileEscHandler = function(e) {
        if (e.key === 'Escape') closeProfile();
    };
    document.addEventListener('keydown', _profileEscHandler);
    if (overlay) overlay.onclick = closeProfile;

    var closeBtn = document.getElementById('profileCloseBtn');
    if (closeBtn) closeBtn.onclick = closeProfile;

    try {
        const resp = await fetch('/api/directory/' + encodeURIComponent(employeeId));
        const data = await resp.json();
        if (!data.success) throw new Error(data.error || 'Not found');
        _populateProfile(data.employee);
    } catch (err) {
        nameEl.textContent = 'Error';
        var portraitWrap = document.getElementById('profilePortraitWrap');
        if (portraitWrap) {
            portraitWrap.textContent = '';
            var errDiv = document.createElement('div');
            errDiv.className = 'dir-profile-error';
            errDiv.textContent = 'Failed to load profile.';
            portraitWrap.appendChild(errDiv);
        }
    }
}

function closeProfile() {
    var panel = document.getElementById('profilePanel');
    var overlay = document.getElementById('profileOverlay');
    if (panel) panel.classList.remove('active');
    if (overlay) overlay.classList.remove('active');
    if (_profileEscHandler) {
        document.removeEventListener('keydown', _profileEscHandler);
        _profileEscHandler = null;
    }
}

function _resetProfileSections() {
    var ids = ['profilePortraitWrap', 'profileIdentity', 'profileStatusRow',
               'profileContactList', 'profileBioText', 'profileSkillsWrap'];
    ids.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.textContent = '';
    });
    var sections = ['profileContact', 'profileBio', 'profileSkills',
                    'profileWorkingOn', 'profileMsgWrap'];
    sections.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
}

function _populateProfile(emp) {
    var name = emp.full_name || emp.name || 'Unknown';
    var title = emp.title || 'Team Member';
    var dept = emp.department || '';
    var color = getDeptColor(dept) || '#00e5ff';

    var nameEl = document.getElementById('profileName');
    if (nameEl) nameEl.textContent = name;

    // Portrait
    var portraitWrap = document.getElementById('profilePortraitWrap');
    if (portraitWrap) {
        portraitWrap.textContent = '';
        var portraitOuter = document.createElement('div');
        portraitOuter.className = 'dir-profile-portrait';
        portraitOuter.style.borderColor = color;

        if (emp.avatar_url) {
            var img = document.createElement('img');
            img.src = emp.avatar_url;
            img.alt = name;
            img.className = 'dir-profile-portrait-img';
            portraitOuter.appendChild(img);
        } else {
            var initCircle = document.createElement('div');
            initCircle.className = 'dir-profile-portrait-initials';
            initCircle.style.background = color + '22';
            initCircle.style.color = color;
            initCircle.textContent = getInitials(name);
            portraitOuter.appendChild(initCircle);
        }

        var statusDot = document.createElement('span');
        statusDot.className = 'dir-profile-portrait-dot offline';
        statusDot.id = 'profilePortraitDot';
        portraitOuter.appendChild(statusDot);
        portraitWrap.appendChild(portraitOuter);
    }

    // Identity
    var identityEl = document.getElementById('profileIdentity');
    if (identityEl) {
        identityEl.textContent = '';

        // Name row with performance score badge
        var nameRow = document.createElement('div');
        nameRow.className = 'dir-profile-id-name-row';

        var pName = document.createElement('div');
        pName.className = 'dir-profile-id-name';
        pName.textContent = name;
        nameRow.appendChild(pName);

        if (emp.performance_score != null) {
            var scoreBadge = document.createElement('span');
            var score = parseFloat(emp.performance_score);
            var scoreColor = score > 80 ? '#10b981' : (score >= 60 ? '#fbbf24' : '#64748b');
            scoreBadge.className = 'dir-profile-perf-badge';
            scoreBadge.style.background = scoreColor + '22';
            scoreBadge.style.color = scoreColor;
            scoreBadge.style.borderColor = scoreColor + '44';
            scoreBadge.textContent = 'Score: ' + score.toFixed(1);
            nameRow.appendChild(scoreBadge);
        }
        identityEl.appendChild(nameRow);

        var pTitle = document.createElement('div');
        pTitle.className = 'dir-profile-id-title';
        pTitle.style.color = color;
        pTitle.textContent = title;
        identityEl.appendChild(pTitle);

        if (dept) {
            var pDept = document.createElement('div');
            pDept.className = 'dir-profile-id-station';
            var deptText = dept;
            if (emp.employee_type) deptText += ' \u2022 ' + emp.employee_type;
            pDept.textContent = deptText;
            identityEl.appendChild(pDept);
        }

        if (emp.reports_to && emp.reports_to.full_name) {
            var pReports = document.createElement('div');
            pReports.className = 'dir-profile-id-reports';
            pReports.textContent = 'Reports to: ' + emp.reports_to.full_name;
            identityEl.appendChild(pReports);
        }

        if (emp.pronouns) {
            var pPronouns = document.createElement('div');
            pPronouns.className = 'dir-profile-id-pronouns';
            pPronouns.textContent = emp.pronouns;
            identityEl.appendChild(pPronouns);
        }
    }

    // Status Badge
    var statusRow = document.getElementById('profileStatusRow');
    if (statusRow) {
        statusRow.textContent = '';
        var badge = document.createElement('span');
        badge.className = 'dir-profile-status-badge offline';
        badge.id = 'profileStatusBadge';
        var dot = document.createElement('span');
        dot.className = 'dir-profile-badge-dot';
        badge.appendChild(dot);
        badge.appendChild(document.createTextNode(' Off Duty'));
        statusRow.appendChild(badge);
    }

    // Contact
    var contactList = document.getElementById('profileContactList');
    var contactSection = document.getElementById('profileContact');
    if (contactList && contactSection) {
        contactList.textContent = '';
        var hasContact = false;
        if (emp.email) {
            hasContact = true;
            contactList.appendChild(_contactRow('email', emp.email, 'mailto:' + emp.email));
        }
        if (emp.phone || emp.extension) {
            hasContact = true;
            var phoneText = emp.phone || '1-877-463-3352';
            if (emp.extension) phoneText += ' ' + emp.extension;
            contactList.appendChild(_contactRow('phone', phoneText, null));
        }
        if (dept) {
            hasContact = true;
            contactList.appendChild(_contactRow('dept', dept, null));
        }
        if (hasContact) contactSection.style.display = '';
    }

    // Bio
    var bioText = document.getElementById('profileBioText');
    var bioSection = document.getElementById('profileBio');
    if (bioText && bioSection && emp.bio) {
        bioText.textContent = emp.bio;
        bioSection.style.display = '';
    }

    // Skills — benchmarked proficiency ratings
    var skillsWrap = document.getElementById('profileSkillsWrap');
    var skillsSection = document.getElementById('profileSkills');
    var skills = emp.skills || [];
    // Fall back to specialties if no benchmarked skills
    if (skills.length === 0 && emp.specialties && emp.specialties.length > 0) {
        skills = emp.specialties.map(function(s) { return { skill_name: s, proficiency_level: null }; });
    }
    if (skillsWrap && skillsSection && skills.length > 0) {
        skillsWrap.textContent = '';

        // Group by skill_category if present
        var grouped = {};
        skills.forEach(function(sk) {
            var cat = sk.skill_category || 'General';
            if (!grouped[cat]) grouped[cat] = [];
            grouped[cat].push(sk);
        });

        Object.keys(grouped).sort().forEach(function(cat) {
            // Category header (only if multiple categories)
            if (Object.keys(grouped).length > 1) {
                var catLabel = document.createElement('div');
                catLabel.className = 'dir-profile-skill-cat';
                catLabel.textContent = cat;
                skillsWrap.appendChild(catLabel);
            }

            grouped[cat].forEach(function(sk) {
                var row = document.createElement('div');
                row.className = 'dir-profile-skill-row';

                var nameSpan = document.createElement('span');
                nameSpan.className = 'dir-profile-skill-name';
                nameSpan.textContent = sk.skill_name;
                row.appendChild(nameSpan);

                if (sk.proficiency_level != null) {
                    var dotsWrap = document.createElement('span');
                    dotsWrap.className = 'dir-profile-skill-dots';
                    var level = Math.min(5, Math.max(1, sk.proficiency_level));
                    var profColor = PROFICIENCY_COLORS[level] || '#64748b';
                    for (var i = 1; i <= 5; i++) {
                        var dot = document.createElement('span');
                        dot.className = 'dir-profile-skill-dot' + (i <= level ? ' filled' : '');
                        if (i <= level) {
                            dot.style.background = profColor;
                            dot.style.boxShadow = '0 0 4px ' + profColor + '66';
                        }
                        dotsWrap.appendChild(dot);
                    }
                    row.appendChild(dotsWrap);
                }

                skillsWrap.appendChild(row);
            });
        });
        skillsSection.style.display = '';
    }

    // Working On (internal only)
    if (isAuthenticated) {
        var workingText = document.getElementById('profileWorkingText');
        var workingSection = document.getElementById('profileWorkingOn');
        if (workingText && workingSection) {
            workingText.textContent = 'No active jobs';
            workingSection.style.display = '';
        }
    }

    // Live status overlay
    if (isAuthenticated) {
        var agentIdStr = String(emp.id || 0);
        var liveStatus = window.agentStatus[agentIdStr];
        var isOnline = liveStatus && liveStatus.is_online;

        var portraitDot = document.getElementById('profilePortraitDot');
        if (portraitDot) {
            portraitDot.classList.toggle('online', isOnline);
            portraitDot.classList.toggle('offline', !isOnline);
        }

        var sBadge = document.getElementById('profileStatusBadge');
        if (sBadge) {
            sBadge.classList.toggle('online', isOnline);
            sBadge.classList.toggle('offline', !isOnline);
            sBadge.lastChild.textContent = isOnline ? ' Online' : ' Off Duty';
        }

        var msgWrap = document.getElementById('profileMsgWrap');
        var msgBtn = document.getElementById('profileMsgBtn');
        if (msgWrap && msgBtn) {
            if (isOnline) {
                msgWrap.style.display = '';
                msgBtn.disabled = false;
                msgBtn.textContent = 'Message ' + name;
                msgBtn.onclick = function() { openChat(emp.id); };
                var msgSub = document.getElementById('profileMsgSub');
                if (msgSub) msgSub.textContent = 'Start a conversation';
            } else {
                msgWrap.style.display = 'none';
            }
        }
    }
}

function _contactRow(type, text, href) {
    var row = document.createElement('div');
    row.className = 'dir-profile-contact-row';

    var icon = document.createElement('span');
    icon.className = 'dir-profile-contact-icon';
    if (type === 'email') icon.textContent = '\u2709';
    else if (type === 'phone') icon.textContent = '\u260E';
    else if (type === 'dept') icon.textContent = '\u2302';
    row.appendChild(icon);

    if (href) {
        var link = document.createElement('a');
        link.href = href;
        link.className = 'dir-profile-contact-link';
        link.textContent = text;
        row.appendChild(link);
    } else {
        var span = document.createElement('span');
        span.className = 'dir-profile-contact-text';
        span.textContent = text;
        row.appendChild(span);
    }
    return row;
}

/* ---------- HELPERS ---------- */

function getInitials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return parts[0].substring(0, 2).toUpperCase();
}

// Legacy helper — kept for backward compat but now just returns ''
function guessStation(department) {
    return '';
}

function debounce(fn, ms) {
    let timer;
    return function() {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, arguments), ms);
    };
}

/* ---------- CHAT PANEL ---------- */

let _chatAgentId = null;
let _chatAgentData = null;
let _chatEscHandler = null;
let _chatSending = false;

function openChat(agentId) {
    if (!agentId || !isAuthenticated) return;
    _chatAgentId = agentId;

    var panel = document.getElementById('chatPanel');
    var overlay = document.getElementById('chatOverlay');
    if (!panel) return;

    // Close profile panel first
    closeProfile();

    // Look up agent data from orgChartNodes
    _chatAgentData = null;
    if (orgChartNodes) {
        _chatAgentData = orgChartNodes.find(function(n) { return n.id === agentId; });
    }

    // Set header
    var agentName = _chatAgentData
        ? (_chatAgentData.full_name || _chatAgentData.display_name || _chatAgentData.name || 'Agent')
        : 'Agent';
    var dept = _chatAgentData ? (_chatAgentData.department || '') : '';
    var color = getDeptColor(dept);

    var headerName = document.getElementById('chatHeaderName');
    if (headerName) headerName.textContent = agentName;

    var headerAvatar = document.getElementById('chatHeaderAvatar');
    if (headerAvatar) {
        headerAvatar.textContent = '';
        headerAvatar.style.background = color + '33';
        headerAvatar.style.border = '2px solid ' + color;
        if (_chatAgentData && _chatAgentData.avatar_url) {
            var img = document.createElement('img');
            img.src = _chatAgentData.avatar_url;
            img.alt = agentName;
            img.style.width = '100%';
            img.style.height = '100%';
            img.style.objectFit = 'cover';
            img.style.borderRadius = '50%';
            headerAvatar.appendChild(img);
        } else {
            headerAvatar.textContent = getInitials(agentName);
        }
    }

    // Clear messages area
    var messagesEl = document.getElementById('chatMessages');
    if (messagesEl) messagesEl.textContent = '';

    // Hide memory banner and typing
    var memBanner = document.getElementById('chatMemoryBanner');
    if (memBanner) memBanner.style.display = 'none';
    var typing = document.getElementById('chatTyping');
    if (typing) typing.style.display = 'none';

    // Clear input
    var input = document.getElementById('chatInput');
    if (input) { input.value = ''; }
    _updateSendBtn();

    // Show panel
    panel.classList.add('active');
    if (overlay) overlay.classList.add('active');

    // Bind close
    var closeBtn = document.getElementById('chatCloseBtn');
    if (closeBtn) closeBtn.onclick = closeChat;
    if (overlay) overlay.onclick = closeChat;

    _chatEscHandler = function(e) { if (e.key === 'Escape') closeChat(); };
    document.addEventListener('keydown', _chatEscHandler);

    // Bind input events
    if (input) {
        input.onkeydown = function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        };
        input.oninput = _updateSendBtn;
    }
    var sendBtn = document.getElementById('chatSendBtn');
    if (sendBtn) sendBtn.onclick = sendMessage;

    // Load history
    _loadChatHistory(agentId);

    // Focus input after a tick
    setTimeout(function() { if (input) input.focus(); }, 350);
}

function closeChat() {
    var panel = document.getElementById('chatPanel');
    var overlay = document.getElementById('chatOverlay');
    if (panel) panel.classList.remove('active');
    if (overlay) overlay.classList.remove('active');
    if (_chatEscHandler) {
        document.removeEventListener('keydown', _chatEscHandler);
        _chatEscHandler = null;
    }
    _chatAgentId = null;
}

async function _loadChatHistory(agentId) {
    var messagesEl = document.getElementById('chatMessages');
    if (!messagesEl) return;

    try {
        var resp = await fetch('/api/directory/chat/' + encodeURIComponent(agentId));
        if (!resp.ok) throw new Error('Failed to load');
        var data = await resp.json();

        messagesEl.textContent = '';

        // Memory banner
        if (data.pinned_memories && data.pinned_memories.length > 0) {
            _renderMemoryBanner(data.pinned_memories);
        }

        // Messages
        if (!data.messages || data.messages.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'dir-chat-empty';
            var agentName = _chatAgentData
                ? (_chatAgentData.full_name || _chatAgentData.display_name || 'this agent')
                : 'this agent';
            empty.textContent = 'Start a conversation with ' + agentName;
            messagesEl.appendChild(empty);
        } else {
            data.messages.forEach(function(msg) {
                _appendMessage(msg.sender_type, msg.message, msg.timestamp);
            });
            _scrollToBottom();
        }
    } catch (err) {
        messagesEl.textContent = '';
        var errDiv = document.createElement('div');
        errDiv.className = 'dir-chat-empty';
        errDiv.textContent = 'Start a new conversation';
        messagesEl.appendChild(errDiv);
    }
}

async function sendMessage() {
    if (_chatSending || !_chatAgentId) return;
    var input = document.getElementById('chatInput');
    var message = (input ? input.value : '').trim();
    if (!message) return;

    _chatSending = true;
    _updateSendBtn();

    // Clear input immediately
    if (input) input.value = '';

    // Clear empty placeholder if present
    var messagesEl = document.getElementById('chatMessages');
    var emptyEl = messagesEl ? messagesEl.querySelector('.dir-chat-empty') : null;
    if (emptyEl) emptyEl.remove();

    // Append user message
    _appendMessage('user', message, new Date().toISOString());
    _scrollToBottom();

    // Show typing indicator
    var typing = document.getElementById('chatTyping');
    if (typing) typing.style.display = 'flex';
    _scrollToBottom();

    try {
        var resp = await fetch('/api/directory/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agent_id: _chatAgentId, message: message })
        });
        var data = await resp.json();

        if (typing) typing.style.display = 'none';

        if (!resp.ok) {
            _appendMessage('agent', data.error || 'Something went wrong.', new Date().toISOString());
        } else {
            _appendMessage('agent', data.response, data.timestamp || new Date().toISOString());
        }
        _scrollToBottom();
    } catch (err) {
        if (typing) typing.style.display = 'none';
        _appendMessage('agent', 'Network error. Please try again.', new Date().toISOString());
        _scrollToBottom();
    } finally {
        _chatSending = false;
        _updateSendBtn();
        if (input) input.focus();
    }
}

function _appendMessage(senderType, text, timestamp) {
    var messagesEl = document.getElementById('chatMessages');
    if (!messagesEl) return;

    var bubble = document.createElement('div');
    bubble.className = 'dir-chat-bubble ' +
        (senderType === 'user' ? 'dir-chat-bubble-user' : 'dir-chat-bubble-agent');

    // Set department color accent for agent bubbles
    if (senderType === 'agent' && _chatAgentData) {
        var dept = _chatAgentData.department || '';
        var agentColor = getDeptColor(dept);
        if (agentColor) {
            bubble.style.borderLeft = '3px solid ' + agentColor;
        }
    }

    bubble.textContent = text;
    messagesEl.appendChild(bubble);

    // Timestamp
    if (timestamp) {
        var tsEl = document.createElement('div');
        tsEl.className = 'dir-chat-timestamp ' +
            (senderType === 'user' ? 'dir-chat-ts-right' : 'dir-chat-ts-left');
        try {
            var d = new Date(timestamp);
            tsEl.textContent = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch (e) {
            tsEl.textContent = '';
        }
        messagesEl.appendChild(tsEl);
    }
}

function _renderMemoryBanner(memories) {
    var banner = document.getElementById('chatMemoryBanner');
    if (!banner || !memories.length) return;
    banner.textContent = '';

    var agentName = _chatAgentData
        ? (_chatAgentData.full_name || _chatAgentData.display_name || 'Agent')
        : 'Agent';

    var label = document.createElement('strong');
    label.textContent = agentName + ' remembers: ';
    banner.appendChild(label);

    var texts = memories.map(function(m) { return m.text; });
    banner.appendChild(document.createTextNode(texts.join(' | ')));
    banner.style.display = '';
}

function _scrollToBottom() {
    var messagesEl = document.getElementById('chatMessages');
    if (messagesEl) {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }
}

function _updateSendBtn() {
    var input = document.getElementById('chatInput');
    var btn = document.getElementById('chatSendBtn');
    if (btn) {
        btn.disabled = _chatSending || !(input && input.value.trim());
    }
}

// Expose for onclick handlers in template
window.openProfile = openProfile;
window.closeProfile = closeProfile;
window.openChat = openChat;
window.closeChat = closeChat;
