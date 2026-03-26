/* effects.js — Shared visual effects for kytranempowerment.com
 * Dependencies: gsap, ScrollTrigger, Splitting (globals)
 */

var Effects = (function () {
    'use strict';

    var SCRAMBLE_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%&';
    var isTouch = window.matchMedia('(pointer: coarse)').matches;

    /* ---- Cursor Glow ---- */
    function initCursorGlow() {
        if (isTouch) return;
        var glow = document.getElementById('cursorGlow');
        if (!glow) return;
        document.addEventListener('mousemove', function (e) {
            glow.style.left = e.clientX + 'px';
            glow.style.top = e.clientY + 'px';
        });
    }

    /* ---- Magnetic Elements ---- */
    function initMagnetic() {
        if (isTouch) return;
        var els = document.querySelectorAll('.magnetic');
        var strength = 0.3;

        els.forEach(function (el) {
            el.addEventListener('mousemove', function (e) {
                var rect = el.getBoundingClientRect();
                var cx = rect.left + rect.width / 2;
                var cy = rect.top + rect.height / 2;
                var dx = (e.clientX - cx) * strength;
                var dy = (e.clientY - cy) * strength;
                gsap.to(el, { x: dx, y: dy, duration: 0.3, ease: 'power2.out' });
            });

            el.addEventListener('mouseleave', function () {
                gsap.to(el, { x: 0, y: 0, duration: 0.6, ease: 'elastic.out(1, 0.4)' });
            });
        });
    }

    /* ---- Text Scramble ---- */
    function _scrambleElement(el) {
        var finalText = el.getAttribute('data-scramble');
        if (!finalText) return;
        var length = finalText.length;
        var iteration = 0;

        var interval = setInterval(function () {
            var display = '';
            for (var i = 0; i < length; i++) {
                if (finalText[i] === ' ') {
                    display += ' ';
                } else if (i < iteration) {
                    display += finalText[i];
                } else {
                    display += SCRAMBLE_CHARS[Math.floor(Math.random() * SCRAMBLE_CHARS.length)];
                }
            }
            el.textContent = display;
            iteration += 1;
            if (iteration > length) {
                clearInterval(interval);
                el.textContent = finalText;
            }
        }, 40);
    }

    function initScramble() {
        var els = document.querySelectorAll('[data-scramble]');
        if (!els.length) return;

        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    _scrambleElement(entry.target);
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.5 });

        els.forEach(function (el) { observer.observe(el); });
    }

    /* ---- Card / Element Tilt ---- */
    function initTilt() {
        if (isTouch) return;
        var els = document.querySelectorAll('[data-tilt], .card');
        var maxDeg = 8;

        els.forEach(function (el) {
            el.addEventListener('mousemove', function (e) {
                var rect = el.getBoundingClientRect();
                var x = (e.clientX - rect.left) / rect.width - 0.5;  // -0.5 to 0.5
                var y = (e.clientY - rect.top) / rect.height - 0.5;
                var rotateX = -y * maxDeg * 2;  // vertical mouse -> X rotation
                var rotateY = x * maxDeg * 2;   // horizontal mouse -> Y rotation
                el.style.transform = 'perspective(1000px) rotateX(' + rotateX + 'deg) rotateY(' + rotateY + 'deg)';
            });

            el.addEventListener('mouseleave', function () {
                el.style.transition = 'transform 0.4s ease';
                el.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg)';
                // Remove inline transition after it completes so mousemove isn't sluggish
                setTimeout(function () { el.style.transition = ''; }, 400);
            });
        });
    }

    /* ---- Scroll Reveal (batch stagger + word splitting) ---- */
    function initScrollReveal() {
        if (typeof gsap === 'undefined' || typeof ScrollTrigger === 'undefined') return;
        gsap.registerPlugin(ScrollTrigger);

        // Batch stagger for [data-stagger] children
        var staggerChildren = document.querySelectorAll('[data-stagger] > *');
        if (staggerChildren.length) {
            gsap.set(staggerChildren, { opacity: 0, y: 40 });
            ScrollTrigger.batch(staggerChildren, {
                onEnter: function (batch) {
                    gsap.to(batch, {
                        opacity: 1,
                        y: 0,
                        duration: 0.6,
                        ease: 'power2.out',
                        stagger: 0.1
                    });
                },
                start: 'top 85%'
            });
        }

        // Word-split animation for [data-split]
        var splitEls = document.querySelectorAll('[data-split]');
        if (splitEls.length && typeof Splitting !== 'undefined') {
            splitEls.forEach(function (el) {
                Splitting({ target: el, by: 'words' });
                var words = el.querySelectorAll('.word');
                if (!words.length) return;
                gsap.set(words, { opacity: 0, y: 20 });
                ScrollTrigger.create({
                    trigger: el,
                    start: 'top 85%',
                    once: true,
                    onEnter: function () {
                        gsap.to(words, {
                            opacity: 1,
                            y: 0,
                            duration: 0.5,
                            ease: 'power2.out',
                            stagger: 0.05
                        });
                    }
                });
            });
        }
    }

    /* ---- Count-Up Numbers ---- */
    function initCountUp() {
        if (typeof gsap === 'undefined' || typeof ScrollTrigger === 'undefined') return;

        var els = document.querySelectorAll('[data-count]');
        els.forEach(function (el) {
            var target = parseInt(el.getAttribute('data-count'), 10);
            if (isNaN(target)) return;

            var obj = { val: 0 };
            ScrollTrigger.create({
                trigger: el,
                start: 'top 85%',
                once: true,
                onEnter: function () {
                    gsap.to(obj, {
                        val: target,
                        duration: 1.5,
                        ease: 'power2.out',
                        snap: { val: 1 },
                        onUpdate: function () {
                            el.textContent = Math.round(obj.val);
                        }
                    });
                }
            });
        });
    }

    /* ---- Reduced-Motion Fallback ---- */
    function _applyReducedMotion() {
        // Show scramble text immediately
        document.querySelectorAll('[data-scramble]').forEach(function (el) {
            el.textContent = el.getAttribute('data-scramble');
        });
        // Show count values immediately
        document.querySelectorAll('[data-count]').forEach(function (el) {
            el.textContent = el.getAttribute('data-count');
        });
        // Remove any opacity:0 that would hide content
        document.querySelectorAll('[data-stagger] > *, [data-split] .word').forEach(function (el) {
            el.style.opacity = '1';
            el.style.transform = 'none';
        });
    }

    /* ---- Public Init ---- */
    function init() {
        var prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (prefersReduced) {
            _applyReducedMotion();
            return;
        }
        initCursorGlow();
        initMagnetic();
        initScramble();
        initTilt();
        initScrollReveal();
        initCountUp();
    }

    return {
        init: init,
        initCursorGlow: initCursorGlow,
        initMagnetic: initMagnetic,
        initScramble: initScramble,
        initTilt: initTilt,
        initScrollReveal: initScrollReveal,
        initCountUp: initCountUp
    };
})();
