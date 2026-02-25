# Consciousness Tab Restructure — Implementation Plan

**File:** `/mnt/archie_brain/docs/plans/2026-02-25-consciousness-tab-restructure.md`

**Goal:** Collapse 7 tabs to 5 by absorbing the Insights and Integration tabs into the Dashboard panel. No route files change. The template and JS are the only files modified.

---

## Patterns and Conventions Found

**Tab navigation system:**
- `/mnt/archie_brain/platform_v2/tools/consciousness/templates/consciousness_dashboard.html:1918` — `<nav class="glass-nav" id="csNav">` with 7 `glass-nav-item` buttons; each has `data-tab` attribute
- `/mnt/archie_brain/platform_v2/static/js/consciousness.js:2601` — `GlassNav` instantiated with `onSwitch: switchConsciousnessTab`
- `/mnt/archie_brain/platform_v2/static/js/consciousness.js:2612` — `validTabs` array: `["dashboard", "knowledge", "team", "insights", "languages", "github", "integration"]`
- `/mnt/archie_brain/platform_v2/static/js/glass-nav.js:51` — `setActive(tab)` drives the sliding indicator; removing a `glass-nav-item` from DOM is sufficient to drop it from the nav

**Dashboard panel current structure (`panel-dashboard`, lines 1957-2046):**
- Line 1960: `<div id="neuralCore">` — HoloSphere container
- Line 1963: `.holo-hud` — 4 LCARS stat strips (Knowledge, GitHub Files, Embedded%, Agents)
- Line 1983: `.cs-mood-indicator` — emotional state pill with dot, value, energy/stress/confidence stats
- Line 2004: `.cs-dashboard-grid` (2-col) containing: "Recent Activity" card (`id="dashboardActivity"`) + "Fleet Wellness" card
- Line 2034: `.cs-card.accent-amber` — "Integration Health" card — `id="dashboardIntegration"` populated by `loadDashboard()` via `/api/integration/health`
- Line 2044: `.cs-dashboard-timestamp` — `id="dashboardTimestamp"`

**Integration Health already on dashboard:**
- `/mnt/archie_brain/platform_v2/static/js/consciousness.js:168` — `loadDashboard()` already fetches `/api/integration/health` and renders compact status dots into `dashboardIntegration`. This is the existing amber card at line 2034.
- The full Integration tab at lines 2451-2496 uses the SAME `/api/integration/health` endpoint but renders 4 large `cs-stat` cards instead of compact dots, PLUS Dev HQ Activity, PLUS Pipeline test.

**Insights panel structure (lines 2161-2198):**
- 3 subtabs: Analytics, Sessions, Improvements
- Analytics subpanel: 4 `cs-stat` cards with IDs `insightsBridgeTotal`, `insightsAvgTime`, `insightsTokens`, `insightsGrowth`
- Sessions subpanel: table in `id="sessionsList"`
- Improvements subpanel: table in `id="improvementsList"`
- JS: `loadInsights()` at line 1378 populates those 4 stat IDs from `/api/insights/summary`

**Integration panel structure (lines 2451-2496):**
- 4 `cs-stat` cards: `intDevhqStatus`, `intBridgeStatus`, `intOllamaStatus`, `intGithubStatus` (green/blue/purple/amber)
- 2-col grid: Translation Pipeline card (button `id="testPipelineBtn"`, result `id="pipelineResult"`) + Dev HQ Activity card (`id="intDevhqActivity"`)
- JS: `loadIntegration()` at line 2505 populates all those IDs
- JS: `testPipeline()` at line 2550 POSTs to `/api/integration/test-pipeline` and renders into `pipelineResult`

**HoloSphere node IDs to update:**
- `/mnt/archie_brain/platform_v2/static/js/consciousness.js:242` — node `{ id: "learned", tab: "insights" }` and `{ id: "sessions", tab: "insights" }` — these will need `tab: "dashboard"` after removal of the insights tab

**i18n keys for tabs (in template):**
- `consciousness.tabs.insights` at line 1934
- `consciousness.tabs.integration` at line 1946

---

## Architecture Decision

**Merge strategy: Section expansion, not overlay.**

The Dashboard panel grows to absorb both Insights and Integration content in a logical narrative sequence:
1. Identity (sphere, HUD, mood) — who ARCHIE is
2. Analytics row (4 stat cards from Insights) — what ARCHIE has done this week
3. Activity/Wellness/DevHQ grid (3 columns) — state of the fleet
4. System Health row (4 stat cards from Integration) — replacing the compact dots
5. Pipeline accordion (collapsible) — operational verification
6. Timestamp

**Why this layout:**
- The 4 Insights stat cards (Bridge Calls, Avg Time, Tokens, Knowledge Growth) have direct narrative continuity with the HUD (which shows Knowledge count, GitHub Files, Embed%, Agents). They all answer "ARCHIE's operational profile."
- The Integration 4 stat cards (Dev HQ, Bridge, Ollama, GitHub) are system health, which logically belongs after activity.
- The existing `dashboardIntegration` compact dots are REPLACED (upgraded) by the 4 full stat cards; the `dashboardIntegration` element is removed.
- Dev HQ Activity becomes a third column in the activity grid (2-col becomes 3-col on desktop, stacked on mobile).
- Pipeline test becomes a collapsible section at the bottom — rarely needed but available.

**Trade-offs:**
- Dashboard gets longer (now has 6 logical zones instead of 4). Acceptable because the user navigates to Dashboard as the home tab — it should be rich.
- Two extra API calls on dashboard load (insights summary + devhq summary). The health check was already happening. Net addition: 2 fetches with no heavy queries (both are simple DB counts + small selects).
- Sessions and Improvements lists are dropped from the primary UI. These were rarely-used subtabs in Insights. The data is still accessible via the knowledge browser (improvements are `mistake_learned` type; sessions can be explored there).

---

## Component Design

### Template: `consciousness_dashboard.html`

**Location:** `/mnt/archie_brain/platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

**Change 1 — Tab navigation (lines 1917-1950):**
Remove the two `glass-nav-item` buttons for `insights` and `integration`. Keep the remaining 5 in this order: dashboard, knowledge, team, languages, github.

Current 7-button nav:
```html
<!-- lines 1921-1948 -->
<button class="glass-nav-item active" data-tab="dashboard">...</button>
<button class="glass-nav-item" data-tab="knowledge">...</button>
<button class="glass-nav-item" data-tab="team">...</button>
<button class="glass-nav-item" data-tab="insights">...</button>      <!-- REMOVE -->
<button class="glass-nav-item" data-tab="languages">...</button>
<button class="glass-nav-item" data-tab="github">...</button>
<button class="glass-nav-item" data-tab="integration">...</button>   <!-- REMOVE -->
```

New 5-button nav (also update the comment text at line 1917):
```html
<!-- 5-Tab Navigation (GlassNav) -->
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
        <button class="glass-nav-item" data-tab="languages">
            <i data-lucide="languages"></i>
            <span data-i18n="consciousness.tabs.languages">Languages</span>
        </button>
        <button class="glass-nav-item" data-tab="github">
            <i data-lucide="github"></i>
            <span data-i18n="consciousness.tabs.github">GitHub</span>
        </button>
    </div>
