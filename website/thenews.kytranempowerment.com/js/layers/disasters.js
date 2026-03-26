/* ==========================================================================
   Kytran News — Disasters Layer
   USGS earthquakes + NASA EONET events
   ========================================================================== */

var Disasters = (function () {
    'use strict';

    var _earthquakes = [];
    var _eonet = [];
    var _visible = true;

    function init() {
        _visible = App.isLayerActive('disasters');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'disasters') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('disasters', refresh, Config.INTERVALS.disasters);
    }

    function refresh() {
        var eqUrl = Config.getEarthquakeUrl(App.getTimeRange());
        var eonetUrl = Config.API.eonet;

        Promise.all([
            Fetcher.get(eqUrl, {
                sourceKey: 'earthquakes',
                fallbackUrl: Config.FALLBACKS.disasters,
                cacheTTL: Config.INTERVALS.disasters,
                transform: Transforms.usgsEarthquakes
            }),
            Fetcher.get(eonetUrl, {
                sourceKey: 'eonet',
                fallbackUrl: Config.FALLBACKS.disasters,
                useCorsProxy: true,
                cacheTTL: 300000,
                transform: Transforms.eonetEvents
            })
        ]).then(function (results) {
            _earthquakes = results[0] || [];
            _eonet = results[1] || [];
            var total = _earthquakes.length + _eonet.length;
            App.updateLayerCount('disasters', total);
            EventBus.emit('data:disasters:updated', { earthquakes: _earthquakes, eonet: _eonet });
            _render();
        });
    }

    function _render() {
        if (!_visible) {
            KytranMap.removeLayer('earthquakes');
            KytranMap.removeLayer('eonet');
            return;
        }

        /* Earthquake ScatterplotLayer — size by magnitude */
        if (_earthquakes.length > 0) {
            var eqLayer = new deck.ScatterplotLayer({
                id: 'earthquakes',
                data: _earthquakes,
                getPosition: function (d) { return [d.lon, d.lat]; },
                getRadius: function (d) {
                    return Math.pow(2, (d.magnitude || 2)) * 2000;
                },
                getFillColor: function (d) {
                    var mag = d.magnitude || 0;
                    if (mag >= 7) return [255, 50, 0, 220];
                    if (mag >= 5.5) return [255, 109, 0, 200];
                    if (mag >= 4) return [255, 170, 0, 180];
                    return [255, 200, 80, 140];
                },
                radiusMinPixels: 3,
                radiusMaxPixels: 40,
                pickable: true,
                autoHighlight: true,
                highlightColor: [255, 255, 255, 60],
                parameters: { depthTest: false }
            });
            KytranMap.setLayer('earthquakes', eqLayer);
        }

        /* EONET events (wildfires, volcanoes, storms) */
        if (_eonet.length > 0) {
            var eoLayer = new deck.ScatterplotLayer({
                id: 'eonet',
                data: _eonet,
                getPosition: function (d) { return [d.lon, d.lat]; },
                getRadius: 15000,
                getFillColor: function (d) {
                    if (d.subtype === 'wildfire') return [255, 100, 0, 200];
                    if (d.subtype === 'volcano') return [200, 0, 0, 220];
                    if (d.subtype === 'storm') return [64, 196, 255, 180];
                    if (d.subtype === 'flood') return [0, 120, 255, 180];
                    return [255, 150, 0, 160];
                },
                radiusMinPixels: 5,
                radiusMaxPixels: 20,
                pickable: true,
                autoHighlight: true,
                parameters: { depthTest: false }
            });
            KytranMap.setLayer('eonet', eoLayer);
        }
    }

    function getData() { return { earthquakes: _earthquakes, eonet: _eonet }; }

    return { init: init, refresh: refresh, getData: getData };
})();
