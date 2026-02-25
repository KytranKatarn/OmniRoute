# Neural Core v2 — Holographic Sphere Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the flat 2D orbital Neural Core with a cinematic holographic sphere and frosted-glass nav bar, built as shared reusable components (`HoloSphere` + `GlassNav`).

**Architecture:** Two self-contained JS classes with matching CSS files, zero external dependencies. HoloSphere uses CSS 3D transforms for the sphere shell, canvas for 3-layer particles, DOM elements for knowledge nodes (Fibonacci-distributed), and pure CSS for cinematic effects. GlassNav uses backdrop-filter glassmorphism with a sliding indicator pill. Both are instantiated by consciousness.js.

**Tech Stack:** CSS 3D transforms (`perspective`, `transform-style: preserve-3d`), HTML5 Canvas (2D context), CSS `backdrop-filter`, vanilla JS classes, existing Flask template system.

**Design Doc:** `docs/plans/2026-02-25-neural-core-v2-holosphere-design.md`

---

## Phase 1: Shared Components

### Task 1: HoloSphere CSS

**Files:**
- Create: `platform_v2/static/css/holo-sphere.css`

**Step 1: Create the CSS file with all sphere styles**

```css
/* ═══════════════════════════════════════════════════════
   HoloSphere — Holographic Sphere Visualization
   Shared component: any module can use this.
   Theme via CSS custom properties.
   ═══════════════════════════════════════════════════════ */

:root {
    --holo-accent: #8b5cf6;
    --holo-accent-rgb: 139, 92, 246;
    --holo-glow-intensity: 1;
}

/* ── Container ────────────────────────────────────── */
.holo-container {
    position: relative;
    width: 100%;
    max-width: 600px;
    margin: 0 auto 24px;
    aspect-ratio: 1 / 1;
    max-height: 500px;
    perspective: 800px;
    display: flex;
    align-items: center;
    justify-content: center;
}

/* ── Ambient Page Glow ────────────────────────────── */
.holo-container::before {
    content: '';
    position: absolute;
    width: 120%;
    height: 120%;
    top: -10%; left: -10%;
    border-radius: 50%;
    background: radial-gradient(
        circle,
        rgba(var(--holo-accent-rgb), 0.06) 0%,
        rgba(var(--holo-accent-rgb), 0.02) 40%,
        transparent 70%
    );
    animation: holoAmbientDrift 20s ease-in-out infinite alternate;
    pointer-events: none;
    z-index: 0;
}
@keyframes holoAmbientDrift {
    0%   { transform: translate(0, 0) scale(1); }
    50%  { transform: translate(3%, -2%) scale(1.04); }
    100% { transform: translate(-2%, 3%) scale(0.98); }
}

/* ── Sphere Shell (5 concentric CSS 3D rings) ─────── */
.holo-sphere {
    position: relative;
    width: 70%;
    height: 70%;
    transform-style: preserve-3d;
    animation: holoSphereRotate 30s linear infinite;
}
@keyframes holoSphereRotate {
    0%   { transform: rotateY(0deg) rotateX(8deg); }
    100% { transform: rotateY(360deg) rotateX(8deg); }
}

.holo-ring {
    position: absolute;
    top: 50%; left: 50%;
    border-radius: 50%;
    border: 1px solid rgba(var(--holo-accent-rgb), 0.1);
    transform-style: preserve-3d;
    pointer-events: none;
}

.holo-ring-1 {
    width: 100%; height: 100%;
    margin-left: -50%; margin-top: -50%;
    transform: rotateX(70deg);
    animation: holoRingSpin1 25s linear infinite;
}
.holo-ring-2 {
    width: 95%; height: 95%;
    margin-left: -47.5%; margin-top: -47.5%;
    transform: rotateX(70deg) rotateY(60deg);
    animation: holoRingSpin2 35s linear infinite reverse;
    border-style: dashed;
    border-color: rgba(var(--holo-accent-rgb), 0.06);
}
.holo-ring-3 {
    width: 90%; height: 90%;
    margin-left: -45%; margin-top: -45%;
    transform: rotateX(70deg) rotateY(120deg);
    animation: holoRingSpin3 45s linear infinite;
}
.holo-ring-4 {
    width: 85%; height: 85%;
    margin-left: -42.5%; margin-top: -42.5%;
    transform: rotateY(70deg);
    animation: holoRingSpin4 55s linear infinite reverse;
    border-style: dashed;
    border-color: rgba(var(--holo-accent-rgb), 0.05);
}
.holo-ring-5 {
    width: 105%; height: 105%;
    margin-left: -52.5%; margin-top: -52.5%;
    transform: rotateX(30deg) rotateZ(45deg);
    animation: holoRingSpin5 80s linear infinite;
    border-color: rgba(var(--holo-accent-rgb), 0.04);
}

@keyframes holoRingSpin1 { to { transform: rotateX(70deg) rotateZ(360deg); } }
@keyframes holoRingSpin2 { to { transform: rotateX(70deg) rotateY(60deg) rotateZ(360deg); } }
@keyframes holoRingSpin3 { to { transform: rotateX(70deg) rotateY(120deg) rotateZ(360deg); } }
@keyframes holoRingSpin4 { to { transform: rotateY(70deg) rotateZ(360deg); } }
@keyframes holoRingSpin5 { to { transform: rotateX(30deg) rotateZ(405deg); } }

/* ── Holographic Glow (behind sphere) ─────────────── */
.holo-glow {
    position: absolute;
    width: 60%; height: 60%;
    top: 20%; left: 20%;
    border-radius: 50%;
    background: radial-gradient(
        circle,
        rgba(var(--holo-accent-rgb), 0.15) 0%,
        rgba(var(--holo-accent-rgb), 0.05) 50%,
        transparent 70%
    );
    filter: blur(20px);
    animation: holoCoreBreath 4s ease-in-out infinite;
    pointer-events: none;
    z-index: 1;
}
@keyframes holoCoreBreath {
    0%, 100% { transform: scale(1); opacity: calc(0.8 * var(--holo-glow-intensity)); }
    50%      { transform: scale(1.06); opacity: calc(1.0 * var(--holo-glow-intensity)); }
}

/* ── Center Core ──────────────────────────────────── */
.holo-core {
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    width: 50px; height: 50px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(var(--holo-accent-rgb), 0.4) 0%, rgba(var(--holo-accent-rgb), 0.1) 60%, transparent 100%);
    border: 1.5px solid rgba(var(--holo-accent-rgb), 0.5);
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    z-index: 20;
    animation: holoCoreBreath 4s ease-in-out infinite;
    transition: border-color 0.8s, background 0.8s;
}
.holo-core-name {
    font-family: 'Orbitron', sans-serif;
    font-size: 0.45rem; font-weight: 700;
    color: rgba(var(--holo-accent-rgb), 1);
    letter-spacing: 1.5px;
}
.holo-core-mood {
    font-family: 'Antonio', sans-serif;
    font-size: 0.5rem; color: rgba(255,255,255,0.4);
    text-transform: uppercase; letter-spacing: 0.5px;
    margin-top: 1px;
}

/* ── Knowledge Nodes (3D positioned) ──────────────── */
.holo-node {
    position: absolute;
    width: 36px; height: 36px;
    border-radius: 50%;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s, opacity 0.3s;
    border: 1.5px solid var(--node-color, rgba(var(--holo-accent-rgb), 1));
    background: radial-gradient(circle, color-mix(in srgb, var(--node-color, #8b5cf6) 12%, transparent) 0%, transparent 80%);
    z-index: 15;
    will-change: transform, opacity;
}
.holo-node:hover {
    transform: scale(1.3) !important;
    box-shadow: 0 0 24px var(--node-color, rgba(var(--holo-accent-rgb), 0.6));
    z-index: 25;
}
.holo-node-count {
    font-family: 'Orbitron', sans-serif;
    font-size: 0.5rem; font-weight: 700;
    color: var(--node-color, rgba(var(--holo-accent-rgb), 1));
}
.holo-node-label {
    font-family: 'Antonio', sans-serif;
    font-size: 0.4rem; font-weight: 500;
    color: rgba(255,255,255,0.45);
    text-transform: uppercase; letter-spacing: 0.3px;
    white-space: nowrap;
}

/* ── Energy Burst (on node update) ────────────────── */
.holo-burst {
    position: absolute;
    border-radius: 50%;
    border: 1.5px solid var(--node-color, rgba(var(--holo-accent-rgb), 0.4));
    pointer-events: none;
    animation: holoBurst 0.6s ease-out forwards;
    z-index: 14;
}
@keyframes holoBurst {
    0%   { transform: translate(-50%, -50%) scale(0.5); opacity: 0.8; }
    100% { transform: translate(-50%, -50%) scale(2.5); opacity: 0; }
}

/* ── Connecting Threads (SVG) ─────────────────────── */
.holo-threads {
    position: absolute; inset: 0;
    pointer-events: none;
    z-index: 12;
}
.holo-thread {
    stroke: rgba(var(--holo-accent-rgb), 0.05);
    stroke-width: 0.5;
    fill: none;
    transition: stroke 0.3s;
}
.holo-thread.active {
    stroke: rgba(var(--holo-accent-rgb), 0.2);
    stroke-width: 1;
    animation: holoThreadPulse 1s ease-out;
}
@keyframes holoThreadPulse {
    0%   { stroke: rgba(var(--holo-accent-rgb), 0.5); stroke-width: 1.5; }
    100% { stroke: rgba(var(--holo-accent-rgb), 0.05); stroke-width: 0.5; }
}

/* ── Particle Canvas ──────────────────────────────── */
.holo-particle-canvas {
    position: absolute; inset: 0;
    pointer-events: none;
    z-index: 13;
}

/* ── Ambient Dust Canvas ──────────────────────────── */
.holo-dust-canvas {
    position: absolute; inset: 0;
    pointer-events: none;
    z-index: 0;
}

/* ── Scanline Overlay ─────────────────────────────── */
.holo-scanlines {
    position: absolute; inset: 0;
    pointer-events: none;
    z-index: 16;
    border-radius: 50%;
    overflow: hidden;
    opacity: 0.4;
}
.holo-scanlines::after {
    content: '';
    position: absolute;
    inset: 0;
    background: repeating-linear-gradient(
        0deg,
        transparent,
        transparent 2px,
        rgba(255,255,255,0.015) 2px,
        rgba(255,255,255,0.015) 3px
    );
    animation: holoScanScroll 8s linear infinite;
}
@keyframes holoScanScroll {
    to { background-position: 0 100px; }
}

/* ── Data Pulse Wave ──────────────────────────────── */
.holo-pulse {
    position: absolute;
    top: 50%; left: 50%;
    width: 60px; height: 60px;
    margin-left: -30px; margin-top: -30px;
    border-radius: 50%;
    border: 2px solid rgba(var(--holo-accent-rgb), 0.3);
    pointer-events: none;
    animation: holoPulseWave 0.8s ease-out forwards;
    z-index: 17;
}
@keyframes holoPulseWave {
    0%   { transform: scale(0.5); opacity: 0.8; }
    100% { transform: scale(3); opacity: 0; }
}

/* ── Surface Energy Sweep ─────────────────────────── */
.holo-sweep {
    position: absolute; inset: 0;
    pointer-events: none;
    z-index: 15;
    border-radius: 50%;
    overflow: hidden;
}
.holo-sweep::after {
    content: '';
    position: absolute;
    width: 100%; height: 8px;
    left: 0; top: -10%;
    background: linear-gradient(
        180deg,
        transparent,
        rgba(var(--holo-accent-rgb), 0.08),
        transparent
    );
    animation: holoSweep 7s ease-in-out infinite;
}
@keyframes holoSweep {
    0%, 100% { top: -10%; opacity: 0; }
    10%      { opacity: 1; }
    90%      { opacity: 1; }
    95%      { top: 110%; opacity: 0; }
}

/* ── Stats HUD ────────────────────────────────────── */
.holo-hud {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 20px;
    max-width: 600px;
    margin-left: auto;
    margin-right: auto;
}
.holo-hud-item {
    display: flex; flex-direction: column;
    align-items: center; padding: 10px 8px;
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    transition: border-color 0.2s;
}
.holo-hud-item:hover {
    border-color: rgba(var(--holo-accent-rgb), 0.15);
}
.holo-hud-value {
    font-family: 'Orbitron', sans-serif;
    font-size: 1.1rem; font-weight: 700;
}
.holo-hud-label {
    font-family: 'Antonio', sans-serif;
    font-size: 0.65rem; color: rgba(255,255,255,0.4);
    text-transform: uppercase; letter-spacing: 1px;
    margin-top: 2px;
}
.holo-hud-item.purple .holo-hud-value { color: #8b5cf6; }
.holo-hud-item.blue .holo-hud-value   { color: #3b82f6; }
.holo-hud-item.green .holo-hud-value  { color: #22c55e; }
.holo-hud-item.amber .holo-hud-value  { color: #f59e0b; }

/* ── Responsive ───────────────────────────────────── */
@media (max-width: 767px) {
    .holo-container { max-height: 350px; }
    .holo-ring-5 { display: none; }
    .holo-ring-4 { display: none; }
    .holo-node { width: 30px; height: 30px; }
    .holo-node-count { font-size: 0.42rem; }
    .holo-node-label { font-size: 0.35rem; }
    .holo-core { width: 42px; height: 42px; }
    .holo-core-name { font-size: 0.38rem; }
    .holo-hud { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 500px) {
    .holo-container { max-height: 260px; aspect-ratio: auto; height: 260px; }
    .holo-ring-3 { display: none; }
    .holo-scanlines { display: none; }
}

/* ── Reduced Motion ───────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
    .holo-sphere, .holo-ring, .holo-glow, .holo-core,
    .holo-sweep::after, .holo-scanlines::after,
    .holo-container::before { animation: none !important; }
}
```

