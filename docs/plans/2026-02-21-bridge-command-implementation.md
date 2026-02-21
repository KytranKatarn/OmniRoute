# Bridge Command Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign Bridge Command into a 5-tab layout with compact status bar, applying Dashboard gold standard visual patterns, responsive at 374px/717px/1280px.

**Architecture:** Replace the single-scroll page with tab-based navigation (Overview/Stations/Dispatch/Crew/Network). Compact status bar replaces the bloated Command Station hero. All existing functionality preserved, just reorganized into focused views with briefing-card styling.

**Tech Stack:** HTML/CSS/JS (inline in Jinja template), Lucide icons, existing Flask API endpoints, Playwright for screenshots.

**Design doc:** `docs/plans/2026-02-21-bridge-command-redesign.md`

**Template:** `platform_v2/templates/tools/bridge.html` (7,233 lines)

---

## Task 1: Add Tab Navigation HTML and CSS

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Context:** The bridge template has CSS at lines 12-3962, HTML at lines 3964-4544, and JS at lines 4548-7233. We need to add tab pill navigation between the header (ends ~line 4040) and the main content (starts ~line 4043), then wrap each content section in a tab panel div.

**Step 1: Add tab pill navigation HTML**

Insert after the header closing `</div>` (after the controls row ~line 4041) and before `.bridge-main`:

```html
<!-- Tab Navigation -->
<nav class="bridge-tabs" id="bridgeTabs">
    <button class="bridge-tab active" data-tab="overview" onclick="switchBridgeTab('overview')">
        <i data-lucide="layout-dashboard"></i>
        <span data-i18n="bridge.tabs.overview">Overview</span>
    </button>
    <button class="bridge-tab" data-tab="stations" onclick="switchBridgeTab('stations')">
        <i data-lucide="radio-tower"></i>
        <span data-i18n="bridge.tabs.stations">Stations</span>
    </button>
    <button class="bridge-tab" data-tab="dispatch" onclick="switchBridgeTab('dispatch')">
        <i data-lucide="activity"></i>
        <span data-i18n="bridge.tabs.dispatch">Dispatch</span>
    </button>
    <button class="bridge-tab" data-tab="crew" onclick="switchBridgeTab('crew')">
        <i data-lucide="users"></i>
        <span data-i18n="bridge.tabs.crew">Crew</span>
    </button>
    <button class="bridge-tab" data-tab="network" onclick="switchBridgeTab('network')">
        <i data-lucide="network"></i>
        <span data-i18n="bridge.tabs.network">Network</span>
    </button>
</nav>
```

**Step 2: Wrap existing content sections in tab panel divs**

Each section gets wrapped in a `<div class="bridge-tab-panel" data-panel="...">`:

- **Overview panel** (new content — Task 3): wrap around new overview HTML
- **Stations panel**: wrap `bridge-command-section` + `bridge-stations-section` (lines ~4046-4083)
- **Dispatch panel**: wrap `bridge-dispatch-section` (lines ~4085-4130)
- **Crew panel**: wrap `crew-manifest-section` + training/lounge from sidebar (lines ~4132-4142 + sidebar training/lounge ~4252-4290)
- **Network panel**: wrap `bridge-nodes-section` + `model-availability-section` (lines ~4145-4215)

Only the active panel gets `display: block`; others are hidden.

**Step 3: Add tab CSS**

Add to the CSS section (before responsive media queries):

