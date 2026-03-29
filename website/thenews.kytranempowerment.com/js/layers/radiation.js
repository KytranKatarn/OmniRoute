/* ==========================================================================
   Kytran News — Nuclear Radiation Monitoring Layer
   Safecast API — live radiation measurements
   ========================================================================== */

var Radiation = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('radiation');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'radiation') { _visible = e.visible; if (_visible && _data.length === 0) refresh(); _render(); }
        });
        if (_visible) refresh();
    }

    function _transform(raw) {
        /* Safecast returns [{latitude, longitude, value, unit, captured_at, ...}] */
        if (!Array.isArray(raw)) return [];
        return raw.filter(function (m) {
            return m.latitude && m.longitude && m.value != null;
        }).map(function (m) {
            var cpm = parseFloat(m.value) || 0;
            /* Convert CPM to approx nSv/h (rough: 1 CPM ~ 10 nSv/h for typical GM tube) */
            var nsvh = Math.round(cpm * 10);
            var status = 'normal';
            if (nsvh > 500) status = 'critical';
            else if (nsvh > 300) status = 'elevated';
            else if (nsvh > 150) status = 'moderate';
            return {
                id: m.id || Math.random().toString(36).substr(2, 9),
                lon: parseFloat(m.longitude),
                lat: parseFloat(m.latitude),
                type: 'radiation',
                title: (m.device_id ? 'Device ' + m.device_id : 'Safecast Sensor') + ' — ' + nsvh + ' nSv/h',
                country: '',
                reading: nsvh,
                unit: 'nSv/h',
                status: status,
                network: 'Safecast',
                timestamp: m.captured_at ? new Date(m.captured_at).getTime() : Date.now()
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

    function refresh() {
        if (!_visible) return;
        Fetcher.get(Config.API.radiation, {
            sourceKey: 'radiation',
            fallbackUrl: 'data/radiation-monitors.json',
            useCorsProxy: true,
            cacheTTL: 600000, /* 10 min */
            transform: _transform
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('radiation', _data.length);
            _render();
        });
    }
    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
