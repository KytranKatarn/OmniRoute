/**
 * Agent Badge System — Project #91
 * Shows assigned team member agent per module (top-left floating badge)
 * Polls /api/module-agents every 15s for real-time status
 */

(function() {
    'use strict';

    const POLL_INTERVAL = 15000; // 15 seconds
    let badgeEl = null;
    let currentModule = null;

    function getModuleName() {
        // Get from data-module attribute on body, or from URL path
        const body = document.querySelector('body');
        if (body && body.dataset.module && body.dataset.module !== 'default') {
            return body.dataset.module;
        }
        // Extract from URL: /tools/team-management → team_management
        const path = window.location.pathname;
        const match = path.match(/\/tools\/([^/]+)/);
        if (match) {
            return match[1].replace(/-/g, '_');
        }
        return null;
    }

    function createBadge() {
        badgeEl = document.createElement('div');
        badgeEl.className = 'agent-badge hidden';

        const avatar = document.createElement('div');
        avatar.className = 'agent-badge-avatar';

        const info = document.createElement('div');
        info.className = 'agent-badge-info';

        const name = document.createElement('span');
        name.className = 'agent-badge-name';
        name.textContent = 'Loading...';

        const station = document.createElement('span');
        station.className = 'agent-badge-station';

        info.appendChild(name);
        info.appendChild(station);

        const status = document.createElement('div');
        status.className = 'agent-badge-status';

        const tooltip = document.createElement('div');
        tooltip.className = 'agent-badge-tooltip';

        badgeEl.appendChild(avatar);
        badgeEl.appendChild(info);
        badgeEl.appendChild(status);
        badgeEl.appendChild(tooltip);

        document.body.appendChild(badgeEl);
        return badgeEl;
    }

    function createTooltipRow(label, value) {
        const row = document.createElement('div');
        row.className = 'agent-badge-tooltip-row';

        const labelEl = document.createElement('span');
        labelEl.className = 'agent-badge-tooltip-label';
        labelEl.textContent = label;

        const valueEl = document.createElement('span');
        valueEl.className = 'agent-badge-tooltip-value';
        valueEl.textContent = value;

        row.appendChild(labelEl);
        row.appendChild(valueEl);
        return row;
    }

    function updateBadge(data) {
        if (!badgeEl) return;
        if (!data || !data.agent_name) {
            badgeEl.classList.add('hidden');
            return;
        }

        badgeEl.classList.remove('hidden');

        // Avatar (first letter of agent name, colored by station)
        const avatar = badgeEl.querySelector('.agent-badge-avatar');
        avatar.textContent = data.agent_name.charAt(0).toUpperCase();
        avatar.className = 'agent-badge-avatar station-' + (data.station_code || 'COMMAND');

        // Name and station
        badgeEl.querySelector('.agent-badge-name').textContent = data.agent_name;
        badgeEl.querySelector('.agent-badge-station').textContent = data.station_code || '';

        // Status indicator
        const status = badgeEl.querySelector('.agent-badge-status');
        status.className = 'agent-badge-status ' + (data.status || 'active');

        // Tooltip (safe DOM construction)
        const tooltip = badgeEl.querySelector('.agent-badge-tooltip');
        tooltip.replaceChildren();
        tooltip.appendChild(createTooltipRow('Agent', data.agent_name));
        tooltip.appendChild(createTooltipRow('Station', data.station_code || 'N/A'));
        tooltip.appendChild(createTooltipRow('Model', data.model || 'N/A'));
        tooltip.appendChild(createTooltipRow('Status', data.status || 'active'));
    }

    async function fetchAgentInfo() {
        if (!currentModule) return;
        try {
            const resp = await fetch('/api/module-agents?module=' + encodeURIComponent(currentModule));
            if (resp.ok) {
                const data = await resp.json();
                updateBadge(data);
            }
        } catch (e) {
            // Silently fail — badge just stays hidden
        }
    }

    function init() {
        currentModule = getModuleName();
        if (!currentModule) return; // Not on a module page

        createBadge();
        fetchAgentInfo();
        setInterval(fetchAgentInfo, POLL_INTERVAL);
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
