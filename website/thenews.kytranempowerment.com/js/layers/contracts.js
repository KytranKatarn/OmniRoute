/* ==========================================================================
   Kytran News — Government Contracts Layer
   W.A.T.C.H. civic data — contract awards by jurisdiction
   ========================================================================== */

var Contracts = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('contracts');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'contracts') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('contracts', refresh, Config.INTERVALS.contracts || 600000);
    }

    function refresh() {
        var timespan = App.getTimeRange();
        var url = Config.WATCH_API + '/events?type=contract&timespan=' + (timespan || '30d') + '&limit=200';
        Fetcher.get(url, {
            sourceKey: 'contracts',
            fallbackUrl: Config.FALLBACKS.contracts,
            useCorsProxy: false,
            cacheTTL: Config.INTERVALS.contracts || 600000
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('contracts', _data.length);
            EventBus.emit('data:contracts:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('contracts');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'contracts',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                var amt = d.amount || 0;
                if (amt > 100000000) return 40000;
                if (amt > 10000000) return 28000;
                if (amt > 1000000) return 18000;
                return 10000;
            },
            getFillColor: function (d) {
                if (d.level === 'federal') return [0, 191, 165, 200];
                if (d.level === 'provincial') return [0, 191, 165, 150];
                return [0, 191, 165, 100];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 25,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('contracts', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
