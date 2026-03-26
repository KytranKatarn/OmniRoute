/* app.js — Entry point for creed-ai.org
 * Dependencies: Lenis, gsap, ScrollTrigger (globals), Effects, Nav, Transitions
 */

document.addEventListener('DOMContentLoaded', function () {
    'use strict';

    /* ---- Lenis Smooth Scroll ---- */
    var lenis = null;
    if (typeof Lenis !== 'undefined') {
        lenis = new Lenis({
            duration: 1.2,
            easing: function (t) {
                return 1 - Math.pow(1 - t, 3);
            },
            smoothWheel: true
        });

        function raf(time) {
            lenis.raf(time);
            requestAnimationFrame(raf);
        }
        requestAnimationFrame(raf);

        if (typeof gsap !== 'undefined' && typeof ScrollTrigger !== 'undefined') {
            lenis.on('scroll', ScrollTrigger.update);
            gsap.ticker.add(function (time) {
                lenis.raf(time * 1000);
            });
            gsap.ticker.lagSmoothing(0);
        }
    }

    /* ---- Core Initialization ---- */
    Nav.init();
    Effects.init();
    Transitions.init();

    /* ---- Page-Specific Init ---- */
    var page = document.querySelector('[data-barba-namespace]');
    var namespace = page ? page.getAttribute('data-barba-namespace') : '';

    switch (namespace) {
        case 'home':
            // Particle canvas init will go here
            break;
        case 'manifesto':
            if (typeof Manifesto !== 'undefined' && typeof Manifesto.init === 'function') Manifesto.init();
            break;
        case 'governance':
            if (typeof Governance !== 'undefined' && typeof Governance.init === 'function') Governance.init();
            break;
    }
});
