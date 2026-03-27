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
        usgsEarthquakes: usgsEarthquakes,
        eonetEvents: eonetEvents,
        nwsAlerts: nwsAlerts,
        gdeltNews: gdeltNews
    };
})();
