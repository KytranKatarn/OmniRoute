/* ==========================================================================
   Ambient Background — constellation canvas + drifting ram-mark watermark
   Sitewide, page-independent (no .hero required). Zero dependency on
   gsap/ScrollTrigger/Lenis — safe to load on every page.
   Extracted from hero-animations.js so every page gets the same background
   layers as the homepage, not just pages with a hero section.
   ========================================================================== */

var AmbientBackground = (function () {
    'use strict';

    var _particleCanvas = null;
    var _particleCtx = null;
    var _particles = [];
    var _particleRaf = null;
    var _canvasRect = null;
    var _isVisible = true;
    var _scrollLogo = null;
    var _scrollRaf = null;
    var _scrollHandler = null;
    var _connectionDistance = 140;
    var _particleSpeed = 0.35;

    /* ====================================================================
       Public: init
       ==================================================================== */
    function init() {
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

        initParticles();
        initScrollAmbient();
    }

    /* ====================================================================
       Constellation Network (2D Canvas)
       70 nodes drifting with cyan connecting edges within 140px — ports the
       design's startCanvas() algorithm 1:1 (Home.dc.html).
       ==================================================================== */
    function initParticles() {
        _particleCanvas = document.getElementById('scrollParticles');
        if (!_particleCanvas) return;

        var compact = window.matchMedia('(max-width: 768px)').matches;
        _connectionDistance = compact ? 100 : 140;
        _particleSpeed = compact ? 0.2 : 0.35;
        _particleCtx = _particleCanvas.getContext('2d');
        _canvasRect = { width: window.innerWidth, height: window.innerHeight };

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

        var count = compact ? 32 : 70;
        for (var i = 0; i < count; i++) {
            _particles.push({
                x: Math.random() * _canvasRect.width,
                y: Math.random() * _canvasRect.height,
                vx: (Math.random() - 0.5) * _particleSpeed,
                vy: (Math.random() - 0.5) * _particleSpeed
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
                var compact = window.matchMedia('(max-width: 768px)').matches;
                var maxScroll = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
                var scrollY = window.scrollY || window.pageYOffset || 0;
                var progress = Math.min(Math.max(scrollY / maxScroll, 0), 1);
                var shift = compact ? 72 : 120;
                var startOpacity = compact ? 0.12 : 0.07;
                var endOpacity = compact ? 0.06 : 0.045;
                _scrollLogo.style.setProperty('--scroll-shift', (progress * shift) + 'px');
                _scrollLogo.style.setProperty('--scroll-scale', (1 + progress * (compact ? 0.05 : 0.08)).toFixed(3));
                _scrollLogo.style.setProperty('--scroll-rotate', ((progress * 2 - 1) * (compact ? 0.5 : 0.8)).toFixed(2) + 'deg');
                _scrollLogo.style.opacity = (startOpacity - progress * (startOpacity - endOpacity)).toFixed(3);
            });
        };

        window.addEventListener('scroll', _scrollHandler, { passive: true });
        _scrollHandler();
    }

    function _resizeCanvas() {
        if (!_particleCanvas) return;
        var compact = window.matchMedia('(max-width: 768px)').matches;
        _connectionDistance = compact ? 100 : 140;
        _particleSpeed = compact ? 0.2 : 0.35;
        var dpr = Math.min(window.devicePixelRatio, 2);
        var width = window.innerWidth;
        var height = window.innerHeight;
        _particleCanvas.width = width * dpr;
        _particleCanvas.height = height * dpr;
        _particleCanvas.style.width = width + 'px';
        _particleCanvas.style.height = height + 'px';
        _particleCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
        _canvasRect = { width: width, height: height };
        if (_scrollHandler) _scrollHandler();
    }

    function _animateParticles() {
        if (!_isVisible || !_particleCtx || !_canvasRect) return;

        var w = _canvasRect.width;
        var h = _canvasRect.height;
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
                if (d < _connectionDistance) {
                    _particleCtx.strokeStyle = 'rgba(0,229,255,' + ((1 - d / _connectionDistance) * 0.25) + ')';
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
