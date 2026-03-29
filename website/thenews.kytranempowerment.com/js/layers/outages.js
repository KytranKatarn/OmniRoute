/* ==========================================================================
   Kytran News — Outages Layer
   IODA (Georgia Tech) internet outage signals + fallback
   ========================================================================== */

var Outages = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    /* Country centroids for IODA entity mapping */
    var COUNTRY_COORDS = {
        US: { lat: 39.8, lon: -98.6 }, GB: { lat: 55.4, lon: -3.4 }, DE: { lat: 51.2, lon: 10.4 },
        FR: { lat: 46.2, lon: 2.2 }, RU: { lat: 61.5, lon: 105.3 }, CN: { lat: 35.9, lon: 104.2 },
        IN: { lat: 20.6, lon: 78.9 }, BR: { lat: -14.2, lon: -51.9 }, AU: { lat: -25.3, lon: 133.8 },
        JP: { lat: 36.2, lon: 138.3 }, ZA: { lat: -30.6, lon: 22.9 }, NG: { lat: 9.1, lon: 8.7 },
        EG: { lat: 26.8, lon: 30.8 }, IR: { lat: 32.4, lon: 53.7 }, PK: { lat: 30.4, lon: 69.3 },
        ID: { lat: -0.8, lon: 113.9 }, TR: { lat: 38.9, lon: 35.2 }, MX: { lat: 23.6, lon: -102.6 },
        CA: { lat: 56.1, lon: -106.3 }, KR: { lat: 35.9, lon: 127.8 }
    };

    function init() {
        _visible = App.isLayerActive('outages');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'outages') { _visible = e.visible; if (_visible && _data.length === 0) refresh(); _render(); }
        });
        EventBus.on('timerange:change', refresh);
        if (_visible) refresh();
        Scheduler.start('outages', refresh, Config.INTERVALS.outages);
    }

    function refresh() {
        var now = Math.floor(Date.now() / 1000);
        var from = now - 86400; /* last 24 hours */
        var url = Config.API.outages.replace('{from}', from).replace('{until}', now);

        Fetcher.get(url, {
            sourceKey: 'outages',
            fallbackUrl: 'data/fallback-outages.json',
            useCorsProxy: true,
            cacheTTL: Config.INTERVALS.outages,
            transform: _transformIoda
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('outages', _data.length);
            EventBus.emit('data:outages:updated', _data);
            _render();
        });
    }

    function _transformIoda(raw) {
        /* IODA returns {data: [...]} or may be an array directly */
        var items = (raw && raw.data) || (Array.isArray(raw) ? raw : []);
        if (!items.length) return [];
        return items.map(function (item) {
            var entity = item.entity || {};
            var code = (entity.code || '').toUpperCase();
            var coords = COUNTRY_COORDS[code] || { lat: 0, lon: 0 };
            return {
                id: (entity.code || '') + '-' + (item.from || Math.random()),
                lon: coords.lon + (Math.random() - 0.5) * 2,
                lat: coords.lat + (Math.random() - 0.5) * 2,
                type: 'outage',
                title: (entity.name || code || 'Internet outage'),
                source: item.datasource || 'IODA',
                country: entity.name || code || '',
                timestamp: item.from ? item.from * 1000 : Date.now()
            };
        }).filter(function (d) { return d.lon !== 0 && d.lat !== 0; });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('outages');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'outages',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: 15000,
            getFillColor: [255, 170, 0, 160],
            radiusMinPixels: 3,
            radiusMaxPixels: 18,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('outages', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
