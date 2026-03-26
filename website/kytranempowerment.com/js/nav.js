/* nav.js — Navigation controller for kytranempowerment.com */

var Nav = (function () {
    'use strict';

    var menuToggle, navLinks, langSwitcher, langOverlay;

    function toggleMenu() {
        if (!navLinks || !menuToggle) return;
        navLinks.classList.toggle('nav__links--open');
        menuToggle.classList.toggle('nav__menu-btn--active');
    }

    function toggleLangOverlay() {
        if (!langOverlay) return;
        if (langOverlay.hidden) {
            langOverlay.hidden = false;
        } else {
            langOverlay.hidden = true;
        }
    }

    function closeLangOverlay() {
        if (langOverlay) langOverlay.hidden = true;
    }

    function highlightActive() {
        var path = window.location.pathname;
        var links = document.querySelectorAll('.nav__link');
        links.forEach(function (link) {
            var href = link.getAttribute('href');
            // Match exact path or filename
            if (href === path || path.endsWith('/' + href) || (href === '/' && (path === '/' || path === '/index.html'))) {
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });
    }

    function _bindLangButtons() {
        var buttons = document.querySelectorAll('[data-lang]');
        buttons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var lang = btn.getAttribute('data-lang');
                // Mark active button
                buttons.forEach(function (b) { b.classList.remove('active'); });
                btn.classList.add('active');
                // Call Translate if available
                if (typeof Translate !== 'undefined' && typeof Translate.setLanguage === 'function') {
                    Translate.setLanguage(lang);
                }
                closeLangOverlay();
            });
        });
    }

    function init() {
        menuToggle = document.getElementById('menuToggle');
        navLinks = document.getElementById('navLinks');
        langSwitcher = document.getElementById('langSwitcher');
        langOverlay = document.getElementById('langOverlay');

        if (menuToggle) menuToggle.addEventListener('click', toggleMenu);
        if (langSwitcher) langSwitcher.addEventListener('click', toggleLangOverlay);

        // Close overlay when clicking outside the panel
        if (langOverlay) {
            langOverlay.addEventListener('click', function (e) {
                if (e.target === langOverlay) closeLangOverlay();
            });
        }

        _bindLangButtons();
        highlightActive();
    }

    return {
        init: init,
        toggleMenu: toggleMenu,
        toggleLangOverlay: toggleLangOverlay,
        closeLangOverlay: closeLangOverlay,
        highlightActive: highlightActive
    };
})();
