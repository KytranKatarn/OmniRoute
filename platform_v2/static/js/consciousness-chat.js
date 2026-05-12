/**
 * consciousness-chat.js
 * C.O.D.E.X. chat overlay for the Consciousness module.
 * C.O.D.E.X. (id 146) — Documentation & Knowledge director.
 */
(function () {
    var AGENT_ID = 146;
    var CONFIG = {
        agentTarget: 'C.O.D.E.X.',
        label: 'C.O.D.E.X.',
        icon: '📚',
        accentColor: '#8b5cf6',
        moduleKey: 'consciousness',
        expandUrl: '/tools/consciousness',
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