**Step 2: Verify** — Open the file in an editor, confirm no syntax errors. The file should be self-contained.

**Step 3: Commit**
```bash
git add platform_v2/static/css/holo-sphere.css
git commit -m "feat: add HoloSphere CSS — 3D rings, scanlines, effects, responsive"
```

---

### Task 2: HoloSphere JavaScript

**Files:**
- Create: `platform_v2/static/js/holo-sphere.js`

**Step 1: Create the HoloSphere class**

This is the largest file. It contains:
- The `HoloSphere` constructor (builds DOM, initializes particles)
- Fibonacci sphere distribution algorithm
- 3-layer particle system (inner, streams, dust)
- Node rendering with z-depth sorting
- Mood and data update methods
- Energy burst and thread pulse effects
- Resize and destroy lifecycle

```javascript
/* ═══════════════════════════════════════════════════════
   HoloSphere — Holographic Sphere Visualization
   Shared component. No dependencies.

   Usage:
     var sphere = new HoloSphere(containerEl, {
       nodes: [{ id, label, count, color, tab }],
       mood: "focused",
       particleCount: 120,
       ambientDust: true,
       ambientTarget: parentEl,
       accentColor: "#8b5cf6",
       onNodeClick: function(node) {}
     });
     sphere.updateNode(id, { count });
     sphere.setMood(mood);
     sphere.destroy();
   ═══════════════════════════════════════════════════════ */

(function() {
"use strict";

var MOOD_COLORS = {
  focused:    "#8b5cf6",
  curious:    "#06b6d4",
  happy:      "#22c55e",
  processing: "#f59e0b",
  empathetic: "#ec4899",
  neutral:    "#8b5cf6",
  confident:  "#3b82f6"
};

var DEG = Math.PI / 180;
var TAU = Math.PI * 2;
var PHI_GOLDEN = Math.PI * (1 + Math.sqrt(5)); // golden angle

/* ── Utility ──────────────────────────────────────── */

function hexToRgb(hex) {
  var r = parseInt(hex.slice(1,3), 16);
  var g = parseInt(hex.slice(3,5), 16);
  var b = parseInt(hex.slice(5,7), 16);
  return r + "," + g + "," + b;
}

function shortNum(n) {
  if (n >= 10000) return (n / 1000).toFixed(1) + "K";
  if (n >= 1000) return (n / 1000).toFixed(1) + "K";
  return String(n);
}

function escHtml(s) {
  var d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/* ── Fibonacci Sphere Distribution ────────────────── */

function fibonacciSphere(count, radius) {
  var points = [];
  for (var i = 0; i < count; i++) {
    var phi = Math.acos(1 - 2 * (i + 0.5) / count);
    var theta = PHI_GOLDEN * i;
    points.push({
      x: radius * Math.sin(phi) * Math.cos(theta),
      y: radius * Math.sin(phi) * Math.sin(theta),
      z: radius * Math.cos(phi),
      theta: theta,
      phi: phi
    });
  }
  return points;
}

/* ── Constructor ──────────────────────────────────── */

function HoloSphere(container, opts) {
  if (!container) throw new Error("HoloSphere: container required");
  opts = opts || {};

  this.container = container;
  this.nodes = opts.nodes || [];
  this.mood = (opts.mood || "focused").toLowerCase();
  this.particleCount = opts.particleCount || 120;
  this.ambientDust = opts.ambientDust !== false;
  this.ambientTarget = opts.ambientTarget || container;
  this.onNodeClick = opts.onNodeClick || null;
  this.accentColor = opts.accentColor || "#8b5cf6";

  this._animId = null;
  this._dustAnimId = null;
  this._particles = [];
  this._streams = [];
  this._dust = [];
  this._nodeEls = {};
  this._nodePositions = [];
  this._orbitOffset = 0;
  this._destroyed = false;
  this._reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  this._build();
  this._initParticles();
  if (this.ambientDust) this._initDust();
  if (!this._reducedMotion) this._animate();
}

/* ── DOM Construction ─────────────────────────────── */

HoloSphere.prototype._build = function() {
  var c = this.container;
  c.classList.add("holo-container");

  // Set accent custom properties
  var rgb = hexToRgb(this.accentColor);
  c.style.setProperty("--holo-accent", this.accentColor);
  c.style.setProperty("--holo-accent-rgb", rgb);

  // Sphere shell
  var sphere = document.createElement("div");
  sphere.className = "holo-sphere";
  this._sphereEl = sphere;

  // 5 rings
  for (var i = 1; i <= 5; i++) {
    var ring = document.createElement("div");
    ring.className = "holo-ring holo-ring-" + i;
    sphere.appendChild(ring);
  }

  // Glow
  var glow = document.createElement("div");
  glow.className = "holo-glow";
  this._glowEl = glow;

  // Scanlines
  var scan = document.createElement("div");
  scan.className = "holo-scanlines";

  // Surface sweep
  var sweep = document.createElement("div");
  sweep.className = "holo-sweep";

  // Thread SVG
  var svgNS = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("class", "holo-threads");
  svg.setAttribute("viewBox", "0 0 600 600");
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  this._threadsSvg = svg;

  // Particle canvas
  var canvas = document.createElement("canvas");
  canvas.className = "holo-particle-canvas";
  this._canvas = canvas;

  // Center core
  var core = document.createElement("div");
  core.className = "holo-core";
  var coreName = document.createElement("span");
  coreName.className = "holo-core-name";
  coreName.textContent = "A.R.C.H.I.E.";
  var coreMood = document.createElement("span");
  coreMood.className = "holo-core-mood";
  coreMood.textContent = this.mood;
  this._coreMoodEl = coreMood;
  this._coreEl = core;
  core.appendChild(coreName);
  core.appendChild(coreMood);

  // Assemble
  c.appendChild(glow);
  c.appendChild(svg);
  c.appendChild(canvas);
  c.appendChild(sphere);
  c.appendChild(scan);
  c.appendChild(sweep);
  c.appendChild(core);

  // Build knowledge nodes
  this._buildNodes();

  // Apply mood color
  this._applyMood();
};

/* ── Knowledge Nodes ──────────────────────────────── */

HoloSphere.prototype._buildNodes = function() {
  var self = this;
  // Calculate sphere radius in CSS pixels (35% of container width)
  var containerW = this.container.offsetWidth || 500;
  var radius = containerW * 0.28;

  // Get Fibonacci positions
  var positions = fibonacciSphere(this.nodes.length, radius);
  this._nodePositions = positions;

  this.nodes.forEach(function(node, i) {
    var pos = positions[i];
    var el = document.createElement("div");
    el.className = "holo-node";
    el.style.setProperty("--node-color", node.color || self.accentColor);
    el.title = node.label || node.id;

    var countEl = document.createElement("span");
    countEl.className = "holo-node-count";
    countEl.textContent = shortNum(node.count || 0);

    var labelEl = document.createElement("span");
    labelEl.className = "holo-node-label";
    labelEl.textContent = node.label || node.id;

    el.appendChild(countEl);
    el.appendChild(labelEl);

    el.addEventListener("click", function() {
      if (self.onNodeClick) self.onNodeClick(node);
    });

    self.container.appendChild(el);
    self._nodeEls[node.id] = { el: el, countEl: countEl, pos: pos, node: node };
  });
};

HoloSphere.prototype._updateNodePositions = function() {
  var containerW = this.container.offsetWidth || 500;
  var containerH = this.container.offsetHeight || 500;
  var cx = containerW / 2;
  var cy = containerH / 2;

  var self = this;
  var ids = Object.keys(this._nodeEls);
  ids.forEach(function(id) {
    var entry = self._nodeEls[id];
    var pos = entry.pos;

    // Rotate by orbit offset
    var cosA = Math.cos(self._orbitOffset);
    var sinA = Math.sin(self._orbitOffset);
    var rx = pos.x * cosA - pos.z * sinA;
    var rz = pos.x * sinA + pos.z * cosA;
    var ry = pos.y;

    // Project: depth factor for size/opacity
    var maxR = containerW * 0.28;
    var depthNorm = (rz + maxR) / (2 * maxR); // 0 = far, 1 = near
    var scale = 0.5 + depthNorm * 0.6;
    var opacity = 0.25 + depthNorm * 0.75;

    var el = entry.el;
    var nodeW = 36 * scale;
    el.style.left = (cx + rx - nodeW / 2) + "px";
    el.style.top = (cy + ry - nodeW / 2) + "px";
    el.style.transform = "scale(" + scale.toFixed(3) + ")";
    el.style.opacity = opacity.toFixed(3);
    el.style.zIndex = Math.round(10 + depthNorm * 10);

    // Store screen position for threads/particles
    entry.screenX = cx + rx;
    entry.screenY = cy + ry;
    entry.depth = depthNorm;
  });
};

/* ── Connecting Threads ───────────────────────────── */

HoloSphere.prototype._drawThreads = function() {
  var svg = this._threadsSvg;
  if (!svg) return;

  var containerW = this.container.offsetWidth || 500;
  var containerH = this.container.offsetHeight || 500;
  // Map to SVG viewBox (600x600)
  var scaleX = 600 / containerW;
  var scaleY = 600 / containerH;

  var svgNS = "http://www.w3.org/2000/svg";
  var frag = document.createDocumentFragment();
  var cx = 300, cy = 300;

  var ids = Object.keys(this._nodeEls);
  var entries = ids.map(function(id) { return this._nodeEls[id]; }.bind(this));

  // Connect each node to center
  entries.forEach(function(entry) {
    var nx = entry.screenX * scaleX;
    var ny = entry.screenY * scaleY;
    var line = document.createElementNS(svgNS, "line");
    line.setAttribute("class", "holo-thread");
    line.setAttribute("x1", cx);
    line.setAttribute("y1", cy);
    line.setAttribute("x2", nx.toFixed(1));
    line.setAttribute("y2", ny.toFixed(1));
    frag.appendChild(line);
  });

  // Connect adjacent nodes (sorted by angle)
  entries.sort(function(a, b) {
    return Math.atan2(a.screenY - containerH/2, a.screenX - containerW/2)
         - Math.atan2(b.screenY - containerH/2, b.screenX - containerW/2);
  });
  for (var j = 0; j < entries.length; j++) {
    var a = entries[j];
    var b = entries[(j + 1) % entries.length];
    var line2 = document.createElementNS(svgNS, "line");
    line2.setAttribute("class", "holo-thread");
    line2.setAttribute("x1", (a.screenX * scaleX).toFixed(1));
    line2.setAttribute("y1", (a.screenY * scaleY).toFixed(1));
    line2.setAttribute("x2", (b.screenX * scaleX).toFixed(1));
    line2.setAttribute("y2", (b.screenY * scaleY).toFixed(1));
    frag.appendChild(line2);
  }

  svg.textContent = "";
  svg.appendChild(frag);
};

/* ── Particle System ──────────────────────────────── */

HoloSphere.prototype._initParticles = function() {
  var canvas = this._canvas;
  if (!canvas) return;
  canvas.width = this.container.offsetWidth;
  canvas.height = this.container.offsetHeight;

  this._ctx = canvas.getContext("2d");
  var cx = canvas.width / 2;
  var cy = canvas.height / 2;
  var sphereR = Math.min(canvas.width, canvas.height) * 0.28;

  // Layer 1: Inner sphere particles (70% of budget)
  var innerCount = Math.round(this.particleCount * 0.65);
  this._particles = [];
  for (var i = 0; i < innerCount; i++) {
    // Random position inside sphere volume
    var r = sphereR * Math.cbrt(Math.random()); // cube root for uniform volume
    var theta = Math.random() * TAU;
    var phi = Math.acos(2 * Math.random() - 1);
    var nodeColors = this.nodes.map(function(n) { return hexToRgb(n.color || "#8b5cf6"); });
    this._particles.push({
      x: r * Math.sin(phi) * Math.cos(theta),
      y: r * Math.sin(phi) * Math.sin(theta),
      z: r * Math.cos(phi),
      vx: (Math.random() - 0.5) * 0.3,
      vy: (Math.random() - 0.5) * 0.3,
      vz: (Math.random() - 0.5) * 0.3,
      wobblePhase: Math.random() * TAU,
      wobbleSpeed: 0.01 + Math.random() * 0.02,
      size: 1.5 + Math.random() * 2,
      alpha: 0.2 + Math.random() * 0.5,
      color: nodeColors.length ? nodeColors[Math.floor(Math.random() * nodeColors.length)] : "139,92,246",
      sphereR: sphereR
    });
  }

  // Layer 2: Energy streams (20% of budget)
  var streamCount = Math.round(this.particleCount * 0.2);
  this._streams = [];
  for (var s = 0; s < streamCount; s++) {
    this._streams.push({
      progress: Math.random(),
      speed: 0.005 + Math.random() * 0.01,
      fromNode: Math.floor(Math.random() * Math.max(this.nodes.length, 1)),
      toCenter: Math.random() > 0.5,
      size: 1.5 + Math.random() * 1.5,
      alpha: 0.4 + Math.random() * 0.4,
      color: hexToRgb(this.accentColor),
      trail: []
    });
  }
};

HoloSphere.prototype._initDust = function() {
  var target = this.ambientTarget;
  if (!target) return;

  var dustCanvas = document.createElement("canvas");
  dustCanvas.className = "holo-dust-canvas";
  dustCanvas.style.position = "absolute";
  dustCanvas.style.inset = "0";
  dustCanvas.style.pointerEvents = "none";
  dustCanvas.style.zIndex = "0";

  // Insert as first child of target
  if (target.firstChild) {
    target.insertBefore(dustCanvas, target.firstChild);
  } else {
    target.appendChild(dustCanvas);
  }

  // Make target position relative if not already
  var pos = window.getComputedStyle(target).position;
  if (pos === "static") target.style.position = "relative";

  this._dustCanvas = dustCanvas;
  dustCanvas.width = target.offsetWidth;
  dustCanvas.height = target.offsetHeight;
  this._dustCtx = dustCanvas.getContext("2d");

  var dustCount = this._reducedMotion ? 15 : 35;
  this._dust = [];
  for (var d = 0; d < dustCount; d++) {
    this._dust.push({
      x: Math.random() * dustCanvas.width,
      y: Math.random() * dustCanvas.height,
      vx: (Math.random() - 0.5) * 0.15,
      vy: (Math.random() - 0.5) * 0.1 - 0.05, // slight upward drift
      size: 0.8 + Math.random() * 1.2,
      alpha: 0.06 + Math.random() * 0.12,
      color: hexToRgb(this.accentColor)
    });
  }
};

/* ── Animation Loop ───────────────────────────────── */

HoloSphere.prototype._animate = function() {
  var self = this;

  function tick() {
    if (self._destroyed) return;

    // Orbit nodes
    self._orbitOffset += 0.001;
    self._updateNodePositions();

    // Redraw threads every 30 frames (performance)
    if (!self._frameCount) self._frameCount = 0;
    self._frameCount++;
    if (self._frameCount % 30 === 0) {
      self._drawThreads();
    }

    // Render particles
    self._renderParticles();

    // Render dust
    if (self._dustCtx) self._renderDust();

    self._animId = requestAnimationFrame(tick);
  }

  // Initial thread draw
  self._updateNodePositions();
  self._drawThreads();

  tick();
};

HoloSphere.prototype._renderParticles = function() {
  var ctx = this._ctx;
  var canvas = this._canvas;
  if (!ctx) return;

  var w = canvas.width;
  var h = canvas.height;
  var cx = w / 2;
  var cy = h / 2;

  ctx.clearRect(0, 0, w, h);

  // Layer 1: Inner sphere particles
  this._particles.forEach(function(p) {
    // Wobble movement
    p.wobblePhase += p.wobbleSpeed;
    p.x += p.vx + Math.sin(p.wobblePhase) * 0.2;
    p.y += p.vy + Math.cos(p.wobblePhase * 0.7) * 0.2;
    p.z += p.vz + Math.sin(p.wobblePhase * 1.3) * 0.15;

    // Contain within sphere
    var dist = Math.sqrt(p.x * p.x + p.y * p.y + p.z * p.z);
    if (dist > p.sphereR) {
      var scale = p.sphereR / dist * 0.95;
      p.x *= scale; p.y *= scale; p.z *= scale;
      p.vx *= -0.5; p.vy *= -0.5; p.vz *= -0.5;
    }

    // Depth scaling
    var depthNorm = (p.z + p.sphereR) / (2 * p.sphereR);
    var drawSize = p.size * (0.5 + depthNorm * 0.8);
    var drawAlpha = p.alpha * (0.3 + depthNorm * 0.7);

    var sx = cx + p.x;
    var sy = cy + p.y;

    ctx.beginPath();
    ctx.arc(sx, sy, drawSize, 0, TAU);
    ctx.fillStyle = "rgba(" + p.color + "," + drawAlpha.toFixed(2) + ")";
    ctx.shadowColor = "rgba(" + p.color + ",0.3)";
    ctx.shadowBlur = 6;
    ctx.fill();
    ctx.shadowBlur = 0;
  });

  // Layer 2: Energy streams
  var nodeEntries = Object.keys(this._nodeEls).map(function(id) {
    return this._nodeEls[id];
  }.bind(this));

  this._streams.forEach(function(s) {
    s.progress += s.speed;
    if (s.progress > 1) {
      s.progress = 0;
      s.fromNode = Math.floor(Math.random() * Math.max(nodeEntries.length, 1));
      s.toCenter = Math.random() > 0.3;
      s.trail = [];
    }

    var fromEntry = nodeEntries[s.fromNode % Math.max(nodeEntries.length, 1)];
    var startX = fromEntry ? fromEntry.screenX : cx;
    var startY = fromEntry ? fromEntry.screenY : cy;
    var endX = cx;
    var endY = cy;

    if (!s.toCenter && nodeEntries.length > 1) {
      var toIdx = (s.fromNode + 1 + Math.floor(Math.random() * (nodeEntries.length - 1))) % nodeEntries.length;
      var toEntry = nodeEntries[toIdx];
      endX = toEntry ? toEntry.screenX : cx;
      endY = toEntry ? toEntry.screenY : cy;
    }

    var t = s.progress;
    var px = startX + (endX - startX) * t;
    var py = startY + (endY - startY) * t;

    // Store trail
    s.trail.push({ x: px, y: py });
    if (s.trail.length > 4) s.trail.shift();

    // Draw trail
    s.trail.forEach(function(pt, idx) {
      var trailAlpha = s.alpha * (idx / s.trail.length) * 0.6;
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, s.size * 0.6, 0, TAU);
      ctx.fillStyle = "rgba(" + s.color + "," + trailAlpha.toFixed(2) + ")";
      ctx.fill();
    });

    // Draw head
    ctx.beginPath();
    ctx.arc(px, py, s.size, 0, TAU);
    ctx.fillStyle = "rgba(" + s.color + "," + s.alpha.toFixed(2) + ")";
    ctx.shadowColor = "rgba(" + s.color + ",0.5)";
    ctx.shadowBlur = 10;
    ctx.fill();
    ctx.shadowBlur = 0;
  });
};

HoloSphere.prototype._renderDust = function() {
  var ctx = this._dustCtx;
  var canvas = this._dustCanvas;
  if (!ctx || !canvas) return;

  var w = canvas.width;
  var h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  this._dust.forEach(function(d) {
    d.x += d.vx;
    d.y += d.vy;

    // Wrap around
    if (d.x < -5) d.x = w + 5;
    if (d.x > w + 5) d.x = -5;
    if (d.y < -5) d.y = h + 5;
    if (d.y > h + 5) d.y = -5;

    ctx.beginPath();
    ctx.arc(d.x, d.y, d.size, 0, TAU);
    ctx.fillStyle = "rgba(" + d.color + "," + d.alpha.toFixed(3) + ")";
    ctx.fill();
  });
};

/* ── Mood ─────────────────────────────────────────── */

HoloSphere.prototype.setMood = function(mood) {
  this.mood = (mood || "focused").toLowerCase();
  this._applyMood();
};

HoloSphere.prototype._applyMood = function() {
  var color = MOOD_COLORS[this.mood] || MOOD_COLORS.focused;
  var rgb = hexToRgb(color);

  if (this._coreMoodEl) this._coreMoodEl.textContent = this.mood;
  if (this._coreEl) {
    this._coreEl.style.borderColor = color;
    this._coreEl.style.background = "radial-gradient(circle, " +
      "rgba(" + rgb + ",0.4) 0%, rgba(" + rgb + ",0.1) 60%, transparent 100%)";
    var nameEl = this._coreEl.querySelector(".holo-core-name");
    if (nameEl) nameEl.style.color = color;
  }
  if (this._glowEl) {
    this._glowEl.style.background = "radial-gradient(circle, " +
      "rgba(" + rgb + ",0.15) 0%, rgba(" + rgb + ",0.05) 50%, transparent 70%)";
  }

  // Fire pulse wave
  this._firePulse(color);
};

/* ── Node Updates ─────────────────────────────────── */

HoloSphere.prototype.updateNode = function(id, data) {
  var entry = this._nodeEls[id];
  if (!entry) return;
  if (data.count !== undefined) {
    var oldCount = entry.node.count;
    entry.node.count = data.count;
    entry.countEl.textContent = shortNum(data.count);

    // Energy burst if count changed
    if (oldCount !== data.count) {
      this._fireBurst(entry);
      this._fireGlitch();
    }
  }
};

HoloSphere.prototype.updateHud = function(items) {
  // items: [{ id, value }]
  items.forEach(function(item) {
    var el = document.getElementById(item.id);
    if (el) el.textContent = item.value;
  });
};

/* ── Effects ──────────────────────────────────────── */

HoloSphere.prototype._firePulse = function(color) {
  var pulse = document.createElement("div");
  pulse.className = "holo-pulse";
  if (color) pulse.style.borderColor = color;
  this.container.appendChild(pulse);
  setTimeout(function() { pulse.remove(); }, 900);
};

HoloSphere.prototype._fireBurst = function(entry) {
  var burst = document.createElement("div");
  burst.className = "holo-burst";
  burst.style.setProperty("--node-color", entry.node.color || this.accentColor);
  burst.style.left = entry.screenX + "px";
  burst.style.top = entry.screenY + "px";
  burst.style.width = "36px";
  burst.style.height = "36px";
  this.container.appendChild(burst);
  setTimeout(function() { burst.remove(); }, 700);

  // Pulse a random thread
  var threads = this._threadsSvg.querySelectorAll(".holo-thread");
  if (threads.length) {
    var t = threads[Math.floor(Math.random() * threads.length)];
    t.classList.add("active");
    setTimeout(function() { t.classList.remove("active"); }, 1000);
  }
};

HoloSphere.prototype._fireGlitch = function() {
  this.container.style.animation = "none";
  this.container.offsetHeight; // force reflow
  var clipA = Math.random() * 30 + 10;
  var clipB = clipA + Math.random() * 20 + 5;
  this.container.style.clipPath = "polygon(0 0, 100% 0, 100% " + clipA + "%, " +
    "calc(100% - 3px) " + clipA + "%, calc(100% - 3px) " + clipB + "%, " +
    "100% " + clipB + "%, 100% 100%, 0 100%)";
  var self = this;
  setTimeout(function() {
    self.container.style.clipPath = "";
  }, 150);
};

/* ── Lifecycle ────────────────────────────────────── */

HoloSphere.prototype.resize = function() {
  if (this._canvas) {
    this._canvas.width = this.container.offsetWidth;
    this._canvas.height = this.container.offsetHeight;
  }
  if (this._dustCanvas && this.ambientTarget) {
    this._dustCanvas.width = this.ambientTarget.offsetWidth;
    this._dustCanvas.height = this.ambientTarget.offsetHeight;
  }
  // Recalculate node positions
  var containerW = this.container.offsetWidth || 500;
  var radius = containerW * 0.28;
  var positions = fibonacciSphere(this.nodes.length, radius);
  this._nodePositions = positions;
  var ids = Object.keys(this._nodeEls);
  for (var i = 0; i < ids.length; i++) {
    if (positions[i]) this._nodeEls[ids[i]].pos = positions[i];
  }
  this._updateNodePositions();
  this._drawThreads();
};

HoloSphere.prototype.destroy = function() {
  this._destroyed = true;
  if (this._animId) cancelAnimationFrame(this._animId);
  if (this._dustAnimId) cancelAnimationFrame(this._dustAnimId);
  if (this._dustCanvas && this._dustCanvas.parentNode) {
    this._dustCanvas.parentNode.removeChild(this._dustCanvas);
  }
  this.container.classList.remove("holo-container");
  this.container.textContent = "";
};

/* ── Export ────────────────────────────────────────── */

window.HoloSphere = HoloSphere;

})();
```

