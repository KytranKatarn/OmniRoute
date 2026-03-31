/* M.A.R.K.E.T. — Strategies tab: list, create, delete, toggle */
'use strict';

var Strategies = {
  loaded: false,

  load() {
    this._bindEvents();
    this._loadList();
    this.loaded = true;
  },

  _bindEvents() {
    if (this._bound) return;
    this._bound = true;

    var createBtn = document.getElementById('strategy-create-btn');
    if (createBtn) {
      createBtn.addEventListener('click', function() { Strategies._create(); });
    }
  },

  async _loadList() {
    var container = document.getElementById('strategies-list');
    if (!container) return;

    App.clearEl(container);
    var loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading';
    loadingDiv.textContent = 'Loading strategies\u2026';
    container.appendChild(loadingDiv);

    try {
      var data = await API.getStrategies();
      var strategies = data.strategies || data || [];

      App.clearEl(container);

      if (!Array.isArray(strategies) || strategies.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'empty-state';
        var icon = document.createElement('div');
        icon.className = 'empty-state__icon';
        icon.textContent = '\uD83D\uDCCA';
        empty.appendChild(icon);
        var msg = document.createElement('p');
        msg.textContent = 'No strategies yet. Create one below.';
        empty.appendChild(msg);
        container.appendChild(empty);
        return;
      }

      var list = document.createElement('div');
      list.className = 'strategy-list';

      strategies.forEach(function(s) {
        list.appendChild(Strategies._buildItem(s));
      });

      container.appendChild(list);
    } catch (e) {
      App.clearEl(container);
      var errEl = document.createElement('div');
      errEl.className = 'empty-state';
      errEl.textContent = 'Failed to load strategies';
      container.appendChild(errEl);
    }
  },

  _buildItem(s) {
    var item = document.createElement('div');
    item.className = 'strategy-item' + (s.is_active ? '' : ' strategy-item--inactive');
    item.setAttribute('data-id', s.id);

    var info = document.createElement('div');
    info.className = 'strategy-item__info';

    var name = document.createElement('div');
    name.className = 'strategy-item__name';
    name.textContent = s.name || 'Unnamed Strategy';
    info.appendChild(name);

    if (s.description) {
      var desc = document.createElement('div');
      desc.className = 'strategy-item__desc';
      desc.textContent = s.description;
      info.appendChild(desc);
    }

    if (s.win_rate != null || s.total_trades != null) {
      var stats = document.createElement('div');
      stats.className = 'strategy-item__stats';
      var parts = [];
      if (s.win_rate != null) parts.push('Win rate: ' + Number(s.win_rate).toFixed(1) + '%');
      if (s.total_trades != null) parts.push('Trades: ' + s.total_trades);
      stats.textContent = parts.join(' \u00B7 ');
      info.appendChild(stats);
    }

    item.appendChild(info);

    /* Actions */
    var actions = document.createElement('div');
    actions.className = 'strategy-item__actions';

    /* Active toggle */
    var toggleLabel = document.createElement('label');
    toggleLabel.className = 'strategy-toggle';
    var checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = !!s.is_active;
    checkbox.addEventListener('change', function() {
      Strategies._toggle(s.id, !s.is_active);
    });
    toggleLabel.appendChild(checkbox);
    var toggleText = document.createTextNode(s.is_active ? 'Active' : 'Inactive');
    toggleLabel.appendChild(toggleText);
    actions.appendChild(toggleLabel);

    /* Delete button */
    var delBtn = document.createElement('button');
    delBtn.className = 'btn btn--danger btn--small';
    delBtn.textContent = 'Delete';
    delBtn.addEventListener('click', function() { Strategies._delete(s.id); });
    actions.appendChild(delBtn);

    item.appendChild(actions);
    return item;
  },

  async _create() {
    var name = (document.getElementById('strategy-name') || {}).value || '';
    var desc = (document.getElementById('strategy-desc') || {}).value || '';
    var rulesRaw = (document.getElementById('strategy-rules') || {}).value || '{}';

    if (!name.trim()) {
      App.toast('Strategy name is required', 'error');
      return;
    }

    var rules = {};
    try {
      if (rulesRaw.trim()) rules = JSON.parse(rulesRaw);
    } catch (_) {
      App.toast('Rules must be valid JSON', 'error');
      return;
    }

    var btn = document.getElementById('strategy-create-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Creating\u2026'; }

    try {
      await API.createStrategy({ name: name.trim(), description: desc.trim(), rules: rules });
      App.toast('Strategy created');

      /* Clear form */
      var nameEl = document.getElementById('strategy-name');
      var descEl = document.getElementById('strategy-desc');
      var rulesEl = document.getElementById('strategy-rules');
      if (nameEl) nameEl.value = '';
      if (descEl) descEl.value = '';
      if (rulesEl) rulesEl.value = '';

      Strategies._loadList();
    } catch (e) {
      App.toast('Failed to create strategy: ' + e.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Create Strategy'; }
    }
  },

  async _delete(id) {
    if (!confirm('Delete this strategy?')) return;
    try {
      await API.deleteStrategy(id);
      App.toast('Strategy deleted');
      Strategies._loadList();
    } catch (e) {
      App.toast('Failed to delete: ' + e.message, 'error');
    }
  },

  async _toggle(id, newState) {
    try {
      await API.updateStrategy(id, { is_active: newState });
      App.toast(newState ? 'Strategy activated' : 'Strategy deactivated');
      Strategies._loadList();
    } catch (e) {
      App.toast('Failed to update strategy: ' + e.message, 'error');
      Strategies._loadList(); /* revert checkbox state */
    }
  },
};
