/**
 * repair-bay-chat.js
 * F.O.R.G.E. chat overlay for the Repair Bay module.
 * F.O.R.G.E. (id 136) — Engineering & Technology, self-healing pipeline owner.
 */
(function () {
    var AGENT_ID = 136;
    var CONFIG = {
        agentTarget: 'F.O.R.G.E.',
        label: 'F.O.R.G.E.',
        icon: '⚙️',
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
