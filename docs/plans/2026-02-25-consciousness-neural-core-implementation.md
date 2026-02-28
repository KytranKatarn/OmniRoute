# Consciousness Neural Core — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the Consciousness module Dashboard with an animated Neural Core visualization and restructure the GitHub tab into Intake/Cards/Discovery zones.

**Architecture:** The Neural Core is a pure HTML/CSS/Canvas visualization wired to existing APIs. No external libraries — Canvas for particles, SVG for pathways, CSS for orbital animations. The GitHub tab is restructured HTML/JS using existing route endpoints. All changes are in 2 files: `consciousness_dashboard.html` (template+CSS) and `consciousness.js` (JS logic).

**Tech Stack:** HTML5 Canvas, inline SVG, CSS animations (transform/opacity only), vanilla JS, existing Flask API endpoints.

**Design Doc:** `docs/plans/2026-02-25-consciousness-neural-core-design.md`

---

## Phase 1: Neural Core Dashboard

### Task 1: Neural Core CSS Foundation

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (CSS section, lines 15-260)

**Step 1: Add Neural Core CSS after existing animations (line ~46)**

Add these CSS rules after the existing `@keyframes` block and before `.cs-container`:

```css
/* --- Neural Core Visualization --- */
@keyframes orbitalDrift {
    0%   { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
@keyframes orbitalDriftReverse {
    0%   { transform: rotate(360deg); }
    100% { transform: rotate(0deg); }
}
@keyframes particleFlow {
    0%   { offset-distance: 0%; opacity: 0; }
    10%  { opacity: 1; }
    90%  { opacity: 1; }
    100% { offset-distance: 100%; opacity: 0; }
}
@keyframes coreBreath {
    0%, 100% { transform: scale(1); filter: brightness(1); }
    50%      { transform: scale(1.04); filter: brightness(1.15); }
}
@keyframes nodeGlow {
    0%, 100% { box-shadow: 0 0 8px var(--node-color); }
    50%      { box-shadow: 0 0 20px var(--node-color), 0 0 40px var(--node-color); }
}

@media (prefers-reduced-motion: reduce) {
    .nc-orbital-ring, .nc-core, .nc-particle, .nc-pathway { animation: none !important; }
}

.nc-container {
    position: relative;
    width: 100%;
    max-width: 700px;
    margin: 0 auto 24px;
    aspect-ratio: 1 / 0.85;
    max-height: 500px;
}

/* Center core node */
.nc-core {
    position: absolute;
    top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    width: 100px; height: 100px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(139,92,246,0.25) 0%, rgba(139,92,246,0.05) 70%, transparent 100%);
    border: 2px solid rgba(139,92,246,0.4);
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    z-index: 10;
    animation: coreBreath 4s ease-in-out infinite;
    cursor: default;
    transition: border-color 0.8s, background 0.8s;
}
.nc-core-name {
    font-family: 'Orbitron', sans-serif;
    font-size: 0.65rem; font-weight: 700;
    color: #8b5cf6; letter-spacing: 2px;
}
.nc-core-mood {
    font-family: 'Antonio', sans-serif;
    font-size: 0.6rem; color: rgba(255,255,255,0.5);
    text-transform: uppercase; letter-spacing: 1px;
    margin-top: 2px;
}
.nc-core-ring {
    position: absolute; inset: -6px;
    border-radius: 50%;
    border: 1px solid rgba(139,92,246,0.2);
    animation: coreBreath 4s ease-in-out infinite reverse;
}

/* Orbital rings */
.nc-orbital-ring {
    position: absolute;
    top: 50%; left: 50%;
    border-radius: 50%;
    border: 1px solid rgba(139,92,246,0.06);
}
.nc-ring-inner {
    width: 280px; height: 280px;
    margin-left: -140px; margin-top: -140px;
    animation: orbitalDrift 60s linear infinite;
}
.nc-ring-outer {
    width: 460px; height: 460px;
    margin-left: -230px; margin-top: -230px;
    animation: orbitalDrift 120s linear infinite reverse;
    border-style: dashed;
}

/* Knowledge cluster nodes (inner ring) */
.nc-node {
    position: absolute;
    width: 48px; height: 48px;
    border-radius: 50%;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
    --node-color: #8b5cf6;
    border: 1.5px solid var(--node-color);
    background: radial-gradient(circle, color-mix(in srgb, var(--node-color) 15%, transparent) 0%, transparent 80%);
    animation: orbitalDriftReverse 60s linear infinite; /* counter-rotate to stay upright */
}
.nc-node:hover {
    transform: scale(1.2);
    box-shadow: 0 0 20px var(--node-color);
    z-index: 20;
}
.nc-node-count {
    font-family: 'Orbitron', sans-serif;
    font-size: 0.6rem; font-weight: 700;
    color: var(--node-color);
}
.nc-node-label {
    font-family: 'Antonio', sans-serif;
    font-size: 0.45rem; font-weight: 500;
    color: rgba(255,255,255,0.5);
    text-transform: uppercase; letter-spacing: 0.5px;
    white-space: nowrap;
}

/* Node color variants */
.nc-node.conversations { --node-color: #3b82f6; }
.nc-node.code          { --node-color: #22c55e; }
.nc-node.vault         { --node-color: #8b5cf6; }
.nc-node.repos         { --node-color: #f59e0b; }
.nc-node.learned       { --node-color: #06b6d4; }
.nc-node.sessions      { --node-color: #ec4899; }

/* Outer ring dots */
.nc-dot {
    position: absolute;
    width: 6px; height: 6px;
    border-radius: 50%;
    animation: orbitalDriftReverse 120s linear infinite;
    opacity: 0.6;
    transition: opacity 0.2s, transform 0.2s;
}
.nc-dot:hover { opacity: 1; transform: scale(2); }

/* Circuit pathways (SVG) */
.nc-pathways {
    position: absolute; inset: 0;
    pointer-events: none;
    z-index: 5;
}
.nc-pathway {
    fill: none;
    stroke: rgba(139,92,246,0.08);
    stroke-width: 1;
}
.nc-pathway.active {
    stroke: rgba(139,92,246,0.25);
    stroke-dasharray: 8 4;
    stroke-dashoffset: 0;
    animation: pathFlow 2s linear infinite;
}
@keyframes pathFlow {
    to { stroke-dashoffset: -24; }
}

/* Particle canvas */
.nc-particle-layer {
    position: absolute; inset: 0;
    pointer-events: none;
    z-index: 6;
}

/* Stats HUD below visualization */
.nc-stats-hud {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 20px;
}
.nc-hud-item {
    display: flex; flex-direction: column;
    align-items: center; padding: 10px 8px;
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
}
.nc-hud-value {
    font-family: 'Orbitron', sans-serif;
    font-size: 1.1rem; font-weight: 700;
}
.nc-hud-label {
    font-family: 'Antonio', sans-serif;
    font-size: 0.65rem; color: rgba(255,255,255,0.4);
    text-transform: uppercase; letter-spacing: 1px;
    margin-top: 2px;
}
.nc-hud-item.purple .nc-hud-value { color: #8b5cf6; }
.nc-hud-item.blue .nc-hud-value   { color: #3b82f6; }
.nc-hud-item.green .nc-hud-value  { color: #22c55e; }
.nc-hud-item.amber .nc-hud-value  { color: #f59e0b; }

/* Responsive */
@media (max-width: 767px) {
    .nc-container { max-height: 300px; }
    .nc-ring-outer { display: none; }
    .nc-ring-inner { width: 220px; height: 220px; margin-left: -110px; margin-top: -110px; }
    .nc-core { width: 80px; height: 80px; }
    .nc-node { width: 38px; height: 38px; }
    .nc-stats-hud { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 500px) {
    .nc-ring-inner { display: none; }
    .nc-container { max-height: 200px; aspect-ratio: auto; height: 200px; }
}
```