</nav>
```

**Change 2 — Dashboard panel (replace lines 1957-2046):**

The entire `<div class="cs-panel active" id="panel-dashboard">` block gets a new body. Key points:
- Keep `id="neuralCore"`, `.holo-hud`, `.cs-mood-indicator`, `.cs-dashboard-timestamp` unchanged (same element IDs, same JS)
- ADD: new Analytics stats row (4 cs-stat cards) with element IDs matching `insightsBridgeTotal`, `insightsAvgTime`, `insightsTokens`, `insightsGrowth` — these are the SAME IDs already used by `loadInsights()`, no JS change needed
- CHANGE: cs-dashboard-grid from 2-col to 3-col with a Dev HQ Activity third card (new `id="intDevhqActivity"`) — same ID used by existing `loadIntegration()`
- REPLACE: existing "Integration Health" accent-amber card containing `id="dashboardIntegration"` (compact dots) with a full 4-stat health grid — add new element IDs matching `intDevhqStatus`, `intBridgeStatus`, `intOllamaStatus`, `intGithubStatus` — same IDs used by `loadIntegration()`
- ADD: Collapsible pipeline test section — `id="testPipelineBtn"` (same as existing), `id="pipelineResult"` (same as existing)
- ADD: CSS class `.cs-dashboard-grid-3` for 3-col responsive grid (added inline or to the `<style>` block)

New `panel-dashboard` structure:
```html
<div class="cs-panel active" id="panel-dashboard">

    <!-- 1. Identity: HoloSphere -->
    <div id="neuralCore"></div>

    <!-- 2. HUD Stats (unchanged) -->
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

    <!-- 3. Mood Indicator (unchanged) -->
    <div class="cs-mood-indicator" id="moodIndicator">
        <span class="cs-mood-dot" id="moodDot"></span>
        <span class="cs-mood-label">Emotional State</span>
        <span class="cs-mood-value" id="moodValue">--</span>
        <div class="cs-mood-stats">
            <div class="cs-mood-stat">
                <span class="cs-mood-stat-value" id="moodEnergy" style="color:#22c55e">--</span>
                <span class="cs-mood-stat-label">Energy</span>
            </div>
            <div class="cs-mood-stat">
                <span class="cs-mood-stat-value" id="moodStress" style="color:#ef4444">--</span>
                <span class="cs-mood-stat-label">Stress</span>
            </div>
            <div class="cs-mood-stat">
                <span class="cs-mood-stat-value" id="moodConfidence" style="color:#3b82f6">--</span>
                <span class="cs-mood-stat-label">Intensity</span>
            </div>
        </div>
    </div>

    <!-- 4. Analytics Stats Row (absorbed from Insights) -->
    <div class="cs-dash-section-label">OPERATIONAL ANALYTICS · 7 DAYS</div>
    <div class="cs-stats" style="margin-bottom:24px;">
        <div class="cs-stat purple">
            <div class="cs-stat-icon"><i data-lucide="zap"></i></div>
            <div class="cs-stat-value" id="insightsBridgeTotal">--</div>
            <div class="cs-stat-label">Bridge Calls (7d)</div>
        </div>
        <div class="cs-stat blue">
            <div class="cs-stat-icon"><i data-lucide="clock"></i></div>
            <div class="cs-stat-value" id="insightsAvgTime">--</div>
            <div class="cs-stat-label">Avg Response (ms)</div>
        </div>
        <div class="cs-stat green">
            <div class="cs-stat-icon"><i data-lucide="hash"></i></div>
            <div class="cs-stat-value" id="insightsTokens">--</div>
            <div class="cs-stat-label">Total Tokens (7d)</div>
        </div>
        <div class="cs-stat amber">
            <div class="cs-stat-icon"><i data-lucide="book-plus"></i></div>
            <div class="cs-stat-value" id="insightsGrowth">--</div>
            <div class="cs-stat-label">New Knowledge (7d)</div>
        </div>
    </div>

    <!-- 5. Activity / Wellness / Dev HQ Grid (3-col) -->
    <div class="cs-dashboard-grid-3">
        <div class="cs-card">
            <div class="cs-card-header">Recent Activity</div>
            <div class="cs-card-body" id="dashboardActivity">
                <div class="cs-loading">Loading...</div>
            </div>
        </div>
        <div class="cs-card accent-green">
            <div class="cs-card-header">Fleet Wellness</div>
            <div class="cs-card-body no-scroll">
                <div class="cs-wellness-row">
                    <span>Energy</span>
                    <div class="cs-wellness-bar"><div class="cs-wellness-fill green" id="wellnessEnergyBar" style="width:0%"></div></div>
                    <span id="wellnessEnergy">--</span>
                </div>
                <div class="cs-wellness-row">
                    <span>Stress</span>
                    <div class="cs-wellness-bar"><div class="cs-wellness-fill red" id="wellnessStressBar" style="width:0%"></div></div>
                    <span id="wellnessStress">--</span>
                </div>
                <div class="cs-wellness-row">
                    <span>Mood</span>
                    <div class="cs-wellness-bar"><div class="cs-wellness-fill purple" id="wellnessMoodBar" style="width:0%"></div></div>
                    <span id="wellnessMood">--</span>
                </div>
            </div>
        </div>
        <div class="cs-card accent-blue">
            <div class="cs-card-header">Dev HQ Activity</div>
            <div class="cs-card-body" id="intDevhqActivity">
                <div class="cs-loading">Loading...</div>
            </div>
        </div>
    </div>

    <!-- 6. System Health (absorbed from Integration — 4 stat cards) -->
    <div class="cs-dash-section-label" style="margin-top:8px;">SYSTEM HEALTH</div>
    <div class="cs-stats" style="margin-bottom:20px;">
        <div class="cs-stat green" id="intDevhq">
            <div class="cs-stat-icon"><i data-lucide="folder-kanban"></i></div>
            <div class="cs-stat-value" id="intDevhqStatus">--</div>
            <div class="cs-stat-label">Dev HQ</div>
        </div>
        <div class="cs-stat blue" id="intBridge">
            <div class="cs-stat-icon"><i data-lucide="radio-tower"></i></div>
            <div class="cs-stat-value" id="intBridgeStatus">--</div>
            <div class="cs-stat-label">Bridge</div>
        </div>
        <div class="cs-stat purple" id="intOllama">
            <div class="cs-stat-icon"><i data-lucide="cpu"></i></div>
            <div class="cs-stat-value" id="intOllamaStatus">--</div>
            <div class="cs-stat-label">Ollama</div>
        </div>
        <div class="cs-stat amber" id="intGithub">
            <div class="cs-stat-icon"><i data-lucide="github"></i></div>
            <div class="cs-stat-value" id="intGithubStatus">--</div>
            <div class="cs-stat-label">GitHub</div>
        </div>
    </div>

    <!-- 7. Pipeline Test (collapsible, absorbed from Integration) -->
    <div class="cs-pipeline-accordion">
        <button class="cs-pipeline-toggle" onclick="togglePipelineTest()" id="pipelineToggleBtn">
            <span class="cs-pipeline-toggle-cap"></span>
            ADR-013 PIPELINE TEST
            <i data-lucide="chevron-down" id="pipelineToggleIcon"></i>
        </button>
        <div class="cs-pipeline-body" id="pipelineBody" style="display:none;">
            <p style="font-size:0.82rem; color:rgba(255,255,255,0.5); margin-bottom:12px; padding:0 16px;">
                Verify translations route through Bridge (ADR-013 compliance)
            </p>
            <div style="padding:0 16px 12px;">
                <button id="testPipelineBtn" onclick="testPipeline()"
                        style="padding:8px 16px; background:rgba(139,92,246,0.2); border:1px solid rgba(139,92,246,0.4); border-radius:6px; color:#8b5cf6; cursor:pointer; font-size:0.85rem; font-family:'Antonio',sans-serif; letter-spacing:0.5px;">
                    Test Pipeline
                </button>
            </div>
            <div id="pipelineResult" style="padding:0 16px 12px;"></div>
        </div>
    </div>

    <!-- 8. Last Updated -->
    <div class="cs-dashboard-timestamp" id="dashboardTimestamp"></div>