```css
/* ============================================================================
   TAB NAVIGATION
   ============================================================================ */
.bridge-tabs {
    display: flex;
    gap: 4px;
    padding: 0 16px 12px;
    border-bottom: 1px solid rgba(0, 255, 255, 0.1);
    margin-bottom: 16px;
    overflow-x: auto;
    scrollbar-width: none;
}
.bridge-tabs::-webkit-scrollbar { display: none; }

.bridge-tab {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 16px;
    background: transparent;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    color: var(--archie-text-tertiary, #8b949e);
    font-family: var(--archie-font-mono, 'JetBrains Mono', monospace);
    font-size: 0.75rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    position: relative;
}
.bridge-tab i {
    width: 14px;
    height: 14px;
}
.bridge-tab:hover {
    color: var(--archie-text-secondary, #c9d1d9);
    border-color: rgba(255, 255, 255, 0.15);
    background: rgba(255, 255, 255, 0.03);
}
.bridge-tab.active {
    color: var(--archie-cyan, #00ffff);
    border-color: var(--archie-cyan, #00ffff);
    background: rgba(0, 255, 255, 0.06);
}
.bridge-tab.active::after {
    content: '';
    position: absolute;
    bottom: -1px;
    left: 20%;
    width: 60%;
    height: 2px;
    background: var(--archie-cyan, #00ffff);
    border-radius: 1px;
}

/* Tab panels */
.bridge-tab-panel {
    display: none;
}
.bridge-tab-panel.active {
    display: block;
}

/* Light mode */
[data-theme="light"] .bridge-tab,
body.light-mode .bridge-tab {
    border-color: rgba(0, 0, 0, 0.1);
    color: #57606a;
}
[data-theme="light"] .bridge-tab:hover,
body.light-mode .bridge-tab:hover {
    color: #24292f;
    border-color: rgba(0, 0, 0, 0.2);
}
[data-theme="light"] .bridge-tab.active,
body.light-mode .bridge-tab.active {
    color: #0969da;
    border-color: #0969da;
    background: rgba(9, 105, 218, 0.06);
}
[data-theme="light"] .bridge-tab.active::after,
body.light-mode .bridge-tab.active::after {
    background: #0969da;
}
```

**Step 4: Add tab switching JS**

Add to the JS section (near the top, after `toggleBridgeControls()`):

```javascript
// === Tab Navigation ===
function switchBridgeTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.bridge-tab').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    // Update panels
    document.querySelectorAll('.bridge-tab-panel').forEach(function(panel) {
        panel.classList.toggle('active', panel.dataset.panel === tabName);
    });
    // Update URL hash
    history.replaceState(null, '', '#' + tabName);
    // Trigger data load for the tab if needed
    if (tabName === 'stations') loadStations();
    if (tabName === 'dispatch') loadDispatchActivity();
    if (tabName === 'crew') loadCrewManifest();
    if (tabName === 'network') { loadNodes(); loadModelAvailability(); }
    // Re-render Lucide icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Restore tab from URL hash on load
(function() {
    var hash = window.location.hash.replace('#', '');
    var validTabs = ['overview', 'stations', 'dispatch', 'crew', 'network'];
    if (hash && validTabs.indexOf(hash) !== -1) {
        switchBridgeTab(hash);
    }
})();
```

**Step 5: Take Playwright screenshots to verify tab structure**

Run: `node platform_v2/tests/bridge-screenshots.mjs`

**Step 6: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): add 5-tab navigation with panel switching"
```

---

## Task 2: Replace Command Station Hero with Compact Status Bar

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Context:** The Command Station hero (lines ~4046-4071) is a 3-slot display (Commander/Center/Co-Commander) that takes ~200px of vertical space. Replace it with a slim status bar that shows key metrics inline.

**Step 1: Replace Command Station HTML**

Replace the `.bridge-command-section` content with a compact status bar inside the **Overview tab panel**:

```html
<div class="bridge-status-bar">
    <div class="status-bar-item">
        <span class="status-bar-dot online" id="overviewBridgeDot"></span>
        <span class="status-bar-label" data-i18n="bridge.status.bridge">Bridge</span>
        <span class="status-bar-value" id="overviewBridgeStatus">Online</span>
    </div>
    <div class="status-bar-divider"></div>
    <div class="status-bar-item">
        <i data-lucide="route" class="status-bar-icon"></i>
        <span class="status-bar-label" data-i18n="bridge.status.routing">Routing</span>
        <span class="status-bar-value" id="overviewRoutingMode">local_cloud</span>
    </div>
    <div class="status-bar-divider"></div>
    <div class="status-bar-item">
        <i data-lucide="zap" class="status-bar-icon"></i>
        <span class="status-bar-label" data-i18n="bridge.status.interactions_24h">24h Activity</span>
        <span class="status-bar-value" id="overviewInteractions">--</span>
    </div>
    <div class="status-bar-divider"></div>
    <div class="status-bar-item">
        <i data-lucide="users" class="status-bar-icon"></i>
        <span class="status-bar-label" data-i18n="bridge.status.agents">Agents</span>
        <span class="status-bar-value" id="overviewAgentCount">--</span>
    </div>
    <div class="status-bar-divider"></div>
    <div class="status-bar-item">
        <i data-lucide="clock" class="status-bar-icon"></i>
        <span class="status-bar-value" id="overviewClock">--:--</span>
    </div>
