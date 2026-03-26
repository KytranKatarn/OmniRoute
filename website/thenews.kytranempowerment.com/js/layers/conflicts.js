/* ==========================================================================
   Kytran News — Conflicts Layer
   GDELT conflict events as ScatterplotLayer
   ========================================================================== */

var Conflicts = (function () {
    'use strict';

    var _data = [];
    var _visible = true;

    function init() {
        _visible = App.isLayerActive('conflicts');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'conflicts') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('conflicts', refresh, Config.INTERVALS.conflicts);
    }

    function refresh() {
        var url = Config.getApiUrl('conflicts', App.getTimeRange());
        Fetcher.get(url, {
            sourceKey: 'conflicts',
            fallbackUrl: Config.FALLBACKS.conflicts,
            useCorsProxy: true,
            cacheTTL: Config.INTERVALS.conflicts,
            transform: Transforms.gdeltGeo
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('conflicts', _data.length);
            EventBus.emit('data:conflicts:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('conflicts');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'conflicts',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.severity === 'critical') return 30000;
                if (d.severity === 'high') return 20000;
                if (d.severity === 'medium') return 12000;
                return 8000;
            },
            getFillColor: function (d) {
                if (d.severity === 'critical') return [255, 0, 0, 200];
                if (d.severity === 'high') return [255, 59, 59, 180];
                if (d.severity === 'medium') return [255, 100, 100, 150];
                return [255, 140, 140, 120];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 30,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('conflicts', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
