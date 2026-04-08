/**
 * Agent Badge System — Fetches and displays agent assignments on module cards.
 * Polls every 30s for updates.
 */
(function() {
    var moduleAgents = {};

    function fetchModuleAgents() {
        fetch('/tools/department-hq/api/dashboard/module-agents')
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (data.success) {
                    moduleAgents = data.module_agents;
                    renderBadges();
                }
            })
            .catch(function(e) {
                console.debug('Agent badge fetch failed:', e);
            });
    }

    function renderBadges() {
        var cards = document.querySelectorAll('[data-module-id]');
        for (var i = 0; i < cards.length; i++) {
            var card = cards[i];
            var moduleId = card.getAttribute('data-module-id');
            var agent = moduleAgents[moduleId];

            // Remove existing badge
            var existing = card.querySelector('.agent-badge');
            if (existing) existing.remove();

            if (!agent) continue;

            var statusClass = agent.status === 'active' ? 'active' :
                              agent.status === 'working' ? 'working' :
                              agent.status === 'resting' ? 'resting' : 'offline';

            var badge = document.createElement('div');
            badge.className = 'agent-badge';

            var dot = document.createElement('span');
            dot.className = 'status-dot ' + statusClass;
            badge.appendChild(dot);

            var nameSpan = document.createElement('span');
            nameSpan.className = 'agent-name';
            nameSpan.textContent = agent.first_name || agent.agent_codename;
            badge.appendChild(nameSpan);

            var codeSpan = document.createElement('span');
            codeSpan.className = 'agent-codename';
            codeSpan.textContent = '(' + agent.agent_codename + ')';
            badge.appendChild(codeSpan);

            // Insert at top of card content
            var cardBody = card.querySelector('.module-card-body, .card-content, .module-info');
            if (cardBody) {
                cardBody.insertBefore(badge, cardBody.firstChild);
            } else if (card.children.length > 1) {
                card.insertBefore(badge, card.children[1]);
            } else {
                card.appendChild(badge);
            }
        }
    }

    // Initial fetch + polling
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', fetchModuleAgents);
    } else {
        fetchModuleAgents();
    }
    setInterval(fetchModuleAgents, 30000);
})();
