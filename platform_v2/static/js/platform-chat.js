/**
 * platform-chat.js
 * A.R.C.H.I.E. chat overlay for the main platform dashboard.
 * Public-facing voice for Kytran + members. Briefing: health, agents, alerts.
 */
(function () {
    var CONFIG = {
        agentTarget: 'ARCHIE',
        label: 'A.R.C.H.I.E.',
        icon: '🤖',
        accentColor: '#00bcd4',
        moduleKey: 'platform_main',
        expandUrl: '/tools/department-hq',
        portraitUrl: null,
    };

    function buildBriefing(summary) {
        var lines = ['PLATFORM STATUS'];
        if (summary) {
            if (summary.platform_health) lines.push('Health: ' + summary.platform_health);
            if (summary.active_agents !== undefined) lines.push('Active agents: ' + summary.active_agents);
            if (summary.pending_alerts !== undefined) lines.push('Pending alerts: ' + summary.pending_alerts);
        }
        lines.push('');
        lines.push('You are A.R.C.H.I.E., the platform COO. Help with platform status, navigation, and quick summaries.');
        return lines.join('\n');
    }

    function applyConfig(briefing) {
        function attempt() {
            var overlay = window.archieOverlay;
            if (!overlay) { setTimeout(attempt, 100); return; }
            overlay.configure(Object.assign({}, CONFIG, {
                systemContext: briefing || null,
            }));
        }
        attempt();
    }

    document.addEventListener('DOMContentLoaded', function () {
        fetch('/api/quick-summary', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) { applyConfig(buildBriefing(d)); })
            .catch(function () { applyConfig(buildBriefing(null)); });
    });
}());