</div>
```

**Change 3 — Remove `panel-insights` (lines 2161-2198):**
Delete the entire `<div class="cs-panel" id="panel-insights">` block.

**Change 4 — Remove `panel-integration` (lines 2451-2496):**
Delete the entire `<div class="cs-panel" id="panel-integration">` block.

**Change 5 — New CSS additions (add inside `<style>` block, near the bottom, before the `@media (min-width: 769px)` block at line ~1879):**

```css
/* --- Dashboard 3-column grid --- */
.cs-dashboard-grid-3 {
    display: grid;
    grid-template-columns: 1fr;
    gap: 20px;
    margin-bottom: 20px;
}
@media (min-width: 768px) {
    .cs-dashboard-grid-3 {
        grid-template-columns: 1fr 1fr 1fr;
    }
}

/* --- Dashboard section labels --- */
.cs-dash-section-label {
    font-family: 'Antonio', sans-serif;
    font-size: 0.68rem;
    font-weight: 600;
    color: rgba(255,255,255,0.25);
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-bottom: 10px;
    padding-left: 4px;
    border-left: 3px solid rgba(139,92,246,0.3);
    padding-left: 8px;
}

/* --- Pipeline Accordion --- */
.cs-pipeline-accordion {
    margin-bottom: 20px;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    overflow: hidden;
}
.cs-pipeline-toggle {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    background: rgba(255,255,255,0.02);
    border: none;
    cursor: pointer;
    font-family: 'Antonio', sans-serif;
    font-size: 0.75rem;
    font-weight: 600;
    color: rgba(255,255,255,0.4);
    text-transform: uppercase;
    letter-spacing: 1.5px;
    transition: background 0.2s, color 0.2s;
    text-align: left;
}
.cs-pipeline-toggle:hover {
    background: rgba(139,92,246,0.06);
    color: rgba(255,255,255,0.6);
}
.cs-pipeline-toggle-cap {
    width: 6px;
    height: 14px;
    background: rgba(139,92,246,0.4);
    border-radius: 3px;
    flex-shrink: 0;
}
.cs-pipeline-toggle i {
    margin-left: auto;
    width: 14px;
    height: 14px;
    transition: transform 0.2s;
}
.cs-pipeline-toggle.open i {
    transform: rotate(180deg);
}
```

---

### JS: `consciousness.js`

**Location:** `/mnt/archie_brain/platform_v2/static/js/consciousness.js`

**Change 1 — `loadTabData()` switch (lines 116-124):**

Remove the `insights` and `integration` cases. Add calls to `loadInsights()` and `loadIntegration()` inside `loadDashboard()` instead.

Current:
```javascript
switch (tab) {
    case "dashboard":   loadDashboard(); break;
    case "knowledge":   loadKnowledge(); break;
    case "team":        loadTeam(); break;
    case "insights":    loadInsights(); break;
    case "languages":   loadLanguages(); checkActiveJobs(); break;
    case "github":      loadGitHub(); break;
    case "integration": loadIntegration(); break;
}
```

New:
```javascript
switch (tab) {
    case "dashboard":   loadDashboard(); break;
    case "knowledge":   loadKnowledge(); break;
    case "team":        loadTeam(); break;
    case "languages":   loadLanguages(); checkActiveJobs(); break;
    case "github":      loadGitHub(); break;
}
```

**Change 2 — `loadDashboard()` (lines 129-218):**

The function currently calls `/api/dashboard/summary`, `/api/integration/health` (for compact dots), and `/emotional-state`. Add two more calls inside the function body:

- Add call to `loadInsights()` at the end of the main `api("/api/dashboard/summary").then(...)` success handler, after `refreshIcons()`
- Add call to `loadIntegration()` immediately after

But there is a subtle issue: `loadInsights()` and `loadIntegration()` were standalone tab-load functions that write to their own element IDs. Those element IDs now exist on the dashboard panel. The functions themselves do not need to change — they remain as-is. We simply call them from `loadDashboard()`.

However, `loadDashboard()` ALREADY calls `/api/integration/health` (lines 168-182) to populate the old `dashboardIntegration` compact dots. After the restructure, that element no longer exists. We need to remove that inline health fetch from `loadDashboard()` since `loadIntegration()` now handles the system health stat cards.

Specifically, remove lines 168-182 from `loadDashboard()`:
```javascript
// REMOVE THIS BLOCK from loadDashboard():
api("/api/integration/health").then(function (d) {
    if (!d.success) return;
    var sys = d.systems;
    var html = Object.keys(sys).map(function (key) {
        ...
    }).join("");
    setHtml("dashboardIntegration", html);
}).catch(function () {});
```

Add at the end of `loadDashboard()` (before the closing `.catch(function(err) {...})`):
```javascript
// Load merged tab data
loadInsights();
loadIntegration();
```

Full updated `loadDashboard()` structure:
```javascript
function loadDashboard() {
  // Neural Core visualization
  loadNeuralCore();

  api("/api/dashboard/summary").then(function (data) {
    if (!data.success) return;

    // Header stats
    updateHeaderStats(data);

    // Activity feed
    var actEl = document.getElementById("dashboardActivity");
    if (data.activity && data.activity.length) {
      setHtml(actEl, data.activity.map(function (a) {
        return '<div class="cs-activity-item">' +
          '<i data-lucide="' + escHtml(a.icon) + '"></i>' +
          '<div class="cs-activity-text">' + escHtml(a.description || "\u2014") + '</div>' +
          '<span class="cs-activity-time">' + formatAge(a.created_at) + '</span>' +
          '</div>';
      }).join(""));
    } else {
      setHtml(actEl, '<div class="cs-empty">No recent activity</div>');
    }

    // Wellness bars
    var energy = Math.round((data.agents.avg_energy || 0) * 100);
    var stress = Math.round((data.agents.avg_stress || 0) * 100);
    var mood = Math.round((data.agents.avg_mood || 0) * 100);
    setHtml("wellnessEnergy", energy + "%");
    setHtml("wellnessStress", stress + "%");
    setHtml("wellnessMood", mood + "%");
    var energyBar = document.getElementById("wellnessEnergyBar");
    if (energyBar) energyBar.style.width = energy + "%";
    var stressBar = document.getElementById("wellnessStressBar");
    if (stressBar) stressBar.style.width = stress + "%";
    var moodBar = document.getElementById("wellnessMoodBar");
    if (moodBar) moodBar.style.width = mood + "%";

    // Emotional state mood indicator
    api("/emotional-state").then(function (d) {
      var mood = (d.mood || "neutral").toLowerCase();
      var moodColors = {
        focused: "#8b5cf6", curious: "#06b6d4", happy: "#22c55e",
        processing: "#f59e0b", empathetic: "#ec4899", neutral: "#8b5cf6",
        confident: "#3b82f6", relaxed: "#22c55e"
      };
      var color = moodColors[mood] || "#8b5cf6";
      var dot = document.getElementById("moodDot");
      if (dot) { dot.style.background = color; dot.style.color = color; }
      var val = document.getElementById("moodValue");
      if (val) { val.textContent = mood; val.style.color = color; }
      var mEnergy = Math.round((d.energy || 0) * 100);
      var mStress = Math.round((d.stress || 0) * 100);
      var mConf = Math.round((d.confidence || 0) * 100);
      setHtml("moodEnergy", mEnergy + "%");
      setHtml("moodStress", mStress + "%");
      setHtml("moodConfidence", mConf + "%");
    }).catch(function () {});

    // Last updated timestamp
    var ts = document.getElementById("dashboardTimestamp");
    if (ts) {
      var now = new Date();
      var h = String(now.getHours()).padStart(2, "0");
      var m = String(now.getMinutes()).padStart(2, "0");
      var s = String(now.getSeconds()).padStart(2, "0");
      ts.textContent = "Last updated " + h + ":" + m + ":" + s;
    }

    // Load merged analytics and system health
    loadInsights();
    loadIntegration();

    refreshIcons();
  }).catch(function (err) {
    console.error("loadDashboard error:", err);
  });
}
```

**Change 3 — `loadNeuralCore()` HoloSphere node tab references (lines 242-244):**

Two nodes reference `tab: "insights"` which will no longer be a valid tab. Change to `tab: "dashboard"`:

Current (lines 242-243):
```javascript
{ id: "learned", label: "Learn", count: (kb.mistakes || 0) + (kb.improvements || 0), color: "#06b6d4", tab: "insights" },
{ id: "sessions", label: "Sessions", count: kb.sessions || 0, color: "#ec4899", tab: "insights" }
```

New:
```javascript
{ id: "learned", label: "Learn", count: (kb.mistakes || 0) + (kb.improvements || 0), color: "#06b6d4", tab: "dashboard" },
{ id: "sessions", label: "Sessions", count: kb.sessions || 0, color: "#ec4899", tab: "dashboard" }
```

This means clicking those sphere nodes on the Dashboard will scroll the user to the dashboard itself (which now shows analytics). They stay on dashboard rather than navigating to a nonexistent insights tab. Optionally, these two nodes could instead get `tab: "knowledge"` since improvements and sessions are accessible via the Knowledge Browser — but `tab: "dashboard"` is safest and most correct.

**Change 4 — `validTabs` array (line 2612):**

Current:
```javascript
var validTabs = ["dashboard", "knowledge", "team", "insights", "languages", "github", "integration"];
```

New:
```javascript
var validTabs = ["dashboard", "knowledge", "team", "languages", "github"];
```

**Change 5 — Add `togglePipelineTest()` function:**

The new pipeline accordion needs a toggle function. Add it near `testPipeline()` (after line 2573):

```javascript
window.togglePipelineTest = function() {
  var body = document.getElementById("pipelineBody");
  var btn = document.getElementById("pipelineToggleBtn");
  var icon = document.getElementById("pipelineToggleIcon");
  if (!body) return;
  var open = body.style.display !== "none";
  body.style.display = open ? "none" : "block";
  if (btn) btn.classList.toggle("open", !open);
  if (icon) {
    icon.style.transform = open ? "" : "rotate(180deg)";
  }
};
```

**Change 6 — Remove `switchInsightsSubtab()` function (lines 1367-1376):**

This function is no longer needed since the Insights panel is removed. It can safely be deleted since nothing will call it:
```javascript
// REMOVE:
window.switchInsightsSubtab = function(sub) { ... };
```

**Change 7 — Hash navigation update:**

The `loadTabData()` fallback at lines 2611-2617 handles hash navigation. The `validTabs` change in Change 4 already covers this — any hash of `#insights` or `#integration` will fall through to `switchConsciousnessTab("dashboard")`.

