/* ==========================================================================
   Kytran News — Region Views
   Fly-to presets for world regions
   ========================================================================== */

var Regions = (function () {
    'use strict';

    function init() {
        /* Region change is handled in App via the select element.
           This module provides additional keyboard shortcuts. */
        document.addEventListener('keydown', function (e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
            var regionMap = {
                '1': 'world',
                '2': 'americas',
                '3': 'europe',
                '4': 'asia',
                '5': 'mena',
                '6': 'africa'
            };
            if (regionMap[e.key]) {
                var sel = document.getElementById('region-select');
                if (sel) sel.value = regionMap[e.key];
                EventBus.emit('region:change', regionMap[e.key]);
            }
        });
    }

    return { init: init };
})();
