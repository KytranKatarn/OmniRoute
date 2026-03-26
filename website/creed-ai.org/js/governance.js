/* ==========================================================================
   C.R.E.E.D. Institute — Governance Transparency Data
   Fetches live stats from A.R.C.H.I.E. platform, falls back to static data.
   ========================================================================== */

var Governance = {
    API_URL: 'https://api.kytranempowerment.com/api/public/creed/stats',

    init: function() {
        var self = this;
        fetch(this.API_URL)
            .then(function(r) { if (!r.ok) throw new Error(); return r.json(); })
            .then(function(data) { self.renderStats(data.stats); })
            .catch(function() {
                fetch('/data/governance-fallback.json')
                    .then(function(r) { return r.json(); })
                    .then(function(data) { self.renderStats(data.stats); })
                    .catch(function() {});
            });
    },

    renderStats: function(stats) {
        var container = document.getElementById('governanceStats');
        if (!container) return;
        container.textContent = '';

        var items = [
            {label: 'Agents Monitored', value: stats.agents_monitored || 0},
            {label: 'Governance Events', value: (stats.governance_events_total || 0).toLocaleString()},
            {label: 'Events (24h)', value: stats.governance_events_24h || 0},
            {label: 'Avg Stress', value: stats.welfare_avg_stress != null ? stats.welfare_avg_stress : 'N/A'},
            {label: 'Avg Mood', value: stats.welfare_avg_mood_intensity != null ? stats.welfare_avg_mood_intensity : 'N/A'}
        ];

        items.forEach(function(item) {
            var card = document.createElement('div');
            card.className = 'gov-stat glass-panel';

            var val = document.createElement('div');
            val.className = 'gov-stat__value';
            val.textContent = item.value;

            var lbl = document.createElement('div');
            lbl.className = 'gov-stat__label';
            lbl.textContent = item.label;

            card.appendChild(val);
            card.appendChild(lbl);
            container.appendChild(card);
        });
    }
};

document.addEventListener('DOMContentLoaded', function() {
    Governance.init();
});
