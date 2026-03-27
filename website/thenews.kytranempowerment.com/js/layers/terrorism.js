/* ==========================================================================
   Kytran News — Terrorism Incidents Layer
   GDELT terrorism events as ScatterplotLayer
   ========================================================================== */

var Terrorism = (function () {
    'use strict';

    var _data = [];
    var _visible = true;

    function init() {
        _visible = App.isLayerActive('terrorism');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'terrorism') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('terrorism', refresh, Config.INTERVALS.terrorism || 300000);
    }

    function refresh() {
        var url = Config.getApiUrl('terrorism', App.getTimeRange());
        Fetcher.get(url, {
            sourceKey: 'terrorism',
            fallbackUrl: 'data/fallback-terrorism.json',
            useCorsProxy: true,
            cacheTTL: Config.INTERVALS.terrorism || 300000,
            transform: Transforms.gdeltGeo
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('terrorism', _data.length);
            EventBus.emit('data:terrorism:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('terrorism');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'terrorism',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.severity === 'critical') return 30000;
                if (d.severity === 'high') return 22000;
                if (d.severity === 'medium') return 14000;
                return 8000;
            },
            getFillColor: function (d) {
                if (d.severity === 'critical') return [183, 28, 28, 220];
                if (d.severity === 'high') return [211, 47, 47, 190];
                if (d.severity === 'medium') return [229, 57, 53, 160];
                return [239, 83, 80, 130];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 30,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('terrorism', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
