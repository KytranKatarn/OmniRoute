/* ==========================================================================
   Kytran News — Embed Widget
   Generate iframe snippet for embedding in other sites
   ========================================================================== */

var Embed = (function () {
    'use strict';

    var _overlayEl = null;

    function init() {
        var btn = document.getElementById('embed-btn');
        if (btn) btn.addEventListener('click', showEmbed);
    }

    function showEmbed() {
        if (_overlayEl) { close(); return; }

        var shareUrl = typeof Share !== 'undefined' ? Share.getShareUrl() : window.location.href;

        _overlayEl = document.createElement('div');
        _overlayEl.className = 'embed-overlay';

        var card = document.createElement('div');
        card.className = 'embed-card';

        /* Header */
        var header = document.createElement('div');
        header.className = 'embed-card__header';
        var headerTitle = document.createElement('span');
        headerTitle.textContent = 'Embed Kytran News';
        header.appendChild(headerTitle);
        var closeBtn = document.createElement('button');
        closeBtn.className = 'embed-card__close';
        closeBtn.textContent = '\u00D7';
        closeBtn.addEventListener('click', close);
        header.appendChild(closeBtn);
        card.appendChild(header);

        /* Sizes */
        var sizes = [
            { label: 'Small (400x300)', w: 400, h: 300 },
            { label: 'Medium (640x480)', w: 640, h: 480 },
            { label: 'Large (960x600)', w: 960, h: 600 },
            { label: 'Full Width', w: '100%', h: 600 }
        ];

        var sizeSelect = document.createElement('select');
        sizeSelect.className = 'embed-card__select';
        sizes.forEach(function (s, i) {
            var opt = document.createElement('option');
            opt.value = i;
            opt.textContent = s.label;
            if (i === 1) opt.selected = true;
            sizeSelect.appendChild(opt);
        });
        card.appendChild(sizeSelect);

        /* Code textarea */
        var textarea = document.createElement('textarea');
        textarea.className = 'embed-card__code';
        textarea.readOnly = true;
        textarea.rows = 4;
        function updateCode() {
            var s = sizes[parseInt(sizeSelect.value)];
            var w = typeof s.w === 'string' ? s.w : s.w + 'px';
            textarea.value = '<iframe src="' + shareUrl + '" width="' + w + '" height="' + s.h + '" frameborder="0" style="border:1px solid rgba(255,255,255,0.1);border-radius:8px;" allowfullscreen></iframe>';
        }
        sizeSelect.addEventListener('change', updateCode);
        updateCode();
        card.appendChild(textarea);

        /* Copy button */
        var copyBtn = document.createElement('button');
        copyBtn.className = 'embed-card__copy';
        copyBtn.textContent = 'Copy Embed Code';
        copyBtn.addEventListener('click', function () {
            textarea.select();
            if (navigator.clipboard) {
                navigator.clipboard.writeText(textarea.value);
            } else {
                document.execCommand('copy');
            }
            copyBtn.textContent = 'Copied!';
            setTimeout(function () { copyBtn.textContent = 'Copy Embed Code'; }, 1500);
        });
        card.appendChild(copyBtn);

        _overlayEl.appendChild(card);
        document.body.appendChild(_overlayEl);

        _overlayEl.addEventListener('click', function (e) {
            if (e.target === _overlayEl) close();
        });

        setTimeout(function () { _overlayEl.classList.add('open'); }, 10);
    }

    function close() {
        if (_overlayEl) {
            _overlayEl.classList.remove('open');
            setTimeout(function () {
                if (_overlayEl && _overlayEl.parentNode) {
                    _overlayEl.parentNode.removeChild(_overlayEl);
                }
                _overlayEl = null;
            }, 300);
        }
    }

    return { init: init, showEmbed: showEmbed, close: close };
})();
