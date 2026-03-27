/* ==========================================================================
   Kytran News — Map Module
   deck.gl + MapLibre initialization, layer composition, view state
   ========================================================================== */

var KytranMap = (function () {
    'use strict';

    var _deckgl = null;
    var _viewState = null;
    var _layers = {};
    var _tooltip = null;

    function init() {
        _viewState = Object.assign({}, Config.MAP.initialView);
        _tooltip = document.getElementById('map-tooltip');

        _deckgl = new deck.DeckGL({
            container: 'map',
            mapStyle: Config.MAP.style,
            initialViewState: _viewState,
            controller: {
                minZoom: Config.MAP.minZoom,
                maxZoom: Config.MAP.maxZoom,
                dragRotate: true,
                touchRotate: true
            },
            onViewStateChange: function (params) {
                _viewState = params.viewState;
            },
            onClick: function (info) {
                if (info && info.object && typeof Detail !== 'undefined') {
                    Detail.show(info.object);
                }
            },
            getTooltip: _getTooltip,
            layers: []
        });

        EventBus.on('layers:update', _renderLayers);
        EventBus.on('region:change', flyToRegion);
    }

    /**
     * Register a deck.gl layer definition.
     * @param {string} key  - Layer key (matches Config.LAYERS)
     * @param {Object} layer - deck.gl Layer instance
     */
    function setLayer(key, layer) {
        _layers[key] = layer;
        _renderLayers();
    }

    function removeLayer(key) {
        delete _layers[key];
        _renderLayers();
    }

    function _renderLayers() {
        if (!_deckgl) return;
        var activeLayers = [];
        Object.keys(_layers).forEach(function (key) {
            if (_layers[key]) activeLayers.push(_layers[key]);
        });
        _deckgl.setProps({ layers: activeLayers });
    }

    function flyToRegion(regionKey) {
        var region = Config.REGIONS[regionKey];
        if (!region || !_deckgl) return;
        _deckgl.setProps({
            initialViewState: {
                latitude: region.lat,
                longitude: region.lon,
                zoom: region.zoom,
                pitch: region.pitch || 0,
                bearing: 0,
                transitionDuration: 1500,
                transitionInterpolator: new deck.FlyToInterpolator()
            }
        });
    }

    function flyTo(lat, lon, zoom, pitch) {
        if (!_deckgl) return;
        _deckgl.setProps({
            initialViewState: {
                latitude: lat,
                longitude: lon,
                zoom: zoom || 6,
                pitch: pitch != null ? pitch : 0,
                bearing: 0,
                transitionDuration: 1200,
                transitionInterpolator: new deck.FlyToInterpolator()
            }
        });
    }

    function getViewState() {
        return Object.assign({}, _viewState);
    }

    function _getTooltip(info) {
        if (!info || !info.object) return null;
        var obj = info.object;

        var html = '<div class="map-tooltip__title">' + _escHtml(obj.title || 'Unknown') + '</div>';

        if (obj.type === 'earthquake') {
            html += '<div class="map-tooltip__row"><span>Magnitude</span><span class="map-tooltip__value">' + (obj.magnitude || '?') + '</span></div>';
            html += '<div class="map-tooltip__row"><span>Depth</span><span class="map-tooltip__value">' + (obj.depth ? obj.depth.toFixed(1) + ' km' : '?') + '</span></div>';
        }
        if (obj.type === 'conflict') {
            html += '<div class="map-tooltip__row"><span>Source</span><span class="map-tooltip__value">' + _escHtml(obj.source || '') + '</span></div>';
            html += '<div class="map-tooltip__row"><span>Severity</span><span class="map-tooltip__value">' + (obj.severity || '?') + '</span></div>';
        }
        if (obj.type === 'disaster') {
            html += '<div class="map-tooltip__row"><span>Type</span><span class="map-tooltip__value">' + _escHtml(obj.subtype || '') + '</span></div>';
        }
        if (obj.type === 'weather') {
            html += '<div class="map-tooltip__row"><span>Severity</span><span class="map-tooltip__value">' + _escHtml(obj.severity || '') + '</span></div>';
            html += '<div class="map-tooltip__row"><span>Area</span><span class="map-tooltip__value">' + _escHtml(obj.area || '') + '</span></div>';
        }
        if (obj.type === 'military') {
            html += '<div class="map-tooltip__row"><span>Type</span><span class="map-tooltip__value">' + _escHtml(obj.subtype || '') + '</span></div>';
            html += '<div class="map-tooltip__row"><span>Country</span><span class="map-tooltip__value">' + _escHtml(obj.country || '') + '</span></div>';
        }

        if (obj.timestamp) {
            html += '<div class="map-tooltip__row"><span>Time</span><span class="map-tooltip__value">' + _formatTime(obj.timestamp) + '</span></div>';
        }

        return { html: html, style: { 'font-family': 'IBM Plex Mono, monospace' } };
    }

    function _escHtml(str) {
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function _formatTime(ts) {
        var d = new Date(ts);
        return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    return {
        init: init,
        setLayer: setLayer,
        removeLayer: removeLayer,
        flyToRegion: flyToRegion,
        flyTo: flyTo,
        getViewState: getViewState
    };
})();
