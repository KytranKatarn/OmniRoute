/* ==========================================================================
   Kytran News — Visual Effects
   Ambient glow, stat counter animations, cursor effects
   ========================================================================== */

var Effects = (function () {
    'use strict';

    function init() {
        _initStatCounters();
        _initCursorGlow();
        _initLastUpdated();
        _initUtcClock();
    }

    /* -- Animated stat counters ------------------------------------------- */
    function _initStatCounters() {
        var _counts = {};
        var countriesSet = new Set();

        function _updateStats() {
            var total = Object.keys(_counts).reduce(function (s, k) { return s + _counts[k]; }, 0);
            _animateCounter('stat-events', total);
            _animateCounter('stat-countries', countriesSet.size);
            /* Update topbar event counter */
            var topEl = document.getElementById('topbar-event-count');
            if (topEl) topEl.textContent = total.toLocaleString();
            /* Update status bar counts */
            var sbEvents = document.getElementById('sb-events');
            if (sbEvents) sbEvents.textContent = total.toLocaleString();
            var sbCountries = document.getElementById('sb-countries');
            if (sbCountries) sbCountries.textContent = countriesSet.size;
            var sbSources = document.getElementById('sb-sources');
            var sourceCount = Object.keys(_counts).filter(function (k) { return _counts[k] > 0; }).length;
            if (sbSources) sbSources.textContent = sourceCount;
        }

        EventBus.on('data:conflicts:updated', function (d) {
            _counts.conflicts = d.length;
            d.forEach(function (item) { if (item.source) countriesSet.add(item.source); });
            _updateStats();
        });

        EventBus.on('data:disasters:updated', function (d) {
            _counts.disasters = (d.earthquakes || []).length + (d.eonet || []).length;
            _updateStats();
        });

        EventBus.on('data:weather:updated', function (d) {
            _counts.weather = d.length;
            _updateStats();
        });

        EventBus.on('data:cyber:updated', function (d) {
            _counts.cyber = d.length;
            d.forEach(function (item) {
                if (item.sourceCountry) countriesSet.add(item.sourceCountry);
                if (item.targetCountry) countriesSet.add(item.targetCountry);
            });
            _updateStats();
        });

        EventBus.on('data:outages:updated', function (d) {
            _counts.outages = d.length;
            _updateStats();
        });
    }

    function _animateCounter(elId, targetValue) {
        var el = document.getElementById(elId);
        if (!el) return;
        var current = parseInt(el.textContent) || 0;
        if (current === targetValue) return;

        var diff = targetValue - current;
        var steps = Math.min(Math.abs(diff), 20);
        var stepValue = diff / steps;
        var step = 0;

        function tick() {
            step++;
            var val = Math.round(current + stepValue * step);
            el.textContent = val.toLocaleString();
            if (step < steps) requestAnimationFrame(tick);
            else el.textContent = targetValue.toLocaleString();
        }
        requestAnimationFrame(tick);
    }

    /* -- Last updated timestamp ------------------------------------------ */
    function _initLastUpdated() {
        var el = document.getElementById('last-updated');
        if (!el) return;

        function update() {
            var now = new Date();
            el.textContent = now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
                ' \u2014 ' + now.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
        }

        /* Update on any data refresh */
        var events = ['data:conflicts:updated', 'data:disasters:updated', 'data:weather:updated', 'data:cyber:updated', 'data:outages:updated'];
        events.forEach(function (evt) { EventBus.on(evt, update); });

        /* Also update news stat card */
        EventBus.on('data:conflicts:updated', function () {
            /* Recalculate total articles from ticker */
            if (typeof Ticker !== 'undefined') {
                _animateCounter('stat-news', Ticker.getData().length);
            }
        });
    }

    /* -- UTC Clock -------------------------------------------------------- */
    function _initUtcClock() {
        var el = document.getElementById('utc-clock');
        if (!el) return;
        function tick() {
            var now = new Date();
            var h = String(now.getUTCHours()).padStart(2, '0');
            var m = String(now.getUTCMinutes()).padStart(2, '0');
            var s = String(now.getUTCSeconds()).padStart(2, '0');
            var day = now.toLocaleDateString('en-US', { timeZone: 'UTC', day: '2-digit', month: 'short', year: 'numeric' });
            el.textContent = h + ':' + m + ':' + s + ' UTC \u2014 ' + day;
        }
        tick();
        setInterval(tick, 1000);
    }

    /* -- Subtle cursor glow on map --------------------------------------- */
    function _initCursorGlow() {
        var mapContainer = document.querySelector('.map-container');
        if (!mapContainer || mapContainer.querySelector('.map-cursor-glow')) return;

        var glow = document.createElement('div');
        glow.className = 'map-cursor-glow';
        glow.style.cssText = 'position:absolute;width:120px;height:120px;border-radius:50%;pointer-events:none;z-index:2;opacity:0;transition:opacity 0.3s;background:radial-gradient(circle,rgba(0,229,255,0.06) 0%,transparent 70%)';
        mapContainer.appendChild(glow);

        mapContainer.addEventListener('mouseenter', function () { glow.style.opacity = '1'; });
        mapContainer.addEventListener('mouseleave', function () { glow.style.opacity = '0'; });
        mapContainer.addEventListener('mousemove', function (e) {
            var rect = mapContainer.getBoundingClientRect();
            glow.style.left = (e.clientX - rect.left - 60) + 'px';
            glow.style.top = (e.clientY - rect.top - 60) + 'px';
        });
    }

    return { init: init };
})();
