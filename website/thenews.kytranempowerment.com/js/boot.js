/* ==========================================================================
   Kytran News — Boot Screen
   Military-style boot sequence with progress steps
   ========================================================================== */
(function () {
    'use strict';

    var BOOT_STEPS = [
        { pct: 5,   msg: 'INITIALIZING FEEDS...' },
        { pct: 15,  msg: 'CONNECTING GDELT STREAM...' },
        { pct: 25,  msg: 'LOADING USGS SEISMIC DATA...' },
        { pct: 35,  msg: 'SYNCING NWS WEATHER ALERTS...' },
        { pct: 45,  msg: 'SCANNING CYBER THREAT FEEDS...' },
        { pct: 55,  msg: 'MAPPING CONFLICT ZONES...' },
        { pct: 65,  msg: 'LOADING SANCTIONS DATABASE...' },
        { pct: 75,  msg: 'INITIALIZING MAP ENGINE...' },
        { pct: 85,  msg: 'CALIBRATING THREAT INDEX...' },
        { pct: 95,  msg: 'ESTABLISHING LIVE CONNECTIONS...' },
        { pct: 100, msg: 'OPERATIONAL' }
    ];

    /**
     * Run the boot sequence animation.
     * Accepts an optional callback to fire when boot completes.
     */
    window.KNBoot = {
        run: function (onComplete) {
            var screen = document.getElementById('boot-screen');
            var bar = document.getElementById('boot-bar');
            var status = document.getElementById('boot-status');

            if (!screen) {
                if (onComplete) onComplete();
                return;
            }

            var stepIndex = 0;

            function nextStep() {
                if (stepIndex >= BOOT_STEPS.length) {
                    // Boot complete — fade out
                    setTimeout(function () {
                        screen.classList.add('fade-out');
                        setTimeout(function () {
                            screen.style.display = 'none';
                            if (onComplete) onComplete();
                        }, 800);
                    }, 400);
                    return;
                }

                var step = BOOT_STEPS[stepIndex];
                if (bar) bar.style.width = step.pct + '%';
                if (status) status.textContent = step.msg;
                stepIndex++;

                // Randomized delay for realism (80-250ms per step)
                var delay = 80 + Math.random() * 170;
                setTimeout(nextStep, delay);
            }

            nextStep();
        },

        /**
         * Update boot progress externally (for real data loading).
         */
        setProgress: function (pct, msg) {
            var bar = document.getElementById('boot-bar');
            var status = document.getElementById('boot-status');
            if (bar) bar.style.width = pct + '%';
            if (status && msg) status.textContent = msg;
        },

        /**
         * Dismiss the boot screen immediately.
         */
        dismiss: function () {
            var screen = document.getElementById('boot-screen');
            if (screen) {
                screen.classList.add('fade-out');
                setTimeout(function () { screen.style.display = 'none'; }, 800);
            }
        }
    };
})();
