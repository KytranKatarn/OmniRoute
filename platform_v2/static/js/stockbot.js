/* StockBot — LCARS Trading Dashboard JS
 * IIFE module exposed as window.SB
 */
(function () {
  'use strict';

  var API_BASE = '/tools/stockbot';

  // ── State ──────────────────────────────────────────────────────
  var _activeTab = 'dashboard';
  var _chart = null;
  var _candleSeries = null;
  var _volumeSeries = null;
  var _indicatorSeries = {};
  var _currentTicker = null;
  var _watchlist = [];
  var _portfolio = [];
  var _activePeriod = '1M';
  var _activeIndicators = [];
  var _toastTimer = null;

  // ── API helper ─────────────────────────────────────────────────
  function api(method, path, body) {
    var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(API_BASE + path, opts).then(function (r) {
      if (!r.ok) return r.json().catch(function () { return { error: r.statusText }; }).then(function (e) { throw new Error(e.error || r.statusText); });
      return r.json();
    }).catch(function (e) { toast('Error: ' + e.message); throw e; });
  }

  // ── Utility ────────────────────────────────────────────────────
  function clearEl(el) { while (el.firstChild) el.removeChild(el.firstChild); }

  function formatCurrency(n) {
    if (n == null) return '—';
    return '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function formatPct(n) {
    if (n == null) return '—';
    var v = Number(n);
    return (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
  }

  function colorClass(n) {
    if (n == null) return '';
    return Number(n) >= 0 ? 'sb-positive' : 'sb-negative';
  }

  function toast(msg, duration) {
    var el = document.getElementById('sbToast');
    if (!el) return;
    el.textContent = msg;
    el.style.display = 'block';
    el.classList.add('sb-toast-show');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(function () {
      el.classList.remove('sb-toast-show');
      setTimeout(function () { el.style.display = 'none'; }, 300);
    }, duration || 3000);
  }

  function td(text, cls) {
    var cell = document.createElement('td');
    cell.textContent = text;
    if (cls) cell.className = cls;
    return cell;
  }

  function emptyRow(cols, msg) {
    var tr = document.createElement('tr');
    var cell = document.createElement('td');
    cell.colSpan = cols;
    cell.textContent = msg || 'No data';
    cell.className = 'sb-empty';
    tr.appendChild(cell);
    return tr;
  }

  function getEl(id) { return document.getElementById(id); }

  // ── Tabs ───────────────────────────────────────────────────────
  function setTab(tab) {
    _activeTab = tab;
    document.querySelectorAll('.sb-tab').forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    var panels = {
      dashboard: 'sbDashboardTab', watchlist: 'sbWatchlistTab',
      portfolio: 'sbPortfolioTab', charts: 'sbChartsTab', chat: 'sbChatTab'
    };
    Object.keys(panels).forEach(function (k) {
      var el = getEl(panels[k]);
      if (el) el.style.display = k === tab ? '' : 'none';
    });
    if (tab === 'dashboard') loadDashboard();
    if (tab === 'watchlist') loadWatchlist();
    if (tab === 'portfolio') { loadPortfolio(); loadTransactions(); }
    if (tab === 'charts' && _currentTicker) loadChart(_currentTicker);
  }

  // ── Dashboard ─────────────────────────────────────────────────
  function loadDashboard() {
    Promise.all([api('GET', '/api/watchlist'), api('GET', '/api/portfolio')]).then(function (results) {
      renderWatchlistPreview(results[0].watchlist || []);
      renderPortfolioSummary(results[1]);
      loadMarketOverview();
      loadRecentAlerts();
    }).catch(function () {});
  }

  function loadMarketOverview() {
    var etfs = [
      { sym: 'SPY', priceId: 'sbSpyPrice', changeId: 'sbSpyChange', sparkId: 'sbSpySpark' },
      { sym: 'QQQ', priceId: 'sbQqqPrice', changeId: 'sbQqqChange', sparkId: 'sbQqqSpark' },
      { sym: 'DIA', priceId: 'sbDiaPrice', changeId: 'sbDiaChange', sparkId: 'sbDiaSpark' }
    ];
    etfs.forEach(function (etf) {
      api('GET', '/api/quote/' + etf.sym).then(function (data) {
        var priceEl = getEl(etf.priceId), changeEl = getEl(etf.changeId);
        if (priceEl) priceEl.textContent = formatCurrency(data.price);
        if (changeEl) { changeEl.textContent = formatPct(data.change_pct); changeEl.className = 'sb-market-change ' + colorClass(data.change_pct); }
        if (data.sparkline) drawSparkline(etf.sparkId, data.sparkline, data.change_pct >= 0);
      }).catch(function () {});
    });
  }

  function drawSparkline(canvasId, values, positive) {
    var canvas = getEl(canvasId);
    if (!canvas || !values || !values.length) return;
    var ctx = canvas.getContext('2d');
    var w = canvas.width, h = canvas.height;
    var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    var range = max - min || 1;
    ctx.clearRect(0, 0, w, h);
    ctx.beginPath();
    ctx.strokeStyle = positive ? '#44ff66' : '#ff4444';
    ctx.lineWidth = 1.5;
    values.forEach(function (v, i) {
      var x = (i / (values.length - 1)) * w;
      var y = h - ((v - min) / range) * (h - 4) - 2;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  function renderWatchlistPreview(wl) {
    var body = getEl('sbWatchlistPreviewBody');
    if (!body) return;
    clearEl(body);
    var items = wl.slice(0, 5);
    if (!items.length) { body.appendChild(emptyRow(3, 'No watchlist items')); return; }
    items.forEach(function (item) {
      var tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', function () { _currentTicker = item.ticker; setTab('charts'); });
      tr.appendChild(td(item.ticker));
      tr.appendChild(td(formatCurrency(item.price)));
      tr.appendChild(td(formatPct(item.change_pct), colorClass(item.change_pct)));
      body.appendChild(tr);
    });
  }

  function renderPortfolioSummary(port) {
    var holdings = port.holdings || [];
    var totalValue = 0, totalCost = 0;
    holdings.forEach(function (h) {
      totalValue += (h.current_price || 0) * (h.shares || 0);
      totalCost += (h.avg_cost || 0) * (h.shares || 0);
    });
    var pnl = totalValue - totalCost;
    if (getEl('sbDashTotalValue')) getEl('sbDashTotalValue').textContent = formatCurrency(totalValue);
    if (getEl('sbDashTotalPnl')) {
      getEl('sbDashTotalPnl').textContent = formatCurrency(pnl);
      getEl('sbDashTotalPnl').className = 'sb-card-value ' + colorClass(pnl);
    }
    if (getEl('sbDashPositions')) getEl('sbDashPositions').textContent = holdings.length;
  }

  function loadRecentAlerts() {
    api('GET', '/api/alerts').then(function (data) {
      var container = getEl('sbRecentAlerts');
      if (!container) return;
      clearEl(container);
      var alerts = (data.alerts || []).slice(0, 5);
      if (!alerts.length) {
        var d = document.createElement('div'); d.className = 'sb-empty'; d.textContent = 'No recent alerts'; container.appendChild(d); return;
      }
      alerts.forEach(function (a) {
        var row = document.createElement('div'); row.className = 'sb-alert-row';
        var sym = document.createElement('strong'); sym.textContent = a.ticker; row.appendChild(sym);
        var desc = document.createElement('span'); desc.textContent = ' ' + a.condition + ' ' + a.threshold; row.appendChild(desc);
        container.appendChild(row);
      });
    }).catch(function () {});
  }

  // ── Watchlist ─────────────────────────────────────────────────
  function loadWatchlist() {
    api('GET', '/api/watchlist').then(function (data) {
      _watchlist = data.watchlist || [];
      renderWatchlistTable(_watchlist);
    }).catch(function () {});
  }

  function renderWatchlistTable(wl) {
    var body = getEl('sbWatchlistBody');
    if (!body) return;
    clearEl(body);
    if (!wl.length) { body.appendChild(emptyRow(7, 'Watchlist is empty')); return; }
    wl.forEach(function (item) {
      var tr = document.createElement('tr');
      var tickerTd = document.createElement('td');
      var tickerBtn = document.createElement('button');
      tickerBtn.className = 'sb-link-btn'; tickerBtn.textContent = item.ticker;
      tickerBtn.addEventListener('click', function () {
        _currentTicker = item.ticker;
        var ts = getEl('sbTickerSearch'); if (ts) ts.value = item.ticker;
        setTab('charts');
      });
      tickerTd.appendChild(tickerBtn); tr.appendChild(tickerTd);
      tr.appendChild(td(formatCurrency(item.price)));
      tr.appendChild(td(formatPct(item.change_pct), colorClass(item.change_pct)));
      tr.appendChild(td(item.week52_low ? formatCurrency(item.week52_low) : '—'));
      tr.appendChild(td(item.week52_high ? formatCurrency(item.week52_high) : '—'));
      tr.appendChild(td(item.notes || ''));
      var actionTd = document.createElement('td');
      var removeBtn = document.createElement('button');
      removeBtn.className = 'sb-btn sb-btn-small sb-btn-negative'; removeBtn.textContent = 'Remove';
      removeBtn.addEventListener('click', function () { removeFromWatchlist(item.ticker); });
      actionTd.appendChild(removeBtn); tr.appendChild(actionTd);
      body.appendChild(tr);
    });
  }

  function addToWatchlist() {
    var input = getEl('sbWatchlistInput'); if (!input) return;
    var ticker = input.value.trim().toUpperCase();
    if (!ticker) { toast('Enter a ticker symbol'); return; }
    api('POST', '/api/watchlist', { ticker: ticker }).then(function () {
      input.value = ''; toast(ticker + ' added to watchlist'); loadWatchlist();
    }).catch(function () {});
  }

  function removeFromWatchlist(ticker) {
    api('DELETE', '/api/watchlist/' + ticker).then(function () { toast(ticker + ' removed'); loadWatchlist(); }).catch(function () {});
  }

  // ── Portfolio ─────────────────────────────────────────────────
  function loadPortfolio() {
    api('GET', '/api/portfolio').then(function (data) {
      _portfolio = data.holdings || [];
      renderPortfolioTable(_portfolio);
    }).catch(function () {});
  }

  function renderPortfolioTable(holdings) {
    var body = getEl('sbPortfolioBody'); if (!body) return;
    clearEl(body);
    var totalValue = 0, totalCost = 0;
    holdings.forEach(function (h) { totalValue += (h.current_price || 0) * (h.shares || 0); totalCost += (h.avg_cost || 0) * (h.shares || 0); });
    if (!holdings.length) { body.appendChild(emptyRow(7, 'No holdings')); }
    else {
      holdings.forEach(function (h) {
        var tr = document.createElement('tr');
        var posValue = (h.current_price || 0) * (h.shares || 0);
        var posCost = (h.avg_cost || 0) * (h.shares || 0);
        var pnl = posValue - posCost;
        var pnlPct = posCost > 0 ? (pnl / posCost) * 100 : 0;
        var alloc = totalValue > 0 ? (posValue / totalValue) * 100 : 0;
        tr.appendChild(td(h.ticker));
        tr.appendChild(td(Number(h.shares).toFixed(4)));
        tr.appendChild(td(formatCurrency(h.avg_cost)));
        tr.appendChild(td(formatCurrency(h.current_price)));
        tr.appendChild(td(formatCurrency(pnl), colorClass(pnl)));
        tr.appendChild(td(formatPct(pnlPct), colorClass(pnlPct)));
        tr.appendChild(td(alloc.toFixed(1) + '%'));
        body.appendChild(tr);
      });
    }
    var totalPnl = totalValue - totalCost;
    if (getEl('sbPortTotalValue')) getEl('sbPortTotalValue').textContent = formatCurrency(totalValue);
    if (getEl('sbPortTotalCost')) getEl('sbPortTotalCost').textContent = formatCurrency(totalCost);
    if (getEl('sbPortTotalPnl')) { getEl('sbPortTotalPnl').textContent = formatCurrency(totalPnl); getEl('sbPortTotalPnl').className = colorClass(totalPnl); }
  }

  function executeTrade(action) {
    var ticker = getEl('sbTradeTicker').value.trim().toUpperCase();
    var shares = parseFloat(getEl('sbTradeShares').value);
    var priceInput = parseFloat(getEl('sbTradePrice').value);
    if (!ticker) { toast('Enter a ticker'); return; }
    if (!shares || shares <= 0) { toast('Enter valid share count'); return; }
    var pricePromise = (!priceInput || isNaN(priceInput))
      ? api('GET', '/api/quote/' + ticker).then(function (q) { return q.price; })
      : Promise.resolve(priceInput);
    pricePromise.then(function (price) {
      return api('POST', '/api/portfolio/trade', { ticker: ticker, shares: shares, price: price, action: action }).then(function () {
        toast(action.toUpperCase() + ' ' + shares + ' ' + ticker + ' @ ' + formatCurrency(price));
        getEl('sbTradeTicker').value = ''; getEl('sbTradeShares').value = ''; getEl('sbTradePrice').value = '';
        loadPortfolio(); loadTransactions();
      });
    }).catch(function () {});
  }

  function loadTransactions() {
    api('GET', '/api/transactions').then(function (data) {
      var body = getEl('sbTransactionBody'); if (!body) return;
      clearEl(body);
      var txs = data.transactions || [];
      if (!txs.length) { body.appendChild(emptyRow(6, 'No transactions')); return; }
      txs.forEach(function (tx) {
        var tr = document.createElement('tr');
        var date = tx.created_at ? new Date(tx.created_at).toLocaleDateString() : '—';
        tr.appendChild(td(date)); tr.appendChild(td(tx.ticker));
        var actionTd = td(tx.action ? tx.action.toUpperCase() : '—');
        actionTd.className = tx.action === 'buy' ? 'sb-positive' : 'sb-negative';
        tr.appendChild(actionTd);
        tr.appendChild(td(Number(tx.shares).toFixed(4)));
        tr.appendChild(td(formatCurrency(tx.price)));
        tr.appendChild(td(formatCurrency((tx.shares || 0) * (tx.price || 0))));
        body.appendChild(tr);
      });
    }).catch(function () {});
  }

  // ── Charts ────────────────────────────────────────────────────
  function loadChart(ticker) {
    var input = getEl('sbTickerSearch');
    var sym = ticker || (input ? input.value.trim().toUpperCase() : null);
    if (!sym) { toast('Enter a ticker to chart'); return; }
    _currentTicker = sym;
    if (input) input.value = sym;
    var indParam = _activeIndicators.join(',');
    api('GET', '/api/history/' + sym + '?period=' + _activePeriod + (indParam ? '&indicators=' + indParam : '')).then(function (data) {
      renderChart(data); updateQuoteBar(data.quote || {});
    }).catch(function () {});
  }

  function renderChart(data) {
    var container = getEl('sbChartContainer'); if (!container) return;
    if (_chart) { _chart.remove(); _chart = null; _candleSeries = null; _volumeSeries = null; _indicatorSeries = {}; }
    _chart = LightweightCharts.createChart(container, {
      width: container.clientWidth || 800, height: 420,
      layout: { background: { color: '#0d0d1a' }, textColor: '#aabb99' },
      grid: { vertLines: { color: '#1a1a2a' }, horzLines: { color: '#1a1a2a' } },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      timeScale: { borderColor: '#334433' }, rightPriceScale: { borderColor: '#334433' }
    });
    _candleSeries = _chart.addCandlestickSeries({ upColor: '#44ff66', downColor: '#ff4444', borderUpColor: '#44ff66', borderDownColor: '#ff4444', wickUpColor: '#44ff66', wickDownColor: '#ff4444' });
    var ohlcv = data.ohlcv || [];
    if (ohlcv.length) _candleSeries.setData(ohlcv.map(function (b) { return { time: b.time || b.date, open: b.open, high: b.high, low: b.low, close: b.close }; }));
    _volumeSeries = _chart.addHistogramSeries({ color: '#334466', priceFormat: { type: 'volume' }, priceScaleId: 'vol', scaleMargins: { top: 0.8, bottom: 0 } });
    if (ohlcv.length) _volumeSeries.setData(ohlcv.map(function (b) { return { time: b.time || b.date, value: b.volume || 0, color: b.close >= b.open ? '#224433' : '#442222' }; }));
    var ind = data.indicators || {};
    if (ind.SMA20) { var s = _chart.addLineSeries({ color: '#4488ff', lineWidth: 1, title: 'SMA20' }); s.setData(ind.SMA20); _indicatorSeries.SMA20 = s; }
    if (ind.SMA50) { var s = _chart.addLineSeries({ color: '#ff8844', lineWidth: 1, title: 'SMA50' }); s.setData(ind.SMA50); _indicatorSeries.SMA50 = s; }
    if (ind.SMA200) { var s = _chart.addLineSeries({ color: '#ff44aa', lineWidth: 1, title: 'SMA200' }); s.setData(ind.SMA200); _indicatorSeries.SMA200 = s; }
    if (ind.BB_upper) { var su = _chart.addLineSeries({ color: '#888888', lineWidth: 1, lineStyle: 2, title: 'BB+' }); su.setData(ind.BB_upper); _indicatorSeries.BB_upper = su; }
    if (ind.BB_lower) { var sl = _chart.addLineSeries({ color: '#888888', lineWidth: 1, lineStyle: 2, title: 'BB-' }); sl.setData(ind.BB_lower); _indicatorSeries.BB_lower = sl; }
    if (window.ResizeObserver) {
      var ro = new ResizeObserver(function () { if (_chart) _chart.applyOptions({ width: container.clientWidth }); });
      ro.observe(container);
    }
  }

  function updateQuoteBar(q) {
    if (getEl('sbQuoteTicker')) getEl('sbQuoteTicker').textContent = _currentTicker || '—';
    if (getEl('sbQuotePrice')) getEl('sbQuotePrice').textContent = formatCurrency(q.price);
    if (getEl('sbQuoteChange')) { getEl('sbQuoteChange').textContent = formatPct(q.change_pct); getEl('sbQuoteChange').className = 'sb-quote-val ' + colorClass(q.change_pct); }
    if (getEl('sbQuoteVolume')) getEl('sbQuoteVolume').textContent = 'Vol: ' + (q.volume ? Number(q.volume).toLocaleString() : '—');
    if (getEl('sbQuoteMarketCap')) {
      var mc = q.market_cap, mcStr = '—';
      if (mc) { if (mc >= 1e12) mcStr = (mc / 1e12).toFixed(2) + 'T'; else if (mc >= 1e9) mcStr = (mc / 1e9).toFixed(2) + 'B'; else if (mc >= 1e6) mcStr = (mc / 1e6).toFixed(2) + 'M'; else mcStr = formatCurrency(mc); }
      getEl('sbQuoteMarketCap').textContent = 'Mkt Cap: ' + mcStr;
    }
  }

  function setPeriod(period) {
    _activePeriod = period;
    document.querySelectorAll('.sb-period-btn').forEach(function (btn) { btn.classList.toggle('active', btn.textContent === period); });
    if (_currentTicker) loadChart(_currentTicker);
  }

  function toggleIndicator(name) {
    var idx = _activeIndicators.indexOf(name);
    if (idx >= 0) _activeIndicators.splice(idx, 1); else _activeIndicators.push(name);
    if (_currentTicker) loadChart(_currentTicker);
  }

  // ── Alerts ────────────────────────────────────────────────────
  function openAlertModal() {
    var modal = getEl('sbAlertModal'); if (modal) modal.style.display = 'flex';
    var wlInput = getEl('sbWatchlistInput'), alertTicker = getEl('sbAlertTicker');
    if (alertTicker && wlInput && wlInput.value) alertTicker.value = wlInput.value;
  }

  function closeAlertModal(event) {
    if (event && event.target !== getEl('sbAlertModal')) return;
    var modal = getEl('sbAlertModal'); if (modal) modal.style.display = 'none';
  }

  function createAlert() {
    var ticker = getEl('sbAlertTicker').value.trim().toUpperCase();
    var condition = getEl('sbAlertCondition').value;
    var threshold = parseFloat(getEl('sbAlertThreshold').value);
    if (!ticker) { toast('Enter a ticker'); return; }
    if (isNaN(threshold)) { toast('Enter a valid threshold'); return; }
    api('POST', '/api/alerts', { ticker: ticker, condition: condition, threshold: threshold }).then(function () {
      toast('Alert created for ' + ticker); closeAlertModal();
      if (_activeTab === 'dashboard') loadRecentAlerts();
    }).catch(function () {});
  }

  // ── AI Chat ───────────────────────────────────────────────────
  function sendChat() {
    var input = getEl('sbChatInput'); if (!input) return;
    var msg = input.value.trim(); if (!msg) return;
    input.value = '';
    appendChatMsg('user', msg);
    var tickerPattern = /\$([A-Z]{1,5})/g;
    var tickers = [], m;
    tickerPattern.lastIndex = 0;
    while ((m = tickerPattern.exec(msg)) !== null) tickers.push(m[1]);
    var thinkingEl = appendChatMsg('bot', '…');
    var enrichPromise;
    if (tickers.length) {
      enrichPromise = Promise.all(tickers.map(function (sym) {
        return api('GET', '/api/quote/' + sym).then(function (q) { return sym + ': ' + formatCurrency(q.price) + ' (' + formatPct(q.change_pct) + ')'; }).catch(function () { return null; });
      })).then(function (quotes) {
        var valid = quotes.filter(Boolean);
        return msg + (valid.length ? ' [Market data: ' + valid.join(', ') + ']' : '');
      });
    } else {
      enrichPromise = Promise.resolve(msg);
    }
    enrichPromise.then(function (enriched) {
      return api('POST', '/api/chat', { message: enriched, original: msg });
    }).then(function (data) {
      var bubble = thinkingEl.querySelector('.sb-chat-bubble');
      if (bubble) bubble.textContent = data.response || '(no response)';
    }).catch(function () {
      var bubble = thinkingEl.querySelector('.sb-chat-bubble');
      if (bubble) bubble.textContent = 'Error contacting AI.';
    });
  }

  function appendChatMsg(role, text) {
    var messages = getEl('sbChatMessages'); if (!messages) return null;
    var wrapper = document.createElement('div');
    wrapper.className = 'sb-chat-msg sb-chat-' + (role === 'user' ? 'user' : 'bot');
    var label = document.createElement('span'); label.className = 'sb-chat-label'; label.textContent = role === 'user' ? 'YOU' : 'STOCKBOT';
    var bubble = document.createElement('div'); bubble.className = 'sb-chat-bubble'; bubble.textContent = text;
    wrapper.appendChild(label); wrapper.appendChild(bubble);
    messages.appendChild(wrapper); messages.scrollTop = messages.scrollHeight;
    return wrapper;
  }

  // ── Init ──────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () { loadDashboard(); });

  window.SB = {
    setTab: setTab, addToWatchlist: addToWatchlist, removeFromWatchlist: removeFromWatchlist,
    loadChart: loadChart, setPeriod: setPeriod, toggleIndicator: toggleIndicator,
    openAlertModal: openAlertModal, closeAlertModal: closeAlertModal, createAlert: createAlert,
    sendChat: sendChat, executeTrade: executeTrade
  };

})();
