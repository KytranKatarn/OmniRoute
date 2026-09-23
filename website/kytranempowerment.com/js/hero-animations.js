/* ==========================================================================
   Hero Animations — Cinematic entrance, starfield, counter, scroll reveals
   Dependencies: gsap, ScrollTrigger, Splitting (globals)
   ========================================================================== */

var HeroAnimations = (function () {
    'use strict';

    var _particleCanvas = null;
    var _particleCtx = null;
    var _particles = [];
    var _particleRaf = null;
    var _heroRect = null;
    var _isVisible = true;
    var _scrollLogo = null;
    var _scrollRaf = null;
    var _scrollHandler = null;

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

        initParticles(hero);
        initScrollAmbient();
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
       Animation 2: Constellation Network (2D Canvas)
       70 nodes drifting with cyan connecting edges within 140px — ports the
       design's startCanvas() algorithm 1:1 (Home.dc.html).
       ==================================================================== */
    function initParticles() {
        // Skip on mobile for performance
        if (window.matchMedia('(max-width: 768px)').matches) return;

        _particleCanvas = document.getElementById('scrollParticles');
        if (!_particleCanvas) return;

        _particleCtx = _particleCanvas.getContext('2d');
        _heroRect = { width: window.innerWidth, height: window.innerHeight };

        _resizeCanvas();
        window.addEventListener('resize', _resizeCanvas);

        document.addEventListener('visibilitychange', function () {
            if (document.hidden) {
                _isVisible = false;
                if (_particleRaf) {
                    cancelAnimationFrame(_particleRaf);
                    _particleRaf = null;
                }
            } else {
                _isVisible = true;
                if (!_particleRaf) _animateParticles();
            }
        });

        var count = 70;
        for (var i = 0; i < count; i++) {
            _particles.push({
                x: Math.random() * _heroRect.width,
                y: Math.random() * _heroRect.height,
                vx: (Math.random() - 0.5) * 0.35,
                vy: (Math.random() - 0.5) * 0.35
            });
        }

        _animateParticles();
    }

    function initScrollAmbient() {
        _scrollLogo = document.getElementById('scrollLogo');
        if (!_scrollLogo) return;

        _scrollHandler = function () {
            if (_scrollRaf) return;
            _scrollRaf = requestAnimationFrame(function () {
                _scrollRaf = null;
                var maxScroll = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
                var scrollY = window.scrollY || window.pageYOffset || 0;
                var progress = Math.min(Math.max(scrollY / maxScroll, 0), 1);
                _scrollLogo.style.setProperty('--scroll-shift', (progress * 120) + 'px');
                _scrollLogo.style.setProperty('--scroll-scale', (1 + progress * 0.08).toFixed(3));
                _scrollLogo.style.setProperty('--scroll-rotate', ((progress * 2 - 1) * 0.8).toFixed(2) + 'deg');
                _scrollLogo.style.opacity = (0.07 - progress * 0.025).toFixed(3);
            });
        };

        window.addEventListener('scroll', _scrollHandler, { passive: true });
        _scrollHandler();
    }

    function _resizeCanvas() {
        if (!_particleCanvas) return;
        var dpr = Math.min(window.devicePixelRatio, 2);
        var width = window.innerWidth;
        var height = window.innerHeight;
        _particleCanvas.width = width * dpr;
        _particleCanvas.height = height * dpr;
        _particleCanvas.style.width = width + 'px';
        _particleCanvas.style.height = height + 'px';
        _particleCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
        _heroRect = { width: width, height: height };
        if (_scrollHandler) _scrollHandler();
    }

    function _animateParticles() {
        if (!_isVisible || !_particleCtx || !_heroRect) return;

        var w = _heroRect.width;
        var h = _heroRect.height;
        var nodes = _particles;
        var n = nodes.length;

        _particleCtx.clearRect(0, 0, w, h);

        for (var i = 0; i < n; i++) {
            var node = nodes[i];
            node.x += node.vx;
            node.y += node.vy;
            if (node.x < 0 || node.x > w) node.vx *= -1;
            if (node.y < 0 || node.y > h) node.vy *= -1;
        }

        for (var a = 0; a < n; a++) {
            for (var b = a + 1; b < n; b++) {
                var na = nodes[a], nb = nodes[b];
                var d = Math.hypot(na.x - nb.x, na.y - nb.y);
                if (d < 140) {
                    _particleCtx.strokeStyle = 'rgba(0,229,255,' + ((1 - d / 140) * 0.25) + ')';
                    _particleCtx.lineWidth = 1;
                    _particleCtx.beginPath();
                    _particleCtx.moveTo(na.x, na.y);
                    _particleCtx.lineTo(nb.x, nb.y);
                    _particleCtx.stroke();
                }
            }
        }

        for (var j = 0; j < n; j++) {
            var p = nodes[j];
            _particleCtx.fillStyle = 'rgba(0,229,255,0.7)';
            _particleCtx.beginPath();
            _particleCtx.arc(p.x, p.y, 1.6, 0, Math.PI * 2);
            _particleCtx.fill();
        }

        _particleRaf = requestAnimationFrame(_animateParticles);
    }

    /* ====================================================================
       Animation 3: Stats Counter with Glow
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
       Animation 4: Scroll-Triggered Section Reveals
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
        if (_scrollHandler) {
            window.removeEventListener('scroll', _scrollHandler);
            _scrollHandler = null;
        }
        if (_scrollRaf) {
            cancelAnimationFrame(_scrollRaf);
            _scrollRaf = null;
        }
        window.removeEventListener('resize', _resizeCanvas);
        if (_particleRaf) {
            cancelAnimationFrame(_particleRaf);
            _particleRaf = null;
        }
        _scrollLogo = null;
        _particles = [];
        _particleCanvas = null;
        _particleCtx = null;
    }

    return {
        init: init,
        destroy: destroy
    };
})();
