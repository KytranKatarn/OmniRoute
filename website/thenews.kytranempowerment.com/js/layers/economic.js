/* ==========================================================================
   Kytran News — Economic Indicators Layer
   ExchangeRate-API + CoinGecko live market data
   ========================================================================== */

var Economic = (function () {
    'use strict';

    var _data = [];
    var _visible = true;

    /* Financial centers with their currencies */
    var FINANCIAL_CENTERS = [
        { name: 'New York (USD)',    lat: 40.71, lon: -74.01, currency: 'USD', exchange: 'NYSE' },
        { name: 'London (GBP)',      lat: 51.51, lon: -0.08,  currency: 'GBP', exchange: 'LSE' },
        { name: 'Tokyo (JPY)',       lat: 35.68, lon: 139.69, currency: 'JPY', exchange: 'TSE' },
        { name: 'Frankfurt (EUR)',   lat: 50.11, lon: 8.68,   currency: 'EUR', exchange: 'FRA' },
        { name: 'Hong Kong (HKD)',   lat: 22.28, lon: 114.16, currency: 'HKD', exchange: 'HKSE' },
        { name: 'Shanghai (CNY)',    lat: 31.23, lon: 121.47, currency: 'CNY', exchange: 'SSE' },
        { name: 'Toronto (CAD)',     lat: 43.65, lon: -79.38, currency: 'CAD', exchange: 'TSX' },
        { name: 'Sydney (AUD)',      lat: -33.87, lon: 151.21, currency: 'AUD', exchange: 'ASX' },
        { name: 'Mumbai (INR)',      lat: 19.08, lon: 72.88,  currency: 'INR', exchange: 'BSE' },
        { name: 'Zurich (CHF)',      lat: 47.37, lon: 8.54,   currency: 'CHF', exchange: 'SIX' },
        { name: 'Singapore (SGD)',   lat: 1.35,  lon: 103.82, currency: 'SGD', exchange: 'SGX' },
        { name: 'Sao Paulo (BRL)',   lat: -23.55, lon: -46.63, currency: 'BRL', exchange: 'B3' }
    ];

    /* Crypto placement (virtual centers) */
    var CRYPTO_LOCATIONS = {
        bitcoin:  { name: 'Bitcoin',  lat: 37.78, lon: -122.42 }, /* San Francisco */
        ethereum: { name: 'Ethereum', lat: 47.37, lon: 8.54 },    /* Zurich */
        solana:   { name: 'Solana',   lat: 37.39, lon: -122.08 }  /* Silicon Valley */
    };

    function init() {
        _visible = App.isLayerActive('economic');
        EventBus.on('layer:toggle', function (e) {
            if (e.key === 'economic') { _visible = e.visible; if (_visible && _data.length === 0) refresh(); _render(); }
        });
        EventBus.on('timerange:change', refresh);
        if (_visible) refresh();
        Scheduler.start('economic', refresh, Config.INTERVALS.economic || 600000);
    }

    function refresh() {
        Promise.all([
            Fetcher.get(Config.API.exchange_rates, {
                sourceKey: 'economic_fx',
                fallbackUrl: 'data/economic-data.json',
                cacheTTL: Config.INTERVALS.economic || 600000
            }),
            Fetcher.get(Config.API.crypto, {
                sourceKey: 'economic_crypto',
                cacheTTL: Config.INTERVALS.economic || 600000
            })
        ]).then(function (results) {
            var fxData = results[0];
            var cryptoData = results[1];
            _data = _buildMarketPoints(fxData, cryptoData);
            App.updateLayerCount('economic', _data.length);
            EventBus.emit('data:economic:updated', _data);
            _render();
        });
    }

    function _buildMarketPoints(fxData, cryptoData) {
        var points = [];
        var rates = (fxData && fxData.rates) || {};

        /* Financial centers with FX rates */
        FINANCIAL_CENTERS.forEach(function (center) {
            var rate = rates[center.currency];
            var status = 'stable';
            /* Simple heuristic: strong currencies (rate < 1.5 vs USD) = up, weak = down */
            if (rate && rate < 1.5) status = 'up';
            else if (rate && rate > 100) status = 'volatile';
            else if (rate) status = 'stable';
            points.push({
                id: center.exchange,
                lon: center.lon,
                lat: center.lat,
                type: 'economic',
                subtype: 'forex',
                title: center.name + (rate ? ' — 1 USD = ' + rate.toFixed(2) + ' ' + center.currency : ''),
                exchange: center.exchange,
                status: status,
                rate: rate || 0,
                timestamp: Date.now()
            });
        });

        /* Crypto points */
        if (cryptoData) {
            Object.keys(CRYPTO_LOCATIONS).forEach(function (coin) {
                var cd = cryptoData[coin];
                var loc = CRYPTO_LOCATIONS[coin];
                if (!cd) return;
                var change = cd.usd_24h_change || 0;
                var status = change > 2 ? 'up' : (change < -2 ? 'down' : 'stable');
                points.push({
                    id: 'crypto_' + coin,
                    lon: loc.lon + 2, /* offset to not overlap with forex */
                    lat: loc.lat + 1,
                    type: 'economic',
                    subtype: 'crypto',
                    title: loc.name + ' — $' + (cd.usd || 0).toLocaleString() + ' (' + change.toFixed(1) + '%)',
                    exchange: coin.toUpperCase(),
                    status: status,
                    rate: cd.usd || 0,
                    timestamp: Date.now()
                });
            });
        }

        return points;
    }

    function _render() {
        if (!_visible || _data.length === 0) {
            KytranMap.removeLayer('economic');
            return;
        }
        var layer = new deck.ScatterplotLayer({
            id: 'economic',
            data: _data,
            getPosition: function (d) { return [d.lon, d.lat]; },
            getRadius: function () { return 20000; },
            getFillColor: function (d) {
                if (d.status === 'up') return [76, 175, 80, 180];
                if (d.status === 'down') return [244, 67, 54, 180];
                if (d.status === 'volatile') return [255, 193, 7, 180];
                return [158, 158, 158, 120];
            },
            radiusMinPixels: 4,
            radiusMaxPixels: 25,
            pickable: true,
            autoHighlight: true,
            highlightColor: [255, 255, 255, 60],
            parameters: { depthTest: false }
        });
        KytranMap.setLayer('economic', layer);
    }

    function getData() { return _data; }

    return { init: init, refresh: refresh, getData: getData };
})();
