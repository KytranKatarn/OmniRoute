/* ==========================================================================
   Kytran News — Configuration
   API endpoints, keys, refresh intervals, region definitions
   ========================================================================== */

var Config = (function () {
    'use strict';

    /* CORS proxy — self-hosted primary, public fallback */
    var CORS_PROXY = 'https://proxy.kytranempowerment.com/proxy?url=';
    var CORS_PROXY_ALT = 'https://api.allorigins.win/raw?url=';

    /* -- API Endpoints ---------------------------------------------------- */
    var API = {
        /* Conflicts (GDELT — free, no key) */
        conflicts: 'https://api.gdeltproject.org/api/v2/geo/geo?query=conflict OR war OR attack OR protest OR emergency&format=geojson&timespan={timespan}',

        /* Earthquakes (USGS — free, no key) */
        earthquakes_hour:  'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_hour.geojson',
        earthquakes_day:   'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson',
        earthquakes_week:  'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson',

        /* Natural disasters (NASA EONET — free, no key) */
        eonet: 'https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=50',

        /* Weather alerts US (NWS — free, no key) */
        nws_alerts: 'https://api.weather.gov/alerts/active?status=actual',

        /* News (GDELT DOC — free, no key, includes Canada) */
        news: 'https://api.gdeltproject.org/api/v2/doc/doc?query=conflict OR disaster OR earthquake OR cyber attack OR sanctions OR Canada&mode=artlist&format=json&maxrecords=100&timespan={timespan}',

        /* Canadian news specifically */
        news_canada: 'https://api.gdeltproject.org/api/v2/doc/doc?query=sourcecountry:CA&mode=artlist&format=json&maxrecords=30&timespan={timespan}',

        /* Cyber threats — simulated from public country-level stats */
        cyber_stats: 'data/fallback-cyber.json'
    };

    /* -- Refresh Intervals (ms) ------------------------------------------- */
    var INTERVALS = {
        conflicts:  300000,   /* 5 min */
        disasters:  120000,   /* 2 min */
        weather:    600000,   /* 10 min */
        cyber:       60000,   /* 1 min */
        news:       180000,   /* 3 min */
        outages:    600000,   /* 10 min */
    };

    /* -- Fallback Data Paths ---------------------------------------------- */
    var FALLBACKS = {
        conflicts: 'data/fallback-conflicts.json',
        disasters: 'data/fallback-disasters.json',
        weather:   'data/fallback-weather.json',
        cyber:     'data/fallback-cyber.json',
        news:      'data/fallback-news.json',
        military:  'data/military-sites.geojson',
        sanctions: 'data/sanctions-entities.json'
    };

    /* -- Time Ranges ------------------------------------------------------ */
    var TIME_RANGES = {
        '1h':  { label: '1H',  gdeltSpan: '1h',  usgsKey: 'earthquakes_hour' },
        '6h':  { label: '6H',  gdeltSpan: '6h',  usgsKey: 'earthquakes_day'  },
        '24h': { label: '24H', gdeltSpan: '24h', usgsKey: 'earthquakes_day'  },
        '48h': { label: '48H', gdeltSpan: '48h', usgsKey: 'earthquakes_day'  },
        '7d':  { label: '7D',  gdeltSpan: '7d',  usgsKey: 'earthquakes_week' }
    };

    /* -- Region Views ----------------------------------------------------- */
    var REGIONS = {
        world:    { label: 'WORLD',    lat: 20,   lon: 0,     zoom: 1.5, pitch: 0   },
        americas: { label: 'AMERICAS', lat: 15,   lon: -85,   zoom: 2.5, pitch: 0   },
        europe:   { label: 'EUROPE',   lat: 50,   lon: 15,    zoom: 3.5, pitch: 0   },
        asia:     { label: 'ASIA',     lat: 35,   lon: 100,   zoom: 2.8, pitch: 0   },
        mena:     { label: 'MENA',     lat: 28,   lon: 45,    zoom: 3.2, pitch: 0   },
        africa:   { label: 'AFRICA',   lat: 2,    lon: 20,    zoom: 2.8, pitch: 0   }
    };

    /* -- Layer Definitions ------------------------------------------------ */
    var LAYERS = {
        conflicts: { label: 'Conflicts',       color: '#ff3b3b', icon: 'crosshair',  default: true  },
        disasters: { label: 'Disasters',        color: '#ff6d00', icon: 'activity',   default: true  },
        weather:   { label: 'Weather Alerts',   color: '#40c4ff', icon: 'cloud',      default: true  },
        cyber:     { label: 'Cyber Threats',    color: '#8b5cf6', icon: 'shield',     default: true  },
        outages:   { label: 'Outages',          color: '#ffaa00', icon: 'zap-off',    default: false },
        sanctions: { label: 'Sanctions',        color: '#f472b6', icon: 'ban',        default: false },
        military:  { label: 'Military / Nuclear', color: '#76ff03', icon: 'target',   default: false },
        flights:   { label: 'Live Flights',      color: '#00c8ff', icon: 'plane',    default: false },
        airquality:{ label: 'Air Quality',        color: '#a0ff00', icon: 'wind',     default: false },
        disease:   { label: 'Disease Outbreaks',  color: '#00ff88', icon: 'heart',    default: false },
        ships:     { label: 'Ship Traffic',       color: '#00b4d8', icon: 'anchor',   default: false }
    };

    /* -- DEFCON Levels ---------------------------------------------------- */
    var DEFCON = {
        5: { label: 'LOW',      color: '#00cc44' },
        4: { label: 'GUARDED',  color: '#0088ff' },
        3: { label: 'ELEVATED', color: '#ffcc00' },
        2: { label: 'HIGH',     color: '#ff6600' },
        1: { label: 'CRITICAL', color: '#ff0000' }
    };

    /* -- Map Defaults ----------------------------------------------------- */
    var MAP = {
        style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
        initialView: {
            latitude: 20,
            longitude: 0,
            zoom: 1.5,
            pitch: 0,
            bearing: 0
        },
        minZoom: 1,
        maxZoom: 16
    };

    /* -- Helpers ---------------------------------------------------------- */
    function getApiUrl(key, timeRange) {
        var url = API[key] || '';
        var range = TIME_RANGES[timeRange] || TIME_RANGES['24h'];
        return url.replace('{timespan}', range.gdeltSpan || '24h');
    }

    function getEarthquakeUrl(timeRange) {
        var range = TIME_RANGES[timeRange] || TIME_RANGES['24h'];
        return API[range.usgsKey] || API.earthquakes_day;
    }

    return {
        CORS_PROXY: CORS_PROXY,
        CORS_PROXY_ALT: CORS_PROXY_ALT,
        API: API,
        INTERVALS: INTERVALS,
        FALLBACKS: FALLBACKS,
        TIME_RANGES: TIME_RANGES,
        REGIONS: REGIONS,
        LAYERS: LAYERS,
        DEFCON: DEFCON,
        MAP: MAP,
        getApiUrl: getApiUrl,
        getEarthquakeUrl: getEarthquakeUrl
    };
})();
