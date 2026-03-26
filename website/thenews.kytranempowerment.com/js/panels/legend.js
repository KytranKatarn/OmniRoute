/* ==========================================================================
   Kytran News — Dynamic Legend
   Syncs legend visibility with active layers
   ========================================================================== */

var Legend = (function () {
    'use strict';

    var _legendEl = null;

    function init() {
        _legendEl = document.getElementById('map-legend');
        if (!_legendEl) return;

        EventBus.on('layer:toggle', _updateVisibility);
        _updateVisibility();
    }

    function _updateVisibility() {
        if (!_legendEl) return;
        var items = _legendEl.querySelectorAll('.map-legend__item');
        var layerMap = {
            'Conflict': 'conflicts',
            'Earthquake': 'disasters',
            'Weather': 'weather',
            'Cyber': 'cyber',
            'Military': 'military',
            'Sanctions': 'sanctions',
            'Outage': 'outages'
        };

        items.forEach(function (item) {
            var text = item.textContent.trim();
            var layerKey = layerMap[text];
            if (layerKey) {
                item.style.display = App.isLayerActive(layerKey) ? '' : 'none';
            }
        });
    }

    return { init: init };
})();
