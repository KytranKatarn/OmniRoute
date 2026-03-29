/* ==========================================================================
   Kytran News — Terrorism Incidents Layer
   BBC RSS feed filtered for terrorism-related keywords
   ========================================================================== */

var Terrorism = (function () {
    'use strict';

    var _data = [];
    var _visible = true;

    var TERROR_KEYWORDS = /terrorism|terrorist|bombing|extremist|attack|isis|isil|militant|al.?qaeda|jihad|insurgent|suicide.?bomb|ied|hostage|radicaliz/i;

    var TERROR_REGIONS = [
        { lat: 33.8, lon: 36.3, label: 'Syria' },
        { lat: 34.5, lon: 69.2, label: 'Afghanistan' },
        { lat: 33.3, lon: 44.4, label: 'Iraq' },
        { lat: 12.0, lon: 45.0, label: 'Somalia' },
        { lat: 9.1, lon: 7.5, label: 'Nigeria' },
        { lat: 30.4, lon: 69.3, label: 'Pakistan' },
        { lat: 15.4, lon: 44.2, label: 'Yemen' },
        { lat: 13.5, lon: -2.0, label: 'Burkina Faso' },
        { lat: 17.6, lon: -4.0, label: 'Mali' },
        { lat: -4.3, lon: 15.3, label: 'DRC' },
        { lat: 0.35, lon: 32.58, label: 'Uganda' },
        { lat: 36.8, lon: 10.2, label: 'Tunisia' }
    ];

    function init() {
        _visible = App.isLayerActive('terrorism');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'terrorism') { _visible = e.visible; if (_visible && _data.length === 0) refresh(); _render(); }
        });
        EventBus.on('timerange:change', refresh);
        if (_visible) refresh();
        Scheduler.start('terrorism', refresh, Config.INTERVALS.terrorism || 300000);
    }

    function refresh() {
        Fetcher.get(Config.API.terrorism, {
            sourceKey: 'terrorism',
            fallbackUrl: 'data/fallback-terrorism.json',
            cacheTTL: Config.INTERVALS.terrorism || 300000,
            transform: _transformRss
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('terrorism', _data.length);
            EventBus.emit('data:terrorism:updated', _data);
            _render();
        });
    }

    function _transformRss(data) {
        if (!data || !data.items) return [];
        var regionIdx = 0;
        return data.items.filter(function (item) {
            var text = (item.title || '') + ' ' + (item.description || '');
            return TERROR_KEYWORDS.test(text);
        }).map(function (item) {
            var region = TERROR_REGIONS[regionIdx % TERROR_REGIONS.length];
            regionIdx++;
            var lat = region.lat + (Math.random() - 0.5) * 2;
            var lon = region.lon + (Math.random() - 0.5) * 2;
            var severity = 'low';
            var text = (item.title || '') + ' ' + (item.description || '');
            if (/suicide.?bomb|massacre|mass.?casualt|major.?attack/i.test(text)) severity = 'critical';
            else if (/bombing|explosion|hostage|killed/i.test(text)) severity = 'high';
            else if (/terrorist|militant|extremist/i.test(text)) severity = 'medium';
            return {
                id: item.link || Math.random().toString(36).substr(2, 9),
                lon: lon,
                lat: lat,
                type: 'terrorism',
                severity: severity,
                title: (item.title || 'Terrorism incident').substring(0, 150),
                source: 'BBC',
                url: item.link || '',
                country: region.label,
                timestamp: item.pubDate ? new Date(item.pubDate).getTime() : Date.now()
            };
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('terrorism');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'terrorism',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.severity === 'critical') return 30000;
                if (d.severity === 'high') return 22000;
                if (d.severity === 'medium') return 14000;
                return 8000;
            },
            getFillColor: function (d) {
                if (d.severity === 'critical') return [183, 28, 28, 220];
                if (d.severity === 'high') return [211, 47, 47, 190];
                if (d.severity === 'medium') return [229, 57, 53, 160];
                return [239, 83, 80, 130];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 30,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('terrorism', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