**Step 2: Verify** — Open http://192.168.1.200:3000/consciousness in browser, confirm no CSS errors in console.

**Step 3: Commit**
```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(consciousness): add Neural Core CSS foundation"
```

---

### Task 2: Neural Core HTML Structure

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (Dashboard panel, lines ~1425-1517)

**Step 1: Replace the Dashboard panel content**

Replace the existing `panel-dashboard` div contents (stat cards, activity/wellness, integration health, brain map) with:

```html
<div class="cs-panel active" id="panel-dashboard">

    <!-- Neural Core Visualization -->
    <div class="nc-container" id="neuralCore">
        <!-- SVG Circuit Pathways (background) -->
        <svg class="nc-pathways" id="ncPathways" viewBox="0 0 700 595" preserveAspectRatio="xMidYMid meet"></svg>

        <!-- Particle Canvas (overlay) -->
        <canvas class="nc-particle-layer" id="ncParticles"></canvas>

        <!-- Outer Ring (recent entries) -->
        <div class="nc-orbital-ring nc-ring-outer" id="ncOuterRing"></div>

        <!-- Inner Ring (knowledge clusters) -->
        <div class="nc-orbital-ring nc-ring-inner" id="ncInnerRing">
            <div class="nc-node conversations" data-tab="knowledge" style="top:-24px; left:50%; margin-left:-24px;"
                 title="Conversations" onclick="switchConsciousnessTab('knowledge')">
                <span class="nc-node-count" id="ncConvCount">--</span>
                <span class="nc-node-label">Conv</span>
            </div>
            <div class="nc-node code" data-tab="knowledge" style="top:20%; right:-24px;"
                 title="Code & GitHub Files" onclick="switchConsciousnessTab('github')">
                <span class="nc-node-count" id="ncCodeCount">--</span>
                <span class="nc-node-label">Code</span>
            </div>
            <div class="nc-node vault" data-tab="knowledge" style="bottom:20%; right:-24px;"
                 title="Vault Notes" onclick="switchConsciousnessTab('knowledge')">
                <span class="nc-node-count" id="ncVaultCount">--</span>
                <span class="nc-node-label">Vault</span>
            </div>
            <div class="nc-node repos" data-tab="github" style="bottom:-24px; left:50%; margin-left:-24px;"
                 title="GitHub Repositories" onclick="switchConsciousnessTab('github')">
                <span class="nc-node-count" id="ncRepoCount">--</span>
                <span class="nc-node-label">Repos</span>
            </div>
            <div class="nc-node learned" data-tab="insights" style="bottom:20%; left:-24px;"
                 title="Learned & Improved" onclick="switchConsciousnessTab('insights')">
                <span class="nc-node-count" id="ncLearnedCount">--</span>
                <span class="nc-node-label">Learn</span>
            </div>
            <div class="nc-node sessions" data-tab="insights" style="top:20%; left:-24px;"
                 title="Sessions" onclick="switchConsciousnessTab('insights')">
                <span class="nc-node-count" id="ncSessionCount">--</span>
                <span class="nc-node-label">Sessions</span>
            </div>
        </div>

        <!-- Center Core Node -->
        <div class="nc-core" id="ncCoreNode">
            <div class="nc-core-ring"></div>
            <span class="nc-core-name">A.R.C.H.I.E.</span>
            <span class="nc-core-mood" id="ncCoreMood">focused</span>
        </div>
    </div>

    <!-- Stats HUD -->
    <div class="nc-stats-hud">
        <div class="nc-hud-item purple">
            <span class="nc-hud-value" id="ncTotalKnowledge">--</span>
            <span class="nc-hud-label">Knowledge</span>
        </div>
        <div class="nc-hud-item blue">
            <span class="nc-hud-value" id="ncGitHubFiles">--</span>
            <span class="nc-hud-label">GitHub Files</span>
        </div>
        <div class="nc-hud-item green">
            <span class="nc-hud-value" id="ncEmbedPct">--</span>
            <span class="nc-hud-label">Embedded</span>
        </div>
        <div class="nc-hud-item amber">
            <span class="nc-hud-value" id="ncActiveAgents">--</span>
            <span class="nc-hud-label">Agents</span>
        </div>
    </div>

    <!-- Activity + Wellness Row (retained from original) -->
    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px; margin-bottom:20px;">
        <div class="cs-card">
            <div class="cs-card-header" data-i18n="consciousness.dashboard.recent_activity">Recent Activity</div>
            <div class="cs-card-body" id="dashboardActivity">
                <div class="cs-loading" data-i18n="common.loading">Loading...</div>
            </div>
        </div>
        <div class="cs-card">
            <div class="cs-card-header" data-i18n="consciousness.dashboard.fleet_wellness">Fleet Wellness</div>
            <div class="cs-card-body">
                <div class="cs-wellness-row">
                    <span data-i18n="consciousness.dashboard.energy">Energy</span>
                    <div class="cs-wellness-bar"><div class="cs-wellness-fill green" id="wellnessEnergyBar" style="width:0%"></div></div>
                    <span id="wellnessEnergy">--</span>
                </div>
                <div class="cs-wellness-row">
                    <span data-i18n="consciousness.dashboard.stress">Stress</span>
                    <div class="cs-wellness-bar"><div class="cs-wellness-fill red" id="wellnessStressBar" style="width:0%"></div></div>
                    <span id="wellnessStress">--</span>
                </div>
                <div class="cs-wellness-row">
                    <span data-i18n="consciousness.dashboard.mood">Mood</span>
                    <div class="cs-wellness-bar"><div class="cs-wellness-fill purple" id="wellnessMoodBar" style="width:0%"></div></div>
                    <span id="wellnessMood">--</span>
                </div>
            </div>
        </div>
    </div>

    <!-- Integration Health (retained from original) -->
    <div class="cs-card">
        <div class="cs-card-header" data-i18n="consciousness.dashboard.integration_health">Integration Health</div>
        <div class="cs-card-body">
            <div class="cs-integration-grid" id="dashboardIntegration">
                <div class="cs-loading" data-i18n="common.loading">Loading...</div>
            </div>
        </div>
    </div>

</div>
```

