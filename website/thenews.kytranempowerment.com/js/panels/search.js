/* ==========================================================================
   Kytran News — Search Panel
   Fuzzy search across all loaded data, fly to result on click
   ========================================================================== */

var Search = (function () {
    'use strict';

    var _inputEl = null;
    var _resultsEl = null;
    var _debounceTimer = null;

    function init() {
        _inputEl = document.getElementById('search-input');
        _resultsEl = document.getElementById('search-results');
        if (!_inputEl || !_resultsEl) return;

        _inputEl.addEventListener('input', function () {
            clearTimeout(_debounceTimer);
            _debounceTimer = setTimeout(function () {
                _search(_inputEl.value.trim());
            }, 250);
        });

        _inputEl.addEventListener('focus', function () {
            if (_resultsEl.children.length > 0) _resultsEl.classList.add('open');
        });

        /* Close on click outside */
        document.addEventListener('click', function (e) {
            if (!_inputEl.contains(e.target) && !_resultsEl.contains(e.target)) {
                _resultsEl.classList.remove('open');
            }
        });

        /* Close on Escape */
        _inputEl.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                _resultsEl.classList.remove('open');
                _inputEl.blur();
            }
        });
    }

    function _search(query) {
        if (!query || query.length < 2) {
            _clearResults();
            return;
        }

        var q = query.toLowerCase();
        var results = [];

        /* Search conflicts */
        if (typeof Conflicts !== 'undefined') {
            Conflicts.getData().forEach(function (d) {
                if (_matches(d.title, q) || _matches(d.source, q)) {
                    results.push({ data: d, type: 'conflict', color: 'var(--layer-conflicts)' });
                }
            });
        }

        /* Search disasters */
        if (typeof Disasters !== 'undefined') {
            var dd = Disasters.getData();
            (dd.earthquakes || []).forEach(function (d) {
                if (_matches(d.title, q)) {
                    results.push({ data: d, type: 'earthquake', color: 'var(--layer-disasters)' });
                }
            });
            (dd.eonet || []).forEach(function (d) {
                if (_matches(d.title, q) || _matches(d.subtype, q)) {
                    results.push({ data: d, type: 'disaster', color: 'var(--layer-disasters)' });
                }
            });
        }

        /* Search weather */
        if (typeof Weather !== 'undefined') {
            Weather.getData().forEach(function (d) {
                if (_matches(d.title, q) || _matches(d.area, q)) {
                    results.push({ data: d, type: 'weather', color: 'var(--layer-weather)' });
                }
            });
        }

        /* Search military */
        if (typeof Military !== 'undefined') {
            Military.getData().forEach(function (d) {
                if (_matches(d.title, q) || _matches(d.country, q)) {
                    results.push({ data: d, type: 'military', color: 'var(--layer-military)' });
                }
            });
        }

        /* Search sanctions */
        if (typeof Sanctions !== 'undefined') {
            Sanctions.getData().forEach(function (d) {
                if (_matches(d.name, q) || _matches(d.code, q) || _matches(d.description, q)) {
                    results.push({ data: d, type: 'sanctions', color: 'var(--layer-sanctions)' });
                }
            });
        }

        /* Search news */
        if (typeof Ticker !== 'undefined') {
            Ticker.getData().forEach(function (d) {
                if (_matches(d.title, q) || _matches(d.source, q)) {
                    results.push({ data: d, type: 'news', color: 'var(--color-info)' });
                }
            });
        }

        /* Limit to 20 results */
        results = results.slice(0, 20);
        _renderResults(results);
    }

    function _matches(str, query) {
        if (!str) return false;
        return str.toLowerCase().indexOf(query) !== -1;
    }

    function _renderResults(results) {
        /* Clear safely */
        while (_resultsEl.firstChild) _resultsEl.removeChild(_resultsEl.firstChild);

        if (results.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'search-results__item';
            empty.style.color = 'var(--color-text-muted)';
            empty.textContent = 'No results found';
            _resultsEl.appendChild(empty);
            _resultsEl.classList.add('open');
            return;
        }

        results.forEach(function (r) {
            var item = document.createElement('div');
            item.className = 'search-results__item';

            var badge = document.createElement('span');
            badge.className = 'search-results__type';
            badge.style.background = r.color;
            badge.style.color = '#fff';
            badge.textContent = r.type;
            item.appendChild(badge);

            var text = document.createElement('span');
            text.className = 'truncate';
            text.textContent = r.data.title || r.data.name || 'Unknown';
            item.appendChild(text);

            item.addEventListener('click', function () {
                _flyToResult(r.data);
                _resultsEl.classList.remove('open');
            });

            _resultsEl.appendChild(item);
        });

        _resultsEl.classList.add('open');
    }

    function _flyToResult(data) {
        var lat = data.lat;
        var lon = data.lon;
        if (lat != null && lon != null) {
            KytranMap.flyTo(lat, lon, 6);
        }
    }

    function _clearResults() {
        while (_resultsEl.firstChild) _resultsEl.removeChild(_resultsEl.firstChild);
        _resultsEl.classList.remove('open');
    }

    return { init: init };
})();
