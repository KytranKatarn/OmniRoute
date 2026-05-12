/**
 * media-studio-chat.js — M.U.S.E. chat overlay for Media Studio module.
 */
(function () {
    const AGENT_ID = 138;
    const CONFIG = {
        agentTarget: 'M.U.S.E.',
        label: 'M.U.S.E.',
        icon: '🎨',
        accentColor: '#f472b6',
        moduleKey: 'media_studio',
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
