// Global state
let users = [];
let selectedUserId = null;
let activityChart = null;
let currentPage = 1;
let totalPages = 1;
let totalUsers = 0;
let pageSize = 10;
let importData = [];

// Sessions auto-refresh with animated countdown
let sessionsRefreshInterval = null;
let sessionsCountdownInterval = null;
let sessionsCountdown = 15;
const SESSIONS_REFRESH_S = 15;
const CIRCUMFERENCE = 50.265; // 2 * PI * 8

// ────────────────────────────────────────────────────────────────────────────
// api(path, opts) — thin wrapper around api() for centralized behavior.
// Same signature as fetch(); drop-in replacement. SAAS_API calls intentionally
// stay as raw api() because they target a different module (/tools/saas-manager).
// innerHTML audit (2026-04-16): 6 sites in this file; all use hardcoded template
// strings or trusted local values (e.g. s.icon from inline array). No XSS surface.
// ────────────────────────────────────────────────────────────────────────────
async function api(path, opts) {
    return fetch(path, opts);
}

function startSessionsAutoRefresh() {
    stopSessionsAutoRefresh();
    sessionsCountdown = SESSIONS_REFRESH_S;
    var indicator = document.getElementById('sessions-refresh-indicator');
    if (indicator) indicator.style.display = 'flex';
    updateRefreshRing();

    sessionsCountdownInterval = setInterval(function() {
        sessionsCountdown--;
        if (sessionsCountdown <= 0) {
            loadSessions();
            sessionsCountdown = SESSIONS_REFRESH_S;
        }
        updateRefreshRing();
    }, 1000);
}

function stopSessionsAutoRefresh() {
    if (sessionsCountdownInterval) {
        clearInterval(sessionsCountdownInterval);
        sessionsCountdownInterval = null;
    }
    if (sessionsRefreshInterval) {
        clearInterval(sessionsRefreshInterval);
        sessionsRefreshInterval = null;
    }
    var indicator = document.getElementById('sessions-refresh-indicator');
    if (indicator) indicator.style.display = 'none';
}

function updateRefreshRing() {
    var progress = document.querySelector('.refresh-ring-progress');
    var label = document.querySelector('.refresh-label');
    if (!progress || !label) return;

    var fraction = sessionsCountdown / SESSIONS_REFRESH_S;
    var offset = CIRCUMFERENCE * (1 - fraction);
    progress.classList.add('animating');
    progress.style.strokeDashoffset = offset;
    label.textContent = sessionsCountdown + 's';
}

// Tab switching
function switchAccountTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    var panel = document.getElementById('tab-' + tabId);
    if (panel) panel.classList.add('active');

    // Stop auto-refresh when leaving tabs
    stopSessionsAutoRefresh();
    stopActivityAutoRefresh();

    if (tabId === 'pending') loadPendingUsers();
    if (tabId === 'permissions') loadPermissions();
    if (tabId === 'subscriptions') loadTiers();
    if (tabId === 'security') loadSecurityData();
    if (tabId === 'sessions') { loadSessions(); startSessionsAutoRefresh(); }
    if (tabId === 'api-keys') loadApiKeys();
    if (tabId === 'activity') { loadActivity(); startActivityAutoRefresh(); }
    if (tabId === 'organizations') saasLoadOrgs();
}

// Bridge LCARS header tabs → module tab switching
window.onLcarsTabSwitch = function(tabId) { switchAccountTab(tabId); };

document.addEventListener('DOMContentLoaded', () => {
    // Deep-link support: ?tab=organizations
    const params = new URLSearchParams(window.location.search);
    const startTab = params.get('tab');
    if (startTab) {
        switchAccountTab(startTab);
        if (window.lcarsHeaderSwitchTab) lcarsHeaderSwitchTab(startTab);
    }

    loadUsers();
    document.getElementById('filter-role').addEventListener('change', loadUsers);
    document.getElementById('filter-tier').addEventListener('change', loadUsers);
    document.getElementById('search-users').addEventListener('input', debounce(loadUsers, 300));
});

function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

async function loadUsers() {
    const role = document.getElementById('filter-role').value;
    const tier = document.getElementById('filter-tier').value;
    const search = document.getElementById('search-users').value;

    let url = '/tools/account-center/api/users?';
    if (role) url += 'role=' + role + '&';
    if (tier) url += 'tier=' + tier + '&';
    if (search) url += 'search=' + encodeURIComponent(search) + '&';
    url += 'limit=' + pageSize + '&offset=' + ((currentPage - 1) * pageSize);

    try {
        const res = await api(url);
        const data = await res.json();
        if (data.success) {
            users = data.users;
            totalUsers = data.total || 0;
            totalPages = Math.ceil(totalUsers / pageSize) || 1;
            renderUsersTable(data.users);
            updatePagination();
        }
    } catch (err) {
        console.error('Error loading users:', err);
    }
}

function updatePagination() {
    const start = ((currentPage - 1) * pageSize) + 1;
    const end = Math.min(currentPage * pageSize, totalUsers);
    document.getElementById('pagination-info').textContent = 'Showing ' + start + '–' + end + ' of ' + totalUsers;
    document.getElementById('prev-page-btn').disabled = currentPage <= 1;
    document.getElementById('next-page-btn').disabled = currentPage >= totalPages;
}

function changePageSize(newSize) {
    pageSize = parseInt(newSize);
    currentPage = 1;
    loadUsers();
}

function changePage(delta) {
    const newPage = currentPage + delta;
    if (newPage >= 1 && newPage <= totalPages) {
        currentPage = newPage;
        loadUsers();
    }
}

function renderUsersTable(userList) {
    const tbody = document.getElementById('users-table-body');
    if (userList.length === 0) {
        tbody.textContent = '';
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 9;
        td.className = 'empty-state';
        td.textContent = 'No users found';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
    }

    tbody.textContent = '';
    userList.forEach(user => {
        const tr = document.createElement('tr');

        const tdUsername = document.createElement('td');
        const strong = document.createElement('strong');
        strong.textContent = user.username;
        tdUsername.appendChild(strong);

        const tdEmail = document.createElement('td');
        tdEmail.textContent = user.email || '-';

        const tdRole = document.createElement('td');
        const roleBadge = document.createElement('span');
        roleBadge.className = 'badge ' + (user.is_admin ? 'badge-danger' : 'badge-info');
        roleBadge.textContent = user.is_admin ? 'ADMIN' : 'USER';
        tdRole.appendChild(roleBadge);

        const tdTier = document.createElement('td');
        const tierBadge = document.createElement('span');
        tierBadge.className = 'badge ' + getTierBadgeClass(user.subscription_tier);
        tierBadge.textContent = getTierDisplayName(user.subscription_tier);
        tdTier.appendChild(tierBadge);

        const tdStatus = document.createElement('td');
        const statusBadge = document.createElement('span');
        statusBadge.className = 'badge ' + (user.is_active !== false ? 'badge-success' : 'badge-danger');
        statusBadge.textContent = user.is_active !== false ? 'Active' : 'Inactive';
        tdStatus.appendChild(statusBadge);

        const tdSessions = document.createElement('td');
        tdSessions.className = 'hide-fold';
        tdSessions.textContent = user.session_count || 0;
        tdSessions.style.textAlign = 'center';

        const tdKeys = document.createElement('td');
        tdKeys.className = 'hide-fold';
        tdKeys.textContent = user.api_key_count || 0;
        tdKeys.style.textAlign = 'center';

        const tdLogin = document.createElement('td');
        tdLogin.className = 'hide-mobile';
        tdLogin.textContent = user.last_login ? ArchieTime.date(user.last_login) : 'Never';

        const tdActions = document.createElement('td');
        const actionsDiv = document.createElement('div');
        actionsDiv.style.display = 'flex';
        actionsDiv.style.gap = '8px';

        const viewBtn = document.createElement('button');
        viewBtn.className = 'btn btn-sm';
        viewBtn.textContent = 'View';
        viewBtn.onclick = () => viewUser(user.id);

        const editBtn = document.createElement('button');
        editBtn.className = 'btn btn-sm';
        editBtn.textContent = 'Edit';
        editBtn.onclick = () => editUser(user.id);

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn btn-sm btn-danger';
        deleteBtn.textContent = 'Delete';
        deleteBtn.onclick = () => deleteUser(user.id);

        actionsDiv.appendChild(viewBtn);
        actionsDiv.appendChild(editBtn);
        actionsDiv.appendChild(deleteBtn);
        tdActions.appendChild(actionsDiv);

        tr.appendChild(tdUsername);
        tr.appendChild(tdEmail);
        tr.appendChild(tdRole);
        tr.appendChild(tdTier);
        tr.appendChild(tdStatus);
        tr.appendChild(tdSessions);
        tr.appendChild(tdKeys);
        tr.appendChild(tdLogin);
        tr.appendChild(tdActions);
        tbody.appendChild(tr);
    });
}

function getTierBadgeClass(tier) {
    const classes = { 'free': '', 'pro': 'badge-success', 'business': 'badge-warning', 'enterprise': 'badge-purple', 'kytran': 'badge-info', 'collaborator': 'badge-purple', 'guest': '', 'vip': 'badge-purple' };
    return classes[tier] || '';
}

function getTierDisplayName(tier) {
    const names = {
        'kytran':       'KE Owner',
        'collaborator': 'Collaborator',
        'guest':        'Guest',
        'free':         'Free',
        'pro':          'Pro',
        'business':     'Business',
        'enterprise':   'Enterprise',
        'premium':      'Premium',
        'vip':          'VIP',
    };
    return names[(tier || 'free').toLowerCase()] || (tier || 'free').toUpperCase();
}

// ─── Pending User Approval ───────────────────────────────────────────

async function loadPendingUsers() {
    try {
        const res = await api('/tools/account-center/api/users/pending');
        const data = await res.json();
        if (data.success) {
            renderPendingUsers(data.users);
            updatePendingBadge(data.total);
        }
    } catch (err) {
        console.error('Error loading pending users:', err);
    }
}

function renderPendingUsers(userList) {
    const tbody = document.getElementById('pending-users-table-body');
    const emptyState = document.getElementById('pending-empty-state');
    const table = tbody.closest('table');

    if (userList.length === 0) {
        table.style.display = 'none';
        emptyState.style.display = 'block';
        return;
    }

    table.style.display = '';
    emptyState.style.display = 'none';
    tbody.textContent = '';

    userList.forEach(user => {
        const tr = document.createElement('tr');

        const tdUsername = document.createElement('td');
        const strong = document.createElement('strong');
        strong.textContent = user.username;
        tdUsername.appendChild(strong);

        const tdEmail = document.createElement('td');
        tdEmail.textContent = user.email || '-';

        const tdRole = document.createElement('td');
        const roleBadge = document.createElement('span');
        roleBadge.className = 'badge badge-info';
        roleBadge.textContent = (user.role || 'user').toUpperCase();
        tdRole.appendChild(roleBadge);

        const tdRegistered = document.createElement('td');
        tdRegistered.textContent = user.created_at ? ArchieTime.date(user.created_at) : '-';

        const tdActions = document.createElement('td');
        const actionsDiv = document.createElement('div');
        actionsDiv.style.display = 'flex';
        actionsDiv.style.gap = '8px';

        const approveBtn = document.createElement('button');
        approveBtn.className = 'btn btn-sm btn-primary';
        approveBtn.textContent = 'Approve';
        approveBtn.onclick = () => approveUser(user.id, user.username);

        const denyBtn = document.createElement('button');
        denyBtn.className = 'btn btn-sm btn-danger';
        denyBtn.textContent = 'Deny';
        denyBtn.onclick = () => denyUser(user.id, user.username);

        actionsDiv.appendChild(approveBtn);
        actionsDiv.appendChild(denyBtn);
        tdActions.appendChild(actionsDiv);

        tr.appendChild(tdUsername);
        tr.appendChild(tdEmail);
        tr.appendChild(tdRole);
        tr.appendChild(tdRegistered);
        tr.appendChild(tdActions);
        tbody.appendChild(tr);
    });
}

async function approveUser(userId, username) {
    if (!confirm('Approve user "' + username + '"? They will be able to log in immediately.')) return;
    try {
        const res = await api('/tools/account-center/api/users/' + userId + '/approve', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            loadPendingUsers();
        } else {
            showToast(data.error || 'Failed to approve user', 'error');
        }
    } catch (err) {
        console.error('Error approving user:', err);
        showToast('Error approving user', 'error');
    }
}

async function denyUser(userId, username) {
    if (!confirm('Deny and DELETE user "' + username + '"? This cannot be undone.')) return;
    try {
        const res = await api('/tools/account-center/api/users/' + userId + '/deny', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(data.message, 'success');
            loadPendingUsers();
        } else {
            showToast(data.error || 'Failed to deny user', 'error');
        }
    } catch (err) {
        console.error('Error denying user:', err);
        showToast('Error denying user', 'error');
    }
}

function updatePendingBadge(count) {
    const badge = document.getElementById('pending-tab-badge');
    const tabBtn = document.getElementById('pending-tab-btn');
    const statCard = document.getElementById('pending-stat-card');
    const statValue = document.getElementById('stat-pending');

    if (badge) badge.textContent = count;
    if (statValue) statValue.textContent = count;

    // Hide tab and stat card when no pending users
    if (count === 0) {
        if (tabBtn) tabBtn.style.display = 'none';
        if (statCard) statCard.style.display = 'none';
    } else {
        if (tabBtn) tabBtn.style.display = '';
        if (statCard) statCard.style.display = '';
    }
}

function showToast(message, type) {
    // Use existing toast system if available, otherwise alert
    if (typeof acShowToast === 'function') {
        acShowToast(message, type);
    } else if (typeof saaShowToast === 'function') {
        saasShowToast(message, type);
    } else {
        alert(message);
    }
}

function showAddUserModal() {
    document.getElementById('modal-title').textContent = 'Add User';
    document.getElementById('user-id').value = '';
    document.getElementById('user-form').reset();
    document.getElementById('password-hint').textContent = '(required)';
    document.getElementById('user-password').required = true;
    document.getElementById('user-modal').classList.add('active');
}

async function editUser(userId) {
    try {
        const res = await api('/tools/account-center/api/users/' + userId);
        const data = await res.json();
        if (data.success) {
            const user = data.user;
            document.getElementById('modal-title').textContent = 'Edit User';
            document.getElementById('user-id').value = user.id;
            document.getElementById('user-username').value = user.username;
            document.getElementById('user-email').value = user.email || '';
            document.getElementById('user-password').value = '';
            document.getElementById('user-role').value = user.is_admin ? 'admin' : 'user';
            document.getElementById('user-tier').value = user.subscription_tier || 'free';
            document.getElementById('password-hint').textContent = '(leave blank to keep current)';
            document.getElementById('user-password').required = false;
            document.getElementById('user-modal').classList.add('active');
        }
    } catch (err) {
        console.error('Error loading user:', err);
        alert('Error loading user');
    }
}

async function saveUser(e) {
    e.preventDefault();
    const userId = document.getElementById('user-id').value;
    const formData = {
        username: document.getElementById('user-username').value,
        email: document.getElementById('user-email').value,
        role: document.getElementById('user-role').value,
        subscription_tier: document.getElementById('user-tier').value,
        is_admin: document.getElementById('user-role').value === 'admin'
    };
    const password = document.getElementById('user-password').value;
    if (password) formData.password = password;

    try {
        const url = userId ? '/tools/account-center/api/users/' + userId : '/tools/account-center/api/users';
        const method = userId ? 'PUT' : 'POST';
        const res = await api(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });
        const result = await res.json();
        if (result.success) {
            closeModal();
            loadUsers();
        } else {
            alert(result.error || 'Error saving user');
        }
    } catch (err) {
        console.error('Error saving user:', err);
        alert('Error saving user');
    }
}

