/* Trust Center public compliance results. Only sanitized aggregate data is rendered. */
var Compliance = {
    API_URL: 'https://api.kytranempowerment.com/api/public/compliance/frameworks',
    CIRCUMFERENCE: 326.7,

    init: function () {
        var self = this;
        var container = document.getElementById('complianceBadges');
        if (!container) return;

        container.setAttribute('aria-busy', 'true');
        fetch(this.API_URL, { headers: { Accept: 'application/json' } })
            .then(function (response) {
                if (!response.ok) throw new Error('Compliance status unavailable');
                return response.json();
            })
            .then(function (data) {
                self.render(data);
            })
            .catch(function () {
                self.renderUnavailable();
            });
    },

    _element: function (tag, className, text) {
        var element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    },

    _formatDate: function (value) {
        if (!value) return '';
        var date = new Date(value);
        if (Number.isNaN(date.getTime())) return '';
        return new Intl.DateTimeFormat(undefined, {
            dateStyle: 'medium',
            timeStyle: 'short'
        }).format(date);
    },

    render: function (data) {
        var container = document.getElementById('complianceBadges');
        var summary = document.getElementById('complianceScanSummary');
        if (!container) return;
        while (container.firstChild) container.removeChild(container.firstChild);

        if (!data || data.available !== true || !Array.isArray(data.badges) || data.badges.length === 0) {
            this.renderUnavailable();
            return;
        }

        var scanDate = this._formatDate(data.last_scan);
        if (summary) {
            summary.textContent = 'Latest complete rule-level scan'
                + (scanDate ? ' · ' + scanDate : '')
                + ' · ' + Number(data.framework_count || data.badges.length) + ' frameworks'
                + ' · ' + Number(data.evaluated_rules || 0) + ' applicable checks';
        }

        var self = this;
        data.badges.forEach(function (badge) {
            var card = self._element('article', 'tc-score-card');
            card.style.setProperty('--tc-accent', '#00e5ff');
            card.appendChild(self._element('h3', 'tc-score-card__title', badge.display_name || badge.framework || 'Framework'));
            card.appendChild(self._element('div', 'tc-score-card__status', 'Automated check pass rate'));

            var ring = self._element('div', 'tc-ring-wrap');
            var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('viewBox', '0 0 120 120');
            var track = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            track.setAttribute('class', 'tc-ring-track');
            track.setAttribute('cx', '60');
            track.setAttribute('cy', '60');
            track.setAttribute('r', '52');
            svg.appendChild(track);
            var value = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            value.setAttribute('class', 'tc-ring-value');
            value.setAttribute('cx', '60');
            value.setAttribute('cy', '60');
            value.setAttribute('r', '52');
            var score = Number(badge.score);
            var validScore = badge.score !== null && badge.score !== undefined
                && Number.isFinite(score) && score >= 0 && score <= 100;
            value.style.strokeDashoffset = validScore
                ? String(self.CIRCUMFERENCE * (1 - score / 100))
                : String(self.CIRCUMFERENCE);
            svg.appendChild(value);
            ring.appendChild(svg);
            ring.appendChild(self._element('div', 'tc-ring-num', validScore ? Math.round(score) + '%' : '—'));
            card.appendChild(ring);

            card.appendChild(self._element('div', 'tc-score-card__label', 'Passing / applicable checks'));
            var detail = Number(badge.passing_rules || 0) + ' of ' + Number(badge.evaluated_rules || 0) + ' checks passed';
            var exclusions = [];
            if (Number(badge.not_applicable_rules || 0) > 0) exclusions.push(Number(badge.not_applicable_rules) + ' not applicable');
            if (Number(badge.manual_rules || 0) > 0) exclusions.push(Number(badge.manual_rules) + ' manual');
            if (exclusions.length) detail += ' · ' + exclusions.join(' · ');
            card.appendChild(self._element('p', 'tc-score-card__detail', detail));
            container.appendChild(card);
        });
        container.setAttribute('aria-busy', 'false');
    },

    renderUnavailable: function () {
        var container = document.getElementById('complianceBadges');
        var summary = document.getElementById('complianceScanSummary');
        if (container) {
            while (container.firstChild) container.removeChild(container.firstChild);
            container.setAttribute('aria-busy', 'false');
            container.appendChild(this._element('p', 'tc-score-card__detail', 'No complete rule-level scan is currently available.'));
        }
        if (summary) summary.textContent = 'Scan results are temporarily unavailable.';
    }
};
