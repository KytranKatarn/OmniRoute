/* ==========================================================================
   Kytran News — Internet Outages Layer
   BGP disruptions, cable cuts, censorship as ScatterplotLayer
   ========================================================================== */

var Internet = (function () {
    'use strict';

    var _data = [];
    var _visible = true;

    function init() {
        _visible = App.isLayerActive('internet');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'internet') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('internet', refresh, Config.INTERVALS.internet || 300000);
    }

    function refresh() {
        Fetcher.get('data/internet-outages.json', {
            sourceKey: 'internet',
            cacheTTL: Config.INTERVALS.internet || 300000
        }).then(function (raw) {
            _data = (raw && raw.outages) ? raw.outages : [];
            App.updateLayerCount('internet', _data.length);
            EventBus.emit('data:internet:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('internet');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'internet',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.severity === 'major') return 28000;
                if (d.severity === 'moderate') return 18000;
                return 10000;
            },
            getFillColor: function (d) {
                if (d.type === 'censorship') return [183, 28, 28, 200];
                if (d.type === 'bgp') return [255, 64, 129, 200];
                if (d.type === 'cable') return [255, 110, 64, 180];
                if (d.type === 'ddos') return [213, 0, 249, 180];
                return [255, 64, 129, 150];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 30,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('internet', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
