/**
 * media-hub-chat.js — M.A.V.E.N. chat overlay for Media Hub module.
 */
(function () {
    const AGENT_ID = 27;
    const CONFIG = {
        agentTarget: 'M.A.V.E.N.',
        label: 'M.A.V.E.N.',
        icon: '📺',
        accentColor: '#8b5cf6',
        moduleKey: 'media_hub',
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
