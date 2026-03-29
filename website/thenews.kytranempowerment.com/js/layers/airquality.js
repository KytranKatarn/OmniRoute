/* ==========================================================================
   Kytran News — Air Quality Layer
   WAQI (World Air Quality Index) live map bounds API
   ========================================================================== */

var AirQuality = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('airquality');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'airquality') { _visible = e.visible; if (_visible && _data.length === 0) refresh(); _render(); }
        });
        if (_visible) refresh();
    }

    function refresh() {
        if (!_visible) return;
        /* WAQI map bounds: latlng=lat1,lng1,lat2,lng2 (world view) */
        var url = Config.API.air_quality.replace('{bounds}', '-90,-180,90,180');
        Fetcher.get(url, {
            sourceKey: 'airquality',
            fallbackUrl: 'data/airquality-cities.json',
            useCorsProxy: true,
            cacheTTL: 600000, /* 10 min */
            transform: _transformWaqi
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('airquality', _data.length);
            _render();
        });
    }

    function _transformWaqi(raw) {
        /* WAQI returns {status: "ok", data: [{lat, lon, aqi, station: {name}}]} */
        if (!raw || raw.status !== 'ok' || !Array.isArray(raw.data)) return [];
        return raw.data.filter(function (d) {
            return d.lat && d.lon && d.aqi && d.aqi !== '-';
        }).map(function (d) {
            return {
                id: (d.station && d.station.name) || (d.lat + ',' + d.lon),
                lon: parseFloat(d.lon),
                lat: parseFloat(d.lat),
                aqi: parseInt(d.aqi, 10) || 0,
                type: 'airquality',
                title: (d.station && d.station.name) || 'Air Quality Station',
                timestamp: Date.now()
            };
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('airquality');
            return;
        }

        var layer = new deck.ScatterplotLayer({
            id: 'airquality',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) { return 15000 + d.aqi * 100; },
            getFillColor: function (d) {
                var aqi = d.aqi || 0;
                if (aqi <= 50) return [0, 228, 0, 140];        /* Good — green */
                if (aqi <= 100) return [255, 255, 0, 150];      /* Moderate — yellow */
                if (aqi <= 150) return [255, 126, 0, 160];      /* Unhealthy sensitive — orange */
                if (aqi <= 200) return [255, 0, 0, 170];        /* Unhealthy — red */
                if (aqi <= 300) return [143, 63, 151, 180];     /* Very unhealthy — purple */
                return [126, 0, 35, 200];                        /* Hazardous — maroon */
            },
            radiusMinPixels: 4,
            radiusMaxPixels: 25,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('airquality', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
