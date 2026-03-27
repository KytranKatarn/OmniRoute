/* M.A.R.K.E.T. — API fetch wrapper */
'use strict';

const API = {
  /** Base fetch with error handling */
  async _fetch(url, options = {}) {
    const defaults = {
      headers: { 'Content-Type': 'application/json' },
    };
    const merged = { ...defaults, ...options };
    if (merged.body && typeof merged.body === 'object') {
      merged.body = JSON.stringify(merged.body);
    }
    try {
      const res = await fetch(url, merged);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        throw new Error(err.error || err.message || res.statusText);
      }
      return await res.json();
    } catch (e) {
      console.error('[API]', url, e.message);
      throw e;
    }
  },

  get(url) { return this._fetch(url); },
  post(url, body) { return this._fetch(url, { method: 'POST', body }); },
  del(url) { return this._fetch(url, { method: 'DELETE' }); },

  /* Health */
  health() { return this.get('/api/health'); },

  /* Watchlist */
  getWatchlist() { return this.get('/api/watchlist'); },
  addWatchlist(ticker) { return this.post('/api/watchlist', { ticker }); },
  removeWatchlist(id) { return this.del('/api/watchlist/' + id); },

  /* Stocks */
  getStock(ticker) { return this.get('/api/stocks/' + encodeURIComponent(ticker)); },
  getFundamentals(ticker) { return this.get('/api/stocks/' + encodeURIComponent(ticker) + '/fundamentals'); },

  /* Portfolio */
  getPortfolio() { return this.get('/api/portfolio'); },
  getPortfolioSummary() { return this.get('/api/portfolio/summary'); },

  /* Alerts */
  getAlerts() { return this.get('/api/alerts'); },
  createAlert(data) { return this.post('/api/alerts', data); },
  deleteAlert(id) { return this.del('/api/alerts/' + id); },

  /* Analysis */
  getAnalysis() { return this.get('/api/analysis'); },
  runAnalysis(ticker) { return this.post('/api/analysis/run', { ticker }); },
  runCycle() { return this.post('/api/analysis/cycle', {}); },
  getCycles() { return this.get('/api/analysis/cycles'); },

  /* Trading */
  buy(ticker, quantity) { return this.post('/api/trading/buy', { ticker, quantity }); },
  sell(ticker, quantity) { return this.post('/api/trading/sell', { ticker, quantity }); },
  getOrders() { return this.get('/api/trading/orders'); },

  /* Charts */
  getChartData(ticker, period) {
    let url = '/api/charts/' + encodeURIComponent(ticker);
    if (period) url += '?period=' + encodeURIComponent(period);
    return this.get(url);
  },
  getIndicators(ticker) { return this.get('/api/charts/' + encodeURIComponent(ticker) + '/indicators'); },

  /* Backtest */
  runBacktest(data) { return this.post('/api/backtest/run', data); },
  getBacktestResults() { return this.get('/api/backtest/results'); },
};
