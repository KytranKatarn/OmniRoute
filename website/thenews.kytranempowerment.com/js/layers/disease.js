/* ==========================================================================
   Kytran News — Disease Outbreaks Layer
   disease.sh — COVID-19 + disease data per country
   ========================================================================== */

var Disease = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('disease');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'disease') { _visible = e.visible; if (_visible && _data.length === 0) refresh(); _render(); }
        });
        if (_visible) refresh();
    }

    function refresh() {
        if (!_visible) return;
        Fetcher.get(Config.API.disease, {
            sourceKey: 'disease',
            fallbackUrl: 'data/fallback-disease.json',
            cacheTTL: 600000,
            transform: _transform
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('disease', _data.length);
            EventBus.emit('data:disease:updated', _data);
            _render();
        });
    }

    function _transform(data) {
        /* disease.sh returns [{country, countryInfo: {lat, long, flag}, todayCases, todayDeaths, active, ...}] */
        if (!Array.isArray(data)) return [];
        return data.filter(function (d) {
            return d.countryInfo && d.countryInfo.lat && d.countryInfo.long && d.active > 0;
        }).slice(0, 80).map(function (d) {
            var severity = 'low';
            if (d.todayCases > 10000) severity = 'critical';
            else if (d.todayCases > 1000) severity = 'high';
            else if (d.todayCases > 100) severity = 'medium';
            return {
                id: d.country || Math.random().toString(36).substr(2, 9),
                lon: d.countryInfo.long,
                lat: d.countryInfo.lat,
                type: 'disease',
                title: d.country + ' — ' + (d.todayCases || 0).toLocaleString() + ' new cases',
                country: d.country || '',
                active: d.active || 0,
                todayCases: d.todayCases || 0,
                todayDeaths: d.todayDeaths || 0,
                severity: severity,
                flag: d.countryInfo.flag || '',
                timestamp: d.updated || Date.now()
            };
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('disease');
            return;
        }

        var layer = new deck.ScatterplotLayer({
            id: 'disease',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.severity === 'critical') return 35000;
                if (d.severity === 'high') return 25000;
                if (d.severity === 'medium') return 18000;
                return 12000;
            },
            getFillColor: function (d) {
                if (d.severity === 'critical') return [255, 0, 0, 200];
                if (d.severity === 'high') return [255, 100, 0, 180];
                if (d.severity === 'medium') return [0, 255, 136, 160];
                return [0, 200, 100, 130];
            },
            radiusMinPixels: 5,
            radiusMaxPixels: 20,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('disease', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