async function viewUser(userId) {
    selectedUserId = userId;
    document.getElementById('details-modal').classList.add('active');
    const content = document.getElementById('user-details-content');
    content.textContent = '';
    const loading = document.createElement('div');
    loading.className = 'loading';
    loading.textContent = 'Loading...';
    content.appendChild(loading);

    try {
        // Fetch user data and subscription data in parallel
        const [userRes, subRes] = await Promise.all([
            api('/tools/account-center/api/users/' + userId),
            api('/tools/account-center/api/users/' + userId + '/subscription')
        ]);
        const userData = await userRes.json();
        const subData = await subRes.json();

        if (!userData.success) return;

        const user = userData.user;
        const stats = userData.stats || {};
        const recentActivity = userData.recent_activity || [];
        const failedLogins = userData.failed_logins || [];
        const subscription = subData.success ? subData.subscription : {};
        const usage = subData.success ? subData.usage : {};
        const availableTiers = subData.success ? subData.available_tiers : [];

        content.textContent = '';

        // Profile header
        buildProfileHeader(content, user, subscription);

        // Sub-tab navigation
        const tabs = document.createElement('div');
        tabs.className = 'profile-tabs';
        const tabNames = ['Overview', 'Subscription', 'Security', 'Activity'];
        tabNames.forEach((name, i) => {
            const btn = document.createElement('button');
            btn.className = 'profile-tab-btn' + (i === 0 ? ' active' : '');
            btn.textContent = name;
            btn.dataset.profileTab = name.toLowerCase();
            btn.addEventListener('click', () => {
                tabs.querySelectorAll('.profile-tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                content.querySelectorAll('.profile-tab-pane').forEach(p => p.style.display = 'none');
                const pane = document.getElementById('profile-pane-' + name.toLowerCase());
                if (pane) pane.style.display = 'block';
            });
            tabs.appendChild(btn);
        });
        content.appendChild(tabs);

        // Tab panes
        const overviewPane = document.createElement('div');
        overviewPane.className = 'profile-tab-pane';
        overviewPane.id = 'profile-pane-overview';
        buildOverviewTab(overviewPane, user, stats);
        content.appendChild(overviewPane);

        const subPane = document.createElement('div');
        subPane.className = 'profile-tab-pane';
        subPane.id = 'profile-pane-subscription';
        subPane.style.display = 'none';
        buildSubscriptionTab(subPane, user, subscription, usage, availableTiers);
        content.appendChild(subPane);

        const secPane = document.createElement('div');
        secPane.className = 'profile-tab-pane';
        secPane.id = 'profile-pane-security';
        secPane.style.display = 'none';
        buildSecurityTab(secPane, user, failedLogins);
        content.appendChild(secPane);

        const actPane = document.createElement('div');
        actPane.className = 'profile-tab-pane';
        actPane.id = 'profile-pane-activity';
        actPane.style.display = 'none';
        buildActivityTab(actPane, recentActivity);
        content.appendChild(actPane);

    } catch (err) {
        console.error('Error loading user profile:', err);
        content.textContent = 'Error loading profile.';
    }
}

function buildProfileHeader(container, user, subscription) {
    const header = document.createElement('div');
    header.className = 'profile-header';

    // Avatar with initials
    const avatar = document.createElement('div');
    avatar.className = 'profile-avatar';
    const initials = (user.username || '?').substring(0, 2);
    avatar.textContent = initials;
    if (subscription && subscription.color) {
        avatar.style.background = subscription.color;
    }
    header.appendChild(avatar);

    // Info section
    const info = document.createElement('div');
    info.className = 'profile-header-info';

    const name = document.createElement('div');
    name.className = 'profile-header-name';
    name.textContent = user.username;
    info.appendChild(name);

    // Badges
    const badges = document.createElement('div');
    badges.className = 'profile-header-badges';

    const roleBadge = document.createElement('span');
    roleBadge.className = 'badge';
    const roleColor = ROLE_COLORS[(user.role || 'user').toUpperCase()] || '#6b7280';
    roleBadge.style.cssText = 'border: 1px solid ' + roleColor + '; color: ' + roleColor + ';';
    roleBadge.textContent = (user.role || 'user').toUpperCase();
    badges.appendChild(roleBadge);

    const tierBadge = document.createElement('span');
    tierBadge.className = 'badge';
    const tierColor = (subscription && subscription.color) || '#6b7280';
    tierBadge.style.cssText = 'border: 1px solid ' + tierColor + '; color: ' + tierColor + ';';
    tierBadge.textContent = (subscription && subscription.display_name) || (user.subscription_tier || 'free');
    badges.appendChild(tierBadge);

    const statusBadge = document.createElement('span');
    statusBadge.className = 'badge';
    const isActive = user.is_active !== false;
    statusBadge.style.cssText = 'border: 1px solid ' + (isActive ? '#22c55e' : '#ef4444') + '; color: ' + (isActive ? '#22c55e' : '#ef4444') + ';';
    statusBadge.textContent = isActive ? 'Active' : 'Inactive';
    badges.appendChild(statusBadge);

    info.appendChild(badges);

    // Meta line
    const meta = document.createElement('div');
    meta.className = 'profile-header-meta';
    const created = user.created_at ? ArchieTime.date(user.created_at) : 'Unknown';
    const lastLogin = user.last_login ? ArchieTime.format(user.last_login, 'datetime') : 'Never';
    meta.textContent = 'Joined ' + created + '  \u00b7  Last login ' + lastLogin;
    info.appendChild(meta);

    // Cross-link buttons
    const crosslinks = document.createElement('div');
    crosslinks.style.cssText = 'display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap;';

    const crmLink = document.createElement('a');
    crmLink.href = '/tools/crm/';
    crmLink.className = 'badge';
    crmLink.style.cssText = 'border: 1px solid #ff6b6b; color: #ff6b6b; text-decoration: none; padding: 3px 10px; cursor: pointer; font-size: 0.7rem;';
    crmLink.textContent = 'CRM \u2192';
    crosslinks.appendChild(crmLink);

    const storeLink = document.createElement('a');
    storeLink.href = '/tools/store-builder/';
    storeLink.className = 'badge';
    storeLink.style.cssText = 'border: 1px solid #22c55e; color: #22c55e; text-decoration: none; padding: 3px 10px; cursor: pointer; font-size: 0.7rem;';
    storeLink.textContent = 'Store \u2192';
    crosslinks.appendChild(storeLink);

    const emailLink = document.createElement('a');
    emailLink.href = '/tools/email-manager/';
    emailLink.className = 'badge';
    emailLink.style.cssText = 'border: 1px solid #3b82f6; color: #3b82f6; text-decoration: none; padding: 3px 10px; cursor: pointer; font-size: 0.7rem;';
    emailLink.textContent = 'Email \u2192';
    crosslinks.appendChild(emailLink);

    info.appendChild(crosslinks);

    header.appendChild(info);
    container.appendChild(header);
}

function buildOverviewTab(container, user, stats) {
    const grid = document.createElement('div');
    grid.className = 'profile-two-col';

    // Left: User info fields
    const leftCol = document.createElement('div');
    const leftTitle = document.createElement('div');
    leftTitle.className = 'profile-section-title';
    leftTitle.textContent = 'User Information';
    leftCol.appendChild(leftTitle);

    leftCol.appendChild(createInlineField('Email', user.email || '-', 'email', user.id, 'email'));
    leftCol.appendChild(createInlineField('Role', (user.role || 'user').toUpperCase(), 'role', user.id, 'select', ['user', 'premium', 'admin', 'super_admin']));
    leftCol.appendChild(createInlineField('Tier', user.subscription_tier || 'free', 'subscription_tier', user.id, 'text'));
    leftCol.appendChild(createInlineField('Status', user.is_active !== false ? 'Active' : 'Inactive', null, null, 'readonly'));

    const createdField = document.createElement('div');
    createdField.className = 'inline-field';
    const createdLabel = document.createElement('div');
    createdLabel.className = 'inline-field-label';
    createdLabel.textContent = 'Created';
    const createdVal = document.createElement('div');
    createdVal.className = 'inline-field-value';
    createdVal.textContent = user.created_at ? ArchieTime.date(user.created_at) : '-';
    createdField.appendChild(createdLabel);
    createdField.appendChild(createdVal);
    leftCol.appendChild(createdField);

    const loginField = document.createElement('div');
    loginField.className = 'inline-field';
    const loginLabel = document.createElement('div');
    loginLabel.className = 'inline-field-label';
    loginLabel.textContent = 'Last Login';
    const loginVal = document.createElement('div');
    loginVal.className = 'inline-field-value';
    loginVal.textContent = user.last_login ? ArchieTime.format(user.last_login, 'datetime') : 'Never';
    loginField.appendChild(loginLabel);
    loginField.appendChild(loginVal);
    leftCol.appendChild(loginField);

    grid.appendChild(leftCol);

    // Right: Usage stats
    const rightCol = document.createElement('div');
    const rightTitle = document.createElement('div');
    rightTitle.className = 'profile-section-title';
    rightTitle.textContent = 'Usage Stats';
    rightCol.appendChild(rightTitle);

    const statItems = [
        ['Conversations', stats.conversations || 0],
        ['App Projects', stats.app_projects || 0],
        ['Website Projects', stats.website_projects || 0],
        ['Active Sessions', stats.session_count || 0],
        ['API Keys', stats.api_key_count || 0]
    ];
    statItems.forEach(([label, value]) => {
        const row = document.createElement('div');
        row.className = 'inline-field';
        const lbl = document.createElement('div');
        lbl.className = 'inline-field-label';
        lbl.textContent = label;
        const val = document.createElement('div');
        val.className = 'inline-field-value';
        val.textContent = value;
        row.appendChild(lbl);
        row.appendChild(val);
        rightCol.appendChild(row);
    });

    grid.appendChild(rightCol);
    container.appendChild(grid);
}

function buildSubscriptionTab(container, user, subscription, usage, availableTiers) {
    // Current tier card
    const tierCard = document.createElement('div');
    tierCard.className = 'sub-tier-card';
    tierCard.style.borderColor = subscription.color || '#6b7280';

    const cardHeader = document.createElement('div');
    cardHeader.className = 'sub-tier-card-header';
    const tierName = document.createElement('div');
    tierName.className = 'sub-tier-name';
    tierName.style.color = subscription.color || '#6b7280';
    tierName.textContent = subscription.display_name || 'Free';
    const tierPrice = document.createElement('div');
    tierPrice.className = 'sub-tier-price';
    tierPrice.textContent = subscription.price > 0 ? '$' + subscription.price + '/mo' : 'Free';
    cardHeader.appendChild(tierName);
    cardHeader.appendChild(tierPrice);
    tierCard.appendChild(cardHeader);

    // Status + dates row
    const detailsDiv = document.createElement('div');
    detailsDiv.style.cssText = 'display: flex; gap: var(--archie-space-4); flex-wrap: wrap; font-size: var(--archie-text-sm); color: var(--archie-text-secondary); margin-bottom: var(--archie-space-3);';

    const statusSpan = document.createElement('span');
    const subStatus = subscription.status || 'active';
    const statusColor = subStatus === 'active' ? '#22c55e' : subStatus === 'cancelled' ? '#ef4444' : '#f59e0b';
    statusSpan.style.color = statusColor;
    statusSpan.textContent = 'Status: ' + subStatus.charAt(0).toUpperCase() + subStatus.slice(1);
    detailsDiv.appendChild(statusSpan);

    if (subscription.started_at) {
        const startSpan = document.createElement('span');
        startSpan.textContent = 'Started: ' + ArchieTime.date(subscription.started_at);
        detailsDiv.appendChild(startSpan);
    }
    if (subscription.expires_at) {
        const expSpan = document.createElement('span');
        expSpan.textContent = 'Expires: ' + ArchieTime.date(subscription.expires_at);
        detailsDiv.appendChild(expSpan);
    }

    tierCard.appendChild(detailsDiv);

    // Role mapping
    if (subscription.mapped_role) {
        const roleDiv = document.createElement('div');
        roleDiv.style.cssText = 'font-size: var(--archie-text-xs); color: var(--archie-text-tertiary);';
        roleDiv.textContent = 'Maps to role: ' + subscription.mapped_role;
        tierCard.appendChild(roleDiv);
    }

    container.appendChild(tierCard);

    // Usage vs limits progress bars
    const limits = subscription.limits || {};
    const LIMIT_LABELS = {
        'storage_mb': 'Storage (MB)', 'app_projects': 'App Projects',
        'api_calls_daily': 'API Calls/Day', 'website_projects': 'Website Projects'
    };

    if (Object.keys(limits).length > 0) {
        const usageTitle = document.createElement('div');
        usageTitle.className = 'profile-section-title';
        usageTitle.textContent = 'Usage vs Limits';
        usageTitle.style.marginTop = 'var(--archie-space-4)';
        container.appendChild(usageTitle);

        Object.entries(limits).forEach(([key, max]) => {
            const current = usage[key] || 0;
            const wrap = document.createElement('div');
            wrap.className = 'usage-bar-wrap';

            const label = document.createElement('div');
            label.className = 'usage-bar-label';
            const labelName = document.createElement('span');
            labelName.textContent = LIMIT_LABELS[key] || key;
            const labelVal = document.createElement('span');
            labelVal.textContent = max === -1 ? current + ' / Unlimited' : current + ' / ' + max;
            label.appendChild(labelName);
            label.appendChild(labelVal);
            wrap.appendChild(label);

            const bar = document.createElement('div');
            bar.className = 'usage-bar';
            const fill = document.createElement('div');
            fill.className = 'usage-bar-fill';
            if (max === -1) {
                fill.style.width = '5%';
            } else {
                const pct = max > 0 ? Math.min(100, (current / max) * 100) : 0;
                fill.style.width = pct + '%';
                if (pct > 85) fill.classList.add('danger');
                else if (pct > 60) fill.classList.add('warning');
            }
            bar.appendChild(fill);
            wrap.appendChild(bar);
            container.appendChild(wrap);
        });
    }

    // "Full Management View" button
    const fullMgmtBtn = document.createElement('button');
    fullMgmtBtn.className = 'btn btn-primary';
    fullMgmtBtn.style.marginTop = 'var(--archie-space-4)';
    fullMgmtBtn.textContent = 'Full Management View';
    fullMgmtBtn.addEventListener('click', () => {
        closeDetailsModal();
        subMgmtSelectedUserId = user.id;
        openSubMgmtModal(user.id, user.username);
    });
    container.appendChild(fullMgmtBtn);

    // ── Admin Entitlements + Trial Management ──
    const adminSection = document.createElement('div');
    adminSection.className = 'sub-mgmt-section';
    adminSection.style.marginTop = 'var(--archie-space-5)';
    adminSection.id = 'admin-entitlements-section-' + user.id;

    const adminTitle = document.createElement('div');
    adminTitle.className = 'profile-section-title';
    adminTitle.style.cssText = 'color: #f59e0b; border-bottom: 1px solid rgba(245,158,11,0.3); padding-bottom: var(--archie-space-2); margin-bottom: var(--archie-space-3);';
    adminTitle.textContent = 'Admin: Entitlements & Trials';
    adminSection.appendChild(adminTitle);

    const entLoadingDiv = document.createElement('div');
    entLoadingDiv.className = 'loading';
    entLoadingDiv.textContent = 'Loading entitlements...';
    entLoadingDiv.id = 'ent-loading-' + user.id;
    adminSection.appendChild(entLoadingDiv);

    const entContentDiv = document.createElement('div');
    entContentDiv.id = 'ent-content-' + user.id;
    entContentDiv.style.display = 'none';
    adminSection.appendChild(entContentDiv);

    container.appendChild(adminSection);

    // Fetch entitlements asynchronously
    loadUserEntitlements(user.id);
}

const TRIAL_PRODUCTS = [
    {id: 'crm', name: 'CRM'},
    {id: 'invoicing', name: 'Invoicing'},
    {id: 'store_builder', name: 'Store Builder'},
    {id: 'content_studio', name: 'Content Studio'},
    {id: 'website_studio', name: 'Website Designer'},
    {id: 'social_media', name: 'Social Media'},
    {id: 'call_center', name: 'Call Center'},
    {id: 'google_work_suite', name: 'Google Work Suite'},
    {id: 'stockbot', name: 'StockBot'},
    {id: 'media_studio', name: 'Media Studio'},
    {id: 'game_studio', name: 'Game Studio'},
    {id: 'family_tree', name: 'Family Tree'},
    {id: 'legal-watch', name: 'Legal Watch'},
    {id: 'civic-watch', name: 'Civic Watch'},
    {id: 'market-watch-viewer', name: 'Market Watch'},
    {id: 'gov-watch', name: 'Gov Watch'},
    {id: 'membership_starter', name: 'Membership: Starter'},
    {id: 'membership_pro', name: 'Membership: Professional'},
    {id: 'membership_enterprise', name: 'Membership: Enterprise'},
];

function _createHeaderCell(text) {
    const th = document.createElement('th');
    th.style.cssText = 'text-align:left;padding:6px 8px;color:var(--archie-text-tertiary);';
    th.textContent = text;
    return th;
}

async function loadUserEntitlements(userId) {
    const loadingEl = document.getElementById('ent-loading-' + userId);
    const contentEl = document.getElementById('ent-content-' + userId);
    if (!contentEl) return;

    try {
        const res = await api('/tools/account-center/api/users/' + userId + '/entitlements');
        const data = await res.json();
        if (loadingEl) loadingEl.style.display = 'none';
        contentEl.style.display = 'block';
        contentEl.textContent = '';

        if (!data.success) {
            contentEl.textContent = 'Error: ' + (data.error || 'Unknown');
            return;
        }

        // Membership tier badge
        const tierRow = document.createElement('div');
        tierRow.style.cssText = 'display: flex; align-items: center; gap: var(--archie-space-3); margin-bottom: var(--archie-space-3);';
        const tierLabel = document.createElement('span');
        tierLabel.style.cssText = 'color: var(--archie-text-secondary); font-size: var(--archie-text-sm);';
        tierLabel.textContent = 'Membership Tier:';
        const tierBadge = document.createElement('span');
        tierBadge.className = 'badge';
        const tierColors = {staff:'#f59e0b', vip:'#a855f7', enterprise:'#3b82f6', professional:'#22c55e', starter:'#06b6d4', explorer:'#6b7280'};
        const tc = tierColors[data.membership_tier] || '#6b7280';
        tierBadge.style.cssText = 'border: 1px solid ' + tc + '; color: ' + tc + '; font-weight: 600;';
        tierBadge.textContent = getTierDisplayName(data.membership_tier || 'free');
        tierRow.appendChild(tierLabel);
        tierRow.appendChild(tierBadge);
        contentEl.appendChild(tierRow);

        // Admin bypass note
        if (data.entitlements && data.entitlements._admin) {
            const adminNote = document.createElement('div');
            adminNote.style.cssText = 'background: rgba(245,158,11,0.1); border: 1px solid rgba(245,158,11,0.3); border-radius: 6px; padding: var(--archie-space-3); margin-bottom: var(--archie-space-3); font-size: var(--archie-text-sm); color: #f59e0b;';
            adminNote.textContent = 'Admin/Staff bypass — full access to all modules.';
            contentEl.appendChild(adminNote);
        }

        // Active subscriptions table
        const subs = data.subscriptions || [];
        if (subs.length > 0) {
            const subsTitle = document.createElement('div');
            subsTitle.style.cssText = 'font-size: var(--archie-text-sm); color: var(--archie-text-secondary); margin-bottom: var(--archie-space-2); font-weight: 600;';
            subsTitle.textContent = 'Active Subscriptions (' + subs.length + ')';
            contentEl.appendChild(subsTitle);

            const table = document.createElement('table');
            table.style.cssText = 'width: 100%; border-collapse: collapse; font-size: var(--archie-text-xs); margin-bottom: var(--archie-space-4);';
            const thead = document.createElement('thead');
            const headerRow = document.createElement('tr');
            headerRow.style.borderBottom = '1px solid rgba(255,255,255,0.1)';
            ['Module', 'Status', 'Source', 'Expires'].forEach(text => headerRow.appendChild(_createHeaderCell(text)));
            const actionsHeader = _createHeaderCell('Actions');
            actionsHeader.style.textAlign = 'right';
            headerRow.appendChild(actionsHeader);
            thead.appendChild(headerRow);
            table.appendChild(thead);

            const tbody = document.createElement('tbody');
            subs.forEach(sub => {
                const tr = document.createElement('tr');
                tr.style.borderBottom = '1px solid rgba(255,255,255,0.05)';

                const tdModule = document.createElement('td');
                tdModule.style.cssText = 'padding: 6px 8px; color: var(--archie-text-primary);';
                const product = TRIAL_PRODUCTS.find(p => p.id === sub.module);
                tdModule.textContent = product ? product.name : sub.module;
                tr.appendChild(tdModule);

                const tdStatus = document.createElement('td');
                tdStatus.style.cssText = 'padding: 6px 8px;';
                const statusSpan = document.createElement('span');
                const sColor = sub.status === 'active' ? '#22c55e' : sub.status === 'trialing' ? '#f59e0b' : '#ef4444';
                statusSpan.style.cssText = 'color: ' + sColor + '; font-weight: 500;';
                statusSpan.textContent = sub.status;
                tdStatus.appendChild(statusSpan);
                tr.appendChild(tdStatus);

                const tdSource = document.createElement('td');
                tdSource.style.cssText = 'padding: 6px 8px; color: var(--archie-text-secondary);';
                tdSource.textContent = sub.source || 'stripe';
                tr.appendChild(tdSource);

                const tdExpires = document.createElement('td');
                tdExpires.style.cssText = 'padding: 6px 8px; color: var(--archie-text-secondary);';
                tdExpires.textContent = sub.expires_at ? ArchieTime.date(sub.expires_at) : 'Never';
                tr.appendChild(tdExpires);

                const tdActions = document.createElement('td');
                tdActions.style.cssText = 'padding: 6px 8px; text-align: right;';
                if (sub.source === 'trial' || sub.source === 'admin_override') {
                    const revokeBtn = document.createElement('button');
                    revokeBtn.className = 'btn';
                    revokeBtn.style.cssText = 'font-size: 0.65rem; padding: 2px 8px; border: 1px solid #ef4444; color: #ef4444; background: transparent; cursor: pointer; border-radius: 4px;';
                    revokeBtn.textContent = 'Revoke';
                    revokeBtn.addEventListener('click', () => revokeUserSubscription(userId, sub.id));
                    tdActions.appendChild(revokeBtn);
                }
                tr.appendChild(tdActions);

                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            contentEl.appendChild(table);
        } else if (!data.entitlements || !data.entitlements._admin) {
            const noSubs = document.createElement('div');
            noSubs.style.cssText = 'color: var(--archie-text-tertiary); font-size: var(--archie-text-sm); margin-bottom: var(--archie-space-3);';
            noSubs.textContent = 'No active subscriptions.';
            contentEl.appendChild(noSubs);
        }

        // Grant Trial form
        const formTitle = document.createElement('div');
        formTitle.style.cssText = 'font-size: var(--archie-text-sm); color: #f59e0b; margin-bottom: var(--archie-space-2); font-weight: 600; margin-top: var(--archie-space-3);';
        formTitle.textContent = 'Grant Trial';
        contentEl.appendChild(formTitle);

        const formRow = document.createElement('div');
        formRow.style.cssText = 'display: flex; gap: var(--archie-space-2); flex-wrap: wrap; align-items: flex-end;';

        // Module dropdown
        const moduleWrap = document.createElement('div');
        moduleWrap.style.cssText = 'flex: 1; min-width: 140px;';
        const moduleLabel = document.createElement('label');
        moduleLabel.style.cssText = 'display: block; font-size: var(--archie-text-xs); color: var(--archie-text-tertiary); margin-bottom: 2px;';
        moduleLabel.textContent = 'Product';
        const moduleSelect = document.createElement('select');
        moduleSelect.id = 'trial-module-' + userId;
        moduleSelect.style.cssText = 'width: 100%; padding: 6px 8px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.15); border-radius: 4px; color: var(--archie-text-primary); font-size: var(--archie-text-xs);';
        TRIAL_PRODUCTS.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.name;
            moduleSelect.appendChild(opt);
        });
        moduleWrap.appendChild(moduleLabel);
        moduleWrap.appendChild(moduleSelect);
        formRow.appendChild(moduleWrap);

        // Tier dropdown
        const tierWrap = document.createElement('div');
        tierWrap.style.cssText = 'min-width: 110px;';
        const tierLabelEl = document.createElement('label');
        tierLabelEl.style.cssText = 'display: block; font-size: var(--archie-text-xs); color: var(--archie-text-tertiary); margin-bottom: 2px;';
        tierLabelEl.textContent = 'Tier';
        const tierSelect = document.createElement('select');
        tierSelect.id = 'trial-tier-' + userId;
        tierSelect.style.cssText = 'width: 100%; padding: 6px 8px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.15); border-radius: 4px; color: var(--archie-text-primary); font-size: var(--archie-text-xs);';
        [{v: 'viewer', n: 'Viewer'}, {v: 'starter', n: 'Starter'}, {v: 'pro', n: 'Professional'}, {v: 'enterprise', n: 'Enterprise'}].forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.v;
            opt.textContent = t.n;
            tierSelect.appendChild(opt);
        });
        tierWrap.appendChild(tierLabelEl);
        tierWrap.appendChild(tierSelect);
        formRow.appendChild(tierWrap);

        // Duration dropdown
        const durWrap = document.createElement('div');
        durWrap.style.cssText = 'min-width: 90px;';
        const durLabel = document.createElement('label');
        durLabel.style.cssText = 'display: block; font-size: var(--archie-text-xs); color: var(--archie-text-tertiary); margin-bottom: 2px;';
        durLabel.textContent = 'Duration';
        const durSelect = document.createElement('select');
        durSelect.id = 'trial-duration-' + userId;
        durSelect.style.cssText = 'width: 100%; padding: 6px 8px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.15); border-radius: 4px; color: var(--archie-text-primary); font-size: var(--archie-text-xs);';
        [{v: 7, n: '7 days'}, {v: 14, n: '14 days'}, {v: 30, n: '30 days'}, {v: 60, n: '60 days'}, {v: 90, n: '90 days'}].forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.v;
            opt.textContent = d.n;
            durSelect.appendChild(opt);
        });
        durWrap.appendChild(durLabel);
        durWrap.appendChild(durSelect);
        formRow.appendChild(durWrap);

        // Grant button
        const grantBtn = document.createElement('button');
        grantBtn.className = 'btn';
        grantBtn.style.cssText = 'padding: 6px 14px; border: 1px solid #f59e0b; color: #f59e0b; background: rgba(245,158,11,0.1); cursor: pointer; border-radius: 4px; font-size: var(--archie-text-xs); font-weight: 600; white-space: nowrap;';
        grantBtn.textContent = 'Grant Trial';
        grantBtn.addEventListener('click', () => grantUserTrial(userId));
        formRow.appendChild(grantBtn);

        contentEl.appendChild(formRow);

    } catch (err) {
        if (loadingEl) loadingEl.style.display = 'none';
        if (contentEl) {
            contentEl.style.display = 'block';
            contentEl.textContent = 'Error loading entitlements.';
        }
        console.error('Error loading entitlements:', err);
    }
}

async function grantUserTrial(userId) {
    const module = document.getElementById('trial-module-' + userId);
    const tier = document.getElementById('trial-tier-' + userId);
    const duration = document.getElementById('trial-duration-' + userId);
    if (!module || !tier || !duration) return;

    if (!confirm('Grant ' + duration.value + '-day trial of ' + module.options[module.selectedIndex].text + ' to this user?')) return;

    try {
        const res = await api('/tools/account-center/api/users/' + userId + '/trial', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                module: module.value,
                tier_price_id: tier.value,
                duration_days: parseInt(duration.value)
            })
        });
        const data = await res.json();
        if (data.success) {
            alert('Trial granted successfully. Expires: ' + (data.trial.expires_at || 'N/A'));
            loadUserEntitlements(userId);
        } else {
            alert('Error: ' + (data.error || 'Unknown error'));
        }
    } catch (err) {
        console.error('Error granting trial:', err);
        alert('Error granting trial');
    }
}

async function revokeUserSubscription(userId, subscriptionId) {
    if (!confirm('Revoke this subscription? This cannot be undone.')) return;

    try {
        const res = await api('/tools/account-center/api/users/' + userId + '/revoke-subscription', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({subscription_id: subscriptionId})
        });
        const data = await res.json();
        if (data.success) {
            alert('Subscription revoked.');
            loadUserEntitlements(userId);
        } else {
            alert('Error: ' + (data.error || 'Unknown error'));
        }
    } catch (err) {
        console.error('Error revoking subscription:', err);
        alert('Error revoking subscription');
    }
}

