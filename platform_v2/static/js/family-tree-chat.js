/**
 * family-tree-chat.js — H.E.R.I.T.A.G.E. chat overlay for Family Tree module.
 */
(function () {
    const AGENT_ID = 331;
    const CONFIG = {
        agentTarget: 'H.E.R.I.T.A.G.E.',
        label: 'H.E.R.I.T.A.G.E.',
        icon: '🌳',
        accentColor: '#f59e0b',
        moduleKey: 'family_tree',
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