**Step 2: Verify** — Reload page, confirm Neural Core structure renders (circles visible, nodes positioned). Data will be `--` until JS is wired.

**Step 3: Commit**
```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(consciousness): add Neural Core HTML structure to Dashboard"
```

---

### Task 3: Neural Core JavaScript — Data Loading

**Files:**
- Modify: `platform_v2/static/js/consciousness.js` (add new section after existing Dashboard functions)

**Step 1: Find the existing `loadDashboard()` function and locate it**

Search for `function loadDashboard` in consciousness.js. The Neural Core data loading will extend this function.

**Step 2: Add Neural Core rendering functions**

Add this block after the existing Dashboard loading code (around line ~200, after the dashboard section):

```javascript
/* ── Neural Core Visualization ──────────────────── */

var _ncMoodColors = {
  focused:    "#8b5cf6",
  curious:    "#06b6d4",
  happy:      "#22c55e",
  processing: "#f59e0b",
  empathetic: "#ec4899",
  neutral:    "#8b5cf6",
  confident:  "#3b82f6"
};

function loadNeuralCore() {
  // Fetch dashboard summary for knowledge counts
  api("/api/dashboard/summary").then(function(data) {
    if (!data.success) return;
    var kb = data.knowledge || {};
    var agents = data.agents || {};

    // Stats HUD
    setHtml("ncTotalKnowledge", (kb.total_entries || 0).toLocaleString());
    setHtml("ncActiveAgents", (agents.active || 0) + "/" + (agents.total || 0));

    // Inner ring node counts
    setHtml("ncConvCount", _shortNum(kb.conversations || 0));
    setHtml("ncCodeCount", _shortNum((kb.github_files || 0) + (kb.code_snippets || 0)));
    setHtml("ncVaultCount", _shortNum(kb.vault_notes || 0));
    setHtml("ncRepoCount", kb.repos || 0);
    setHtml("ncLearnedCount", _shortNum((kb.mistakes || 0) + (kb.improvements || 0)));
    setHtml("ncSessionCount", _shortNum(kb.sessions || 0));
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

  // Fetch emotional state for mood-reactive core
  api("/emotional-state").then(function(data) {
    var mood = (data.mood || "focused").toLowerCase();
    setHtml("ncCoreMood", mood);

    var coreEl = document.getElementById("ncCoreNode");
    if (coreEl) {
      var color = _ncMoodColors[mood] || "#8b5cf6";
      coreEl.style.borderColor = color;
      coreEl.style.background = "radial-gradient(circle, " + color + "40 0%, " + color + "0d 70%, transparent 100%)";
      var nameEl = coreEl.querySelector(".nc-core-name");
      if (nameEl) nameEl.style.color = color;
    }
  }).catch(function() {});

  // Init particles
  _initParticles();
  // Draw pathways
  _drawPathways();
}

function _shortNum(n) {
  if (n >= 10000) return (n / 1000).toFixed(1) + "K";
  if (n >= 1000) return (n / 1000).toFixed(1) + "K";
  return n.toString();
}

/* ── Circuit Pathways (SVG) ─────────────────────── */

function _drawPathways() {
  var svg = document.getElementById("ncPathways");
  if (!svg) return;

  // Center point of the SVG viewBox (700x595)
  var cx = 350, cy = 297;
  // Inner ring node positions (6 nodes at 60° intervals, radius 140)
  var r = 140;
  var nodes = [];
  for (var i = 0; i < 6; i++) {
    var angle = (i * 60 - 90) * Math.PI / 180; // start from top
    nodes.push({ x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
  }

  var paths = "";
  // Connect each node to center with curved paths
  nodes.forEach(function(n, i) {
    var ctrl1x = cx + (n.x - cx) * 0.3;
    var ctrl1y = cy + (n.y - cy) * 0.1;
    var ctrl2x = cx + (n.x - cx) * 0.7;
    var ctrl2y = cy + (n.y - cy) * 0.9;
    paths += '<path class="nc-pathway" d="M' + cx + ',' + cy +
      ' C' + ctrl1x + ',' + ctrl1y + ' ' + ctrl2x + ',' + ctrl2y +
      ' ' + n.x + ',' + n.y + '" />';
  });

  // Connect adjacent nodes
  for (var j = 0; j < nodes.length; j++) {
    var n1 = nodes[j];
    var n2 = nodes[(j + 1) % nodes.length];
    var midX = (n1.x + n2.x) / 2 + (cx - (n1.x + n2.x) / 2) * 0.15;
    var midY = (n1.y + n2.y) / 2 + (cy - (n1.y + n2.y) / 2) * 0.15;
    paths += '<path class="nc-pathway" d="M' + n1.x + ',' + n1.y +
      ' Q' + midX + ',' + midY + ' ' + n2.x + ',' + n2.y + '" />';
  }

  svg.innerHTML = paths;
}

/* ── Particle System (Canvas) ───────────────────── */

var _particleAnim = null;
var _particles = [];

function _initParticles() {
  var canvas = document.getElementById("ncParticles");
  if (!canvas) return;
  var container = canvas.parentElement;
  canvas.width = container.offsetWidth;
  canvas.height = container.offsetHeight;

  var ctx = canvas.getContext("2d");
  var cx = canvas.width / 2, cy = canvas.height / 2;
  var r = Math.min(canvas.width, canvas.height) * 0.2; // inner ring radius

  // Create particles that orbit between center and inner ring
  _particles = [];
  for (var i = 0; i < 15; i++) {
    _particles.push({
      angle: Math.random() * Math.PI * 2,
      radius: r * 0.3 + Math.random() * r * 0.7,
      speed: 0.002 + Math.random() * 0.004,
      size: 2 + Math.random() * 2,
      alpha: 0.3 + Math.random() * 0.5,
      color: ["139,92,246", "59,130,246", "34,197,94", "6,182,212"][Math.floor(Math.random() * 4)]
    });
  }

  if (_particleAnim) cancelAnimationFrame(_particleAnim);

  // Check prefers-reduced-motion
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  function animate() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    _particles.forEach(function(p) {
      p.angle += p.speed;
      var x = cx + Math.cos(p.angle) * p.radius;
      var y = cy + Math.sin(p.angle) * p.radius * 0.85; // slight ellipse
      ctx.beginPath();
      ctx.arc(x, y, p.size, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(" + p.color + "," + p.alpha + ")";
      ctx.shadowColor = "rgba(" + p.color + ",0.4)";
      ctx.shadowBlur = 8;
      ctx.fill();
      ctx.shadowBlur = 0;
    });
    _particleAnim = requestAnimationFrame(animate);
  }
  animate();
}
```

