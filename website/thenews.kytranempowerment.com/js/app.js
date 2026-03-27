/* ==========================================================================
   Kytran News — App Entry Point
   Initialize all modules, wire up UI controls, start data polling
   ========================================================================== */

/* -- Event Bus (lightweight pub/sub) ------------------------------------- */
var EventBus = (function () {
    'use strict';
    var _listeners = {};
    function on(event, fn) {
        (_listeners[event] = _listeners[event] || []).push(fn);
    }
    function off(event, fn) {
        if (!_listeners[event]) return;
        _listeners[event] = _listeners[event].filter(function (f) { return f !== fn; });
    }
    function emit(event, data) {
        (_listeners[event] || []).forEach(function (fn) { fn(data); });
    }
    return { on: on, off: off, emit: emit };
})();

/* -- App ----------------------------------------------------------------- */
var App = (function () {
    'use strict';

    var _timeRange = '24h';
    var _region = 'world';
    var _layerState = {};
    var _loadingEl = null;
    var _loadBar = null;
    var _loadStatus = null;
    var _loadProgress = 0;

    function init() {
        _loadingEl = document.getElementById('loading-overlay');
        _loadBar = document.getElementById('loading-bar');
        _loadStatus = document.getElementById('loading-status');

        _setLoadProgress(10, 'Initializing map...');

        /* Initialize layer toggle state from config defaults */
        Object.keys(Config.LAYERS).forEach(function (key) {
            _layerState[key] = Config.LAYERS[key].default;
        });

        /* Initialize map */
        KytranMap.init();
        _setLoadProgress(30, 'Map loaded');

        /* Wire up UI controls */
        _initLayerToggles();
        _initRegionSelector();
        _initTimeSelector();
        _initViewToggle();
        _initSidebarToggle();
        _initZoomControls();
        _setLoadProgress(50, 'Controls ready');

        /* Start data layers */
        _initDataLayers();
        _startAnimationLoop();
        _setLoadProgress(70, 'Fetching data...');

        /* Hide loading after a delay (let first data arrive) */
        setTimeout(function () {
            _setLoadProgress(100, 'Ready');
            setTimeout(function () {
                if (_loadingEl) _loadingEl.classList.add('fade-out');
                setTimeout(function () {
                    if (_loadingEl) _loadingEl.remove();
                }, 800);
            }, 400);
        }, 2000);
    }

    /* -- Loading ---------------------------------------------------------- */
    function _setLoadProgress(pct, status) {
        _loadProgress = pct;
        if (_loadBar) _loadBar.style.width = pct + '%';
        if (_loadStatus) _loadStatus.textContent = status;
    }

    /* -- Layer Toggles ---------------------------------------------------- */
    function _initLayerToggles() {
        var toggles = document.querySelectorAll('.layer-toggle');
        toggles.forEach(function (el) {
            var key = el.dataset.layer;
            if (!key) return;
            if (_layerState[key]) el.classList.add('active');

            el.addEventListener('click', function () {
                _layerState[key] = !_layerState[key];
                el.classList.toggle('active');
                EventBus.emit('layer:toggle', { key: key, visible: _layerState[key] });
            });
        });
    }

    function isLayerActive(key) {
        return !!_layerState[key];
    }

    /* -- Region Selector -------------------------------------------------- */
    function _initRegionSelector() {
        var sel = document.getElementById('region-select');
        if (!sel) return;
        sel.addEventListener('change', function () {
            _region = sel.value;
            EventBus.emit('region:change', _region);
        });
    }

    /* -- Time Selector ---------------------------------------------------- */
    function _initTimeSelector() {
        var sel = document.getElementById('time-select');
        if (!sel) return;
        sel.addEventListener('change', function () {
            _timeRange = sel.value;
            EventBus.emit('timerange:change', _timeRange);
            /* Re-fetch all data with new time range */
            _refreshAllData();
        });
    }

    function getTimeRange() { return _timeRange; }

    /* -- View Toggle (2D/3D) ---------------------------------------------- */
    function _initViewToggle() {
        var btns = document.querySelectorAll('.map-view-toggle__btn');
        btns.forEach(function (btn) {
            btn.addEventListener('click', function () {
                btns.forEach(function (b) { b.classList.remove('active'); });
                btn.classList.add('active');
                var view = btn.dataset.view;
                var vs = KytranMap.getViewState();
                if (view === '3d') {
                    KytranMap.flyTo(vs.latitude, vs.longitude, vs.zoom, 45);
                } else {
                    KytranMap.flyTo(vs.latitude, vs.longitude, vs.zoom, 0);
                }
            });
        });
    }

    /* -- Sidebar Mobile Toggle -------------------------------------------- */
    function _initSidebarToggle() {
        var toggle = document.getElementById('sidebar-toggle');
        var sidebar = document.querySelector('.sidebar');
        var backdrop = document.getElementById('sidebar-backdrop');
        if (!toggle || !sidebar) return;

        function openSidebar() {
            sidebar.classList.add('open');
            if (backdrop) backdrop.classList.add('open');
        }
        function closeSidebar() {
            sidebar.classList.remove('open');
            if (backdrop) backdrop.classList.remove('open');
        }
        toggle.addEventListener('click', openSidebar);
        if (backdrop) backdrop.addEventListener('click', closeSidebar);
    }

    /* -- Zoom Controls ---------------------------------------------------- */
    function _initZoomControls() {
        var zoomIn = document.getElementById('zoom-in');
        var zoomOut = document.getElementById('zoom-out');
        if (zoomIn) {
            zoomIn.addEventListener('click', function () {
                var vs = KytranMap.getViewState();
                KytranMap.flyTo(vs.latitude, vs.longitude, Math.min(vs.zoom + 1, Config.MAP.maxZoom));
            });
        }
        if (zoomOut) {
            zoomOut.addEventListener('click', function () {
                var vs = KytranMap.getViewState();
                KytranMap.flyTo(vs.latitude, vs.longitude, Math.max(vs.zoom - 1, Config.MAP.minZoom));
            });
        }
    }

    /* -- Animation Loop (pulsing markers, refreshing visual layers) ------- */
    function _startAnimationLoop() {
        function tick() {
            /* Re-render pulse layers every 200ms for smooth pulsing */
            if (typeof Disasters !== 'undefined' && _layerState.disasters) {
                Disasters.renderPulse && Disasters.renderPulse();
            }
            if (typeof Conflicts !== 'undefined' && _layerState.conflicts) {
                Conflicts.renderPulse && Conflicts.renderPulse();
            }
            if (typeof Cyber !== 'undefined' && _layerState.cyber) {
                Cyber.renderPulse && Cyber.renderPulse();
            }
            setTimeout(tick, 200);
        }
        tick();
    }

    /* -- Data Layer Initialization ---------------------------------------- */
    function _initDataLayers() {
        /* Each layer module self-registers when loaded */
        if (typeof Conflicts !== 'undefined') Conflicts.init();
        if (typeof Disasters !== 'undefined') Disasters.init();
        if (typeof Weather !== 'undefined') Weather.init();
        if (typeof Cyber !== 'undefined') Cyber.init();
        if (typeof Outages !== 'undefined') Outages.init();
        if (typeof Sanctions !== 'undefined') Sanctions.init();
        if (typeof Military !== 'undefined') Military.init();
        if (typeof Flights !== 'undefined') Flights.init();
        if (typeof AirQuality !== 'undefined') AirQuality.init();
        if (typeof Disease !== 'undefined') Disease.init();
        if (typeof Ships !== 'undefined') Ships.init();
        if (typeof Ticker !== 'undefined') Ticker.init();
        if (typeof Defcon !== 'undefined') Defcon.init();
        if (typeof Detail !== 'undefined') Detail.init();
        if (typeof Search !== 'undefined') Search.init();
        if (typeof Legend !== 'undefined') Legend.init();
        if (typeof Timeline !== 'undefined') Timeline.init();
        if (typeof Regions !== 'undefined') Regions.init();
        if (typeof Effects !== 'undefined') Effects.init();
    }

    function _refreshAllData() {
        Fetcher.clearCache();
        if (typeof Conflicts !== 'undefined') Conflicts.refresh();
        if (typeof Disasters !== 'undefined') Disasters.refresh();
        if (typeof Weather !== 'undefined') Weather.refresh();
        if (typeof Cyber !== 'undefined') Cyber.refresh();
        if (typeof Outages !== 'undefined') Outages.refresh();
        if (typeof Ticker !== 'undefined') Ticker.refresh();
    }

    /* -- Update layer event counts in sidebar ----------------------------- */
    function updateLayerCount(key, count) {
        var el = document.querySelector('.layer-toggle[data-layer="' + key + '"] .layer-toggle__count');
        if (el) el.textContent = count;
    }

    return {
        init: init,
        isLayerActive: isLayerActive,
        getTimeRange: getTimeRange,
        updateLayerCount: updateLayerCount
    };
})();

/* -- Boot ---------------------------------------------------------------- */
document.addEventListener('DOMContentLoaded', App.init);
