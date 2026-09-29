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
                    // Scroll to top. `window.scrollTo` alone desyncs Lenis:
                    // Lenis tracks its own internal scroll position and drives
                    // the real one from it, so jumping the native scrollTop
                    // out from under it leaves Lenis's target stale — the next
                    // wheel/touch input resumes from that stale value, which
                    // is what made scrolling feel broken/unresponsive after
                    // any in-app nav-link transition (every page after the
                    // first). `resize()` also recomputes Lenis's scroll limit
                    // for the arriving page's (likely different) height.
                    if (window.__lenis) {
                        window.__lenis.resize();
                        window.__lenis.scrollTo(0, { immediate: true });
                    } else {
                        window.scrollTo(0, 0);
                    }
                }
            }]
        });
    }

    return {
        init: init
    };
})();
