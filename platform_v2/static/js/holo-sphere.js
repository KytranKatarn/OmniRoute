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

/* ── Event Bridge (matches NeuralCore API) ────────── */

HoloSphere.prototype.fireEvent = function(type, data) {
  data = data || {};
  var EVENT_COLORS = {
    "job:started": "#f59e0b",
    "job:completed": "#22c55e",
    "job:failed": "#ef4444",
    "knowledge:added": "#8b5cf6"
  };

  switch (type) {
    case "job:started":
      this._firePulse(EVENT_COLORS["job:started"]);
      break;

    case "job:completed":
      this._firePulse(EVENT_COLORS["job:completed"]);
      this._fireGlitch();
      break;

    case "job:failed":
      this._firePulse(EVENT_COLORS["job:failed"]);
      break;

    case "knowledge:added":
      if (data.node && this._nodeEls[data.node]) {
        this._fireBurst(this._nodeEls[data.node]);
        this._fireGlitch();
      } else {
        this._firePulse(EVENT_COLORS["knowledge:added"]);
      }
      break;
  }
};

HoloSphere.prototype.addAgent = function() {
  // Stub — HoloSphere does not render individual agents
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
