/**
 * security-network-chat.js
 * V.I.G.I.L. chat overlay for the Security & Network module.
 * Config baked in — no configure() call needed in the template.
 */
(function () {
    const AGENT_ID = 3;
    const CONFIG = {
        agentTarget: 'V.I.G.I.L.',
        label: 'V.I.G.I.L.',
        icon: '🛡️',
        accentColor: '#ef4444',
        moduleKey: 'security_network',
        expandUrl: '/tools/security-network',
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
