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
        var card = document.createElement('div');
        card.className = 'report-card';

        /* Header */
        var header = document.createElement('div');
        header.className = 'report-card__header';

        var ticker = document.createElement('span');
        ticker.className = 'report-card__ticker';
        ticker.textContent = report.ticker || '--';
        header.appendChild(ticker);

        if (report.recommendation) {
          header.appendChild(App.createBadge(report.recommendation, report.recommendation));
        }
        card.appendChild(header);

        /* Director thesis */
        if (report.director_thesis) {
          var section1 = document.createElement('div');
          section1.className = 'report-card__section';
          var label1 = document.createElement('div');
          label1.className = 'report-card__label';
          label1.textContent = 'Director Thesis';
          section1.appendChild(label1);
          var body1 = document.createElement('div');
          body1.className = 'report-card__body';
          body1.textContent = report.director_thesis;
          section1.appendChild(body1);
          card.appendChild(section1);
        }

        /* Quant score */
        if (report.quant_score != null) {
          var section2 = document.createElement('div');
          section2.className = 'report-card__section';
          var label2 = document.createElement('div');
          label2.className = 'report-card__label';
          label2.textContent = 'Quant Score';
          section2.appendChild(label2);
          var body2 = document.createElement('div');
          body2.className = 'report-card__body';
          body2.textContent = report.quant_score + '/100';
          if (report.quant_details) {
            var details = document.createElement('div');
            details.style.marginTop = '4px';
            details.style.fontSize = '0.8rem';
            details.textContent = report.quant_details;
            body2.appendChild(details);
          }
          section2.appendChild(body2);
          card.appendChild(section2);
        }

        /* Risk assessment */
        if (report.risk_assessment) {
          var section3 = document.createElement('div');
          section3.className = 'report-card__section';
          var label3 = document.createElement('div');
          label3.className = 'report-card__label';
          label3.textContent = 'Risk Assessment';
          section3.appendChild(label3);
          var body3 = document.createElement('div');
          body3.className = 'report-card__body';
          body3.textContent = report.risk_assessment;
          section3.appendChild(body3);
          card.appendChild(section3);
        }

        /* Timestamp */
        if (report.created_at) {
          var footer = document.createElement('div');
          footer.style.marginTop = '8px';
          footer.style.fontSize = '0.7rem';
          footer.style.color = 'var(--text-dim)';
          footer.textContent = 'Analyzed: ' + App.formatDateTime(report.created_at);
          card.appendChild(footer);
        }

        container.appendChild(card);
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
