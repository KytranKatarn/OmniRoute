/* nav.js — Navigation controller for creed-ai.org
 * Simplified: no language switcher (English-only for grant readiness)
 */

var Nav = (function () {
    'use strict';

    var menuToggle, navLinks;

    function toggleMenu() {
        if (!navLinks || !menuToggle) return;
        navLinks.classList.toggle('nav__links--open');
        menuToggle.classList.toggle('is-open');
    }

    function highlightActive() {
        var path = window.location.pathname;
        var links = document.querySelectorAll('.nav__link');
        links.forEach(function (link) {
            var href = link.getAttribute('href');
            if (href === path || path.endsWith('/' + href) || (href === '/' && (path === '/' || path === '/index.html'))) {
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });
    }

    /* ---- Scroll-aware nav background ---- */
    function _bindScroll() {
        var nav = document.getElementById('mainNav');
        if (!nav) return;
        window.addEventListener('scroll', function () {
            if (window.scrollY > 40) {
                nav.classList.add('nav--scrolled');
            } else {
                nav.classList.remove('nav--scrolled');
            }
        }, { passive: true });
    }

    function init() {
        menuToggle = document.getElementById('menuToggle');
        navLinks = document.getElementById('navLinks');

        if (menuToggle) menuToggle.addEventListener('click', toggleMenu);

        _bindScroll();
        highlightActive();
    }

    return {
        init: init,
        toggleMenu: toggleMenu,
        highlightActive: highlightActive
    };
})();
