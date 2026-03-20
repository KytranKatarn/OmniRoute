/* ==========================================================================
   EMPLOYEE DIRECTORY — Kytran Empowerment
   Loads team data, renders org chart, department cards, filters.
   All dynamic content is sanitized via escHtml()/escAttr() before DOM insertion.
   ========================================================================== */

const STATION_COLORS = {
    COMMAND: '#00e5ff',
    ANALYTICS: '#8b5cf6',
    CREATIVE: '#f472b6',
    ENGINEERING: '#fbbf24',
    COMMUNICATIONS: '#22d3ee',
    RESEARCH: '#10b981',
    SECURITY: '#ef4444',
    LOGISTICS: '#f97316',
    DIPLOMATIC: '#818cf8',
    OPERATIONS: '#a3e635'
};

// Department-to-station mapping (best guess from department name)
const DEPT_STATION_MAP = {
    'Command': 'COMMAND',
    'Analytics': 'ANALYTICS',
    'Creative': 'CREATIVE',
    'Engineering': 'ENGINEERING',
    'Communications': 'COMMUNICATIONS',
    'Research': 'RESEARCH',
    'Security': 'SECURITY',
    'Logistics': 'LOGISTICS',
    'Diplomatic': 'DIPLOMATIC',
    'Operations': 'OPERATIONS'
};

let directoryData = null;
let isAuthenticated = false;

document.addEventListener('DOMContentLoaded', init);

async function init() {
    const wrapper = document.querySelector('.dir-wrapper');
    isAuthenticated = wrapper && wrapper.dataset.authenticated === 'true';
    await Promise.all([loadDirectory(), loadOrgChart()]);
    setupFilters();
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
        renderDepartments(data.by_department);
    } catch (err) {
        const el = document.getElementById('dirDepartments');
        if (el) {
            el.textContent = '';
            const div = document.createElement('div');
            div.className = 'dir-loading';
            div.style.color = '#ef4444';
            div.textContent = 'Failed to load directory: ' + err.message;
            el.appendChild(div);
        }
    }
}