</div>
```

**Step 2: Add status bar CSS**

```css
/* Compact status bar (replaces Command Station hero) */
.bridge-status-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 16px;
    background: rgba(0, 0, 0, 0.3);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(0, 255, 255, 0.1);
    border-radius: 8px;
    margin: 0 16px 12px;
}
.status-bar-item {
    display: flex;
    align-items: center;
    gap: 6px;
}
.status-bar-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #ff6b6b;
}
.status-bar-dot.online {
    background: #00ff41;
    box-shadow: 0 0 6px rgba(0, 255, 65, 0.5);
}
.status-bar-icon {
    width: 14px;
    height: 14px;
    color: var(--archie-text-tertiary, #8b949e);
}
.status-bar-label {
    font-family: var(--archie-font-mono, 'JetBrains Mono', monospace);
    font-size: 0.65rem;
    color: var(--archie-text-tertiary, #8b949e);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.status-bar-value {
    font-family: var(--archie-font-mono, 'JetBrains Mono', monospace);
    font-size: 0.75rem;
    color: var(--archie-cyan, #00ffff);
    font-weight: 600;
}
.status-bar-divider {
    width: 1px;
    height: 20px;
    background: rgba(255, 255, 255, 0.1);
}
```

**Step 3: Wire status bar data to existing API**

Add JS to populate the status bar from existing `loadRoutingMode()` and station data:

```javascript
function updateOverviewStatusBar() {
    fetch('/tools/bridge/api/traffic')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.success) {
                var el = document.getElementById('overviewInteractions');
                if (el) el.textContent = data.total_today || 0;
            }
        }).catch(function() {});
}
```

**Step 4: Remove old Command Station CSS** that's no longer needed (`.command-station`, `.command-slot`, `.command-center-display` — lines ~401-600).

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): replace command station hero with compact status bar"
```

---

## Task 3: Build Overview Tab Content

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Context:** The Overview tab is new content — HUD pods for metrics, briefing cards for quick-glance status, and a mini activity feed.

**Step 1: Add Overview tab HTML**

Inside the overview panel div:

