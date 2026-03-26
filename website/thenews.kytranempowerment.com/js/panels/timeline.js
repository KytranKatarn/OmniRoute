/* ==========================================================================
   Kytran News — Timeline Panel
   Time range selector logic + keyboard shortcuts
   ========================================================================== */

var Timeline = (function () {
    'use strict';

    var _ranges = ['1h', '6h', '24h', '48h', '7d'];

    function init() {
        /* Keyboard shortcuts: T + number for time ranges */
        document.addEventListener('keydown', function (e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            var rangeMap = {
                'q': '1h',
                'w': '6h',
                'e': '24h',
                'r': '48h',
                't': '7d'
            };

            if (rangeMap[e.key]) {
                var sel = document.getElementById('time-select');
                if (sel) {
                    sel.value = rangeMap[e.key];
                    sel.dispatchEvent(new Event('change'));
                }
            }
        });
    }

    return { init: init };
})();
