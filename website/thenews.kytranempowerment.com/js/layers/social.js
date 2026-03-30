/* ==========================================================================
   Kytran News — Social Media Trending Layer
   Reddit r/worldnews hot posts — falls back to static JSON
   Geo-placed by keyword matching to known regions
   ========================================================================== */

var Social = (function () {
    'use strict';

    var _data = [];
    var _visible = true;

    /* Region keyword → coordinates mapping */
    var REGION_MAP = [
        { keywords: /ukraine|russia|kyiv|moscow|kremlin/i,             lat: 50.4501,  lon: 30.5234  },
        { keywords: /israel|gaza|palestin|hamas|west bank/i,           lat: 31.5,     lon: 34.5     },
        { keywords: /china|beijing|taiwan|xi jinping|hong kong/i,      lat: 39.9042,  lon: 116.4074 },
        { keywords: /iran|tehran|persian|ayatollah/i,                   lat: 35.6892,  lon: 51.3890  },
        { keywords: /india|pakistan|modi|kashmir/i,                     lat: 28.6139,  lon: 77.2090  },
        { keywords: /north korea|pyongyang|kim jong/i,                  lat: 39.0392,  lon: 125.7625 },
        { keywords: /usa|united states|washington|biden|trump|congress/i, lat: 38.8951, lon: -77.0364 },
        { keywords: /uk|britain|london|sunak|parliament/i,              lat: 51.5074,  lon: -0.1278  },
        { keywords: /france|paris|macron|élysée/i,                      lat: 48.8566,  lon: 2.3522   },
        { keywords: /germany|berlin|scholz|bundesrat/i,                 lat: 52.5200,  lon: 13.4050  },
        { keywords: /canada|ottawa|trudeau|liberal/i,                   lat: 45.4215,  lon: -75.6972 },
        { keywords: /brazil|brasilia|lula|amazon/i,                     lat: -15.794,  lon: -47.883  },
        { keywords: /africa|nigeria|kenya|ethiopia|sudan/i,             lat: 9.0820,   lon: 8.6753   },
        { keywords: /myanmar|burma|junta|coup/i,                        lat: 19.8,     lon: 96.2     },
        { keywords: /syria|damascus|aleppo/i,                           lat: 33.5138,  lon: 36.2765  },
        { keywords: /turkey|ankara|erdogan/i,                           lat: 39.9334,  lon: 32.8597  },
        { keywords: /japan|tokyo|kishida|earthquake/i,                  lat: 35.6762,  lon: 139.6503 },
        { keywords: /saudi|riyadh|oil|opec/i,                           lat: 24.7136,  lon: 46.6753  }
    ];

    var DEFAULT_LOC = { lat: 20.0, lon: 0.0 };

    function init() {
        _visible = App.isLayerActive('social');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'social') { _visible = e.visible; _render(); }
        });
        EventBus.on('timerange:change', refresh);
        refresh();
        Scheduler.start('social', refresh, Config.INTERVALS.social || 300000);
    }

    function refresh() {
        /* Reddit requires a User-Agent but works from browser without one for hot.json */
        var url = Config.API.social_reddit;
        fetch(url, { headers: { 'Accept': 'application/json' } })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                var parsed = _parseReddit(data);
                if (parsed.length > 0) {
                    _data = parsed;
                    _finalize();
                } else {
                    _loadFallback();
                }
            })
            .catch(function () { _loadFallback(); });
    }

    function _geoFromText(text) {
        for (var i = 0; i < REGION_MAP.length; i++) {
            if (REGION_MAP[i].keywords.test(text)) {
                var r = REGION_MAP[i];
                /* Small jitter so multiple posts in same region spread slightly */
                return {
                    lat: r.lat + (Math.random() - 0.5) * 2,
                    lon: r.lon + (Math.random() - 0.5) * 2
                };
            }
        }
        return {
            lat: DEFAULT_LOC.lat + (Math.random() - 0.5) * 30,
            lon: DEFAULT_LOC.lon + (Math.random() - 0.5) * 60
        };
    }

    function _parseReddit(data) {
        try {
            var posts = data && data.data && data.data.children ? data.data.children : [];
            return posts.map(function (child) {
                var post = child.data;
                var title = post.title || 'World News';
                var text = title + ' ' + (post.selftext || '');
                var geo = _geoFromText(text);
                var score = post.score || 0;
                var sentiment = score > 5000 ? 'positive' : (score < 0 ? 'negative' : 'neutral');
                /* Reddit scores on hot tend to be high — treat upvote ratio */
                if (post.upvote_ratio && post.upvote_ratio < 0.45) sentiment = 'negative';
                return {
                    type: 'social',
                    title: title,
                    lat: geo.lat,
                    lon: geo.lon,
                    volume: score,
                    sentiment: sentiment,
                    description: post.selftext ? post.selftext.substring(0, 200) : ('Score: ' + score + ' · Comments: ' + (post.num_comments || 0)),
                    url: 'https://reddit.com' + (post.permalink || ''),
                    timestamp: post.created_utc ? new Date(post.created_utc * 1000).toISOString() : null,
                    subreddit: post.subreddit_name_prefixed || 'r/worldnews',
                    source: 'Reddit'
                };
            });
        } catch (e) {
            return [];
        }
    }

    function _loadFallback() {
        fetch('data/social-trends.json')
            .then(function (r) { return r.json(); })
            .then(function (raw) {
                var items = (raw && raw.trends) ? raw.trends : (Array.isArray(raw) ? raw : []);
                _data = items.map(function (d) {
                    return {
                        type: d.type || 'social',
                        title: d.title || d.topic || 'Social Trend',
                        lat: d.lat,
                        lon: d.lon,
                        volume: d.volume || 0,
                        sentiment: d.sentiment || 'neutral',
                        description: d.description || '',
                        url: d.url || null,
                        timestamp: d.timestamp || null,
                        subreddit: d.subreddit || '',
                        source: d.source || 'Fallback'
                    };
                });
                _finalize();
            })
            .catch(function () {
                _data = [];
                _finalize();
            });
    }

    function _finalize() {
        App.updateLayerCount('social', _data.length);
        EventBus.emit('data:social:updated', _data);
        _render();
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('social');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'social',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function (d) {
                var vol = d.volume || 1000;
                if (vol >= 100000) return 35000;
                if (vol >= 50000) return 25000;
                if (vol >= 10000) return 16000;
                return 10000;
            },
            getFillColor: function (d) {
                if (d.sentiment === 'positive') return [76, 175, 80, 170];
                if (d.sentiment === 'negative') return [244, 67, 54, 170];
                return [224, 64, 251, 160];
            },
            radiusMinPixels: 3,
            radiusMaxPixels: 35,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('social', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