**Step 2: Verify** — Check file syntax with `node -c platform_v2/static/js/holo-sphere.js`.

**Step 3: Commit**
```bash
git add platform_v2/static/js/holo-sphere.js
git commit -m "feat: add HoloSphere JS — 3D sphere, Fibonacci nodes, 3-layer particles, effects"
```

---

### Task 3: GlassNav CSS

**Files:**
- Create: `platform_v2/static/css/glass-nav.css`

**Step 1: Create the glassmorphism nav CSS**

```css
/* ═══════════════════════════════════════════════════════
   GlassNav — Frosted Glass Navigation Bar
   Shared component. Theme via CSS custom properties.
   ═══════════════════════════════════════════════════════ */

:root {
    --glass-blur: 16px;
    --glass-bg: rgba(15, 15, 30, 0.6);
    --glass-border: rgba(139, 92, 246, 0.15);
    --glass-accent: #8b5cf6;
    --glass-accent-rgb: 139, 92, 246;
}

.glass-nav {
    position: sticky;
    top: 0;
    z-index: 50;
    display: flex;
    justify-content: center;
    padding: 10px 16px;
    margin-bottom: 20px;
}

.glass-nav-track {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-around;
    gap: 2px;
    max-width: 680px;
    width: 100%;
    padding: 5px 6px;
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur)) saturate(1.4);
    -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(1.4);
    border: 1px solid var(--glass-border);
    border-radius: 20px;
    box-shadow:
        0 4px 30px rgba(0, 0, 0, 0.3),
        inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

/* ── Sliding Indicator ────────────────────────────── */
.glass-nav-indicator {
    position: absolute;
    height: calc(100% - 10px);
    top: 5px;
    border-radius: 16px;
    background: rgba(var(--glass-accent-rgb), 0.18);
    box-shadow:
        0 0 20px rgba(var(--glass-accent-rgb), 0.2),
        inset 0 0 8px rgba(var(--glass-accent-rgb), 0.08);
    transition: left 0.3s cubic-bezier(0.4, 0, 0.2, 1),
                width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    pointer-events: none;
    z-index: 0;
}
.glass-nav-indicator::after {
    content: '';
    position: absolute;
    bottom: 2px;
    left: 25%; right: 25%;
    height: 2px;
    border-radius: 1px;
    background: var(--glass-accent);
    box-shadow: 0 0 8px rgba(var(--glass-accent-rgb), 0.5);
}

/* ── Tab Items ────────────────────────────────────── */
.glass-nav-item {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    background: none;
    border: none;
    color: rgba(255, 255, 255, 0.35);
    font-family: 'Antonio', sans-serif;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    cursor: pointer;
    white-space: nowrap;
    transition: color 0.2s;
    border-radius: 14px;
}
.glass-nav-item i {
    width: 14px; height: 14px;
    flex-shrink: 0;
}
.glass-nav-item:hover {
    color: rgba(255, 255, 255, 0.65);
}
.glass-nav-item.active {
    color: #fff;
}

/* ── Responsive ───────────────────────────────────── */
@media (max-width: 767px) {
    .glass-nav-item span { display: none; }
    .glass-nav-item { padding: 8px 12px; }
    .glass-nav-track { max-width: none; }
}

@media (max-width: 500px) {
    .glass-nav { padding: 6px 8px; }
    .glass-nav-track {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
        justify-content: flex-start;
        gap: 0;
    }
    .glass-nav-track::-webkit-scrollbar { display: none; }
    .glass-nav-item { padding: 6px 10px; }
}
```

