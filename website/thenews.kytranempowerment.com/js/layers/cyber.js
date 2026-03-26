/* ==========================================================================
   Kytran News — Cyber Threats Layer
   Animated ArcLayer showing attack flows between countries
   (checkpoint threatmap style)
   ========================================================================== */

var Cyber = (function () {
    'use strict';

    var _arcs = [];
    var _visible = true;
    var _animFrame = null;
    var _time = 0;

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
                if (_visible) { _startAnimation(); _render(); }
                else { _stopAnimation(); KytranMap.removeLayer('cyber'); }
            }
        });
        refresh();
        Scheduler.start('cyber', refresh, Config.INTERVALS.cyber);
    }

    function refresh() {
        Fetcher.get(Config.API.cyber_stats, {
            sourceKey: 'cyber',
            fallbackUrl: Config.FALLBACKS.cyber,
            cacheTTL: Config.INTERVALS.cyber
        }).then(function (data) {
            _arcs = _generateArcs(data);
            App.updateLayerCount('cyber', _arcs.length);
            EventBus.emit('data:cyber:updated', _arcs);
            if (_visible) {
                _startAnimation();
                _render();
            }
        });
    }

    function _generateArcs(data) {
        if (!data || !data.flows) return _generateRandomArcs();
        return data.flows.map(function (flow) {
            var src = COUNTRY_COORDS[flow.source] || [0, 0];
            var tgt = COUNTRY_COORDS[flow.target] || [0, 0];
            return {
                id: flow.source + '-' + flow.target,
                type: 'cyber',
                title: flow.source + ' → ' + flow.target + ' (' + flow.type + ')',
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

    function _generateRandomArcs() {
        /* Generate plausible cyber attack arcs for demo */
        var countries = Object.keys(COUNTRY_COORDS);
        var types = ['DDoS', 'Ransomware', 'Phishing', 'Exploit', 'Brute Force', 'Malware'];
        var arcs = [];
        for (var i = 0; i < 40; i++) {
            var src = countries[Math.floor(Math.random() * countries.length)];
            var tgt = countries[Math.floor(Math.random() * countries.length)];
            if (src === tgt) continue;
            arcs.push({
                id: src + '-' + tgt + '-' + i,
                type: 'cyber',
                title: src + ' → ' + tgt,
                source: COUNTRY_COORDS[src],
                target: COUNTRY_COORDS[tgt],
                sourceCountry: src,
                targetCountry: tgt,
                attackType: types[Math.floor(Math.random() * types.length)],
                intensity: Math.random() * 3 + 0.5,
                timestamp: Date.now()
            });
        }
        return arcs;
    }

    function _startAnimation() {
        if (_animFrame) return;
        function tick() {
            _time += 0.005;
            _render();
            _animFrame = requestAnimationFrame(tick);
        }
        _animFrame = requestAnimationFrame(tick);
    }

    function _stopAnimation() {
        if (_animFrame) {
            cancelAnimationFrame(_animFrame);
            _animFrame = null;
        }
    }

    function _render() {
        if (!_visible || _arcs.length === 0) return;

        var layer = new deck.ArcLayer({
            id: 'cyber',
            data: _arcs,
            getSourcePosition: function (d) { return d.source; },
            getTargetPosition: function (d) { return d.target; },
            getSourceColor: function (d) {
                var a = Math.floor(80 + d.intensity * 40);
                return [139, 92, 246, a]; /* purple */
            },
            getTargetColor: function (d) {
                var a = Math.floor(120 + d.intensity * 40);
                return [244, 114, 182, a]; /* pink */
            },
            getWidth: function (d) { return 1 + d.intensity * 0.8; },
            widthMinPixels: 1,
            widthMaxPixels: 4,
            greatCircle: true,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 80],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('cyber', layer);
    }

    function getData() { return _arcs; }

    return { init: init, refresh: refresh, getData: getData };
})();
