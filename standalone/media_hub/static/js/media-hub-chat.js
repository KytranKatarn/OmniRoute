/**
 * media-hub-chat.js
 * M.A.V.E.N. floating chat overlay for the Media Hub standalone.
 * Accent: #3b82f6 (archie-blue). Included in maven_base.html on every
 * M.A.V.E.N. page except the dedicated /maven/chat page.
 */
(function () {
    'use strict';

    var ACCENT = '#3b82f6';
    var STORAGE_KEY = 'maven_overlay_history';

    /* ── Inject styles ───────────────────────────────────────────────────── */
    var style = document.createElement('style');
    style.textContent = [
        '#mv-fab{position:fixed;bottom:1.5rem;right:1.5rem;z-index:9000;',
        'width:52px;height:52px;border-radius:50%;background:' + ACCENT + ';',
        'border:none;cursor:pointer;box-shadow:0 4px 16px rgba(59,130,246,.45);',
        'display:flex;align-items:center;justify-content:center;',
        'transition:transform .15s,box-shadow .15s;font-size:1.4rem;color:#fff;}',

        '#mv-fab:hover{transform:scale(1.08);box-shadow:0 6px 20px rgba(59,130,246,.6);}',

        '#mv-panel{position:fixed;bottom:5.5rem;right:1.5rem;z-index:9001;',
        'width:360px;max-width:calc(100vw - 2rem);',
        'background:var(--archie-bg-elevated,#1e293b);',
        'border:1px solid var(--archie-border-subtle,#334155);',
        'border-radius:16px;box-shadow:0 8px 32px rgba(0,0,0,.45);',
        'display:none;flex-direction:column;overflow:hidden;}',

        '#mv-panel-head{display:flex;align-items:center;gap:.6rem;',
        'padding:.8rem 1rem;background:' + ACCENT + ';color:#fff;}',

        '#mv-panel-head .mv-title{flex:1;font-weight:700;font-size:.95rem;}',

        '#mv-panel-head button{background:none;border:none;color:rgba(255,255,255,.8);',
        'cursor:pointer;font-size:1.1rem;line-height:1;padding:2px;}',
        '#mv-panel-head button:hover{color:#fff;}',

        '#mv-log{flex:1;overflow-y:auto;padding:.75rem;',
        'display:flex;flex-direction:column;gap:.5rem;',
        'min-height:180px;max-height:320px;scroll-behavior:smooth;}',

        '.mv-msg{max-width:88%;padding:.55rem .85rem;border-radius:12px;',
        'font-size:.875rem;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;}',

        '.mv-user{align-self:flex-end;background:' + ACCENT + ';color:#fff;',
        'border-bottom-right-radius:3px;}',

        '.mv-maven{align-self:flex-start;',
        'background:var(--archie-bg-secondary,#0f172a);',
        'border:1px solid var(--archie-border-subtle,#334155);',
        'color:var(--archie-text-primary,#e2e8f0);border-bottom-left-radius:3px;}',

        '.mv-pending{align-self:flex-start;color:var(--archie-text-muted,#94a3b8);',
        'font-style:italic;font-size:.8rem;padding:.3rem 0;}',

        '.mv-error{align-self:flex-start;background:rgba(239,68,68,.1);',
        'border-left:2px solid #ef4444;color:#fca5a5;',
        'border-radius:6px;font-size:.82rem;}',

        '#mv-form{display:flex;gap:.4rem;padding:.6rem .75rem;',
        'border-top:1px solid var(--archie-border-subtle,#334155);}',

        '#mv-input{flex:1;background:var(--archie-bg-secondary,#0f172a);',
        'border:1px solid var(--archie-border-subtle,#334155);',
        'border-radius:8px;color:var(--archie-text-primary,#e2e8f0);',
        'padding:.45rem .7rem;font-size:.875rem;font-family:inherit;outline:none;}',
        '#mv-input:focus{border-color:' + ACCENT + ';}',

        '#mv-send{background:' + ACCENT + ';color:#fff;border:none;',
        'border-radius:8px;padding:.45rem .8rem;font-weight:600;',
        'cursor:pointer;font-size:.875rem;}',
        '#mv-send:disabled{opacity:.55;cursor:default;}',

        '#mv-open-full{display:block;text-align:center;padding:.5rem;',
        'font-size:.75rem;color:var(--archie-text-muted,#94a3b8);',
        'border-top:1px solid var(--archie-border-subtle,#334155);',
        'text-decoration:none;}',
        '#mv-open-full:hover{color:' + ACCENT + ';}',
    ].join('');
    document.head.appendChild(style);

    /* ── Build DOM ───────────────────────────────────────────────────────── */
    var fab = document.createElement('button');
    fab.id = 'mv-fab';
    fab.setAttribute('aria-label', 'Chat with M.A.V.E.N.');
    fab.setAttribute('title', 'Chat with M.A.V.E.N.');
    fab.textContent = '💬';

    var panel = document.createElement('div');
    panel.id = 'mv-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'M.A.V.E.N. chat');

    panel.innerHTML = [
        '<div id="mv-panel-head">',
        '  <span class="mv-title">M.A.V.E.N.</span>',
        '  <button id="mv-close" aria-label="Close chat">✕</button>',
        '</div>',
        '<div id="mv-log" role="log" aria-live="polite"></div>',
        '<form id="mv-form">',
        '  <input id="mv-input" type="text" autocomplete="off"',
        '         placeholder="Ask about your library…">',
        '  <button id="mv-send" type="submit">Send</button>',
        '</form>',
        '<a id="mv-open-full" href="/maven/chat">Open full chat →</a>',
    ].join('');

    document.body.appendChild(fab);
    document.body.appendChild(panel);

    /* ── State ───────────────────────────────────────────────────────────── */
    var logEl   = panel.querySelector('#mv-log');
    var form    = panel.querySelector('#mv-form');
    var input   = panel.querySelector('#mv-input');
    var sendBtn = panel.querySelector('#mv-send');
    var closeBtn = panel.querySelector('#mv-close');
    var open = false;

    // Short session history (last 12 exchanges)
    var history = [];
    try { history = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]'); } catch (_) {}

    function saveHistory() {
        try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-24))); } catch (_) {}
    }

    /* ── Helpers ─────────────────────────────────────────────────────────── */
    function addMsg(text, cls) {
        var el = document.createElement('div');
        el.className = 'mv-msg ' + cls;
        el.textContent = text;
        logEl.appendChild(el);
        el.scrollIntoView({ block: 'end' });
        return el;
    }

    function restoreHistory() {
        history.forEach(function (m) {
            addMsg(m.content, m.role === 'user' ? 'mv-user' : 'mv-maven');
        });
    }

    /* ── Toggle ──────────────────────────────────────────────────────────── */
    function openPanel() {
        panel.style.display = 'flex';
        open = true;
        fab.textContent = '✕';
        if (history.length === 0) {
            addMsg('Hi! Ask me about your library, downloads, or request something new.', 'mv-maven');
        }
        setTimeout(function () { input.focus(); }, 50);
    }

    function closePanel() {
        panel.style.display = 'none';
        open = false;
        fab.textContent = '💬';
    }

    fab.addEventListener('click', function () {
        if (open) { closePanel(); } else { openPanel(); }
    });
    closeBtn.addEventListener('click', closePanel);

    /* ── Send ────────────────────────────────────────────────────────────── */
    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var text = input.value.trim();
        if (!text || sendBtn.disabled) return;

        addMsg(text, 'mv-user');
        history.push({ role: 'user', content: text });
        saveHistory();
        input.value = '';
        sendBtn.disabled = true;

        var pending = addMsg('M.A.V.E.N. is thinking…', 'mv-pending');

        var payload = JSON.stringify({ messages: history });
        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/maven/api/chat', true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.onload = function () {
            pending.remove();
            try {
                var j = JSON.parse(xhr.responseText);
                if (j.error) {
                    addMsg(j.error, 'mv-error');
                } else {
                    addMsg(j.reply, 'mv-maven');
                    history.push({ role: 'assistant', content: j.reply });
                    saveHistory();
                }
            } catch (_) {
                addMsg('Unexpected response from M.A.V.E.N.', 'mv-error');
            }
            sendBtn.disabled = false;
            input.focus();
        };
        xhr.onerror = function () {
            pending.remove();
            addMsg('Network error — check your connection.', 'mv-error');
            sendBtn.disabled = false;
        };
        xhr.send(payload);
    });

    /* ── Restore session history on first open ───────────────────────────── */
    if (history.length > 0) {
        restoreHistory();
    }

}());
