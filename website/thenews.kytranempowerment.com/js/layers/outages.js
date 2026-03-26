/* ==========================================================================
   Kytran News — Outages Layer
   News-derived power/internet outage markers
   ========================================================================== */

var Outages = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('outages');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'outages') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('outages', refresh, Config.INTERVALS.outages);
    }

    function refresh() {
        var tr = App.getTimeRange();
        var span = (Config.TIME_RANGES[tr] && Config.TIME_RANGES[tr].gdeltSpan) || '24h';
        var url = 'https://api.gdeltproject.org/api/v2/geo/geo?query=power outage OR internet outage OR blackout&format=geojson&timespan=' + span;

        Fetcher.get(url, {
            sourceKey: 'outages',
            fallbackUrl: Config.FALLBACKS.weather, /* reuse weather fallback structure */
            useCorsProxy: true,
            cacheTTL: Config.INTERVALS.outages,
            transform: function (data) {
                if (!data || !data.features) return [];
                return data.features.map(function (f) {
                    var p = f.properties || {};
                    var coords = (f.geometry && f.geometry.coordinates) || [0, 0];
                    return {
                        id: p.urlsourcex || Math.random().toString(36).substr(2, 9),
                        lon: coords[0],
                        lat: coords[1],
                        type: 'outage',
                        title: p.name || 'Reported outage',
                        source: p.domain || 'GDELT',
                        url: p.url || '',
                        timestamp: Date.now(),
                        severity: 'medium'
                    };
                });
            }
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('outages', _data.length);
            EventBus.emit('data:outages:updated', _data);
            _render();
        });
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
