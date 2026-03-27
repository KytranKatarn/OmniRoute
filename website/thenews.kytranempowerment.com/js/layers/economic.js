/* ==========================================================================
   Kytran News — Economic Indicators Layer
   Major financial centers and market status as ScatterplotLayer
   ========================================================================== */

var Economic = (function () {
    'use strict';

    var _data = [];
    var _visible = true;

    function init() {
        _visible = App.isLayerActive('economic');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'economic') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('economic', refresh, Config.INTERVALS.economic || 600000);
    }

    function refresh() {
        Fetcher.get('data/economic-data.json', {
            sourceKey: 'economic',
            cacheTTL: Config.INTERVALS.economic || 600000
        }).then(function (raw) {
            _data = (raw && raw.centers) ? raw.centers : [];
            App.updateLayerCount('economic', _data.length);
            EventBus.emit('data:economic:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('economic');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'economic',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function () { return 20000; },
            getFillColor: function (d) {
                if (d.status === 'up') return [76, 175, 80, 180];
                if (d.status === 'down') return [244, 67, 54, 180];
                if (d.status === 'volatile') return [255, 193, 7, 180];
                return [158, 158, 158, 120];
            },
            radiusMinPixels: 4,
            radiusMaxPixels: 25,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('economic', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
