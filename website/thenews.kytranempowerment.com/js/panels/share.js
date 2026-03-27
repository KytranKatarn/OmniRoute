/* ==========================================================================
   Kytran News — Share / URL State
   Encode current view state in URL for sharing, restore on load
   ========================================================================== */

var Share = (function () {
    'use strict';

    function init() {
        /* Restore state from URL on load */
        _restoreFromUrl();

        /* Add share button click handler */
        var btn = document.getElementById('share-btn');
        if (btn) btn.addEventListener('click', copyShareLink);
    }

    function _restoreFromUrl() {
        var params = new URLSearchParams(window.location.search);

        /* Region */
        var region = params.get('region');
        if (region && Config.REGIONS[region]) {
            var sel = document.getElementById('region-select');
            if (sel) { sel.value = region; sel.dispatchEvent(new Event('change')); }
        }

        /* Time range */
        var time = params.get('time');
        if (time && Config.TIME_RANGES[time]) {
            var tsel = document.getElementById('time-select');
            if (tsel) { tsel.value = time; tsel.dispatchEvent(new Event('change')); }
        }

        /* Active layers from URL (comma-separated) */
        var layers = params.get('layers');
        if (layers) {
            var activeKeys = layers.split(',');
            Object.keys(Config.LAYERS).forEach(function (key) {
                var toggle = document.querySelector('.layer-toggle[data-layer="' + key + '"]');
                if (!toggle) return;
                var shouldBeActive = activeKeys.indexOf(key) !== -1;
                var isActive = toggle.classList.contains('active');
                if (shouldBeActive !== isActive) toggle.click();
            });
        }

        /* Zoom/lat/lon */
        var lat = parseFloat(params.get('lat'));
        var lon = parseFloat(params.get('lon'));
        var zoom = parseFloat(params.get('zoom'));
        if (!isNaN(lat) && !isNaN(lon)) {
            setTimeout(function () {
                KytranMap.flyTo(lat, lon, isNaN(zoom) ? 4 : zoom);
            }, 2500); /* wait for map init */
        }
    }

    function getShareUrl() {
        var vs = KytranMap.getViewState();
        var region = document.getElementById('region-select');
        var time = document.getElementById('time-select');

        /* Collect active layers */
        var activeLayers = [];
        document.querySelectorAll('.layer-toggle.active').forEach(function (el) {
            if (el.dataset.layer) activeLayers.push(el.dataset.layer);
        });

        var params = new URLSearchParams();
        params.set('lat', vs.latitude.toFixed(2));
        params.set('lon', vs.longitude.toFixed(2));
        params.set('zoom', vs.zoom.toFixed(1));
        if (region) params.set('region', region.value);
        if (time) params.set('time', time.value);
        if (activeLayers.length > 0) params.set('layers', activeLayers.join(','));

        return window.location.origin + window.location.pathname + '?' + params.toString();
    }

    function copyShareLink() {
        var url = getShareUrl();
        if (navigator.clipboard) {
            navigator.clipboard.writeText(url).then(function () {
                _showToast('Link copied to clipboard');
            });
        } else {
            /* Fallback */
            var input = document.createElement('input');
            input.value = url;
            document.body.appendChild(input);
            input.select();
            document.execCommand('copy');
            document.body.removeChild(input);
            _showToast('Link copied to clipboard');
        }
    }

    function _showToast(msg) {
        var toast = document.createElement('div');
        toast.className = 'share-toast';
        toast.textContent = msg;
        document.body.appendChild(toast);
        setTimeout(function () { toast.classList.add('visible'); }, 10);
        setTimeout(function () {
            toast.classList.remove('visible');
            setTimeout(function () { document.body.removeChild(toast); }, 300);
        }, 2000);
    }

    return { init: init, getShareUrl: getShareUrl, copyShareLink: copyShareLink };
})();
