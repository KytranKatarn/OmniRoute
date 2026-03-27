/* ==========================================================================
   Kytran News — Heatmap Mode
   Toggle to aggregate all visible data points into a density heatmap
   ========================================================================== */

var Heatmap = (function () {
    'use strict';

    var _active = false;
    var _btn = null;

    function init() {
        _btn = document.getElementById('heatmap-btn');
        if (_btn) {
            _btn.addEventListener('click', toggle);
        }

        /* Keyboard shortcut: M for heatmap */
        document.addEventListener('keydown', function (e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            if (e.key === 'm' || e.key === 'M') toggle();
        });

        /* Re-render when data updates */
        var events = ['data:conflicts:updated', 'data:disasters:updated', 'data:weather:updated',
                      'data:cyber:updated', 'data:outages:updated'];
        events.forEach(function (evt) {
            EventBus.on(evt, function () { if (_active) _render(); });
        });
    }

    function toggle() {
        _active = !_active;
        if (_btn) _btn.classList.toggle('active', _active);
        if (_active) {
            _render();
        } else {
            KytranMap.removeLayer('heatmap');
        }
    }

    function _render() {
        var points = _collectAllPoints();
        if (points.length === 0) {
            KytranMap.removeLayer('heatmap');
            return;
        }

        var layer = new deck.HeatmapLayer({
            id: 'heatmap',
            data: points,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getWeight: function (d) { return d.weight || 1; },
            radiusPixels: 40,
            intensity: 1.5,
            threshold: 0.05,
            colorRange: [
                [0, 25, 50, 80],
                [0, 100, 100, 120],
                [0, 200, 150, 160],
                [255, 200, 0, 180],
                [255, 100, 0, 210],
                [255, 0, 0, 240]
            ],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('heatmap', layer);
    }

    function _collectAllPoints() {
        var points = [];

        /* Conflicts */
        if (typeof Conflicts !== 'undefined' && App.isLayerActive('conflicts')) {
            Conflicts.getData().forEach(function (d) {
                if (d.lat && d.lon) points.push({ lat: d.lat, lon: d.lon, weight: d.severity === 'critical' ? 5 : d.severity === 'high' ? 3 : 1 });
            });
        }

        /* Disasters */
        if (typeof Disasters !== 'undefined' && App.isLayerActive('disasters')) {
            var dd = Disasters.getData();
            (dd.earthquakes || []).forEach(function (d) {
                if (d.lat && d.lon) points.push({ lat: d.lat, lon: d.lon, weight: Math.max(1, (d.magnitude || 2) - 1) });
            });
            (dd.eonet || []).forEach(function (d) {
                if (d.lat && d.lon) points.push({ lat: d.lat, lon: d.lon, weight: 2 });
            });
        }

        /* Weather */
        if (typeof Weather !== 'undefined' && App.isLayerActive('weather')) {
            Weather.getData().forEach(function (d) {
                if (d.lat && d.lon) points.push({ lat: d.lat, lon: d.lon, weight: d.severity === 'extreme' ? 4 : d.severity === 'severe' ? 3 : 1 });
            });
        }

        /* Cyber */
        if (typeof Cyber !== 'undefined' && App.isLayerActive('cyber')) {
            Cyber.getData().forEach(function (d) {
                if (d.target) points.push({ lat: d.target[1], lon: d.target[0], weight: d.intensity || 1 });
                if (d.source) points.push({ lat: d.source[1], lon: d.source[0], weight: (d.intensity || 1) * 0.5 });
            });
        }

        /* Protests */
        if (typeof Protests !== 'undefined' && App.isLayerActive('protests')) {
            Protests.getData().forEach(function (d) {
                if (d.lat && d.lon) points.push({ lat: d.lat, lon: d.lon, weight: 2 });
            });
        }

        /* Terrorism */
        if (typeof Terrorism !== 'undefined' && App.isLayerActive('terrorism')) {
            Terrorism.getData().forEach(function (d) {
                if (d.lat && d.lon) points.push({ lat: d.lat, lon: d.lon, weight: 4 });
            });
        }

        return points;
    }

    function isActive() { return _active; }

    return { init: init, toggle: toggle, isActive: isActive };
})();
