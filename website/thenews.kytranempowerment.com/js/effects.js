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
    }

    /* -- Animated stat counters ------------------------------------------- */
    function _initStatCounters() {
        /* Listen for data updates to animate stat cards */
        var totalEvents = 0;
        var countriesSet = new Set();

        function _updateStats() {
            _animateCounter('stat-events', totalEvents);
            _animateCounter('stat-countries', countriesSet.size);
        }

        EventBus.on('data:conflicts:updated', function (d) {
            totalEvents += d.length;
            d.forEach(function (item) { if (item.source) countriesSet.add(item.source); });
            _updateStats();
        });

        EventBus.on('data:disasters:updated', function (d) {
            var eq = d.earthquakes || [];
            var eo = d.eonet || [];
            totalEvents += eq.length + eo.length;
            _updateStats();
        });

        EventBus.on('data:weather:updated', function (d) {
            totalEvents += d.length;
            _updateStats();
        });

        EventBus.on('data:cyber:updated', function (d) {
            totalEvents += d.length;
            d.forEach(function (item) {
                if (item.sourceCountry) countriesSet.add(item.sourceCountry);
                if (item.targetCountry) countriesSet.add(item.targetCountry);
            });
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

    /* -- Subtle cursor glow on map --------------------------------------- */
    function _initCursorGlow() {
        var mapContainer = document.querySelector('.map-container');
        if (!mapContainer) return;

        var glow = document.createElement('div');
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
