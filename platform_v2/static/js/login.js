(function() {
    'use strict';

    // ═══════════════════════════════════════════════════════════════════════
    // Stardate Calculator
    // ═══════════════════════════════════════════════════════════════════════
    function calcStardate() {
        var now = new Date();
        var y = now.getFullYear();
        var start = new Date(y, 0, 1);
        var diff = now - start;
        var dayOfYear = Math.floor(diff / 86400000);
        var fraction = (dayOfYear / 365.25).toFixed(1);
        // TNG-era stardate: (year - 1947) * 1000 + day fraction
        var sd = ((y - 1947) * 1000 + dayOfYear * (1000 / 365.25)).toFixed(1);
        return 'SD ' + sd;
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Boot Animation
    // ═══════════════════════════════════════════════════════════════════════
    var frame = document.getElementById('loginFrame');
    var stardateEl = document.getElementById('loginStardate');
    var BOOT_KEY = 'archie-login-booted';
    var skipBoot = sessionStorage.getItem(BOOT_KEY) === '1';
    // Clear dashboard boot key so boot animation plays after every fresh login
    sessionStorage.removeItem('archie-booted');

    function finishBoot() {
        frame.classList.remove('boot-hidden');
        frame.classList.add('frame-build');
        sessionStorage.setItem(BOOT_KEY, '1');
        // Set real stardate after brief easter egg
        if (stardateEl) {
            stardateEl.textContent = 'THREAT LEVEL MIDNIGHT';
            setTimeout(function() {
                stardateEl.textContent = calcStardate();
            }, 500);
        }
    }

    if (skipBoot) {
        // Skip animation, show immediately
        frame.classList.remove('boot-hidden');
        frame.classList.add('frame-build');
        if (stardateEl) stardateEl.textContent = calcStardate();
    } else {
        // Slight delay then trigger boot sequence
        setTimeout(finishBoot, 150);

        // Click or keypress to skip boot animation
        var skipHandler = function() {
            frame.classList.remove('boot-hidden');
            frame.classList.add('frame-build');
            sessionStorage.setItem(BOOT_KEY, '1');
            if (stardateEl) stardateEl.textContent = calcStardate();
            document.removeEventListener('click', skipHandler);
            document.removeEventListener('keypress', skipHandler);
        };
        document.addEventListener('click', skipHandler);
        document.addEventListener('keypress', skipHandler);
    }

    // ═══════════════════════════════════════════════════════════════════════
    // Form Submit — Loading State
    // ═══════════════════════════════════════════════════════════════════════
    document.getElementById('loginForm').addEventListener('submit', function() {
        var btn = document.getElementById('loginBtn');
        btn.classList.add('loading');
        btn.textContent = (typeof archieI18n !== 'undefined')
            ? archieI18n.t('login.authenticating', 'AUTHENTICATING...')
            : 'AUTHENTICATING...';
    });

    // ═══════════════════════════════════════════════════════════════════════
    // Forgot Password Toggle
    // ═══════════════════════════════════════════════════════════════════════
    document.getElementById('forgotPasswordLink').addEventListener('click', function(e) {
        e.preventDefault();
        var msg = document.getElementById('forgotPasswordMsg');
        msg.style.display = msg.style.display === 'none' || msg.style.display === '' ? 'block' : 'none';
    });

    // ═══════════════════════════════════════════════════════════════════════
    // Password Visibility Toggle
    // ═══════════════════════════════════════════════════════════════════════
    function createSvgIcon(pathData) {
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '16');
        svg.setAttribute('height', '16');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        pathData.forEach(function(d) {
            var el;
            if (d.tag === 'circle') {
                el = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                el.setAttribute('cx', d.cx); el.setAttribute('cy', d.cy); el.setAttribute('r', d.r);
            } else if (d.tag === 'line') {
                el = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                el.setAttribute('x1', d.x1); el.setAttribute('y1', d.y1);
                el.setAttribute('x2', d.x2); el.setAttribute('y2', d.y2);
            } else {
                el = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                el.setAttribute('d', d.d);
            }
            svg.appendChild(el);
        });
        return svg;
    }

    var eyeOpenPaths = [
        {d: 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z'},
        {tag: 'circle', cx: '12', cy: '12', r: '3'}
    ];
    var eyeClosedPaths = [
        {d: 'M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24'},
        {tag: 'line', x1: '1', y1: '1', x2: '23', y2: '23'}
    ];

    document.querySelectorAll('.password-toggle').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var input = document.getElementById(this.dataset.target);
            var isHidden = input.type === 'password';
            input.type = isHidden ? 'text' : 'password';
            this.replaceChildren(createSvgIcon(isHidden ? eyeClosedPaths : eyeOpenPaths));
            this.title = isHidden
                ? ((typeof archieI18n !== 'undefined') ? archieI18n.t('login.hide_password', 'Hide password') : 'Hide password')
                : ((typeof archieI18n !== 'undefined') ? archieI18n.t('login.show_password', 'Show password') : 'Show password');
        });
    });

    // ═══════════════════════════════════════════════════════════════════════
    // Language Dropdown
    // ═══════════════════════════════════════════════════════════════════════
    var LANG_LABELS = { en: 'EN', fr: 'FR', es: 'ES', pt: 'PT', de: 'DE', zh: '中文', ar: 'عر', he: 'עב' };
    var langBtn = document.getElementById('langToggle');
    var langMenu = document.getElementById('langMenu');

    function syncLangUI(lang) {
        if (langBtn) {
            var span = langBtn.querySelector('span');
            if (span) span.textContent = LANG_LABELS[lang] || lang.toUpperCase();
        }
        if (langMenu) {
            langMenu.querySelectorAll('.lang-dropdown-item').forEach(function(o) {
                o.classList.toggle('active', o.getAttribute('data-lang') === lang);
            });
        }
    }

    if (langMenu) {
        langMenu.querySelectorAll('.lang-dropdown-item').forEach(function(opt) {
            opt.addEventListener('click', function() {
                var lang = opt.getAttribute('data-lang');
                if (window.archieI18n) archieI18n.switchLanguage(lang);
                syncLangUI(lang);
                langMenu.classList.add('hidden');
            });
        });
    }

    // Close dropdown on outside click
    document.addEventListener('click', function(e) {
        if (langMenu && !langMenu.classList.contains('hidden') &&
            !langMenu.contains(e.target) && e.target !== langBtn && !langBtn.contains(e.target)) {
            langMenu.classList.add('hidden');
        }
    });

    // ═══════════════════════════════════════════════════════════════════════
    // i18n Init
    // ═══════════════════════════════════════════════════════════════════════
    if (typeof archieI18n !== 'undefined') {
        archieI18n.init();
        setTimeout(function() { syncLangUI(archieI18n.getCurrentLanguage()); }, 500);
    }
})();
