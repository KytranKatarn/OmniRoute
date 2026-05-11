/**
 * email-manager-chat.js
 * R.E.S.O.L.V.E. chat overlay for the Email HQ module.
 * Briefing includes live mailbox + triage stats from email_messages.
 */
(function () {
    var AGENT_ID = 142;
    var CONFIG = {
        agentTarget: 'R.E.S.O.L.V.E.',
        label: 'R.E.S.O.L.V.E.',
        icon: '🤝',
        accentColor: '#ef4444',
        moduleKey: 'email_manager',
        expandUrl: '/tools/department-hq',
        portraitUrl: null,
    };

    function buildBriefing(counts) {
        var lines = ['EMAIL HQ BRIEFING'];
        if (counts) {
            lines.push('Unread messages: ' + (counts.unread || 0));
            lines.push('Action items: ' + (counts.action_items || 0));
        }
        lines.push('');
        lines.push('You are R.E.S.O.L.V.E., Customer Success & Support director.');
        lines.push('Help triage, draft replies, and manage the email workflow.');
        return lines.join('\n');
    }

    function applyConfig(portraitUrl, briefing) {
        function attempt() {
            var overlay = window.archieOverlay;
            if (!overlay) { setTimeout(attempt, 100); return; }
            overlay.configure(Object.assign({}, CONFIG, {
                portraitUrl: portraitUrl || null,
                systemContext: briefing || null,
            }));
        }
        attempt();
    }

    document.addEventListener('DOMContentLoaded', function () {
        // Fetch portrait + live counts in parallel
        var portraitP = fetch('/tools/media-studio/api/portraits/' + AGENT_ID, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .catch(function () { return {}; });

        var countsP = fetch('/tools/email-manager/api/email/counts', { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .catch(function () { return {}; });

        Promise.all([portraitP, countsP]).then(function (results) {
            var portrait = results[0];
            var counts = results[1];
            var portraitUrl = portrait.canonical_image_path || portrait.avatar_url || null;
            applyConfig(portraitUrl, buildBriefing(counts));
        });
    });
}());
