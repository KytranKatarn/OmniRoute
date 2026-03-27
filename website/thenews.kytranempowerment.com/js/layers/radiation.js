/* ==========================================================================
   Kytran News — Nuclear Radiation Monitoring Layer
   Static IAEA-style monitoring station dataset as ScatterplotLayer
   ========================================================================== */

var Radiation = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('radiation');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'radiation') { _visible = e.visible; _render(); }
        });
        /* Static data — load once */
        Fetcher.get('data/radiation-monitors.json', {
            sourceKey: 'radiation',
            cacheTTL: 86400000, /* 24 hours */
            transform: _transform
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('radiation', _data.length);
            _render();
        });
    }

    function _transform(raw) {
        if (!raw || !Array.isArray(raw)) return [];
        return raw.map(function (station) {
            var reading = station.reading_nsvh || 0;
            var status = 'normal';
            if (reading > 500) {
                status = 'critical';
            } else if (reading > 300) {
                status = 'elevated';
            } else if (reading > 150) {
                status = 'moderate';
            }
            return {
                id: station.id || Math.random().toString(36).substr(2, 9),
                lon: station.lon || 0,
                lat: station.lat || 0,
                type: 'radiation',
                title: station.name || 'Monitoring station',
                country: station.country || '',
                reading: reading,
                unit: 'nSv/h',
                status: status,
                network: station.network || 'IAEA',
                timestamp: station.last_update ? new Date(station.last_update).getTime() : Date.now()
            };
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('radiation');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'radiation',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.status === 'critical') return 25000;
                if (d.status === 'elevated') return 18000;
                if (d.status === 'moderate') return 12000;
                return 8000;
            },
            getFillColor: function (d) {
                if (d.status === 'critical') return [255, 0, 0, 220];
                if (d.status === 'elevated') return [255, 80, 0, 190];
                if (d.status === 'moderate') return [220, 220, 0, 170];
                return [198, 255, 0, 150];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 18,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('radiation', layer);
    }

    function refresh() { /* static data, no refresh needed */ }
    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
