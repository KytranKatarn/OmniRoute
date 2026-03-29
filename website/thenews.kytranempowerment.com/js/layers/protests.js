/* ==========================================================================
   Kytran News — Protests & Civil Unrest Layer
   BBC RSS feed filtered for protest/demonstration keywords
   ========================================================================== */

var Protests = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    var PROTEST_KEYWORDS = /protest|demonstration|rally|unrest|march|strike|riot|uprising|dissent|crackdown|tear.?gas|water.?cannon/i;

    /* Major protest-prone cities for geo-placement */
    var PROTEST_LOCATIONS = [
        { lat: 48.86, lon: 2.35, label: 'Paris' },
        { lat: 51.51, lon: -0.13, label: 'London' },
        { lat: 52.52, lon: 13.41, label: 'Berlin' },
        { lat: 40.42, lon: -3.70, label: 'Madrid' },
        { lat: 38.90, lon: -77.04, label: 'Washington DC' },
        { lat: 28.61, lon: 77.21, label: 'New Delhi' },
        { lat: -23.55, lon: -46.63, label: 'Sao Paulo' },
        { lat: 30.04, lon: 31.24, label: 'Cairo' },
        { lat: 35.69, lon: 51.39, label: 'Tehran' },
        { lat: -33.87, lon: 151.21, label: 'Sydney' },
        { lat: 37.57, lon: 126.98, label: 'Seoul' },
        { lat: 41.01, lon: 28.98, label: 'Istanbul' },
        { lat: 55.76, lon: 37.62, label: 'Moscow' },
        { lat: -1.29, lon: 36.82, label: 'Nairobi' },
        { lat: 14.60, lon: 120.98, label: 'Manila' }
    ];

    function init() {
        _visible = App.isLayerActive('protests');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'protests') { _visible = e.visible; if (_visible && _data.length === 0) refresh(); _render(); }
        });
        EventBus.on('timerange:change', refresh);
        if (_visible) refresh();
        Scheduler.start('protests', refresh, Config.INTERVALS.protests || 300000);
    }

    function refresh() {
        Fetcher.get(Config.API.protests, {
            sourceKey: 'protests',
            fallbackUrl: 'data/fallback-protests.json',
            cacheTTL: Config.INTERVALS.protests || 300000,
            transform: _transformRss
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('protests', _data.length);
            EventBus.emit('data:protests:updated', _data);
            _render();
        });
    }

    function _transformRss(data) {
        if (!data || !data.items) return [];
        var locIdx = 0;
        return data.items.filter(function (item) {
            var text = (item.title || '') + ' ' + (item.description || '');
            return PROTEST_KEYWORDS.test(text);
        }).map(function (item) {
            var loc = PROTEST_LOCATIONS[locIdx % PROTEST_LOCATIONS.length];
            locIdx++;
            var lat = loc.lat + (Math.random() - 0.5) * 1.5;
            var lon = loc.lon + (Math.random() - 0.5) * 1.5;
            var severity = 'low';
            var text = (item.title || '') + ' ' + (item.description || '');
            if (/riot|uprising|crackdown|killed|dead/i.test(text)) severity = 'critical';
            else if (/clash|tear.?gas|water.?cannon|arrest/i.test(text)) severity = 'high';
            else if (/protest|demonstration|rally/i.test(text)) severity = 'medium';
            return {
                id: item.link || Math.random().toString(36).substr(2, 9),
                lon: lon,
                lat: lat,
                type: 'protests',
                severity: severity,
                title: (item.title || 'Protest event').substring(0, 150),
                source: 'BBC',
                url: item.link || '',
                country: loc.label,
                timestamp: item.pubDate ? new Date(item.pubDate).getTime() : Date.now()
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
