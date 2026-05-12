/**
 * department-hq-chat.js
 * K.I.N. chat overlay for the Department HQ module.
 * K.I.N. (id 145) — Human Resources & Culture, agent welfare and org management.
 */
(function () {
    var AGENT_ID = 145;
    var CONFIG = {
        agentTarget: 'K.I.N.',
        label: 'K.I.N.',
        icon: '🤝',
        accentColor: '#00e5ff',
        moduleKey: 'department_hq',
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
