/* ==========================================================================
   Kytran News — Cyber Threats Layer
   Animated ArcLayer showing attack flows between countries
   (checkpoint threatmap style — persistent arcs with pulsing glow)
   ========================================================================== */

var Cyber = (function () {
    'use strict';

    var _arcs = [];
    var _visible = true;
    var _initialized = false;

    /* Major country centroids for arc source/target */
    var COUNTRY_COORDS = {
        US: [-98.5, 39.8], CN: [104.1, 35.8], RU: [105.3, 61.5],
        DE: [10.4, 51.1], GB: [-3.4, 55.3], FR: [2.2, 46.2],
        BR: [-51.9, -14.2], IN: [78.9, 20.5], JP: [138.2, 36.2],
        KR: [127.7, 35.9], AU: [133.7, -25.2], CA: [-106.3, 56.1],
        NL: [5.2, 52.1], UA: [31.1, 48.3], IR: [53.6, 32.4],
        IL: [34.8, 31.0], SA: [45.0, 23.8], NG: [8.6, 9.0],
        ZA: [22.9, -30.5], MX: [-102.5, 23.6], SG: [103.8, 1.3],
        KP: [127.5, 40.3], PK: [69.3, 30.3], EG: [30.8, 26.8],
        TR: [35.2, 38.9], ID: [113.9, -0.7], VN: [108.2, 14.0],
        PH: [121.7, 12.8], TH: [100.9, 15.8], PL: [19.1, 51.9]
    };

    function init() {
        _visible = App.isLayerActive('cyber');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'cyber') {
                _visible = e.visible;
                if (_visible) _render();
                else {
                    KytranMap.removeLayer('cyber');
                    KytranMap.removeLayer('cyber-glow');
                    KytranMap.removeLayer('cyber-endpoints');
                }
            }
        });
        refresh();
        /* Refresh every 5 min instead of 1 min — arcs are stable */
        Scheduler.start('cyber', refresh, 300000);
    }

    function refresh() {
        Fetcher.get(Config.API.cyber_stats, {
            sourceKey: 'cyber',
            fallbackUrl: Config.FALLBACKS.cyber,
            cacheTTL: 300000 /* 5 min cache — keep arcs stable */
        }).then(function (data) {
            _arcs = _generateArcs(data);
            App.updateLayerCount('cyber', _arcs.length);
            EventBus.emit('data:cyber:updated', _arcs);
            if (_visible) _render();
        });
    }

    function _generateArcs(data) {
        if (!data || !data.flows) return [];
        return data.flows.map(function (flow) {
            var src = COUNTRY_COORDS[flow.source] || [0, 0];
            var tgt = COUNTRY_COORDS[flow.target] || [0, 0];
            return {
                id: flow.source + '-' + flow.target,
                type: 'cyber',
                title: flow.source + ' \u2192 ' + flow.target + ' (' + flow.type + ')',
                source: src,
                target: tgt,
                sourceCountry: flow.source,
                targetCountry: flow.target,
                attackType: flow.type || 'unknown',
                intensity: flow.intensity || 1,
                timestamp: Date.now()
            };
        });
    }

    function _render() {
        if (!_visible || _arcs.length === 0) return;

        /* Main arcs — persistent, always visible */
        var arcLayer = new deck.ArcLayer({
            id: 'cyber',
            data: _arcs,
            getSourcePosition: function (d) { return d.source; },
            getTargetPosition: function (d) { return d.target; },
            getSourceColor: function (d) {
                var a = Math.floor(100 + d.intensity * 50);
                return [139, 92, 246, a];
            },
            getTargetColor: function (d) {
                var a = Math.floor(140 + d.intensity * 40);
                return [244, 114, 182, a];
            },
            getWidth: function (d) { return 1 + d.intensity * 0.8; },
            getHeight: 0.05, /* very low arcs — almost flat on surface */
            widthMinPixels: 1,
            widthMaxPixels: 4,
            greatCircle: true, /* needed for anti-meridian wrapping */
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 80],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('cyber', arcLayer);

        /* Endpoint dots — glowing source/target markers */
        var endpoints = [];
        _arcs.forEach(function (arc) {
            endpoints.push({
                position: arc.source,
                color: [139, 92, 246],
                label: arc.sourceCountry,
                intensity: arc.intensity
            });
            endpoints.push({
                position: arc.target,
                color: [244, 114, 182],
                label: arc.targetCountry,
                intensity: arc.intensity
            });
        });

        var endpointLayer = new deck.ScatterplotLayer({
            id: 'cyber-endpoints',
            data: endpoints,
            getPosition: function (d) { return d.position; },
            getRadius: function (d) { return 8000 + d.intensity * 4000; },
            getFillColor: function (d) { return [d.color[0], d.color[1], d.color[2], 160]; },
            radiusMinPixels: 3,
            radiusMaxPixels: 10,
            pickable: false,
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('cyber-endpoints', endpointLayer);
    }

    /**
     * Interpolate a position along a great circle arc.
     * t = 0 at source, t = 1 at target.
     */
    function _interpolateArc(src, tgt, t) {
        /* Simple linear interpolation (good enough for visual effect) */
        return [
            src[0] + (tgt[0] - src[0]) * t,
            src[1] + (tgt[1] - src[1]) * t
        ];
    }

    /* Called from animation loop — animated projectiles traveling along arcs */
    function renderPulse() {
        if (!_visible || _arcs.length === 0) {
            KytranMap.removeLayer('cyber-projectiles');
            KytranMap.removeLayer('cyber-trails');
            KytranMap.removeLayer('cyber-impact');
            return;
        }

        var now = Date.now();
        var projectiles = [];
        var trails = [];
        var impacts = [];

        _arcs.forEach(function (arc, i) {
            /* Each arc has its own travel cycle — staggered so they don't all move at once */
            var speed = 2.5 + (arc.intensity || 1) * 0.5; /* seconds per trip */
            var t = ((now / 1000 + i * 0.7) % speed) / speed; /* 0 to 1 progress */

            /* Main projectile dot — traveling from source to target */
            var pos = _interpolateArc(arc.source, arc.target, t);
            projectiles.push({
                position: pos,
                intensity: arc.intensity,
                t: t
            });

            /* Trail dots behind the projectile (3 trailing dots) */
            for (var j = 1; j <= 3; j++) {
                var trailT = t - j * 0.06;
                if (trailT < 0) continue;
                var trailPos = _interpolateArc(arc.source, arc.target, trailT);
                trails.push({
                    position: trailPos,
                    alpha: 1 - (j * 0.3),
                    intensity: arc.intensity
                });
            }

            /* Impact flash at target when projectile arrives (t > 0.9) */
            if (t > 0.9) {
                var impactAlpha = (t - 0.9) / 0.1; /* 0 to 1 in last 10% */
                impacts.push({
                    position: arc.target,
                    cycle: impactAlpha,
                    intensity: arc.intensity
                });
            }
        });

        /* Projectile heads — bright moving dots */
        var projectileLayer = new deck.ScatterplotLayer({
            id: 'cyber-projectiles',
            data: projectiles,
            getPosition: function (d) { return d.position; },
            getRadius: function (d) { return 6000 + d.intensity * 3000; },
            getFillColor: function (d) {
                var blend = d.t;
                var r = Math.floor(139 + (244 - 139) * blend);
                var g = Math.floor(92 + (114 - 92) * blend);
                var b = Math.floor(246 + (182 - 246) * blend);
                return [r, g, b, 240];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 8,
            pickable: false,
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('cyber-projectiles', projectileLayer);

        /* Trail dots — fading behind projectiles */
        var trailLayer = new deck.ScatterplotLayer({
            id: 'cyber-trails',
            data: trails,
            getPosition: function (d) { return d.position; },
            getRadius: function (d) { return 4000 + d.intensity * 1500; },
            getFillColor: function (d) {
                return [180, 100, 220, Math.floor(140 * d.alpha)];
            },
            radiusMinPixels: 1,
            radiusMaxPixels: 5,
            pickable: false,
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('cyber-trails', trailLayer);

        /* Impact flashes at targets */
        if (impacts.length > 0) {
            var impactLayer = new deck.ScatterplotLayer({
                id: 'cyber-impact',
                data: impacts,
                getPosition: function (d) { return d.position; },
                getRadius: function (d) {
                    return 15000 * (1 + d.cycle * 2);
                },
                stroked: true,
                filled: false,
                getLineColor: function (d) {
                    return [244, 114, 182, Math.floor(200 * (1 - d.cycle))];
                },
                getLineWidth: 2,
                lineWidthMinPixels: 1,
                radiusMinPixels: 4,
                radiusMaxPixels: 30,
                pickable: false,
                parameters: { depthTest: false }
            });
            KytranMap.setLayer('cyber-impact', impactLayer);
        }
    }

    function getData() { return _arcs; }

    return { init: init, refresh: refresh, getData: getData, renderPulse: renderPulse };
})();
