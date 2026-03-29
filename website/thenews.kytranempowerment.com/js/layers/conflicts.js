/* ==========================================================================
   Kytran News — Conflicts Layer
   BBC + Al Jazeera RSS feeds filtered for conflict keywords
   ========================================================================== */

var Conflicts = (function () {
    'use strict';

    var _data = [];
    var _visible = true;

    var CONFLICT_KEYWORDS = /war|attack|conflict|military|strike|missile|troops|combat|airstrike|bomb|shell|offensive|invasion|soldier/i;

    /* Known conflict regions for geo-placement when articles lack coordinates */
    var CONFLICT_REGIONS = [
        { lat: 33.8, lon: 35.8, label: 'Lebanon' },
        { lat: 31.5, lon: 34.5, label: 'Gaza' },
        { lat: 48.5, lon: 37.5, label: 'Ukraine East' },
        { lat: 15.5, lon: 32.5, label: 'Sudan' },
        { lat: 13.5, lon: 44.2, label: 'Yemen' },
        { lat: 35.0, lon: 43.0, label: 'Iraq' },
        { lat: 36.2, lon: 37.2, label: 'Syria' },
        { lat: 12.0, lon: 45.0, label: 'Somalia' },
        { lat: 4.0, lon: 31.6, label: 'South Sudan' },
        { lat: 34.5, lon: 69.2, label: 'Afghanistan' },
        { lat: 19.8, lon: 96.2, label: 'Myanmar' },
        { lat: 9.1, lon: 7.5, label: 'Nigeria' }
    ];

    function init() {
        _visible = App.isLayerActive('conflicts');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'conflicts') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('conflicts', refresh, Config.INTERVALS.conflicts);
    }

    function refresh() {
        var bbcUrl = Config.API.conflicts_bbc;
        var ajUrl = Config.API.conflicts_aj;

        Promise.all([
            Fetcher.get(bbcUrl, {
                sourceKey: 'conflicts_bbc',
                fallbackUrl: Config.FALLBACKS.conflicts,
                cacheTTL: Config.INTERVALS.conflicts,
                transform: function (data) { return _transformRss(data, 'BBC'); }
            }),
            Fetcher.get(ajUrl, {
                sourceKey: 'conflicts_aj',
                cacheTTL: Config.INTERVALS.conflicts,
                transform: function (data) { return _transformRss(data, 'Al Jazeera'); }
            })
        ]).then(function (results) {
            var combined = (results[0] || []).concat(results[1] || []);
            /* Deduplicate by title similarity */
            var seen = {};
            _data = combined.filter(function (d) {
                var key = d.title.substring(0, 40).toLowerCase();
                if (seen[key]) return false;
                seen[key] = true;
                return true;
            });
            App.updateLayerCount('conflicts', _data.length);
            EventBus.emit('data:conflicts:updated', _data);
            _render();
        });
    }

    function _transformRss(data, source) {
        if (!data || !data.items) return [];
        var regionIdx = 0;
        return data.items.filter(function (item) {
            var text = (item.title || '') + ' ' + (item.description || '');
            return CONFLICT_KEYWORDS.test(text);
        }).map(function (item) {
            var region = CONFLICT_REGIONS[regionIdx % CONFLICT_REGIONS.length];
            regionIdx++;
            /* Add slight randomness so dots don't stack */
            var lat = region.lat + (Math.random() - 0.5) * 2;
            var lon = region.lon + (Math.random() - 0.5) * 2;
            var severity = 'low';
            var text = (item.title || '') + ' ' + (item.description || '');
            if (/airstrike|missile|bomb|invasion|massacre/i.test(text)) severity = 'critical';
            else if (/attack|offensive|troops|combat|shell/i.test(text)) severity = 'high';
            else if (/military|conflict|war/i.test(text)) severity = 'medium';
            return {
                id: item.link || Math.random().toString(36).substr(2, 9),
                lon: lon,
                lat: lat,
                type: 'conflict',
                severity: severity,
                title: (item.title || 'Conflict event').substring(0, 150),
                source: source,
                url: item.link || '',
                thumbnail: item.thumbnail || item.enclosure && item.enclosure.link || '',
                country: region.label,
                timestamp: item.pubDate ? new Date(item.pubDate).getTime() : Date.now()
            };
        });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('conflicts');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'conflicts',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                if (d.severity === 'critical') return 30000;
                if (d.severity === 'high') return 20000;
                if (d.severity === 'medium') return 12000;
                return 8000;
            },
            getFillColor: function (d) {
                if (d.severity === 'critical') return [255, 0, 0, 200];
                if (d.severity === 'high') return [255, 59, 59, 180];
                if (d.severity === 'medium') return [255, 100, 100, 150];
                return [255, 140, 140, 120];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 30,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('conflicts', layer);
    }

    function renderPulse() {
        var critical = _data.filter(function (d) { return d.severity === 'critical' || d.severity === 'high'; });
        if (!_visible || critical.length === 0) { KytranMap.removeLayer('conflict-pulse'); return; }

        var now = Date.now();
        var pulseLayer = new deck.ScatterplotLayer({
            id: 'conflict-pulse',
            data: critical,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                var cycle = ((now / 1000) % 3) / 3;
                return 25000 * (1 + cycle * 2);
            },
            stroked: true,
            filled: false,
            getLineColor: function () {
                var cycle = ((now / 1000) % 3) / 3;
                return [255, 59, 59, Math.floor(160 * (1 - cycle))];
            },
            getLineWidth: 2,
            lineWidthMinPixels: 1,
            radiusMinPixels: 5,
            radiusMaxPixels: 60,
            pickable: false,
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('conflict-pulse', pulseLayer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData, renderPulse: renderPulse };
})();