**Step 3: Wire `loadNeuralCore()` into `loadDashboard()`**

Find the existing `loadDashboard()` function and add `loadNeuralCore();` as the first call inside it.

**Step 4: Verify** — Reload page, confirm:
- Neural core visualization appears with data from APIs
- Particles animate smoothly
- SVG pathways visible
- Mood label updates from emotional-state API
- Stats HUD shows real numbers

**Step 5: Commit**
```bash
git add platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): add Neural Core JS — data loading, pathways, particles"
```

---

### Task 4: Dashboard API Enhancement

**Files:**
- Modify: `platform_v2/tools/consciousness/routes.py` (add/update the dashboard summary endpoint)

**Step 1: Check if `/api/dashboard/summary` exists**

Search for `dashboard/summary` in routes.py. If it exists, verify it returns the fields needed:
- `knowledge.total_entries`, `knowledge.conversations`, `knowledge.github_files`, `knowledge.code_snippets`
- `knowledge.vault_notes`, `knowledge.repos`, `knowledge.mistakes`, `knowledge.improvements`, `knowledge.sessions`
- `agents.total`, `agents.active`

**Step 2: Update the endpoint to include all needed fields**

If fields are missing, add queries for:
```sql
-- Knowledge breakdown by type
SELECT knowledge_type, COUNT(*) as count FROM knowledge_base
WHERE knowledge_type != 'archie_v1' GROUP BY knowledge_type;

-- Repo count
SELECT COUNT(*) FROM github_repositories;

-- Session count
SELECT COUNT(*) FROM conversation_sessions;
```

Map results to the expected JSON structure.

**Step 3: Verify** — `curl http://192.168.1.200:3000/tools/consciousness/api/dashboard/summary` returns all expected fields.

**Step 4: Commit**
```bash
git add platform_v2/tools/consciousness/routes.py
git commit -m "feat(consciousness): enhance dashboard summary API for Neural Core"
```

---

## Phase 2: GitHub Tab Restructure

### Task 5: GitHub Tab CSS — Intake Port & Cards

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (CSS section)

**Step 1: Add GitHub tab restructure CSS**

Add after the Neural Core CSS block:

