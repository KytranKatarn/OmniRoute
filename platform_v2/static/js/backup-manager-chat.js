/**
 * backup-manager-chat.js
 * W.A.R.D.E.N. chat overlay for the Backup Manager module.
 * Config baked in — no configure() call needed in the template.
 */
(function () {
    const AGENT_ID = 363;
    const CONFIG = {
        agentTarget: 'W.A.R.D.E.N.',
        label: 'W.A.R.D.E.N.',
        icon: '🛡',
        accentColor: '#ef4444',
        moduleKey: 'backup_manager',
        expandUrl: '/tools/department-hq',
        portraitUrl: null,
    };

    function applyConfig(portraitUrl) {
        function attempt() {
            const overlay = window.archieOverlay;
            if (!overlay) { setTimeout(attempt, 100); return; }
            overlay.configure(Object.assign({}, CONFIG, { portraitUrl: portraitUrl || null }));
        }
        attempt();
    }

    document.addEventListener('DOMContentLoaded', function () {
        fetch('/tools/media-studio/api/portraits/' + AGENT_ID, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                applyConfig(d.canonical_image_path || d.avatar_url || null);
            })
            .catch(function () { applyConfig(null); });
    });
})();
