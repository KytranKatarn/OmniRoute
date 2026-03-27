/* M.A.R.K.E.T. — Alerts tab: create, list, delete alerts */
'use strict';

var Alerts = {
  loaded: false,

  load() {
    this._bindEvents();
    this._refresh();
    this.loaded = true;
  },

  _bindEvents() {
    if (this._bound) return;
    this._bound = true;

    var btn = document.getElementById('alert-create-btn');
    if (btn) {
      btn.addEventListener('click', function() { Alerts._create(); });
    }
  },

  async _create() {
    var tickerEl = document.getElementById('alert-ticker');
    var typeEl = document.getElementById('alert-type');
    var valueEl = document.getElementById('alert-value');

    var ticker = tickerEl ? tickerEl.value.trim().toUpperCase() : '';
    var alertType = typeEl ? typeEl.value : '';
    var value = valueEl ? parseFloat(valueEl.value) : NaN;

    if (!ticker) { App.toast('Enter a ticker', 'error'); return; }
    if (isNaN(value)) { App.toast('Enter a valid value', 'error'); return; }

    try {
      await API.createAlert({
        ticker: ticker,
        alert_type: alertType,
        value: value,
      });
      App.toast('Alert created for ' + ticker);
      if (tickerEl) tickerEl.value = '';
      if (valueEl) valueEl.value = '';
      this._refresh();
    } catch (e) {
      App.toast('Failed to create alert: ' + e.message, 'error');
    }
  },

  async _delete(id) {
    try {
      await API.deleteAlert(id);
      App.toast('Alert deleted');
      this._refresh();
    } catch (e) {
      App.toast('Failed to delete alert: ' + e.message, 'error');
    }
  },

  async _refresh() {
    App.setLoading('alerts-tbody');

    try {
      var data = await API.getAlerts();
      var alerts = data.alerts || data;

      if (!Array.isArray(alerts) || alerts.length === 0) {
        App.setEmpty('alerts-tbody', 'No alerts. Create one above.');
        return;
      }

      var tbody = document.getElementById('alerts-tbody');
      App.clearEl(tbody);

      alerts.forEach(function(alert) {
        var tr = document.createElement('tr');

        /* Ticker */
        var tdTicker = document.createElement('td');
        tdTicker.style.fontWeight = '600';
        tdTicker.style.color = 'var(--accent)';
        tdTicker.textContent = alert.ticker || '--';
        tr.appendChild(tdTicker);

        /* Type */
        var tdType = document.createElement('td');
        tdType.textContent = (alert.alert_type || alert.type || '--').replace(/_/g, ' ');
        tr.appendChild(tdType);

        /* Target */
        var tdTarget = document.createElement('td');
        tdTarget.textContent = alert.value != null ? alert.value : '--';
        tr.appendChild(tdTarget);

        /* Status */
        var tdStatus = document.createElement('td');
        var status = alert.status || 'active';
        tdStatus.appendChild(App.createBadge(status, status));
        tr.appendChild(tdStatus);

        /* Created */
        var tdCreated = document.createElement('td');
        tdCreated.textContent = App.formatDateTime(alert.created_at);
        tr.appendChild(tdCreated);

        /* Triggered */
        var tdTriggered = document.createElement('td');
        tdTriggered.textContent = alert.triggered_at ? App.formatDateTime(alert.triggered_at) : '--';
        tr.appendChild(tdTriggered);

        /* Actions */
        var tdActions = document.createElement('td');
        var delBtn = document.createElement('button');
        delBtn.className = 'btn btn--danger btn--small';
        delBtn.textContent = 'Delete';
        delBtn.addEventListener('click', function() {
          Alerts._delete(alert.id);
        });
        tdActions.appendChild(delBtn);
        tr.appendChild(tdActions);

        tbody.appendChild(tr);
      });
    } catch (e) {
      App.setEmpty('alerts-tbody', 'Failed to load alerts');
    }
  },
};