**Step 2: Commit**
```bash
git add platform_v2/static/css/glass-nav.css
git commit -m "feat: add GlassNav CSS — glassmorphism bar, sliding indicator, responsive"
```

---

### Task 4: GlassNav JavaScript

**Files:**
- Create: `platform_v2/static/js/glass-nav.js`

**Step 1: Create the GlassNav class**

```javascript
/* ═══════════════════════════════════════════════════════
   GlassNav — Frosted Glass Navigation Bar
   Shared component. No dependencies.

   Usage:
     var nav = new GlassNav(navEl, {
       onSwitch: function(tabName) {}
     });
     nav.setActive("dashboard");
   ═══════════════════════════════════════════════════════ */

(function() {
"use strict";

function GlassNav(el, opts) {
  if (!el) throw new Error("GlassNav: element required");
  opts = opts || {};

  this.el = el;
  this.onSwitch = opts.onSwitch || null;
  this._indicator = el.querySelector(".glass-nav-indicator");
  this._items = Array.prototype.slice.call(el.querySelectorAll(".glass-nav-item"));

  this._bindEvents();
  // Position indicator on the initially active item
  var active = el.querySelector(".glass-nav-item.active");
  if (active && this._indicator) {
    this._moveIndicator(active, false);
  }
}

GlassNav.prototype._bindEvents = function() {
  var self = this;
  this._items.forEach(function(item) {
    item.addEventListener("click", function() {
      var tab = item.dataset.tab;
      if (!tab) return;
      self.setActive(tab);
      if (self.onSwitch) self.onSwitch(tab);
    });
  });

  // Reposition indicator on resize
  this._resizeHandler = function() {
    var active = self.el.querySelector(".glass-nav-item.active");
    if (active) self._moveIndicator(active, false);
  };
  window.addEventListener("resize", this._resizeHandler);
};

GlassNav.prototype.setActive = function(tab) {
  var target = null;
  this._items.forEach(function(item) {
    if (item.dataset.tab === tab) {
      item.classList.add("active");
      target = item;
    } else {
      item.classList.remove("active");
    }
  });
  if (target && this._indicator) {
    this._moveIndicator(target, true);
  }
};

GlassNav.prototype._moveIndicator = function(item, animate) {
  var indicator = this._indicator;
  if (!indicator || !item) return;

  var trackRect = this.el.querySelector(".glass-nav-track").getBoundingClientRect();
  var itemRect = item.getBoundingClientRect();

  var left = itemRect.left - trackRect.left;
  var width = itemRect.width;

  if (!animate) {
    indicator.style.transition = "none";
  }
  indicator.style.left = left + "px";
  indicator.style.width = width + "px";

  if (!animate) {
    // Force reflow then restore transition
    indicator.offsetHeight;
    indicator.style.transition = "";
  }
};

GlassNav.prototype.destroy = function() {
  if (this._resizeHandler) {
    window.removeEventListener("resize", this._resizeHandler);
  }
};

window.GlassNav = GlassNav;

})();
```

