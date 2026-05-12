/**
 * therapy-chat.js — V.I.T.A.L. chat overlay for Therapy module.
 */
(function () {
    const AGENT_ID = 148;
    const CONFIG = {
        agentTarget: 'V.I.T.A.L.',
        label: 'V.I.T.A.L.',
        icon: '🧠',
        accentColor: '#10b981',
        moduleKey: 'therapy',
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
