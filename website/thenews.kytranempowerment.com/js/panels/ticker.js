/* ==========================================================================
   Kytran News — News Ticker
   Scrolling headlines from RSS feeds (BBC World, Al Jazeera, CBC)
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

    function _transformRss(data) {
        var items = (data && data.items) ? data.items : [];
        return items.map(function (item) {
            var title = item.title || '';
            var category = 'world';
            var lc = title.toLowerCase();
            if (lc.indexOf('war') !== -1 || lc.indexOf('attack') !== -1 || lc.indexOf('conflict') !== -1) category = 'conflict';
            else if (lc.indexOf('earthquake') !== -1 || lc.indexOf('flood') !== -1 || lc.indexOf('storm') !== -1) category = 'disaster';
            else if (lc.indexOf('protest') !== -1 || lc.indexOf('rally') !== -1) category = 'protest';
            else if (lc.indexOf('cyber') !== -1 || lc.indexOf('hack') !== -1) category = 'cyber';
            else if (lc.indexOf('market') !== -1 || lc.indexOf('economy') !== -1) category = 'economy';
            return { title: title, url: item.link || '#', category: category, pubDate: item.pubDate || '' };
        });
    }

    function refresh() {
        var feeds = [Config.API.news_bbc, Config.API.news_aj, Config.API.news_canada].filter(Boolean);
        var promises = feeds.map(function (url) {
            return Fetcher.get(url, {
                sourceKey: 'news_' + url.slice(-20),
                cacheTTL: Config.INTERVALS.news,
                transform: _transformRss
            }).catch(function () { return []; });
        });

        Promise.all(promises).then(function (results) {
            var all = [];
            results.forEach(function (r) { if (r) all = all.concat(r); });
            /* Deduplicate by title */
            var seen = {};
            _articles = all.filter(function (a) {
                if (!a.title || seen[a.title]) return false;
                seen[a.title] = true;
                return true;
            });
            /* Sort newest first */
            _articles.sort(function (a, b) { return (b.pubDate || '').localeCompare(a.pubDate || ''); });
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
