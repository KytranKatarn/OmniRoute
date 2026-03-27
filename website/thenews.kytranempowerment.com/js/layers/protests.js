/* ==========================================================================
   Kytran News — Protests & Civil Unrest Layer
   GDELT protest/demonstration events as ScatterplotLayer
   ========================================================================== */

var Protests = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('protests');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'protests') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('protests', refresh, Config.INTERVALS.protests || 300000);
    }

    function refresh() {
        var timespan = App.getTimeRange();
        var url = Config.getApiUrl('protests', timespan);
        Fetcher.get(url, {
            sourceKey: 'protests',
            fallbackUrl: 'data/fallback-protests.json',
            useCorsProxy: true,
            cacheTTL: Config.INTERVALS.protests || 300000,
            transform: _transform
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('protests', _data.length);
            EventBus.emit('data:protests:updated', _data);
            _render();
        });
    }

    function _transform(raw) {
        if (!raw) return [];
        var features = raw.features || raw;
        if (!Array.isArray(features)) return [];
        return features.map(function (f) {
            var props = f.properties || f;
            var coords = (f.geometry && f.geometry.coordinates) || [props.lon || 0, props.lat || 0];
            var name = props.name || props.title || props.ActionGeo_FullName || 'Protest event';
            var severity = 'low';
            var tone = parseFloat(props.AvgTone || props.goldsteinscale || 0);
            if (tone < -6) {
                severity = 'critical';
            } else if (tone < -4) {
                severity = 'high';
            } else if (tone < -2) {
                severity = 'medium';
            }
            return {
                id: props.GLOBALEVENTID || props.url_mobile || Math.random().toString(36).substr(2, 9),
                lon: coords[0],
                lat: coords[1],
                type: 'protests',
                severity: severity,
                title: name.substring(0, 150),
                source: props.domain || props.sourceurl || '',
                country: props.ActionGeo_CountryCode || props.country || '',
                timestamp: props.dateadded ? new Date(
                    props.dateadded.substring(0, 4) + '-' +
                    props.dateadded.substring(4, 6) + '-' +
                    props.dateadded.substring(6, 8)
                ).getTime() : Date.now()
            };
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('protests');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'protests',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.severity === 'critical') return 28000;
                if (d.severity === 'high') return 20000;
                if (d.severity === 'medium') return 14000;
                return 8000;
            },
            getFillColor: function (d) {
                if (d.severity === 'critical') return [255, 20, 147, 220];
                if (d.severity === 'high') return [255, 50, 160, 190];
                if (d.severity === 'medium') return [255, 100, 180, 160];
                return [255, 140, 200, 130];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 25,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('protests', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
