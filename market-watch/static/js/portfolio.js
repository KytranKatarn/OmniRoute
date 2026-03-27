/* M.A.R.K.E.T. — Portfolio tab: positions table + P&L */
'use strict';

var Portfolio = {
  loaded: false,

  async load() {
    if (this.loaded) return;
    this.loaded = true;
    await Promise.all([this._loadSummary(), this._loadPositions()]);
  },

  async _loadSummary() {
    try {
      var data = await API.getPortfolioSummary();

      var cashEl = document.getElementById('portfolio-cash');
      if (cashEl) cashEl.textContent = App.formatCurrency(data.cash);

      var eqEl = document.getElementById('portfolio-equity');
      if (eqEl) eqEl.textContent = App.formatCurrency(data.total_equity);

      var pnlEl = document.getElementById('portfolio-total-pnl');
      if (pnlEl) {
        pnlEl.textContent = App.formatCurrency(data.total_pnl);
        pnlEl.className = 'hero-stat__value ' + App.pnlClass(data.total_pnl);
      }

      var pctEl = document.getElementById('portfolio-total-pnl-pct');
      if (pctEl) {
        pctEl.textContent = App.formatPct(data.total_pnl_pct);
        pctEl.className = 'hero-stat__value ' + App.pnlClass(data.total_pnl_pct);
      }
    } catch (_) { /* keep dashes */ }
  },

  async _loadPositions() {
    App.setLoading('portfolio-tbody');

    try {
      var data = await API.getPortfolio();
      var positions = data.positions || data;

      if (!Array.isArray(positions) || positions.length === 0) {
        App.setEmpty('portfolio-tbody', 'No open positions');
        return;
      }

      var tbody = document.getElementById('portfolio-tbody');
      App.clearEl(tbody);

      positions.forEach(function(pos) {
        var tr = document.createElement('tr');

        /* Ticker */
        var tdTicker = document.createElement('td');
        tdTicker.style.fontWeight = '600';
        tdTicker.style.color = 'var(--accent)';
        tdTicker.textContent = pos.ticker;
        tr.appendChild(tdTicker);

        /* Qty */
        var tdQty = document.createElement('td');
        tdQty.textContent = pos.quantity;
        tr.appendChild(tdQty);

        /* Avg Cost */
        var tdCost = document.createElement('td');
        tdCost.textContent = App.formatCurrency(pos.avg_cost);
        tr.appendChild(tdCost);

        /* Current Price */
        var tdPrice = document.createElement('td');
        tdPrice.textContent = App.formatCurrency(pos.current_price);
        tr.appendChild(tdPrice);

        /* Market Value */
        var tdValue = document.createElement('td');
        var mktVal = (pos.quantity || 0) * (pos.current_price || 0);
        tdValue.textContent = App.formatCurrency(pos.market_value != null ? pos.market_value : mktVal);
        tr.appendChild(tdValue);

        /* P&L */
        var pnl = pos.unrealized_pnl;
        var tdPnl = document.createElement('td');
        tdPnl.className = App.pnlClass(pnl);
        tdPnl.textContent = App.formatCurrency(pnl);
        tr.appendChild(tdPnl);

        /* P&L % */
        var pnlPct = pos.unrealized_pnl_pct;
        var tdPnlPct = document.createElement('td');
        tdPnlPct.className = App.pnlClass(pnlPct);
        tdPnlPct.textContent = App.formatPct(pnlPct);
        tr.appendChild(tdPnlPct);

        tbody.appendChild(tr);
      });
    } catch (e) {
      App.setEmpty('portfolio-tbody', 'Failed to load portfolio');
    }
  },
};
