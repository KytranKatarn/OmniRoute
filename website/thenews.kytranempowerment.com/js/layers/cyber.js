/* ==========================================================================
   Kytran News — Cyber Threats Layer
   Flat lines with animated projectiles showing attack direction
   No arcs — everything flat on the map surface
   ========================================================================== */

var Cyber = (function () {
    'use strict';

    var _arcs = [];
    var _visible = true;

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
                if (!_visible) {
                    KytranMap.removeLayer('cyber-lines');
                    KytranMap.removeLayer('cyber-projectiles');
                    KytranMap.removeLayer('cyber-trails');
                    KytranMap.removeLayer('cyber-sources');
                    KytranMap.removeLayer('cyber-targets');
                    KytranMap.removeLayer('cyber-impact');
                }
            }
        });
        refresh();
        Scheduler.start('cyber', refresh, 300000);
    }

    function refresh() {
        Fetcher.get(Config.API.cyber_stats, {
            sourceKey: 'cyber',
            fallbackUrl: Config.FALLBACKS.cyber,
            cacheTTL: 300000
        }).then(function (data) {
            _arcs = _generateArcs(data);
            App.updateLayerCount('cyber', _arcs.length);
            EventBus.emit('data:cyber:updated', _arcs);
            if (_visible) _renderStatic();
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

    /* Render the static parts: faint lines + source/target dots */
    function _renderStatic() {
        if (!_visible || _arcs.length === 0) return;

        /* Faint flat lines connecting source to target */
        var lineLayer = new deck.LineLayer({
            id: 'cyber-lines',
            data: _arcs,
            getSourcePosition: function (d) { return d.source; },
            getTargetPosition: function (d) { return d.target; },
            getColor: [139, 92, 246, 50],
            getWidth: 1,
            widthMinPixels: 1,
            widthMaxPixels: 1,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 80],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('cyber-lines', lineLayer);

        /* Source dots (attackers) — purple */
        var sources = [];
        var targets = [];
        _arcs.forEach(function (arc) {
            sources.push({ position: arc.source, label: arc.sourceCountry, intensity: arc.intensity });
            targets.push({ position: arc.target, label: arc.targetCountry, intensity: arc.intensity });
        });

        var sourceLayer = new deck.ScatterplotLayer({
            id: 'cyber-sources',
            data: sources,
            getPosition: function (d) { return d.position; },
            getRadius: function (d) { return 6000 + d.intensity * 3000; },
            getFillColor: [139, 92, 246, 180],
            radiusMinPixels: 3,
            radiusMaxPixels: 8,
            pickable: false,
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('cyber-sources', sourceLayer);

        /* Target dots (victims) — pink */
        var targetLayer = new deck.ScatterplotLayer({
            id: 'cyber-targets',
            data: targets,
            getPosition: function (d) { return d.position; },
            getRadius: function (d) { return 6000 + d.intensity * 3000; },
            getFillColor: [244, 114, 182, 180],
            radiusMinPixels: 3,
            radiusMaxPixels: 8,
            pickable: false,
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('cyber-targets', targetLayer);
    }

    /**
     * Called from animation loop (200ms).
     * Animated projectile dots traveling flat from source → target.
     */
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
            /* Each arc has its own staggered travel cycle */
            var speed = 2000 + (arc.intensity || 1) * 500; /* ms per trip */
            var t = ((now + i * 400) % speed) / speed; /* 0→1 progress */

            /* Interpolate position along flat line */
            var lon = arc.source[0] + (arc.target[0] - arc.source[0]) * t;
            var lat = arc.source[1] + (arc.target[1] - arc.source[1]) * t;

            /* Main projectile — bright, color shifts purple→pink as it travels */
            projectiles.push({
                position: [lon, lat],
                intensity: arc.intensity,
                t: t
            });

            /* 4 trailing dots behind the projectile */
            for (var j = 1; j <= 4; j++) {
                var trailT = t - j * 0.04;
                if (trailT < 0) continue;
                var tlon = arc.source[0] + (arc.target[0] - arc.source[0]) * trailT;
                var tlat = arc.source[1] + (arc.target[1] - arc.source[1]) * trailT;
                trails.push({
                    position: [tlon, tlat],
                    fade: j / 4,
                    intensity: arc.intensity
                });
            }

            /* Impact ring at target when projectile arrives */
            if (t > 0.85) {
                var impactT = (t - 0.85) / 0.15;
                impacts.push({
                    position: arc.target,
                    cycle: impactT,
                    intensity: arc.intensity
                });
            }
        });

        /* Projectile heads — bright dots */
        var projLayer = new deck.ScatterplotLayer({
            id: 'cyber-projectiles',
            data: projectiles,
            getPosition: function (d) { return d.position; },
            getRadius: function (d) { return 5000 + d.intensity * 3000; },
            getFillColor: function (d) {
                /* Color shifts from purple (source) to pink (target) */
                var r = Math.floor(139 + (244 - 139) * d.t);
                var g = Math.floor(92 + (114 - 92) * d.t);
                var b = Math.floor(246 + (182 - 246) * d.t);
                return [r, g, b, 255];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 7,
            pickable: false,
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('cyber-projectiles', projLayer);

        /* Trails — fading behind projectiles */
        if (trails.length > 0) {
            var trailLayer = new deck.ScatterplotLayer({
                id: 'cyber-trails',
                data: trails,
                getPosition: function (d) { return d.position; },
                getRadius: function (d) { return 3000 + d.intensity * 1500; },
                getFillColor: function (d) {
                    return [180, 100, 220, Math.floor(180 * (1 - d.fade))];
                },
                radiusMinPixels: 1,
                radiusMaxPixels: 4,
                pickable: false,
                parameters: { depthTest: false }
            });
            KytranMap.setLayer('cyber-trails', trailLayer);
        }

        /* Impact flash rings at targets */
        if (impacts.length > 0) {
            var impactLayer = new deck.ScatterplotLayer({
                id: 'cyber-impact',
                data: impacts,
                getPosition: function (d) { return d.position; },
                getRadius: function (d) { return 12000 * (1 + d.cycle * 2); },
                stroked: true,
                filled: false,
                getLineColor: function (d) {
                    return [244, 114, 182, Math.floor(220 * (1 - d.cycle))];
                },
                getLineWidth: 2,
                lineWidthMinPixels: 1,
                radiusMinPixels: 4,
                radiusMaxPixels: 25,
                pickable: false,
                parameters: { depthTest: false }
            });
            KytranMap.setLayer('cyber-impact', impactLayer);
        }
    }

    function getData() { return _arcs; }

    return { init: init, refresh: refresh, getData: getData, renderPulse: renderPulse };
})();
