/* ==========================================================================
   EMPLOYEE DIRECTORY — Kytran Empowerment
   Loads team data, renders full pyramid org chart with all agents.
   All dynamic content is sanitized via escHtml()/escAttr() before DOM insertion.
   ========================================================================== */

const DEPT_COLORS = {
    'Analytics & Intelligence': '#8b5cf6',
    'Creative & Design': '#f472b6',
    'Customer Success & Support': '#06b6d4',
    'Diplomatic & External Relations': '#818cf8',
    'Documentation & Knowledge': '#d4a843',
    'Engineering & Technology': '#fbbf24',
    'Executive Office': '#f59e0b',
    'Finance & Accounting': '#10b981',
    'Human Resources & Culture': '#a78bfa',
    'Legal & Regulatory': '#94a3b8',
    'Logistics & Supply Chain': '#a3e635',
    'Marketing & Communications': '#22d3ee',
    'Medical & Wellness': '#ec4899',
    'Operations & Infrastructure': '#f97316',
    'Research & Development': '#34d399',
    'Security & Compliance': '#ef4444',
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
        renderCardsGrid(data.nodes);
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

function renderCardsGrid(nodes) {
    const leadershipEl = document.getElementById('dirLeadership');
    const deptGridEl = document.getElementById('dirDeptGrid');

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

    // --- Leadership Banner ---
    const leaders = [
        { name: 'Kytran', title: 'CEO & Founder', employee_type: 'Human', department: 'Executive', id: 0 },
        archie || { name: 'A.R.C.H.I.E.', title: 'AI Director / Co-Owner', employee_type: 'AI', department: 'Command', id: 2 },
        vigil || { name: 'Vigil', title: 'Ethics Officer', employee_type: 'AI', department: 'Command', id: 3 }
    ];
    if (leadershipEl) renderLeadershipBanner(leaders, leadershipEl);

    // --- Department Cards Grid ---
    if (!deptGridEl) return;
    deptGridEl.textContent = '';

    // Sort departments by DEPT_COLORS order, then alphabetically for unknown
    const knownDepts = Object.keys(DEPT_COLORS);
    const deptOrder = knownDepts.filter(d => deptMap[d]).concat(
        Object.keys(deptMap).filter(d => !knownDepts.includes(d)).sort()
    );

    deptOrder.forEach(dept => {
        const color = getDeptColor(dept);
        const info = deptMap[dept];
        const allMembers = [];
        if (info.head) allMembers.push(info.head);
        allMembers.push(...info.members);
        renderDeptCard(dept, allMembers, color, deptGridEl);
    });
}

function getDeptColor(dept) {
    return DEPT_COLORS[dept] || '#64748b';
}

function renderLeadershipBanner(leaders, container) {
    container.textContent = '';

    leaders.forEach(person => {
        const name = person.full_name || person.display_name || person.name || 'Unknown';
        const title = person.title || '';
        const agentId = person.id || 0;
        const isCeo = name.toLowerCase() === 'kytran';
        const color = isCeo ? '#f59e0b' : '#00e5ff';

        const card = document.createElement('div');
        card.className = 'dir-leader-card ' + (isCeo ? 'dir-leader-card--ceo' : 'dir-leader-card--ai');
        card.dataset.agentId = String(agentId);
        if (agentId && !isCeo) {
            card.style.cursor = 'pointer';
            card.addEventListener('click', () => openProfile(agentId));
        }

        card.appendChild(createPortrait(person, 'dir-leader-portrait', color));

        const nameEl = document.createElement('div');
        nameEl.className = 'dir-leader-name';
        if (isAuthenticated && !isCeo) {
            const dot = document.createElement('span');
            dot.className = 'dir-status-dot offline';
            dot.style.width = '8px';
            dot.style.height = '8px';
            dot.style.marginRight = '6px';
            nameEl.appendChild(dot);
        }
        nameEl.appendChild(document.createTextNode(name));
        card.appendChild(nameEl);

        const titleEl = document.createElement('div');
        titleEl.className = 'dir-leader-title';
        titleEl.textContent = title;
        card.appendChild(titleEl);

        const roleTag = document.createElement('div');
        roleTag.className = 'dir-leader-role-tag';
        roleTag.textContent = isCeo ? 'HUMAN' : 'AI';
        roleTag.style.color = color;
        roleTag.style.borderColor = color + '44';
        card.appendChild(roleTag);

        container.appendChild(card);
    });

    // Add connector line below leadership
    const connector = document.createElement('div');
    connector.className = 'dir-leadership-connector';
    container.appendChild(connector);
}

function renderDeptCard(deptName, members, color, container) {
    const card = document.createElement('div');
    card.className = 'dir-dept-card';
    card.style.setProperty('--dept-color', color);
    card.dataset.department = deptName;

    const nameEl = document.createElement('div');
    nameEl.className = 'dir-dept-card-name';
    nameEl.style.color = color;
    nameEl.textContent = deptName;
    card.appendChild(nameEl);

    const countEl = document.createElement('div');
    countEl.className = 'dir-dept-card-count';
    countEl.textContent = members.length + ' member' + (members.length !== 1 ? 's' : '');
    card.appendChild(countEl);

    // Avatar thumbnails (up to 3 + overflow)
    const avatarsEl = document.createElement('div');
    avatarsEl.className = 'dir-dept-card-avatars';
    const showCount = Math.min(3, members.length);
    for (let i = 0; i < showCount; i++) {
        avatarsEl.appendChild(createPortrait(members[i], 'dir-dept-card-avatar', color));
    }
    if (members.length > 3) {
        const overflow = document.createElement('div');
        overflow.className = 'dir-dept-card-avatar';
        overflow.style.background = color + '22';
        overflow.style.color = color;
        overflow.style.display = 'flex';
        overflow.style.alignItems = 'center';
        overflow.style.justifyContent = 'center';
        overflow.style.fontSize = '0.7rem';
        overflow.style.fontWeight = '600';
        overflow.textContent = '+' + (members.length - 3);
        avatarsEl.appendChild(overflow);
    }
    card.appendChild(avatarsEl);

    card.addEventListener('click', () => expandDepartment(deptName, members, color, card));
    container.appendChild(card);
}

let _expandedDeptName = null;

function expandDepartment(deptName, members, color, cardEl) {
    // Remove any existing expanded panel
    const existing = document.querySelector('.dir-dept-expanded');
    if (existing) existing.remove();

    // Toggle: if same dept was open, just close
    if (_expandedDeptName === deptName) {
        _expandedDeptName = null;
        document.querySelectorAll('.dir-dept-card.expanded').forEach(c => c.classList.remove('expanded'));
        return;
    }

    // Clear previous expanded state
    document.querySelectorAll('.dir-dept-card.expanded').forEach(c => c.classList.remove('expanded'));
    cardEl.classList.add('expanded');
    _expandedDeptName = deptName;

    // Create expanded panel
    const panel = document.createElement('div');
    panel.className = 'dir-dept-expanded open';
    panel.style.setProperty('--dept-color', color);

    // Find department head
    const headRankTerms = ['head', 'director', 'chief', 'lead', 'senior'];
    let head = members.find(m => m.is_head);
    if (!head) {
        head = members.find(m => {
            const t = (m.title || '').toLowerCase();
            return headRankTerms.some(term => t.includes(term));
        });
    }
    const rest = members.filter(m => m !== head);

    // Render head card
    if (head) {
        const headCard = document.createElement('div');
        headCard.className = 'dir-head-card';
        headCard.dataset.agentId = String(head.id || 0);
        if (head.id) {
            headCard.style.cursor = 'pointer';
            headCard.addEventListener('click', () => openProfile(head.id));
        }

        headCard.appendChild(createPortrait(head, 'dir-head-portrait', color));

        const headInfo = document.createElement('div');
        headInfo.className = 'dir-head-info';

        const headNameRow = document.createElement('div');
        headNameRow.style.display = 'flex';
        headNameRow.style.alignItems = 'center';
        headNameRow.style.gap = '8px';

        const headName = document.createElement('div');
        headName.className = 'dir-head-name';
        const hName = head.full_name || head.display_name || head.name || 'Unknown';
        if (isAuthenticated) {
            const dot = document.createElement('span');
            dot.className = 'dir-status-dot offline';
            dot.style.width = '6px';
            dot.style.height = '6px';
            dot.style.marginRight = '4px';
            headName.appendChild(dot);
        }
        headName.appendChild(document.createTextNode(hName));
        headNameRow.appendChild(headName);

        const headBadge = document.createElement('span');
        headBadge.className = 'dir-head-badge';
        headBadge.textContent = 'HEAD';
        headBadge.style.color = color;
        headBadge.style.borderColor = color + '66';
        headNameRow.appendChild(headBadge);
        headInfo.appendChild(headNameRow);

        const headTitle = document.createElement('div');
        headTitle.className = 'dir-head-title';
        headTitle.style.color = color;
        headTitle.textContent = head.title || '';
        headInfo.appendChild(headTitle);

        // Top 3 skills
        const skills = head.top_skills || [];
        if (skills.length > 0) {
            const skillsWrap = document.createElement('div');
            skillsWrap.className = 'dir-head-skills';
            skills.slice(0, 3).forEach(sk => {
                const tag = document.createElement('span');
                tag.className = 'dir-skill-tag';
                tag.textContent = sk.skill || sk.skill_name || sk;
                skillsWrap.appendChild(tag);
            });
            headInfo.appendChild(skillsWrap);
        }

        headCard.appendChild(headInfo);
        panel.appendChild(headCard);
    }

    // Render team grid
    if (rest.length > 0) {
        const teamGrid = document.createElement('div');
        teamGrid.className = 'dir-team-grid';

        rest.forEach(member => {
            const memberEl = document.createElement('div');
            memberEl.className = 'dir-team-member';
            memberEl.dataset.agentId = String(member.id || 0);
            if (member.id) {
                memberEl.style.cursor = 'pointer';
                memberEl.addEventListener('click', () => openProfile(member.id));
            }

            memberEl.appendChild(createPortrait(member, 'dir-team-portrait', color));

            const memberName = document.createElement('div');
            memberName.className = 'dir-team-name';
            const mName = member.full_name || member.display_name || member.name || 'Unknown';
            if (isAuthenticated) {
                const dot = document.createElement('span');
                dot.className = 'dir-status-dot offline';
                dot.style.width = '6px';
                dot.style.height = '6px';
                dot.style.marginRight = '4px';
                memberName.appendChild(dot);
            }
            memberName.appendChild(document.createTextNode(mName));
            memberEl.appendChild(memberName);

            const memberTitle = document.createElement('div');
            memberTitle.className = 'dir-team-title';
            memberTitle.textContent = member.title || '';
            memberEl.appendChild(memberTitle);

            teamGrid.appendChild(memberEl);
        });

        panel.appendChild(teamGrid);
    }

    // Insert panel after the card in the grid
    cardEl.parentNode.insertBefore(panel, cardEl.nextSibling);
}

function createPortrait(person, sizeClass, color) {
    const name = person.full_name || person.display_name || person.name || 'Unknown';
    const el = document.createElement('div');
    el.className = sizeClass;

    if (person.avatar_url) {
        el.style.backgroundImage = 'url(' + person.avatar_url + ')';
        el.style.backgroundSize = 'cover';
        el.style.backgroundPosition = 'center';
    } else {
        el.style.background = color + '22';
        el.style.color = color;
        el.style.display = 'flex';
        el.style.alignItems = 'center';
        el.style.justifyContent = 'center';
        el.style.fontWeight = '600';
        el.textContent = getInitials(name);
    }

    return el;
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

    // Close any expanded department when filters change
    const existing = document.querySelector('.dir-dept-expanded');
    if (existing) existing.remove();
    document.querySelectorAll('.dir-dept-card.expanded').forEach(c => c.classList.remove('expanded'));
    _expandedDeptName = null;

    if (!orgChartNodes) return;

    // Build a set of matching department names for search
    let searchMatchDepts = null;
    if (searchVal) {
        searchMatchDepts = new Set();
        orgChartNodes.forEach(n => {
            const name = (n.full_name || n.display_name || n.name || '').toLowerCase();
            const title = (n.title || '').toLowerCase();
            if (name.includes(searchVal) || title.includes(searchVal)) {
                searchMatchDepts.add(n.department || 'Unassigned');
            }
        });
    }

    // Filter department cards
    document.querySelectorAll('.dir-dept-card').forEach(card => {
        const dept = card.dataset.department || '';
        let visible = true;

        // Department filter
        if (deptVal !== 'all' && dept.toLowerCase() !== deptVal.toLowerCase()) {
            visible = false;
        }

        // Search filter: show card if any member name/title matches
        if (visible && searchVal && searchMatchDepts && !searchMatchDepts.has(dept)) {
            visible = false;
        }

        card.style.display = visible ? '' : 'none';

        // Auto-expand matching department on search
        if (visible && searchVal && searchMatchDepts && searchMatchDepts.has(dept)) {
            // Find the members for this dept from orgChartNodes
            const archie = orgChartNodes.find(n =>
                (n.reports_to === null || n.reports_to === undefined) &&
                (/^archie$/i.test(n.name || '') || /^A\.R\.C\.H\.I\.E\.$/i.test(n.display_name || ''))
            );
            const vigil = orgChartNodes.find(n => /^vigil$/i.test(n.name || '') || /^vigil/i.test(n.display_name || ''));
            const skipIds = new Set([archie, vigil].filter(Boolean).map(n => n.id));

            const deptMembers = orgChartNodes.filter(n =>
                !skipIds.has(n.id) && (n.department || 'Unassigned') === dept
            );
            const color = getDeptColor(dept);
            expandDepartment(dept, deptMembers, color, card);
        }
    });

    // Filter leader cards
    document.querySelectorAll('.dir-leader-card').forEach(card => {
        if (!searchVal) {
            card.style.display = '';
            return;
        }
        const name = (card.querySelector('.dir-leader-name')?.textContent || '').toLowerCase();
        const title = (card.querySelector('.dir-leader-title')?.textContent || '').toLowerCase();
        card.style.display = (name.includes(searchVal) || title.includes(searchVal)) ? '' : 'none';
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

        // Performance score hidden from public directory (internal metric only)
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
    // Strip parenthetical callsigns like "(DataMind)" or "(Compact)"
    const clean = name.replace(/\s*\(.*?\)\s*/g, '').trim();
    const parts = clean.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return parts[0] ? parts[0].substring(0, 2).toUpperCase() : '?';
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