function buildSecurityTab(container, user, failedLogins) {
    // 2FA Status
    const sec2fa = document.createElement('div');
    sec2fa.className = 'sub-mgmt-section';
    const sec2faTitle = document.createElement('div');
    sec2faTitle.className = 'profile-section-title';
    sec2faTitle.textContent = 'Two-Factor Authentication';
    sec2fa.appendChild(sec2faTitle);

    const statusRow = document.createElement('div');
    statusRow.style.cssText = 'display: flex; align-items: center; gap: var(--archie-space-3); margin-bottom: var(--archie-space-3);';
    const statusIndicator = document.createElement('span');
    statusIndicator.className = 'badge';
    statusIndicator.style.cssText = 'border: 1px solid ' + (user.totp_enabled ? '#22c55e' : '#ef4444') + '; color: ' + (user.totp_enabled ? '#22c55e' : '#ef4444') + ';';
    statusIndicator.textContent = user.totp_enabled ? 'Enabled' : 'Disabled';
    statusRow.appendChild(statusIndicator);

    if (user.totp_verified_at) {
        const verifiedAt = document.createElement('span');
        verifiedAt.style.cssText = 'font-size: var(--archie-text-xs); color: var(--archie-text-tertiary);';
        verifiedAt.textContent = 'Verified: ' + ArchieTime.format(user.totp_verified_at, 'datetime');
        statusRow.appendChild(verifiedAt);
    }
    sec2fa.appendChild(statusRow);

    const btnRow2fa = document.createElement('div');
    btnRow2fa.style.cssText = 'display: flex; gap: var(--archie-space-2);';

    if (user.totp_enabled) {
        const disableBtn = document.createElement('button');
        disableBtn.className = 'btn btn-ghost';
        disableBtn.textContent = 'Disable 2FA';
        disableBtn.addEventListener('click', () => toggle2FA(user.id, false));
        btnRow2fa.appendChild(disableBtn);

        const resetBtn = document.createElement('button');
        resetBtn.className = 'btn btn-ghost';
        resetBtn.textContent = 'Reset 2FA';
        resetBtn.addEventListener('click', () => toggle2FA(user.id, 'reset'));
        btnRow2fa.appendChild(resetBtn);
    } else {
        const enableBtn = document.createElement('button');
        enableBtn.className = 'btn btn-primary';
        enableBtn.textContent = 'Enable 2FA';
        enableBtn.addEventListener('click', () => toggle2FA(user.id, true));
        btnRow2fa.appendChild(enableBtn);
    }
    sec2fa.appendChild(btnRow2fa);
    container.appendChild(sec2fa);

    // Password Reset
    const secPw = document.createElement('div');
    secPw.className = 'sub-mgmt-section';
    const secPwTitle = document.createElement('div');
    secPwTitle.className = 'profile-section-title';
    secPwTitle.textContent = 'Password';
    secPw.appendChild(secPwTitle);

    const pwRow = document.createElement('div');
    pwRow.style.cssText = 'display: flex; gap: var(--archie-space-2); align-items: center;';
    const pwInput = document.createElement('input');
    pwInput.type = 'password';
    pwInput.placeholder = 'New password (min 8 chars)';
    pwInput.style.cssText = 'flex: 1; padding: var(--archie-space-2); background: var(--archie-bg-input); border: 1px solid var(--archie-border-default); border-radius: var(--archie-radius-sm); color: var(--archie-text-primary);';
    const pwBtn = document.createElement('button');
    pwBtn.className = 'btn btn-primary';
    pwBtn.textContent = 'Reset Password';
    pwBtn.addEventListener('click', async () => {
        const pw = pwInput.value;
        if (!pw || pw.length < 8) { alert('Password must be at least 8 characters'); return; }
        try {
            const res = await api('/tools/account-center/api/users/' + user.id + '/password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password: pw })
            });
            const data = await res.json();
            if (data.success) {
                alert('Password reset successfully');
                pwInput.value = '';
            } else {
                alert(data.error || 'Error resetting password');
            }
        } catch (err) {
            alert('Error resetting password');
        }
    });
    pwRow.appendChild(pwInput);
    pwRow.appendChild(pwBtn);
    secPw.appendChild(pwRow);
    container.appendChild(secPw);

    // Account Lock Status
    const secLock = document.createElement('div');
    secLock.className = 'sub-mgmt-section';
    const secLockTitle = document.createElement('div');
    secLockTitle.className = 'profile-section-title';
    secLockTitle.textContent = 'Account Lock Status';
    secLock.appendChild(secLockTitle);

    const isLocked = user.locked_until && new Date(user.locked_until) > new Date();
    const lockInfo = document.createElement('div');
    lockInfo.style.cssText = 'display: flex; align-items: center; gap: var(--archie-space-3); margin-bottom: var(--archie-space-2);';

    const lockBadge = document.createElement('span');
    lockBadge.className = 'badge';
    lockBadge.style.cssText = 'border: 1px solid ' + (isLocked ? '#ef4444' : '#22c55e') + '; color: ' + (isLocked ? '#ef4444' : '#22c55e') + ';';
    lockBadge.textContent = isLocked ? 'LOCKED' : 'Unlocked';
    lockInfo.appendChild(lockBadge);

    const failCount = document.createElement('span');
    failCount.style.cssText = 'font-size: var(--archie-text-sm); color: var(--archie-text-secondary);';
    failCount.textContent = 'Failed since last login: ' + (user.failed_login_count || 0);
    lockInfo.appendChild(failCount);

    secLock.appendChild(lockInfo);

    if (isLocked) {
        const unlockBtn = document.createElement('button');
        unlockBtn.className = 'btn btn-primary';
        unlockBtn.textContent = 'Unlock Account';
        unlockBtn.addEventListener('click', () => {
            unlockUser(user.id);
            // Refresh profile after unlock
            setTimeout(() => viewUser(user.id), 500);
        });
        secLock.appendChild(unlockBtn);
    }

    container.appendChild(secLock);

    // Failed Login History
    const secFailed = document.createElement('div');
    secFailed.className = 'sub-mgmt-section';
    const secFailedTitle = document.createElement('div');
    secFailedTitle.className = 'profile-section-title';
    secFailedTitle.textContent = 'Recent Failed Login Attempts';
    secFailed.appendChild(secFailedTitle);

    if (!failedLogins || failedLogins.length === 0) {
        const noFails = document.createElement('div');
        noFails.style.cssText = 'font-size: var(--archie-text-sm); color: var(--archie-text-tertiary); padding: var(--archie-space-2) 0;';
        noFails.textContent = 'No failed login attempts recorded';
        secFailed.appendChild(noFails);
    } else {
        const table = document.createElement('table');
        table.style.cssText = 'width: 100%; border-collapse: collapse; font-size: var(--archie-text-sm);';
        const thead = document.createElement('thead');
        const headRow = document.createElement('tr');
        ['IP Address', 'Reason', 'Time'].forEach(h => {
            const th = document.createElement('th');
            th.style.cssText = 'text-align: left; padding: var(--archie-space-2); border-bottom: 1px solid var(--archie-border-default); color: var(--archie-text-secondary); font-weight: 500;';
            th.textContent = h;
            headRow.appendChild(th);
        });
        thead.appendChild(headRow);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        failedLogins.forEach(f => {
            const tr = document.createElement('tr');

            const tdIp = document.createElement('td');
            tdIp.style.cssText = 'padding: var(--archie-space-2); border-bottom: 1px solid var(--archie-border-default); font-family: monospace; color: var(--archie-text-primary);';
            tdIp.textContent = f.ip_address || '-';

            const tdReason = document.createElement('td');
            tdReason.style.cssText = 'padding: var(--archie-space-2); border-bottom: 1px solid var(--archie-border-default); color: var(--archie-text-secondary);';
            tdReason.textContent = (f.reason || 'unknown').replace(/_/g, ' ');

            const tdTime = document.createElement('td');
            tdTime.style.cssText = 'padding: var(--archie-space-2); border-bottom: 1px solid var(--archie-border-default); color: var(--archie-text-tertiary);';
            tdTime.textContent = f.attempted_at ? ArchieTime.format(f.attempted_at, 'short') : '-';

            tr.appendChild(tdIp);
            tr.appendChild(tdReason);
            tr.appendChild(tdTime);
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        secFailed.appendChild(table);
    }

    container.appendChild(secFailed);
}

function buildActivityTab(container, recentActivity) {
    if (!recentActivity || recentActivity.length === 0) {
        const empty = document.createElement('div');
        empty.style.cssText = 'text-align: center; padding: var(--archie-space-8); color: var(--archie-text-tertiary);';
        empty.textContent = 'No recent activity';
        container.appendChild(empty);
    } else {
        recentActivity.forEach(a => {
            const item = document.createElement('div');
            item.className = 'activity-list-item';

            const dot = document.createElement('div');
            dot.className = 'activity-dot';
            item.appendChild(dot);

            const action = document.createElement('span');
            action.className = 'activity-list-action';
            action.textContent = (a.action || '').replace(/_/g, ' ');
            item.appendChild(action);

            if (a.module) {
                const mod = document.createElement('span');
                mod.className = 'activity-list-module';
                mod.textContent = a.module;
                item.appendChild(mod);
            }

            const time = document.createElement('span');
            time.className = 'activity-list-time';
            time.textContent = a.created_at ? ArchieTime.format(a.created_at, 'short') : '';
            item.appendChild(time);

            container.appendChild(item);
        });
    }

    // "View Full Activity" button
    const viewFullBtn = document.createElement('button');
    viewFullBtn.className = 'btn btn-ghost';
    viewFullBtn.style.marginTop = 'var(--archie-space-4)';
    viewFullBtn.textContent = 'View Full Activity';
    viewFullBtn.addEventListener('click', () => {
        closeDetailsModal();
        document.querySelector('[data-tab="activity"]').click();
    });
    container.appendChild(viewFullBtn);
}

function createInlineField(label, value, fieldName, userId, type, options) {
    const row = document.createElement('div');
    row.className = 'inline-field';

    const lbl = document.createElement('div');
    lbl.className = 'inline-field-label';
    lbl.textContent = label;
    row.appendChild(lbl);

    const val = document.createElement('div');
    val.className = 'inline-field-value';
    val.textContent = value;
    row.appendChild(val);

    if (type === 'readonly' || !fieldName) return row;

    // Edit controls
    const editDiv = document.createElement('div');
    editDiv.className = 'inline-field-edit';

    let input;
    if (type === 'select' && options) {
        input = document.createElement('select');
        options.forEach(opt => {
            const o = document.createElement('option');
            o.value = opt;
            o.textContent = opt.toUpperCase();
            if (opt === (value || '').toLowerCase()) o.selected = true;
            input.appendChild(o);
        });
    } else {
        input = document.createElement('input');
        input.type = type || 'text';
        input.value = value === '-' ? '' : value;
    }
    editDiv.appendChild(input);
    row.appendChild(editDiv);

    // Action buttons
    const actions = document.createElement('div');
    actions.className = 'inline-field-actions';

    const editBtn = document.createElement('button');
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', () => {
        row.classList.add('editing');
        input.focus();
    });
    actions.appendChild(editBtn);

    const saveBtn = document.createElement('button');
    saveBtn.className = 'save-btn';
    saveBtn.textContent = 'Save';
    saveBtn.style.display = 'none';
    saveBtn.addEventListener('click', () => saveProfileField(userId, fieldName, input.value, row, val, saveBtn, cancelBtn));
    actions.appendChild(saveBtn);

    const cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.style.display = 'none';
    cancelBtn.addEventListener('click', () => {
        row.classList.remove('editing');
        editBtn.style.display = '';
        saveBtn.style.display = 'none';
        cancelBtn.style.display = 'none';
    });
    actions.appendChild(cancelBtn);

    // Toggle visibility on edit
    editBtn.addEventListener('click', () => {
        editBtn.style.display = 'none';
        saveBtn.style.display = '';
        cancelBtn.style.display = '';
    });

    row.appendChild(actions);
    return row;
}

