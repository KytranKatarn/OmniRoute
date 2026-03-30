/* ==========================================================================
   Kytran News — Sanctions Layer
   Country-level choropleth from static sanctions data
   ========================================================================== */

var Sanctions = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('sanctions');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'sanctions') { _visible = e.visible; _render(); }
        });
        /* Static data — load once */
        Fetcher.get(Config.FALLBACKS.sanctions, {
            sourceKey: 'sanctions',
            cacheTTL: 86400000
        }).then(function (data) {
            var raw = (data && data.countries) || [];
            /* Normalize to ensure detail panel fields are present */
            _data = raw.map(function (d) {
                return {
                    type: 'sanction',
                    title: d.name || d.code || 'Sanctioned Entity',
                    lat: d.lat,
                    lon: d.lon,
                    severity: d.severity || 'targeted',
                    description: d.description || '',
                    url: d.url || ('https://ofac.treasury.gov/sanctions-programs-and-country-information'),
                    timestamp: null,
                    sources: d.sources || [],
                    code: d.code || '',
                    name: d.name || ''
                };
            });
            App.updateLayerCount('sanctions', _data.length);
            _render();
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('sanctions');
            return;
        }
        /* Render sanctioned countries as markers at centroids */
        var layer = new deck.ScatterplotLayer({
            id: 'sanctions',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.severity === 'comprehensive') return 40000;
                if (d.severity === 'sectoral') return 25000;
                return 15000;
            },
            getFillColor: function (d) {
                if (d.severity === 'comprehensive') return [244, 114, 182, 180];
                if (d.severity === 'sectoral') return [244, 114, 182, 120];
                return [244, 114, 182, 80];
            },
            radiusMinPixels: 4,
            radiusMaxPixels: 30,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('sanctions', layer);
    }

    function refresh() { /* static */ }
    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
