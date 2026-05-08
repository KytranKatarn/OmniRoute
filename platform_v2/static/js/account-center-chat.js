/**
 * account-center-chat.js
 * W.A.R.D.E.N. chat overlay for the Account Center module.
 * Config baked in — no configure() call needed in the template.
 */
(function () {
    const AGENT_ID = 142;
    const CONFIG = {
        agentTarget: 'R.E.S.O.L.V.E.',
        label: 'R.E.S.O.L.V.E.',
        icon: '🤝',
        accentColor: '#7c3aed',
        moduleKey: 'account_center',
        expandUrl: '/tools/department-hq',
        portraitUrl: null,
    };

    function applyConfig(portraitUrl) {
        function attempt() {
            var overlay = window.archieOverlay;
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
