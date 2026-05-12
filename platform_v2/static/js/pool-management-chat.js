/**
 * pool-management-chat.js — C.H.A.I.N. chat overlay for Pool Management module.
 */
(function () {
    const AGENT_ID = 365;
    const CONFIG = {
        agentTarget: 'C.H.A.I.N.',
        label: 'C.H.A.I.N.',
        icon: '⛓',
        accentColor: '#f59e0b',
        moduleKey: 'pool_management',
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
            .then(function (d) { applyConfig(d.canonical_image_path || d.avatar_url || null); })
            .catch(function () { applyConfig(null); });
    });
})();
