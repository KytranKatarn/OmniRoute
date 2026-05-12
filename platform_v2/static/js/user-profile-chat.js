/**
 * user-profile-chat.js
 * R.E.S.O.L.V.E. chat overlay for the My Profile module.
 * R.E.S.O.L.V.E. (id 142) — Customer Success & Support director.
 */
(function () {
    var AGENT_ID = 142;
    var CONFIG = {
        agentTarget: 'R.E.S.O.L.V.E.',
        label: 'R.E.S.O.L.V.E.',
        icon: '👤',
        accentColor: '#ef4444',
        moduleKey: 'user_profile',
        expandUrl: '/tools/my-profile',
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
