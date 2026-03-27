/* ==========================================================================
   Kytran News — Disease Outbreaks Layer
   WHO Disease Outbreak News + ReliefWeb health emergencies
   ========================================================================== */

var Disease = (function () {
    'use strict';

    var _data = [];
    var _visible = false;

    function init() {
        _visible = App.isLayerActive('disease');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'disease') { _visible = e.visible; if (_visible && _data.length === 0) refresh(); _render(); }
        });
        if (_visible) refresh();
    }

    function refresh() {
        if (!_visible) return;
        /* ReliefWeb Disasters API — filter for epidemics */
        Fetcher.get('https://api.reliefweb.int/v1/disasters?appname=kytran-news&limit=30&filter[field]=type&filter[value]=Epidemic&sort[]=date:desc', {
            sourceKey: 'disease',
            fallbackUrl: 'data/fallback-disease.json',
            useCorsProxy: true,
            cacheTTL: 600000,
            transform: _transform
        }).then(function (data) {
            _data = data || [];
            App.updateLayerCount('disease', _data.length);
            EventBus.emit('data:disease:updated', _data);
            _render();
        });
    }

    function _transform(data) {
        if (!data || !data.data) return [];
        return data.data.map(function (item) {
            var fields = item.fields || {};
            var country = (fields.country && fields.country[0]) || {};
            return {
                id: item.id || Math.random().toString(36).substr(2, 9),
                lon: country.location ? country.location.lon : 0,
                lat: country.location ? country.location.lat : 0,
                type: 'disease',
                title: fields.name || 'Disease outbreak',
                country: country.name || '',
                status: fields.status || '',
                timestamp: fields.date ? new Date(fields.date.created).getTime() : Date.now(),
                url: fields.url || ''
            };
        }).filter(function (d) { return d.lon !== 0 && d.lat !== 0; });
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('disease');
            return;
        }

        var layer = new deck.ScatterplotLayer({
            id: 'disease',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: 25000,
            getFillColor: [0, 255, 136, 160],
            radiusMinPixels: 5,
            radiusMaxPixels: 20,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('disease', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
