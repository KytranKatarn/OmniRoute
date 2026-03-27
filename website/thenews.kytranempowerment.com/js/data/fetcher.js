/* ==========================================================================
   Kytran News — Data Fetcher
   Fetch wrapper with caching, retry, CORS proxy fallback, local fallback
   ========================================================================== */

var Fetcher = (function () {
    'use strict';

    var _cache = {};
    var _status = {};  /* per-source: 'fresh' | 'stale' | 'error' */
    var _gdeltQueue = [];
    var _gdeltProcessing = false;
    var _lastGdeltRequest = 0;
    var GDELT_DELAY = 5500; /* 5.5s between GDELT requests (API requires 5s) */

    /**
     * Fetch data with resilience layers.
     * @param {string} url          - Primary API URL
     * @param {Object} options
     * @param {string} options.fallbackUrl  - Local JSON fallback path
     * @param {number} options.cacheTTL     - Cache duration in ms (default 60000)
     * @param {boolean} options.useCorsProxy - Wrap URL in CORS proxy on failure
     * @param {Function} options.transform  - Transform response data
     * @param {string} options.sourceKey    - Key for status tracking
     * @param {number} options.timeout      - Request timeout in ms (default 10000)
     * @returns {Promise<any>}
     */
    function _isGdeltUrl(url) {
        return url.indexOf('gdeltproject.org') !== -1;
    }

    function _processGdeltQueue() {
        if (_gdeltProcessing || _gdeltQueue.length === 0) return;
        _gdeltProcessing = true;

        var item = _gdeltQueue.shift();
        var now = Date.now();
        var wait = Math.max(0, GDELT_DELAY - (now - _lastGdeltRequest));

        setTimeout(function () {
            _lastGdeltRequest = Date.now();
            _doFetch(item.url, item.options).then(item.resolve).catch(item.reject);
            _gdeltProcessing = false;
            _processGdeltQueue(); /* process next in queue */
        }, wait);
    }

    function get(url, options) {
        options = options || {};
        var cacheTTL = options.cacheTTL || 60000;
        var sourceKey = options.sourceKey || url;

        /* 1. Check cache */
        var cached = _cache[sourceKey];
        if (cached && (Date.now() - cached.timestamp < cacheTTL)) {
            _status[sourceKey] = 'fresh';
            return Promise.resolve(cached.data);
        }

        /* 2. Queue GDELT requests to respect rate limits */
        if (_isGdeltUrl(url)) {
            return new Promise(function (resolve, reject) {
                _gdeltQueue.push({ url: url, options: options, resolve: resolve, reject: reject });
                _processGdeltQueue();
            });
        }

        return _doFetch(url, options);
    }

    function _doFetch(url, options) {
        options = options || {};
        var sourceKey = options.sourceKey || url;
        var timeout = options.timeout || 10000;

        /* Fetch with timeout */
        return _fetchWithTimeout(url, timeout)
            .then(function (response) {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then(function (data) {
                if (options.transform) data = options.transform(data);
                _cache[sourceKey] = { data: data, timestamp: Date.now() };
                _status[sourceKey] = 'fresh';
                return data;
            })
            .catch(function () {
                /* 3. Retry via CORS proxy (primary) */
                if (!options.useCorsProxy) return _loadFallback(options, sourceKey);
                var proxyUrl = Config.CORS_PROXY + encodeURIComponent(url);
                return _fetchWithTimeout(proxyUrl, timeout)
                    .then(function (r) {
                        if (!r.ok) throw new Error('Proxy HTTP ' + r.status);
                        return r.json();
                    })
                    .then(function (data) {
                        if (options.transform) data = options.transform(data);
                        _cache[sourceKey] = { data: data, timestamp: Date.now() };
                        _status[sourceKey] = 'fresh';
                        return data;
                    })
                    .catch(function () {
                        /* 4. Skip to fallback — alt proxies disabled */
                        return _loadFallback(options, sourceKey);
                    });
            });
    }

    function _fetchWithTimeout(url, timeout) {
        return new Promise(function (resolve, reject) {
            var controller = new AbortController();
            var timer = setTimeout(function () {
                controller.abort();
                reject(new Error('Timeout'));
            }, timeout);

            fetch(url, { signal: controller.signal })
                .then(function (response) {
                    clearTimeout(timer);
                    resolve(response);
                })
                .catch(function (err) {
                    clearTimeout(timer);
                    reject(err);
                });
        });
    }

    function _loadFallback(options, sourceKey) {
        if (!options.fallbackUrl) {
            _status[sourceKey] = 'error';
            return Promise.resolve(null);
        }
        return fetch(options.fallbackUrl)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (options.transform) data = options.transform(data);
                _cache[sourceKey] = { data: data, timestamp: Date.now() };
                _status[sourceKey] = 'stale';
                return data;
            })
            .catch(function () {
                _status[sourceKey] = 'error';
                return null;
            });
    }

    function getStatus(sourceKey) {
        return _status[sourceKey] || 'unknown';
    }

    function getAllStatuses() {
        return Object.assign({}, _status);
    }

    function clearCache(sourceKey) {
        if (sourceKey) {
            delete _cache[sourceKey];
            delete _status[sourceKey];
        } else {
            _cache = {};
            _status = {};
        }
    }

    return {
        get: get,
        getStatus: getStatus,
        getAllStatuses: getAllStatuses,
        clearCache: clearCache
    };
})();
