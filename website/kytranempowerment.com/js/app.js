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

        // Drive Lenis from exactly ONE loop. gsap.ticker already runs on
        // requestAnimationFrame internally, so when GSAP is present it is
        // the sole driver (and keeps ScrollTrigger in sync). Running BOTH
        // a native rAF loop AND gsap.ticker double-updates Lenis's scroll
        // interpolation every frame — the two timing sources fight each
        // other, which is what made scrolling feel stuttery/inconsistent.
        if (typeof gsap !== 'undefined' && typeof ScrollTrigger !== 'undefined') {
            lenis.on('scroll', ScrollTrigger.update);
            gsap.ticker.add(function (time) {
                lenis.raf(time * 1000);
            });
            gsap.ticker.lagSmoothing(0);
        } else {
            function raf(time) {
                lenis.raf(time);
                requestAnimationFrame(raf);
            }
            requestAnimationFrame(raf);
        }
    }

    /* ---- Core Initialization ---- */
    Nav.init();
    if (typeof AmbientBackground !== 'undefined' && typeof AmbientBackground.init === 'function') AmbientBackground.init();
    I18n.init();
    Effects.init();
    Transitions.init();

    initPageScripts();
});

/* ---- Page-Specific Init ----
 * A plain global function (not wrapped in the DOMContentLoaded closure) so
 * Transitions.js can call it again from Barba's `after` hook. Barba swaps
 * the container's HTML without re-firing DOMContentLoaded or executing any
 * inline <script> tags inside the swapped content, so a page whose dynamic
 * content only ran here once would stay blank on every in-app nav-link
 * transition into it and only work on a hard page load. This dispatch is
 * what makes a Barba-arrival re-run the right page module.
 */
function initPageScripts() {
    'use strict';
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
        case 'store':
            if (typeof Store !== 'undefined' && typeof Store.init === 'function') Store.init();
            break;
        case 'product-detail':
            if (typeof ProductDetail !== 'undefined' && typeof ProductDetail.init === 'function') ProductDetail.init();
            break;
        case 'cart':
            if (typeof CartPage !== 'undefined' && typeof CartPage.init === 'function') CartPage.init();
            break;
        case 'checkout':
            if (typeof CheckoutPage !== 'undefined' && typeof CheckoutPage.init === 'function') CheckoutPage.init();
            break;
        case 'order-success':
            if (typeof OrderSuccess !== 'undefined' && typeof OrderSuccess.init === 'function') OrderSuccess.init();
            break;
    }

    if (typeof KECart !== 'undefined') KECart.updateCartBadges();
}
