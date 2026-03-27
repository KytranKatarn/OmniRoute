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
        var url = Config.getApiUrl('outages', App.getTimeRange());

        Fetcher.get(url, {
            sourceKey: 'outages',
            fallbackUrl: Config.FALLBACKS.weather,
            useCorsProxy: true,
            cacheTTL: Config.INTERVALS.outages,
            transform: function (data) { return Transforms.gdeltDocToGeo(data, 'outage'); }
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