**Step 2: Verify** — `node -c platform_v2/static/js/glass-nav.js`

**Step 3: Commit**
```bash
git add platform_v2/static/js/glass-nav.js
git commit -m "feat: add GlassNav JS — sliding indicator, tab switching, resize handling"
```

---

## Phase 2: Integration

### Task 5: Update consciousness_dashboard.html — Scripts, Links, and Remove Old CSS

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

**Step 1: Add `<link>` tags for new CSS files**

Find the Google Fonts `<link>` tag (line 6). After it, add:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/holo-sphere.css') }}">
<link rel="stylesheet" href="{{ url_for('static', filename='css/glass-nav.css') }}">
```

**Step 2: Add `<script>` tags for new JS files**

Find the consciousness.js `<script>` tag (line ~2598). **Before** it, add:

```html
<script src="{{ url_for('static', filename='js/holo-sphere.js') }}"></script>
<script src="{{ url_for('static', filename='js/glass-nav.js') }}"></script>
```

**Step 3: Remove old Neural Core CSS**

Delete the entire `/* --- Neural Core Visualization --- */` CSS block (from `@keyframes orbitalDrift` through the `@media (max-width: 500px)` block that ends with `.nc-container { max-height: 200px; ... }`). This is approximately lines 46-257 of the current file. All these styles are now in `holo-sphere.css`.

**Step 4: Remove old `.cs-tab` CSS**

Delete the `.cs-tab` CSS block (approximately lines 632-676 which includes `.cs-tabs`, `.cs-tab`, `.cs-tab:hover`, `.cs-tab.active`, `.cs-tab::after`, `.cs-tab.active::after`). These are replaced by `glass-nav.css`.

**Step 5: Verify** — Reload the page, confirm no 404 errors for new CSS/JS files in browser console.

**Step 6: Commit**
```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(consciousness): add holo-sphere + glass-nav assets, remove old NC/tab CSS"
```

---

### Task 6: Update consciousness_dashboard.html — Replace Nav HTML

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

**Step 1: Replace the `<nav class="cs-tabs">` block (lines ~1876-1905) with GlassNav markup**

```html
    <nav class="glass-nav" id="csNav">
        <div class="glass-nav-track">
            <div class="glass-nav-indicator"></div>
            <button class="glass-nav-item active" data-tab="dashboard">
                <i data-lucide="layout-dashboard"></i>
                <span data-i18n="consciousness.tabs.dashboard">Dashboard</span>
            </button>
            <button class="glass-nav-item" data-tab="knowledge">
                <i data-lucide="book-open"></i>
                <span data-i18n="consciousness.tabs.knowledge">Knowledge</span>
            </button>
            <button class="glass-nav-item" data-tab="team">
                <i data-lucide="users"></i>
                <span data-i18n="consciousness.tabs.team">Team</span>
            </button>
            <button class="glass-nav-item" data-tab="insights">
                <i data-lucide="bar-chart-3"></i>
                <span data-i18n="consciousness.tabs.insights">Insights</span>
            </button>
            <button class="glass-nav-item" data-tab="languages">
                <i data-lucide="languages"></i>
                <span data-i18n="consciousness.tabs.languages">Languages</span>
            </button>
            <button class="glass-nav-item" data-tab="github">
                <i data-lucide="github"></i>
                <span data-i18n="consciousness.tabs.github">GitHub</span>
            </button>
            <button class="glass-nav-item" data-tab="integration">
                <i data-lucide="plug"></i>
                <span data-i18n="consciousness.tabs.integration">Integration</span>
            </button>
        </div>
    </nav>
