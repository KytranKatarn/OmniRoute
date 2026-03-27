/* M.A.R.K.E.T. — Trading tab: order form + execution history */
'use strict';

var Trading = {
  loaded: false,

  load() {
    this._bindEvents();
    this._refreshOrders();
    this.loaded = true;
  },

  _bindEvents() {
    if (this._bound) return;
    this._bound = true;

    var buyBtn = document.getElementById('buy-submit-btn');
    if (buyBtn) {
      buyBtn.addEventListener('click', function() { Trading._executeBuy(); });
    }

    var sellBtn = document.getElementById('sell-submit-btn');
    if (sellBtn) {
      sellBtn.addEventListener('click', function() { Trading._executeSell(); });
    }
  },

  async _executeBuy() {
    var tickerEl = document.getElementById('buy-ticker');
    var qtyEl = document.getElementById('buy-qty');

    var ticker = tickerEl ? tickerEl.value.trim().toUpperCase() : '';
    var qty = qtyEl ? parseInt(qtyEl.value, 10) : 0;

    if (!ticker) { App.toast('Enter a ticker', 'error'); return; }
    if (!qty || qty < 1) { App.toast('Enter a valid quantity', 'error'); return; }

    var btn = document.getElementById('buy-submit-btn');
    if (btn) btn.disabled = true;

    try {
      var result = await API.buy(ticker, qty);
      App.toast('Bought ' + qty + ' shares of ' + ticker);
      if (tickerEl) tickerEl.value = '';
      if (qtyEl) qtyEl.value = '';
      this._refreshOrders();
      /* Refresh portfolio if it was loaded */
      if (Portfolio.loaded) {
        Portfolio.loaded = false;
        Portfolio.load();
      }
    } catch (e) {
      App.toast('Buy failed: ' + e.message, 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  async _executeSell() {
    var tickerEl = document.getElementById('sell-ticker');
    var qtyEl = document.getElementById('sell-qty');

    var ticker = tickerEl ? tickerEl.value.trim().toUpperCase() : '';
    var qty = qtyEl ? parseInt(qtyEl.value, 10) : 0;

    if (!ticker) { App.toast('Enter a ticker', 'error'); return; }
    if (!qty || qty < 1) { App.toast('Enter a valid quantity', 'error'); return; }

    var btn = document.getElementById('sell-submit-btn');
    if (btn) btn.disabled = true;

    try {
      var result = await API.sell(ticker, qty);
      App.toast('Sold ' + qty + ' shares of ' + ticker);
      if (tickerEl) tickerEl.value = '';
      if (qtyEl) qtyEl.value = '';
      this._refreshOrders();
      if (Portfolio.loaded) {
        Portfolio.loaded = false;
        Portfolio.load();
      }
    } catch (e) {
      App.toast('Sell failed: ' + e.message, 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  },

  async _refreshOrders() {
    App.setLoading('orders-tbody');

    try {
      var data = await API.getOrders();
      var orders = data.orders || data;

      if (!Array.isArray(orders) || orders.length === 0) {
        App.setEmpty('orders-tbody', 'No orders yet');
        return;
      }

      var tbody = document.getElementById('orders-tbody');
      App.clearEl(tbody);

      orders.forEach(function(order) {
        var tr = document.createElement('tr');

        /* Time */
        var tdTime = document.createElement('td');
        tdTime.textContent = App.formatDateTime(order.created_at || order.executed_at);
        tr.appendChild(tdTime);

        /* Side */
        var tdSide = document.createElement('td');
        var side = (order.side || order.action || '').toUpperCase();
        var sideSpan = document.createElement('span');
        sideSpan.style.fontWeight = '600';
        sideSpan.style.color = side === 'BUY' ? 'var(--positive)' : 'var(--negative)';
        sideSpan.textContent = side;
        tdSide.appendChild(sideSpan);
        tr.appendChild(tdSide);

        /* Ticker */
        var tdTicker = document.createElement('td');
        tdTicker.style.fontWeight = '600';
        tdTicker.textContent = order.ticker || '--';
        tr.appendChild(tdTicker);

        /* Qty */
        var tdQty = document.createElement('td');
        tdQty.textContent = order.quantity || '--';
        tr.appendChild(tdQty);

        /* Price */
        var tdPrice = document.createElement('td');
        tdPrice.textContent = App.formatCurrency(order.price);
        tr.appendChild(tdPrice);

        /* Total */
        var tdTotal = document.createElement('td');
        var total = (order.quantity || 0) * (order.price || 0);
        tdTotal.textContent = App.formatCurrency(order.total != null ? order.total : total);
        tr.appendChild(tdTotal);

        /* Status */
        var tdStatus = document.createElement('td');
        var status = order.status || 'filled';
        tdStatus.appendChild(App.createBadge(status, status));
        tr.appendChild(tdStatus);

        tbody.appendChild(tr);
      });
    } catch (e) {
      App.setEmpty('orders-tbody', 'Failed to load orders');
    }
  },
};
