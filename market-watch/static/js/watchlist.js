/* M.A.R.K.E.T. — Watchlist tab: CRUD + price display */
'use strict';

var Watchlist = {
  loaded: false,

  load() {
    this._bindEvents();
    this._refresh();
    this.loaded = true;
  },

  _bindEvents() {
    if (this._bound) return;
    this._bound = true;

    var addBtn = document.getElementById('watchlist-add-btn');
    if (addBtn) {
      addBtn.addEventListener('click', () => this._add());
    }

    var input = document.getElementById('watchlist-ticker');
    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this._add();
      });
    }
  },

  async _add() {
    var input = document.getElementById('watchlist-ticker');
    if (!input) return;
    var ticker = input.value.trim().toUpperCase();
    if (!ticker) return;

    try {
      await API.addWatchlist(ticker);
      input.value = '';
      App.toast(ticker + ' added to watchlist');
      this._refresh();
    } catch (e) {
      App.toast('Failed to add ' + ticker + ': ' + e.message, 'error');
    }
  },

  async _remove(id, ticker) {
    try {
      await API.removeWatchlist(id);
      App.toast(ticker + ' removed from watchlist');
      this._refresh();
    } catch (e) {
      App.toast('Failed to remove: ' + e.message, 'error');
    }
  },

  async _refresh() {
    App.setLoading('watchlist-tbody');

    try {
      var data = await API.getWatchlist();
      var items = data.watchlist || data;

      if (!Array.isArray(items) || items.length === 0) {
        App.setEmpty('watchlist-tbody', 'No stocks in watchlist. Add a ticker above.');
        return;
      }

      var tbody = document.getElementById('watchlist-tbody');
      App.clearEl(tbody);

      items.forEach(function(stock) {
        var tr = document.createElement('tr');

        /* Ticker */
        var tdTicker = document.createElement('td');
        tdTicker.style.fontWeight = '600';
        tdTicker.style.color = 'var(--accent)';
        tdTicker.textContent = stock.ticker;
        tr.appendChild(tdTicker);

        /* Price */
        var tdPrice = document.createElement('td');
        tdPrice.textContent = stock.price != null ? App.formatCurrency(stock.price) : '--';
        tr.appendChild(tdPrice);

        /* Change */
        var tdChange = document.createElement('td');
        tdChange.className = App.pnlClass(stock.change);
        tdChange.textContent = stock.change != null ? App.formatCurrency(stock.change) : '--';
        tr.appendChild(tdChange);

        /* Change % */
        var tdChangePct = document.createElement('td');
        tdChangePct.className = App.pnlClass(stock.change_pct);
        tdChangePct.textContent = stock.change_pct != null ? App.formatPct(stock.change_pct) : '--';
        tr.appendChild(tdChangePct);

        /* Last Analysis */
        var tdAnalysis = document.createElement('td');
        if (stock.recommendation) {
          tdAnalysis.appendChild(App.createBadge(stock.recommendation, stock.recommendation));
        } else {
          tdAnalysis.textContent = '--';
          tdAnalysis.style.color = 'var(--text-dim)';
        }
        tr.appendChild(tdAnalysis);

        /* Actions */
        var tdActions = document.createElement('td');
        var removeBtn = document.createElement('button');
        removeBtn.className = 'btn btn--danger btn--small';
        removeBtn.textContent = 'Remove';
        removeBtn.addEventListener('click', function() {
          Watchlist._remove(stock.id, stock.ticker);
        });
        tdActions.appendChild(removeBtn);
        tr.appendChild(tdActions);

        tbody.appendChild(tr);
      });
    } catch (e) {
      App.setEmpty('watchlist-tbody', 'Failed to load watchlist');
    }
  },
};
