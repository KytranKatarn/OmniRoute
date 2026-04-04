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
    }

    return {
        init: init,
        closeMobile: closeMobile
    };
})();
