/* M.A.R.K.E.T. — Backtest tab: form + results + equity curve */
'use strict';

var Backtest = {
  chart: null,
  initialized: false,

  init() {
    if (this.initialized) return;
    this.initialized = true;
    this._bindEvents();
  },

  _bindEvents() {
    var runBtn = document.getElementById('backtest-run-btn');
    if (runBtn) {
      runBtn.addEventListener('click', function() { Backtest._run(); });
    }
  },

  async _run() {
    var tickerEl = document.getElementById('backtest-ticker');
    var strategyEl = document.getElementById('backtest-strategy');
    var periodEl = document.getElementById('backtest-period');

    var ticker = tickerEl ? tickerEl.value.trim().toUpperCase() : '';
    var strategy = strategyEl ? strategyEl.value : '';
    var period = periodEl ? periodEl.value : '1Y';

    if (!ticker) { App.toast('Enter a ticker', 'error'); return; }

    var btn = document.getElementById('backtest-run-btn');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Running...';
    }

    try {
      var data = await API.runBacktest({ ticker: ticker, strategy: strategy, period: period });
      this._showResults(data);
      document.getElementById('backtest-empty').classList.add('hidden');
      document.getElementById('backtest-results-section').classList.remove('hidden');
    } catch (e) {
      App.toast('Backtest failed: ' + e.message, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Run Backtest';
      }
    }
  },

  _showResults(data) {
    var results = data.results || data;

    /* Metrics */
    var metricsContainer = document.getElementById('backtest-metrics');
    App.clearEl(metricsContainer);

    var metrics = [
      { label: 'Total Return', value: App.formatPct(results.total_return), cls: App.pnlClass(results.total_return) },
      { label: 'Sharpe Ratio', value: results.sharpe_ratio != null ? results.sharpe_ratio.toFixed(2) : '--', cls: '' },
      { label: 'Max Drawdown', value: App.formatPct(results.max_drawdown), cls: 'negative' },
      { label: 'Win Rate', value: App.formatPct(results.win_rate), cls: '' },
    ];

    metrics.forEach(function(m) {
      var div = document.createElement('div');
      div.className = 'backtest-metric';

      var valEl = document.createElement('div');
      valEl.className = 'backtest-metric__value';
      if (m.cls) valEl.classList.add(m.cls);
      valEl.textContent = m.value;
      div.appendChild(valEl);

      var lblEl = document.createElement('div');
      lblEl.className = 'backtest-metric__label';
      lblEl.textContent = m.label;
      div.appendChild(lblEl);

      metricsContainer.appendChild(div);
    });

    /* Equity curve */
    if (results.equity_curve && typeof LightweightCharts !== 'undefined') {
      this._renderEquityCurve(results.equity_curve);
    }

    /* Trade log */
    this._renderTrades(results.trades || []);
  },

  _renderEquityCurve(curve) {
    var container = document.getElementById('backtest-chart-container');
    if (!container) return;
    App.clearEl(container);

    if (!Array.isArray(curve) || curve.length === 0) return;

    var chartWidth = container.clientWidth - 32;
    var chartHeight = Math.max(container.clientHeight - 32, 250);

    this.chart = LightweightCharts.createChart(container, {
      width: chartWidth,
      height: chartHeight,
      layout: {
        background: { color: '#1a1f2e' },
        textColor: '#8892a4',
        fontFamily: "'IBM Plex Mono', monospace",
      },
      grid: {
        vertLines: { color: '#2a3040' },
        horzLines: { color: '#2a3040' },
      },
      rightPriceScale: { borderColor: '#2a3040' },
      timeScale: { borderColor: '#2a3040' },
    });

    var lineSeries = this.chart.addLineSeries({
      color: '#10b981',
      lineWidth: 2,
    });

    var lineData = curve.map(function(pt) {
      return {
        time: pt.time || pt.date,
        value: Number(pt.value || pt.equity),
      };
    }).sort(function(a, b) {
      return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
    });

    lineSeries.setData(lineData);
    this.chart.timeScale().fitContent();

    var self = this;
    var resizeObserver = new ResizeObserver(function() {
      if (self.chart) {
        self.chart.applyOptions({ width: container.clientWidth - 32 });
      }
    });
    resizeObserver.observe(container);
  },

  _renderTrades(trades) {
    var tbody = document.getElementById('backtest-trades-tbody');
    if (!tbody) return;
    App.clearEl(tbody);

    if (!Array.isArray(trades) || trades.length === 0) {
      App.setEmpty('backtest-trades-tbody', 'No trades in backtest', 5);
      return;
    }

    trades.forEach(function(trade) {
      var tr = document.createElement('tr');

      /* Date */
      var tdDate = document.createElement('td');
      tdDate.textContent = App.formatDate(trade.date || trade.time);
      tr.appendChild(tdDate);

      /* Action */
      var tdAction = document.createElement('td');
      var action = (trade.action || trade.side || '').toUpperCase();
      var actionSpan = document.createElement('span');
      actionSpan.style.fontWeight = '600';
      actionSpan.style.color = action === 'BUY' ? 'var(--positive)' : 'var(--negative)';
      actionSpan.textContent = action;
      tdAction.appendChild(actionSpan);
      tr.appendChild(tdAction);

      /* Price */
      var tdPrice = document.createElement('td');
      tdPrice.textContent = App.formatCurrency(trade.price);
      tr.appendChild(tdPrice);

      /* Shares */
      var tdShares = document.createElement('td');
      tdShares.textContent = trade.shares || trade.quantity || '--';
      tr.appendChild(tdShares);

      /* P&L */
      var tdPnl = document.createElement('td');
      tdPnl.className = App.pnlClass(trade.pnl);
      tdPnl.textContent = trade.pnl != null ? App.formatCurrency(trade.pnl) : '--';
      tr.appendChild(tdPnl);

      tbody.appendChild(tr);
    });
  },
};
