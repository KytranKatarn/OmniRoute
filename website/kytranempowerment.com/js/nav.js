/* nav.js — Navigation controller for kytranempowerment.com
 * Handles: hamburger toggle, mobile accordion, desktop dropdowns,
 * language overlay, escape key, active-language highlight.
 */

var Nav = (function () {
    'use strict';

    var menuBtn, navMobile, langOverlay;

    /* ---- Helpers ---- */
    function closeAllDropdowns() {
        var triggers = document.querySelectorAll('.nav__dropdown-trigger');
        triggers.forEach(function (t) { t.setAttribute('aria-expanded', 'false'); });
    }

    function closeMobile() {
        if (!navMobile || !menuBtn) return;
        navMobile.setAttribute('aria-hidden', 'true');
        menuBtn.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
        // Collapse all mobile accordion sections
        var mobileTriggers = navMobile.querySelectorAll('.nav-mobile__trigger');
        mobileTriggers.forEach(function (t) { t.setAttribute('aria-expanded', 'false'); });
    }

    function closeLangOverlay() {
        if (langOverlay) langOverlay.hidden = true;
    }

    /* ---- Hamburger toggle ---- */
    function toggleMobile() {
        if (!navMobile || !menuBtn) return;
        var isOpen = navMobile.getAttribute('aria-hidden') === 'false';
        if (isOpen) {
            closeMobile();
        } else {
            navMobile.setAttribute('aria-hidden', 'false');
            menuBtn.setAttribute('aria-expanded', 'true');
            document.body.style.overflow = 'hidden';
        }
    }

    /* ---- Mobile accordion ---- */
    function bindMobileAccordion() {
        var triggers = document.querySelectorAll('.nav-mobile__trigger');
        triggers.forEach(function (trigger) {
            trigger.addEventListener('click', function () {
                var expanded = trigger.getAttribute('aria-expanded') === 'true';
                trigger.setAttribute('aria-expanded', expanded ? 'false' : 'true');
            });
        });

        // Close mobile nav when any link inside is clicked
        if (navMobile) {
            navMobile.addEventListener('click', function (e) {
                if (e.target.tagName === 'A') {
                    closeMobile();
                }
            });
        }
    }

    /* ---- Desktop dropdowns ---- */
    function bindDesktopDropdowns() {
        var triggers = document.querySelectorAll('.nav__dropdown-trigger');
        triggers.forEach(function (trigger) {
            trigger.addEventListener('click', function (e) {
                e.stopPropagation();
                var expanded = trigger.getAttribute('aria-expanded') === 'true';
                // Close all other dropdowns first
                closeAllDropdowns();
                if (!expanded) {
                    trigger.setAttribute('aria-expanded', 'true');
                }
            });
        });

        // Click outside closes all dropdowns
        document.addEventListener('click', function (e) {
            if (!e.target.closest('.nav__dropdown')) {
                closeAllDropdowns();
            }
        });
    }

    /* ---- Language overlay ---- */
    function bindLangOverlay() {
        var langBtn = document.querySelector('.nav__lang-btn');
        var closeBtn = langOverlay ? langOverlay.querySelector('.lang-overlay__close') : null;

        if (langBtn) {
            langBtn.addEventListener('click', function () {
                if (!langOverlay) return;
                langOverlay.hidden = !langOverlay.hidden;
            });
        }

        if (closeBtn) {
            closeBtn.addEventListener('click', closeLangOverlay);
        }

        // Click outside panel closes overlay
        if (langOverlay) {
            langOverlay.addEventListener('click', function (e) {
                if (e.target === langOverlay) closeLangOverlay();
            });
        }
    }

    /* ---- Language selection ---- */
    function bindLangButtons() {
        var buttons = document.querySelectorAll('.lang-overlay__btn');
        buttons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var lang = btn.getAttribute('data-lang');
                // Mark active
                buttons.forEach(function (b) { b.classList.remove('active'); });
                btn.classList.add('active');
                // Dispatch to i18n system
                if (typeof window.I18n !== 'undefined' && typeof window.I18n.setLang === 'function') {
                    window.I18n.setLang(lang);
                } else if (typeof Translate !== 'undefined' && typeof Translate.setLanguage === 'function') {
                    Translate.setLanguage(lang);
                }
                // Persist choice
                try { localStorage.setItem('ke-lang', lang); } catch (e) { /* noop */ }
                closeLangOverlay();
            });
        });
    }

    /* ---- Active language highlight ---- */
    function highlightActiveLang() {
        var lang;
        try { lang = localStorage.getItem('ke-lang'); } catch (e) { /* noop */ }
        if (!lang) return;
        var buttons = document.querySelectorAll('.lang-overlay__btn');
        buttons.forEach(function (btn) {
            if (btn.getAttribute('data-lang') === lang) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }

    /* ---- Escape key ---- */
    function bindEscape() {
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                closeMobile();
                closeAllDropdowns();
                closeLangOverlay();
            }
        });
    }

    /* ---- Scroll shadow + back-to-top ---- */
    function bindScroll() {
        var navEl = document.querySelector('.nav');
        var topBtn = document.getElementById('backToTop');
        if (!navEl && !topBtn) return;

        function reposition() {
            if (!topBtn) return;
            var consented = false;
            try { consented = !!localStorage.getItem('ke-cookie-consent'); } catch (e) { /* noop */ }
            var banner = document.getElementById('cookieConsent');
            var bannerShown = banner && banner.style.display !== 'none' && !consented;
            topBtn.style.bottom = bannerShown ? '6rem' : '1.5rem';
        }

        function onScroll() {
            var y = window.scrollY || document.documentElement.scrollTop;
            if (navEl) navEl.classList.toggle('nav--scrolled', y > 40);
            if (topBtn) topBtn.classList.toggle('back-to-top--visible', y > 500);
            reposition();
        }

        window.addEventListener('scroll', onScroll, { passive: true });
        onScroll();

        if (topBtn) {
            topBtn.addEventListener('click', function () {
                window.scrollTo({ top: 0, behavior: 'smooth' });
            });
        }
    }

    /* ---- Page fade-in on mount ---- */
    function fadeInPage() {
        var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (reduceMotion) return;
        document.body.style.transition = 'opacity 0.35s ease';
        document.body.style.opacity = '0';
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                document.body.style.opacity = '1';
            });
        });
    }

    /* ---- Cart badge (design Nav: hidden when empty; reads the backend cart) ---- */
    function bindCartBadge() {
        var actions = document.querySelector('.nav__actions');
        if (!actions) return;

        var link = document.createElement('a');
        link.href = 'cart.html';
        link.className = 'nav__cart-link';
        link.title = 'Cart';
        link.setAttribute('hidden', '');
        link.innerHTML = 'Cart <span class="nav__cart-badge">0</span>';
        var cta = actions.querySelector('.nav__link--cta');
        actions.insertBefore(link, cta || actions.querySelector('.nav__menu-btn'));
        var badge = link.querySelector('.nav__cart-badge');
        var timer = null;

        function refresh() {
            var sid = null;
            try { sid = localStorage.getItem('userSessionId'); } catch (e) {}
            if (!sid) { link.setAttribute('hidden', ''); return; }
            fetch('https://business.kytranempowerment.com/plugins/store/api/cart/' + sid)
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) {
                    var items = (data && data.cart_items) || [];
                    var count = items.reduce(function (t, i) { return t + (i.quantity || 0); }, 0);
                    if (count > 0) {
                        badge.textContent = String(count);
                        link.removeAttribute('hidden');
                    } else {
                        link.setAttribute('hidden', '');
                    }
                })
                .catch(function () {});
        }

        function start() {
            if (timer === null) { timer = setInterval(refresh, 1500); }
            refresh();
        }
        function stop() {
            if (timer !== null) { clearInterval(timer); timer = null; }
        }

        document.addEventListener('visibilitychange', function () {
            if (document.hidden) stop(); else start();
        });
        window.addEventListener('pageshow', refresh);
        start();
    }

    /* ---- Init ---- */
    function init() {
        menuBtn = document.querySelector('.nav__menu-btn');
        navMobile = document.getElementById('navMobile');
        langOverlay = document.querySelector('.lang-overlay');

        if (menuBtn) menuBtn.addEventListener('click', toggleMobile);

        bindMobileAccordion();
        bindDesktopDropdowns();
        bindLangOverlay();
        bindLangButtons();
        highlightActiveLang();
        bindEscape();
        bindScroll();
        bindCartBadge();
        fadeInPage();
    }

    return {
        init: init,
        closeMobile: closeMobile
    };
})();