```

Note: Remove the `onclick="switchConsciousnessTab(...)"` from each button — GlassNav handles click events internally.

**Step 2: Commit**
```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(consciousness): replace cs-tabs with GlassNav HTML"
```

---

### Task 7: Update consciousness_dashboard.html — Replace Neural Core HTML

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

**Step 1: Replace the Neural Core container + Stats HUD**

Find the `<div class="nc-container" id="neuralCore">` block through the closing `</div>` of `.nc-stats-hud` (lines ~1915-1985). Replace the entire block with:

```html
            <!-- Holographic Sphere (rendered by holo-sphere.js) -->
            <div id="neuralCore"></div>

            <!-- Stats HUD -->
            <div class="holo-hud">
                <div class="holo-hud-item purple">
                    <span class="holo-hud-value" id="ncTotalKnowledge">--</span>
                    <span class="holo-hud-label">Knowledge</span>
                </div>
                <div class="holo-hud-item blue">
                    <span class="holo-hud-value" id="ncGitHubFiles">--</span>
                    <span class="holo-hud-label">GitHub Files</span>
                </div>
                <div class="holo-hud-item green">
                    <span class="holo-hud-value" id="ncEmbedPct">--</span>
                    <span class="holo-hud-label">Embedded</span>
                </div>
                <div class="holo-hud-item amber">
                    <span class="holo-hud-value" id="ncActiveAgents">--</span>
                    <span class="holo-hud-label">Agents</span>
                </div>
            </div>
