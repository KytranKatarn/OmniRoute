/* ==========================================================================
   Kytran News — Polling Scheduler
   Manages per-source refresh intervals
   ========================================================================== */

var Scheduler = (function () {
    'use strict';

    var _timers = {};
    var _running = false;

    /**
     * Register and start a polling source.
     * @param {string} key       - Source identifier
     * @param {Function} fetchFn - Async function to call
     * @param {number} interval  - Polling interval in ms
     */
    function start(key, fetchFn, interval) {
        stop(key);
        /* Immediate first fetch */
        fetchFn();
        _timers[key] = {
            id: setInterval(fetchFn, interval),
            interval: interval,
            fn: fetchFn
        };
        _running = true;
    }

    function stop(key) {
        if (_timers[key]) {
            clearInterval(_timers[key].id);
            delete _timers[key];
        }
    }

    function stopAll() {
        Object.keys(_timers).forEach(stop);
        _running = false;
    }

    function restartAll() {
        Object.keys(_timers).forEach(function (key) {
            var entry = _timers[key];
            clearInterval(entry.id);
            entry.fn();
            entry.id = setInterval(entry.fn, entry.interval);
        });
        _running = true;
    }

    function isRunning() { return _running; }

    function getActiveKeys() { return Object.keys(_timers); }

    return {
        start: start,
        stop: stop,
        stopAll: stopAll,
        restartAll: restartAll,
        isRunning: isRunning,
        getActiveKeys: getActiveKeys
    };
})();