async function saveProfileField(userId, fieldName, value, row, valEl, saveBtn, cancelBtn) {
    try {
        const body = {};
        body[fieldName] = value;
        const res = await api('/tools/account-center/api/users/' + userId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (data.success) {
            valEl.textContent = value || '-';
            row.classList.remove('editing');
            row.querySelector('.inline-field-actions button:first-child').style.display = '';
            saveBtn.style.display = 'none';
            cancelBtn.style.display = 'none';
            loadUsers(); // Refresh the user list
        } else {
            alert(data.error || 'Error saving');
        }
    } catch (err) {
        alert('Error saving field');
    }
}

async function deleteUser(userId) {
    if (!confirm('Are you sure you want to deactivate this user?')) return;
    try {
        const res = await api('/tools/account-center/api/users/' + userId, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            loadUsers();
        } else {
            alert(data.error || 'Error deleting user');
        }
    } catch (err) {
        console.error('Error deleting user:', err);
        alert('Error deleting user');
    }
}

function closeModal() {
    document.getElementById('user-modal').classList.remove('active');
}

function closeDetailsModal() {
    document.getElementById('details-modal').classList.remove('active');
}

let permissionsData = null;
let permFilterMode = 'all';
let selectedRole = null;

async function loadPermissions() {
    try {
        // Load roles and permissions in parallel
        const [rolesRes, permsRes] = await Promise.all([
            api('/tools/account-center/api/roles'),
            api('/tools/account-center/api/permissions')
        ]);
        const rolesData = await rolesRes.json();
        const permsData = await permsRes.json();

        if (rolesData.success) renderRoleCards(rolesData.roles);
        if (permsData.success) {
            permissionsData = permsData;
            renderPermissionMatrix(permsData);
        }
    } catch (err) {
        console.error('Error loading permissions:', err);
    }
}

function renderRoleCards(roles) {
    const container = document.getElementById('roles-overview');
    container.textContent = '';

    roles.forEach(role => {
        const card = document.createElement('div');
        card.className = 'role-overview-card';
        card.style.setProperty('--role-color', role.color);
        card.onclick = () => toggleRoleHighlight(role.name, card);

        const icon = document.createElement('div');
        icon.className = 'role-icon';
        const iconEl = document.createElement('i');
        // Sanitize icon name - only allow alphanumeric and hyphens
        const safeIcon = (role.icon || 'user').replace(/[^a-zA-Z0-9-]/g, '');
        iconEl.setAttribute('data-lucide', safeIcon);
        icon.appendChild(iconEl);

        const name = document.createElement('div');
        name.className = 'role-card-name';
        name.textContent = role.name.replace('_', ' ');

        const level = document.createElement('div');
        level.className = 'role-card-level';
        level.textContent = 'Level ' + role.level;

        const desc = document.createElement('div');
        desc.className = 'role-card-desc';
        desc.textContent = role.description;

        const count = document.createElement('div');
        count.className = 'role-perm-count';
        count.textContent = role.permission_count;

        const label = document.createElement('div');
        label.className = 'role-perm-label';
        label.textContent = 'Permissions';

        card.appendChild(icon);
        card.appendChild(name);
        card.appendChild(level);
        card.appendChild(desc);
        card.appendChild(count);
        card.appendChild(label);

        // Show which subscription tiers map to this role
        if (role.subscription_tiers && role.subscription_tiers.length > 0) {
            const tierLine = document.createElement('div');
            tierLine.style.cssText = 'font-size: 10px; color: var(--archie-text-tertiary); margin-top: var(--archie-space-2); text-transform: uppercase; letter-spacing: 0.05em;';
            tierLine.textContent = role.subscription_tiers.join(' \u00B7 ');
            card.appendChild(tierLine);
        }

        container.appendChild(card);
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function toggleRoleHighlight(roleName, cardEl) {
    const cards = document.querySelectorAll('.role-overview-card');
    if (selectedRole === roleName) {
        selectedRole = null;
        cards.forEach(c => c.classList.remove('active'));
        // Remove column highlight
        document.querySelectorAll('.perm-matrix-table th, .perm-matrix-table td').forEach(el => {
            el.style.removeProperty('background');
        });
    } else {
        selectedRole = roleName;
        cards.forEach(c => c.classList.remove('active'));
        cardEl.classList.add('active');
        highlightRoleColumn(roleName);
    }
}

function highlightRoleColumn(roleName) {
    if (!permissionsData) return;
    const roleIdx = permissionsData.roles.indexOf(roleName);
    if (roleIdx === -1) return;
    const colIdx = roleIdx + 1; // +1 for the permission name column

    // Reset all columns
    document.querySelectorAll('.perm-matrix-table th, .perm-matrix-table td').forEach(el => {
        el.style.removeProperty('background');
    });

    // Highlight the selected column
    document.querySelectorAll('.perm-matrix-table tr').forEach(tr => {
        const cells = tr.querySelectorAll('th, td');
        if (cells[colIdx]) {
            cells[colIdx].style.background = 'var(--archie-accent-alpha-10)';
        }
    });
}

function renderPermissionMatrix(data) {
    const head = document.getElementById('perm-matrix-head');
    const body = document.getElementById('perm-matrix-body');
    head.textContent = '';
    body.textContent = '';

    const roleColors = {
        'PUBLIC': '#6b7280', 'USER': '#06b6d4', 'PREMIUM': '#f97316',
        'ADMIN': '#ef4444', 'SUPER_ADMIN': '#a855f7'
    };

    // Build header
    const headerRow = document.createElement('tr');
    const permTh = document.createElement('th');
    permTh.textContent = 'Permission';
    headerRow.appendChild(permTh);

    data.roles.forEach(role => {
        const th = document.createElement('th');
        const nameSpan = document.createElement('span');
        nameSpan.className = 'th-role-name';
        nameSpan.textContent = role.replace('_', ' ');
        const dot = document.createElement('span');
        dot.className = 'th-role-dot';
        dot.style.background = roleColors[role] || '#6b7280';
        th.appendChild(nameSpan);
        th.appendChild(dot);
        headerRow.appendChild(th);
    });
    head.appendChild(headerRow);

    // Build rows grouped by category
    let totalPerms = 0;
    data.groups.forEach(group => {
        // Category header row
        const catRow = document.createElement('tr');
        catRow.className = 'category-row expanded';
        catRow.dataset.category = group.category;
        const catTd = document.createElement('td');
        catTd.colSpan = data.roles.length + 1;
        catTd.textContent = group.category + ' (' + group.permissions.length + ')';
        catRow.appendChild(catTd);
        catRow.onclick = () => toggleCategory(group.category, catRow);
        body.appendChild(catRow);

        // Permission rows
        group.permissions.forEach(perm => {
            const row = document.createElement('tr');
            row.className = 'perm-row';
            row.dataset.category = group.category;
            row.dataset.label = perm.label.toLowerCase();
            row.dataset.code = perm.value.toLowerCase();

            // Check if all roles have same value (for "differences" filter)
            const values = data.roles.map(r => perm.roles[r]);
            const allSame = values.every(v => v === values[0]);
            row.dataset.allSame = allSame ? '1' : '0';

            // Permission name cell
            const nameTd = document.createElement('td');
            const labelSpan = document.createElement('span');
            labelSpan.textContent = perm.label;
            const codeSpan = document.createElement('span');
            codeSpan.className = 'perm-code';
            codeSpan.textContent = perm.value;
            nameTd.appendChild(labelSpan);
            nameTd.appendChild(codeSpan);
            row.appendChild(nameTd);

            // Role checkmarks
            data.roles.forEach(role => {
                const td = document.createElement('td');
                if (perm.roles[role]) {
                    const check = document.createElement('span');
                    check.className = 'perm-check';
                    check.textContent = '\u2713';
                    td.appendChild(check);
                } else {
                    const x = document.createElement('span');
                    x.className = 'perm-x';
                    x.textContent = '\u2014';
                    td.appendChild(x);
                }
                row.appendChild(td);
            });

            body.appendChild(row);
            totalPerms++;
        });
    });

    document.getElementById('perm-count-label').textContent = totalPerms + ' permissions across ' + data.groups.length + ' categories';

    // Re-apply role highlight if active
    if (selectedRole) highlightRoleColumn(selectedRole);
}

function toggleCategory(category, catRow) {
    const isExpanded = catRow.classList.contains('expanded');
    catRow.classList.toggle('expanded');

    document.querySelectorAll('.perm-row[data-category="' + category + '"]').forEach(row => {
        row.style.display = isExpanded ? 'none' : '';
    });
}

function filterPermissions() {
    const query = document.getElementById('perm-search').value.toLowerCase().trim();
    let visibleCount = 0;

    document.querySelectorAll('.perm-row').forEach(row => {
        const matchesSearch = !query || row.dataset.label.includes(query) || row.dataset.code.includes(query);
        const matchesFilter = permFilterMode === 'all' || row.dataset.allSame === '0';
        const show = matchesSearch && matchesFilter;
        row.classList.toggle('hidden', !show);
        if (show) visibleCount++;
    });

    // Show/hide category headers based on whether they have visible children
    document.querySelectorAll('.category-row').forEach(catRow => {
        const cat = catRow.dataset.category;
        const hasVisible = document.querySelector('.perm-row[data-category="' + cat + '"]:not(.hidden)');
        catRow.style.display = hasVisible ? '' : 'none';
    });
}

function setPermFilter(mode) {
    permFilterMode = mode;
    document.querySelectorAll('.perm-filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === mode);
    });
    filterPermissions();
}

// Permission value to human-readable label lookup (shared with permissions tab)
const PERM_LABELS = {
    'public:view': 'View Public Pages', 'directory:view': 'View Directory',
    'archie:chat': 'Chat with A.R.C.H.I.E.', 'code_editor:read': 'Code Editor (Read)',
    'code_editor:write': 'Code Editor (Write)', 'user:settings': 'User Settings',
    'read:own': 'Read Own Data', 'write:own': 'Write Own Data',
    'task_planner:schedule': 'Schedule Tasks', 'task_planner:calendar': 'Calendar Access',
    'google:email': 'Google Email', 'google:contacts': 'Google Contacts',
    'google:calendar': 'Google Calendar', 'app_builder:create': 'Create Apps',
    'app_builder:deploy': 'Deploy Apps', 'app_builder:unlimited': 'Unlimited Projects',
    'website_builder:create': 'Create Websites', 'website_builder:deploy': 'Deploy Websites',
    'store:create': 'Create Store', 'store:manage': 'Manage Store',
    'telephony:access': 'Phone System', 'telephony:admin': 'Phone Admin',
    'social_media:create': 'Social Posts', 'social_media:schedule': 'Schedule Social',
    'figma:import': 'Figma Import', 'analytics:view': 'Analytics',
    'stock_bot:scan': 'Stock Scanner', 'stock_bot:alerts': 'Stock Alerts',
'admin:access': 'Admin Panel', 'admin:agents': 'Manage Agents',
    'admin:improvements': 'Improvements', 'admin:users': 'Manage Users',
    'admin:backups': 'Backups', 'admin:logs': 'System Logs',
    'admin:sandbox': 'Sandbox', 'admin:fine_tuning': 'AI Fine-Tuning',
    'admin:ide': 'IDE Access', 'admin:testing': 'Testing Tools',
    'admin:projects': 'Projects', 'read:all': 'Read All', 'write:all': 'Write All',
    'admin:mining': 'Mining', 'admin:system': 'System Ops',
    'admin:security': 'Security', 'superadmin:all': 'Full Access'
};

const ROLE_COLORS = {
    'USER': '#06b6d4', 'PREMIUM': '#f97316', 'ADMIN': '#ef4444', 'SUPER_ADMIN': '#a855f7'
};

// Store tiers data globally for subscription management
let cachedTiers = [];

// Subscription management user table pagination
let subMgmtPage = 1;
let subMgmtPageSize = 5;
let subMgmtTotal = 0;
let subMgmtSelectedUserId = null;

function changeSubMgmtPageSize(newSize) {
    subMgmtPageSize = parseInt(newSize);
    subMgmtPage = 1;
    loadSubMgmtUsers();
}

function changeSubMgmtPage(delta) {
    var totalSmPages = Math.ceil(subMgmtTotal / subMgmtPageSize) || 1;
    var newPage = subMgmtPage + delta;
    if (newPage >= 1 && newPage <= totalSmPages) {
        subMgmtPage = newPage;
        loadSubMgmtUsers();
    }
}

function updateSubMgmtPagination() {
    var totalSmPages = Math.ceil(subMgmtTotal / subMgmtPageSize) || 1;
    var start = ((subMgmtPage - 1) * subMgmtPageSize) + 1;
    var end = Math.min(subMgmtPage * subMgmtPageSize, subMgmtTotal);
    var info = document.getElementById('sub-mgmt-pagination-info');
    if (info) info.textContent = 'Showing ' + start + '–' + end + ' of ' + subMgmtTotal;
    var prevBtn = document.getElementById('sub-mgmt-prev-btn');
    var nextBtn = document.getElementById('sub-mgmt-next-btn');
    if (prevBtn) prevBtn.disabled = subMgmtPage <= 1;
    if (nextBtn) nextBtn.disabled = subMgmtPage >= totalSmPages;
}

async function loadSubMgmtUsers() {
    try {
        var url = '/tools/account-center/api/users?limit=' + subMgmtPageSize + '&offset=' + ((subMgmtPage - 1) * subMgmtPageSize);
        var res = await api(url);
        var data = await res.json();
        if (data.success) {
            subMgmtTotal = data.total || data.users.length;
            var tbody = document.getElementById('sub-mgmt-user-tbody');
            tbody.textContent = '';

            if (data.users.length === 0) {
                var tr = document.createElement('tr');
                var td = document.createElement('td');
                td.colSpan = 4;
                td.className = 'empty-state';
                td.textContent = 'No users found';
                tr.appendChild(td);
                tbody.appendChild(tr);
                updateSubMgmtPagination();
                return;
            }

            data.users.forEach(function(u) {
                var tr = document.createElement('tr');
                if (subMgmtSelectedUserId && subMgmtSelectedUserId == u.id) {
                    tr.className = 'selected-row';
                }

                var tdUser = document.createElement('td');
                var strong = document.createElement('strong');
                strong.textContent = u.username;
                tdUser.appendChild(strong);

                var tdTier = document.createElement('td');
                var tierBadge = document.createElement('span');
                tierBadge.className = 'badge ' + getTierBadgeClass(u.subscription_tier);
                tierBadge.textContent = getTierDisplayName(u.subscription_tier);
                tdTier.appendChild(tierBadge);

                var tdStatus = document.createElement('td');
                var statusBadge = document.createElement('span');
                statusBadge.className = 'badge ' + (u.is_active !== false ? 'badge-success' : 'badge-danger');
                statusBadge.textContent = u.is_active !== false ? 'Active' : 'Inactive';
                tdStatus.appendChild(statusBadge);

                var tdActions = document.createElement('td');
                var manageBtn = document.createElement('button');
                manageBtn.className = 'btn btn-sm';
                manageBtn.textContent = 'Manage';
                manageBtn.addEventListener('click', (function(userId, username) {
                    return function() {
                        subMgmtSelectedUserId = userId;
                        // Highlight selected row
                        tbody.querySelectorAll('tr').forEach(function(r) { r.classList.remove('selected-row'); });
                        tr.classList.add('selected-row');
                        openSubMgmtModal(userId, username);
                    };
                })(u.id, u.username));
                tdActions.appendChild(manageBtn);

                tr.appendChild(tdUser);
                tr.appendChild(tdTier);
                tr.appendChild(tdStatus);
                tr.appendChild(tdActions);
                tbody.appendChild(tr);
            });

            updateSubMgmtPagination();
        }
    } catch (err) {
        console.error('Error loading sub mgmt users:', err);
    }
}

async function loadTiers() {
    try {
        var tiersRes = await api('/tools/account-center/api/tiers');
        var tiersData = await tiersRes.json();

        if (tiersData.success) {
            cachedTiers = tiersData.tiers;
            renderTierCards(tiersData.tiers);
            renderTierComparison(tiersData.tiers);
        }

        // Load user table for subscription management
        loadSubMgmtUsers();
    } catch (err) {
        console.error('Error loading tiers:', err);
    }
}

function renderTierCards(tiers) {
    const grid = document.getElementById('tiers-grid');
    grid.textContent = '';

    const LIMIT_LABELS = {
        'storage_mb': 'Storage', 'app_projects': 'App Projects',
        'api_calls_daily': 'API Calls/Day', 'website_projects': 'Website Projects'
    };

    tiers.forEach(t => {
        const card = document.createElement('div');
        card.className = 'tier-card';
        card.style.borderColor = t.color;

        // Tier name
        const name = document.createElement('div');
        name.className = 'tier-name';
        name.style.color = t.color;
        name.textContent = t.display_name;

        // Price
        const price = document.createElement('div');
        price.className = 'tier-price';
        price.textContent = t.price_monthly > 0 ? '$' + t.price_monthly + '/mo' : 'Free';

        // Role badge
        const roleBadge = document.createElement('div');
        roleBadge.className = 'tier-role-badge';
        const roleColor = ROLE_COLORS[t.mapped_role] || '#6b7280';
        roleBadge.style.color = roleColor;
        roleBadge.style.borderColor = roleColor;
        roleBadge.textContent = t.mapped_role.replace('_', ' ') + ' Role';

        // Stats row (permissions, modules, users)
        const statsRow = document.createElement('div');
        statsRow.className = 'tier-stats-row';
        [{v: t.permission_count, l: 'Permissions'}, {v: t.module_count, l: 'Modules'}, {v: t.user_count, l: 'Users'}].forEach(s => {
            const stat = document.createElement('div');
            stat.className = 'tier-stat';
            const val = document.createElement('div');
            val.className = 'tier-stat-value';
            val.textContent = s.v;
            const lbl = document.createElement('div');
            lbl.className = 'tier-stat-label';
            lbl.textContent = s.l;
            stat.appendChild(val);
            stat.appendChild(lbl);
            statsRow.appendChild(stat);
        });

        // Features list
        const features = t.features || [];
        const featureList = document.createElement('ul');
        featureList.className = 'tier-features';
        features.forEach(f => {
            const li = document.createElement('li');
            li.textContent = f;
            featureList.appendChild(li);
        });

        // Limits grid
        const limits = t.limits || {};
        const limitsDiv = document.createElement('div');
        limitsDiv.className = 'tier-limits';
        Object.entries(limits).forEach(([key, val]) => {
            const item = document.createElement('div');
            item.className = 'tier-limit-item';
            const label = document.createElement('span');
            label.className = 'limit-label';
            label.textContent = LIMIT_LABELS[key] || key;
            const value = document.createElement('span');
            value.className = 'limit-value';
            value.textContent = val === -1 ? '\u221E' : (key.includes('storage') ? formatStorage(val) : val.toLocaleString());
            item.appendChild(label);
            item.appendChild(value);
            limitsDiv.appendChild(item);
        });

        // User count
        const userCount = document.createElement('div');
        userCount.className = 'tier-user-count';
        userCount.textContent = t.user_count + ' user' + (t.user_count !== 1 ? 's' : '') + ' on this tier';

        card.appendChild(name);
        card.appendChild(price);
        card.appendChild(roleBadge);
        card.appendChild(statsRow);
        card.appendChild(featureList);
        card.appendChild(limitsDiv);
        card.appendChild(userCount);

        // Upgrade CTA → KBS checkout for paid tiers (Phase F of unified billing plan)
        if (t.stripe_price_id_monthly && t.kbs_product_slug) {
            const cta = document.createElement('a');
            cta.className = 'btn btn-primary';
            cta.style.cssText = 'display: block; text-align: center; margin-top: var(--archie-space-4);';
            cta.target = '_blank';
            cta.rel = 'noopener';
            const returnUrl = encodeURIComponent(window.location.href);
            cta.href = 'https://business.kytranempowerment.com/plugins/billing/checkout'
                + '?tier=' + encodeURIComponent(t.kbs_product_slug)
                + '&return_url=' + returnUrl;
            cta.textContent = 'Upgrade to ' + t.display_name;
            card.appendChild(cta);
        }

        grid.appendChild(card);
    });
}

function formatStorage(mb) {
    if (mb >= 1000) return (mb / 1000) + ' GB';
    return mb + ' MB';
}

function renderTierComparison(tiers) {
    const head = document.getElementById('tier-comparison-head');
    const body = document.getElementById('tier-comparison-body');
    head.textContent = '';
    body.textContent = '';

    // Header row
    const headerRow = document.createElement('tr');
    const emptyTh = document.createElement('th');
    emptyTh.textContent = 'Feature';
    headerRow.appendChild(emptyTh);
    tiers.forEach(t => {
        const th = document.createElement('th');
        const nameSpan = document.createElement('span');
        nameSpan.className = 'th-role-name';
        nameSpan.textContent = t.display_name;
        nameSpan.style.color = t.color;
        const priceSpan = document.createElement('span');
        priceSpan.style.cssText = 'display:block; font-size:10px; color:var(--archie-text-secondary); font-weight:normal;';
        priceSpan.textContent = t.price_monthly > 0 ? '$' + t.price_monthly + '/mo' : 'Free';
        th.appendChild(nameSpan);
        th.appendChild(priceSpan);
        headerRow.appendChild(th);
    });
    head.appendChild(headerRow);

    // Role row
    addCompRow(body, 'RBAC Role', tiers.map(t => {
        const span = document.createElement('span');
        span.textContent = t.mapped_role.replace('_', ' ');
        span.style.color = ROLE_COLORS[t.mapped_role] || '#6b7280';
        span.style.fontWeight = '600';
        return span;
    }));

    // Permissions count row
    addCompRow(body, 'Total Permissions', tiers.map(t => t.permission_count));

    // Modules count row
    addCompRow(body, 'Modules Accessible', tiers.map(t => t.module_count));

    // Limit rows
    const LIMIT_LABELS = {
        'storage_mb': 'Storage', 'app_projects': 'App Projects',
        'api_calls_daily': 'API Calls/Day', 'website_projects': 'Website Projects'
    };
    const limitKeys = Object.keys(tiers[0]?.limits || {});
    limitKeys.forEach(key => {
        addCompRow(body, LIMIT_LABELS[key] || key, tiers.map(t => {
            const val = (t.limits || {})[key];
            if (val === undefined) return '\u2014';
            if (val === -1) return '\u221E';
            if (key.includes('storage')) return formatStorage(val);
            return val.toLocaleString();
        }));
    });

    // Permissions gained row (what's new at each tier)
    addCompRow(body, 'New Permissions', tiers.map(t => {
        const gained = t.permissions_gained || [];
        if (gained.length === 0) return '\u2014';
        const div = document.createElement('div');
        div.style.cssText = 'font-size:10px; max-height:80px; overflow-y:auto; text-align:left;';
        gained.slice(0, 8).forEach(p => {
            const line = document.createElement('div');
            line.textContent = '+ ' + (PERM_LABELS[p] || p);
            line.style.color = '#22c55e';
            div.appendChild(line);
        });
        if (gained.length > 8) {
            const more = document.createElement('div');
            more.textContent = '+ ' + (gained.length - 8) + ' more';
            more.style.color = 'var(--archie-text-tertiary)';
            div.appendChild(more);
        }
        return div;
    }));
}

function addCompRow(tbody, label, values) {
    const row = document.createElement('tr');
    row.className = 'perm-row';
    const labelTd = document.createElement('td');
    labelTd.textContent = label;
    labelTd.style.fontWeight = '500';
    row.appendChild(labelTd);

    values.forEach(val => {
        const td = document.createElement('td');
        if (val instanceof HTMLElement) {
            td.appendChild(val);
        } else {
            td.textContent = val;
        }
        row.appendChild(td);
    });
    tbody.appendChild(row);
}

// ============================================================================
// SUBSCRIPTION MANAGEMENT
// ============================================================================

let subMgmtData = null; // Cached subscription data for current management view

function openSubMgmtModal(userId, username) {
    var title = document.getElementById('sub-mgmt-modal-title');
    title.textContent = 'Manage Subscription — ' + (username || 'User');
    var overlay = document.getElementById('sub-mgmt-modal-overlay');
    overlay.classList.add('active');
    loadSubscriptionManagement(userId);
}

function closeSubMgmtModal() {
    var overlay = document.getElementById('sub-mgmt-modal-overlay');
    overlay.classList.remove('active');
}

// Close modal on overlay click (outside the modal content)
document.addEventListener('click', function(e) {
    var overlay = document.getElementById('sub-mgmt-modal-overlay');
    if (e.target === overlay) closeSubMgmtModal();
});

// Close modal on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeSubMgmtModal();
});

async function loadSubscriptionManagement(userIdParam) {
    const container = document.getElementById('subscription-management');
    const userId = userIdParam || subMgmtSelectedUserId || '';

    if (!userId) {
        container.textContent = '';
        const empty = document.createElement('div');
        empty.className = 'empty-state';
        const icon = document.createElement('div');
        icon.className = 'empty-state-icon';
        icon.textContent = '$';
        const p = document.createElement('p');
        p.textContent = 'Select a user above to manage their subscription';
        empty.appendChild(icon);
        empty.appendChild(p);
        container.appendChild(empty);
        return;
    }

    container.textContent = '';
    const loading = document.createElement('div');
    loading.className = 'loading';
    loading.textContent = 'Loading subscription data...';
    container.appendChild(loading);

    try {
        const res = await api('/tools/account-center/api/users/' + userId + '/subscription');
        const data = await res.json();
        if (data.success) {
            subMgmtData = data;
            container.textContent = '';
            renderSubscriptionManagement(container, data, userId);
        } else {
            container.textContent = 'Error loading subscription data.';
        }
    } catch (err) {
        console.error('Error loading subscription management:', err);
        container.textContent = 'Error loading subscription data.';
    }
}

function renderSubscriptionManagement(container, data, userId) {
    const sub = data.subscription || {};
    const usage = data.usage || {};
    const availableTiers = data.available_tiers || [];

    // Section 1: Current Tier Card
    const currentSection = document.createElement('div');
    currentSection.className = 'sub-mgmt-section';
    const currentTitle = document.createElement('div');
    currentTitle.className = 'sub-mgmt-section-title';
    currentTitle.textContent = 'Current Tier';
    currentSection.appendChild(currentTitle);

    const tierCard = document.createElement('div');
    tierCard.className = 'sub-tier-card';
    tierCard.style.borderColor = sub.color || '#6b7280';

    const cardHeader = document.createElement('div');
    cardHeader.className = 'sub-tier-card-header';
    const tierName = document.createElement('div');
    tierName.className = 'sub-tier-name';
    tierName.style.color = sub.color || '#6b7280';
    tierName.textContent = sub.display_name || 'Free';
    const tierPrice = document.createElement('div');
    tierPrice.className = 'sub-tier-price';
    tierPrice.textContent = sub.price > 0 ? '$' + sub.price + '/mo' : 'Free';
    cardHeader.appendChild(tierName);
    cardHeader.appendChild(tierPrice);
    tierCard.appendChild(cardHeader);

    // Details: role, status, dates
    const detailsGrid = document.createElement('div');
    detailsGrid.style.cssText = 'display: grid; grid-template-columns: 1fr 1fr; gap: var(--archie-space-2); font-size: var(--archie-text-sm);';

    const addDetail = (label, value, color) => {
        const row = document.createElement('div');
        const lbl = document.createElement('span');
        lbl.style.color = 'var(--archie-text-tertiary)';
        lbl.textContent = label + ': ';
        const val = document.createElement('span');
        val.style.color = color || 'var(--archie-text-primary)';
        val.textContent = value;
        row.appendChild(lbl);
        row.appendChild(val);
        detailsGrid.appendChild(row);
    };

    addDetail('Role', sub.mapped_role || 'USER');
    const subStatus = sub.status || 'active';
    const statusColor = subStatus === 'active' ? '#22c55e' : subStatus === 'cancelled' ? '#ef4444' : '#f59e0b';
    addDetail('Status', subStatus.charAt(0).toUpperCase() + subStatus.slice(1), statusColor);
    addDetail('Started', sub.started_at ? ArchieTime.date(sub.started_at) : 'N/A');
    addDetail('Expires', sub.expires_at ? ArchieTime.date(sub.expires_at) : 'Never');

    tierCard.appendChild(detailsGrid);
    currentSection.appendChild(tierCard);
    container.appendChild(currentSection);

    // Section 2: Usage Progress Bars
    const limits = sub.limits || {};
    if (Object.keys(limits).length > 0) {
        const usageSection = document.createElement('div');
        usageSection.className = 'sub-mgmt-section';
        const usageTitle = document.createElement('div');
        usageTitle.className = 'sub-mgmt-section-title';
        usageTitle.textContent = 'Usage';
        usageSection.appendChild(usageTitle);

        const LIMIT_LABELS = {
            'storage_mb': 'Storage (MB)', 'app_projects': 'App Projects',
            'api_calls_daily': 'API Calls/Day', 'website_projects': 'Website Projects'
        };

        Object.entries(limits).forEach(([key, max]) => {
            const current = usage[key] || 0;
            const wrap = document.createElement('div');
            wrap.className = 'usage-bar-wrap';

            const label = document.createElement('div');
            label.className = 'usage-bar-label';
            const labelName = document.createElement('span');
            labelName.textContent = LIMIT_LABELS[key] || key;
            const labelVal = document.createElement('span');
            labelVal.textContent = max === -1 ? current + ' / Unlimited' : current + ' / ' + max;
            label.appendChild(labelName);
            label.appendChild(labelVal);
            wrap.appendChild(label);

            const bar = document.createElement('div');
            bar.className = 'usage-bar';
            const fill = document.createElement('div');
            fill.className = 'usage-bar-fill';
            if (max === -1) {
                fill.style.width = '5%';
            } else {
                const pct = max > 0 ? Math.min(100, (current / max) * 100) : 0;
                fill.style.width = pct + '%';
                if (pct > 85) fill.classList.add('danger');
                else if (pct > 60) fill.classList.add('warning');
            }
            bar.appendChild(fill);
            wrap.appendChild(bar);
            usageSection.appendChild(wrap);
        });

        container.appendChild(usageSection);
    }

    // Section 3: Change Tier
    const changeSection = document.createElement('div');
    changeSection.className = 'sub-mgmt-section';
    const changeTitle = document.createElement('div');
    changeTitle.className = 'sub-mgmt-section-title';
    changeTitle.textContent = 'Change Tier';
    changeSection.appendChild(changeTitle);

    const changeRow = document.createElement('div');
    changeRow.style.cssText = 'display: flex; gap: var(--archie-space-2); align-items: center; flex-wrap: wrap;';

    const tierSelect = document.createElement('select');
    tierSelect.id = 'sub-mgmt-tier-select';
    tierSelect.className = 'form-select';
    tierSelect.style.minWidth = '180px';
    availableTiers.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t.name;
        opt.textContent = t.display_name + (t.price_monthly > 0 ? ' ($' + t.price_monthly + '/mo)' : ' (Free)');
        if (t.name === sub.tier_name) opt.selected = true;
        tierSelect.appendChild(opt);
    });
    changeRow.appendChild(tierSelect);

    const previewBtn = document.createElement('button');
    previewBtn.className = 'btn btn-ghost';
    previewBtn.textContent = 'Preview Changes';
    previewBtn.addEventListener('click', () => previewTierChange(userId, sub, availableTiers));
    changeRow.appendChild(previewBtn);

    const applyBtn = document.createElement('button');
    applyBtn.className = 'btn btn-primary';
    applyBtn.id = 'sub-mgmt-apply-btn';
    applyBtn.textContent = 'Apply Change';
    applyBtn.style.display = 'none';
    applyBtn.addEventListener('click', () => applyTierChange(userId));
    changeRow.appendChild(applyBtn);

    changeSection.appendChild(changeRow);

    // Preview area
    const previewArea = document.createElement('div');
    previewArea.id = 'sub-mgmt-preview';
    changeSection.appendChild(previewArea);

    container.appendChild(changeSection);

    // Section 4: Status & Expiry
    const statusSection = document.createElement('div');
    statusSection.className = 'sub-mgmt-section';
    const statusTitle = document.createElement('div');
    statusTitle.className = 'sub-mgmt-section-title';
    statusTitle.textContent = 'Status & Expiry';
    statusSection.appendChild(statusTitle);

    const statusRow = document.createElement('div');
    statusRow.style.cssText = 'display: flex; gap: var(--archie-space-3); align-items: center; flex-wrap: wrap;';

    const statusSelect = document.createElement('select');
    statusSelect.id = 'sub-mgmt-status-select';
    statusSelect.className = 'form-select';
    ['active', 'cancelled', 'paused'].forEach(s => {
        const opt = document.createElement('option');
        opt.value = s;
        opt.textContent = s.charAt(0).toUpperCase() + s.slice(1);
        if (s === (sub.status || 'active')) opt.selected = true;
        statusSelect.appendChild(opt);
    });
    statusRow.appendChild(statusSelect);

    const dateLabel = document.createElement('span');
    dateLabel.style.cssText = 'font-size: var(--archie-text-sm); color: var(--archie-text-secondary);';
    dateLabel.textContent = 'Expires:';
    statusRow.appendChild(dateLabel);

    const dateInput = document.createElement('input');
    dateInput.type = 'date';
    dateInput.id = 'sub-mgmt-expires-input';
    dateInput.className = 'form-input';
    dateInput.style.cssText = 'padding: var(--archie-space-2); background: var(--archie-bg-input); border: 1px solid var(--archie-border-default); border-radius: var(--archie-radius-sm); color: var(--archie-text-primary);';
    if (sub.expires_at) {
        dateInput.value = new Date(sub.expires_at).toISOString().split('T')[0];
    }
    statusRow.appendChild(dateInput);

    const clearDateBtn = document.createElement('button');
    clearDateBtn.className = 'btn btn-ghost';
    clearDateBtn.textContent = 'Clear';
    clearDateBtn.addEventListener('click', () => { dateInput.value = ''; });
    statusRow.appendChild(clearDateBtn);

    const saveStatusBtn = document.createElement('button');
    saveStatusBtn.className = 'btn btn-primary';
    saveStatusBtn.textContent = 'Save Status';
    saveStatusBtn.addEventListener('click', () => saveSubscriptionStatus(userId));
    statusRow.appendChild(saveStatusBtn);

    statusSection.appendChild(statusRow);
    container.appendChild(statusSection);
}

function previewTierChange(userId, currentSub, availableTiers) {
    const tierSelect = document.getElementById('sub-mgmt-tier-select');
    const previewArea = document.getElementById('sub-mgmt-preview');
    const applyBtn = document.getElementById('sub-mgmt-apply-btn');
    const newTierName = tierSelect.value;

    if (newTierName === currentSub.tier_name) {
        previewArea.textContent = '';
        applyBtn.style.display = 'none';
        return;
    }

    const newTier = availableTiers.find(t => t.name === newTierName);
    if (!newTier) return;

    const currentLevel = currentSub.role_level || 10;
    const newLevel = newTier.role_level || 10;
    const isUpgrade = newLevel > currentLevel;

    const preview = document.createElement('div');
    preview.className = 'tier-change-preview';

    // Direction label
    const dirLabel = document.createElement('div');
    dirLabel.style.cssText = 'font-family: var(--archie-font-heading); font-size: var(--archie-text-sm); margin-bottom: var(--archie-space-3); color: ' + (isUpgrade ? '#22c55e' : '#ef4444') + ';';
    dirLabel.textContent = isUpgrade ? 'UPGRADE' : 'DOWNGRADE';
    preview.appendChild(dirLabel);

    // Tier name change
    const nameRow = document.createElement('div');
    nameRow.className = 'tier-change-row';
    const nameLabel = document.createElement('span');
    nameLabel.textContent = 'Tier';
    const nameVals = document.createElement('span');
    const oldName = document.createElement('span');
    oldName.className = 'old-val';
    oldName.textContent = currentSub.display_name || 'Free';
    const arrow = document.createTextNode(' \u2192 ');
    const newName = document.createElement('span');
    newName.className = isUpgrade ? 'new-val-up' : 'new-val-down';
    newName.textContent = newTier.display_name;
    nameVals.appendChild(oldName);
    nameVals.appendChild(arrow);
    nameVals.appendChild(newName);
    nameRow.appendChild(nameLabel);
    nameRow.appendChild(nameVals);
    preview.appendChild(nameRow);

    // Price change
    const priceRow = document.createElement('div');
    priceRow.className = 'tier-change-row';
    const priceLabel = document.createElement('span');
    priceLabel.textContent = 'Price';
    const priceVals = document.createElement('span');
    const oldPrice = document.createElement('span');
    oldPrice.className = 'old-val';
    oldPrice.textContent = currentSub.price > 0 ? '$' + currentSub.price + '/mo' : 'Free';
    const priceArrow = document.createTextNode(' \u2192 ');
    const newPrice = document.createElement('span');
    newPrice.className = isUpgrade ? 'new-val-up' : 'new-val-down';
    newPrice.textContent = newTier.price_monthly > 0 ? '$' + newTier.price_monthly + '/mo' : 'Free';
    priceVals.appendChild(oldPrice);
    priceVals.appendChild(priceArrow);
    priceVals.appendChild(newPrice);
    priceRow.appendChild(priceLabel);
    priceRow.appendChild(priceVals);
    preview.appendChild(priceRow);

    // Limits comparison
    const LIMIT_LABELS = {
        'storage_mb': 'Storage (MB)', 'app_projects': 'App Projects',
        'api_calls_daily': 'API Calls/Day', 'website_projects': 'Website Projects'
    };

    const currentLimits = currentSub.limits || {};
    const newLimits = newTier.limits || {};
    const allKeys = new Set([...Object.keys(currentLimits), ...Object.keys(newLimits)]);

    allKeys.forEach(key => {
        const oldVal = currentLimits[key];
        const newVal = newLimits[key];
        if (oldVal === newVal) return;

        const limRow = document.createElement('div');
        limRow.className = 'tier-change-row';
        const limLabel = document.createElement('span');
        limLabel.textContent = LIMIT_LABELS[key] || key;
        const limVals = document.createElement('span');

        const oldLim = document.createElement('span');
        oldLim.className = 'old-val';
        oldLim.textContent = oldVal === -1 ? 'Unlimited' : (oldVal !== undefined ? oldVal : 'N/A');
        const limArrow = document.createTextNode(' \u2192 ');
        const newLim = document.createElement('span');

        const limImproved = (newVal === -1) || (newVal > (oldVal || 0));
        newLim.className = limImproved ? 'new-val-up' : 'new-val-down';
        newLim.textContent = newVal === -1 ? 'Unlimited' : (newVal !== undefined ? newVal : 'N/A');

        limVals.appendChild(oldLim);
        limVals.appendChild(limArrow);
        limVals.appendChild(newLim);
        limRow.appendChild(limLabel);
        limRow.appendChild(limVals);
        preview.appendChild(limRow);
    });

    previewArea.textContent = '';
    previewArea.appendChild(preview);
    applyBtn.style.display = '';
}