```

The `#neuralCore` div is now just an empty container — HoloSphere.js will build all the DOM inside it.

**Step 2: Commit**
```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(consciousness): replace old NC HTML with HoloSphere container"
```

---

### Task 8: Update consciousness.js — Replace Neural Core with HoloSphere

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`

**Step 1: Add module-level sphere variable**

At the top of the file (after the existing `var _cache = ...` and similar module vars, around line 5-10), add:

```javascript
var _holoSphere = null;
var _glassNav = null;
```

**Step 2: Replace `loadNeuralCore()` function (lines ~200-249)**

Replace the entire `loadNeuralCore()` function with:

```javascript
function loadNeuralCore() {
  var container = document.getElementById("neuralCore");
  if (!container) return;

  // Destroy previous instance if exists
  if (_holoSphere) { _holoSphere.destroy(); _holoSphere = null; }

  // Fetch data then build sphere
  api("/api/dashboard/summary").then(function(data) {
    if (!data.success) return;
    var kb = data.knowledge || {};
    var agents = data.agents || {};

    // Build node array from knowledge data
    var nodes = [
      { id: "conversations", label: "Conv", count: kb.conversations || 0, color: "#3b82f6", tab: "knowledge" },
      { id: "code", label: "Code", count: (kb.github_files || 0) + (kb.code_snippets || 0), color: "#22c55e", tab: "github" },
      { id: "vault", label: "Vault", count: kb.vault_notes || 0, color: "#8b5cf6", tab: "knowledge" },
      { id: "repos", label: "Repos", count: kb.repos || 0, color: "#f59e0b", tab: "github" },
      { id: "learned", label: "Learn", count: (kb.mistakes || 0) + (kb.improvements || 0), color: "#06b6d4", tab: "insights" },
      { id: "sessions", label: "Sessions", count: kb.sessions || 0, color: "#ec4899", tab: "insights" }
    ];

    _holoSphere = new HoloSphere(container, {
      nodes: nodes,
      mood: "focused",
      particleCount: 120,
      ambientDust: true,
      ambientTarget: document.querySelector(".cs-body"),
      onNodeClick: function(node) {
        if (node.tab) switchConsciousnessTab(node.tab);
      }
    });

    // Stats HUD
    setHtml("ncTotalKnowledge", (kb.total_entries || kb.total || 0).toLocaleString());
    setHtml("ncActiveAgents", (agents.active || 0) + "/" + (agents.total || 0));
  }).catch(function(err) {
    console.error("Neural core data error:", err);
  });

  // Fetch GitHub stats for embed coverage
  api("/github/stats").then(function(data) {
    if (data.success) {
      setHtml("ncGitHubFiles", (data.total_files || 0).toLocaleString());
      setHtml("ncEmbedPct", (data.embed_pct || 0) + "%");
    }
  }).catch(function() {});

  // Fetch emotional state
  api("/emotional-state").then(function(data) {
    var mood = (data.mood || "focused").toLowerCase();
    if (_holoSphere) _holoSphere.setMood(mood);
  }).catch(function() {});
}
```

**Step 3: Delete old Neural Core functions**

Delete these blocks entirely:
- `var _ncMoodColors = { ... };` (lines ~190-198)
- `function _shortNum(n) { ... }` (lines ~251-255)
- The entire `/* ── Circuit Pathways (SVG) ─── */` section including `function _drawPathways()` (lines ~257-305)
- `var _particleAnim = null;` and `var _particles = [];` (lines ~309-310)
- The entire `/* ── Particle System (Canvas) ─── */` section including `function _initParticles()` (lines ~312-358)

Note: `_shortNum` is no longer needed because HoloSphere has its own `shortNum()` internally.

**Step 4: Update `switchConsciousnessTab()` for GlassNav**

Find the `switchConsciousnessTab` function (lines ~86-99). Replace the tab button toggling (lines 87-88) with GlassNav:

```javascript
window.switchConsciousnessTab = function (tab) {
  // Update glass nav indicator
  if (_glassNav) _glassNav.setActive(tab);

  // Toggle panels
  document.querySelectorAll(".cs-panel").forEach(function (panel) {
    panel.classList.toggle("active", panel.id === "panel-" + tab);
  });
  history.replaceState(null, "", "#" + tab);
  loadTabData(tab);
  if (tab === "knowledge" || tab === "github") {
    checkActiveJobs();
  }
};
```

**Step 5: Initialize GlassNav in the DOMContentLoaded handler**

Find the `DOMContentLoaded` event listener (near the end of the file). Add GlassNav initialization before the hash-based tab routing:

```javascript
  // Initialize Glass Nav
  var navEl = document.getElementById("csNav");
  if (navEl) {
    _glassNav = new GlassNav(navEl, {
      onSwitch: function(tab) { switchConsciousnessTab(tab); }
    });
  }