```css
/* --- GitHub Tab: Knowledge Intake --- */
.gh-intake {
    background: rgba(139,92,246,0.03);
    border: 1px solid rgba(139,92,246,0.12);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 20px;
    position: relative;
    overflow: hidden;
}
.gh-intake::before {
    content: '';
    position: absolute; top: 0; left: 0;
    width: 6px; height: 100%;
    background: #8b5cf6;
    border-radius: 6px 0 0 6px;
}
.gh-intake-title {
    font-family: 'Antonio', sans-serif;
    font-size: 0.8rem; font-weight: 600;
    color: rgba(255,255,255,0.5);
    text-transform: uppercase; letter-spacing: 1.5px;
    margin-bottom: 12px; padding-left: 12px;
}
.gh-intake-row {
    display: flex; gap: 10px; align-items: center;
    padding-left: 12px;
}
.gh-intake-input {
    flex: 1; padding: 12px 16px;
    background: rgba(255,255,255,0.04);
    border: 1.5px solid rgba(139,92,246,0.2);
    border-radius: 8px;
    color: #fff; font-size: 0.9rem;
    font-family: 'IBM Plex Mono', monospace;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.gh-intake-input:focus {
    outline: none;
    border-color: #8b5cf6;
    box-shadow: 0 0 16px rgba(139,92,246,0.2);
}
.gh-intake-input::placeholder { color: rgba(255,255,255,0.25); }
.gh-intake-btn {
    padding: 12px 24px;
    background: rgba(139,92,246,0.2);
    border: 1.5px solid rgba(139,92,246,0.5);
    border-radius: 0 20px 20px 0;
    color: #8b5cf6; font-weight: 700;
    font-family: 'Antonio', sans-serif;
    font-size: 0.85rem; letter-spacing: 1px;
    text-transform: uppercase;
    cursor: pointer;
    transition: background 0.2s, color 0.2s;
    white-space: nowrap;
}
.gh-intake-btn:hover {
    background: #8b5cf6;
    color: #fff;
}
.gh-intake-btn:disabled {
    opacity: 0.4; cursor: not-allowed;
}
.gh-intake-options {
    display: none;
    padding: 12px 12px 0;
    gap: 12px;
}
.gh-intake-options.open { display: flex; }
.gh-intake-toggle {
    font-size: 0.72rem; color: rgba(255,255,255,0.3);
    cursor: pointer; padding: 6px 12px; border: none; background: none;
    font-family: 'Antonio', sans-serif; letter-spacing: 0.5px;
}
.gh-intake-toggle:hover { color: rgba(255,255,255,0.6); }
.gh-intake-progress {
    margin-top: 12px; padding-left: 12px;
    display: none;
}
.gh-intake-progress.active { display: block; }
.gh-intake-progress-bar {
    height: 6px; background: rgba(255,255,255,0.06);
    border-radius: 3px; overflow: hidden;
    margin-bottom: 6px;
}
.gh-intake-progress-fill {
    height: 100%; background: linear-gradient(90deg, #8b5cf6, #3b82f6);
    border-radius: 3px; transition: width 0.3s;
    box-shadow: 0 0 8px rgba(139,92,246,0.3);
}

/* --- Repo Intelligence Cards --- */
.gh-cards-header {
    display: flex; align-items: center; gap: 10px;
    margin-bottom: 14px;
}
.gh-cards-header-cap {
    width: 6px; height: 24px; border-radius: 3px;
    background: #8b5cf6; flex-shrink: 0;
}
.gh-cards-header-title {
    font-family: 'Antonio', sans-serif;
    font-size: 0.8rem; font-weight: 600;
    color: rgba(255,255,255,0.5);
    text-transform: uppercase; letter-spacing: 1.5px;
}
.gh-cards-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 14px;
    margin-bottom: 20px;
}
.gh-repo-card {
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 10px;
    padding: 16px;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s, box-shadow 0.2s;
    cursor: pointer;
}
.gh-repo-card:hover {
    border-color: rgba(139,92,246,0.25);
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}
.gh-repo-card::before {
    content: '';
    position: absolute; top: 0; left: 0;
    width: 4px; height: 100%;
    border-radius: 4px 0 0 4px;
}
.gh-repo-card.coverage-high::before   { background: #22c55e; }
.gh-repo-card.coverage-mid::before    { background: #f59e0b; }
.gh-repo-card.coverage-low::before    { background: #ef4444; }
.gh-repo-card-name {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.85rem; font-weight: 500;
    color: rgba(255,255,255,0.85);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    margin-bottom: 10px;
}
.gh-repo-card-row {
    display: flex; align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}
/* SVG circular progress ring */
.gh-progress-ring {
    width: 48px; height: 48px; flex-shrink: 0;
}
.gh-progress-ring-bg {
    fill: none; stroke: rgba(255,255,255,0.06); stroke-width: 4;
}
.gh-progress-ring-fill {
    fill: none; stroke-width: 4; stroke-linecap: round;
    transition: stroke-dashoffset 0.6s ease;
}
.gh-repo-card-meta {
    font-size: 0.72rem; color: rgba(255,255,255,0.4);
    display: flex; gap: 8px; flex-wrap: wrap;
    margin-top: 8px;
}
.gh-repo-card-meta span {
    display: inline-flex; align-items: center; gap: 3px;
}
.gh-repo-card-actions {
    display: flex; gap: 6px; margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid rgba(255,255,255,0.06);
}
.gh-repo-card-actions button, .gh-repo-card-actions a {
    padding: 5px 10px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 6px;
    color: rgba(255,255,255,0.5);
    font-size: 0.7rem; font-family: 'Antonio', sans-serif;
    letter-spacing: 0.5px; text-transform: uppercase;
    cursor: pointer; text-decoration: none;
    transition: all 0.15s;
}
.gh-repo-card-actions button:hover, .gh-repo-card-actions a:hover {
    background: rgba(139,92,246,0.15);
    border-color: rgba(139,92,246,0.3);
    color: #8b5cf6;
}
.gh-repo-card-actions .danger:hover {
    background: rgba(239,68,68,0.15);
    border-color: rgba(239,68,68,0.3);
    color: #ef4444;
}

/* --- Discovery Console --- */
.gh-discovery {
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 12px;
    padding: 20px;
    position: relative;
}
.gh-discovery::before {
    content: '';
    position: absolute; top: 0; left: 0;
    width: 6px; height: 100%;
    background: #06b6d4;
    border-radius: 6px 0 0 6px;
}
.gh-discovery-title {
    font-family: 'Antonio', sans-serif;
    font-size: 0.8rem; font-weight: 600;
    color: rgba(255,255,255,0.5);
    text-transform: uppercase; letter-spacing: 1.5px;
    margin-bottom: 12px; padding-left: 12px;
}
.gh-discovery-input {
    width: 100%; padding: 12px 16px;
    background: rgba(255,255,255,0.04);
    border: 1.5px solid rgba(6,182,212,0.2);
    border-radius: 8px; box-sizing: border-box;
    color: #fff; font-size: 0.9rem;
    font-family: 'IBM Plex Mono', monospace;
    transition: border-color 0.2s, box-shadow 0.2s;
    margin-left: 12px; width: calc(100% - 12px);
}
.gh-discovery-input:focus {
    outline: none;
    border-color: #06b6d4;
    box-shadow: 0 0 16px rgba(6,182,212,0.2);
}
.gh-discovery-results {
    margin-top: 14px; padding-left: 12px;
}
.gh-discovery-result {
    padding: 10px 12px;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    margin-bottom: 8px;
    transition: border-color 0.15s;
}
.gh-discovery-result:hover {
    border-color: rgba(6,182,212,0.2);
}
.gh-discovery-result-path {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem; color: #06b6d4;
}
.gh-discovery-result-repo {
    font-size: 0.68rem; color: rgba(255,255,255,0.3);
    margin-left: 8px;
}
.gh-discovery-result-score {
    float: right; font-family: 'Orbitron', sans-serif;
    font-size: 0.65rem; color: #22c55e;
}
.gh-discovery-result-snippet {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75rem; color: rgba(255,255,255,0.4);
    margin-top: 6px; padding: 6px 8px;
    background: rgba(0,0,0,0.2); border-radius: 4px;
    white-space: pre-wrap; max-height: 80px; overflow: hidden;
}
```

