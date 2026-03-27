/* ==========================================================================
   Kytran News — Space Weather Layer
   NOAA SWPC alerts as ScatterplotLayer (solar flares, geomagnetic storms)
   ========================================================================== */

var SpaceWeather = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('spaceweather');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'spaceweather') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('spaceweather', refresh, Config.INTERVALS.spaceweather || 300000);
    }

    function refresh() {
        Fetcher.get('https://services.swpc.noaa.gov/products/alerts.json', {
            sourceKey: 'spaceweather',
            fallbackUrl: 'data/fallback-spaceweather.json',
            useCorsProxy: false,
            cacheTTL: Config.INTERVALS.spaceweather || 300000,
            transform: _transform
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('spaceweather', _data.length);
            EventBus.emit('data:spaceweather:updated', _data);
            _render();
        });
    }

    function _transform(raw) {
        if (!raw || !Array.isArray(raw)) return [];
        /* Impact points: north pole, south pole, equatorial zones */
        var impactPoints = [
            { lon: 0, lat: 78, label: 'Arctic' },
            { lon: 0, lat: -78, label: 'Antarctic' },
            { lon: 0, lat: 0, label: 'Equator (Atlantic)' },
            { lon: 100, lat: 0, label: 'Equator (Pacific)' },
            { lon: -80, lat: 0, label: 'Equator (Americas)' }
        ];
        var results = [];
        raw.forEach(function (alert) {
            var msg = (alert.message || '').toLowerCase();
            var severity = 'low';
            var alertType = 'unknown';
            if (msg.indexOf('x-class') !== -1 || msg.indexOf('extreme') !== -1 || msg.indexOf('g5') !== -1 || msg.indexOf('g4') !== -1 || msg.indexOf('s4') !== -1 || msg.indexOf('s5') !== -1) {
                severity = 'critical';
            } else if (msg.indexOf('m-class') !== -1 || msg.indexOf('severe') !== -1 || msg.indexOf('g3') !== -1 || msg.indexOf('s3') !== -1) {
                severity = 'high';
            } else if (msg.indexOf('strong') !== -1 || msg.indexOf('g2') !== -1 || msg.indexOf('s2') !== -1) {
                severity = 'medium';
            }
            if (msg.indexOf('solar flare') !== -1 || msg.indexOf('flare') !== -1) {
                alertType = 'solar_flare';
            } else if (msg.indexOf('geomagnetic') !== -1 || msg.indexOf('magnetic') !== -1) {
                alertType = 'geomagnetic_storm';
            } else if (msg.indexOf('radiation') !== -1 || msg.indexOf('proton') !== -1) {
                alertType = 'radiation_storm';
            } else if (msg.indexOf('cme') !== -1 || msg.indexOf('coronal') !== -1) {
                alertType = 'cme';
            }
            var ts = alert.issue_datetime ? new Date(alert.issue_datetime).getTime() : Date.now();
            impactPoints.forEach(function (pt, idx) {
                results.push({
                    id: (alert.product_id || Math.random().toString(36).substr(2, 9)) + '-' + idx,
                    lon: pt.lon,
                    lat: pt.lat,
                    type: 'spaceweather',
                    alertType: alertType,
                    severity: severity,
                    title: (alert.message || 'Space weather alert').substring(0, 120),
                    region: pt.label,
                    timestamp: ts
                });
            });
        });
        return results;
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('spaceweather');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'spaceweather',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.severity === 'critical') return 80000;
                if (d.severity === 'high') return 55000;
                if (d.severity === 'medium') return 35000;
                return 20000;
            },
            getFillColor: function (d) {
                if (d.severity === 'critical') return [255, 215, 0, 220];
                if (d.severity === 'high') return [255, 200, 0, 180];
                if (d.severity === 'medium') return [255, 230, 50, 150];
                return [255, 240, 100, 120];
            },
            radiusMinPixels: 4,
            radiusMaxPixels: 40,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('spaceweather', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
