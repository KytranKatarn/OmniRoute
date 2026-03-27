/* ==========================================================================
   Kytran News — News Ticker
   Scrolling headlines from GDELT DOC API
   ========================================================================== */

var Ticker = (function () {
    'use strict';

    var _articles = [];
    var _scrollEl = null;
    var _countEl = null;

    function init() {
        _scrollEl = document.getElementById('ticker-scroll');
        _countEl = document.getElementById('ticker-count');
        refresh();
        Scheduler.start('news', refresh, Config.INTERVALS.news);
    }

    function refresh() {
        var url = Config.getApiUrl('news', App.getTimeRange());
        Fetcher.get(url, {
            sourceKey: 'news',
            fallbackUrl: Config.FALLBACKS.news,
            useCorsProxy: true,
            cacheTTL: Config.INTERVALS.news,
            transform: Transforms.gdeltNews
        }).then(function (data) {
            _articles = data || [];
            if (_countEl) _countEl.textContent = _articles.length;
            _render();
        });
    }

    function _render() {
        if (!_scrollEl || _articles.length === 0) return;

        /* Clear existing content safely */
        while (_scrollEl.firstChild) _scrollEl.removeChild(_scrollEl.firstChild);

        /* Build items twice for seamless loop */
        for (var pass = 0; pass < 2; pass++) {
            _articles.forEach(function (a) {
                var link = document.createElement('a');
                link.className = 'ticker__item';
                link.href = a.url || '#';
                link.target = '_blank';
                link.rel = 'noopener';

                var cat = document.createElement('span');
                cat.className = 'ticker__category ticker__category--' + (a.category || 'general');
                cat.textContent = a.category || 'news';
                link.appendChild(cat);

                var text = document.createElement('span');
                text.textContent = _truncate(a.title, 90);
                link.appendChild(text);

                _scrollEl.appendChild(link);

                var sep = document.createElement('span');
                sep.className = 'ticker__separator';
                sep.textContent = '\u2022';
                _scrollEl.appendChild(sep);
            });
        }

        /* Reset animation — duration based on content length */
        _scrollEl.style.animation = 'none';
        void _scrollEl.offsetHeight; /* trigger reflow */
        var totalChars = _articles.reduce(function (n, a) { return n + (a.title || '').length; }, 0);
        var duration = Math.max(totalChars * 0.08, 30);
        _scrollEl.style.animation = 'ticker-scroll ' + duration + 's linear infinite';
    }

    function _truncate(str, max) {
        if (!str) return '';
        return str.length > max ? str.substr(0, max) + '...' : str;
    }

    function getData() { return _articles; }

    return { init: init, refresh: refresh, getData: getData };
})();
