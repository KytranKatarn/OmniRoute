/* ==========================================================================
   Kytran News — Parliament Layer
   W.A.T.C.H. civic data — bills, votes, debates in Ottawa + capitals
   ========================================================================== */

var Parliament = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('parliament');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'parliament') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('parliament', refresh, Config.INTERVALS.parliament || 600000);
    }

    function refresh() {
        /* Civic data uses 1y for parliament — bills have long lifecycles */
        var url = Config.WATCH_API + '/events?type=bill,vote,debate&timespan=1y&limit=200';
        Fetcher.get(url, {
            sourceKey: 'parliament',
            fallbackUrl: Config.FALLBACKS.parliament,
            useCorsProxy: false,
            cacheTTL: Config.INTERVALS.parliament || 600000
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('parliament', _data.length);
            EventBus.emit('data:parliament:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('parliament');
            KytranMap.removeLayer('parliament-pulse');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'parliament',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.event_type === 'vote') return 22000;
                if (d.event_type === 'bill') return 16000;
                return 12000;
            },
            getFillColor: function (d) {
                if (d.event_type === 'vote') return [255, 215, 64, 220];
                if (d.event_type === 'bill') return [255, 215, 64, 170];
                return [255, 215, 64, 120];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 20,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('parliament', layer);
    }

    function renderPulse() {
        var votes = _data.filter(function (d) { return d.event_type === 'vote'; });
        if (!_visible || votes.length === 0) { KytranMap.removeLayer('parliament-pulse'); return; }

        var now = Date.now();
        var pulseLayer = new deck.ScatterplotLayer({
            id: 'parliament-pulse',
            data: votes,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function () {
                var cycle = ((now / 1000) % 3) / 3;
                return 20000 * (1 + cycle * 2);
            },
            stroked: true,
            filled: false,
            getLineColor: function () {
                var cycle = ((now / 1000) % 3) / 3;
                return [255, 215, 64, Math.floor(180 * (1 - cycle))];
            },
            getLineWidth: 2,
            lineWidthMinPixels: 1,
            radiusMinPixels: 5,
            radiusMaxPixels: 40,
            pickable: false,
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('parliament-pulse', pulseLayer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData, renderPulse: renderPulse };
})();