**Step 2: Commit**
```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(consciousness): add GitHub tab restructure CSS — intake, cards, discovery"
```

---

### Task 6: GitHub Tab HTML Restructure

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (GitHub panel, lines ~1819-1883)

**Step 1: Replace the `panel-github` contents**

Replace the entire `<div class="cs-panel" id="panel-github">...</div>` with:

```html
<div class="cs-panel" id="panel-github">

    <!-- Zone 1: Knowledge Intake Port -->
    <div class="gh-intake">
        <div class="gh-intake-title">Knowledge Intake</div>
        <div class="gh-intake-row">
            <input type="text" class="gh-intake-input" id="ghIntakeUrl"
                   placeholder="https://github.com/owner/repo"
                   onkeydown="if(event.key==='Enter')ingestRepo()">
            <button class="gh-intake-btn" id="ghIntakeBtn" onclick="ingestRepo()">Ingest</button>
        </div>
        <button class="gh-intake-toggle" onclick="toggleIntakeOptions()">Options</button>
        <div class="gh-intake-options" id="ghIntakeOptions">
            <div>
                <label style="display:block; margin-bottom:4px; font-size:0.72rem; color:rgba(255,255,255,0.4);">Type</label>
                <select id="ghIntakeType" style="padding:8px 12px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:#fff; font-size:0.82rem;">
                    <option value="">Auto-detect</option>
                    <option value="ai-agents">AI Agents</option>
                    <option value="claude-skills">Claude Skills</option>
                    <option value="ai-tools">AI Tools</option>
                    <option value="python">Python</option>
                    <option value="skills-library">Skills Library</option>
                    <option value="reference">Reference</option>
                </select>
            </div>
            <div>
                <label style="display:block; margin-bottom:4px; font-size:0.72rem; color:rgba(255,255,255,0.4);">Max Files</label>
                <input type="number" id="ghIntakeMax" value="2000"
                       style="width:80px; padding:8px 12px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:#fff; font-size:0.82rem;">
            </div>
        </div>
        <div class="gh-intake-progress" id="ghIntakeProgress">
            <div class="gh-intake-progress-bar">
                <div class="gh-intake-progress-fill" id="ghIntakeFill" style="width:0%"></div>
            </div>
            <span style="font-size:0.72rem; color:rgba(255,255,255,0.4);" id="ghIntakeStatus">Indexing...</span>
        </div>
        <div id="ghIntakeResult" style="padding-left:12px; margin-top:8px;"></div>
    </div>

    <!-- LCARS Readout Strips (retained) -->
    <div class="cs-gh-readouts">
        <div class="cs-gh-strip purple">
            <div class="cs-gh-cap"></div>
            <div class="cs-gh-strip-icon"><i data-lucide="git-branch"></i></div>
            <div class="cs-gh-strip-label">Repositories</div>
            <div class="cs-gh-strip-line"></div>
            <div class="cs-gh-strip-value" id="ghRepoCount">--</div>
        </div>
        <div class="cs-gh-strip blue">
            <div class="cs-gh-cap"></div>
            <div class="cs-gh-strip-icon"><i data-lucide="file-code"></i></div>
            <div class="cs-gh-strip-label">Files Indexed</div>
            <div class="cs-gh-strip-line"></div>
            <div class="cs-gh-strip-value" id="ghFileCount">--</div>
        </div>
        <div class="cs-gh-strip green">
            <div class="cs-gh-cap"></div>
            <div class="cs-gh-strip-icon"><i data-lucide="database"></i></div>
            <div class="cs-gh-strip-label">Embedded</div>
            <div class="cs-gh-strip-line"></div>
            <div class="cs-gh-strip-value" id="ghEmbedPct">--</div>
        </div>
        <div class="cs-gh-strip amber">
            <div class="cs-gh-cap"></div>
            <div class="cs-gh-strip-icon"><i data-lucide="search"></i></div>
            <div class="cs-gh-strip-label">Searchable</div>
            <div class="cs-gh-strip-line"></div>
            <div class="cs-gh-strip-value" id="ghSearchable">--</div>
        </div>
    </div>

    <!-- Zone 2: Repository Intelligence Cards -->
    <div class="gh-cards-header">
        <div class="gh-cards-header-cap"></div>
        <div class="gh-cards-header-title">Indexed Repositories</div>
        <div style="flex:1;"></div>
        <div style="display:flex; gap:6px;">
            <button class="cs-ops-cmd amber" onclick="reindexAllRepos()" id="btnReindexAll" style="font-size:0.65rem; padding:4px 10px;">Reindex All</button>
            <button class="cs-ops-cmd green" onclick="embedGitHubFiles()" id="btnEmbedGH" style="font-size:0.65rem; padding:4px 10px;">Embed Files</button>
            <button class="cs-ops-cmd cyan" onclick="verifyGitHubData()" style="font-size:0.65rem; padding:4px 10px;">Verify</button>
        </div>
    </div>
    <div class="gh-cards-grid" id="ghRepoGrid">
        <div class="cs-loading">Loading repositories...</div>
    </div>

    <!-- Active jobs display -->
    <div id="ghOpsJobs" style="margin-bottom:16px;"></div>

    <!-- Zone 3: Discovery Console -->
    <div class="gh-discovery">
        <div class="gh-discovery-title">Discovery</div>
        <input type="text" class="gh-discovery-input" id="ghDiscoveryInput"
               placeholder="Search ARCHIE's indexed knowledge..."
               onkeydown="if(event.key==='Enter')searchGithubSemantic()">
        <div class="gh-discovery-results" id="ghDiscoveryResults"></div>
    </div>
</div>
```