async function applyTierChange(userId) {
    const tierSelect = document.getElementById('sub-mgmt-tier-select');
    const statusSelect = document.getElementById('sub-mgmt-status-select');
    const expiresInput = document.getElementById('sub-mgmt-expires-input');
    const newTier = tierSelect.value;

    if (!confirm('Change this user\'s subscription to ' + newTier.toUpperCase() + '?')) return;

    try {
        const body = {
            tier: newTier,
            status: statusSelect ? statusSelect.value : 'active',
            expires_at: expiresInput && expiresInput.value ? expiresInput.value : null
        };
        const res = await api('/tools/account-center/api/users/' + userId + '/subscription', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (data.success) {
            // Refresh all panels
            loadSubscriptionManagement(userId);
            loadSubMgmtUsers();
            loadUsers();
        } else {
            alert(data.error || 'Error updating subscription');
        }
    } catch (err) {
        console.error('Error applying tier change:', err);
        alert('Error applying tier change');
    }
}

async function saveSubscriptionStatus(userId) {
    const statusSelect = document.getElementById('sub-mgmt-status-select');
    const expiresInput = document.getElementById('sub-mgmt-expires-input');

    if (!statusSelect) return;

    // Use current tier from the data
    const currentTier = subMgmtData && subMgmtData.subscription ? subMgmtData.subscription.tier_name : 'free';

    try {
        const body = {
            tier: currentTier,
            status: statusSelect.value,
            expires_at: expiresInput && expiresInput.value ? expiresInput.value : null
        };
        const res = await api('/tools/account-center/api/users/' + userId + '/subscription', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (data.success) {
            loadSubscriptionManagement(userId);
            loadSubMgmtUsers();
            loadUsers();
        } else {
            alert(data.error || 'Error saving subscription status');
        }
    } catch (err) {
        console.error('Error saving subscription status:', err);
        alert('Error saving subscription status');
    }
}

// Activity tab pagination and auto-refresh
let activityPage = 1;
let activityPageSize = 10;
let activityTotal = 0;
let activityRefreshInterval = null;
let activityCountdown = 15;
const ACTIVITY_REFRESH_S = 15;

function startActivityAutoRefresh() {
    stopActivityAutoRefresh();
    activityCountdown = ACTIVITY_REFRESH_S;
    var indicator = document.getElementById('activity-refresh-indicator');
    if (indicator) indicator.style.display = 'flex';
    updateActivityRefreshRing();

    activityRefreshInterval = setInterval(function() {
        activityCountdown--;
        if (activityCountdown <= 0) {
            loadActivity();
            activityCountdown = ACTIVITY_REFRESH_S;
        }
        updateActivityRefreshRing();
    }, 1000);
}

function stopActivityAutoRefresh() {
    if (activityRefreshInterval) {
        clearInterval(activityRefreshInterval);
        activityRefreshInterval = null;
    }
    var indicator = document.getElementById('activity-refresh-indicator');
    if (indicator) indicator.style.display = 'none';
}

function updateActivityRefreshRing() {
    var progress = document.querySelector('.activity-ring-progress');
    var label = document.querySelector('.activity-refresh-label');
    if (!progress || !label) return;

    var fraction = activityCountdown / ACTIVITY_REFRESH_S;
    var offset = CIRCUMFERENCE * (1 - fraction);
    progress.classList.add('animating');
    progress.style.strokeDashoffset = offset;
    label.textContent = activityCountdown + 's';
}

function changeActivityPageSize(newSize) {
    activityPageSize = parseInt(newSize);
    activityPage = 1;
    loadActivity();
}

function changeActivityPage(delta) {
    var totalActivityPages = Math.ceil(activityTotal / activityPageSize) || 1;
    var newPage = activityPage + delta;
    if (newPage >= 1 && newPage <= totalActivityPages) {
        activityPage = newPage;
        loadActivity();
    }
}

function updateActivityPagination() {
    var totalActivityPages = Math.ceil(activityTotal / activityPageSize) || 1;
    var start = ((activityPage - 1) * activityPageSize) + 1;
    var end = Math.min(activityPage * activityPageSize, activityTotal);
    var info = document.getElementById('activity-pagination-info');
    if (info) info.textContent = 'Showing ' + start + '–' + end + ' of ' + activityTotal;
    var prevBtn = document.getElementById('activity-prev-btn');
    var nextBtn = document.getElementById('activity-next-btn');
    if (prevBtn) prevBtn.disabled = activityPage <= 1;
    if (nextBtn) nextBtn.disabled = activityPage >= totalActivityPages;
}

async function loadActivity() {
    const module = document.getElementById('filter-activity-module').value;
    const action = document.getElementById('filter-activity-action').value;

    // Load summary data (chart + top actions/users with independent try/catch)
    try {
        const summaryRes = await api('/tools/account-center/api/activity/summary');
        const summaryData = await summaryRes.json();
        if (summaryData.success) {
            try {
                renderActivityChart(summaryData.by_day);
            } catch (chartErr) {
                console.error('Error rendering activity chart:', chartErr);
            }
            renderTopActions(summaryData.top_actions || []);
            renderTopUsers(summaryData.top_users || []);
        }
    } catch (fetchErr) {
        console.error('Error loading activity summary:', fetchErr);
    }

    // Load activity list (independent of chart)
    try {
        let url = '/tools/account-center/api/activity?';
        if (module) url += 'module=' + module + '&';
        if (action) url += 'action=' + action + '&';
        url += 'limit=' + activityPageSize + '&offset=' + ((activityPage - 1) * activityPageSize);

        const res = await api(url);
        const data = await res.json();
        if (data.success) {
            activityTotal = data.total || data.activities.length;
            const list = document.getElementById('activity-list');
            list.textContent = '';

            if (data.activities.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'empty-state';
                empty.textContent = 'No activity found';
                list.appendChild(empty);
                updateActivityPagination();
                return;
            }

            data.activities.forEach(a => {
                const item = document.createElement('div');
                item.className = 'activity-item';

                const icon = document.createElement('div');
                icon.className = 'activity-icon';
                icon.textContent = getActivityIcon(a.action);

                const details = document.createElement('div');
                details.className = 'activity-details';

                const actionDiv = document.createElement('div');
                actionDiv.className = 'activity-action';
                actionDiv.textContent = a.action;

                const meta = document.createElement('div');
                meta.className = 'activity-meta';
                meta.textContent = (a.user_name || 'System') + ' - ' + (a.module || '') + ' - ' + ArchieTime.format(a.created_at, 'short');

                details.appendChild(actionDiv);
                details.appendChild(meta);
                item.appendChild(icon);
                item.appendChild(details);
                list.appendChild(item);
            });

            updateActivityPagination();
        }
    } catch (err) {
        console.error('Error loading activity:', err);
    }
}

function getActivityIcon(action) {
    const icons = { 'login_success': 'i', 'login_failed': 'x', 'user_created': '+', 'user_updated': 'e', 'user_deleted': '-', 'subscription_changed': '$', 'role_changed': 'r' };
    return icons[action] || '>';
}

function renderActivityChart(data) {
    const ctx = document.getElementById('activity-chart');
    if (activityChart) activityChart.destroy();
    const accentColor = getComputedStyle(document.documentElement).getPropertyValue('--archie-accent').trim() || '#f97316';
    activityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.map(d => ArchieTime.date(d.date)),
            datasets: [{ label: 'Activity', data: data.map(d => d.count), borderColor: accentColor, backgroundColor: accentColor + '20', fill: true, tension: 0.4 }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { color: '#333' }, ticks: { color: '#888' } }, y: { grid: { color: '#333' }, ticks: { color: '#888' } } } }
    });
}

function renderTopActions(actions) {
    const container = document.getElementById('activity-top-actions');
    container.textContent = '';
    if (actions.length === 0) {
        const empty = document.createElement('div');
        empty.style.cssText = 'color: var(--archie-text-secondary); text-align: center; padding: var(--archie-space-4);';
        empty.textContent = 'No actions recorded';
        container.appendChild(empty);
        return;
    }
    const maxCount = actions[0].count || 1;
    actions.forEach(a => {
        const row = document.createElement('div');
        row.style.cssText = 'display: flex; align-items: center; gap: var(--archie-space-3); margin-bottom: var(--archie-space-2);';
        const label = document.createElement('span');
        label.style.cssText = 'min-width: 140px; color: var(--archie-text-primary); font-size: var(--archie-text-sm);';
        label.textContent = a.action;
        const barWrap = document.createElement('div');
        barWrap.style.cssText = 'flex: 1; height: 20px; background: var(--archie-bg-surface); border-radius: var(--archie-radius-sm); overflow: hidden;';
        const bar = document.createElement('div');
        const pct = Math.max((a.count / maxCount) * 100, 4);
        bar.style.cssText = 'height: 100%; background: var(--archie-accent); border-radius: var(--archie-radius-sm); width: ' + pct + '%;';
        barWrap.appendChild(bar);
        const count = document.createElement('span');
        count.style.cssText = 'min-width: 36px; text-align: right; color: var(--archie-text-secondary); font-size: var(--archie-text-sm);';
        count.textContent = a.count;
        row.appendChild(label);
        row.appendChild(barWrap);
        row.appendChild(count);
        container.appendChild(row);
    });
}

function renderTopUsers(topUsers) {
    const container = document.getElementById('activity-top-users');
    container.textContent = '';
    if (topUsers.length === 0) {
        const empty = document.createElement('div');
        empty.style.cssText = 'color: var(--archie-text-secondary); text-align: center; padding: var(--archie-space-4);';
        empty.textContent = 'No user activity recorded';
        container.appendChild(empty);
        return;
    }
    const maxCount = topUsers[0].count || 1;
    topUsers.forEach(u => {
        const row = document.createElement('div');
        row.style.cssText = 'display: flex; align-items: center; gap: var(--archie-space-3); margin-bottom: var(--archie-space-2);';
        const label = document.createElement('span');
        label.style.cssText = 'min-width: 140px; color: var(--archie-text-primary); font-size: var(--archie-text-sm); font-weight: 600;';
        label.textContent = u.username || u.user_name || 'Unknown';
        const barWrap = document.createElement('div');
        barWrap.style.cssText = 'flex: 1; height: 20px; background: var(--archie-bg-surface); border-radius: var(--archie-radius-sm); overflow: hidden;';
        const bar = document.createElement('div');
        const pct = Math.max((u.count / maxCount) * 100, 4);
        bar.style.cssText = 'height: 100%; background: var(--archie-green, #22c55e); border-radius: var(--archie-radius-sm); width: ' + pct + '%;';
        barWrap.appendChild(bar);
        const count = document.createElement('span');
        count.style.cssText = 'min-width: 36px; text-align: right; color: var(--archie-text-secondary); font-size: var(--archie-text-sm);';
        count.textContent = u.count;
        row.appendChild(label);
        row.appendChild(barWrap);
        row.appendChild(count);
        container.appendChild(row);
    });
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeModal(); closeDetailsModal(); closeApiKeyModal(); closeApiKeyCreatedModal(); } });
document.querySelectorAll('.modal-overlay').forEach(overlay => { overlay.addEventListener('click', e => { if (e.target === overlay) overlay.classList.remove('active'); }); });

// ============================================================================
// SESSIONS MANAGEMENT
// ============================================================================

// Sessions pagination (client-side)
let sessionsAllData = [];
let sessionsPage = 1;
let sessionsPageSize = 10;

function changeSessionsPageSize(newSize) {
    sessionsPageSize = parseInt(newSize);
    sessionsPage = 1;
    renderSessionsPage();
}

function changeSessionsPage(delta) {
    var totalSessPages = Math.ceil(sessionsAllData.length / sessionsPageSize) || 1;
    var newPage = sessionsPage + delta;
    if (newPage >= 1 && newPage <= totalSessPages) {
        sessionsPage = newPage;
        renderSessionsPage();
    }
}

function updateSessionsPagination() {
    var total = sessionsAllData.length;
    var totalSessPages = Math.ceil(total / sessionsPageSize) || 1;
    var start = ((sessionsPage - 1) * sessionsPageSize) + 1;
    var end = Math.min(sessionsPage * sessionsPageSize, total);
    var info = document.getElementById('sessions-pagination-info');
    if (info) info.textContent = 'Showing ' + start + '–' + end + ' of ' + total;
    var prevBtn = document.getElementById('sessions-prev-btn');
    var nextBtn = document.getElementById('sessions-next-btn');
    if (prevBtn) prevBtn.disabled = sessionsPage <= 1;
    if (nextBtn) nextBtn.disabled = sessionsPage >= totalSessPages;
}

function renderSessionsPage() {
    const start = (sessionsPage - 1) * sessionsPageSize;
    const pageSessions = sessionsAllData.slice(start, start + sessionsPageSize);
    renderSessionsTable(pageSessions);
    updateSessionsPagination();
}

async function loadSessions() {
    const userId = document.getElementById('filter-session-user').value;
    const search = document.getElementById('search-sessions').value;

    let url = '/tools/account-center/api/sessions?';
    if (userId) url += 'user_id=' + userId + '&';
    if (search) url += 'search=' + encodeURIComponent(search) + '&';

    try {
        const res = await api(url);
        const data = await res.json();
        if (data.success) {
            sessionsAllData = data.sessions || [];
            sessionsPage = 1;
            renderSessionsPage();
            populateSessionUserFilter(data.users || []);
        }
    } catch (err) {
        console.error('Error loading sessions:', err);
    }
}

function populateSessionUserFilter(userList) {
    const select = document.getElementById('filter-session-user');
    const currentVal = select.value;
    select.textContent = '';
    const defaultOpt = document.createElement('option');
    defaultOpt.value = '';
    defaultOpt.textContent = 'All Users';
    select.appendChild(defaultOpt);
    userList.forEach(u => {
        const opt = document.createElement('option');
        opt.value = u.id;
        opt.textContent = u.username;
        select.appendChild(opt);
    });
    if (currentVal) select.value = currentVal;
}

function renderSessionsTable(sessions) {
    const tbody = document.getElementById('sessions-table-body');
    tbody.textContent = '';

    if (sessions.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 7;
        td.className = 'empty-state';
        td.textContent = 'No active sessions found';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
    }

    sessions.forEach(s => {
        const tr = document.createElement('tr');

        const tdUser = document.createElement('td');
        const strong = document.createElement('strong');
        strong.textContent = s.username || 'Unknown';
        tdUser.appendChild(strong);

        const tdIp = document.createElement('td');
        tdIp.textContent = s.ip_address || '-';
        tdIp.style.fontFamily = 'monospace';

        const tdDevice = document.createElement('td');
        tdDevice.className = 'hide-fold';
        tdDevice.textContent = parseUserAgent(s.user_agent);
        tdDevice.style.fontSize = 'var(--archie-text-sm)';

        const tdCreated = document.createElement('td');
        tdCreated.className = 'hide-mobile';
        tdCreated.textContent = s.created_at ? ArchieTime.format(s.created_at, 'short') : '-';

        const tdActivity = document.createElement('td');
        tdActivity.className = 'hide-fold';
        tdActivity.textContent = s.last_activity ? ArchieTime.format(s.last_activity, 'short') : '-';

        const tdExpires = document.createElement('td');
        tdExpires.className = 'hide-mobile';
        if (s.expires_at) {
            const expires = new Date(s.expires_at);
            const isExpired = expires < new Date();
            tdExpires.textContent = ArchieTime.format(expires.toISOString(), 'short');
            if (isExpired) tdExpires.style.color = 'var(--archie-red)';
        } else {
            tdExpires.textContent = 'Never';
        }

        const tdActions = document.createElement('td');
        const revokeBtn = document.createElement('button');
        revokeBtn.className = 'btn btn-sm btn-danger';
        revokeBtn.textContent = 'Revoke';
        revokeBtn.onclick = () => revokeSession(s.id);
        tdActions.appendChild(revokeBtn);

        tr.appendChild(tdUser);
        tr.appendChild(tdIp);
        tr.appendChild(tdDevice);
        tr.appendChild(tdCreated);
        tr.appendChild(tdActivity);
        tr.appendChild(tdExpires);
        tr.appendChild(tdActions);
        tbody.appendChild(tr);
    });
}

function parseUserAgent(ua) {
    if (!ua) return 'Unknown';
    if (ua.includes('Chrome')) return 'Chrome';
    if (ua.includes('Firefox')) return 'Firefox';
    if (ua.includes('Safari')) return 'Safari';
    if (ua.includes('Edge')) return 'Edge';
    if (ua.includes('Mobile')) return 'Mobile';
    return 'Browser';
}

async function revokeSession(sessionId) {
    if (!confirm('Revoke this session? The user will be logged out.')) return;
    try {
        const res = await api('/tools/account-center/api/sessions/' + sessionId, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            loadSessions();
        } else {
            alert(data.error || 'Error revoking session');
        }
    } catch (err) {
        console.error('Error revoking session:', err);
        alert('Error revoking session');
    }
}

async function revokeAllSessions() {
    if (!confirm('Revoke all expired sessions?')) return;
    try {
        const res = await api('/tools/account-center/api/sessions/expired', { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            alert('Revoked ' + (data.count || 0) + ' expired sessions');
            loadSessions();
        } else {
            alert(data.error || 'Error revoking sessions');
        }
    } catch (err) {
        console.error('Error revoking sessions:', err);
    }
}

// ============================================================================
// API KEYS MANAGEMENT
// ============================================================================

// API Keys pagination (client-side)
let apiKeysAllData = [];
let apiKeysPage = 1;
let apiKeysPageSize = 10;

function changeApiKeysPageSize(newSize) {
    apiKeysPageSize = parseInt(newSize);
    apiKeysPage = 1;
    renderApiKeysPage();
}

function changeApiKeysPage(delta) {
    var totalAkPages = Math.ceil(apiKeysAllData.length / apiKeysPageSize) || 1;
    var newPage = apiKeysPage + delta;
    if (newPage >= 1 && newPage <= totalAkPages) {
        apiKeysPage = newPage;
        renderApiKeysPage();
    }
}

function updateApiKeysPagination() {
    var total = apiKeysAllData.length;
    var totalAkPages = Math.ceil(total / apiKeysPageSize) || 1;
    var start = ((apiKeysPage - 1) * apiKeysPageSize) + 1;
    var end = Math.min(apiKeysPage * apiKeysPageSize, total);
    var info = document.getElementById('apikeys-pagination-info');
    if (info) info.textContent = 'Showing ' + start + '–' + end + ' of ' + total;
    var prevBtn = document.getElementById('apikeys-prev-btn');
    var nextBtn = document.getElementById('apikeys-next-btn');
    if (prevBtn) prevBtn.disabled = apiKeysPage <= 1;
    if (nextBtn) nextBtn.disabled = apiKeysPage >= totalAkPages;
}

function renderApiKeysPage() {
    const start = (apiKeysPage - 1) * apiKeysPageSize;
    const pageKeys = apiKeysAllData.slice(start, start + apiKeysPageSize);
    renderApiKeysTable(pageKeys);
    updateApiKeysPagination();
}

async function loadApiKeys() {
    const userId = document.getElementById('filter-apikey-user').value;
    const status = document.getElementById('filter-apikey-status').value;

    let url = '/tools/account-center/api/api-keys?';
    if (userId) url += 'user_id=' + userId + '&';
    if (status) url += 'status=' + status + '&';

    try {
        const res = await api(url);
        const data = await res.json();
        if (data.success) {
            apiKeysAllData = data.keys || [];
            apiKeysPage = 1;
            renderApiKeysPage();
            populateApiKeyUserFilters(data.users || []);
        }
    } catch (err) {
        console.error('Error loading API keys:', err);
    }
}

function populateApiKeyUserFilters(userList) {
    ['filter-apikey-user', 'apikey-user'].forEach(selectId => {
        const select = document.getElementById(selectId);
        if (!select) return;
        const currentVal = select.value;
        select.textContent = '';
        const defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = selectId === 'apikey-user' ? 'Select User' : 'All Users';
        select.appendChild(defaultOpt);
        userList.forEach(u => {
            const opt = document.createElement('option');
            opt.value = u.id;
            opt.textContent = u.username;
            select.appendChild(opt);
        });
        if (currentVal) select.value = currentVal;
    });
}

function renderApiKeysTable(keys) {
    const tbody = document.getElementById('apikeys-table-body');
    tbody.textContent = '';

    if (keys.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 8;
        td.className = 'empty-state';
        td.textContent = 'No API keys found';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
    }

    keys.forEach(k => {
        const tr = document.createElement('tr');

        const tdUser = document.createElement('td');
        tdUser.textContent = k.username || 'System';

        const tdName = document.createElement('td');
        const strong = document.createElement('strong');
        strong.textContent = k.name;
        tdName.appendChild(strong);
        if (k.description) {
            const desc = document.createElement('div');
            desc.style.cssText = 'font-size: var(--archie-text-xs); color: var(--archie-text-tertiary);';
            desc.textContent = k.description;
            tdName.appendChild(desc);
        }

        const tdPrefix = document.createElement('td');
        tdPrefix.className = 'hide-fold';
        tdPrefix.textContent = k.key_prefix + '...';
        tdPrefix.style.fontFamily = 'monospace';

        const tdPerms = document.createElement('td');
        tdPerms.className = 'hide-mobile';
        const perms = k.permissions || ['read'];
        perms.forEach(p => {
            const badge = document.createElement('span');
            badge.className = 'badge';
            badge.style.marginRight = '4px';
            badge.textContent = p;
            tdPerms.appendChild(badge);
        });

        const tdLastUsed = document.createElement('td');
        tdLastUsed.className = 'hide-fold';
        tdLastUsed.textContent = k.last_used_at ? ArchieTime.date(k.last_used_at) : 'Never';

        const tdExpires = document.createElement('td');
        tdExpires.className = 'hide-mobile';
        if (k.expires_at) {
            const expires = new Date(k.expires_at);
            const isExpired = expires < new Date();
            tdExpires.textContent = ArchieTime.date(expires.toISOString());
            if (isExpired) tdExpires.style.color = 'var(--archie-red)';
        } else {
            tdExpires.textContent = 'Never';
        }

        const tdStatus = document.createElement('td');
        const statusBadge = document.createElement('span');
        let statusText = 'Active';
        let statusClass = 'badge-success';
        if (!k.is_active) {
            statusText = 'Inactive';
            statusClass = 'badge-danger';
        } else if (k.expires_at && new Date(k.expires_at) < new Date()) {
            statusText = 'Expired';
            statusClass = 'badge-warning';
        }
        statusBadge.className = 'badge ' + statusClass;
        statusBadge.textContent = statusText;
        tdStatus.appendChild(statusBadge);

        const tdActions = document.createElement('td');
        const actionsDiv = document.createElement('div');
        actionsDiv.style.display = 'flex';
        actionsDiv.style.gap = '8px';

        if (k.is_active) {
            const deactivateBtn = document.createElement('button');
            deactivateBtn.className = 'btn btn-sm';
            deactivateBtn.textContent = 'Deactivate';
            deactivateBtn.onclick = () => toggleApiKey(k.id, false);
            actionsDiv.appendChild(deactivateBtn);
        } else {
            const activateBtn = document.createElement('button');
            activateBtn.className = 'btn btn-sm btn-success';
            activateBtn.textContent = 'Activate';
            activateBtn.onclick = () => toggleApiKey(k.id, true);
            actionsDiv.appendChild(activateBtn);
        }

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn btn-sm btn-danger';
        deleteBtn.textContent = 'Delete';
        deleteBtn.onclick = () => deleteApiKey(k.id);
        actionsDiv.appendChild(deleteBtn);

        tdActions.appendChild(actionsDiv);

        tr.appendChild(tdUser);
        tr.appendChild(tdName);
        tr.appendChild(tdPrefix);
        tr.appendChild(tdPerms);
        tr.appendChild(tdLastUsed);
        tr.appendChild(tdExpires);
        tr.appendChild(tdStatus);
        tr.appendChild(tdActions);
        tbody.appendChild(tr);
    });
}

function showCreateApiKeyModal() {
    document.getElementById('apikey-form').reset();
    loadApiKeys(); // Refresh user list
    document.getElementById('apikey-modal').classList.add('active');
}

function closeApiKeyModal() {
    document.getElementById('apikey-modal').classList.remove('active');
}

function closeApiKeyCreatedModal() {
    document.getElementById('apikey-created-modal').classList.remove('active');
}

async function createApiKey(e) {
    e.preventDefault();
    const userId = document.getElementById('apikey-user').value;
    const name = document.getElementById('apikey-name').value;
    const description = document.getElementById('apikey-description').value;
    const expiry = document.getElementById('apikey-expiry').value;
    const rateLimit = document.getElementById('apikey-ratelimit').value;

    const permCheckboxes = document.querySelectorAll('input[name="apikey-perm"]:checked');
    const permissions = Array.from(permCheckboxes).map(cb => cb.value);

    try {
        const res = await api('/tools/account-center/api/api-keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: parseInt(userId),
                name: name,
                description: description,
                permissions: permissions,
                expires_in_days: expiry ? parseInt(expiry) : null,
                rate_limit_per_hour: parseInt(rateLimit)
            })
        });
        const data = await res.json();
        if (data.success) {
            closeApiKeyModal();
            document.getElementById('generated-key').value = data.api_key;
            document.getElementById('apikey-created-modal').classList.add('active');
            loadApiKeys();
        } else {
            alert(data.error || 'Error creating API key');
        }
    } catch (err) {
        console.error('Error creating API key:', err);
        alert('Error creating API key');
    }
}

