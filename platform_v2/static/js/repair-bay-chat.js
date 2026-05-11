/**
 * repair-bay-chat.js
 * S.M.I.T.H. chat overlay for the Repair Bay module.
 * S.M.I.T.H. (id 364) — Engineering & Technology, Self-healing pipeline.
 */
(function () {
    var AGENT_ID = 364;
    var CONFIG = {
        agentTarget: 'S.M.I.T.H.',
        label: 'S.M.I.T.H.',
        icon: '🔧',
        accentColor: '#00e5ff',
        moduleKey: 'repair_bay',
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
            .then(function (d) { applyConfig(d.canonical_image_path || d.avatar_url || null); })
            .catch(function () { applyConfig(null); });
    });
}());