```html
<div class="bridge-tab-panel active" data-panel="overview">
    <!-- Status Bar (from Task 2) -->
    ...

    <!-- HUD Pods -->
    <div class="bridge-hud-strip">
        <div class="bridge-hud-pod">
            <span class="bridge-hud-label" data-i18n="bridge.overview.throughput">Throughput</span>
            <div class="bridge-hud-value" id="hudThroughput">--</div>
            <span class="bridge-hud-unit">req/min</span>
        </div>
        <div class="bridge-hud-pod">
            <span class="bridge-hud-label" data-i18n="bridge.overview.agents">Agent Utilization</span>
            <div class="bridge-hud-value" id="hudAgentUtil">--%</div>
        </div>
        <div class="bridge-hud-pod">
            <span class="bridge-hud-label" data-i18n="bridge.overview.models">Model Health</span>
            <div class="bridge-hud-value" id="hudModelHealth">--</div>
        </div>
        <div class="bridge-hud-pod">
            <span class="bridge-hud-label" data-i18n="bridge.overview.iaae">IAAE Score</span>
            <div class="bridge-hud-value" id="hudIAAE">--%</div>
        </div>
    </div>

    <!-- Briefing Cards Row -->
    <div class="bridge-overview-cards">
        <div class="briefing-card" style="--card-accent: #00ff41;">
            <div class="briefing-card-header">
                <i data-lucide="cpu"></i>
                <span data-i18n="bridge.overview.ai_status">AI Bridge Status</span>
            </div>
            <div class="briefing-card-body" id="overviewAiStatus">
                <span class="briefing-muted">Loading...</span>
            </div>
        </div>
        <div class="briefing-card" style="--card-accent: #ffaa00;">
            <div class="briefing-card-header">
                <i data-lucide="radio-tower"></i>
                <span data-i18n="bridge.overview.station_summary">Station Summary</span>
            </div>
            <div class="briefing-card-body" id="overviewStationSummary">
                <span class="briefing-muted">Loading...</span>
            </div>
        </div>
        <div class="briefing-card" style="--card-accent: #8b5cf6;">
            <div class="briefing-card-header">
                <i data-lucide="shield-check"></i>
                <span data-i18n="bridge.overview.iaae_health">IAAE Health</span>
            </div>
            <div class="briefing-card-body" id="overviewIAAE">
                <span class="briefing-muted">Loading...</span>
            </div>
        </div>
    </div>

    <!-- Mini Activity Feed -->
    <div class="briefing-card" style="--card-accent: #00ffff;">
        <div class="briefing-card-header">
            <i data-lucide="activity"></i>
            <span data-i18n="bridge.overview.recent_activity">Recent Activity</span>
            <a href="#dispatch" onclick="switchBridgeTab('dispatch'); return false;" class="briefing-card-link" data-i18n="bridge.overview.view_all">View All</a>
        </div>
        <div class="briefing-card-body" id="overviewActivity">
            <span class="briefing-muted">Loading...</span>
        </div>
    </div>
</div>
```

**Step 2: Add briefing card + HUD pod CSS**

Use the Dashboard patterns:
- `.briefing-card` — backdrop-blur, accent header with gradient line
- `.bridge-hud-strip` — flex row of metric pods
- `.bridge-hud-pod` — rounded card with value/label/unit
- `.bridge-overview-cards` — 3-column grid

**Step 3: Add JS to populate Overview content**

```javascript
function loadOverviewData() {
    // Fetch AI status, station summary, IAAE health, mini activity
    // Populate the briefing card bodies
}
```

Wire to existing endpoints: `/api/traffic`, `/api/stations`, `/api/iaae/check-move/0`, `/api/dispatch/activity-history`.

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): build overview tab with HUD pods and briefing cards"
```

---

## Task 4: Polish Stations Tab with Briefing-Card Pattern

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Context:** The station cards exist but need the gold standard visual treatment. The Command Station 3-slot display moves into the Stations tab as a compact commander indicator rather than a hero section.

**Step 1: Wrap station grid in Stations tab panel**

Move the existing `bridge-stations-section` content into the stations panel div. Remove the old Command Station 3-slot hero — replace with a compact "Command Team" badge row above the grid showing Commander + Co-Commander.

**Step 2: Restyle station cards with briefing-card pattern**

Update `.bridge-station-card` CSS to match briefing-card:
- `background: rgba(0, 0, 0, 0.4)`, `backdrop-filter: blur(10px)`
- Station accent color as `--card-accent` (use existing `STATION_COLORS`)
- Accent header line with gradient `::before`
- Rounded corners (12px)
- Light mode overrides

**Step 3: Update `createStationCard()` JS function**

Modify the card rendering function to use new CSS classes and add briefing-card markup structure.

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): polish station cards with briefing-card pattern"
```

---

## Task 5: Polish Dispatch Tab

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Context:** Move dispatch content (lines ~4085-4130) into the dispatch tab panel. Apply briefing-card styling to dispatch stats, active jobs, and history list.

**Step 1: Wrap dispatch section in tab panel**

**Step 2: Style dispatch stats as HUD pods**

The 4 dispatch stats (total/success/fail/avg ms) become a HUD pod strip.