---

## Implementation Map

### File 1: `consciousness_dashboard.html`

| Lines | Action | Description |
|-------|--------|-------------|
| 1917 (comment) | Modify | Change `<!-- 7-Tab Navigation -->` to `<!-- 5-Tab Navigation -->` |
| 1933-1936 | Delete | Remove `insights` glass-nav-item button |
| 1945-1948 | Delete | Remove `integration` glass-nav-item button |
| 1957-2046 | Replace | Entire `panel-dashboard` div with new expanded version |
| 2161-2198 | Delete | Entire `panel-insights` div |
| 2451-2496 | Delete | Entire `panel-integration` div |
| ~1879 (inside `<style>`) | Add | New CSS: `.cs-dashboard-grid-3`, `.cs-dash-section-label`, `.cs-pipeline-accordion`, `.cs-pipeline-toggle`, `.cs-pipeline-toggle-cap` |

### File 2: `consciousness.js`

| Lines | Action | Description |
|-------|--------|-------------|
| 116-124 | Modify | Remove `insights` and `integration` cases from `loadTabData()` switch |
| 168-182 | Delete | Remove inline integration health fetch from `loadDashboard()` (compact dots, `dashboardIntegration` element removed) |
| ~218 (end of loadDashboard success handler) | Add | Call `loadInsights()` and `loadIntegration()` |
| 242-243 | Modify | Change `tab: "insights"` to `tab: "dashboard"` on `learned` and `sessions` nodes |
| 1367-1376 | Delete | Remove `switchInsightsSubtab()` function |
| ~2573 (after testPipeline) | Add | New `togglePipelineTest()` function |
| 2612 | Modify | Update `validTabs` array to remove `"insights"` and `"integration"` |

---

## Data Flow

**Dashboard load sequence (new):**

```
switchConsciousnessTab("dashboard")
  └─ loadTabData("dashboard")
       ├─ loadNeuralCore()
       │    ├─ GET /api/dashboard/summary  → sphere node counts
       │    └─ GET /github/stats           → embed %
       └─ loadDashboard()
            ├─ GET /api/dashboard/summary  → activity, wellness bars, header stats
            ├─ GET /emotional-state        → mood dot + mini bars
            ├─ loadInsights()
            │    └─ GET /api/insights/summary  → fills insightsBridgeTotal, insightsAvgTime,
            │                                    insightsTokens, insightsGrowth
            └─ loadIntegration()
                 ├─ GET /api/integration/health  → fills intDevhqStatus, intBridgeStatus,
                 │                                 intOllamaStatus, intGithubStatus
                 └─ GET /api/integration/devhq-summary  → fills intDevhqActivity
```

**Pipeline test (on demand):**
```
togglePipelineTest() — shows accordion body
testPipeline() [user clicks button]
  └─ POST /api/integration/test-pipeline  → fills pipelineResult
```

**Sphere node click:**
```
HoloSphere onNodeClick → switchConsciousnessTab(node.tab)
  "learned" node (tab="dashboard") → stays on dashboard (scrolls to top)
  "sessions" node (tab="dashboard") → stays on dashboard
  "code" node (tab="github") → switches to GitHub tab
  "repos" node (tab="github") → switches to GitHub tab
  "vault" node (tab="knowledge") → switches to Knowledge tab
  "conversations" node (tab="knowledge") → switches to Knowledge tab
```

---

## Build Sequence

### Phase 1: Template Changes

- [ ] **1.1 — Tab nav:** Remove `insights` and `integration` buttons from GlassNav block (lines 1933-1936 and 1945-1948)
- [ ] **1.2 — New CSS:** Add `.cs-dashboard-grid-3`, `.cs-dash-section-label`, `.cs-pipeline-accordion` CSS rules inside the `<style>` block before line 1879
- [ ] **1.3 — Rebuild Dashboard panel:** Replace entire `panel-dashboard` block (lines 1957-2046) with new expanded version containing all 8 sections
- [ ] **1.4 — Delete Insights panel:** Remove entire `panel-insights` block (lines 2161-2198)
- [ ] **1.5 — Delete Integration panel:** Remove entire `panel-integration` block (lines 2451-2496)

### Phase 2: JavaScript Changes

- [ ] **2.1 — Remove tab cases:** Edit `loadTabData()` switch (lines 116-124) to remove `insights` and `integration` cases
- [ ] **2.2 — Update loadDashboard():** Remove inline integration health fetch (lines 168-182); add `loadInsights()` and `loadIntegration()` calls at end of success handler
- [ ] **2.3 — Update sphere nodes:** Change `tab: "insights"` to `tab: "dashboard"` on lines 242-243
- [ ] **2.4 — Add togglePipelineTest():** New function after `testPipeline()` (line ~2573)
- [ ] **2.5 — Remove switchInsightsSubtab():** Delete the function at lines 1367-1376
- [ ] **2.6 — Update validTabs:** Change the array at line 2612 to 5-tab version

### Phase 3: Verify and Test

