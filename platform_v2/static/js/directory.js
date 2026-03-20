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

async function openProfile(employeeId) {
    if (!employeeId) return;
    const panel = document.getElementById('profilePanel');
    const overlay = document.getElementById('profileOverlay');
    const nameEl = document.getElementById('profileName');
    const bodyEl = document.getElementById('profileBody');
    if (!panel || !bodyEl) return;

    bodyEl.textContent = '';
    const loadingDiv = document.createElement('div');
    loadingDiv.style.cssText = 'color:#64748b;padding:20px;';
    loadingDiv.textContent = 'Loading profile...';
    bodyEl.appendChild(loadingDiv);
    nameEl.textContent = 'Loading...';
    panel.classList.add('open');
    if (overlay) overlay.classList.add('open');

    try {
        const resp = await fetch('/api/directory/' + employeeId);
        const data = await resp.json();
        if (!data.success) throw new Error(data.error);

        const emp = data.employee;
        const name = emp.full_name || emp.name || 'Unknown';
        nameEl.textContent = name;

        bodyEl.textContent = '';

        const station = guessStation(emp.department || '');
        const color = STATION_COLORS[station] || '#00e5ff';

        // Portrait
        const portraitWrap = document.createElement('div');
        portraitWrap.style.cssText = 'text-align:center;margin-bottom:24px;';
        if (emp.avatar_url) {
            const img = document.createElement('img');
            img.src = emp.avatar_url;
            img.alt = name;
            img.style.cssText = 'width:120px;height:120px;border-radius:50%;object-fit:cover;border:3px solid ' + color;
            portraitWrap.appendChild(img);
        } else {
            const initCircle = document.createElement('div');
            initCircle.style.cssText = 'width:120px;height:120px;border-radius:50%;background:' + color + '22;border:3px solid ' + color + ';display:inline-flex;align-items:center;justify-content:center;font-family:Orbitron,sans-serif;font-size:2rem;font-weight:700;color:#f1f5f9;';
            initCircle.textContent = getInitials(name);
            portraitWrap.appendChild(initCircle);
        }
        bodyEl.appendChild(portraitWrap);

        // Info block
        const infoBlock = document.createElement('div');
        infoBlock.style.marginBottom = '16px';

        const pName = document.createElement('div');
        pName.style.cssText = 'color:#f1f5f9;font-weight:600;font-size:1.1rem;margin-bottom:4px;';
        pName.textContent = name;
        infoBlock.appendChild(pName);

        const pTitle = document.createElement('div');
        pTitle.style.cssText = 'color:' + color + ';font-size:0.9rem;margin-bottom:4px;';
        pTitle.textContent = emp.title || 'Team Member';
        infoBlock.appendChild(pTitle);

        const pDept = document.createElement('div');
        pDept.style.cssText = 'color:#64748b;font-size:0.85rem;';
        pDept.textContent = emp.department || '';
        infoBlock.appendChild(pDept);

        bodyEl.appendChild(infoBlock);

        // Contact
        if (emp.email) {
            const emailRow = document.createElement('div');
            emailRow.style.cssText = 'margin-bottom:8px;font-size:0.85rem;';
            const emailLabel = document.createElement('span');
            emailLabel.style.color = '#64748b';
            emailLabel.textContent = 'Email: ';
            emailRow.appendChild(emailLabel);
            const emailLink = document.createElement('a');
            emailLink.href = 'mailto:' + emp.email;
            emailLink.style.cssText = 'color:#00e5ff;text-decoration:none;';
            emailLink.textContent = emp.email;
            emailRow.appendChild(emailLink);
            bodyEl.appendChild(emailRow);
        }
        if (emp.extension) {
            const extRow = document.createElement('div');
            extRow.style.cssText = 'margin-bottom:8px;font-size:0.85rem;';
            const extLabel = document.createElement('span');
            extLabel.style.color = '#64748b';
            extLabel.textContent = 'Ext: ';
            extRow.appendChild(extLabel);
            const extVal = document.createElement('span');
            extVal.style.color = '#f1f5f9';
            extVal.textContent = emp.extension;
            extRow.appendChild(extVal);
            bodyEl.appendChild(extRow);
        }

        // Bio
        if (emp.bio) {
            const bioDiv = document.createElement('div');
            bioDiv.style.cssText = 'margin-top:20px;padding:16px;background:#1e293b;border-radius:8px;border-left:3px solid ' + color + ';font-size:0.85rem;color:#94a3b8;line-height:1.6;';
            bioDiv.textContent = emp.bio;
            bodyEl.appendChild(bioDiv);
        }

        // Specialties
        if (emp.specialties && emp.specialties.length > 0) {
            const specWrap = document.createElement('div');
            specWrap.style.marginTop = '16px';

            const specLabel = document.createElement('div');
            specLabel.style.cssText = 'color:#64748b;font-size:0.78rem;margin-bottom:8px;text-transform:uppercase;letter-spacing:1px;';
            specLabel.textContent = 'Expertise';
            specWrap.appendChild(specLabel);

            const specTags = document.createElement('div');
            specTags.style.cssText = 'display:flex;flex-wrap:wrap;gap:6px;';
            emp.specialties.forEach(s => {
                const tag = document.createElement('span');
                tag.className = 'dir-skill-tag';
                tag.style.borderColor = color + '33';
                tag.style.color = color;
                tag.style.background = color + '15';
                tag.textContent = s;
                specTags.appendChild(tag);
            });
            specWrap.appendChild(specTags);
            bodyEl.appendChild(specWrap);
        }

    } catch (err) {
        bodyEl.textContent = '';
        const errDiv = document.createElement('div');
        errDiv.style.cssText = 'color:#ef4444;padding:20px;';
        errDiv.textContent = 'Failed to load profile.';
        bodyEl.appendChild(errDiv);
    }
}

function closeProfile() {
    const panel = document.getElementById('profilePanel');
    const overlay = document.getElementById('profileOverlay');
    if (panel) panel.classList.remove('open');
    if (overlay) overlay.classList.remove('open');
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
