/* ==========================================================================
   Kytran News — Social Media Trending Layer
   Viral events and trending topics as ScatterplotLayer
   ========================================================================== */

var Social = (function () {
    'use strict';

    var _data = [];
    var _visible = true;

    function init() {
        _visible = App.isLayerActive('social');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'social') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('social', refresh, Config.INTERVALS.social || 300000);
    }

    function refresh() {
        Fetcher.get('data/social-trends.json', {
            sourceKey: 'social',
            cacheTTL: Config.INTERVALS.social || 300000
        }).then(function (raw) {
            _data = (raw && raw.trends) ? raw.trends : [];
            App.updateLayerCount('social', _data.length);
            EventBus.emit('data:social:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('social');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'social',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                var vol = d.volume || 1000;
                if (vol >= 100000) return 35000;
                if (vol >= 50000) return 25000;
                if (vol >= 10000) return 16000;
                return 10000;
            },
            getFillColor: function (d) {
                if (d.sentiment === 'positive') return [76, 175, 80, 170];
                if (d.sentiment === 'negative') return [244, 67, 54, 170];
                return [224, 64, 251, 160];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 35,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('social', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