function copyApiKey() {
    const keyInput = document.getElementById('generated-key');
    keyInput.select();
    document.execCommand('copy');
    alert('API key copied to clipboard');
}

async function toggleApiKey(keyId, activate) {
    try {
        const res = await api('/tools/account-center/api/api-keys/' + keyId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: activate })
        });
        const data = await res.json();
        if (data.success) {
            loadApiKeys();
        } else {
            alert(data.error || 'Error updating API key');
        }
    } catch (err) {
        console.error('Error updating API key:', err);
    }
}

async function deleteApiKey(keyId) {
    if (!confirm('Delete this API key? This cannot be undone.')) return;
    try {
        const res = await api('/tools/account-center/api/api-keys/' + keyId, { method: 'DELETE' });
        const data = await res.json();
        if (data.success) {
            loadApiKeys();
        } else {
            alert(data.error || 'Error deleting API key');
        }
    } catch (err) {
        console.error('Error deleting API key:', err);
    }
}

// ============================================================================
// BULK OPERATIONS
// ============================================================================

let bulkPreviewData = null;

document.getElementById('bulk-action').addEventListener('change', function() {
    const tierGroup = document.getElementById('bulk-tier-group');
    tierGroup.style.display = ['upgrade', 'downgrade'].includes(this.value) ? 'block' : 'none';
});

async function exportUsers() {
    const format = document.getElementById('export-format').value;
    const scope = document.getElementById('export-scope').value;

    try {
        const res = await api('/tools/account-center/api/bulk/export?format=' + format + '&scope=' + scope);
        if (res.ok) {
            const blob = await res.blob();
            const filename = 'users_export_' + new Date().toISOString().slice(0, 10) + '.' + format;
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        } else {
            const data = await res.json();
            alert(data.error || 'Error exporting users');
        }
    } catch (err) {
        console.error('Error exporting users:', err);
        alert('Error exporting users');
    }
}

async function previewBulkUpdate() {
    const target = document.getElementById('bulk-target').value;
    const action = document.getElementById('bulk-action').value;
    const tier = document.getElementById('bulk-tier').value;

    try {
        const res = await api('/tools/account-center/api/bulk/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target: target, action: action, tier: tier })
        });
        const data = await res.json();
        if (data.success) {
            bulkPreviewData = data;
            const content = document.getElementById('bulk-preview-content');
            content.textContent = '';

            const summary = document.createElement('p');
            summary.style.marginBottom = 'var(--archie-space-4)';
            summary.textContent = 'This will affect ' + data.count + ' user(s): ' + data.action_description;
            content.appendChild(summary);

            if (data.users && data.users.length > 0) {
                const list = document.createElement('ul');
                list.style.cssText = 'list-style: none; max-height: 200px; overflow-y: auto;';
                data.users.slice(0, 20).forEach(u => {
                    const li = document.createElement('li');
                    li.style.padding = 'var(--archie-space-1) 0';
                    li.textContent = u.username + ' (' + (u.email || 'no email') + ')';
                    list.appendChild(li);
                });
                if (data.users.length > 20) {
                    const more = document.createElement('li');
                    more.style.color = 'var(--archie-text-tertiary)';
                    more.textContent = '... and ' + (data.users.length - 20) + ' more';
                    list.appendChild(more);
                }
                content.appendChild(list);
            }

            document.getElementById('bulk-preview-card').style.display = 'block';
        } else {
            alert(data.error || 'Error generating preview');
        }
    } catch (err) {
        console.error('Error previewing bulk update:', err);
    }
}

function cancelBulkPreview() {
    document.getElementById('bulk-preview-card').style.display = 'none';
    bulkPreviewData = null;
}

async function executeBulkUpdate() {
    if (!bulkPreviewData) return;
    if (!confirm('Are you sure you want to apply these changes to ' + bulkPreviewData.count + ' users?')) return;

    try {
        const res = await api('/tools/account-center/api/bulk/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target: document.getElementById('bulk-target').value,
                action: document.getElementById('bulk-action').value,
                tier: document.getElementById('bulk-tier').value
            })
        });
        const data = await res.json();
        if (data.success) {
            alert('Successfully updated ' + data.count + ' users');
            cancelBulkPreview();
            loadUsers();
        } else {
            alert(data.error || 'Error applying bulk update');
        }
    } catch (err) {
        console.error('Error executing bulk update:', err);
    }
}

// ============================================================================
// SECURITY TAB
// ============================================================================

async function loadSecurityData() {
    // Initialize Lucide icons in security tab (static icons in HTML)
    if (typeof lucide !== 'undefined') lucide.createIcons();

    try {
        const res = await api('/tools/account-center/api/security/overview');
        const data = await res.json();
        if (data.success) {
            document.getElementById('failed-login-count').textContent = data.failed_logins_24h || 0;
            document.getElementById('locked-account-count').textContent = data.locked_accounts || 0;
            document.getElementById('totp-enabled-count').textContent = data.totp_enabled || 0;
        }
    } catch (err) {
        console.error('Error loading security data:', err);
    }

    loadFailedLogins();
    loadTotpUsers();
}

// Failed logins pagination
let failedLoginPage = 1;
let failedLoginPageSize = 10;
let failedLoginTotal = 0;

function changeFailedLoginsPageSize(newSize) {
    failedLoginPageSize = parseInt(newSize);
    failedLoginPage = 1;
    loadFailedLogins();
}

function changeFailedLoginsPage(delta) {
    var totalFlPages = Math.ceil(failedLoginTotal / failedLoginPageSize) || 1;
    var newPage = failedLoginPage + delta;
    if (newPage >= 1 && newPage <= totalFlPages) {
        failedLoginPage = newPage;
        loadFailedLogins();
    }
}

function updateFailedLoginsPagination() {
    var totalFlPages = Math.ceil(failedLoginTotal / failedLoginPageSize) || 1;
    var start = ((failedLoginPage - 1) * failedLoginPageSize) + 1;
    var end = Math.min(failedLoginPage * failedLoginPageSize, failedLoginTotal);
    var info = document.getElementById('fl-pagination-info');
    if (info) info.textContent = 'Showing ' + start + '–' + end + ' of ' + failedLoginTotal;
    var prevBtn = document.getElementById('fl-prev-btn');
    var nextBtn = document.getElementById('fl-next-btn');
    if (prevBtn) prevBtn.disabled = failedLoginPage <= 1;
    if (nextBtn) nextBtn.disabled = failedLoginPage >= totalFlPages;
}

async function loadFailedLogins() {
    try {
        const url = '/tools/account-center/api/security/failed-logins?limit=' + failedLoginPageSize + '&offset=' + ((failedLoginPage - 1) * failedLoginPageSize);
        const res = await api(url);
        const data = await res.json();
        if (data.success) {
            failedLoginTotal = data.total || data.logins.length;
            const tbody = document.getElementById('failed-logins-table');
            tbody.textContent = '';

            if (data.logins.length === 0) {
                const tr = document.createElement('tr');
                const td = document.createElement('td');
                td.colSpan = 4;
                td.className = 'empty-state';
                td.textContent = 'No failed login attempts in the last 24 hours';
                tr.appendChild(td);
                tbody.appendChild(tr);
                updateFailedLoginsPagination();
                return;
            }

            data.logins.forEach(l => {
                const tr = document.createElement('tr');

                const tdUser = document.createElement('td');
                const strong = document.createElement('strong');
                strong.textContent = l.username || 'Unknown';
                tdUser.appendChild(strong);

                const tdIp = document.createElement('td');
                tdIp.textContent = l.ip_address || '-';
                tdIp.style.fontFamily = 'monospace';

                const tdReason = document.createElement('td');
                tdReason.className = 'hide-mobile';
                tdReason.textContent = l.reason || 'Invalid credentials';

                const tdTime = document.createElement('td');
                tdTime.textContent = ArchieTime.format(l.attempted_at, 'short');

                tr.appendChild(tdUser);
                tr.appendChild(tdIp);
                tr.appendChild(tdReason);
                tr.appendChild(tdTime);
                tbody.appendChild(tr);
            });

            updateFailedLoginsPagination();
        }
    } catch (err) {
        console.error('Error loading failed logins:', err);
    }
}

// 2FA pagination (client-side)
let totpAllUsers = [];
let totpPage = 1;
let totpPageSize = 10;

function changeTotpPageSize(newSize) {
    totpPageSize = parseInt(newSize);
    totpPage = 1;
    renderTotpPage();
}

function changeTotpPage(delta) {
    var totalTotpPages = Math.ceil(totpAllUsers.length / totpPageSize) || 1;
    var newPage = totpPage + delta;
    if (newPage >= 1 && newPage <= totalTotpPages) {
        totpPage = newPage;
        renderTotpPage();
    }
}

function updateTotpPagination() {
    var total = totpAllUsers.length;
    var totalTotpPages = Math.ceil(total / totpPageSize) || 1;
    var start = ((totpPage - 1) * totpPageSize) + 1;
    var end = Math.min(totpPage * totpPageSize, total);
    var info = document.getElementById('totp-pagination-info');
    if (info) info.textContent = 'Showing ' + start + '–' + end + ' of ' + total;
    var prevBtn = document.getElementById('totp-prev-btn');
    var nextBtn = document.getElementById('totp-next-btn');
    if (prevBtn) prevBtn.disabled = totpPage <= 1;
    if (nextBtn) nextBtn.disabled = totpPage >= totalTotpPages;
}

function renderTotpPage() {
    const tbody = document.getElementById('totp-users-table');
    tbody.textContent = '';

    if (totpAllUsers.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 5;
        td.className = 'empty-state';
        td.textContent = 'No users configured';
        tr.appendChild(td);
        tbody.appendChild(tr);
        updateTotpPagination();
        return;
    }

    const start = (totpPage - 1) * totpPageSize;
    const pageUsers = totpAllUsers.slice(start, start + totpPageSize);

    pageUsers.forEach(u => {
        const tr = document.createElement('tr');

        const tdUser = document.createElement('td');
        const strong = document.createElement('strong');
        strong.textContent = u.username;
        tdUser.appendChild(strong);

        const tdEmail = document.createElement('td');
        tdEmail.className = 'hide-fold';
        tdEmail.textContent = u.email || '-';

        const tdStatus = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = 'badge ' + (u.totp_enabled ? 'badge-success' : 'badge-danger');
        badge.textContent = u.totp_enabled ? 'Enabled' : 'Disabled';
        tdStatus.appendChild(badge);

        const tdSince = document.createElement('td');
        tdSince.className = 'hide-mobile';
        tdSince.textContent = u.totp_verified_at ? ArchieTime.date(u.totp_verified_at) : '-';

        const tdActions = document.createElement('td');
        const actionsDiv = document.createElement('div');
        actionsDiv.style.display = 'flex';
        actionsDiv.style.gap = '8px';

        if (u.totp_enabled) {
            const disableBtn = document.createElement('button');
            disableBtn.className = 'btn btn-sm btn-danger';
            disableBtn.textContent = 'Disable';
            disableBtn.onclick = () => toggle2FA(u.id, false);
            actionsDiv.appendChild(disableBtn);

            const resetBtn = document.createElement('button');
            resetBtn.className = 'btn btn-sm btn-warning';
            resetBtn.textContent = 'Reset';
            resetBtn.onclick = () => toggle2FA(u.id, 'reset');
            actionsDiv.appendChild(resetBtn);
        } else {
            const enableBtn = document.createElement('button');
            enableBtn.className = 'btn btn-sm';
            enableBtn.style.cssText = 'background: rgba(34,197,94,0.15); color: #22c55e; border: 1px solid rgba(34,197,94,0.3);';
            enableBtn.textContent = 'Enable';
            enableBtn.onclick = () => toggle2FA(u.id, true);
            actionsDiv.appendChild(enableBtn);
        }

        if (u.locked_until && new Date(u.locked_until) > new Date()) {
            const unlockBtn = document.createElement('button');
            unlockBtn.className = 'btn btn-sm btn-warning';
            unlockBtn.textContent = 'Unlock';
            unlockBtn.onclick = () => unlockUser(u.id);
            actionsDiv.appendChild(unlockBtn);
        }

        tdActions.appendChild(actionsDiv);

        tr.appendChild(tdUser);
        tr.appendChild(tdEmail);
        tr.appendChild(tdStatus);
        tr.appendChild(tdSince);
        tr.appendChild(tdActions);
        tbody.appendChild(tr);
    });

    updateTotpPagination();
}

async function loadTotpUsers() {
    try {
        const res = await api('/tools/account-center/api/security/2fa');
        const data = await res.json();
        if (data.success) {
            totpAllUsers = data.users || [];
            totpPage = 1;
            renderTotpPage();
        }
    } catch (err) {
        console.error('Error loading 2FA users:', err);
    }
}

async function toggle2FA(userId, action) {
    const labels = { true: 'enable', false: 'disable', reset: 'reset' };
    const label = labels[action] || action;

    const messages = {
        true: 'Enable 2FA for this user? A TOTP secret will be generated that must be added to their authenticator app.',
        false: 'Disable 2FA for this user? They will need to re-enroll to use 2FA again.',
        reset: 'Reset 2FA for this user? This generates a new TOTP secret and invalidates the old one.'
    };
    if (!confirm(messages[action] || 'Are you sure?')) return;

    try {
        const body = action === 'reset'
            ? { enabled: true, reset: true }
            : { enabled: action === true };

        const res = await api('/tools/account-center/api/security/2fa/' + userId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if (data.success) {
            // If enabling/resetting, show QR code modal
            if ((action === true || action === 'reset') && data.totp_secret) {
                show2FAQRModal(data.totp_secret, data.qr_code, action === 'reset');
            }
            loadSecurityData();
        } else {
            alert(data.error || 'Error updating 2FA');
        }
    } catch (err) {
        console.error('Error toggling 2FA:', err);
    }
}

function show2FAQRModal(secret, qrCode, isReset) {
    // Remove existing modal if any
    const existing = document.getElementById('qr-modal-overlay');
    if (existing) existing.remove();

    // Build modal using safe DOM methods
    const overlay = document.createElement('div');
    overlay.id = 'qr-modal-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:10000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });

    const modal = document.createElement('div');
    modal.style.cssText = 'background:var(--archie-bg-card,#161b22);border:1px solid var(--archie-accent-alpha-30,rgba(0,255,65,0.3));border-radius:16px;padding:32px;max-width:420px;width:90%;text-align:center;box-shadow:0 25px 50px rgba(0,0,0,0.5);';

    // Title
    const h3 = document.createElement('h3');
    h3.style.cssText = 'color:var(--archie-accent,#00ff41);font-family:var(--archie-font-heading,"Orbitron",sans-serif);font-size:1.1rem;margin-bottom:8px;letter-spacing:0.1em;';
    h3.textContent = isReset ? '2FA Secret Reset' : '2FA Enabled Successfully';
    modal.appendChild(h3);

    // Subtitle
    const subtitle = document.createElement('p');
    subtitle.style.cssText = 'color:var(--archie-text-secondary,#8b949e);font-size:0.8rem;margin-bottom:20px;';
    subtitle.textContent = 'Scan this QR code with Google Authenticator or any TOTP app';
    modal.appendChild(subtitle);

    // QR code image
    if (qrCode) {
        const img = document.createElement('img');
        img.src = qrCode;
        img.alt = '2FA QR Code';
        img.style.cssText = 'display:block;margin:0 auto 20px;border-radius:8px;background:#fff;padding:8px;';
        modal.appendChild(img);
    }

    // Manual entry section
    const manualDiv = document.createElement('div');
    manualDiv.style.cssText = 'margin-bottom:20px;';

    const manualLabel = document.createElement('p');
    manualLabel.style.cssText = 'color:var(--archie-text-secondary,#8b949e);font-size:0.7rem;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.1em;';
    manualLabel.textContent = 'Manual Entry Key';
    manualDiv.appendChild(manualLabel);

    const secretCode = document.createElement('code');
    secretCode.id = 'totp-secret-display';
    secretCode.style.cssText = 'display:block;background:rgba(0,0,0,0.4);border:1px solid var(--archie-border,#21262d);border-radius:8px;padding:12px;font-size:0.95rem;color:var(--archie-text-primary,#e6edf3);letter-spacing:0.15em;word-break:break-all;cursor:pointer;user-select:all;';
    secretCode.title = 'Click to copy';
    secretCode.textContent = secret;
    manualDiv.appendChild(secretCode);

    const copyBtn = document.createElement('button');
    copyBtn.style.cssText = 'margin-top:8px;background:transparent;border:1px solid var(--archie-accent-alpha-30,rgba(0,255,65,0.3));border-radius:6px;color:var(--archie-accent,#00ff41);padding:6px 16px;font-size:0.75rem;cursor:pointer;letter-spacing:0.05em;';
    copyBtn.textContent = 'Copy Secret';
    copyBtn.addEventListener('click', function() {
        navigator.clipboard.writeText(secret).then(function() {
            copyBtn.textContent = 'Copied!';
            setTimeout(function() { copyBtn.textContent = 'Copy Secret'; }, 2000);
        });
    });
    manualDiv.appendChild(copyBtn);
    modal.appendChild(manualDiv);

    // Done button
    const doneBtn = document.createElement('button');
    doneBtn.style.cssText = 'background:var(--archie-accent,#00ff41);color:#000;border:none;border-radius:8px;padding:12px 32px;font-family:var(--archie-font-heading,"Orbitron",sans-serif);font-size:0.8rem;font-weight:600;cursor:pointer;letter-spacing:0.1em;text-transform:uppercase;';
    doneBtn.textContent = 'Done';
    doneBtn.addEventListener('click', function() { overlay.remove(); });
    modal.appendChild(doneBtn);

    overlay.appendChild(modal);
    document.body.appendChild(overlay);
}

async function unlockUser(userId) {
    if (!confirm('Unlock this user account?')) return;

    try {
        const res = await api('/tools/account-center/api/security/unlock/' + userId, {
            method: 'POST'
        });
        const data = await res.json();
        if (data.success) {
            loadSecurityData();
        } else {
            alert(data.error || 'Error unlocking user');
        }
    } catch (err) {
        console.error('Error unlocking user:', err);
    }
}

// ============================================================================
// USER IMPORT
// ============================================================================

// Drag and drop
const dropzone = document.getElementById('import-dropzone');
if (dropzone) {
    dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
    dropzone.addEventListener('dragleave', () => { dropzone.classList.remove('dragover'); });
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file && file.name.endsWith('.csv')) {
            parseCSVFile(file);
        } else {
            alert('Please drop a CSV file');
        }
    });
}

function handleImportFile(event) {
    const file = event.target.files[0];
    if (file) parseCSVFile(file);
}

function parseCSVFile(file) {
    const reader = new FileReader();
    reader.onload = function(e) {
        const text = e.target.result;
        const lines = text.split('\n').filter(l => l.trim());
        if (lines.length < 2) {
            alert('CSV must have a header row and at least one data row');
            return;
        }

        const headers = lines[0].split(',').map(h => h.trim().toLowerCase());
        const usernameIdx = headers.indexOf('username');
        const emailIdx = headers.indexOf('email');
        const passwordIdx = headers.indexOf('password');

        if (usernameIdx === -1 || passwordIdx === -1) {
            alert('CSV must have at least "username" and "password" columns');
            return;
        }

        importData = [];
        const roleIdx = headers.indexOf('role');
        const tierIdx = headers.indexOf('subscription_tier');

        for (let i = 1; i < Math.min(lines.length, 1001); i++) {
            const cols = lines[i].split(',').map(c => c.trim());
            if (!cols[usernameIdx]) continue;

            importData.push({
                username: cols[usernameIdx],
                email: emailIdx >= 0 ? (cols[emailIdx] || '') : '',
                password: cols[passwordIdx] || '',
                role: roleIdx >= 0 ? (cols[roleIdx] || 'user') : 'user',
                subscription_tier: tierIdx >= 0 ? (cols[tierIdx] || 'free') : 'free'
            });
        }

        // Show preview
        document.getElementById('import-count').textContent = importData.length;
        const previewTable = document.getElementById('import-preview-table');
        previewTable.textContent = '';

        importData.slice(0, 10).forEach(u => {
            const tr = document.createElement('tr');
            ['username', 'email', 'role', 'subscription_tier'].forEach(field => {
                const td = document.createElement('td');
                td.textContent = u[field] || '-';
                tr.appendChild(td);
            });
            previewTable.appendChild(tr);
        });

        if (importData.length > 10) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.colSpan = 4;
            td.style.color = 'var(--archie-text-tertiary)';
            td.textContent = '... and ' + (importData.length - 10) + ' more';
            tr.appendChild(td);
            previewTable.appendChild(tr);
        }

        document.getElementById('import-preview').style.display = 'block';
    };
    reader.readAsText(file);
}

function cancelImport() {
    importData = [];
    document.getElementById('import-preview').style.display = 'none';
    document.getElementById('import-file').value = '';
}

async function executeImport() {
    if (importData.length === 0) return;
    if (!confirm('Import ' + importData.length + ' users?')) return;

    try {
        const res = await api('/tools/account-center/api/bulk/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ users: importData })
        });
        const data = await res.json();
        if (data.success) {
            alert('Imported ' + data.created + ' users. ' + (data.skipped || 0) + ' skipped (duplicates).');
            cancelImport();
            loadUsers();
        } else {
            alert(data.error || 'Error importing users');
        }
    } catch (err) {
        console.error('Error importing users:', err);
        alert('Error importing users');
    }
}

// ==========================================================================
// ORGS TAB - SaaS Manager Integration
// All functions prefixed with "saas" to avoid collisions
// Uses innerHTML with saasEscapeHtml() sanitizer matching existing codebase patterns.
// All data is from authenticated admin API endpoints.
// ==========================================================================