**Step 2: Remove the Add Repository modal** (lines ~1975-2040) — no longer needed since intake is inline. Keep the Verify modal.

**Step 3: Commit**
```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(consciousness): restructure GitHub tab HTML — intake, cards, discovery"
```

---

### Task 7: GitHub Tab JavaScript — New Rendering

**Files:**
- Modify: `platform_v2/static/js/consciousness.js` (GitHub tab section)

**Step 1: Update `loadGitHub()` to render repo cards instead of flat rows**

Replace the existing `loadGitHub()` function with:

```javascript
function loadGitHub() {
  api("/api/github/repos").then(function(data) {
    if (!data.success) return;
    var repos = data.repos || [];
    setHtml("ghRepoCount", repos.length);

    if (!repos.length) {
      setHtml("ghRepoGrid",
        '<div style="grid-column:1/-1; text-align:center; padding:40px 20px; color:rgba(255,255,255,0.3);">' +
        '<div style="font-size:2rem; margin-bottom:8px;">&#x1f4e1;</div>' +
        '<div style="font-family:Antonio,sans-serif; font-size:0.85rem; letter-spacing:1px; text-transform:uppercase;">No repositories indexed</div>' +
        '<div style="font-size:0.75rem; margin-top:4px;">Paste a GitHub URL above to begin learning</div>' +
        '</div>');
      return;
    }

    var html = '';
    repos.forEach(function(r) {
      var pct = 0;
      // embed pct calculated from file stats if available
      var coverageCls = 'coverage-low';
      if (r.indexed && r.indexed_files > 0) {
        coverageCls = 'coverage-mid';
        // Will be updated by embed stats
      }

      var circumference = 2 * Math.PI * 18; // radius 18
      var dashoffset = circumference; // 0% by default

      html += '<div class="gh-repo-card ' + coverageCls + '" data-repo-id="' + r.id + '">' +
        '<div class="gh-repo-card-name" title="' + escHtml(r.repo_name) + '">' + escHtml(r.repo_name) + '</div>' +
        '<div class="gh-repo-card-row">' +
          '<svg class="gh-progress-ring" viewBox="0 0 44 44">' +
            '<circle class="gh-progress-ring-bg" cx="22" cy="22" r="18" />' +
            '<circle class="gh-progress-ring-fill" cx="22" cy="22" r="18"' +
              ' stroke="#22c55e" stroke-dasharray="' + circumference + '"' +
              ' stroke-dashoffset="' + dashoffset + '"' +
              ' transform="rotate(-90 22 22)" data-repo="' + r.id + '" />' +
          '</svg>' +
          '<div style="flex:1; padding-left:12px;">' +
            '<div style="font-family:Orbitron,sans-serif; font-size:0.9rem; font-weight:700; color:' +
              (r.indexed ? '#22c55e' : '#f59e0b') + ';">' + (r.indexed_files || 0) + ' <span style="font-size:0.65rem; color:rgba(255,255,255,0.4);">files</span></div>' +
            '<div style="font-size:0.7rem; color:rgba(255,255,255,0.35);">' +
              (r.indexed ? 'Indexed ' + formatAge(r.indexed_at) : 'Pending') + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="gh-repo-card-meta">' +
          (r.repo_type ? '<span>' + escHtml(r.repo_type) + '</span>' : '') +
          (r.status ? '<span>' + escHtml(r.status) + '</span>' : '') +
        '</div>' +
        '<div class="gh-repo-card-actions">' +
          '<button onclick="event.stopPropagation(); reindexRepo(' + r.id + ')">Re-index</button>' +
          '<button class="danger" onclick="event.stopPropagation(); deleteRepo(' + r.id + ', \'' + escHtml(r.repo_name) + '\')">Delete</button>' +
          '<a href="https://github.com/' + escHtml(r.repo_name) + '" target="_blank" onclick="event.stopPropagation();">Open</a>' +
        '</div>' +
      '</div>';
    });
    setHtml("ghRepoGrid", html);
    refreshIcons();
    loadGitHubEmbedStats();
  }).catch(function(err) {
    console.error("loadGitHub error:", err);
    setHtml("ghRepoGrid", '<div class="cs-empty">Error loading repos</div>');
  });
}
```

