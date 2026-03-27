/* M.A.R.K.E.T. — Dashboard tab: portfolio value, P&L, cycle status, alerts */
'use strict';

var Dashboard = {
  loaded: false,

  async load() {
    if (this.loaded) return;
    this.loaded = true;

    await Promise.all([
      this._loadSummary(),
      this._loadCycleStatus(),
      this._loadAlerts(),
      this._loadPositions(),
      this._loadWatchlistPreview(),
    ]);

    /* Auto-refresh every 60s when on dashboard */
    setInterval(() => {
      if (App.currentTab === 'dashboard') this._loadSummary();
    }, 60000);
  },

  async _loadSummary() {
    try {
      var data = await API.getPortfolioSummary();

      var valEl = document.getElementById('stat-portfolio-value');
      if (valEl) valEl.textContent = App.formatCurrency(data.total_equity);

      var pnlEl = document.getElementById('stat-daily-pnl');
      if (pnlEl) {
        pnlEl.textContent = App.formatCurrency(data.daily_pnl);
        pnlEl.className = 'hero-stat__value ' + App.pnlClass(data.daily_pnl);
      }

      var posEl = document.getElementById('stat-positions');
      if (posEl) posEl.textContent = data.positions_count != null ? data.positions_count : '0';

      var mktEl = document.getElementById('stat-market-status');
      if (mktEl) {
        var status = data.market_status || 'Unknown';
        mktEl.textContent = status;
      }
    } catch (e) {
      var valEl2 = document.getElementById('stat-portfolio-value');
      if (valEl2) valEl2.textContent = '--';
    }
  },

  async _loadCycleStatus() {
    var container = document.getElementById('widget-cycle-status');
    if (!container) return;

    try {
      var data = await API.getCycles();
      App.clearEl(container);

      var cycles = data.cycles || data;
      if (!Array.isArray(cycles) || cycles.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = 'No analysis cycles yet';
        container.appendChild(empty);
        return;
      }

      var latest = cycles[0];
      var item = document.createElement('div');
      item.className = 'widget-item';

      var title = document.createElement('span');
      title.className = 'widget-item__title';
      title.textContent = 'Cycle #' + (latest.id || '?');
      item.appendChild(title);

      var meta = document.createElement('span');
      meta.className = 'widget-item__meta';
      meta.textContent = latest.status || 'unknown';
      item.appendChild(meta);

      container.appendChild(item);

      if (latest.started_at) {
        var timeItem = document.createElement('div');
        timeItem.className = 'widget-item';
        var tl = document.createElement('span');
        tl.className = 'widget-item__title';
        tl.textContent = 'Started';
        timeItem.appendChild(tl);
        var tm = document.createElement('span');
        tm.className = 'widget-item__meta';
        tm.textContent = App.formatDateTime(latest.started_at);
        timeItem.appendChild(tm);
        container.appendChild(timeItem);
      }
    } catch (e) {
      App.clearEl(container);
      var errEl = document.createElement('div');
      errEl.className = 'empty-state';
      errEl.textContent = 'Unable to load cycle status';
      container.appendChild(errEl);
    }
  },

  async _loadAlerts() {
    var container = document.getElementById('widget-alerts-list');
    if (!container) return;

    try {
      var data = await API.getAlerts();
      App.clearEl(container);

      var alerts = data.alerts || data;
      if (!Array.isArray(alerts) || alerts.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = 'No alerts configured';
        container.appendChild(empty);
        return;
      }

      /* Show up to 5 most recent */
      alerts.slice(0, 5).forEach(function(alert) {
        var item = document.createElement('div');
        item.className = 'widget-item';

        var title = document.createElement('span');
        title.className = 'widget-item__title';
        title.textContent = (alert.ticker || '') + ' - ' + (alert.alert_type || alert.type || '');
        item.appendChild(title);

        var badge = App.createBadge(
          alert.status || 'active',
          alert.status === 'triggered' ? 'triggered' : 'active'
        );
        item.appendChild(badge);

        container.appendChild(item);
      });
    } catch (e) {
      App.clearEl(container);
      var errEl = document.createElement('div');
      errEl.className = 'empty-state';
      errEl.textContent = 'Unable to load alerts';
      container.appendChild(errEl);
    }
  },

  async _loadPositions() {
    var container = document.getElementById('widget-positions-list');
    if (!container) return;

    try {
      var data = await API.getPortfolio();
      App.clearEl(container);

      var positions = data.positions || data;
      if (!Array.isArray(positions) || positions.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = 'No open positions';
        container.appendChild(empty);
        return;
      }

      positions.slice(0, 5).forEach(function(pos) {
        var item = document.createElement('div');
        item.className = 'widget-item';

        var title = document.createElement('span');
        title.className = 'widget-item__title';
        title.textContent = pos.ticker + ' x' + pos.quantity;
        item.appendChild(title);

        var meta = document.createElement('span');
        meta.className = 'widget-item__meta ' + App.pnlClass(pos.unrealized_pnl);
        meta.textContent = App.formatCurrency(pos.unrealized_pnl);
        item.appendChild(meta);

        container.appendChild(item);
      });
    } catch (e) {
      App.clearEl(container);
      var errEl = document.createElement('div');
      errEl.className = 'empty-state';
      errEl.textContent = 'Unable to load positions';
      container.appendChild(errEl);
    }
  },

  async _loadWatchlistPreview() {
    var container = document.getElementById('widget-watchlist-preview');
    if (!container) return;

    try {
      var data = await API.getWatchlist();
      App.clearEl(container);

      var items = data.watchlist || data;
      if (!Array.isArray(items) || items.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = 'Watchlist empty';
        container.appendChild(empty);
        return;
      }

      items.slice(0, 5).forEach(function(stock) {
        var item = document.createElement('div');
        item.className = 'widget-item';

        var title = document.createElement('span');
        title.className = 'widget-item__title';
        title.textContent = stock.ticker;
        item.appendChild(title);

        var meta = document.createElement('span');
        meta.className = 'widget-item__meta ' + App.pnlClass(stock.change_pct);
        meta.textContent = stock.price != null ? App.formatCurrency(stock.price) : '--';
        item.appendChild(meta);

        container.appendChild(item);
      });
    } catch (e) {
      App.clearEl(container);
      var errEl = document.createElement('div');
      errEl.className = 'empty-state';
      errEl.textContent = 'Unable to load watchlist';
      container.appendChild(errEl);
    }
  },
};
