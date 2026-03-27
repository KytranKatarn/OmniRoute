/* ==========================================================================
   Kytran News — Detail Panel
   Slide-out panel showing full event details on map click
   ========================================================================== */

var Detail = (function () {
    'use strict';

    var _panelEl = null;
    var _isOpen = false;

    function init() {
        _createPanel();

        /* Close on Escape */
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && _isOpen) close();
        });
    }

    function _createPanel() {
        _panelEl = document.createElement('div');
        _panelEl.className = 'detail-panel';
        _panelEl.setAttribute('role', 'dialog');
        _panelEl.setAttribute('aria-label', 'Event details');
        document.querySelector('.map-container').appendChild(_panelEl);
    }

    function show(object) {
        if (!_panelEl || !object) return;

        var type = object.type || 'unknown';
        var color = _getTypeColor(type);

        /* Build content safely via DOM */
        while (_panelEl.firstChild) _panelEl.removeChild(_panelEl.firstChild);

        /* Close button */
        var closeBtn = document.createElement('button');
        closeBtn.className = 'detail-panel__close';
        closeBtn.setAttribute('aria-label', 'Close');
        closeBtn.textContent = '\u00D7';
        closeBtn.addEventListener('click', close);
        _panelEl.appendChild(closeBtn);

        /* Type badge */
        var badge = document.createElement('div');
        badge.className = 'detail-panel__badge';
        badge.style.background = color;
        badge.textContent = _formatType(type);
        _panelEl.appendChild(badge);

        /* Title */
        var title = document.createElement('h3');
        title.className = 'detail-panel__title';
        title.textContent = object.title || object.name || 'Unknown Event';
        _panelEl.appendChild(title);

        /* Meta rows */
        var meta = document.createElement('div');
        meta.className = 'detail-panel__meta';

        if (object.type === 'earthquake') {
            _addRow(meta, 'Magnitude', object.magnitude || '?');
            _addRow(meta, 'Depth', object.depth ? object.depth.toFixed(1) + ' km' : '?');
        }
        if (object.type === 'conflict') {
            _addRow(meta, 'Source', object.source || '?');
            _addRow(meta, 'Severity', object.severity || '?');
        }
        if (object.type === 'weather') {
            _addRow(meta, 'Severity', object.severity || '?');
            _addRow(meta, 'Urgency', object.urgency || '?');
            _addRow(meta, 'Area', object.area || '?');
            if (object.expires) {
                _addRow(meta, 'Expires', new Date(object.expires).toLocaleString());
            }
        }
        if (object.type === 'disaster') {
            _addRow(meta, 'Sub-type', object.subtype || '?');
        }
        if (object.type === 'cyber') {
            _addRow(meta, 'Attack Type', object.attackType || '?');
            _addRow(meta, 'Source', object.sourceCountry || '?');
            _addRow(meta, 'Target', object.targetCountry || '?');
            _addRow(meta, 'Intensity', object.intensity ? object.intensity.toFixed(1) : '?');
        }
        if (object.type === 'military') {
            _addRow(meta, 'Type', object.subtype || '?');
            _addRow(meta, 'Country', object.country || '?');
        }
        if (object.type === 'flight') {
            _addRow(meta, 'Callsign', object.callsign || '?');
            _addRow(meta, 'Origin', object.origin || '?');
            _addRow(meta, 'Altitude', object.altitude ? Math.round(object.altitude) + ' m' : '?');
            _addRow(meta, 'Speed', object.velocity ? Math.round(object.velocity) + ' m/s' : '?');
        }
        if (object.type === 'ship') {
            _addRow(meta, 'Location', object.port || object.route || '?');
            _addRow(meta, 'Country', object.country || '?');
        }
        if (object.type === 'disease') {
            _addRow(meta, 'Country', object.country || '?');
            _addRow(meta, 'Status', object.status || '?');
        }

        /* Coordinates */
        if (object.lat != null && object.lon != null) {
            _addRow(meta, 'Coordinates', object.lat.toFixed(2) + ', ' + object.lon.toFixed(2));
        }

        /* Timestamp */
        if (object.timestamp) {
            _addRow(meta, 'Time', new Date(object.timestamp).toLocaleString());
        }

        _panelEl.appendChild(meta);

        /* Link button */
        if (object.url) {
            var link = document.createElement('a');
            link.className = 'detail-panel__link';
            link.href = object.url;
            link.target = '_blank';
            link.rel = 'noopener';
            link.textContent = 'View Source \u2192';
            _panelEl.appendChild(link);
        }

        /* Fly to location */
        if (object.lat != null && object.lon != null) {
            var flyBtn = document.createElement('button');
            flyBtn.className = 'detail-panel__fly';
            flyBtn.textContent = 'Zoom to Location';
            flyBtn.addEventListener('click', function () {
                KytranMap.flyTo(object.lat, object.lon, 8);
            });
            _panelEl.appendChild(flyBtn);
        }

        _panelEl.classList.add('open');
        _isOpen = true;
    }

    function close() {
        if (_panelEl) _panelEl.classList.remove('open');
        _isOpen = false;
    }

    function _addRow(parent, label, value) {
        var row = document.createElement('div');
        row.className = 'detail-panel__row';

        var labelEl = document.createElement('span');
        labelEl.className = 'detail-panel__label';
        labelEl.textContent = label;
        row.appendChild(labelEl);

        var valueEl = document.createElement('span');
        valueEl.className = 'detail-panel__value';
        valueEl.textContent = value;
        row.appendChild(valueEl);

        parent.appendChild(row);
    }

    function _getTypeColor(type) {
        var colors = {
            conflict: 'rgba(255, 59, 59, 0.8)',
            earthquake: 'rgba(255, 109, 0, 0.8)',
            disaster: 'rgba(255, 109, 0, 0.8)',
            weather: 'rgba(64, 196, 255, 0.8)',
            cyber: 'rgba(139, 92, 246, 0.8)',
            outage: 'rgba(255, 170, 0, 0.8)',
            military: 'rgba(118, 255, 3, 0.8)',
            flight: 'rgba(0, 200, 255, 0.8)',
            ship: 'rgba(0, 180, 216, 0.8)',
            disease: 'rgba(0, 255, 136, 0.8)'
        };
        return colors[type] || 'rgba(255, 255, 255, 0.3)';
    }

    function _formatType(type) {
        return (type || 'unknown').charAt(0).toUpperCase() + (type || 'unknown').slice(1);
    }

    function isOpen() { return _isOpen; }

    return { init: init, show: show, close: close, isOpen: isOpen };
})();
