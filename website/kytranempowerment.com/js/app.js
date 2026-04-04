/* app.js — Entry point for kytranempowerment.com
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
                // Custom ease-out cubic
                return 1 - Math.pow(1 - t, 3);
            },
            smoothWheel: true
        });

        // RAF loop
        function raf(time) {
            lenis.raf(time);
            requestAnimationFrame(raf);
        }
        requestAnimationFrame(raf);

        // Connect Lenis to GSAP ScrollTrigger
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
    I18n.init();
    Effects.init();
    Transitions.init();

    /* ---- Page-Specific Init ---- */
    var page = document.querySelector('[data-barba-namespace]');
    var namespace = page ? page.getAttribute('data-barba-namespace') : '';

    switch (namespace) {
        case 'home':
            if (typeof Hero !== 'undefined' && typeof Hero.init === 'function') Hero.init();
            if (typeof HeroAnimations !== 'undefined' && typeof HeroAnimations.init === 'function') HeroAnimations.init();
            break;
        case 'directory':
            if (typeof Directory !== 'undefined' && typeof Directory.init === 'function') Directory.init();
            break;
        case 'compliance':
            if (typeof Compliance !== 'undefined' && typeof Compliance.init === 'function') Compliance.init();
            break;
    }
});
