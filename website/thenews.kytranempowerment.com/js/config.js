/* ==========================================================================
   Kytran News — Configuration
   API endpoints, keys, refresh intervals, region definitions
   ========================================================================== */

var Config = (function () {
    'use strict';

    /* CORS proxy — self-hosted primary, public fallback */
    var CORS_PROXY = 'https://proxy.kytranempowerment.com/proxy?url=';
    var CORS_PROXY_ALT = ''; /* disabled — allorigins/corsproxy both broken as of 2026-03 */

    /* W.A.T.C.H. Civic Intelligence API */
    var WATCH_API = 'https://civic.kytranempowerment.com/api';

    /* -- API Endpoints ---------------------------------------------------- */
    /* GDELT removed — 429 rate-limited as of 2026-03-29. Replaced with RSS + free APIs. */
    var API = {
        /* Conflicts — RSS feeds via rss2json (free, no key, no CORS issues) */
        conflicts_bbc: 'https://api.rss2json.com/v1/api.json?rss_url=https://feeds.bbci.co.uk/news/world/rss.xml',
        conflicts_aj:  'https://api.rss2json.com/v1/api.json?rss_url=https://www.aljazeera.com/xml/rss/all.xml',

        /* Earthquakes (USGS — free, no key) */
        earthquakes_hour:  'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_hour.geojson',
        earthquakes_day:   'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson',
        earthquakes_week:  'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson',

        /* Natural disasters (NASA EONET — free, no key) */
        eonet: 'https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=50',

        /* Weather alerts US (NWS — free, needs User-Agent) */
        nws_alerts: 'https://api.weather.gov/alerts/active?status=actual',

        /* News ticker — RSS feeds (replaces GDELT DOC) */
        news_bbc:    'https://api.rss2json.com/v1/api.json?rss_url=https://feeds.bbci.co.uk/news/world/rss.xml',
        news_aj:     'https://api.rss2json.com/v1/api.json?rss_url=https://www.aljazeera.com/xml/rss/all.xml',
        news_canada: 'https://api.rss2json.com/v1/api.json?rss_url=https://www.cbc.ca/cmlink/rss-world',

        /* Protests — RSS filtered (replaces GDELT DOC) */
        protests: 'https://api.rss2json.com/v1/api.json?rss_url=https://feeds.bbci.co.uk/news/world/rss.xml',

        /* Terrorism — RSS filtered (replaces GDELT DOC) */
        terrorism: 'https://api.rss2json.com/v1/api.json?rss_url=https://feeds.bbci.co.uk/news/world/rss.xml',

        /* Outages — IODA (Georgia Tech, free) */
        outages: 'https://api.ioda.inetintel.cc.gatech.edu/v2/signals/raw/country/US?from={from}&until={until}',

        /* Cyber threats — simulated from public stats */
        cyber_stats: 'data/fallback-cyber.json',

        /* Air quality — WAQI (free demo token) */
        air_quality: 'https://api.waqi.info/v2/map/bounds/?latlng={bounds}&token=demo',

        /* Disease outbreaks — disease.sh (free, no key) */
        disease: 'https://disease.sh/v3/covid-19/countries?sort=todayCases&yesterday=true',

        /* Ship traffic — MarineTraffic public */
        ships: 'https://www.marinetraffic.com/getData/get_data_json_4/z:2/X:0/Y:0/station:0',

        /* Space weather (NOAA SWPC — free, no key) */
        space_weather: 'https://services.swpc.noaa.gov/products/alerts.json',

        /* Radiation — Safecast (free, no key) */
        radiation: 'https://api.safecast.org/measurements.json?distance=10000&latitude=35.6762&longitude=139.6503&limit=50',

        /* Markets — ExchangeRate-API + CoinGecko (both free) */
        exchange_rates: 'https://open.er-api.com/v6/latest/USD',
        crypto: 'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd&include_24hr_change=true',

        /* Flights — OpenSky (free, no key) */
        flights: 'https://opensky-network.org/api/states/all?lamin={lamin}&lomin={lomin}&lamax={lamax}&lomax={lomax}'
    };

    /* -- Refresh Intervals (ms) ------------------------------------------- */
    var INTERVALS = {
        conflicts:  300000,   /* 5 min */
        disasters:  120000,   /* 2 min */
        weather:    600000,   /* 10 min */
        cyber:       60000,   /* 1 min */
        news:       180000,   /* 3 min */
        outages:    600000,   /* 10 min */
        contracts:  600000,   /* 10 min */
        parliament: 600000,   /* 10 min */
        spending:   600000,   /* 10 min */
    };

    /* -- Fallback Data Paths ---------------------------------------------- */
    var FALLBACKS = {
        conflicts: 'data/fallback-conflicts.json',
        disasters: 'data/fallback-disasters.json',
        weather:   'data/fallback-weather.json',
        cyber:     'data/fallback-cyber.json',
        news:      'data/fallback-news.json',
        military:  'data/military-sites.geojson',
        sanctions: 'data/sanctions-entities.json',
        contracts:  'data/fallback-contracts.json',
        parliament: 'data/fallback-parliament.json',
        spending:   'data/fallback-spending.json'
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
        ships:     { label: 'Ship Traffic',       color: '#00b4d8', icon: 'anchor',   default: false },
        spaceweather:{ label: 'Space Weather',   color: '#ffd700', icon: 'sun',      default: false },
        radiation: { label: 'Radiation',          color: '#c6ff00', icon: 'alert',    default: false },
        protests:  { label: 'Protests / Unrest', color: '#ff1493', icon: 'flag',     default: false },
        internet:  { label: 'Internet Outages',  color: '#ff4081', icon: 'wifi',     default: false },
        terrorism: { label: 'Terrorism',          color: '#b71c1c', icon: 'alert',    default: false },
        economic:  { label: 'Markets / Economy',  color: '#ffc107', icon: 'trending', default: false },
        social:    { label: 'Social Trends',      color: '#e040fb', icon: 'hash',     default: false },
        contracts:  { label: 'Gov Contracts',   color: '#00bfa5', icon: 'briefcase', default: false },
        parliament: { label: 'Parliament',      color: '#ffd740', icon: 'landmark',  default: false },
        spending:   { label: 'Public Spending', color: '#69f0ae', icon: 'dollar',    default: false }
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
        WATCH_API: WATCH_API,
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
