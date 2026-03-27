/* ==========================================================================
   Kytran News — Data Export
   Export currently visible events as CSV or JSON
   ========================================================================== */

var Export = (function () {
    'use strict';

    function init() {
        var csvBtn = document.getElementById('export-csv');
        var jsonBtn = document.getElementById('export-json');
        if (csvBtn) csvBtn.addEventListener('click', function () { exportData('csv'); });
        if (jsonBtn) jsonBtn.addEventListener('click', function () { exportData('json'); });
    }

    function exportData(format) {
        var data = _collectVisibleData();
        if (data.length === 0) {
            alert('No visible data to export. Toggle on some layers first.');
            return;
        }

        var blob, filename;
        if (format === 'csv') {
            blob = new Blob([_toCSV(data)], { type: 'text/csv;charset=utf-8;' });
            filename = 'kytran-news-' + _dateStamp() + '.csv';
        } else {
            blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            filename = 'kytran-news-' + _dateStamp() + '.json';
        }

        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function _collectVisibleData() {
        var all = [];

        var sources = [
            { key: 'conflicts', mod: 'Conflicts', flat: true },
            { key: 'disasters', mod: 'Disasters', flat: false },
            { key: 'weather', mod: 'Weather', flat: true },
            { key: 'outages', mod: 'Outages', flat: true },
            { key: 'protests', mod: 'Protests', flat: true },
            { key: 'terrorism', mod: 'Terrorism', flat: true }
        ];

        sources.forEach(function (s) {
            if (!App.isLayerActive(s.key)) return;
            var mod = window[s.mod];
            if (!mod || !mod.getData) return;
            var data = mod.getData();

            if (s.flat) {
                (Array.isArray(data) ? data : []).forEach(function (d) { all.push(_normalize(d)); });
            } else {
                /* Disasters has nested structure */
                if (data.earthquakes) data.earthquakes.forEach(function (d) { all.push(_normalize(d)); });
                if (data.eonet) data.eonet.forEach(function (d) { all.push(_normalize(d)); });
            }
        });

        /* Static layers */
        ['Military', 'Sanctions', 'Flights', 'Ships', 'AirQuality', 'Disease',
         'SpaceWeather', 'Radiation', 'Internet', 'Economic', 'Social'].forEach(function (name) {
            var mod = window[name];
            if (!mod || !mod.getData) return;
            var key = name.toLowerCase();
            if (key === 'airquality') key = 'airquality';
            if (key === 'spaceweather') key = 'spaceweather';
            if (!App.isLayerActive(key)) return;
            var data = mod.getData();
            (Array.isArray(data) ? data : []).forEach(function (d) { all.push(_normalize(d)); });
        });

        return all;
    }

    function _normalize(d) {
        return {
            type: d.type || 'unknown',
            title: d.title || d.name || '',
            lat: d.lat || null,
            lon: d.lon || null,
            severity: d.severity || d.magnitude || '',
            source: d.source || d.country || '',
            timestamp: d.timestamp ? new Date(d.timestamp).toISOString() : '',
            url: d.url || ''
        };
    }

    function _toCSV(data) {
        var headers = ['type', 'title', 'lat', 'lon', 'severity', 'source', 'timestamp', 'url'];
        var lines = [headers.join(',')];
        data.forEach(function (d) {
            var row = headers.map(function (h) {
                var val = (d[h] == null ? '' : String(d[h]));
                /* Escape CSV */
                if (val.indexOf(',') !== -1 || val.indexOf('"') !== -1 || val.indexOf('\n') !== -1) {
                    val = '"' + val.replace(/"/g, '""') + '"';
                }
                return val;
            });
            lines.push(row.join(','));
        });
        return lines.join('\n');
    }

    function _dateStamp() {
        var d = new Date();
        return d.getFullYear() + '-' +
               String(d.getMonth() + 1).padStart(2, '0') + '-' +
               String(d.getDate()).padStart(2, '0') + '_' +
               String(d.getHours()).padStart(2, '0') +
               String(d.getMinutes()).padStart(2, '0');
    }

    return { init: init, exportData: exportData };
})();
