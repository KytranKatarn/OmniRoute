/* ==========================================================================
   Kytran News — Public Spending Layer
   W.A.T.C.H. civic data — government spending by department/jurisdiction
   ========================================================================== */

var Spending = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

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
        /* Civic data uses 1y for spending — fiscal year cycles */
        var url = Config.WATCH_API + '/events?type=spending&timespan=1y&limit=200';
        Fetcher.get(url, {
            sourceKey: 'spending',
            fallbackUrl: Config.FALLBACKS.spending,
            useCorsProxy: false,
            cacheTTL: Config.INTERVALS.spending || 600000
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('spending', _data.length);
            EventBus.emit('data:spending:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('spending');
            return;
        }

        var CATEGORY_COLORS = {
            capital:  [33, 150, 243, 180],
            operating: [105, 240, 174, 180],
            grants:   [255, 235, 59, 180],
            transfer: [255, 152, 0, 180]
        };

        var layer = new deck.ScatterplotLayer({
            id: 'spending',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                var amt = d.amount || 0;
                if (amt > 1000000000) return 45000;
                if (amt > 100000000) return 32000;
                if (amt > 10000000) return 20000;
                return 12000;
            },
            getFillColor: function (d) {
                var meta = {};
                try { meta = JSON.parse(d.metadata || '{}'); } catch (e) {}
                return CATEGORY_COLORS[meta.category] || [105, 240, 174, 150];
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
