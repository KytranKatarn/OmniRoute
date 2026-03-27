/* ==========================================================================
   Kytran News — Ships / Vessel Tracking Layer
   Major shipping lanes and port activity
   Uses static dataset + simulated vessel movement along routes
   ========================================================================== */

var Ships = (function () {
    'use strict';

    var _vessels = [];
    var _routes = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('ships');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'ships') {
                _visible = e.visible;
                if (_visible && _vessels.length === 0) refresh();
                else _render();
            }
        });
        if (_visible) refresh();
    }

    function refresh() {
        Fetcher.get('data/shipping-data.json', {
            sourceKey: 'ships',
            cacheTTL: 600000
        }).then(function (data) {
            if (!data) return;
            _routes = data.routes || [];
            _vessels = _generateVessels(data);
            App.updateLayerCount('ships', _vessels.length);
            if (_visible) _render();
        });
    }

    function _generateVessels(data) {
        var vessels = [];
        var ports = data.ports || [];
        var routes = data.routes || [];

        /* Place vessels at ports */
        ports.forEach(function (port) {
            for (var i = 0; i < (port.traffic || 1); i++) {
                vessels.push({
                    id: port.name + '-' + i,
                    lon: port.lon + (Math.random() - 0.5) * 0.5,
                    lat: port.lat + (Math.random() - 0.5) * 0.5,
                    type: 'ship',
                    subtype: 'port',
                    title: port.name + ' — vessel ' + (i + 1),
                    port: port.name,
                    country: port.country
                });
            }
        });

        /* Place vessels along routes */
        routes.forEach(function (route) {
            var numVessels = route.density || 3;
            for (var i = 0; i < numVessels; i++) {
                var t = Math.random();
                var pts = route.points;
                var segIdx = Math.floor(t * (pts.length - 1));
                var segT = (t * (pts.length - 1)) - segIdx;
                if (segIdx >= pts.length - 1) { segIdx = pts.length - 2; segT = 1; }
                var lon = pts[segIdx][0] + (pts[segIdx + 1][0] - pts[segIdx][0]) * segT;
                var lat = pts[segIdx][1] + (pts[segIdx + 1][1] - pts[segIdx][1]) * segT;
                vessels.push({
                    id: route.name + '-' + i,
                    lon: lon + (Math.random() - 0.5) * 0.3,
                    lat: lat + (Math.random() - 0.5) * 0.3,
                    type: 'ship',
                    subtype: 'transit',
                    title: route.name + ' — vessel ' + (i + 1),
                    route: route.name,
                    country: ''
                });
            }
        });

        return vessels;
    }

    function _render() {
        if (!_visible) {
            KytranMap.removeLayer('ships');
            KytranMap.removeLayer('shipping-routes');
            return;
        }

        /* Shipping route lines */
        if (_routes.length > 0) {
            var routeData = _routes.map(function (r) {
                return { path: r.points, name: r.name };
            });
            var routeLayer = new deck.PathLayer({
                id: 'shipping-routes',
                data: routeData,
                getPath: function (d) { return d.path; },
                getColor: [0, 150, 200, 40],
                getWidth: 2,
                widthMinPixels: 1,
                widthMaxPixels: 3,
                pickable: false,
                parameters: { depthTest: false }
            });
            KytranMap.setLayer('shipping-routes', routeLayer);
        }

        /* Vessel dots */
        if (_vessels.length > 0) {
            var vesselLayer = new deck.ScatterplotLayer({
                id: 'ships',
                data: _vessels,
                getPosition: function (d) { return [d.lon, d.lat]; },
                getRadius: function (d) { return d.subtype === 'port' ? 5000 : 4000; },
                getFillColor: function (d) {
                    return d.subtype === 'port' ? [0, 180, 220, 180] : [0, 140, 180, 140];
                },
                radiusMinPixels: 2,
                radiusMaxPixels: 6,
                pickable: true,
                autoHighlight: true,
                highlightColor: [255, 255, 255, 60],
                parameters: { depthTest: false }
            });
            KytranMap.setLayer('ships', vesselLayer);
        }
    }

    /* Animate vessel positions along routes */
    function renderPulse() {
        /* Subtle drift — not full re-render, just shift transit vessels slightly */
    }

    function getData() { return _vessels; }

    return { init: init, refresh: refresh, getData: getData, renderPulse: renderPulse };
})();