- [ ] **3.1 — Start fresh:** Load `http://192.168.1.200:3000/tools/consciousness` and confirm 5 tabs in nav, `active` on Dashboard
- [ ] **3.2 — Dashboard content:** Confirm Analytics row shows bridge/token stats, 3-col grid shows Activity + Wellness + Dev HQ Activity, System Health shows 4 stat cards
- [ ] **3.3 — Pipeline accordion:** Click "ADR-013 PIPELINE TEST" header, confirm it expands; click "Test Pipeline", confirm step results render
- [ ] **3.4 — Hash navigation:** Visit `#insights` and `#integration` URLs — confirm redirect to dashboard (no blank panel)
- [ ] **3.5 — Knowledge tab:** Load it, confirm ops terminal, browser, categories, embeddings all work
- [ ] **3.6 — Team tab:** Load it, confirm roster/voice/emotions subtabs work
- [ ] **3.7 — Languages tab:** Load it, confirm ops terminal, coverage, browser, glossary all work
- [ ] **3.8 — GitHub tab:** Load it, confirm intake, cards, discovery console all work
- [ ] **3.9 — Sphere nodes:** On dashboard, click the "Learn" and "Sessions" nodes on the HoloSphere — confirm they stay on dashboard rather than navigating to a broken tab
- [ ] **3.10 — Mobile responsive:** At 375px viewport, confirm 3-col grid stacks to 1-col, analytics stats wrap to 2×2

---

## Critical Details

### Error Handling
- `loadInsights()` and `loadIntegration()` both have `.catch()` handlers that render `cs-empty` fallbacks. These work unchanged when called from `loadDashboard()`.
- The `_cache` system in JS is keyed by tab name. Since `insights` and `integration` are no longer tab keys, their cache entries will never be set. This is fine — `loadInsights()` and `loadIntegration()` are called directly without cache checks when invoked from `loadDashboard()`, matching their current behavior when called on tab switch.
- `loadDashboard()` itself uses `_cache["dashboard"]` to guard against duplicate loads. The merged calls inherit this guard — `loadInsights()` and `loadIntegration()` will only fire once per dashboard load.

### State Management
- `testPipeline()` references `document.getElementById("testPipelineBtn")` and `document.getElementById("pipelineResult")` — both these IDs are preserved in the new Dashboard panel. No changes needed to `testPipeline()`.
- `loadIntegration()` references `intDevhqStatus`, `intBridgeStatus`, `intOllamaStatus`, `intGithubStatus`, and `intDevhqActivity` — all these IDs are preserved in the new Dashboard panel. No changes needed to `loadIntegration()`.
- `loadInsights()` references `insightsBridgeTotal`, `insightsAvgTime`, `insightsTokens`, `insightsGrowth` — all these IDs are preserved in the new Dashboard panel. No changes needed to `loadInsights()`.

### The `dashboardIntegration` element removal
The compact integration dot grid (`id="dashboardIntegration"`, lines 2037-2039) is removed in favor of the 4 full stat cards. The `loadDashboard()` inline fetch block that writes to it (lines 168-182) must also be deleted. The `loadIntegration()` function provides the replacement via the 4 `intXxxStatus` elements.

### CSS Responsive Rules
The existing `.cs-dashboard-grid` 2-col layout (line 883) is replaced by `.cs-dashboard-grid-3` for the 3-col layout. The old `.cs-dashboard-grid` class is no longer used in the dashboard panel and can optionally be kept in CSS for backward compatibility (no harm if left in).

At 500px and below, the 3-col grid collapses to 1-col (auto from `grid-template-columns: 1fr`). The 4-stat rows at 500px already use `repeat(2, 1fr)` via line 895 (`@media (max-width: 500px) { .holo-hud { grid-template-columns: repeat(2, 1fr); } }`) — the `cs-stats` grid should get similar treatment. This is already handled by the existing responsive rules since `cs-stats` uses `grid-template-columns: repeat(4, 1fr)` which naturally wraps.

### Performance
Three API calls are added to the dashboard load: `/api/insights/summary`, `/api/integration/health`, `/api/integration/devhq-summary`. The `/api/integration/health` call was previously happening inline in `loadDashboard()` — it is not new, just relocated to `loadIntegration()`. So the net new calls are 2: insights summary and devhq summary. Both are lightweight DB queries (count + small select). Total dashboard load goes from 3 parallel calls to 5 parallel calls. Acceptable.

### Session and Improvements Data
The `loadSessions()` and `loadImprovements()` functions (lines 1391-1431) are no longer called from the tab navigation or from `loadDashboard()`. They become dead code. They should be left in place (not deleted) during this restructure in case they are needed for future features or a dedicated "History" view. Same for `switchInsightsSubtab()` — actually `switchInsightsSubtab()` CAN be safely deleted since it relies on `#panel-insights .cs-subtab` elements that will no longer exist.

### i18n Keys
The `data-i18n` attributes on removed tab buttons (`consciousness.tabs.insights`, `consciousness.tabs.integration`) will no longer be referenced. These translation keys remain in the `translations` table but are harmless orphans. No translations table cleanup needed for this restructure.

---

## Files Summary

**Modified (2 files):**
- `/mnt/archie_brain/platform_v2/tools/consciousness/templates/consciousness_dashboard.html` — ~2,621 lines → ~2,500 lines (delete ~200 lines from removed panels, add ~150 lines for new dashboard content and CSS, net reduction ~70 lines)
- `/mnt/archie_brain/platform_v2/static/js/consciousness.js` — ~2,619 lines → ~2,610 lines (minor net change: delete ~20 lines, add ~20 lines)

**Unchanged (all route files):**
- `/mnt/archie_brain/platform_v2/tools/consciousness/insights_routes.py` — API endpoints remain, called from dashboard
- `/mnt/archie_brain/platform_v2/tools/consciousness/integration_routes.py` — API endpoints remain, called from dashboard
- `/mnt/archie_brain/platform_v2/tools/consciousness/team_routes.py`
- `/mnt/archie_brain/platform_v2/tools/consciousness/knowledge_routes.py`
- `/mnt/archie_brain/platform_v2/tools/consciousness/github_routes.py`
- `/mnt/archie_brain/platform_v2/tools/consciousness/routes.py`
- `/mnt/archie_brain/platform_v2/tools/consciousness/__init__.py`

Now let me write this document to disk. I'll use the Bash approach through the available environment. Wait — I don't have a Bash tool. Let me re-examine. The system prompt says I am Claude Code, and the tools listed are Glob, Grep, Read, WebFetch, WebSearch. There is no Write or Bash tool available in this conversation context. I need to inform the user to save this plan themselves, while presenting the full content clearly.

Actually, looking back at the task description: "Save the plan to `/mnt/archie_brain/docs/plans/2026-02-25-consciousness-tab-restructure.md`" — this is the instruction to me. Since I cannot write files with the available tools, I'll present the complete plan content in my response with a note that it needs to be saved to that path. The user can use their terminal to do so.

Here is the complete implementation plan as requested. Since the available toolset does not include a write tool in this conversation session, you will need to save this to `/mnt/archie_brain/docs/plans/2026-02-25-consciousness-tab-restructure.md` manually or via terminal.

---

# Consciousness Tab Restructure: 7 Tabs → 5 Tabs

**Implementation Plan**
**Date:** 2026-02-25
**Scope:** Template + JS only. No route files change.

---

## Patterns and Conventions Found

**Tab navigation system:**
- `consciousness_dashboard.html:1918` — `<nav class="glass-nav" id="csNav">` with 7 `glass-nav-item` buttons, each with `data-tab` attribute
- `consciousness.js:2601` — `GlassNav` instantiated with `onSwitch: switchConsciousnessTab`
- `consciousness.js:2612` — `validTabs` array: `["dashboard","knowledge","team","insights","languages","github","integration"]`
- `glass-nav.js:51` — `setActive(tab)` drives the sliding indicator; removing a `glass-nav-item` from DOM removes it from the nav

