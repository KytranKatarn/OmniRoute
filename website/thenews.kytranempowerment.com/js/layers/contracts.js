/* ==========================================================================
   Kytran News — Government Contracts Layer
   Open Canada proactive disclosure API — falls back to static JSON
   ========================================================================== */

var Contracts = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    /* Capital city coordinates for Canadian provinces / federal */
    var CANADA_CITIES = [
        { name: 'Ottawa',      lat: 45.4215,  lon: -75.6972, level: 'federal'    },
        { name: 'Toronto',     lat: 43.6532,  lon: -79.3832, level: 'provincial' },
        { name: 'Vancouver',   lat: 49.2827,  lon: -123.1207, level: 'provincial' },
        { name: 'Montreal',    lat: 45.5017,  lon: -73.5673, level: 'provincial' },
        { name: 'Calgary',     lat: 51.0447,  lon: -114.0719, level: 'provincial' },
        { name: 'Edmonton',    lat: 53.5461,  lon: -113.4938, level: 'provincial' },
        { name: 'Winnipeg',    lat: 49.8951,  lon: -97.1384, level: 'provincial' },
        { name: 'Halifax',     lat: 44.6488,  lon: -63.5752, level: 'provincial' },
        { name: 'Quebec City', lat: 46.8139,  lon: -71.2080, level: 'provincial' },
        { name: 'Regina',      lat: 50.4452,  lon: -104.6189, level: 'provincial' }
    ];

    function init() {
        _visible = App.isLayerActive('contracts');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'contracts') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('contracts', refresh, Config.INTERVALS.contracts || 600000);
    }

    function refresh() {
        var url = Config.API.contracts_canada;
        fetch(url)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                var parsed = _parseOpenCanada(data);
                if (parsed.length > 0) {
                    _data = parsed;
                    _finalize();
                } else {
                    _loadFallback();
                }
            })
            .catch(function () { _loadFallback(); });
    }

    function _parseOpenCanada(data) {
        try {
            var results = data.result && data.result.results ? data.result.results : [];
            var cityIdx = 0;
            return results.map(function (pkg) {
                var city = CANADA_CITIES[cityIdx % CANADA_CITIES.length];
                cityIdx++;
                /* Jitter coordinates slightly so dots don't stack */
                var jitter = function () { return (Math.random() - 0.5) * 1.5; };
                /* Rough amount from title/notes — default to a mid-range value */
                var titleLower = (pkg.title && pkg.title.en ? pkg.title.en : (pkg.title || '')).toLowerCase();
                var amount = 500000;
                if (/million/.test(titleLower)) amount = 5000000;
                if (/billion/.test(titleLower)) amount = 500000000;
                var title = pkg.title && pkg.title.en ? pkg.title.en : (pkg.title || 'Government Contract');
                var notes = pkg.notes && pkg.notes.en ? pkg.notes.en : (pkg.notes || '');
                return {
                    type: 'contract',
                    title: title,
                    lat: city.lat + jitter(),
                    lon: city.lon + jitter(),
                    amount: amount,
                    level: city.level,
                    description: notes ? notes.substring(0, 200) : 'Canadian government contract disclosure',
                    url: pkg.url || ('https://open.canada.ca/data/en/dataset/' + (pkg.name || '')),
                    timestamp: pkg.metadata_modified ? new Date(pkg.metadata_modified).toISOString() : null,
                    source: 'Open Canada'
                };
            });
        } catch (e) {
            return [];
        }
    }

    function _loadFallback() {
        fetch(Config.FALLBACKS.contracts)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _data = Array.isArray(data) ? data : (data.contracts || data.events || []);
                /* Ensure required fields on fallback records */
                _data = _data.map(function (d) {
                    return {
                        type: d.type || 'contract',
                        title: d.title || d.name || 'Government Contract',
                        lat: d.lat,
                        lon: d.lon,
                        amount: d.amount || 0,
                        level: d.level || 'federal',
                        description: d.description || '',
                        url: d.url || null,
                        timestamp: d.timestamp || null,
                        source: d.source || 'Fallback'
                    };
                });
                _finalize();
            })
            .catch(function () {
                _data = [];
                _finalize();
            });
    }

    function _finalize() {
        App.updateLayerCount('contracts', _data.length);
        EventBus.emit('data:contracts:updated', _data);
        _render();
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('contracts');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'contracts',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                var amt = d.amount || 0;
                if (amt > 100000000) return 40000;
                if (amt > 10000000) return 28000;
                if (amt > 1000000) return 18000;
                return 10000;
            },
            getFillColor: function (d) {
                if (d.level === 'federal') return [0, 191, 165, 200];
                if (d.level === 'provincial') return [0, 191, 165, 150];
                return [0, 191, 165, 100];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 25,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('contracts', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