```

**Step 6: Add resize handler for HoloSphere**

In the same DOMContentLoaded handler, add:

```javascript
  // Resize handler for HoloSphere
  window.addEventListener("resize", function() {
    if (_holoSphere) _holoSphere.resize();
  });
```

**Step 7: Verify** — Reload the page. Confirm:
- Holographic sphere renders with 5 rotating rings
- Knowledge nodes float inside the sphere
- Particles orbit with glow effects
- Ambient dust visible across the page
- Scanlines visible on the sphere
- Glass nav bar at top with sliding indicator
- Tab switching works via glass nav
- Stats HUD shows real numbers
- No console errors

**Step 8: Commit**
```bash
git add platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): wire HoloSphere + GlassNav, remove old NC code"
```

---

## Phase 3: Polish

### Task 9: Visual Tuning and Browser Verification

**Files:**
- Potentially modify: any of the 4 new files + 2 modified files

**Step 1: Full visual verification**

Open http://192.168.1.200:3000/consciousness in browser and check:

1. **Sphere appearance** — 5 rings visible and rotating at different speeds? Holographic glow breathing? Scanlines scrolling?
2. **Nodes** — All 6 knowledge nodes visible inside sphere? Depth effect working (back nodes dimmer)? Hover scales up?
3. **Particles** — Inner particles orbiting with glow? Energy streams flowing between nodes? Ambient dust across page?
4. **Effects** — Data pulse on load? Surface energy sweep cycling?
5. **Nav** — Glass bar frosted? Indicator slides smoothly between tabs? All 7 tabs work?
6. **Stats HUD** — All 4 values populated from API?
7. **Responsive** — Check at 768px and 500px breakpoints
8. **Performance** — Open DevTools Performance tab, confirm 60fps

**Step 2: Fix any visual issues found**

Adjust CSS values (ring speeds, glow intensity, particle count, colors) based on what looks right in the browser. Common tuning:
- Ring border opacity (too visible or invisible?)
- Particle glow blur (too bright or too dim?)
- Ambient dust alpha (visible or invisible?)
- Glass nav blur strength
- Node size at various breakpoints

**Step 3: Commit any fixes**
```bash
git add -A
git commit -m "fix(consciousness): visual tuning for HoloSphere + GlassNav"
```

---

### Task 10: Final Verification and Cleanup

**Step 1: Check for any remaining references to old code**

Search consciousness.js for any remaining `nc-` class references, `_drawPathways`, `_initParticles`, `_ncMoodColors`, `showAddRepoModal` references. Remove any dead code.

Search consciousness_dashboard.html for any remaining `.nc-` CSS classes or `.cs-tab` CSS. Remove any dead styles.

**Step 2: Restart Docker container to confirm clean deployment**

```bash
docker compose restart archie_platform
```

Wait for startup, then verify http://192.168.1.200:3000/consciousness loads cleanly.

**Step 3: Commit any cleanup**
```bash
git add -A
git commit -m "chore(consciousness): remove dead NC/tab references after HoloSphere migration"
```