(function() {
    'use strict';

    var SAAS_API = '/tools/saas-manager';
    var saasAllOrgs = [];
    var saasAllModules = [];
    var saasCurrentOrgId = null;
    var saasInitialized = false;

    // ── Sub-Tab Switching ───────────────────────────────────────────────────

    window.saasSwitchSubTab = function(tabName) {
        document.querySelectorAll('.saas-sub-tab-btn').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.saasTab === tabName);
        });
        document.querySelectorAll('.saas-sub-content').forEach(function(panel) {
            panel.classList.toggle('active', panel.id === tabName);
        });

        if (tabName === 'saas-domains') saasLoadAllDomains();
        if (tabName === 'saas-network') saasLoadNetworkInfo();
    };

    // ── Main Load (called when ORGS tab is activated) ───────────────────────

    window.saasLoadOrgs = function() {
        if (!saasInitialized) {
            saasLoadAvailableModules();
            saasLoadNetworkInfo();
            saasInitialized = true;
        }

        var loading = document.getElementById('saas-orgs-loading');
        var grid = document.getElementById('saas-orgs-grid');
        var empty = document.getElementById('saas-orgs-empty');
        if (loading) loading.style.display = 'flex';
        if (grid) grid.style.display = 'none';
        if (empty) empty.style.display = 'none';

        fetch(SAAS_API + '/orgs')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (loading) loading.style.display = 'none';
                if (!data.success) {
                    saasShowToast('Failed to load organizations', 'error');
                    return;
                }
                saasAllOrgs = data.orgs || [];
                saasUpdateStats();
                saasRenderOrgGrid();
            })
            .catch(function(err) {
                if (loading) loading.style.display = 'none';
                saasShowToast('Error loading organizations: ' + err.message, 'error');
            });
    };

    function saasRenderOrgGrid() {
        var grid = document.getElementById('saas-orgs-grid');
        var empty = document.getElementById('saas-orgs-empty');

        if (saasAllOrgs.length === 0) {
            grid.style.display = 'none';
            empty.style.display = 'block';
            return;
        }

        grid.style.display = 'grid';
        empty.style.display = 'none';

        // Build DOM safely using document fragment
        grid.textContent = '';
        saasAllOrgs.forEach(function(org) {
            var card = document.createElement('div');
            card.className = 'saas-org-card';
            card.setAttribute('onclick', 'saasOpenOrgDetail(' + org.id + ')');

            var nameDiv = document.createElement('div');
            nameDiv.className = 'saas-org-card-name';
            nameDiv.innerHTML = '<i data-lucide="building" style="width:18px;height:18px;color:var(--archie-accent)"></i>';
            var nameText = document.createTextNode(' ' + (org.name || ''));
            nameDiv.appendChild(nameText);
            var badge = document.createElement('span');
            badge.className = 'badge badge-' + (org.status || 'active');
            badge.textContent = org.status || 'active';
            nameDiv.appendChild(badge);

            var statsDiv = document.createElement('div');
            statsDiv.className = 'saas-org-card-stats';
            [{icon:'users', val:org.user_count||0, label:'users'},
             {icon:'layout-grid', val:org.module_count||0, label:'modules'},
             {icon:'globe', val:org.domain_count||0, label:'domains'}].forEach(function(s) {
                var stat = document.createElement('div');
                stat.className = 'saas-org-card-stat';
                stat.innerHTML = '<i data-lucide="' + s.icon + '" style="width:14px;height:14px"></i>';
                var span = document.createElement('span');
                span.textContent = s.val;
                stat.appendChild(span);
                stat.appendChild(document.createTextNode(' ' + s.label));
                statsDiv.appendChild(stat);
            });

            // Node badge
            if (org.node_name) {
                var nodeBadge = document.createElement('div');
                nodeBadge.style.cssText = 'display:flex;align-items:center;gap:4px;margin-top:6px;font-size:11px;color:var(--archie-success);';
                var nbIcon = document.createElement('i');
                nbIcon.setAttribute('data-lucide', 'server');
                nbIcon.style.cssText = 'width:12px;height:12px';
                nodeBadge.appendChild(nbIcon);
                var nbText = document.createElement('span');
                nbText.textContent = 'Node: ' + org.node_name;
                nodeBadge.appendChild(nbText);
                var nbDot = document.createElement('span');
                nbDot.style.cssText = 'width:6px;height:6px;border-radius:50%;display:inline-block;margin-left:4px;background:' + (org.node_status === 'online' ? 'var(--archie-success)' : 'var(--archie-text-muted)') + ';';
                nodeBadge.appendChild(nbDot);
                card.appendChild(nameDiv);
                card.appendChild(nodeBadge);
            } else {
                card.appendChild(nameDiv);
            }
            card.appendChild(statsDiv);
            grid.appendChild(card);
        });

        if (typeof lucide !== 'undefined') lucide.createIcons();
        document.getElementById('saas-org-count').textContent = saasAllOrgs.length;
    }

    function saasUpdateStats() {
        document.getElementById('saas-stat-orgs').textContent = saasAllOrgs.length;
        var headerStat = document.getElementById('stat-orgs');
        if (headerStat) headerStat.textContent = saasAllOrgs.length;

        var totalDomains = 0, totalModules = 0;
        saasAllOrgs.forEach(function(o) {
            totalDomains += (o.domain_count || 0);
            totalModules += (o.module_count || 0);
        });
        document.getElementById('saas-stat-domains').textContent = totalDomains;
        document.getElementById('saas-stat-modules').textContent = totalModules;
    }

    // ── Org Detail Panel ────────────────────────────────────────────────────

    window.saasOpenOrgDetail = function(orgId) {
        saasCurrentOrgId = orgId;
        document.getElementById('saas-detail-overlay').classList.add('active');
        document.getElementById('saas-detail-panel').classList.add('open');
        document.getElementById('saas-detail-loading').style.display = 'flex';
        document.getElementById('saas-detail-content').style.display = 'none';

        fetch(SAAS_API + '/orgs/' + orgId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                document.getElementById('saas-detail-loading').style.display = 'none';
                if (!data.success) {
                    saasShowToast('Failed to load org details', 'error');
                    return;
                }
                document.getElementById('saas-detail-content').style.display = 'block';
                document.getElementById('saas-detail-org-name').textContent = data.org.name;
                saasRenderDetailUsers(data.users || []);
                saasRenderDetailModules(data.modules || [], orgId);
                saasRenderDetailDomains(data.domains || [], orgId);
                saasRenderDetailNode(data.node, data.org, orgId);
                // Set org default theme dropdown
                var orgSettings = data.org.settings || {};
                var orgTheme = (typeof orgSettings === 'string' ? JSON.parse(orgSettings) : orgSettings).default_theme || 'lcars-classic';
                var themeSelect = document.getElementById('saas-org-theme-select');
                if (themeSelect) themeSelect.value = orgTheme;
                if (typeof lucide !== 'undefined') lucide.createIcons();
            })
            .catch(function(err) {
                document.getElementById('saas-detail-loading').style.display = 'none';
                saasShowToast('Error: ' + err.message, 'error');
            });
    };

    window.saasCloseDetailPanel = function() {
        document.getElementById('saas-detail-overlay').classList.remove('active');
        document.getElementById('saas-detail-panel').classList.remove('open');
        saasCurrentOrgId = null;
    };

    window.saasUpdateOrgTheme = function(theme) {
        if (!saasCurrentOrgId) return;
        fetch(SAAS_API + '/orgs/' + saasCurrentOrgId, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({settings: {default_theme: theme}})
        })
        .then(function(r) { return r.json(); })
        .catch(function() { return {success: false}; })
        .then(function(data) {
            if (data.success) {
                saasShowToast('Default theme updated', 'success');
            } else {
                saasShowToast('Failed to update theme', 'error');
            }
        });
    };

    function saasRenderDetailUsers(users) {
        var container = document.getElementById('saas-detail-users');
        container.textContent = '';
        if (users.length === 0) {
            var emptyDiv = document.createElement('div');
            emptyDiv.className = 'saas-empty-state';
            emptyDiv.style.padding = 'var(--archie-space-4)';
            emptyDiv.textContent = 'No users assigned';
            container.appendChild(emptyDiv);
            return;
        }
        users.forEach(function(u) {
            var item = document.createElement('div');
            item.className = 'saas-user-list-item';

            var info = document.createElement('div');
            info.className = 'saas-user-list-info';
            var nameSpan = document.createElement('span');
            nameSpan.className = 'saas-user-list-name';
            nameSpan.textContent = u.username || u.email || 'User #' + u.user_id;
            var roleSpan = document.createElement('span');
            roleSpan.className = 'saas-user-list-role';
            roleSpan.textContent = u.role || 'member';
            info.appendChild(nameSpan);
            info.appendChild(roleSpan);
            item.appendChild(info);

            if (u.role !== 'archie') {
                var btn = document.createElement('button');
                btn.className = 'btn btn-ghost btn-sm';
                btn.title = 'Remove user';
                btn.setAttribute('onclick', 'saasRemoveOrgUser(' + saasCurrentOrgId + ', ' + u.user_id + ')');
                btn.innerHTML = '<i data-lucide="user-minus" style="width:14px;height:14px;color:var(--archie-danger)"></i>';
                item.appendChild(btn);
            }
            container.appendChild(item);
        });
    }

    function saasRenderDetailModules(orgModules, orgId) {
        var container = document.getElementById('saas-detail-modules');
        container.textContent = '';
        var enabledKeys = {};
        orgModules.forEach(function(m) { if (m.enabled) enabledKeys[m.module_key] = true; });

        if (saasAllModules.length === 0) {
            container.textContent = 'Loading modules...';
            return;
        }

        saasAllModules.forEach(function(mod) {
            var label = document.createElement('label');
            label.className = 'saas-module-check-item';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = !!enabledKeys[mod.key];
            cb.setAttribute('onchange', 'saasToggleModule(' + orgId + ', \'' + mod.key + '\', this.checked)');
            label.appendChild(cb);
            label.appendChild(document.createTextNode(' ' + mod.name));
            container.appendChild(label);
        });
    }

    function saasRenderDetailDomains(domains, orgId) {
        var container = document.getElementById('saas-detail-domains');
        container.textContent = '';
        if (domains.length === 0) {
            var emptyDiv = document.createElement('div');
            emptyDiv.className = 'saas-empty-state';
            emptyDiv.style.padding = 'var(--archie-space-4)';
            emptyDiv.textContent = 'No domains configured';
            container.appendChild(emptyDiv);
            return;
        }
        domains.forEach(function(d) {
            var item = document.createElement('div');
            item.className = 'saas-domain-list-item';
            var nameSpan = document.createElement('span');
            nameSpan.className = 'saas-domain-name';
            nameSpan.textContent = d.domain;
            item.appendChild(nameSpan);

            var actionsDiv = document.createElement('div');
            actionsDiv.style.cssText = 'display:flex;align-items:center;gap:var(--archie-space-2);';
            var badge = document.createElement('span');
            badge.className = 'badge badge-' + saasGetBadgeClass(d.dns_status);
            badge.textContent = d.dns_status || 'pending';
            actionsDiv.appendChild(badge);
            var btn = document.createElement('button');
            btn.className = 'btn btn-ghost btn-sm';
            btn.title = 'Remove domain';
            btn.setAttribute('onclick', 'saasRemoveDomain(' + orgId + ', ' + d.id + ')');
            btn.innerHTML = '<i data-lucide="trash-2" style="width:14px;height:14px;color:var(--archie-danger)"></i>';
            actionsDiv.appendChild(btn);
            item.appendChild(actionsDiv);
            container.appendChild(item);
        });
    }

    // ── Node Assignment ─────────────────────────────────────────────────────

    function saasRenderDetailNode(node, org, orgId) {
        var container = document.getElementById('saas-detail-node');
        container.textContent = '';

        if (!node) {
            // No node assigned - show shared info + assign button
            var wrapper = document.createElement('div');
            wrapper.style.cssText = 'padding:var(--archie-space-4);';

            var shared = document.createElement('div');
            shared.style.cssText = 'color:var(--archie-text-muted);margin-bottom:var(--archie-space-3);font-size:13px;';
            shared.textContent = 'Running on shared infrastructure';
            wrapper.appendChild(shared);

            var btn = document.createElement('button');
            btn.className = 'btn btn-sm';
            btn.style.cssText = 'background:var(--archie-accent);color:#000;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;';
            btn.textContent = 'Assign Node';
            btn.setAttribute('onclick', 'saasShowAssignNodeModal(' + orgId + ')');
            wrapper.appendChild(btn);
            container.appendChild(wrapper);
            return;
        }

        // Node assigned - show card with info
        var card = document.createElement('div');
        card.style.cssText = 'padding:var(--archie-space-3);background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:8px;';

        var header = document.createElement('div');
        header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;';

        var nameGroup = document.createElement('div');
        nameGroup.style.cssText = 'display:flex;align-items:center;gap:8px;';
        var icon = document.createElement('i');
        icon.setAttribute('data-lucide', 'server');
        icon.style.cssText = 'width:16px;height:16px;color:var(--archie-accent)';
        nameGroup.appendChild(icon);
        var name = document.createElement('span');
        name.style.cssText = 'font-weight:600;font-size:14px;';
        name.textContent = node.node_name || node.node_id;
        nameGroup.appendChild(name);

        var dot = document.createElement('span');
        var isOnline = node.status === 'online';
        dot.style.cssText = 'width:8px;height:8px;border-radius:50%;display:inline-block;background:' + (isOnline ? 'var(--archie-success)' : 'var(--archie-danger)') + ';';
        nameGroup.appendChild(dot);

        var statusText = document.createElement('span');
        statusText.style.cssText = 'font-size:11px;color:' + (isOnline ? 'var(--archie-success)' : 'var(--archie-danger)') + ';';
        statusText.textContent = node.status || 'unknown';
        nameGroup.appendChild(statusText);
        header.appendChild(nameGroup);

        var unassignBtn = document.createElement('button');
        unassignBtn.className = 'btn btn-ghost btn-sm';
        unassignBtn.style.cssText = 'color:var(--archie-danger);font-size:11px;';
        unassignBtn.textContent = 'Unassign';
        unassignBtn.setAttribute('onclick', 'saasUnassignNode(' + orgId + ')');
        header.appendChild(unassignBtn);
        card.appendChild(header);

        // Hardware specs grid
        var specs = document.createElement('div');
        specs.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:12px;color:var(--archie-text-muted);';
        var specItems = [
            {label: 'IP', value: node.vpn_ip || '-'},
            {label: 'GPU', value: (node.gpu_model || 'None') + (node.gpu_vram_gb ? ' (' + node.gpu_vram_gb + 'GB)' : '')},
            {label: 'CPU', value: (node.cpu_cores || '?') + ' cores'},
            {label: 'RAM', value: (node.ram_gb || '?') + ' GB'},
        ];
        specItems.forEach(function(s) {
            var div = document.createElement('div');
            var lbl = document.createElement('span');
            lbl.style.cssText = 'color:var(--archie-text-muted);opacity:0.6;';
            lbl.textContent = s.label + ': ';
            div.appendChild(lbl);
            div.appendChild(document.createTextNode(s.value));
            specs.appendChild(div);
        });
        card.appendChild(specs);

        // Load bar
        if (node.current_load !== null && node.current_load !== undefined) {
            var loadWrap = document.createElement('div');
            loadWrap.style.cssText = 'margin-top:10px;';
            var loadLabel = document.createElement('div');
            loadLabel.style.cssText = 'font-size:11px;color:var(--archie-text-muted);margin-bottom:4px;display:flex;justify-content:space-between;';
            loadLabel.textContent = 'Load';
            var loadVal = document.createElement('span');
            loadVal.textContent = node.current_load + '%';
            loadLabel.appendChild(loadVal);
            loadWrap.appendChild(loadLabel);
            var loadBar = document.createElement('div');
            loadBar.style.cssText = 'height:4px;background:rgba(255,255,255,0.1);border-radius:2px;overflow:hidden;';
            var loadFill = document.createElement('div');
            var loadPct = Math.min(100, Math.max(0, node.current_load));
            var loadColor = loadPct > 80 ? 'var(--archie-danger)' : loadPct > 50 ? 'var(--archie-warning)' : 'var(--archie-success)';
            loadFill.style.cssText = 'height:100%;width:' + loadPct + '%;background:' + loadColor + ';border-radius:2px;transition:width 0.3s;';
            loadBar.appendChild(loadFill);
            loadWrap.appendChild(loadBar);
            card.appendChild(loadWrap);
        }

        // Last heartbeat
        if (node.last_heartbeat) {
            var hbDiv = document.createElement('div');
            hbDiv.style.cssText = 'margin-top:8px;font-size:11px;color:var(--archie-text-muted);opacity:0.6;';
            hbDiv.textContent = 'Last heartbeat: ' + ArchieTime.format(node.last_heartbeat, 'short');
            card.appendChild(hbDiv);
        }

        container.appendChild(card);
    }

    window.saasShowAssignNodeModal = function(orgId) {
        // Fetch available nodes and show selection
        fetch(SAAS_API + '/nodes')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success || !data.nodes || data.nodes.length === 0) {
                    saasShowToast('No approved nodes available', 'warning');
                    return;
                }
                // Filter to unassigned nodes
                var available = data.nodes.filter(function(n) { return !n.assigned_org_id; });
                if (available.length === 0) {
                    saasShowToast('All nodes are assigned to other orgs', 'warning');
                    return;
                }
                // Simple prompt-based selection (can be enhanced to modal later)
                var msg = 'Available nodes:\\n';
                available.forEach(function(n, i) {
                    msg += (i + 1) + '. ' + n.node_name + ' (' + (n.vpn_ip || 'no IP') + ') - ' + (n.gpu_model || 'no GPU') + '\\n';
                });
                msg += '\\nEnter number to assign:';
                var choice = prompt(msg);
                if (!choice) return;
                var idx = parseInt(choice, 10) - 1;
                if (idx < 0 || idx >= available.length) {
                    saasShowToast('Invalid selection', 'error');
                    return;
                }
                var selectedNode = available[idx];
                fetch(SAAS_API + '/orgs/' + orgId + '/node', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ node_id: selectedNode.node_id })
                })
                .then(function(r) { return r.json(); })
                .then(function(res) {
                    if (res.success) {
                        saasShowToast('Node assigned: ' + selectedNode.node_name, 'success');
                        saasOpenOrgDetail(orgId);
                        saasLoadOrgs();
                    } else {
                        saasShowToast('Failed: ' + (res.error || ''), 'error');
                    }
                });
            })
            .catch(function(err) { saasShowToast('Error: ' + err.message, 'error'); });
    };

    window.saasUnassignNode = function(orgId) {
        if (!confirm('Unassign this node? The org will revert to shared infrastructure.')) return;
        fetch(SAAS_API + '/orgs/' + orgId + '/node', { method: 'DELETE' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) {
                    saasShowToast('Node unassigned', 'success');
                    saasOpenOrgDetail(orgId);
                    saasLoadOrgs();
                } else {
                    saasShowToast('Failed: ' + (data.error || ''), 'error');
                }
            })
            .catch(function(err) { saasShowToast('Error: ' + err.message, 'error'); });
    };

    // ── Module Toggle ───────────────────────────────────────────────────────

    window.saasToggleModule = function(orgId, moduleKey, enabled) {
        fetch(SAAS_API + '/orgs/' + orgId + '/modules', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ module_key: moduleKey, enabled: enabled })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.success) {
                saasShowToast('Failed to toggle module: ' + (data.error || ''), 'error');
                return;
            }
            saasShowToast('Module ' + (enabled ? 'enabled' : 'disabled'), 'success');
            saasLoadOrgs();
        })
        .catch(function(err) { saasShowToast('Error: ' + err.message, 'error'); });
    };

    // ── Remove User from Org ────────────────────────────────────────────────

    window.saasRemoveOrgUser = function(orgId, userId) {
        if (!confirm('Remove this user from the organization?')) return;
        fetch(SAAS_API + '/orgs/' + orgId + '/users/' + userId, { method: 'DELETE' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) {
                    saasShowToast('Failed to remove user: ' + (data.error || ''), 'error');
                    return;
                }
                saasShowToast('User removed', 'success');
                saasOpenOrgDetail(orgId);
                saasLoadOrgs();
            })
            .catch(function(err) { saasShowToast('Error: ' + err.message, 'error'); });
    };

    // ── Remove Domain ───────────────────────────────────────────────────────

    window.saasRemoveDomain = function(orgId, domainId) {
        if (!confirm('Remove this domain?')) return;
        fetch(SAAS_API + '/orgs/' + orgId + '/domains/' + domainId, { method: 'DELETE' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) {
                    saasShowToast('Failed to remove domain: ' + (data.error || ''), 'error');
                    return;
                }
                saasShowToast('Domain removed', 'success');
                if (saasCurrentOrgId) saasOpenOrgDetail(saasCurrentOrgId);
                saasLoadOrgs();
            })
            .catch(function(err) { saasShowToast('Error: ' + err.message, 'error'); });
    };

    // ── New Organization Modal ──────────────────────────────────────────────

    window.saasShowNewOrgModal = function() {
        document.getElementById('saas-new-org-modal').classList.add('active');
        document.getElementById('saas-new-org-name').value = '';

        var modulesDiv = document.getElementById('saas-new-org-modules');
        modulesDiv.textContent = '';
        saasAllModules.forEach(function(mod) {
            var label = document.createElement('label');
            label.className = 'saas-module-check-item';
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = mod.key;
            label.appendChild(cb);
            label.appendChild(document.createTextNode(' ' + mod.name));
            modulesDiv.appendChild(label);
        });

        api('/tools/account-center/api/users?limit=100')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var select = document.getElementById('saas-new-org-owner');
                select.textContent = '';
                var defaultOpt = document.createElement('option');
                defaultOpt.value = '';
                defaultOpt.textContent = 'Select owner...';
                select.appendChild(defaultOpt);
                var users = data.users || [];
                users.forEach(function(u) {
                    var opt = document.createElement('option');
                    opt.value = u.id;
                    opt.textContent = u.username || u.email;
                    select.appendChild(opt);
                });
            })
            .catch(function() {});

        if (typeof lucide !== 'undefined') lucide.createIcons();
    };

    window.saasCloseNewOrgModal = function() {
        document.getElementById('saas-new-org-modal').classList.remove('active');
    };

    window.saasCreateOrg = function() {
        var name = document.getElementById('saas-new-org-name').value.trim();
        if (!name) {
            saasShowToast('Organization name is required', 'error');
            return;
        }

        var ownerId = document.getElementById('saas-new-org-owner').value;
        var selectedModules = [];
        document.querySelectorAll('#saas-new-org-modules input[type="checkbox"]:checked').forEach(function(cb) {
            selectedModules.push(cb.value);
        });

        var btn = document.getElementById('saas-btn-create-org');
        btn.disabled = true;
        btn.textContent = 'Creating...';

        fetch(SAAS_API + '/orgs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                owner_user_id: ownerId ? parseInt(ownerId) : null,
                settings: {},
                ai_config: {}
            })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            btn.disabled = false;
            btn.textContent = 'Create Organization';

            if (!data.success) {
                saasShowToast('Failed: ' + (data.error || 'Unknown error'), 'error');
                return;
            }

            var orgId = data.org.id;
            var modulePromises = selectedModules.map(function(key) {
                return fetch(SAAS_API + '/orgs/' + orgId + '/modules', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ module_key: key, enabled: true })
                });
            });

            Promise.all(modulePromises).then(function() {
                saasShowToast('Organization "' + name + '" created', 'success');
                saasCloseNewOrgModal();
                saasLoadOrgs();
            });
        })
        .catch(function(err) {
            btn.disabled = false;
            btn.textContent = 'Create Organization';
            saasShowToast('Error: ' + err.message, 'error');
        });
    };

    // ── Domains Sub-Tab ─────────────────────────────────────────────────────

    function saasLoadAllDomains() {
        document.getElementById('saas-domains-loading').style.display = 'flex';
        document.getElementById('saas-domains-table-wrap').style.display = 'none';
        document.getElementById('saas-domains-empty').style.display = 'none';

        fetch(SAAS_API + '/orgs')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) return;
                var orgs = data.orgs || [];
                var domainPromises = orgs.map(function(o) {
                    return fetch(SAAS_API + '/orgs/' + o.id)
                        .then(function(r) { return r.json(); })
                        .then(function(detail) {
                            return { org: o, domains: detail.domains || [] };
                        });
                });
                return Promise.all(domainPromises);
            })
            .then(function(results) {
                document.getElementById('saas-domains-loading').style.display = 'none';
                if (!results) return;

                var allDomains = [];
                results.forEach(function(r) {
                    r.domains.forEach(function(d) {
                        d._orgName = r.org.name;
                        d._orgId = r.org.id;
                        allDomains.push(d);
                    });
                });

                if (allDomains.length === 0) {
                    document.getElementById('saas-domains-empty').style.display = 'block';
                    return;
                }

                document.getElementById('saas-domains-table-wrap').style.display = 'block';
                var tbody = document.getElementById('saas-domains-tbody');
                tbody.textContent = '';

                allDomains.forEach(function(d) {
                    var tr = document.createElement('tr');

                    var td1 = document.createElement('td');
                    var domSpan = document.createElement('span');
                    domSpan.className = 'saas-domain-name';
                    domSpan.textContent = d.domain;
                    td1.appendChild(domSpan);

                    var td2 = document.createElement('td');
                    td2.textContent = d._orgName;

                    var td3 = document.createElement('td');
                    td3.textContent = d.target_module || '-';

                    var td4 = document.createElement('td');
                    var dnsBadge = document.createElement('span');
                    dnsBadge.className = 'badge badge-' + saasGetBadgeClass(d.dns_status);
                    dnsBadge.textContent = d.dns_status || 'pending';
                    td4.appendChild(dnsBadge);

                    var td5 = document.createElement('td');
                    var sslBadge = document.createElement('span');
                    sslBadge.className = 'badge badge-' + saasGetBadgeClass(d.ssl_status);
                    sslBadge.textContent = d.ssl_status || 'pending';
                    td5.appendChild(sslBadge);

                    var td6 = document.createElement('td');
                    var btnDiv = document.createElement('div');
                    btnDiv.style.cssText = 'display:flex;gap:var(--archie-space-2);';
                    var verifyBtn = document.createElement('button');
                    verifyBtn.className = 'btn btn-ghost btn-sm';
                    verifyBtn.title = 'Verify DNS';
                    verifyBtn.setAttribute('onclick', 'saasVerifyDns(' + d._orgId + ', ' + d.id + ')');
                    verifyBtn.innerHTML = '<i data-lucide="search-check" style="width:14px;height:14px"></i> Verify';
                    var removeBtn = document.createElement('button');
                    removeBtn.className = 'btn btn-ghost btn-sm';
                    removeBtn.title = 'Remove';
                    removeBtn.setAttribute('onclick', 'saasRemoveDomain(' + d._orgId + ', ' + d.id + ')');
                    removeBtn.innerHTML = '<i data-lucide="trash-2" style="width:14px;height:14px;color:var(--archie-danger)"></i>';
                    btnDiv.appendChild(verifyBtn);
                    btnDiv.appendChild(removeBtn);
                    td6.appendChild(btnDiv);

                    tr.appendChild(td1);
                    tr.appendChild(td2);
                    tr.appendChild(td3);
                    tr.appendChild(td4);
                    tr.appendChild(td5);
                    tr.appendChild(td6);
                    tbody.appendChild(tr);
                });

                if (typeof lucide !== 'undefined') lucide.createIcons();
            })
            .catch(function(err) {
                document.getElementById('saas-domains-loading').style.display = 'none';
                saasShowToast('Error loading domains: ' + err.message, 'error');
            });
    }

    window.saasVerifyDns = function(orgId, domainId) {
        fetch(SAAS_API + '/orgs/' + orgId + '/domains/' + domainId + '/verify', { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) {
                    saasShowToast('DNS: ' + (data.dns_status || 'checked'), 'success');
                    saasLoadAllDomains();
                } else {
                    saasShowToast('Verification failed: ' + (data.error || ''), 'error');
                }
            })
            .catch(function(err) { saasShowToast('Error: ' + err.message, 'error'); });
    };

    // ── Add Domain Modal ────────────────────────────────────────────────────

    window.saasShowAddDomainModal = function() {
        document.getElementById('saas-add-domain-modal').classList.add('active');
        document.getElementById('saas-domain-name').value = '';

        var orgSelect = document.getElementById('saas-domain-org-select');
        orgSelect.textContent = '';
        var defaultOpt = document.createElement('option');
        defaultOpt.value = '';
        defaultOpt.textContent = 'Select organization...';
        orgSelect.appendChild(defaultOpt);
        saasAllOrgs.forEach(function(o) {
            var opt = document.createElement('option');
            opt.value = o.id;
            opt.textContent = o.name;
            orgSelect.appendChild(opt);
        });

        var modSelect = document.getElementById('saas-domain-target-module');
        modSelect.textContent = '';
        var modDefault = document.createElement('option');
        modDefault.value = '';
        modDefault.textContent = 'Select module...';
        modSelect.appendChild(modDefault);
        saasAllModules.forEach(function(m) {
            var opt = document.createElement('option');
            opt.value = m.key;
            opt.textContent = m.name;
            modSelect.appendChild(opt);
        });
    };

    window.saasCloseAddDomainModal = function() {
        document.getElementById('saas-add-domain-modal').classList.remove('active');
    };

    window.saasAddDomain = function() {
        var orgId = document.getElementById('saas-domain-org-select').value;
        var domain = document.getElementById('saas-domain-name').value.trim();
        var targetModule = document.getElementById('saas-domain-target-module').value;

        if (!orgId || !domain) {
            saasShowToast('Organization and domain name are required', 'error');
            return;
        }

        var btn = document.getElementById('saas-btn-add-domain');
        btn.disabled = true;
        btn.textContent = 'Adding...';

        fetch(SAAS_API + '/orgs/' + orgId + '/domains', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ domain: domain, target_module: targetModule || null })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            btn.disabled = false;
            btn.textContent = 'Add Domain';

            if (!data.success) {
                saasShowToast('Failed: ' + (data.error || 'Unknown error'), 'error');
                return;
            }
            saasShowToast('Domain "' + domain + '" added', 'success');
            saasCloseAddDomainModal();
            saasLoadAllDomains();
            saasLoadOrgs();
        })
        .catch(function(err) {
            btn.disabled = false;
            btn.textContent = 'Add Domain';
            saasShowToast('Error: ' + err.message, 'error');
        });
    };

    // ── Available Modules ───────────────────────────────────────────────────

    function saasLoadAvailableModules() {
        fetch(SAAS_API + '/available-modules')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.success) saasAllModules = data.modules || [];
            })
            .catch(function() {});
    }

    // ── Network Sub-Tab ─────────────────────────────────────────────────────

    function saasLoadNetworkInfo() {
        fetch(SAAS_API + '/network/public-ip')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.success) {
                    document.getElementById('saas-network-public-ip').textContent = 'Error';
                    return;
                }

                document.getElementById('saas-network-public-ip').textContent = data.current_ip;
                document.getElementById('saas-stat-ip').textContent = data.current_ip;

                if (data.changed) {
                    document.getElementById('saas-ip-changed-notice').style.display = 'block';
                } else {
                    document.getElementById('saas-ip-changed-notice').style.display = 'none';
                }

                var tbody = document.getElementById('saas-ip-history-tbody');
                var history = data.history || [];
                tbody.textContent = '';
                if (history.length === 0) {
                    var tr = document.createElement('tr');
                    var td = document.createElement('td');
                    td.colSpan = 2;
                    td.style.cssText = 'text-align:center;color:var(--archie-text-muted)';
                    td.textContent = 'No history';
                    tr.appendChild(td);
                    tbody.appendChild(tr);
                } else {
                    history.forEach(function(h) {
                        var tr = document.createElement('tr');
                        var td1 = document.createElement('td');
                        td1.textContent = saasFormatDate(h.detected_at);
                        var td2 = document.createElement('td');
                        var ipSpan = document.createElement('span');
                        ipSpan.className = 'saas-domain-name';
                        ipSpan.textContent = h.ip_address;
                        td2.appendChild(ipSpan);
                        tr.appendChild(td1);
                        tr.appendChild(td2);
                        tbody.appendChild(tr);
                    });
                }
            })
            .catch(function() {
                document.getElementById('saas-network-public-ip').textContent = 'Unavailable';
                document.getElementById('saas-stat-ip').textContent = '?';
            });
    }

    window.saasCheckPorts = function() {
        var btn = document.getElementById('saas-btn-check-ports');
        btn.disabled = true;

        document.getElementById('saas-port-80-status').textContent = 'Checking...';
        document.getElementById('saas-port-80-status').className = 'saas-port-card-status saas-port-unknown';
        document.getElementById('saas-port-443-status').textContent = 'Checking...';
        document.getElementById('saas-port-443-status').className = 'saas-port-card-status saas-port-unknown';

        fetch(SAAS_API + '/network/check-ports', { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                btn.disabled = false;
                if (!data.success) {
                    saasShowToast('Port check failed', 'error');
                    return;
                }
                var ports = data.ports || {};
                [80, 443].forEach(function(port) {
                    var el = document.getElementById('saas-port-' + port + '-status');
                    var info = ports[port];
                    if (info && info.open) {
                        el.textContent = 'Open (HTTP ' + info.status + ')';
                        el.className = 'saas-port-card-status saas-port-open';
                    } else {
                        el.textContent = 'Closed';
                        el.className = 'saas-port-card-status saas-port-closed';
                    }
                });
            })
            .catch(function(err) {
                btn.disabled = false;
                saasShowToast('Error: ' + err.message, 'error');
            });
    };

    // ── Helpers ─────────────────────────────────────────────────────────────

    function saasGetBadgeClass(status) {
        if (!status) return 'pending';
        var s = status.toLowerCase();
        if (s === 'verified' || s === 'active' || s === 'issued') return 'verified';
        if (s === 'pending') return 'pending';
        if (s === 'failed') return 'failed';
        return 'unknown';
    }

    function saasFormatDate(isoStr) {
        if (!isoStr) return '-';
        return ArchieTime.format(isoStr, 'datetime');
    }

    function saasShowToast(message, type) {
        var container = document.querySelector('.flash-messages');
        if (!container) {
            container = document.createElement('div');
            container.className = 'flash-messages';
            document.body.appendChild(container);
        }
        var flash = document.createElement('div');
        flash.className = 'flash ' + (type || 'info');
        flash.textContent = '> ' + message;
        container.appendChild(flash);
        setTimeout(function() { flash.remove(); }, 4000);
    }

})();