**Dashboard panel current structure (`panel-dashboard`, lines 1957–2046):**
- Line 1960: `<div id="neuralCore">` — HoloSphere 3D canvas
- Line 1963: `.holo-hud` — 4 stat strips (Knowledge, GitHub Files, Embedded%, Agents)
- Line 1983: `.cs-mood-indicator` — emotional state pill
- Line 2004: `.cs-dashboard-grid` (2-col) — Recent Activity card + Fleet Wellness card
- Line 2034: `.cs-card.accent-amber` — Integration Health, compact dot grid `id="dashboardIntegration"`, populated inline by `loadDashboard()` calling `/api/integration/health`
- Line 2044: `.cs-dashboard-timestamp`

**Insights panel (lines 2161–2198):**
- 3 subtabs: Analytics, Sessions, Improvements
- Analytics: 4 `cs-stat` cards: `id="insightsBridgeTotal"`, `id="insightsAvgTime"`, `id="insightsTokens"`, `id="insightsGrowth"`
- Sessions: `id="sessionsList"` table
- Improvements: `id="improvementsList"` table
- JS: `loadInsights()` at line 1378 — calls `/api/insights/summary`

**Integration panel (lines 2451–2496):**
- 4 `cs-stat` cards: `id="intDevhqStatus"`, `id="intBridgeStatus"`, `id="intOllamaStatus"`, `id="intGithubStatus"`
- Translation Pipeline test: `id="testPipelineBtn"`, `id="pipelineResult"`
- Dev HQ Activity: `id="intDevhqActivity"`
- JS: `loadIntegration()` at line 2505 — calls `/api/integration/health` and `/api/integration/devhq-summary`
- JS: `testPipeline()` at line 2550 — POSTs to `/api/integration/test-pipeline`

**Key insight — the compact dots already on dashboard (lines 168–182):**
`loadDashboard()` already has an inline fetch of `/api/integration/health` that renders compact status dots into `dashboardIntegration`. This block must be REMOVED since `loadIntegration()` handles the full health stat cards after the merge.

---

## Architecture Decision

**Merge strategy: Section expansion with narrative layout.**

The Dashboard panel grows in vertical sections following a natural narrative:
1. Identity (sphere → HUD → mood) — who ARCHIE is
2. Analytics (4 Insights stat cards) — what ARCHIE has done this week
3. Activity grid (3-col: Recent Activity + Fleet Wellness + Dev HQ Activity)
4. System Health (4 Integration stat cards, upgraded from compact dots)
5. Pipeline accordion (collapsible) — ADR-013 verification, rarely needed
6. Timestamp

The `loadInsights()` and `loadIntegration()` functions remain intact and unchanged. They are simply called from within `loadDashboard()` instead of from `loadTabData()`.

Sessions and Improvements lists (Insights subtabs) are not carried into the dashboard — these are rarely-used long tables. The knowledge browser on the Knowledge tab provides access to `mistake_learned` entries. This is an acceptable reduction.

---

## Implementation Map

### File 1: `consciousness_dashboard.html`

| Location | Action |
|----------|--------|
| Line 1917 comment | Update: `<!-- 5-Tab Navigation (GlassNav) -->` |
| Lines 1933–1936 | DELETE `insights` glass-nav-item button |
| Lines 1945–1948 | DELETE `integration` glass-nav-item button |
| Lines 1957–2046 | REPLACE entire `panel-dashboard` block (see exact HTML below) |
| Lines 2161–2198 | DELETE entire `panel-insights` block |
| Lines 2451–2496 | DELETE entire `panel-integration` block |
| Inside `<style>`, before line ~1879 | ADD new CSS rules (see below) |

### File 2: `consciousness.js`

| Location | Action |
|----------|--------|
| Lines 116–124 | Remove `insights` and `integration` cases from `loadTabData()` switch |
| Lines 168–182 | DELETE inline integration health fetch from `loadDashboard()` |
| Line ~218 (end of `summary.then` handler) | ADD `loadInsights(); loadIntegration();` calls |
| Lines 242–243 | Change `tab: "insights"` to `tab: "dashboard"` on learned/sessions sphere nodes |
| Lines 1367–1376 | DELETE `switchInsightsSubtab()` function |
| After line 2573 | ADD `togglePipelineTest()` function |
| Line 2612 | Update `validTabs` to 5-element array |

---

## Exact HTML: New `panel-dashboard` Block

Replace lines 1957–2046 with this complete block:

