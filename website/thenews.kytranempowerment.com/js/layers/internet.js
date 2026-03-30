/* ==========================================================================
   Kytran News — Internet Outages Layer
   IODA outage signals + The Verge tech/internet RSS — falls back to static JSON
   ========================================================================== */

var Internet = (function () {
    'use strict';

    var _data = [];
    var _visible = true;

    /* Country/region → coordinates for IODA signal placement */
    var IODA_REGION_COORDS = {
        US: { lat: 38.8951, lon: -77.0364 },
        CN: { lat: 39.9042, lon: 116.4074 },
        RU: { lat: 55.7558, lon: 37.6173  },
        IR: { lat: 35.6892, lon: 51.3890  },
        GB: { lat: 51.5074, lon: -0.1278  },
        DE: { lat: 52.5200, lon: 13.4050  },
        FR: { lat: 48.8566, lon: 2.3522   },
        IN: { lat: 28.6139, lon: 77.2090  },
        BR: { lat: -15.794, lon: -47.883  },
        AU: { lat: -35.282, lon: 149.1287 },
        TR: { lat: 39.9334, lon: 32.8597  },
        PK: { lat: 33.7294, lon: 73.0931  },
        MM: { lat: 19.745,  lon: 96.129   },
        KP: { lat: 39.039,  lon: 125.763  },
        NG: { lat: 9.082,   lon: 8.675    },
        EG: { lat: 30.033,  lon: 31.233   }
    };

    /* Internet/outage keywords for filtering Verge RSS */
    var OUTAGE_KEYWORDS = /outage|down|offline|disruption|censorship|bgp|internet|cyberattack|ddos|cable|cut|blackout|connectivity/i;

    function init() {
        _visible = App.isLayerActive('internet');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'internet') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('internet', refresh, Config.INTERVALS.internet || 300000);
    }

    function refresh() {
        /* Fetch IODA and Verge RSS in parallel, merge results */
        var now = Math.floor(Date.now() / 1000);
        var from = now - 86400; /* last 24h */
        var iodaUrl = Config.API.outages
            .replace('{from}', from)
            .replace('{until}', now);
        var vergeUrl = Config.API.internet_verge;

        Promise.all([
            fetch(iodaUrl)
                .then(function (r) { return r.ok ? r.json() : null; })
                .catch(function () { return null; }),
            fetch(vergeUrl)
                .then(function (r) { return r.ok ? r.json() : null; })
                .catch(function () { return null; })
        ]).then(function (results) {
            var iodaItems = _parseIoda(results[0]);
            var vergeItems = _parseVerge(results[1]);
            var combined = iodaItems.concat(vergeItems);
            if (combined.length > 0) {
                _data = combined;
                _finalize();
            } else {
                _loadFallback();
            }
        });
    }

    function _parseIoda(data) {
        try {
            if (!data || !data.data) return [];
            var signals = Array.isArray(data.data) ? data.data : Object.values(data.data);
            var items = [];
            signals.forEach(function (sig) {
                if (!sig) return;
                var entityCode = sig.entityCode || sig.country || 'US';
                var coords = IODA_REGION_COORDS[entityCode] || IODA_REGION_COORDS['US'];
                var jitter = function () { return (Math.random() - 0.5) * 1.5; };
                /* Determine severity from signal score */
                var score = sig.score || sig.magnitude || 0;
                var severity = score > 0.7 ? 'major' : (score > 0.3 ? 'moderate' : 'minor');
                items.push({
                    type: 'internet',
                    title: 'Internet Disruption — ' + (sig.entityName || entityCode),
                    lat: coords.lat + jitter(),
                    lon: coords.lon + jitter(),
                    severity: severity,
                    subtype: 'bgp',
                    description: 'IODA signal: ' + (sig.datasource || 'BGP') + ' disruption detected' + (score ? ' (score ' + score.toFixed(2) + ')' : ''),
                    url: 'https://ioda.inetintel.cc.gatech.edu/country/' + entityCode,
                    timestamp: sig.from ? new Date(sig.from * 1000).toISOString() : new Date().toISOString(),
                    source: 'IODA'
                });
            });
            return items;
        } catch (e) {
            return [];
        }
    }

    function _parseVerge(data) {
        try {
            if (!data || !data.items) return [];
            /* Place Verge tech news at Bay Area / Silicon Valley region */
            var BASE_LOC = { lat: 37.3861, lon: -122.0839 };
            var idx = 0;
            return data.items.filter(function (item) {
                var text = (item.title || '') + ' ' + (item.description || '');
                return OUTAGE_KEYWORDS.test(text);
            }).map(function (item) {
                var jitter = function () { return (Math.random() - 0.5) * 2; };
                idx++;
                return {
                    type: 'internet',
                    title: item.title || 'Tech/Internet News',
                    lat: BASE_LOC.lat + jitter(),
                    lon: BASE_LOC.lon + jitter(),
                    severity: 'moderate',
                    subtype: 'news',
                    description: item.description ? item.description.replace(/<[^>]*>/g, '').substring(0, 200) : '',
                    url: item.link || item.url || null,
                    timestamp: item.pubDate ? new Date(item.pubDate).toISOString() : null,
                    source: 'The Verge'
                };
            });
        } catch (e) {
            return [];
        }
    }

    function _loadFallback() {
        fetch('data/internet-outages.json')
            .then(function (r) { return r.json(); })
            .then(function (raw) {
                var items = (raw && raw.outages) ? raw.outages : (Array.isArray(raw) ? raw : []);
                _data = items.map(function (d) {
                    return {
                        type: d.type || 'internet',
                        title: d.title || d.name || 'Internet Outage',
                        lat: d.lat,
                        lon: d.lon,
                        severity: d.severity || 'minor',
                        subtype: d.subtype || d.type || 'bgp',
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
        App.updateLayerCount('internet', _data.length);
        EventBus.emit('data:internet:updated', _data);
        _render();
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('internet');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'internet',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.severity === 'major') return 28000;
                if (d.severity === 'moderate') return 18000;
                return 10000;
            },
            getFillColor: function (d) {
                if (d.subtype === 'censorship') return [183, 28, 28, 200];
                if (d.subtype === 'bgp') return [255, 64, 129, 200];
                if (d.subtype === 'cable') return [255, 110, 64, 180];
                if (d.subtype === 'ddos') return [213, 0, 249, 180];
                return [255, 64, 129, 150];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 30,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('internet', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