// ────────────────────────────────────────────────────────────────────────────
// Click dispatcher: routes elements with [data-action] to their window functions.
// Supports: data-action="functionName" (no-arg), data-action="fn" data-arg="..."
// Numeric args are converted via Number(); non-numeric are passed as strings.
// Custom actions (non-function) live in ACCOUNT_CENTER_CUSTOM_ACTIONS below.
// ────────────────────────────────────────────────────────────────────────────
const ACCOUNT_CENTER_CUSTOM_ACTIONS = {
    'focus-pending-tab': function() {
        var el = document.querySelector('[data-tab=pending]');
        if (el) el.click();
    },
    'trigger-import-file': function() {
        var el = document.getElementById('import-file');
        if (el) el.click();
    },
};

document.addEventListener('click', function(e) {
    var el = e.target.closest && e.target.closest('[data-action]');
    if (!el) return;
    var action = el.dataset.action;
    if (!action) return;
    var custom = ACCOUNT_CENTER_CUSTOM_ACTIONS[action];
    if (custom) { custom(e, el); return; }
    var fn = window[action];
    if (typeof fn !== 'function') return;
    var raw = el.dataset.arg;
    if (raw === undefined) { fn(e, el); return; }
    var n = Number(raw);
    fn((raw !== '' && !isNaN(n)) ? n : raw);
});

// ---------------------------------------------------------------------------
// Overview, tab navigation, invite system — extracted from inline scripts
// ---------------------------------------------------------------------------

const _origFetch = window.fetch;
window.fetch = function(url, opts) {
    if (typeof url === 'string' && url.includes('/tools/account-center/api/users') && !url.includes('/api/users/')) {
        const statusEl = document.getElementById('filter-status');
        if (statusEl && !url.includes('status=')) {
            url = url + (url.includes('?') ? '&' : '?') + 'status=' + encodeURIComponent(statusEl.value);
        }
    }
    return _origFetch.call(this, url, opts);
};

document.addEventListener('DOMContentLoaded', () => {
    const statusEl = document.getElementById('filter-status');
    if (statusEl) statusEl.addEventListener('change', () => { if (typeof loadUsers === 'function') loadUsers(); });
});

const _editObserver = new MutationObserver(() => {
    document.querySelectorAll('#users-table-body .btn-sm:not(.btn-danger)').forEach(btn => {
        if (btn.textContent.trim() === 'Edit') btn.style.display = 'none';
    });
});
document.addEventListener('DOMContentLoaded', () => {
    const tbody = document.getElementById('users-table-body');
    if (tbody) _editObserver.observe(tbody, { childList: true, subtree: true });
});

function acGoToTab(tabId) {
    const btn = document.querySelector('[data-tab="' + tabId + '"]');
    if (btn) {
        btn.click();
    } else {
        switchAccountTab(tabId);
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function esc(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
}

function mkEl(tag, styles, text) {
    const el = document.createElement(tag);
    if (styles) Object.assign(el.style, styles);
    if (text !== undefined) el.textContent = text;
    return el;
}

async function loadOverview() {
    try {
        const r = await fetch('/tools/account-center/api/overview');
        const d = await r.json();

        const alertsWrap = document.getElementById('overview-alerts');
        const alertsList = document.getElementById('alerts-list');
        if (d.alerts && d.alerts.length > 0) {
            alertsWrap.style.display = 'block';
            alertsList.textContent = '';
            d.alerts.forEach(a => {
                const div = mkEl('div', {background:'rgba(239,68,68,0.15)', border:'1px solid var(--archie-red)', borderRadius:'8px', padding:'10px 14px', marginBottom:'8px', color:'var(--archie-red)'});
                div.textContent = '⚠ ' + a.message;
                alertsList.appendChild(div);
            });
        }

        const humanUsers = (d.active_users || []).filter(u => !u.is_system);
        const systemUsers = (d.active_users || []).filter(u => u.is_system);

        const statsRow = document.getElementById('overview-stats-row');
        if (statsRow) {
            statsRow.querySelector('#ov-active').textContent = d.active_users.length;
            statsRow.querySelector('#ov-sessions').textContent = d.active_sessions;
            statsRow.querySelector('#ov-failed').textContent = d.failed_logins_24h;
        }

        const grid = document.getElementById('overview-users-grid');
        grid.textContent = '';
        humanUsers.forEach(u => {
            const card = mkEl('div', {background:'var(--archie-bg-secondary)', border:'1px solid rgba(0,255,255,0.2)', borderRadius:'10px', padding:'16px', display:'flex', alignItems:'center', gap:'14px'});
            const avatar = mkEl('div', {width:'44px', height:'44px', borderRadius:'50%', background:'var(--archie-cyan)', display:'flex', alignItems:'center', justifyContent:'center', fontFamily:'Antonio,sans-serif', fontWeight:'700', color:'var(--archie-bg-primary)', flexShrink:'0'});
            avatar.textContent = (u.username || '?').slice(0,2).toUpperCase();
            const info = mkEl('div', {minWidth:'0'});
            const name = mkEl('div', {fontWeight:'600', color:'var(--archie-text-primary)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}, u.username);
            const email = mkEl('div', {fontSize:'0.75rem', color:'var(--archie-text-secondary)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}, u.email);
            const meta = mkEl('div', {fontSize:'0.72rem', marginTop:'4px', display:'flex', gap:'8px'});
            const badge = mkEl('span', {color:'var(--archie-cyan)'}, u.is_admin ? 'Admin' : 'User');
            const lastSeen = mkEl('span', {color:'var(--archie-text-secondary)'}, 'Last: ' + u.last_login_display);
            meta.appendChild(badge); meta.appendChild(lastSeen);
            info.appendChild(name); info.appendChild(email); info.appendChild(meta);
            card.appendChild(avatar); card.appendChild(info);
            grid.appendChild(card);
        });
        if (!humanUsers.length) grid.textContent = 'No human accounts found.';

        const sysGrid = document.getElementById('overview-system-grid');
        sysGrid.textContent = '';
        if (systemUsers.length > 0) {
            systemUsers.forEach(u => {
                const card = mkEl('div', {background:'var(--archie-bg-secondary)', border:'1px solid rgba(139,92,246,0.3)', borderRadius:'10px', padding:'16px', display:'flex', alignItems:'center', gap:'14px'});
                const avatar = mkEl('div', {width:'44px', height:'44px', borderRadius:'50%', background:'rgba(139,92,246,0.3)', display:'flex', alignItems:'center', justifyContent:'center', fontFamily:'Antonio,sans-serif', fontWeight:'700', color:'var(--archie-purple)', flexShrink:'0'});
                avatar.textContent = (u.username || '?').slice(0,2).toUpperCase();
                const info = mkEl('div', {minWidth:'0'});
                const name = mkEl('div', {fontWeight:'600', color:'var(--archie-text-primary)'}, u.username);
                const email = mkEl('div', {fontSize:'0.75rem', color:'var(--archie-text-secondary)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}, u.email);
                const meta = mkEl('span', {fontSize:'0.72rem', color:'var(--archie-purple)', marginTop:'4px', display:'block'}, 'System / Agent Account');
                info.appendChild(name); info.appendChild(email); info.appendChild(meta);
                card.appendChild(avatar); card.appendChild(info);
                sysGrid.appendChild(card);
            });
        } else {
            sysGrid.textContent = 'No system accounts active.';
        }

        const actEl = document.getElementById('overview-activity');
        actEl.textContent = '';
        if (d.recent_activity && d.recent_activity.length > 0) {
            const table = document.createElement('table');
            table.style.cssText = 'width:100%;border-collapse:collapse;';
            const thead = table.createTHead();
            const hr = thead.insertRow();
            ['User','Event','Time'].forEach(h => {
                const th = document.createElement('th');
                th.style.cssText = 'text-align:left;padding:6px 8px;color:var(--archie-text-secondary);font-size:0.75rem;text-transform:uppercase;letter-spacing:1px;';
                th.textContent = h;
                hr.appendChild(th);
            });
            const tbody = table.createTBody();
            d.recent_activity.forEach(a => {
                const row = tbody.insertRow();
                row.style.borderTop = '1px solid rgba(255,255,255,0.05)';
                const c1 = row.insertCell(); c1.style.padding = '8px'; c1.textContent = a.username;
                const c2 = row.insertCell(); c2.style.padding = '8px';
                const ok = a.action === 'login_success';
                const evSpan = mkEl('span', {color: ok ? 'var(--archie-green)' : 'var(--archie-red)'}, ok ? 'Login OK' : 'Failed');
                c2.appendChild(evSpan);
                const c3 = row.insertCell(); c3.style.cssText = 'padding:8px;color:var(--archie-text-secondary);font-size:0.82rem;'; c3.textContent = a.display;
            });
            actEl.appendChild(table);
        } else {
            actEl.textContent = 'No login activity in the last 48 hours.';
        }

        const sessEl = document.getElementById('stat-sessions');
        if (sessEl) sessEl.textContent = d.active_sessions;

    } catch(e) { console.error('Overview load error:', e); }
}

document.addEventListener('DOMContentLoaded', () => {
    loadOverview();
    document.querySelectorAll('[data-tab="overview"]').forEach(btn => {
        btn.addEventListener('click', loadOverview);
    });
});

async function acSendInvite(e) {
    e.preventDefault();
    const email = document.getElementById('inviteEmail').value.trim();
    const role = document.getElementById('inviteRole').value;
    const message = document.getElementById('inviteMessage').value.trim();
    const resultEl = document.getElementById('inviteResult');
    const linkBox = document.getElementById('inviteLinkBox');
    resultEl.style.display = 'none';
    linkBox.style.display = 'none';
    try {
        const res = await fetch('/tools/account-center/api/invites', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({email, role, subscription_tier: role, message: message || null})
        });
        const data = await res.json();
        resultEl.style.display = 'block';
        resultEl.style.padding = '8px 12px';
        resultEl.style.borderRadius = '6px';
        if (data.success) {
            resultEl.style.background = 'rgba(16,185,129,0.1)';
            resultEl.style.border = '1px solid #10b981';
            resultEl.style.color = '#10b981';
            resultEl.textContent = data.email_sent ? '✓ Invite sent to ' + email : '✓ Invite created (email unavailable). Share the link:';
            linkBox.style.display = 'block';
            linkBox.textContent = '';
            const label = mkEl('strong', {}, 'Invite Link: ');
            const link = mkEl('span', {wordBreak:'break-all'}, data.invite_link);
            const copyBtn = mkEl('button', {marginLeft:'6px', fontSize:'0.75rem', padding:'2px 8px', cursor:'pointer', borderRadius:'3px', border:'1px solid #7c3aed', background:'rgba(124,58,237,0.2)', color:'#7c3aed'}, 'Copy');
            const inviteLink = data.invite_link;
            copyBtn.addEventListener('click', () => navigator.clipboard.writeText(inviteLink));
            linkBox.appendChild(label); linkBox.appendChild(link); linkBox.appendChild(copyBtn);
        } else {
            resultEl.style.background = 'rgba(239,68,68,0.1)';
            resultEl.style.border = '1px solid #ef4444';
            resultEl.style.color = '#ef4444';
            resultEl.textContent = '✗ ' + (data.error || 'Failed');
        }
    } catch(err) { resultEl.style.display='block'; resultEl.textContent='✗ '+err.message; }
}

async function acLoadInvites() {
    const sec = document.getElementById('pendingInvitesSection');
    const list = document.getElementById('pendingInvitesList');
    sec.style.display = sec.style.display === 'none' ? 'block' : 'none';
    if (sec.style.display === 'none') return;
    list.textContent = '';
    const loading = mkEl('div', {color:'var(--archie-text-secondary)', fontSize:'0.85rem', padding:'8px 0'}, 'Loading...');
    list.appendChild(loading);
    try {
        const data = await fetch('/tools/account-center/api/invites').then(r => r.json());
        const pending = (data.invites || []).filter(i => i.status === 'pending');
        list.textContent = '';
        if (!pending.length) {
            list.appendChild(mkEl('div', {color:'var(--archie-text-secondary)', padding:'8px 0'}, 'No pending invitations.'));
            return;
        }
        pending.forEach(i => {
            const row = mkEl('div', {display:'flex', alignItems:'center', gap:'12px', padding:'8px 0', borderBottom:'1px solid var(--archie-border-subtle)'});
            row.appendChild(mkEl('span', {flex:'1', fontFamily:'monospace', fontSize:'0.85rem'}, i.email));
            row.appendChild(mkEl('span', {color:'var(--archie-text-secondary)', fontSize:'0.8rem', background:'rgba(124,58,237,0.15)', padding:'2px 8px', borderRadius:'3px'}, i.role));
            row.appendChild(mkEl('span', {color:'var(--archie-text-secondary)', fontSize:'0.75rem'}, 'exp. ' + new Date(i.expires_at).toLocaleDateString()));
            const revoke = mkEl('button', {background:'rgba(239,68,68,0.1)', color:'#ef4444', border:'1px solid rgba(239,68,68,0.4)', borderRadius:'4px', padding:'2px 8px', cursor:'pointer', fontSize:'0.75rem'}, 'Revoke');
            revoke.addEventListener('click', () => acRevokeInvite(i.id, revoke));
            row.appendChild(revoke);
            list.appendChild(row);
        });
    } catch(err) {
        list.textContent = '';
        list.appendChild(mkEl('div', {color:'#ef4444'}, 'Error: ' + err.message));
    }
}

async function acRevokeInvite(id, btn) {
    if (!confirm('Revoke this invitation?')) return;
    const data = await fetch('/tools/account-center/api/invites/' + id, {method:'DELETE'}).then(r => r.json());
    if (data.success) btn.closest('div').remove(); else alert(data.error);
}
