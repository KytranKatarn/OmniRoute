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
        var nav = document.getElementById('mainNav');
        if (nav) nav.classList.toggle('nav--menu-open');
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

    function closeMenu() {
        if (!navLinks || !menuToggle) return;
        navLinks.classList.remove('nav__links--open');
        menuToggle.classList.remove('is-open');
        var nav = document.getElementById('mainNav');
        if (nav) nav.classList.remove('nav--menu-open');
    }

    function init() {
        menuToggle = document.getElementById('menuToggle');
        navLinks = document.getElementById('navLinks');

        if (menuToggle) menuToggle.addEventListener('click', toggleMenu);

        // Close menu when any nav link is clicked
        if (navLinks) {
            navLinks.querySelectorAll('.nav__link').forEach(function (link) {
                link.addEventListener('click', closeMenu);
            });
        }

        _bindScroll();
        highlightActive();
    }

    return {
        init: init,
        toggleMenu: toggleMenu,
        highlightActive: highlightActive
    };
})();
