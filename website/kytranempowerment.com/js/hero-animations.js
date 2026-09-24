/* ==========================================================================
   Hero Animations — Cinematic entrance, counter, scroll reveals
   Dependencies: gsap, ScrollTrigger, Splitting (globals)
   The constellation canvas + ram-mark watermark moved to
   ambient-background.js (page-independent, no .hero required, loaded on
   every page) — this file now owns only the hero-section-specific pieces.
   ========================================================================== */

var HeroAnimations = (function () {
    'use strict';

    /* ====================================================================
       Public: init
       ==================================================================== */
    function init() {
        // Respect reduced motion
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            _showContentImmediately();
            return;
        }

        var hero = document.querySelector('.hero');
        if (!hero) return;

        initEntrance(hero);
        initScrollReveals();

        // Fetch live agent count before counter animation — 1.5s timeout fallback
        _fetchAgentCount().then(function () { initStatsCounter(); });
    }

    function _fetchAgentCount() {
        var el = document.querySelector('.hero__stat-number[data-count]');
        if (!el) return Promise.resolve();
        var timeout = new Promise(function (res) { setTimeout(res, 1500); });
        var req = fetch('https://platform.kytranempowerment.com/api/public/directory')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var count = d && d.summary && d.summary.total;
                if (count && count > 0) { el.setAttribute('data-count', count); }
            })
            .catch(function () {});
        return Promise.race([req, timeout]);
    }

    /* ====================================================================
       Animation 1: Cinematic Entrance
       ==================================================================== */
    function initEntrance(hero) {
        if (typeof gsap === 'undefined') return;

        // Mark hero for CSS initial-hidden states
        hero.classList.add('hero--animating');

        var tl = gsap.timeline({ delay: 0.3 });

        // --- Logo glow (nav logo) ---
        var logo = document.querySelector('.nav__logo-img');
        if (logo) {
            gsap.set(logo, { scale: 0.3, opacity: 0 });
            tl.to(logo, {
                scale: 1,
                opacity: 1,
                duration: 0.6,
                ease: 'elastic.out(1, 0.5)',
                onComplete: function () {
                    logo.classList.add('logo-entrance');
                }
            }, 0);
        }

        // --- Title: use Splitting.js for char-by-char reveal ---
        var title = hero.querySelector('.hero__title');
        if (title) {
            // Remove the scramble behavior — we'll do char animation instead
            var scrambleText = title.getAttribute('data-scramble');
            if (scrambleText) {
                // Clear existing content, set visible text for Splitting
                title.removeAttribute('data-scramble');
                var hiddenSpan = title.querySelector('.visually-hidden');
                if (hiddenSpan) hiddenSpan.remove();
                title.textContent = scrambleText;

                // Split into chars with Splitting.js
                if (typeof Splitting !== 'undefined') {
                    Splitting({ target: title, by: 'chars' });
                    var chars = title.querySelectorAll('.char');
                    if (chars.length) {
                        gsap.set(chars, { opacity: 0, y: 40 });
                        tl.to(chars, {
                            opacity: 1,
                            y: 0,
                            duration: 0.5,
                            ease: 'power3.out',
                            stagger: 0.03
                        }, 0.3);
                    }
                } else {
                    // Fallback: simple fade-up
                    tl.to(title, {
                        opacity: 1,
                        y: 0,
                        duration: 0.6,
                        ease: 'power2.out'
                    }, 0.3);
                }
            }
        }

        // --- Tagline ---
        var tagline = hero.querySelector('.hero__tagline');
        if (tagline) {
            tl.to(tagline, {
                opacity: 1,
                y: 0,
                duration: 0.6,
                ease: 'power2.out'
            }, 1.0);
        }

        // --- Stats ---
        var stats = hero.querySelector('.hero__stats');
        var statItems = hero.querySelectorAll('.hero__stat');
        if (stats && statItems.length) {
            tl.to(stats, {
                opacity: 1,
                scale: 1,
                duration: 0.4,
                ease: 'power2.out'
            }, 1.3);
            tl.to(statItems, {
                opacity: 1,
                scale: 1,
                duration: 0.5,
                ease: 'back.out(1.4)',
                stagger: 0.12
            }, 1.3);
        }

        // --- CTA buttons ---
        var cta = hero.querySelector('.hero__cta');
        if (cta) {
            tl.to(cta, {
                opacity: 1,
                y: 0,
                duration: 0.5,
                ease: 'power2.out'
            }, 1.6);
        }
    }

    /* ====================================================================
       Animation 2: Stats Counter with Glow
       ==================================================================== */
    function initStatsCounter() {
        if (typeof gsap === 'undefined' || typeof ScrollTrigger === 'undefined') return;

        // Target hero stat numbers specifically (not mission stats which effects.js handles)
        var statNumbers = document.querySelectorAll('.hero__stat-number[data-count]');
        if (!statNumbers.length) return;

        statNumbers.forEach(function (el) {
            var target = parseInt(el.getAttribute('data-count'), 10);
            if (isNaN(target)) return;

            // Prevent effects.js from also animating these — remove data-count temporarily
            // and re-apply after our animation
            var countVal = el.getAttribute('data-count');
            el.removeAttribute('data-count');

            var obj = { val: 0 };
            ScrollTrigger.create({
                trigger: el,
                start: 'top 80%',
                once: true,
                onEnter: function () {
                    gsap.to(obj, {
                        val: target,
                        duration: 1.5,
                        ease: 'power2.out',
                        snap: { val: 1 },
                        onUpdate: function () {
                            var v = Math.round(obj.val);
                            el.textContent = v >= 1000 ? v.toLocaleString() : v;
                        },
                        onComplete: function () {
                            el.textContent = target >= 1000 ? target.toLocaleString() : target;
                            el.classList.add('glow-pulse');
                            // Restore data-count for any external code that might read it
                            el.setAttribute('data-count', countVal);
                        }
                    });
                }
            });
        });
    }

    /* ====================================================================
       Animation 3: Scroll-Triggered Section Reveals
       ==================================================================== */
    function initScrollReveals() {
        if (typeof gsap === 'undefined' || typeof ScrollTrigger === 'undefined') return;
        gsap.registerPlugin(ScrollTrigger);

        var sections = document.querySelectorAll('.reveal-section');
        if (!sections.length) return;

        sections.forEach(function (section) {
            ScrollTrigger.create({
                trigger: section,
                start: 'top 85%',
                once: true,
                onEnter: function () {
                    gsap.to(section, {
                        opacity: 1,
                        y: 0,
                        duration: 0.8,
                        ease: 'power2.out',
                        onComplete: function () {
                            section.classList.add('is-visible');
                        }
                    });

                    // Stagger child cards/items within section
                    var children = section.querySelectorAll('.card, .glass-panel, .faq-item, .testimonial-card');
                    if (children.length) {
                        gsap.from(children, {
                            opacity: 0,
                            y: 25,
                            duration: 0.5,
                            ease: 'power2.out',
                            stagger: 0.1,
                            delay: 0.2
                        });
                    }
                }
            });
        });

        // Safety net: if ScrollTrigger hasn't revealed sections after 3s, force-show them
        setTimeout(function () {
            sections.forEach(function (section) {
                if (!section.classList.contains('is-visible')) {
                    section.style.opacity = '1';
                    section.style.transform = 'none';
                    section.classList.add('is-visible');
                }
            });
        }, 3000);
    }

    /* ====================================================================
       Helpers
       ==================================================================== */
    function _showContentImmediately() {
        // For reduced-motion: ensure everything is visible
        var hero = document.querySelector('.hero');
        if (hero) hero.classList.remove('hero--animating');

        document.querySelectorAll('.reveal-section').forEach(function (el) {
            el.classList.add('is-visible');
            el.style.opacity = '1';
            el.style.transform = 'none';
        });
    }

    /* ---- Cleanup (for Barba.js transitions) ---- */
    function destroy() {
        // Nothing to clean up here — entrance/stats/reveals are one-shot
        // ScrollTrigger instances. Persistent state (particles/scroll
        // handlers) lives in AmbientBackground now.
    }

    return {
        init: init,
        destroy: destroy
    };
})();