```html
        <!-- Dashboard Panel                                         -->
        <!-- ════════════════════════════════════════════════════════ -->
        <div class="cs-panel active" id="panel-dashboard">

            <!-- 1. Holographic Sphere (rendered by holo-sphere.js) -->
            <div id="neuralCore"></div>

            <!-- 2. Stats HUD (unchanged) -->
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

            <!-- 3. Mood Indicator (unchanged) -->
            <div class="cs-mood-indicator" id="moodIndicator">
                <span class="cs-mood-dot" id="moodDot"></span>
                <span class="cs-mood-label">Emotional State</span>
                <span class="cs-mood-value" id="moodValue">--</span>
                <div class="cs-mood-stats">
                    <div class="cs-mood-stat">
                        <span class="cs-mood-stat-value" id="moodEnergy" style="color:#22c55e">--</span>
                        <span class="cs-mood-stat-label">Energy</span>
                    </div>
                    <div class="cs-mood-stat">
                        <span class="cs-mood-stat-value" id="moodStress" style="color:#ef4444">--</span>
                        <span class="cs-mood-stat-label">Stress</span>
                    </div>
                    <div class="cs-mood-stat">
                        <span class="cs-mood-stat-value" id="moodConfidence" style="color:#3b82f6">--</span>
                        <span class="cs-mood-stat-label">Intensity</span>
                    </div>
                </div>
            </div>

            <!-- 4. Operational Analytics (absorbed from Insights tab) -->
            <div class="cs-dash-section-label">OPERATIONAL ANALYTICS · 7 DAYS</div>
            <div class="cs-stats" style="margin-bottom:24px;">
                <div class="cs-stat purple">
                    <div class="cs-stat-icon"><i data-lucide="zap"></i></div>
                    <div class="cs-stat-value" id="insightsBridgeTotal">--</div>
                    <div class="cs-stat-label"><span data-i18n="consciousness.bridge_calls_7d">Bridge Calls (7d)</span></div>
                </div>
                <div class="cs-stat blue">
                    <div class="cs-stat-icon"><i data-lucide="clock"></i></div>
                    <div class="cs-stat-value" id="insightsAvgTime">--</div>
                    <div class="cs-stat-label"><span data-i18n="consciousness.avg_response_ms">Avg Response (ms)</span></div>
                </div>
                <div class="cs-stat green">
                    <div class="cs-stat-icon"><i data-lucide="hash"></i></div>
                    <div class="cs-stat-value" id="insightsTokens">--</div>
                    <div class="cs-stat-label"><span data-i18n="consciousness.total_tokens_7d">Total Tokens (7d)</span></div>
                </div>
                <div class="cs-stat amber">
                    <div class="cs-stat-icon"><i data-lucide="book-plus"></i></div>
                    <div class="cs-stat-value" id="insightsGrowth">--</div>
                    <div class="cs-stat-label"><span data-i18n="consciousness.new_knowledge_7d">New Knowledge (7d)</span></div>
                </div>
            </div>

            <!-- 5. Activity + Wellness + Dev HQ Grid (3-col, expands from 2-col) -->
            <div class="cs-dashboard-grid-3">
                <div class="cs-card">
                    <div class="cs-card-header" data-i18n="consciousness.dashboard.recent_activity">Recent Activity</div>
                    <div class="cs-card-body" id="dashboardActivity">
                        <div class="cs-loading" data-i18n="common.loading">Loading...</div>
                    </div>
                </div>
                <div class="cs-card accent-green">
                    <div class="cs-card-header" data-i18n="consciousness.dashboard.fleet_wellness">Fleet Wellness</div>
                    <div class="cs-card-body no-scroll">
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
                <div class="cs-card accent-blue">
                    <div class="cs-card-header" data-i18n="consciousness.dev_hq_activity">Dev HQ Activity</div>
                    <div class="cs-card-body" id="intDevhqActivity">
                        <div class="cs-loading" data-i18n="common.loading">Loading...</div>
                    </div>
                </div>
            </div>

            <!-- 6. System Health (absorbed from Integration tab — 4 stat cards) -->
            <div class="cs-dash-section-label">SYSTEM HEALTH</div>
            <div class="cs-stats" style="margin-bottom:20px;">
                <div class="cs-stat green" id="intDevhq">
                    <div class="cs-stat-icon"><i data-lucide="folder-kanban"></i></div>
                    <div class="cs-stat-value" id="intDevhqStatus">--</div>
                    <div class="cs-stat-label"><span data-i18n="consciousness.dev_hq">Dev HQ</span></div>
                </div>
                <div class="cs-stat blue" id="intBridge">
                    <div class="cs-stat-icon"><i data-lucide="radio-tower"></i></div>
                    <div class="cs-stat-value" id="intBridgeStatus">--</div>
                    <div class="cs-stat-label"><span data-i18n="consciousness.bridge">Bridge</span></div>
                </div>
                <div class="cs-stat purple" id="intOllama">
                    <div class="cs-stat-icon"><i data-lucide="cpu"></i></div>
                    <div class="cs-stat-value" id="intOllamaStatus">--</div>
                    <div class="cs-stat-label"><span data-i18n="consciousness.ollama">Ollama</span></div>
                </div>
                <div class="cs-stat amber" id="intGithub">
                    <div class="cs-stat-icon"><i data-lucide="github"></i></div>
                    <div class="cs-stat-value" id="intGithubStatus">--</div>
                    <div class="cs-stat-label"><span data-i18n="consciousness.github">GitHub</span></div>
                </div>
            </div>

            <!-- 7. ADR-013 Pipeline Test (collapsible accordion) -->
            <div class="cs-pipeline-accordion">
                <button class="cs-pipeline-toggle" onclick="togglePipelineTest()" id="pipelineToggleBtn">
                    <span class="cs-pipeline-toggle-cap"></span>
                    ADR-013 PIPELINE TEST
                    <i data-lucide="chevron-down" id="pipelineToggleIcon"></i>
                </button>
                <div class="cs-pipeline-body" id="pipelineBody" style="display:none;">
                    <p style="font-size:0.82rem; color:rgba(255,255,255,0.5); margin:0; padding:12px 16px 8px;">
                        Verify translations route through Bridge (ADR-013 compliance)
                    </p>
                    <div style="padding:0 16px 12px;">
                        <button id="testPipelineBtn" onclick="testPipeline()"
                                style="padding:8px 16px; background:rgba(139,92,246,0.2); border:1px solid rgba(139,92,246,0.4); border-radius:6px; color:#8b5cf6; cursor:pointer; font-size:0.85rem; font-family:'Antonio',sans-serif; letter-spacing:0.5px; text-transform:uppercase;">
                            Test Pipeline
                        </button>
                    </div>
                    <div id="pipelineResult" style="padding:0 16px 12px;"></div>
                </div>
            </div>

            <!-- 8. Last Updated -->
            <div class="cs-dashboard-timestamp" id="dashboardTimestamp"></div>

        </div>
```

---

## Exact CSS Additions

Add the following CSS rules inside the `<style>` block in the template, before the existing `@media (min-width: 769px)` block (currently around line 1879):

```css
/* --- Dashboard 3-column activity grid --- */
.cs-dashboard-grid-3 {
    display: grid;
    grid-template-columns: 1fr;
    gap: 20px;
    margin-bottom: 20px;
}
@media (min-width: 768px) {
    .cs-dashboard-grid-3 {
        grid-template-columns: 1fr 1fr 1fr;
    }
}

/* --- Dashboard section divider labels --- */
.cs-dash-section-label {
    font-family: 'Antonio', sans-serif;
    font-size: 0.68rem;
    font-weight: 600;
    color: rgba(255,255,255,0.25);
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-bottom: 10px;
    border-left: 3px solid rgba(139,92,246,0.3);
    padding-left: 8px;
}

/* --- ADR-013 Pipeline Test accordion --- */
.cs-pipeline-accordion {
    margin-bottom: 20px;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    overflow: hidden;
}
.cs-pipeline-toggle {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    background: rgba(255,255,255,0.02);
    border: none;
    cursor: pointer;
    font-family: 'Antonio', sans-serif;
    font-size: 0.75rem;
    font-weight: 600;
    color: rgba(255,255,255,0.35);
    text-transform: uppercase;
    letter-spacing: 1.5px;
    transition: background 0.2s, color 0.2s;
    text-align: left;
}
.cs-pipeline-toggle:hover {
    background: rgba(139,92,246,0.06);
    color: rgba(255,255,255,0.6);
}
.cs-pipeline-toggle.open {
    color: rgba(255,255,255,0.6);
    background: rgba(139,92,246,0.04);
}
.cs-pipeline-toggle-cap {
    width: 6px;
    height: 14px;
    background: rgba(139,92,246,0.4);
    border-radius: 3px;
    flex-shrink: 0;
}
.cs-pipeline-toggle i {
    margin-left: auto;
    width: 14px;
    height: 14px;
    transition: transform 0.2s;
    opacity: 0.4;
}
.cs-pipeline-toggle.open i { opacity: 0.7; }
```

---

## Exact JS Changes

### Change 1: `loadTabData()` switch (replace lines 116–124)

```javascript
switch (tab) {
    case "dashboard":   loadDashboard(); break;
    case "knowledge":   loadKnowledge(); break;
    case "team":        loadTeam(); break;
    case "languages":   loadLanguages(); checkActiveJobs(); break;
    case "github":      loadGitHub(); break;
}
```

### Change 2: `loadDashboard()` — remove compact integration block, add merged calls

Delete this block from inside `loadDashboard()` (currently lines 168–182):
```javascript
// DELETE THIS — compact integration dots no longer used
api("/api/integration/health").then(function (d) {
    if (!d.success) return;
    var sys = d.systems;
    var html = Object.keys(sys).map(function (key) {
        var s = sys[key];
        var dot = s.status === "online" ? "online" : "offline";
        var info = s.projects || s.stations || s.repos || "";
        return '<div class="cs-integration-item">' +
            '<span class="status-dot ' + dot + '"></span>' +
            '<span class="cs-integration-name">' + escHtml(key.toUpperCase()) + '</span>' +
            (info ? '<span class="cs-integration-count">' + info + '</span>' : '') +
            '</div>';
    }).join("");
    setHtml("dashboardIntegration", html);
}).catch(function () {});
```

Then add after the `refreshIcons()` call (currently line 215) and before the closing `}).catch(function (err) {`:
```javascript
    // Load analytics and system health (merged from Insights + Integration tabs)
    loadInsights();
    loadIntegration();
```

### Change 3: HoloSphere node tab references (lines 242–243)

```javascript
// Change tab: "insights" → tab: "dashboard" on both nodes:
{ id: "learned", label: "Learn", count: (kb.mistakes || 0) + (kb.improvements || 0), color: "#06b6d4", tab: "dashboard" },
{ id: "sessions", label: "Sessions", count: kb.sessions || 0, color: "#ec4899", tab: "dashboard" }
```

### Change 4: Add `togglePipelineTest()` — insert after `testPipeline()` (after line 2573)

