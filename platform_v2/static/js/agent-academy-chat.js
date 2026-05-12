/**
 * agent-academy-chat.js
 * F.O.R.G.E. chat overlay for the Agent Academy module.
 * F.O.R.G.E. (id 136) — Engineering & Technology director, training owner.
 */
(function () {
    var AGENT_ID = 136;
    var CONFIG = {
        agentTarget: 'F.O.R.G.E.',
        label: 'F.O.R.G.E.',
        icon: '🎓',
        accentColor: '#00e5ff',
        moduleKey: 'agent_academy',
        expandUrl: '/tools/agent-academy',
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
