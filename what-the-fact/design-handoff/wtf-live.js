/* Live-data hooks. A design page renders from sample constants; on the live
 * site the same page reads the real endpoint or server-injected data, with the
 * constants as the fallback when a service is unreachable.
 *
 *   WTFLive.get('/api/cost/summary', SAMPLE).then(render)
 *     — fetches same-origin JSON; resolves to SAMPLE on any failure and marks
 *       the page so the reader can see the figures are not live.
 *   WTFLive.injected('__WTF_SCAN', SAMPLE)
 *     — server writes `window.__WTF_SCAN = {{ scan|tojson }}`; falls back to SAMPLE.
 *   WTFLive.geo(localFile, cdnUrl)
 *     — tries the trimmed local geometry first, the CDN second.
 */
(function () {
  function mark(reason) {
    if (document.getElementById('wtf-live-note')) return;
    var n = document.createElement('div');
    n.id = 'wtf-live-note';
    n.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:900;font-family:var(--wtf-font-mono),monospace;font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--wtf-developing);background:var(--wtf-bg-card);border:1px solid var(--wtf-developing);border-radius:999px;padding:6px 11px;opacity:.92';
    n.textContent = reason || 'Sample figures \u2014 live feed unavailable';
    document.body.appendChild(n);
  }
  window.WTFLive = {
    get: function (url, fallback, opts) {
      opts = opts || {};
      if (!/^\//.test(url) && !/^https?:/.test(url)) return Promise.resolve(fallback);
      return fetch(url, { credentials: 'same-origin', cache: 'no-store' })
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .catch(function () { if (!opts.silent) mark(opts.note); return fallback; });
    },
    injected: function (name, fallback) {
      return (typeof window[name] !== 'undefined' && window[name] !== null) ? window[name] : fallback;
    },
    geo: function (local, cdn) {
      var d3json = window.d3 && window.d3.json;
      var load = function (u) { return d3json ? d3json(u) : fetch(u).then(function (r) { if (!r.ok) throw 0; return r.json(); }); };
      return load(local).catch(function () { return load(cdn); });
    },
    mark: mark
  };
})();
