/* ==========================================================================
   Kytran News — Time Machine Slider
   Controls time range filtering and live/replay modes
   ========================================================================== */
(function () {
    'use strict';

    function initTimeMachine() {
        var rangeButtons = document.querySelectorAll('.timeline-slider__btn');
        var slider = document.getElementById('time-slider');
        var rangeLabel = document.getElementById('time-range-label');
        var liveBtn = document.getElementById('tm-live');
        var replayBtn = document.getElementById('tm-replay');

        var currentRange = '24h';
        var isLive = true;

        // Range button clicks
        rangeButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                rangeButtons.forEach(function (b) { b.classList.remove('active'); });
                btn.classList.add('active');
                currentRange = btn.getAttribute('data-range');

                // Reset slider to max (live position)
                if (slider) {
                    slider.value = 100;
                }
                updateRangeLabel();

                // Dispatch event for other modules to listen to
                window.dispatchEvent(new CustomEvent('timemachine:rangechange', {
                    detail: { range: currentRange, position: 100, live: isLive }
                }));
            });
        });

        // Slider input
        if (slider) {
            slider.addEventListener('input', function () {
                var val = parseInt(slider.value, 10);
                if (val < 100 && isLive) {
                    setReplayMode();
                } else if (val === 100 && !isLive) {
                    setLiveMode();
                }
                updateRangeLabel();

                window.dispatchEvent(new CustomEvent('timemachine:slide', {
                    detail: { range: currentRange, position: val, live: val === 100 }
                }));
            });
        }

        // Mode buttons
        if (liveBtn) {
            liveBtn.addEventListener('click', function () {
                setLiveMode();
                if (slider) slider.value = 100;
                updateRangeLabel();
            });
        }
        if (replayBtn) {
            replayBtn.addEventListener('click', function () {
                setReplayMode();
                if (slider) slider.value = 50;
                updateRangeLabel();
            });
        }

        function setLiveMode() {
            isLive = true;
            if (liveBtn) liveBtn.classList.add('active');
            if (replayBtn) replayBtn.classList.remove('active');
        }

        function setReplayMode() {
            isLive = false;
            if (replayBtn) replayBtn.classList.add('active');
            if (liveBtn) liveBtn.classList.remove('active');
        }

        function updateRangeLabel() {
            if (!rangeLabel) return;
            if (isLive || (slider && parseInt(slider.value, 10) === 100)) {
                rangeLabel.textContent = 'LIVE';
                rangeLabel.style.color = 'var(--color-safe)';
            } else {
                var pct = slider ? parseInt(slider.value, 10) : 0;
                rangeLabel.textContent = pct + '% OF ' + currentRange.toUpperCase();
                rangeLabel.style.color = 'var(--color-primary)';
            }
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTimeMachine);
    } else {
        initTimeMachine();
    }
})();
