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
    var _scrollY = 0;
    var _heroRect = null;
    var _isVisible = true;

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
        initEntrance(hero);
        initStatsCounter();
        initScrollReveals();
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
       Animation 2: Particle Starfield (2D Canvas)
       ==================================================================== */
    function initParticles(hero) {
        // Skip on mobile for performance
        if (window.matchMedia('(max-width: 768px)').matches) return;

        _particleCanvas = document.getElementById('heroParticles');
        if (!_particleCanvas) return;

        _particleCtx = _particleCanvas.getContext('2d');
        _heroRect = hero.getBoundingClientRect();

        // Size canvas
        _resizeCanvas();
        window.addEventListener('resize', _resizeCanvas);

        // Track scroll for parallax
        window.addEventListener('scroll', function () {
            _scrollY = window.pageYOffset || document.documentElement.scrollTop;
        }, { passive: true });

        // Visibility API: pause when tab is hidden
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

        // Create particles
        var count = 100;
        for (var i = 0; i < count; i++) {
            _particles.push({
                x: Math.random() * _particleCanvas.width,
                y: Math.random() * _particleCanvas.height,
                size: 1 + Math.random() * 2,
                speedX: (Math.random() - 0.5) * 0.4,
                speedY: (Math.random() - 0.5) * 0.4,
                opacity: 0.1 + Math.random() * 0.5,
                baseOpacity: 0.1 + Math.random() * 0.5,
                twinkleSpeed: 0.005 + Math.random() * 0.015,
                twinklePhase: Math.random() * Math.PI * 2,
                isCyan: Math.random() > 0.7
            });
        }

        // Start animation loop
        _animateParticles();
    }

    function _resizeCanvas() {
        if (!_particleCanvas) return;
        var hero = _particleCanvas.parentElement;
        if (!hero) return;
        var dpr = Math.min(window.devicePixelRatio, 2);
        var rect = hero.getBoundingClientRect();
        _particleCanvas.width = rect.width * dpr;
        _particleCanvas.height = rect.height * dpr;
        _particleCanvas.style.width = rect.width + 'px';
        _particleCanvas.style.height = rect.height + 'px';
        _particleCtx.scale(dpr, dpr);
        _heroRect = rect;
    }

    function _animateParticles() {
        if (!_isVisible || !_particleCtx || !_heroRect) return;

        var w = _heroRect.width;
        var h = _heroRect.height;

        _particleCtx.clearRect(0, 0, w, h);

        // Parallax offset based on scroll
        var parallaxY = _scrollY * 0.15;

        for (var i = 0; i < _particles.length; i++) {
            var p = _particles[i];

            // Move
            p.x += p.speedX;
            p.y += p.speedY;

            // Wrap around edges
            if (p.x < -5) p.x = w + 5;
            if (p.x > w + 5) p.x = -5;
            if (p.y < -5) p.y = h + 5;
            if (p.y > h + 5) p.y = -5;

            // Twinkle
            p.twinklePhase += p.twinkleSpeed;
            p.opacity = p.baseOpacity + Math.sin(p.twinklePhase) * 0.2;
            if (p.opacity < 0.05) p.opacity = 0.05;
            if (p.opacity > 0.7) p.opacity = 0.7;

            // Draw with parallax offset
            var drawY = p.y - parallaxY % h;
            if (drawY < 0) drawY += h;

            _particleCtx.beginPath();
            _particleCtx.arc(p.x, drawY, p.size, 0, Math.PI * 2);
            if (p.isCyan) {
                _particleCtx.fillStyle = 'rgba(0, 229, 255, ' + p.opacity + ')';
            } else {
                _particleCtx.fillStyle = 'rgba(255, 255, 255, ' + p.opacity + ')';
            }
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
        if (_particleRaf) {
            cancelAnimationFrame(_particleRaf);
            _particleRaf = null;
        }
        _particles = [];
        _particleCanvas = null;
        _particleCtx = null;
    }

    return {
        init: init,
        destroy: destroy
    };
})();
