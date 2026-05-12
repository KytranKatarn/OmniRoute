/**
 * faith-chat.js — F.A.I.T.H. chat overlay for Faith module.
 */
(function () {
    const AGENT_ID = 352;
    const CONFIG = {
        agentTarget: 'F.A.I.T.H.',
        label: 'F.A.I.T.H.',
        icon: '🙏',
        accentColor: '#10b981',
        moduleKey: 'faith',
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
