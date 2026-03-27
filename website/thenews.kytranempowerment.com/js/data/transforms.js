/* ==========================================================================
   Kytran News — Data Transforms
   Normalize various API responses into unified formats
   ========================================================================== */

var Transforms = (function () {
    'use strict';

    /**
     * Normalize GDELT Geo API response to array of point features.
     * GDELT returns: { type: "FeatureCollection", features: [...] }
     */
    function gdeltGeo(data) {
        if (!data || !data.features) return [];
        return data.features.map(function (f) {
            var p = f.properties || {};
            var coords = (f.geometry && f.geometry.coordinates) || [0, 0];
            return {
                id: p.urlsourcex || Math.random().toString(36).substr(2, 9),
                lon: coords[0],
                lat: coords[1],
                type: 'conflict',
                title: p.name || p.html || 'Unknown event',
                source: p.domain || 'GDELT',
                url: p.url || p.shareimage || '',
                timestamp: p.dateadded ? _parseGdeltDate(p.dateadded) : Date.now(),
                severity: _estimateConflictSeverity(p)
            };
        });
    }

    /**
     * Normalize USGS earthquake GeoJSON.
     */
    function usgsEarthquakes(data) {
        if (!data || !data.features) return [];
        return data.features.map(function (f) {
            var p = f.properties || {};
            var coords = (f.geometry && f.geometry.coordinates) || [0, 0, 0];
            return {
                id: f.id || Math.random().toString(36).substr(2, 9),
                lon: coords[0],
                lat: coords[1],
                depth: coords[2],
                type: 'earthquake',
                title: p.place || 'Unknown location',
                magnitude: p.mag || 0,
                timestamp: p.time || Date.now(),
                severity: _magnitudeToSeverity(p.mag),
                url: p.url || ''
            };
        });
    }

    /**
     * Normalize NASA EONET events.
     */
    function eonetEvents(data) {
        if (!data || !data.events) return [];
        var results = [];
        data.events.forEach(function (evt) {
            var geom = evt.geometry && evt.geometry[evt.geometry.length - 1];
            if (!geom || !geom.coordinates) return;
            results.push({
                id: evt.id || Math.random().toString(36).substr(2, 9),
                lon: geom.coordinates[0],
                lat: geom.coordinates[1],
                type: 'disaster',
                subtype: _eonetCategory(evt.categories),
                title: evt.title || 'Natural event',
                timestamp: geom.date ? new Date(geom.date).getTime() : Date.now(),
                severity: 'high',
                url: evt.link || ''
            });
        });
        return results;
    }

    /**
     * Normalize NWS weather alerts.
     */
    function nwsAlerts(data) {
        if (!data || !data.features) return [];
        return data.features.map(function (f) {
            var p = f.properties || {};
            var coords = _extractCentroid(f.geometry);
            return {
                id: p.id || Math.random().toString(36).substr(2, 9),
                lon: coords[0],
                lat: coords[1],
                type: 'weather',
                title: p.headline || p.event || 'Weather alert',
                severity: (p.severity || 'unknown').toLowerCase(),
                urgency: (p.urgency || '').toLowerCase(),
                area: p.areaDesc || '',
                timestamp: p.onset ? new Date(p.onset).getTime() : Date.now(),
                expires: p.expires ? new Date(p.expires).getTime() : null,
                geometry: f.geometry,
                url: p['@id'] || ''
            };
        });
    }

    function _extractCentroid(geometry) {
        if (!geometry) return [0, 0];
        if (geometry.type === 'Point') return geometry.coordinates;
        if (geometry.type === 'Polygon' && geometry.coordinates && geometry.coordinates[0]) {
            var ring = geometry.coordinates[0];
            var lon = 0, lat = 0;
            for (var i = 0; i < ring.length; i++) { lon += ring[i][0]; lat += ring[i][1]; }
            return [lon / ring.length, lat / ring.length];
        }
        if (geometry.type === 'MultiPolygon' && geometry.coordinates && geometry.coordinates[0]) {
            var ring2 = geometry.coordinates[0][0];
            if (!ring2) return [0, 0];
            var lo = 0, la = 0;
            for (var j = 0; j < ring2.length; j++) { lo += ring2[j][0]; la += ring2[j][1]; }
            return [lo / ring2.length, la / ring2.length];
        }
        return [0, 0];
    }

    /**
     * Normalize GDELT DOC API news articles.
     */
    function gdeltNews(data) {
        if (!data || !data.articles) return [];
        return data.articles.map(function (a) {
            return {
                id: a.url || Math.random().toString(36).substr(2, 9),
                title: a.title || '',
                source: a.domain || a.sourcecountry || '',
                url: a.url || '',
                image: a.socialimage || '',
                language: a.language || 'English',
                timestamp: a.seendate ? _parseGdeltDate(a.seendate) : Date.now(),
                category: _categorizeNews(a.title || '')
            };
        });
    }

    /**
     * Normalize GDELT DOC API artlist into geo-located event points.
     * Extracts country from sourcecountry field and maps to centroid coords.
     * Used as replacement for dead GDELT GEO API (404 since ~2026-03).
     */
    function gdeltDocToGeo(data, eventType) {
        if (!data || !data.articles) return [];
        var seen = {};
        return data.articles.reduce(function (results, a) {
            var country = (a.sourcecountry || '').toUpperCase().trim();
            var coords = COUNTRY_CENTROIDS[country];
            if (!coords) return results;
            /* Jitter coords slightly to avoid stacking */
            var jitterKey = country + '-' + results.length;
            if (seen[country]) {
                coords = [
                    coords[0] + (Math.random() - 0.5) * 4,
                    coords[1] + (Math.random() - 0.5) * 4
                ];
            }
            seen[country] = true;
            results.push({
                id: a.url || Math.random().toString(36).substr(2, 9),
                lon: coords[0],
                lat: coords[1],
                type: eventType || 'event',
                title: a.title || 'Unknown event',
                source: a.domain || a.sourcecountry || 'GDELT',
                url: a.url || '',
                country: country,
                timestamp: a.seendate ? _parseGdeltDate(a.seendate) : Date.now(),
                severity: _estimateConflictSeverity({ name: a.title || '' })
            });
            return results;
        }, []);
    }

    /* Country centroids for mapping GDELT sourcecountry to coordinates */
    var COUNTRY_CENTROIDS = {
        'UNITED STATES': [-98.5, 39.8], 'CHINA': [104.1, 35.8], 'RUSSIA': [105.3, 61.5],
        'GERMANY': [10.4, 51.1], 'UNITED KINGDOM': [-3.4, 55.3], 'FRANCE': [2.2, 46.2],
        'BRAZIL': [-51.9, -14.2], 'INDIA': [78.9, 20.5], 'JAPAN': [138.2, 36.2],
        'SOUTH KOREA': [127.7, 35.9], 'AUSTRALIA': [133.7, -25.2], 'CANADA': [-106.3, 56.1],
        'NETHERLANDS': [5.2, 52.1], 'UKRAINE': [31.1, 48.3], 'IRAN': [53.6, 32.4],
        'ISRAEL': [34.8, 31.0], 'SAUDI ARABIA': [45.0, 23.8], 'NIGERIA': [8.6, 9.0],
        'SOUTH AFRICA': [22.9, -30.5], 'MEXICO': [-102.5, 23.6], 'SINGAPORE': [103.8, 1.3],
        'NORTH KOREA': [127.5, 40.3], 'PAKISTAN': [69.3, 30.3], 'EGYPT': [30.8, 26.8],
        'TURKEY': [35.2, 38.9], 'INDONESIA': [113.9, -0.7], 'VIETNAM': [108.2, 14.0],
        'PHILIPPINES': [121.7, 12.8], 'THAILAND': [100.9, 15.8], 'POLAND': [19.1, 51.9],
        'ITALY': [12.5, 41.9], 'SPAIN': [-3.7, 40.4], 'SWEDEN': [18.6, 60.1],
        'ARGENTINA': [-63.6, -38.4], 'COLOMBIA': [-74.3, 4.6], 'IRAQ': [44.4, 33.2],
        'SYRIA': [38.9, 34.8], 'AFGHANISTAN': [67.7, 33.9], 'YEMEN': [48.5, 15.5],
        'LEBANON': [35.8, 33.8], 'PALESTINE': [35.2, 31.9], 'SUDAN': [30.2, 12.8],
        'ETHIOPIA': [40.5, 9.1], 'SOMALIA': [46.2, 5.1], 'CONGO': [21.7, -4.0],
        'MYANMAR': [96.0, 21.9], 'TAIWAN': [120.9, 23.7], 'GREECE': [21.8, 39.0],
        'LIBYA': [17.2, 26.3], 'ALGERIA': [1.6, 28.0], 'MOROCCO': [-7.0, 31.8],
        'KENYA': [37.9, -0.0], 'TANZANIA': [34.8, -6.3], 'CHILE': [-71.5, -35.6],
        'PERU': [-75.0, -9.1], 'VENEZUELA': [-66.5, 6.4], 'CUBA': [-77.7, 21.5],
        'NORWAY': [8.4, 60.4], 'FINLAND': [25.7, 61.9], 'DENMARK': [9.5, 56.2],
        'BELGIUM': [4.4, 50.5], 'SWITZERLAND': [8.2, 46.8], 'AUSTRIA': [14.5, 47.5],
        'PORTUGAL': [-8.2, 39.4], 'CZECH REPUBLIC': [15.4, 49.8], 'ROMANIA': [24.9, 45.9],
        'HUNGARY': [19.5, 47.1], 'IRELAND': [-8.2, 53.4], 'NEW ZEALAND': [174.8, -40.9],
        'BANGLADESH': [90.3, 23.6], 'NEPAL': [84.1, 28.3], 'SRI LANKA': [80.7, 7.8],
        'MALAYSIA': [101.9, 4.2], 'JORDAN': [36.2, 30.5], 'QATAR': [51.1, 25.3],
        'KUWAIT': [47.4, 29.3], 'UAE': [53.8, 23.4], 'GEORGIA': [43.3, 42.3],
        'ARMENIA': [45.0, 40.0], 'AZERBAIJAN': [47.5, 40.1], 'TUNISIA': [9.5, 33.8],
        'MOZAMBIQUE': [35.5, -18.6], 'ZAMBIA': [27.8, -13.1], 'ZIMBABWE': [29.1, -19.0],
        'CAMEROON': [12.3, 7.3], 'GHANA': [-1.0, 7.9], 'SENEGAL': [-14.4, 14.4],
        'MALI': [-1.9, 17.5], 'NIGER': [8.0, 17.6], 'CHAD': [18.7, 15.4],
        'BURKINA FASO': [-1.5, 12.3], 'HAITI': [-72.2, 18.9], 'HONDURAS': [-86.2, 15.2],
        'GUATEMALA': [-90.2, 15.7], 'EL SALVADOR': [-88.8, 13.7], 'NICARAGUA': [-85.2, 12.8],
        'COSTA RICA': [-83.7, 10.0], 'PANAMA': [-80.8, 8.5], 'ECUADOR': [-78.1, -1.8],
        'BOLIVIA': [-65.2, -16.3], 'PARAGUAY': [-58.4, -23.4], 'URUGUAY': [-55.7, -32.5]
    };

    /* -- Helpers ---------------------------------------------------------- */

    function _parseGdeltDate(str) {
        /* GDELT format: YYYYMMDDHHmmss */
        if (!str || str.length < 8) return Date.now();
        var y = str.substr(0, 4), m = str.substr(4, 2), d = str.substr(6, 2);
        var h = str.substr(8, 2) || '00', mi = str.substr(10, 2) || '00';
        return new Date(y + '-' + m + '-' + d + 'T' + h + ':' + mi + ':00Z').getTime();
    }

    function _estimateConflictSeverity(p) {
        var name = ((p.name || '') + ' ' + (p.html || '')).toLowerCase();
        if (name.indexOf('killed') !== -1 || name.indexOf('dead') !== -1) return 'critical';
        if (name.indexOf('attack') !== -1 || name.indexOf('bomb') !== -1) return 'high';
        if (name.indexOf('protest') !== -1 || name.indexOf('clash') !== -1) return 'medium';
        return 'low';
    }

    function _magnitudeToSeverity(mag) {
        if (mag >= 7) return 'critical';
        if (mag >= 5.5) return 'high';
        if (mag >= 4) return 'medium';
        return 'low';
    }

    function _eonetCategory(cats) {
        if (!cats || !cats.length) return 'other';
        var id = (cats[0].id || cats[0].title || '').toLowerCase();
        if (id.indexOf('wildfire') !== -1 || id === '8') return 'wildfire';
        if (id.indexOf('volcan') !== -1 || id === '12') return 'volcano';
        if (id.indexOf('storm') !== -1 || id === '10') return 'storm';
        if (id.indexOf('flood') !== -1 || id === '9') return 'flood';
        if (id.indexOf('ice') !== -1 || id === '15') return 'ice';
        return 'other';
    }

    function _categorizeNews(title) {
        var t = title.toLowerCase();
        if (/war|conflict|attack|military|strike|bomb|troops/.test(t)) return 'conflict';
        if (/earthquake|flood|wildfire|hurricane|tornado|tsunami|volcano/.test(t)) return 'disaster';
        if (/weather|storm|heat|cold|rain|snow/.test(t)) return 'weather';
        if (/cyber|hack|breach|ransomware|malware|phishing/.test(t)) return 'cyber';
        if (/sanction|tariff|trade war|embargo/.test(t)) return 'politics';
        return 'general';
    }

    return {
        gdeltGeo: gdeltGeo,
        gdeltDocToGeo: gdeltDocToGeo,
        usgsEarthquakes: usgsEarthquakes,
        eonetEvents: eonetEvents,
        nwsAlerts: nwsAlerts,
        gdeltNews: gdeltNews
    };
})();
