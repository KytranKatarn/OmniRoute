/* ==========================================================================
   Kytran News — Parliament Layer
   Canadian Parliament bills RSS via rss2json — falls back to static JSON
   Bills shown at Ottawa; other capital legislatures at their cities
   ========================================================================== */

var Parliament = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    /* Parliament locations — Ottawa is primary, others for variety */
    var PARLIAMENT_LOCS = [
        { lat: 45.4253,  lon: -75.7009, country: 'Canada',         label: 'House of Commons'  },
        { lat: 51.4994,  lon: -0.1248,  country: 'United Kingdom',  label: 'UK Parliament'     },
        { lat: 48.8566,  lon: 2.3522,   country: 'France',          label: 'Assemblée Nationale' },
        { lat: 52.5186,  lon: 13.3763,  country: 'Germany',         label: 'Bundestag'         },
        { lat: 41.9029,  lon: 12.4534,  country: 'Italy',           label: 'Camera dei Deputati' },
        { lat: 40.4168,  lon: -3.7038,  country: 'Spain',           label: 'Cortes Generales'  },
        { lat: 59.3293,  lon: 18.0686,  country: 'Sweden',          label: 'Riksdag'           },
        { lat: 35.6762,  lon: 139.6503, country: 'Japan',           label: 'National Diet'     }
    ];

    function init() {
        _visible = App.isLayerActive('parliament');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'parliament') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('parliament', refresh, Config.INTERVALS.parliament || 600000);
    }

    function refresh() {
        var url = Config.API.parliament_bills;
        fetch(url)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                var parsed = _parseRss(data);
                if (parsed.length > 0) {
                    _data = parsed;
                    _finalize();
                } else {
                    _loadFallback();
                }
            })
            .catch(function () { _loadFallback(); });
    }

    function _parseRss(data) {
        try {
            if (!data || !data.items || !data.items.length) return [];
            var locIdx = 0;
            return data.items.map(function (item) {
                var loc = PARLIAMENT_LOCS[locIdx % PARLIAMENT_LOCS.length];
                locIdx++;
                /* Jitter so bills don't stack exactly on same point */
                var jitter = function () { return (Math.random() - 0.5) * 0.3; };
                /* Infer event_type from title */
                var titleLow = (item.title || '').toLowerCase();
                var event_type = 'bill';
                if (/vote|division|passed|defeated|third reading/.test(titleLow)) event_type = 'vote';
                if (/debate|second reading|committee/.test(titleLow)) event_type = 'debate';
                return {
                    type: 'parliament',
                    event_type: event_type,
                    title: item.title || 'Parliament Bill',
                    lat: loc.lat + jitter(),
                    lon: loc.lon + jitter(),
                    description: item.description ? item.description.replace(/<[^>]*>/g, '').substring(0, 200) : '',
                    url: item.link || item.url || null,
                    timestamp: item.pubDate ? new Date(item.pubDate).toISOString() : null,
                    country: loc.country,
                    legislature: loc.label,
                    source: 'Parliament RSS'
                };
            });
        } catch (e) {
            return [];
        }
    }

    function _loadFallback() {
        fetch(Config.FALLBACKS.parliament)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _data = Array.isArray(data) ? data : (data.bills || data.events || []);
                _data = _data.map(function (d) {
                    return {
                        type: d.type || 'parliament',
                        event_type: d.event_type || 'bill',
                        title: d.title || d.name || 'Parliament Bill',
                        lat: d.lat != null ? d.lat : 45.4253,
                        lon: d.lon != null ? d.lon : -75.7009,
                        description: d.description || '',
                        url: d.url || null,
                        timestamp: d.timestamp || null,
                        country: d.country || 'Canada',
                        legislature: d.legislature || 'House of Commons',
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
        App.updateLayerCount('parliament', _data.length);
        EventBus.emit('data:parliament:updated', _data);
        _render();
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('parliament');
            KytranMap.removeLayer('parliament-pulse');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'parliament',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.event_type === 'vote') return 22000;
                if (d.event_type === 'bill') return 16000;
                return 12000;
            },
            getFillColor: function (d) {
                if (d.event_type === 'vote') return [255, 215, 64, 220];
                if (d.event_type === 'bill') return [255, 215, 64, 170];
                return [255, 215, 64, 120];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 20,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('parliament', layer);
    }

    function renderPulse() {
        var votes = _data.filter(function (d) { return d.event_type === 'vote'; });
        if (!_visible || votes.length === 0) { KytranMap.removeLayer('parliament-pulse'); return; }

        var now = Date.now();
        var pulseLayer = new deck.ScatterplotLayer({
            id: 'parliament-pulse',
            data: votes,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function () {
                var cycle = ((now / 1000) % 3) / 3;
                return 20000 * (1 + cycle * 2);
            },
            stroked: true,
            filled: false,
            getLineColor: function () {
                var cycle = ((now / 1000) % 3) / 3;
                return [255, 215, 64, Math.floor(180 * (1 - cycle))];
            },
            getLineWidth: 2,
            lineWidthMinPixels: 1,
            radiusMinPixels: 5,
            radiusMaxPixels: 40,
            pickable: false,
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('parliament-pulse', pulseLayer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData, renderPulse: renderPulse };
})();
