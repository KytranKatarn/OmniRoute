/* ==========================================================================
   Kytran News — Weather Alerts Layer
   NWS active alerts as GeoJsonLayer polygons
   ========================================================================== */

var Weather = (function () {
    'use strict';

    var _data = [];
    var _raw = null;
    var _visible = true;

    function init() {
        _visible = App.isLayerActive('weather');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'weather') { _visible = e.visible; _render(); }
        });
        refresh();
        Scheduler.start('weather', refresh, Config.INTERVALS.weather);
    }

    function refresh() {
        Fetcher.get(Config.API.nws_alerts, {
            sourceKey: 'weather',
            fallbackUrl: Config.FALLBACKS.weather,
            useCorsProxy: false,
            cacheTTL: Config.INTERVALS.weather,
            transform: function (data) {
                _raw = data;
                return Transforms.nwsAlerts(data);
            }
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('weather', _data.length);
            EventBus.emit('data:weather:updated', _data);
            _render();
        });
    }

    function _render() {
        if (!_visible || !_raw || !_raw.features) {
            KytranMap.removeLayer('weather');
            return;
        }

        /* Filter to only features with geometry */
        var features = _raw.features.filter(function (f) {
            return f.geometry && f.geometry.coordinates;
        });
        if (features.length === 0) {
            KytranMap.removeLayer('weather');
            return;
        }

        var geojson = { type: 'FeatureCollection', features: features };

        var layer = new deck.GeoJsonLayer({
            id: 'weather',
            data: geojson,
            filled: true,
            stroked: true,
            getFillColor: function (f) {
                var sev = (f.properties.severity || '').toLowerCase();
                if (sev === 'extreme') return [255, 0, 0, 80];
                if (sev === 'severe') return [255, 109, 0, 60];
                if (sev === 'moderate') return [255, 204, 0, 50];
                return [64, 196, 255, 40];
            },
            getLineColor: function (f) {
                var sev = (f.properties.severity || '').toLowerCase();
                if (sev === 'extreme') return [255, 0, 0, 180];
                if (sev === 'severe') return [255, 109, 0, 150];
                if (sev === 'moderate') return [255, 204, 0, 120];
                return [64, 196, 255, 100];
            },
            getLineWidth: 1,
            lineWidthMinPixels: 1,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 40],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('weather', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
