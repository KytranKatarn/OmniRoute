/* ==========================================================================
   Kytran News — Military / Nuclear Sites Layer
   Static dataset rendered as ScatterplotLayer with icons
   ========================================================================== */

var Military = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('military');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'military') { _visible = e.visible; _render(); }
        });
        /* Static data — load once */
        Fetcher.get(Config.FALLBACKS.military, {
            sourceKey: 'military',
            cacheTTL: 86400000, /* 24 hours */
            transform: _transformGeoJson
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('military', _data.length);
            _render();
        });
    }

    function _transformGeoJson(data) {
        if (!data || !data.features) return [];
        return data.features.map(function (f) {
            var p = f.properties || {};
            var coords = (f.geometry && f.geometry.coordinates) || [0, 0];
            return {
                id: p.name || Math.random().toString(36).substr(2, 9),
                lon: coords[0],
                lat: coords[1],
                type: 'military',
                subtype: p.type || 'base',
                title: p.name || 'Military site',
                country: p.country || '',
                timestamp: null
            };
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('military');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'military',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: 8000,
            getFillColor: function (d) {
                if (d.subtype === 'nuclear') return [255, 0, 0, 200];
                if (d.subtype === 'missile') return [255, 100, 0, 190];
                return [118, 255, 3, 160];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 12,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('military', layer);
    }

    function refresh() { /* static data, no refresh needed */ }
    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
