/* Compliance / Trust Center — Badge rendering */
var Compliance = {
    API_URL: 'https://api.kytranempowerment.com/api/public/compliance/frameworks',

    init: function () {
        var self = this;
        fetch(this.API_URL)
            .then(function (r) {
                if (!r.ok) throw new Error(r.status);
                return r.json();
            })
            .then(function (data) {
                self.renderBadges(data.badges || data.frameworks || data);
            })
            .catch(function () {
                fetch('/data/badges-fallback.json')
                    .then(function (r) { return r.json(); })
                    .then(function (data) {
                        self.renderBadges(data.badges || data.frameworks || data);
                    })
                    .catch(function () { /* no data available */ });
            });
    },

    _getGradeColor: function (score) {
        if (score >= 90) return 'green';
        if (score >= 80) return 'blue';
        if (score >= 70) return 'yellow';
        return 'red';
    },

    _getGradeLetter: function (score) {
        if (score >= 95) return 'A+';
        if (score >= 90) return 'A';
        if (score >= 85) return 'B+';
        if (score >= 80) return 'B';
        if (score >= 70) return 'C';
        if (score >= 60) return 'D';
        return 'F';
    },

    _clearChildren: function (el) {
        while (el.firstChild) el.removeChild(el.firstChild);
    },

    renderBadges: function (badges) {
        var container = document.getElementById('complianceBadges');
        if (!container) return;
        this._clearChildren(container);

        if (!Array.isArray(badges)) return;

        var self = this;
        badges.forEach(function (badge) {
            var score = badge.score || 0;
            var color = self._getGradeColor(score);
            var grade = self._getGradeLetter(score);

            var card = document.createElement('div');
            card.className = 'badge-card';

            // Grade letter
            var gradeEl = document.createElement('div');
            gradeEl.className = 'badge-card__grade badge-card__grade--' + color;
            gradeEl.textContent = grade;
            card.appendChild(gradeEl);

            // Framework name
            var nameEl = document.createElement('div');
            nameEl.className = 'badge-card__framework';
            nameEl.textContent = badge.display_name || badge.framework || 'Unknown';
            card.appendChild(nameEl);

            // Score percentage
            var scoreEl = document.createElement('div');
            scoreEl.className = 'badge-card__score';
            scoreEl.textContent = Math.round(score) + '% compliant';
            card.appendChild(scoreEl);

            // Progress bar
            var progressWrap = document.createElement('div');
            progressWrap.className = 'badge-card__progress';
            var progressFill = document.createElement('div');
            progressFill.className = 'badge-card__progress-fill badge-card__progress-fill--' + color;
            progressFill.style.width = Math.min(100, Math.round(score)) + '%';
            progressWrap.appendChild(progressFill);
            card.appendChild(progressWrap);

            // Rule count
            if (badge.rule_count !== undefined) {
                var rulesEl = document.createElement('div');
                rulesEl.className = 'badge-card__rules';
                rulesEl.textContent = badge.rule_count + ' rules evaluated';
                card.appendChild(rulesEl);
            }

            container.appendChild(card);
        });
    }
};

document.addEventListener('DOMContentLoaded', function () {
    Compliance.init();
});