function renderHeroStats(stats) {
    const el = (id) => document.getElementById(id);
    if (el('statTotalMembers')) el('statTotalMembers').textContent = stats.total_members || 0;
    if (el('statDepartments')) el('statDepartments').textContent = stats.total_departments || 0;
    // Online count will be populated by Task 5 live status polling
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

/* ---------- DEPARTMENT RENDERING ---------- */

function renderDepartments(byDepartment) {
    const container = document.getElementById('dirDepartments');
    if (!container) return;
    container.textContent = '';

    const depts = Object.keys(byDepartment).sort();
    if (depts.length === 0) {
        const noRes = document.createElement('div');
        noRes.className = 'dir-no-results';
        noRes.textContent = 'No team members found.';
        container.appendChild(noRes);
        return;
    }

    depts.forEach(dept => {
        const members = byDepartment[dept];
        const station = guessStation(dept);
        const color = STATION_COLORS[station] || '#00e5ff';

        const section = document.createElement('div');
        section.className = 'dir-dept-section';
        section.dataset.department = dept;

        // Header
        const header = document.createElement('div');
        header.className = 'dir-dept-header';

        const accent = document.createElement('div');
        accent.className = 'dir-dept-accent';
        accent.style.background = color;
        header.appendChild(accent);

        const nameEl = document.createElement('span');
        nameEl.className = 'dir-dept-name';
        nameEl.textContent = dept;
        header.appendChild(nameEl);

        const countEl = document.createElement('span');
        countEl.className = 'dir-dept-count';
        countEl.textContent = members.length + ' member' + (members.length !== 1 ? 's' : '');
        header.appendChild(countEl);

        section.appendChild(header);

        // Card grid
        const grid = document.createElement('div');
        grid.className = 'dir-card-grid';
        members.forEach(member => {
            grid.appendChild(buildCard(member, station, color));
        });
        section.appendChild(grid);
        container.appendChild(section);
    });
}

function buildCard(member, station, color) {
    const name = member.full_name || member.name || 'Team Member';
    const title = member.title || 'Team Member';
    const email = member.email || name.toLowerCase().replace(/\s+/g, '.') + '@kytranempowerment.com';
    const initials = getInitials(name);
    const agentId = member.id || 0;

    const card = document.createElement('div');
    card.className = 'dir-card';
    card.dataset.agentId = agentId;
    card.dataset.name = name;
    card.dataset.title = title;
    card.dataset.department = member.department || '';
    card.addEventListener('click', () => openProfile(agentId));

    // Portrait area
    const portrait = document.createElement('div');
    portrait.className = 'dir-portrait ' + (station ? 'dir-bg-' + station : 'dir-portrait-default');
    if (member.avatar_url) {
        const img = document.createElement('img');
        img.src = member.avatar_url;
        img.alt = name;
        img.loading = 'lazy';
        portrait.appendChild(img);
    } else {
        const initialsEl = document.createElement('div');
        initialsEl.className = 'dir-initials';
        initialsEl.style.background = color + '33';
        initialsEl.style.borderColor = color + '55';
        initialsEl.textContent = initials;
        portrait.appendChild(initialsEl);
    }
    card.appendChild(portrait);

    // Card body
    const body = document.createElement('div');
    body.className = 'dir-card-body';

    const nameDiv = document.createElement('div');
    nameDiv.className = 'dir-card-name';
    nameDiv.textContent = name;
    body.appendChild(nameDiv);

    const titleDiv = document.createElement('div');
    titleDiv.className = 'dir-card-title' + (station ? ' dir-color-' + station : '');
    titleDiv.textContent = title;
    body.appendChild(titleDiv);

    const emailDiv = document.createElement('div');
    emailDiv.className = 'dir-card-email';
    const emailLink = document.createElement('a');
    emailLink.href = 'mailto:' + email;
    emailLink.textContent = email;
    emailDiv.appendChild(emailLink);
    body.appendChild(emailDiv);

    // Skill tags
    if (member.specialties && member.specialties.length > 0) {
        const tagsDiv = document.createElement('div');
        tagsDiv.className = 'dir-skill-tags';
        member.specialties.slice(0, 3).forEach(skill => {
            const tag = document.createElement('span');
            tag.className = 'dir-skill-tag';
            tag.style.borderColor = color + '33';
            tag.style.color = color;
            tag.style.background = color + '15';
            tag.textContent = skill;
            tagsDiv.appendChild(tag);
        });
        body.appendChild(tagsDiv);
    }

    // Status footer (authenticated only)
    if (isAuthenticated) {
        const footer = document.createElement('div');
        footer.className = 'dir-card-footer';

        const status = document.createElement('div');
        status.className = 'dir-status';
        const dot = document.createElement('span');
        dot.className = 'dir-status-dot offline';
        status.appendChild(dot);
        const statusText = document.createElement('span');
        statusText.textContent = 'Off Duty';
        status.appendChild(statusText);
        footer.appendChild(status);

        const chatBtn = document.createElement('button');
        chatBtn.className = 'dir-chat-btn unavailable';
        chatBtn.textContent = 'Unavailable';
        footer.appendChild(chatBtn);

        body.appendChild(footer);
    }

    card.appendChild(body);
    return card;
}

/* ---------- ORG CHART ---------- */

async function loadOrgChart() {
    try {
        const resp = await fetch('/api/directory/org-chart');
        const data = await resp.json();
        if (!data.success) throw new Error(data.error || 'Failed to load');
        renderOrgChart(data.nodes);
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

    // Find key people
    const kytran = nodes.find(n => n.employee_type === 'Human' && /kytran/i.test(n.full_name || n.name || ''));
    const archie = nodes.find(n => /^archie$/i.test(n.name || '') || /^archie$/i.test(n.display_name || ''));
    const vigil = nodes.find(n => /^vigil$/i.test(n.name || '') || /^vigil$/i.test(n.display_name || ''));

    // Level 1: CEO
    chart.appendChild(createOrgLevel([
        kytran || { full_name: 'Kytran', title: 'CEO & Founder', employee_type: 'Human', _station: 'ceo' }
    ], 'role-ceo'));

    chart.appendChild(createConnector());

    // Level 2: AI Leadership
    const level2 = [];
    if (archie) level2.push(Object.assign({}, archie, { _station: 'COMMAND' }));
    else level2.push({ full_name: 'ARCHIE', title: 'AI Director', employee_type: 'AI', station_code: 'COMMAND', _station: 'COMMAND' });
    if (vigil) level2.push(Object.assign({}, vigil, { _station: 'COMMAND' }));
    else level2.push({ full_name: 'Vigil', title: 'Ethics Officer', employee_type: 'AI', station_code: 'COMMAND', _station: 'COMMAND' });

    chart.appendChild(createOrgLevel(level2));

    chart.appendChild(createConnector());
    chart.appendChild(createHorizontalConnector());
    chart.appendChild(createConnector());

    // Level 3: Department heads (one per station, excluding COMMAND)
    const skipIds = [kytran, archie, vigil].filter(Boolean).map(n => n.id);
    const stations = ['ANALYTICS', 'CREATIVE', 'ENGINEERING', 'COMMUNICATIONS', 'RESEARCH', 'SECURITY', 'LOGISTICS', 'DIPLOMATIC', 'OPERATIONS'];
    const deptHeads = [];

    stations.forEach(station => {
        const head = nodes.find(n => n.station_code === station && !skipIds.includes(n.id));
        if (head) {
            deptHeads.push(Object.assign({}, head, { _station: station }));
        }
    });

    if (deptHeads.length > 0) {
        chart.appendChild(createOrgLevel(deptHeads));
    }
}

function createOrgLevel(people, extraClass) {
    const level = document.createElement('div');
    level.className = 'dir-org-level';
    people.forEach(person => {
        const stationCode = person._station || person.station_code || '';
        const nodeClass = stationCode === 'ceo' ? 'role-ceo' : (stationCode ? 'station-' + stationCode : '');
        const color = stationCode === 'ceo' ? '#f59e0b' : (STATION_COLORS[stationCode] || '#00e5ff');
        const name = person.full_name || person.display_name || person.name || 'Unknown';
        const initials = getInitials(name);
        const title = person.title || '';
        const agentId = person.id || 0;

        const node = document.createElement('div');
        node.className = 'dir-org-node ' + nodeClass + (extraClass ? ' ' + extraClass : '');
        node.addEventListener('click', () => openProfile(agentId));

        const portraitEl = document.createElement('div');
        portraitEl.className = 'dir-org-node-portrait';
        portraitEl.style.background = color + '33';
        portraitEl.style.border = '2px solid ' + color;
        portraitEl.textContent = initials;
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

        level.appendChild(node);
    });
    return level;
}

function createConnector() {
    const c = document.createElement('div');
    c.className = 'dir-org-connector';
    return c;
}

function createHorizontalConnector() {
    const c = document.createElement('div');
    c.className = 'dir-org-connector-horizontal';
    return c;
}

/* ---------- FILTERS ---------- */

function setupFilters() {
    const search = document.getElementById('dirSearch');
    const deptFilter = document.getElementById('dirDeptFilter');
    const statusFilter = document.getElementById('dirStatusFilter');

    if (search) {
        search.addEventListener('input', debounce(applyFilters, 250));
    }
    if (deptFilter) {
        deptFilter.addEventListener('change', applyFilters);
    }
    if (statusFilter) {
        statusFilter.addEventListener('change', applyFilters);
    }
}

function applyFilters() {
    if (!directoryData) return;

    const searchVal = (document.getElementById('dirSearch')?.value || '').toLowerCase().trim();
    const deptVal = document.getElementById('dirDeptFilter')?.value || 'all';
    /* statusVal will be used in Task 5 with live status */
    /* const statusVal = document.getElementById('dirStatusFilter')?.value || 'all'; */

    // Filter members
    const filtered = {};
    Object.keys(directoryData.by_department).forEach(dept => {
        if (deptVal !== 'all' && dept !== deptVal) return;

        const members = directoryData.by_department[dept].filter(m => {
            // Search filter
            if (searchVal) {
                const haystack = [
                    m.full_name || m.name || '',
                    m.title || '',
                    m.department || '',
                    ...(m.specialties || [])
                ].join(' ').toLowerCase();
                if (!haystack.includes(searchVal)) return false;
            }
            return true;
        });

        if (members.length > 0) {
            filtered[dept] = members;
        }
    });

    renderDepartments(filtered);
}

/* ---------- PROFILE PANEL ---------- */

let _profileEscHandler = null;

async function openProfile(employeeId) {
    if (!employeeId) return;
    const panel = document.getElementById('profilePanel');
    const overlay = document.getElementById('profileOverlay');
    const nameEl = document.getElementById('profileName');
    if (!panel) return;

    // Show panel with loading state
    nameEl.textContent = 'Loading...';
    _resetProfileSections();
    panel.classList.add('active');
    if (overlay) overlay.classList.add('active');

    // ESC key listener
    _profileEscHandler = function(e) {
        if (e.key === 'Escape') closeProfile();
    };
    document.addEventListener('keydown', _profileEscHandler);

    // Backdrop click
    if (overlay) overlay.onclick = closeProfile;

    // Close button
    var closeBtn = document.getElementById('profileCloseBtn');
    if (closeBtn) closeBtn.onclick = closeProfile;

    try {
        const resp = await fetch('/api/directory/' + encodeURIComponent(employeeId));
        const data = await resp.json();
        if (!data.success) throw new Error(data.error || 'Not found');

        const emp = data.employee;
        _populateProfile(emp);

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
    // Clear dynamic content areas
    var ids = ['profilePortraitWrap', 'profileIdentity', 'profileStatusRow',
               'profileContactList', 'profileBioText', 'profileSkillsWrap'];
    ids.forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.textContent = '';
    });
    // Hide optional sections
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
    var station = guessStation(dept);
    var color = STATION_COLORS[station] || '#00e5ff';

    // Header name
    var nameEl = document.getElementById('profileName');
    if (nameEl) nameEl.textContent = name;

    // --- Portrait ---
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

        // Status dot overlay (bottom-right)
        var statusDot = document.createElement('span');
        statusDot.className = 'dir-profile-portrait-dot offline';
        statusDot.id = 'profilePortraitDot';
        portraitOuter.appendChild(statusDot);

        portraitWrap.appendChild(portraitOuter);
    }

    // --- Identity (name, title, station+role) ---
    var identityEl = document.getElementById('profileIdentity');
    if (identityEl) {
        identityEl.textContent = '';

        var pName = document.createElement('div');
        pName.className = 'dir-profile-id-name';
        pName.textContent = name;
        identityEl.appendChild(pName);

        var pTitle = document.createElement('div');
        pTitle.className = 'dir-profile-id-title';
        pTitle.style.color = color;
        pTitle.textContent = title;
        identityEl.appendChild(pTitle);

        if (station || dept) {
            var pStation = document.createElement('div');
            pStation.className = 'dir-profile-id-station';
            var stationText = station ? (station + ' Station') : dept;
            if (emp.employee_type) {
                stationText += ' \u2022 ' + emp.employee_type;
            }
            pStation.textContent = stationText;
            identityEl.appendChild(pStation);
        }

        // Pronouns
        if (emp.pronouns) {
            var pPronouns = document.createElement('div');
            pPronouns.className = 'dir-profile-id-pronouns';
            pPronouns.textContent = emp.pronouns;
            identityEl.appendChild(pPronouns);
        }
    }

    // --- Status Badge ---
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

    // --- Contact Card ---
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

    // --- Bio ---
    var bioText = document.getElementById('profileBioText');
    var bioSection = document.getElementById('profileBio');
    if (bioText && bioSection && emp.bio) {
        bioText.textContent = emp.bio;
        bioSection.style.display = '';
    }

    // --- Skills ---
    var skillsWrap = document.getElementById('profileSkillsWrap');
    var skillsSection = document.getElementById('profileSkills');
    if (skillsWrap && skillsSection && emp.specialties && emp.specialties.length > 0) {
        skillsWrap.textContent = '';
        emp.specialties.forEach(function(skill) {
            var pill = document.createElement('span');
            pill.className = 'dir-profile-skill';
            pill.style.borderColor = color + '44';
            pill.style.color = color;
            pill.style.background = color + '18';
            pill.textContent = skill;
            skillsWrap.appendChild(pill);
        });
        skillsSection.style.display = '';
    }

    // --- Currently Working On (internal only) ---
    if (isAuthenticated) {
        var workingText = document.getElementById('profileWorkingText');
        var workingSection = document.getElementById('profileWorkingOn');
        if (workingText && workingSection) {
            workingText.textContent = 'No active jobs';
            workingSection.style.display = '';
        }
    }

    // --- Message Button (internal only, hidden until Task 6) ---
    // Left hidden for now; Task 6 will wire up chat functionality.
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

function guessStation(department) {
    if (!department) return '';
    // Direct match
    const upper = department.toUpperCase();
    if (STATION_COLORS[upper]) return upper;
    // Partial match
    for (const key of Object.keys(DEPT_STATION_MAP)) {
        if (department.toLowerCase().includes(key.toLowerCase())) return DEPT_STATION_MAP[key];
    }
    return '';
}

function debounce(fn, ms) {
    let timer;
    return function() {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, arguments), ms);
    };
}

// Expose for onclick handlers in template
window.openProfile = openProfile;
window.closeProfile = closeProfile;
