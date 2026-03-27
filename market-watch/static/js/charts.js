/* M.A.R.K.E.T. — Charts tab: candlestick chart using lightweight-charts CDN */
'use strict';

var Charts = {
  chart: null,
  candleSeries: null,
  currentPeriod: '3M',
  initialized: false,

  init() {
    if (this.initialized) return;
    this.initialized = true;
    this._bindEvents();
  },

  _bindEvents() {
    var loadBtn = document.getElementById('chart-load-btn');
    if (loadBtn) {
      loadBtn.addEventListener('click', function() { Charts._loadChart(); });
    }

    var input = document.getElementById('chart-ticker');
    if (input) {
      input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') Charts._loadChart();
      });
    }

    /* Period buttons */
    document.querySelectorAll('#chart-periods .period-btn').forEach(function(btn) {
      btn.addEventListener('click', function() {
        document.querySelectorAll('#chart-periods .period-btn').forEach(function(b) {
          b.classList.remove('active');
        });
        btn.classList.add('active');
        Charts.currentPeriod = btn.getAttribute('data-period');
        Charts._loadChart();
      });
    });
  },

  async _loadChart() {
    var input = document.getElementById('chart-ticker');
    var ticker = input ? input.value.trim().toUpperCase() : '';
    if (!ticker) {
      App.toast('Enter a ticker symbol', 'error');
      return;
    }

    var container = document.getElementById('chart-container');
    if (!container) return;

    /* Clear container */
    App.clearEl(container);

    /* Show loading */
    var loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading';
    loadingDiv.textContent = 'Loading chart data\u2026';
    container.appendChild(loadingDiv);

    try {
      var data = await API.getChartData(ticker, this.currentPeriod);
      var candles = data.candles || data.data || data;

      App.clearEl(container);

      if (!Array.isArray(candles) || candles.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = 'No chart data available for ' + ticker;
        container.appendChild(empty);
        return;
      }

      this._renderChart(container, candles, ticker);
    } catch (e) {
      App.clearEl(container);
      var errEl = document.createElement('div');
      errEl.className = 'empty-state';
      errEl.textContent = 'Failed to load chart: ' + e.message;
      container.appendChild(errEl);
    }
  },

  _renderChart(container, candles, ticker) {
    /* Ensure lightweight-charts is available */
    if (typeof LightweightCharts === 'undefined') {
      var errEl = document.createElement('div');
      errEl.className = 'empty-state';
      errEl.textContent = 'Chart library not loaded';
      container.appendChild(errEl);
      return;
    }

    var chartWidth = container.clientWidth - 32;
    var chartHeight = Math.max(container.clientHeight - 32, 350);

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
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#2a3040',
      },
      timeScale: {
        borderColor: '#2a3040',
        timeVisible: true,
      },
    });

    this.candleSeries = this.chart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#ef4444',
      borderDownColor: '#ef4444',
      borderUpColor: '#10b981',
      wickDownColor: '#ef4444',
      wickUpColor: '#10b981',
    });

    /* Normalize data */
    var chartData = candles.map(function(c) {
      return {
        time: c.time || c.date || c.timestamp,
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close),
      };
    }).sort(function(a, b) {
      return a.time < b.time ? -1 : a.time > b.time ? 1 : 0;
    });

    this.candleSeries.setData(chartData);
    this.chart.timeScale().fitContent();

    /* Handle resize */
    var self = this;
    var resizeObserver = new ResizeObserver(function() {
      if (self.chart) {
        self.chart.applyOptions({
          width: container.clientWidth - 32,
        });
      }
    });
    resizeObserver.observe(container);
  },
};