```javascript
window.togglePipelineTest = function() {
  var body = document.getElementById("pipelineBody");
  var btn = document.getElementById("pipelineToggleBtn");
  var icon = document.getElementById("pipelineToggleIcon");
  if (!body) return;
  var open = body.style.display !== "none";
  body.style.display = open ? "none" : "block";
  if (btn) btn.classList.toggle("open", !open);
  if (icon) icon.style.transform = open ? "" : "rotate(180deg)";
  if (!open) refreshIcons(); // ensure lucide renders chevron if first open
};
```

### Change 5: Delete `switchInsightsSubtab()` (lines 1367–1376)

```javascript
// DELETE this entire function — panel-insights is removed:
window.switchInsightsSubtab = function(sub) {
    document.querySelectorAll("#panel-insights .cs-subtab").forEach(function(b) {
        b.classList.toggle("active", b.textContent.toLowerCase() === sub);
    });
    document.querySelectorAll("#panel-insights .cs-subpanel").forEach(function(p) {
        p.classList.toggle("active", p.id === "insights-" + sub);
    });
    if (sub === "sessions") loadSessions();
    if (sub === "improvements") loadImprovements();
};
```

### Change 6: Update `validTabs` (line 2612)

```javascript
var validTabs = ["dashboard", "knowledge", "team", "languages", "github"];
```

---

## Data Flow

```
switchConsciousnessTab("dashboard")
  └─ loadTabData("dashboard")
       ├─ loadNeuralCore()
       │    ├─ GET /api/dashboard/summary   → sphere node counts
       │    └─ GET /github/stats            → ncGitHubFiles, ncEmbedPct
       └─ loadDashboard()
            ├─ GET /api/dashboard/summary   → activity feed, wellness bars, header stats
            ├─ GET /emotional-state         → mood dot, moodEnergy/Stress/Confidence
            ├─ loadInsights()
            │    └─ GET /api/insights/summary
            │         → insightsBridgeTotal, insightsAvgTime, insightsTokens, insightsGrowth
            └─ loadIntegration()
                 ├─ GET /api/integration/health
                 │    → intDevhqStatus, intBridgeStatus, intOllamaStatus, intGithubStatus
                 └─ GET /api/integration/devhq-summary
                      → intDevhqActivity (recent projects + decisions)

Pipeline test (on demand by user):
  togglePipelineTest()              → shows accordion body
  testPipeline() (user click)
    └─ POST /api/integration/test-pipeline → pipelineResult (step list)
```

---

## Build Sequence Checklist

### Phase 1 — Template

- [ ] 1.1 Update nav comment at line 1917: `<!-- 5-Tab Navigation (GlassNav) -->`
- [ ] 1.2 Delete insights `glass-nav-item` button (lines 1933–1936)
- [ ] 1.3 Delete integration `glass-nav-item` button (lines 1945–1948)
- [ ] 1.4 Add CSS rules for `.cs-dashboard-grid-3`, `.cs-dash-section-label`, `.cs-pipeline-accordion`, `.cs-pipeline-toggle`, `.cs-pipeline-toggle-cap` inside `<style>` block before line 1879
- [ ] 1.5 Replace `panel-dashboard` block (lines 1957–2046) with the new 8-section version
- [ ] 1.6 Delete `panel-insights` block (lines 2161–2198)
- [ ] 1.7 Delete `panel-integration` block (lines 2451–2496)

### Phase 2 — JavaScript

- [ ] 2.1 Update `loadTabData()` switch: remove `insights` and `integration` cases (lines 116–124)
- [ ] 2.2 Remove inline integration health fetch from `loadDashboard()` (lines 168–182)
- [ ] 2.3 Add `loadInsights(); loadIntegration();` calls at end of dashboard summary handler (after `refreshIcons()`, before `.catch`)
- [ ] 2.4 Change `tab: "insights"` to `tab: "dashboard"` on `learned` and `sessions` sphere nodes (lines 242–243)
- [ ] 2.5 Delete `switchInsightsSubtab()` function (lines 1367–1376)
- [ ] 2.6 Add `togglePipelineTest()` function after `testPipeline()` (after line 2573)
- [ ] 2.7 Update `validTabs` array to 5 tabs (line 2612)

### Phase 3 — Verify

- [ ] 3.1 Load `/tools/consciousness` — confirm 5 tabs in nav, Dashboard active
- [ ] 3.2 Dashboard: Analytics row (4 stats) shows real values, not `--`
- [ ] 3.3 Dashboard: 3-col grid shows Recent Activity + Fleet Wellness + Dev HQ Activity
- [ ] 3.4 Dashboard: System Health shows 4 stat cards with real values
- [ ] 3.5 Dashboard: Pipeline accordion collapses/expands; Test Pipeline renders steps
- [ ] 3.6 Hash `#insights` → falls through to dashboard (no blank panel, no JS error)
- [ ] 3.7 Hash `#integration` → falls through to dashboard
- [ ] 3.8 Knowledge tab: ops terminal, browser, categories, embeddings all load
- [ ] 3.9 Team tab: roster, voice, emotional state all load
- [ ] 3.10 Languages tab: ops terminal, coverage, browser, glossary all load
- [ ] 3.11 GitHub tab: intake, cards, discovery console all load
- [ ] 3.12 HoloSphere: click "Learn" and "Sessions" nodes → stays on dashboard, no error
- [ ] 3.13 Mobile (375px): analytics 4-stats wrap to 2×2, 3-col grid stacks to 1-col

---

## Critical Details

**The `dashboardIntegration` element is gone.** The old compact dot grid is replaced by the 4 full stat cards. The inline fetch in `loadDashboard()` that wrote to it must be deleted (lines 168–182). If this block is NOT deleted, `loadDashboard()` will log a silent `setHtml("dashboardIntegration", ...)` call on a null element — not a crash, but wasteful. Delete it cleanly.

**`loadInsights()` and `loadIntegration()` are called unconditionally from `loadDashboard()`.** These functions each have their own `.catch()` handlers. If the API is slow or returns an error, the Dashboard still renders (the stats just remain at `--`). This is correct behavior.

**Cache guard works correctly.** `_cache["dashboard"]` prevents `loadDashboard()` from running twice. Since `loadInsights()` and `loadIntegration()` are now called from inside `loadDashboard()`, they are protected by the same cache guard. There is no separate cache for the removed tabs, so no stale cache entries will interfere.

**`testPipeline()` is unchanged.** It still references `testPipelineBtn` and `pipelineResult` — both IDs are present in the new Dashboard panel. Only `togglePipelineTest()` is new.

**`loadSessions()` and `loadImprovements()` become dead code** — they are never called. Leave them in the JS file for this work session; they can be pruned in a future cleanup pass.

**i18n keys `consciousness.tabs.insights` and `consciousness.tabs.integration`** become orphaned in the `translations` table. This is harmless — they just go unreferenced. No DB cleanup needed.

**No `module_registry.py` or `rbac.py` changes needed** — only the template and JS change. The Consciousness module registration is unchanged.

---

## Files Changed Summary

| File | Net Change | What Changes |
|------|-----------|--------------|
| `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` | ~−70 lines | 5-tab nav, expanded dashboard panel with 8 sections, 3 CSS rules added, 2 panels deleted |
| `platform_v2/static/js/consciousness.js` | ~0 lines net | 7 targeted edits: 2 deletions, 2 additions, 3 modifications |

| File | Status |
|------|--------|
| `platform_v2/tools/consciousness/insights_routes.py` | Unchanged |
| `platform_v2/tools/consciousness/integration_routes.py` | Unchanged |
| `platform_v2/tools/consciousness/team_routes.py` | Unchanged |
| `platform_v2/tools/consciousness/knowledge_routes.py` | Unchanged |
| `platform_v2/tools/consciousness/github_routes.py` | Unchanged |
| `platform_v2/tools/consciousness/routes.py` | Unchanged |
| `platform_v2/tools/consciousness/__init__.py` | Unchanged |