**Step 2: Add new functions for intake, delete, and semantic search**

```javascript
/* ── Inline Intake (replaces modal) ─────────────── */

window.toggleIntakeOptions = function() {
  var el = document.getElementById("ghIntakeOptions");
  if (el) el.classList.toggle("open");
};

window.ingestRepo = function() {
  var url = (document.getElementById("ghIntakeUrl").value || "").trim();
  if (!url) return;

  var repoType = document.getElementById("ghIntakeType").value || "";
  var maxFiles = parseInt(document.getElementById("ghIntakeMax").value) || 2000;

  var btn = document.getElementById("ghIntakeBtn");
  if (btn) { btn.disabled = true; btn.textContent = "INGESTING..."; }

  // Show progress area
  var prog = document.getElementById("ghIntakeProgress");
  if (prog) prog.classList.add("active");
  setHtml("ghIntakeStatus", "Starting indexing...");
  setHtml("ghIntakeResult", "");

  var body = { repo_url: url, max_files: maxFiles };
  if (repoType) body.repo_type = repoType;

  api("/github/index-selective", { method: "POST", body: body }).then(function(data) {
    if (data.success) {
      setHtml("ghIntakeResult", lcarsMsg("ok", "\u2713", "Indexing job started — " + escHtml(data.message || "processing")));
      document.getElementById("ghIntakeUrl").value = "";
      // Polling will pick up the active job
    } else {
      setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(data.error || "Failed to start indexing")));
    }
  }).catch(function(err) {
    setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(err.message || "Network error")));
  }).finally(function() {
    if (btn) { btn.disabled = false; btn.textContent = "INGEST"; }
    if (prog) prog.classList.remove("active");
    _cache.github = false;
    loadGitHub();
  });
};

/* ── Delete Repo ────────────────────────────────── */

window.deleteRepo = function(repoId, repoName) {
  if (!confirm("Delete repository '" + repoName + "' and all indexed files?\n\nThis cannot be undone.")) return;

  api("/github/repositories/" + repoId, { method: "DELETE" }).then(function(data) {
    if (data.success) {
      setHtml("ghIntakeResult", lcarsMsg("ok", "\u2713", escHtml(repoName) + " removed"));
      _cache.github = false;
      loadGitHub();
    } else {
      setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(data.error || "Delete failed")));
    }
  }).catch(function(err) {
    setHtml("ghIntakeResult", lcarsMsg("err", "\u2717", escHtml(err.message || "Delete error")));
  });
};

/* ── Semantic Search (Discovery Console) ────────── */

window.searchGithubSemantic = function() {
  var query = (document.getElementById("ghDiscoveryInput").value || "").trim();
  if (!query) return;

  setHtml("ghDiscoveryResults", '<div class="cs-loading">Searching...</div>');

  api("/github/search-semantic", { method: "POST", body: { query: query, limit: 20 } }).then(function(data) {
    if (!data.success || !data.results || !data.results.length) {
      setHtml("ghDiscoveryResults",
        '<div style="text-align:center; padding:20px; color:rgba(255,255,255,0.3); font-size:0.8rem;">' +
        'No matches found. Try different terms or index more repos.</div>');
      return;
    }

    var html = '<div style="font-size:0.72rem; color:rgba(255,255,255,0.3); margin-bottom:8px;">' +
      data.results.length + ' matches</div>';
    data.results.forEach(function(r) {
      var score = r.similarity ? Math.round(r.similarity * 100) + "%" : "";
      html += '<div class="gh-discovery-result">' +
        '<span class="gh-discovery-result-path">' + escHtml(r.file_path || r.title || "Unknown") + '</span>' +
        (r.repo_name ? '<span class="gh-discovery-result-repo">' + escHtml(r.repo_name) + '</span>' : '') +
        (score ? '<span class="gh-discovery-result-score">' + score + '</span>' : '') +
        (r.snippet ? '<div class="gh-discovery-result-snippet">' + escHtml(r.snippet) + '</div>' : '') +
        '</div>';
    });
    setHtml("ghDiscoveryResults", html);
  }).catch(function(err) {
    setHtml("ghDiscoveryResults", lcarsMsg("err", "\u2717", escHtml(err.message || "Search error")));
  });
};
```

**Step 3: Remove the old `showAddRepoModal()` and `addRepo()` functions** since intake is now inline.

**Step 4: Verify** — Test the full workflow:
1. Navigate to GitHub tab
2. Paste a URL in the intake port, click INGEST
3. See progress feedback
4. Repo cards render with progress rings
5. Delete a repo
6. Search via Discovery console

**Step 5: Commit**
```bash
git add platform_v2/static/js/consciousness.js
git commit -m "feat(consciousness): GitHub tab JS — intake, cards, delete, semantic search"
```

---

### Task 8: Tab Bar Enhancement

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` (CSS + tab nav HTML)

**Step 1: Add active tab glow CSS**

```css
/* --- Enhanced Tab Navigation --- */
.cs-tab.active {
    box-shadow: 0 0 12px rgba(139,92,246,0.2);
}
.cs-tab::after {
    content: '';
    position: absolute;
    bottom: 0; left: 20%; right: 20%;
    height: 2px;
    background: transparent;
    border-radius: 1px;
    transition: background 0.2s;
}
.cs-tab.active::after {
    background: #8b5cf6;
    box-shadow: 0 0
