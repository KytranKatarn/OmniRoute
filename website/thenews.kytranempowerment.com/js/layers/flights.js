/* ==========================================================================
   Kytran News — Flights Layer
   Live aircraft positions from OpenSky Network API (free, no key)
   ========================================================================== */

var Flights = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('flights');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'flights') { _visible = e.visible; _render(); }
        });
        if (_visible) refresh();
        Scheduler.start('flights', refresh, 15000); /* 15 sec — OpenSky rate limit */
    }

    function refresh() {
        if (!_visible) return;
        /* OpenSky Network — returns all aircraft in bounding box or worldwide */
        Fetcher.get('https://opensky-network.org/api/states/all', {
            sourceKey: 'flights',
            fallbackUrl: 'data/fallback-flights.json',
            useCorsProxy: true,
            cacheTTL: 10000,
            transform: _transform
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('flights', _data.length);
            _render();
        });
    }

    function _transform(data) {
        if (!data || !data.states) return [];
        /* OpenSky returns: [icao24, callsign, origin, timePosition, lastContact,
           lon, lat, baroAlt, onGround, velocity, heading, vertRate, sensors, geoAlt,
           squawk, spi, positionSource, category] */
        var results = [];
        var states = data.states;
        /* Limit to 500 for performance */
        var limit = Math.min(states.length, 500);
        for (var i = 0; i < limit; i++) {
            var s = states[i];
            if (s[5] == null || s[6] == null) continue; /* no position */
            if (s[8]) continue; /* on ground — skip */
            results.push({
                id: s[0],
                lon: s[5],
                lat: s[6],
                type: 'flight',
                title: (s[1] || '').trim() || s[0],
                callsign: (s[1] || '').trim(),
                origin: s[2] || '',
                altitude: s[7] || 0,
                velocity: s[9] || 0,
                heading: s[10] || 0,
                timestamp: (s[3] || 0) * 1000
            });
        }
        return results;
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('flights');
            return;
        }

        var layer = new deck.ScatterplotLayer({
            id: 'flights',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: 3000,
            getFillColor: [0, 200, 255, 120],
            radiusMinPixels: 1,
            radiusMaxPixels: 4,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 80],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('flights', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