**Step 3: Style active jobs and history as briefing cards**

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): polish dispatch tab with briefing-card styling"
```

---

## Task 6: Build Crew Tab (Merge Manifest + Training + Lounge)

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Context:** Crew Manifest (lines ~4132-4142), Training Rooms (sidebar ~4252-4270), and Lounge (sidebar ~4270-4290) are currently scattered. Merge them into the Crew tab with sub-sections.

**Step 1: Create Crew tab panel with 3 sub-sections**

Use collapsible sections or mini-tab pills within the Crew tab:
- Manifest (default visible)
- Training Rooms
- Lounge

**Step 2: Move training and lounge HTML from sidebar into Crew tab**

**Step 3: Style crew agent cards with briefing-card pattern**

**Step 4: Update `loadCrewManifest()` to also load training + lounge data**

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): merge crew manifest, training, and lounge into crew tab"
```

---

## Task 7: Build Network Tab (Merge Nodes + Models + Providers)

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Context:** Node Network (lines ~4145-4198), Model Availability (lines ~4201-4215), and External Providers are currently separate sections. Merge into Network tab.

**Step 1: Create Network tab panel**

Move nodes grid, pending approvals, model availability, and agent mesh/learning patterns into the Network panel.

**Step 2: Apply briefing-card styling to node cards and model cards**

**Step 3: Remove old sidebar sections that are now empty**

After moving IAAE to Overview and Training/Lounge to Crew, the sidebar only has Remote Connections. Either remove the sidebar entirely or keep as a slim panel.

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): merge nodes, models, providers into network tab"
```

---

## Task 8: Responsive Polish

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Context:** Update responsive breakpoints for the new tab-based layout.

**Step 1: Add tab responsiveness**

```css
@media (max-width: 768px) {
    .bridge-tab span { display: none; }  /* Icon-only tabs on mobile */
    .bridge-tab { padding: 8px 12px; }
    .bridge-overview-cards { grid-template-columns: 1fr; }
    .bridge-hud-strip { flex-wrap: wrap; }
    .bridge-hud-pod { flex: 1 1 45%; }
    .bridge-status-bar { flex-wrap: wrap; gap: 8px; }
}

@media (max-width: 480px) {
    .bridge-hud-pod { flex: 1 1 100%; }
    .status-bar-divider { display: none; }
    .bridge-status-bar { justify-content: space-around; }
}
```

**Step 2: Test at 374px, 717px, 1280px**

Run: `node platform_v2/tests/bridge-screenshots.mjs`

**Step 3: Fix any overflow or layout issues found in screenshots**

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): responsive polish for tab layout at all breakpoints"
```

---

## Task 9: Clean Up and Final Verification

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html`

**Step 1: Remove dead CSS for old layout**

Remove CSS for `.bridge-sidebar` if sidebar is gone, old `.command-station` styles, and any orphaned selectors.

**Step 2: Resolve TODO comments**

- Line ~5048: `const skillMatch = true; // TODO` — remove the TODO, skill match is acceptable as true for now (no skill validation API exists)
- Line ~5130: `// TODO: API call to update assignment` — wire to existing `PUT /api/assignments/<id>` endpoint

**Step 3: Final Playwright screenshots at all 3 breakpoints**

Verify all 5 tabs look correct at 374px, 717px, 1280px. That's 15 screenshots total.

**Step 4: Final commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): final cleanup, dead CSS removal, TODO resolution"
```

---

## Summary

| Task | Description | Estimated Scope |
|------|-------------|-----------------|
| 1 | Tab navigation + panel switching | CSS + HTML + JS scaffolding |
| 2 | Compact status bar | Replace hero section |
| 3 | Overview tab content | New briefing cards + HUD pods |
| 4 | Stations tab polish | Restyle existing cards |
| 5 | Dispatch tab polish | Restyle existing content |
| 6 | Crew tab (merge 3 sections) | Restructure + restyle |
| 7 | Network tab (merge 3 sections) | Restructure + restyle |
| 8 | Responsive polish | All breakpoints |
| 9 | Cleanup + verification | Dead code, TODOs, final test |
