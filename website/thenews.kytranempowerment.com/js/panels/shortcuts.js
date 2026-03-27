/* ==========================================================================
   Kytran News — Keyboard Shortcuts Panel + Fullscreen Toggle
   Press ? or H to show shortcuts overlay, F for fullscreen
   ========================================================================== */

var Shortcuts = (function () {
    'use strict';

    var _overlay = null;
    var _visible = false;

    var _shortcuts = [
        { key: '1', desc: 'Region: World' },
        { key: '2', desc: 'Region: Americas' },
        { key: '3', desc: 'Region: Europe' },
        { key: '4', desc: 'Region: Asia' },
        { key: '5', desc: 'Region: MENA' },
        { key: '6', desc: 'Region: Africa' },
        { key: 'Q', desc: 'Time: 1 Hour' },
        { key: 'W', desc: 'Time: 6 Hours' },
        { key: 'E', desc: 'Time: 24 Hours' },
        { key: 'R', desc: 'Time: 48 Hours' },
        { key: 'T', desc: 'Time: 7 Days' },
        { key: 'F', desc: 'Toggle fullscreen' },
        { key: 'Esc', desc: 'Close panels' },
        { key: '?', desc: 'Show this help' }
    ];

    function init() {
        _createOverlay();
        _bindKeys();
    }

    function _createOverlay() {
        _overlay = document.createElement('div');
        _overlay.className = 'shortcuts-overlay';

        /* Build DOM safely using createElement/textContent */
        var panel = document.createElement('div');
        panel.className = 'shortcuts-overlay__panel';

        var header = document.createElement('div');
        header.className = 'shortcuts-overlay__header';

        var title = document.createElement('span');
        title.className = 'shortcuts-overlay__title';
        title.textContent = 'KEYBOARD SHORTCUTS';

        var closeBtn = document.createElement('button');
        closeBtn.className = 'shortcuts-overlay__close';
        closeBtn.setAttribute('aria-label', 'Close');
        closeBtn.textContent = '\u00D7';
        closeBtn.addEventListener('click', _hide);

        header.appendChild(title);
        header.appendChild(closeBtn);

        var grid = document.createElement('div');
        grid.className = 'shortcuts-overlay__grid';

        _shortcuts.forEach(function (s) {
            var item = document.createElement('div');
            item.className = 'shortcuts-overlay__item';

            var kbd = document.createElement('kbd');
            kbd.className = 'shortcuts-overlay__key';
            kbd.textContent = s.key;

            var desc = document.createElement('span');
            desc.className = 'shortcuts-overlay__desc';
            desc.textContent = s.desc;

            item.appendChild(kbd);
            item.appendChild(desc);
            grid.appendChild(item);
        });

        panel.appendChild(header);
        panel.appendChild(grid);
        _overlay.appendChild(panel);
        document.body.appendChild(_overlay);

        /* Close on backdrop click */
        _overlay.addEventListener('click', function (e) {
            if (e.target === _overlay) _hide();
        });
    }

    function _bindKeys() {
        var regionMap = { '1': 'world', '2': 'americas', '3': 'europe', '4': 'asia', '5': 'mena', '6': 'africa' };
        var timeMap = { 'q': '1h', 'w': '6h', 'e': '24h', 'r': '48h', 't': '7d' };

        document.addEventListener('keydown', function (e) {
            /* Ignore when typing in inputs */
            var tag = (e.target.tagName || '').toLowerCase();
            if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

            var key = e.key.toLowerCase();

            /* Toggle shortcuts overlay */
            if (key === '?' || (key === 'h' && !e.ctrlKey && !e.metaKey)) {
                e.preventDefault();
                _toggle();
                return;
            }

            /* Escape — close overlay or other panels */
            if (key === 'escape') {
                if (_visible) { _hide(); return; }
                /* Close search results */
                var sr = document.getElementById('search-results');
                if (sr) sr.classList.remove('open');
                return;
            }

            /* Fullscreen toggle */
            if (key === 'f' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault();
                _toggleFullscreen();
                return;
            }

            /* Region shortcuts */
            if (regionMap[key]) {
                var sel = document.getElementById('region-select');
                if (sel) {
                    sel.value = regionMap[key];
                    sel.dispatchEvent(new Event('change'));
                }
                return;
            }

            /* Time range shortcuts */
            if (timeMap[key]) {
                var tsel = document.getElementById('time-select');
                if (tsel) {
                    tsel.value = timeMap[key];
                    tsel.dispatchEvent(new Event('change'));
                }
                return;
            }
        });
    }

    function _toggleFullscreen() {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(function () {});
        } else {
            document.exitFullscreen().catch(function () {});
        }
    }

    function _toggle() {
        if (_visible) _hide(); else _show();
    }

    function _show() {
        if (!_overlay) return;
        _overlay.classList.add('visible');
        _visible = true;
    }

    function _hide() {
        if (!_overlay) return;
        _overlay.classList.remove('visible');
        _visible = false;
    }

    return { init: init, toggle: _toggle, toggleFullscreen: _toggleFullscreen };
})();
