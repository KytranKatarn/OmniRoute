/**
 * Kytran Empowerment — Cinematic Splash Intro
 * Plays once per session: particles → logo reveal → tagline → dissolve into homepage.
 * Pure JS + Canvas (no GSAP dependency — runs before deferred scripts).
 */
const Intro = (() => {
  'use strict';

  /* ── helpers ──────────────────────────────────────────── */
  const $ = (id) => document.getElementById(id);
  const raf = requestAnimationFrame.bind(window);
  const perfNow = performance.now.bind(performance);

  function easeInOutQuad(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }

  /* ── config ──────────────────────────────────────────── */
  const PARTICLE_COUNT = 150;
  const PHASE_1_END    = 1500;          // particles converge
  const PHASE_2_END    = 3000;          // logo + title reveal
  const PHASE_3_END    = 4000;          // tagline + scanline
  // Phase 4: 4000-5000 — dissolve out

  const TAGLINE = 'AI-Powered Business Automation';
  const TYPING_SPEED = 30;             // ms per character

  /* ── state ───────────────────────────────────────────── */
  let canvas, ctx, cw, ch;
  let particles = [];
  let startTime = 0;
  let animId = null;
  let done = false;

  /* ── particles ───────────────────────────────────────── */
  function createParticles() {
    particles = [];
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      particles.push({
        x: Math.random() * cw,
        y: Math.random() * ch,
        tx: cw / 2 + (Math.random() - 0.5) * 10,
        ty: ch / 2 + (Math.random() - 0.5) * 10,
        size: 1 + Math.random() * 2,
        color: Math.random() > 0.5 ? '#ffffff' : '#00e5ff',
        alpha: 0.3 + Math.random() * 0.7,
        arrived: false
      });
    }
  }

  function updateParticles(progress) {
    var ease = easeInOutQuad(Math.min(progress, 1));
    var speed = 0.02 + ease * 0.08;

    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      if (p.arrived) continue;
      var dx = p.tx - p.x;
      var dy = p.ty - p.y;
      var dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 3) {
        p.arrived = true;
        p.alpha *= 0.3;
        continue;
      }
      p.x += dx * speed;
      p.y += dy * speed;
    }
  }

  function drawParticles(fade) {
    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      if (p.arrived && fade > 0.3) continue;
      ctx.globalAlpha = p.alpha * (1 - fade * 0.8);
      ctx.fillStyle = p.color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  /* ── element animations (no GSAP) ───────────────────── */
  function fadeIn(el, duration, delay, extras) {
    if (!el) return;
    el.style.transition = 'opacity ' + duration + 'ms ease, transform ' + duration + 'ms ease';
    el.style.opacity = '0';
    if (extras && extras.scale) el.style.transform = 'scale(' + extras.scale + ')';
    if (extras && extras.y) el.style.transform = 'translateY(' + extras.y + 'px)';
    setTimeout(function() {
      el.style.opacity = '1';
      el.style.transform = 'scale(1) translateY(0)';
    }, delay);
  }

  function animateLetters(container, text, baseDelay) {
    if (!container) return;
    // Clear children safely using DOM methods
    while (container.firstChild) { container.removeChild(container.firstChild); }
    container.style.opacity = '1';
    for (var i = 0; i < text.length; i++) {
      var span = document.createElement('span');
      span.className = 'intro-letter';
      span.textContent = text[i];
      container.appendChild(span);
      (function(s, d) {
        setTimeout(function() {
          s.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
          s.style.opacity = '1';
          s.style.transform = 'translateY(0)';
        }, d);
      })(span, baseDelay + i * 50);
    }
  }

  function typeText(el, text, startDelay) {
    if (!el) return;
    el.textContent = '';
    el.style.opacity = '1';
    for (var i = 0; i < text.length; i++) {
      (function(idx) {
        setTimeout(function() { el.textContent = text.slice(0, idx + 1); }, startDelay + idx * TYPING_SPEED);
      })(i);
    }
  }

  /* ── main loop ───────────────────────────────────────── */
  function tick(ts) {
    if (done) return;
    var elapsed = ts - startTime;

    ctx.clearRect(0, 0, cw, ch);

    /* Phase 1: particles converge (0–1500ms) */
    if (elapsed < PHASE_1_END) {
      var p1 = elapsed / PHASE_1_END;
      updateParticles(p1);
      drawParticles(0);
    }

    /* Phase 1→2 transition: still draw fading particles */
    if (elapsed >= PHASE_1_END && elapsed < PHASE_2_END) {
      var fade = (elapsed - PHASE_1_END) / (PHASE_2_END - PHASE_1_END);
      drawParticles(fade);
    }

    if (elapsed < 5000) {
      animId = raf(tick);
    }
  }

  /* ── phase triggers (called once each) ──────────────── */
  function schedulePhases() {
    var overlay  = $('introOverlay');
    var flash    = $('introFlash');
    var logo     = $('introLogo');
    var glow     = $('introGlowRing');
    var title    = $('introTitle');
    var subtitle = $('introSubtitle');
    var tagline  = $('introTagline');
    var scanline = $('introScanline');
    var grid     = $('introGrid');

    /* Phase 2 — flash + logo + glow ring + title (1500ms) */
    setTimeout(function() {
      // Flash
      if (flash) {
        flash.style.transition = 'transform 0.4s ease-out, opacity 0.4s ease-out';
        flash.style.opacity = '1';
        flash.style.transform = 'translate(-50%, -50%) scale(30)';
        setTimeout(function() {
          flash.style.transition = 'opacity 0.3s ease';
          flash.style.opacity = '0';
        }, 400);
      }

      // Logo
      fadeIn(logo, 600, 200, { scale: 0.5 });

      // Glow ring expanding
      if (glow) {
        glow.style.opacity = '1';
        glow.style.transition = 'width 1s ease-out, height 1s ease-out, opacity 1s ease-out';
        setTimeout(function() {
          glow.style.width = '300px';
          glow.style.height = '300px';
          glow.style.opacity = '0';
        }, 100);
      }

      // Title letters
      animateLetters(title, 'KYTRAN', 400);

      // Subtitle
      fadeIn(subtitle, 500, 900, { y: 10 });
    }, PHASE_1_END);

    /* Phase 3 — tagline + scanline + grid (3000ms) */
    setTimeout(function() {
      typeText(tagline, TAGLINE, 0);

      // Grid flash
      if (grid) {
        grid.style.transition = 'opacity 0.5s ease';
        grid.style.opacity = '0.4';
        setTimeout(function() { grid.style.opacity = '0'; }, 600);
      }

      // Scanline sweep
      if (scanline) {
        scanline.style.opacity = '1';
        scanline.style.top = '0';
        scanline.style.transition = 'top 0.6s linear, opacity 0.2s ease 0.5s';
        setTimeout(function() {
          scanline.style.top = '100%';
        }, 50);
        setTimeout(function() { scanline.style.opacity = '0'; }, 600);
      }
    }, PHASE_2_END);

    /* Phase 4 — slide up + dissolve (4200ms) */
    setTimeout(function() {
      if (!overlay) return;
      overlay.style.transition = 'transform 0.8s cubic-bezier(0.76, 0, 0.24, 1), opacity 0.6s ease 0.2s';
      overlay.style.transform = 'translateY(-100%)';
      overlay.style.opacity = '0';

      setTimeout(function() {
        overlay.remove();
        document.body.style.overflow = '';
        done = true;
        if (animId) cancelAnimationFrame(animId);
      }, 900);
    }, PHASE_3_END + 200);
  }

  /* ── public init ─────────────────────────────────────── */
  function shouldPlay() {
    if (sessionStorage.getItem('ke-intro-played')) return false;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false;
    return true;
  }

  function init() {
    var overlay = $('introOverlay');

    if (!shouldPlay()) {
      if (overlay) overlay.remove();
      return;
    }

    if (!overlay) return;

    // Lock scroll during intro
    document.body.style.overflow = 'hidden';
    sessionStorage.setItem('ke-intro-played', 'true');

    // Set up canvas
    canvas = $('introCanvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d');
    cw = canvas.width = window.innerWidth;
    ch = canvas.height = window.innerHeight;

    createParticles();
    startTime = perfNow();

    // Start render loop
    animId = raf(tick);

    // Schedule phase transitions
    schedulePhases();
  }

  return { init: init, shouldPlay: shouldPlay };
})();

// Run immediately — script is NOT deferred
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', Intro.init);
} else {
  Intro.init();
}
