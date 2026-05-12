/**
 * wtf-hub-chat.js
 * F.A.C.T. chat overlay for the WTF Hub module.
 * F.A.C.T. (id 48) — News & Media director, bias/factcheck pipeline owner.
 */
(function () {
    var AGENT_ID = 48;
    var CONFIG = {
        agentTarget: 'F.A.C.T.',
        label: 'F.A.C.T.',
        icon: '📰',
        accentColor: '#00ffff',
        moduleKey: 'wtf_hub',
        expandUrl: '/tools/wtf-hub',
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
