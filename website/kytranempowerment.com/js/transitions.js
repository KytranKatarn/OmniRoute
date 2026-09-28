/* transitions.js — Barba.js page transitions for kytranempowerment.com
 * Dependencies: barba (global), gsap (global), Effects, Nav
 */

var Transitions = (function () {
    'use strict';

    function init() {
        if (typeof barba === 'undefined') return;

        barba.init({
            prefetchIgnore: '/api',
            transitions: [{
                name: 'lcars-sweep',

                leave: function (data) {
                    return gsap.to(data.current.container, {
                        opacity: 0,
                        x: -50,
                        duration: 0.4,
                        ease: 'power2.in'
                    });
                },

                enter: function (data) {
                    gsap.set(data.next.container, { opacity: 0, x: 50 });
                    return gsap.to(data.next.container, {
                        opacity: 1,
                        x: 0,
                        duration: 0.4,
                        ease: 'power2.out'
                    });
                },

                after: function () {
                    // Reinitialize effects and navigation for the new page
                    Effects.init();
                    Nav.highlightActive();
                    // Re-run the arriving page's own dynamic init (app.js) —
                    // Barba swaps the container's HTML without re-firing
                    // DOMContentLoaded or executing inline <script> tags, so
                    // this is the only place a client-side nav transition
                    // re-triggers a page's data fetch/render logic.
                    if (typeof initPageScripts === 'function') initPageScripts();
                    // Scroll to top
                    window.scrollTo(0, 0);
                }
            }]
        });
    }

    return {
        init: init
    };
})();
