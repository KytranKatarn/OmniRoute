/* M.A.R.K.E.T. — Analysis tab: agent reports + recommendation badges */
'use strict';

var Analysis = {
  loaded: false,

  load() {
    this._bindEvents();
    this._refresh();
    this.loaded = true;
  },

  _bindEvents() {
    if (this._bound) return;
    this._bound = true;

    var runBtn = document.getElementById('analysis-run-btn');
    if (runBtn) {
      runBtn.addEventListener('click', function() { Analysis._runCycle(); });
    }
  },

  async _runCycle() {
    var btn = document.getElementById('analysis-run-btn');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Running...';
    }

    try {
      await API.runCycle();
      App.toast('Analysis cycle started');
      /* Reload after a short delay to show results */
      setTimeout(function() { Analysis._refresh(); }, 3000);
    } catch (e) {
      App.toast('Failed to start cycle: ' + e.message, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Run Analysis Cycle';
      }
    }
  },

  async _refresh() {
    var container = document.getElementById('analysis-reports');
    if (!container) return;

    App.clearEl(container);
    var loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading';
    loadingDiv.textContent = 'Loading analysis reports\u2026';
    container.appendChild(loadingDiv);

    try {
      /* Load cycles info */
      var cycleData = await API.getCycles();
      var cycles = cycleData.cycles || cycleData;
      var lastCycleEl = document.getElementById('analysis-last-cycle');
      if (lastCycleEl && Array.isArray(cycles) && cycles.length > 0) {
        lastCycleEl.textContent = App.formatDateTime(cycles[0].started_at || cycles[0].created_at);
      }

      /* Load reports */
      var data = await API.getAnalysis();
      var reports = data.reports || data;

      App.clearEl(container);

      if (!Array.isArray(reports) || reports.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        empty.textContent = 'No analysis reports yet. Click "Run Analysis Cycle" to generate reports.';
        container.appendChild(empty);
        return;
      }

      reports.forEach(function(report) {
        /* Ticker header */
        var tickerHeader = document.createElement('div');
        tickerHeader.className = 'analysis-ticker-header';

        var sym = document.createElement('span');
        sym.className = 'analysis-ticker-header__sym';
        sym.textContent = report.ticker || '--';
        tickerHeader.appendChild(sym);

        var meta = document.createElement('span');
        meta.className = 'analysis-ticker-header__meta';
        meta.textContent = report.created_at ? 'Analyzed: ' + App.formatDateTime(report.created_at) : '';
        tickerHeader.appendChild(meta);
        container.appendChild(tickerHeader);

        /* 6-agent cards grid */
        var grid = document.createElement('div');
        grid.className = 'agent-cards-grid';

        var agentDefs = [
          { key: 'quant',   cls: 'quant',  name: 'Quant',   persona: 'Raj Mehta',      reportKey: 'quant_report',  scoreKey: 'quant_score' },
          { key: 'value',   cls: 'value',  name: 'Value',   persona: 'Maya Chen',      reportKey: 'value_report',  scoreKey: 'value_score' },
          { key: 'pulse',   cls: 'pulse',  name: 'Pulse',   persona: 'Jordan Rivera',  reportKey: 'pulse_report',  scoreKey: 'pulse_score' },
          { key: 'shield',  cls: 'shield', name: 'Shield',  persona: 'Alex Storm',     reportKey: 'risk_assessment', scoreKey: null },
          { key: 'oracle',  cls: 'oracle', name: 'Oracle',  persona: 'Director',       reportKey: 'oracle_synthesis', scoreKey: null, isOracle: true },
          { key: 'market',  cls: 'market', name: 'M.A.R.K.E.T.', persona: 'Execution', reportKey: 'market_execution', scoreKey: null, isMarket: true },
        ];

        agentDefs.forEach(function(def) {
          var reportText = report[def.reportKey];
          if (!reportText && !def.isOracle && !def.isMarket) return;

          var card = document.createElement('div');
          card.className = 'agent-card ' + def.cls + (def.isOracle ? ' agent-card--oracle' : '');

          /* Card header */
          var cardHeader = document.createElement('div');
          cardHeader.className = 'agent-card__header';

          var nameWrap = document.createElement('div');
          var nameEl = document.createElement('span');
          nameEl.className = 'agent-card__name';
          nameEl.textContent = def.name;
          nameWrap.appendChild(nameEl);
          var personaEl = document.createElement('span');
          personaEl.className = 'agent-card__persona';
          personaEl.textContent = '— ' + def.persona;
          nameWrap.appendChild(personaEl);
          cardHeader.appendChild(nameWrap);

          /* Score bar (if applicable) */
          if (def.scoreKey && report[def.scoreKey] != null) {
            var scoreWrap = document.createElement('div');
            scoreWrap.className = 'agent-card__score';
            var bar = document.createElement('div');
            bar.className = 'score-bar';
            var fill = document.createElement('div');
            fill.className = 'score-bar__fill';
            fill.style.width = report[def.scoreKey] + '%';
            bar.appendChild(fill);
            scoreWrap.appendChild(bar);
            var scoreVal = document.createElement('span');
            scoreVal.className = 'score-value';
            scoreVal.textContent = report[def.scoreKey] + '/100';
            scoreWrap.appendChild(scoreVal);
            cardHeader.appendChild(scoreWrap);
          }

          card.appendChild(cardHeader);

          /* Report body */
          var body = document.createElement('div');
          body.className = 'agent-card__body';
          body.textContent = reportText || (def.isOracle ? 'No synthesis available.' : def.isMarket ? 'No execution data.' : '');
          card.appendChild(body);

          /* Oracle footer: recommendation + confidence */
          if (def.isOracle && (report.recommendation || report.oracle_confidence != null)) {
            var footer = document.createElement('div');
            footer.className = 'agent-card__footer';

            if (report.recommendation) {
              var recBadge = document.createElement('span');
              recBadge.className = 'badge-' + report.recommendation.toLowerCase();
              recBadge.textContent = report.recommendation.toUpperCase();
              footer.appendChild(recBadge);
            }

            if (report.oracle_confidence != null) {
              var conf = document.createElement('span');
              conf.className = 'confidence-pct';
              conf.textContent = 'Confidence: ' + report.oracle_confidence + '%';
              footer.appendChild(conf);
            }

            card.appendChild(footer);
          }

          /* M.A.R.K.E.T. execution line */
          if (def.isMarket && report.market_execution) {
            var execLine = document.createElement('div');
            execLine.className = 'agent-card__execution';
            execLine.textContent = report.market_execution;
            card.appendChild(execLine);
          }

          grid.appendChild(card);
        });

        container.appendChild(grid);
      });
    } catch (e) {
      App.clearEl(container);
      var errEl = document.createElement('div');
      errEl.className = 'empty-state';
      errEl.textContent = 'Failed to load analysis reports';
      container.appendChild(errEl);
    }
  },
};
