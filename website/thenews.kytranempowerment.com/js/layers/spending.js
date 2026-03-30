/* ==========================================================================
   Kytran News — Public Spending Layer
   World Bank government expenditure (% of GDP) — falls back to static JSON
   Countries shown as scaled circles at their capital cities
   ========================================================================== */

var Spending = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    /* Capital city coordinates keyed by World Bank 2-letter country code */
    var COUNTRY_META = {
        CA: { name: 'Canada',         lat: 45.4215, lon: -75.6972,  gdp: 2140000000000 },
        US: { name: 'United States',  lat: 38.8951, lon: -77.0364,  gdp: 25000000000000 },
        GB: { name: 'United Kingdom', lat: 51.5074, lon: -0.1278,   gdp: 3130000000000 },
        FR: { name: 'France',         lat: 48.8566, lon: 2.3522,    gdp: 2940000000000 },
        DE: { name: 'Germany',        lat: 52.5200, lon: 13.4050,   gdp: 4260000000000 },
        JP: { name: 'Japan',          lat: 35.6762, lon: 139.6503,  gdp: 4230000000000 },
        AU: { name: 'Australia',      lat: -35.282, lon: 149.1287,  gdp: 1710000000000 },
        BR: { name: 'Brazil',         lat: -15.794, lon: -47.883,   gdp: 1920000000000 },
        IN: { name: 'India',          lat: 28.6139, lon: 77.2090,   gdp: 3390000000000 },
        CN: { name: 'China',          lat: 39.9042, lon: 116.4074,  gdp: 17960000000000 }
    };

    function init() {
        _visible = App.isLayerActive('spending');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'spending') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('spending', refresh, Config.INTERVALS.spending || 600000);
    }

    function refresh() {
        var url = Config.API.spending_worldbank;
        fetch(url)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                var parsed = _parseWorldBank(data);
                if (parsed.length > 0) {
                    _data = parsed;
                    _finalize();
                } else {
                    _loadFallback();
                }
            })
            .catch(function () { _loadFallback(); });
    }

    function _parseWorldBank(data) {
        try {
            /* World Bank returns [metadata, records_array] */
            var records = Array.isArray(data) && data.length > 1 ? data[1] : [];
            if (!records || !records.length) return [];

            /* Group by country — take the most recent non-null value */
            var byCountry = {};
            records.forEach(function (rec) {
                if (!rec || rec.value == null) return;
                var code = rec.country && rec.country.id ? rec.country.id : null;
                if (!code) return;
                if (!byCountry[code] || rec.date > byCountry[code].date) {
                    byCountry[code] = rec;
                }
            });

            return Object.keys(byCountry).map(function (code) {
                var rec = byCountry[code];
                var meta = COUNTRY_META[code];
                if (!meta) return null;
                /* Convert % of GDP to an absolute spending estimate */
                var pct = rec.value;
                var amount = Math.round((pct / 100) * meta.gdp);
                return {
                    type: 'spending',
                    title: meta.name + ' Gov Spending (' + rec.date + ')',
                    lat: meta.lat,
                    lon: meta.lon,
                    amount: amount,
                    description: 'Government expenditure ' + pct.toFixed(1) + '% of GDP (' + rec.date + ')',
                    url: 'https://data.worldbank.org/indicator/GC.XPN.TOTL.GD.ZS?locations=' + code,
                    timestamp: new Date(rec.date + '-01-01').toISOString(),
                    country: meta.name,
                    pct_gdp: pct,
                    source: 'World Bank'
                };
            }).filter(Boolean);
        } catch (e) {
            return [];
        }
    }

    function _loadFallback() {
        fetch(Config.FALLBACKS.spending)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _data = Array.isArray(data) ? data : (data.spending || data.events || []);
                _data = _data.map(function (d) {
                    return {
                        type: d.type || 'spending',
                        title: d.title || d.name || 'Public Spending',
                        lat: d.lat,
                        lon: d.lon,
                        amount: d.amount || 0,
                        description: d.description || '',
                        url: d.url || null,
                        timestamp: d.timestamp || null,
                        country: d.country || '',
                        pct_gdp: d.pct_gdp || null,
                        source: d.source || 'Fallback',
                        metadata: d.metadata || null
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
        App.updateLayerCount('spending', _data.length);
        EventBus.emit('data:spending:updated', _data);
        _render();
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('spending');
            return;
        }

        var layer = new deck.ScatterplotLayer({
            id: 'spending',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                var amt = d.amount || 0;
                if (amt > 1000000000000) return 50000;
                if (amt > 100000000000) return 38000;
                if (amt > 10000000000)  return 26000;
                if (amt > 1000000000)   return 18000;
                return 12000;
            },
            getFillColor: function (d) {
                /* Color by % of GDP if available, else teal */
                var pct = d.pct_gdp || 0;
                if (pct > 45) return [33, 150, 243, 180];   /* blue — high spend */
                if (pct > 35) return [105, 240, 174, 180];  /* green — moderate */
                if (pct > 25) return [255, 235, 59, 180];   /* yellow — lower */
                return [255, 152, 0, 180];                   /* orange — low */
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 30,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('spending', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
