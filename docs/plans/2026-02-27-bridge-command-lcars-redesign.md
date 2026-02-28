# Bridge Command — Full LCARS Redesign Pass

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert Bridge Command's custom `.briefing-card` sci-fi aesthetic to the LCARS gold standard design system used in Dashboard/Consciousness/Dev HQ.

**Architecture:** CSS-only restyle of the existing `<style>` block in `bridge.html` (line 5866 is `</style>`). Override existing classes to LCARS signature patterns (asymmetric radius, left gradient bars, GlassNav tabs, LCARS form controls). One JS change for leaderboard row styling. No HTML template restructuring.

**Tech Stack:** CSS3 (custom properties, `::before` pseudo-elements, `backdrop-filter`), existing `--card-accent` color system.

---

### Task 1: Briefing Cards → LCARS Panels

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:5684-5738` (`.briefing-card` CSS rules)

**Step 1: Replace `.briefing-card` base styles**

Find the existing rules at line 5684 and replace:

```css
/* BEFORE (line 5684-5691): */
.briefing-card {
    background: rgba(0, 0, 0, 0.4);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    overflow: hidden;
    min-width: 0;
}

/* AFTER: */
.briefing-card {
    background: rgba(0, 0, 0, 0.4);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(var(--card-accent-rgb, 0,255,255), 0.12);
    border-left: 3px solid rgba(var(--card-accent-rgb, 0,255,255), 0.4);
    border-radius: 2px 12px 12px 2px;
    overflow: hidden;
    min-width: 0;
    position: relative;
}
.briefing-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: linear-gradient(180deg,
        rgba(var(--card-accent-rgb, 0,255,255), 0.6) 0%,
        rgba(var(--card-accent-rgb, 0,255,255), 0.15) 50%,
        rgba(var(--card-accent-rgb, 0,255,255), 0.6) 100%);
    pointer-events: none;
    z-index: 1;
}
```

**Step 2: Replace `.briefing-card-header` styles**

Find at line 5692 and replace:

```css
/* BEFORE (line 5692-5713): */
.briefing-card-header {
    ...
    border-bottom: 2px solid var(--card-accent, #00ffff);
    ...
}
.briefing-card-header::before {
    ...
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--card-accent, #00ffff), transparent);
}

/* AFTER: */
.briefing-card-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-bottom: 1px solid rgba(var(--card-accent-rgb, 0,255,255), 0.15);
    font-family: 'Orbitron', var(--archie-font-display, sans-serif);
    font-size: 0.7rem;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--card-accent, #00ffff);
    position: relative;
    background: rgba(var(--card-accent-rgb, 0,255,255), 0.04);
}
.briefing-card-header::before {
    display: none; /* Left bar on parent replaces top gradient */
}
```

**Step 3: Add `--card-accent-rgb` variables to each card instance**

Add a CSS block that maps each `--card-accent` hex to its RGB counterpart (needed for `rgba()` functions). Insert before the closing `</style>` at line 5866:

```css
/* LCARS accent RGB mapping for briefing cards */
.briefing-card[style*="--card-accent: #00ff41"] { --card-accent-rgb: 0,255,65; }
.briefing-card[style*="--card-accent: #ffaa00"] { --card-accent-rgb: 255,170,0; }
.briefing-card[style*="--card-accent: #8b5cf6"] { --card-accent-rgb: 139,92,246; }
.briefing-card[style*="--card-accent: #ff6b6b"] { --card-accent-rgb: 255,107,107; }
.briefing-card[style*="--card-accent: #00ffff"] { --card-accent-rgb: 0,255,255; }
.briefing-card[style*="--card-accent: #58a6ff"] { --card-accent-rgb: 88,166,255; }
.briefing-card[style*="--card-accent: #fbbf24"] { --card-accent-rgb: 251,191,36; }
```

**Step 4: Update light mode briefing card overrides**

Replace light mode rules at line 5808-5817:

```css
[data-theme="light"] .briefing-card,
body.light-mode .briefing-card {
    background: rgba(255, 255, 255, 0.7);
    border-color: rgba(var(--card-accent-rgb, 0,255,255), 0.15);
    border-left-color: rgba(var(--card-accent-rgb, 0,255,255), 0.25);
}
[data-theme="light"] .briefing-card::before,
body.light-mode .briefing-card::before {
    background: linear-gradient(180deg,
        rgba(var(--card-accent-rgb, 0,255,255), 0.35) 0%,
        rgba(var(--card-accent-rgb, 0,255,255), 0.1) 50%,
        rgba(var(--card-accent-rgb, 0,255,255), 0.35) 100%);
}
[data-theme="light"] .briefing-card-header,
body.light-mode .briefing-card-header {
    background: rgba(var(--card-accent-rgb, 0,255,255), 0.06);
    color: color-mix(in srgb, var(--card-accent, #0969da) 80%, #000);
}
[data-theme="light"] .briefing-card-body,
body.light-mode .briefing-card-body {
    color: #24292f;
}
```

**Step 5: Restart and verify**

Run: `docker compose restart archie_platform`
Navigate to Bridge → Overview tab. Verify cards have asymmetric radius, left gradient bar, accent-tinted headers.

**Step 6: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): LCARS briefing cards — asymmetric radius + left gradient bars"
```

---

### Task 2: Tab Navigation → GlassNav

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:4897-4979` (`.bridge-tabs`, `.bridge-tab` rules)

**Step 1: Replace `.bridge-tabs` container**

```css
/* BEFORE (line 4897-4905): */
.bridge-tabs {
    display: flex;
    gap: 4px;
    padding: 0 16px 8px;
    border-bottom: 1px solid rgba(0, 255, 255, 0.1);
    margin-bottom: 8px;
    overflow-x: auto;
    scrollbar-width: none;
}

/* AFTER: */
.bridge-tabs {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 2px;
    padding: 5px 6px;
    margin: 0 16px 12px;
    background: rgba(15, 15, 30, 0.6);
    backdrop-filter: blur(16px) saturate(1.4);
    -webkit-backdrop-filter: blur(16px) saturate(1.4);
    border: 1px solid rgba(0, 255, 255, 0.15);
    border-radius: 20px;
    box-shadow: 0 4px 30px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04);
    overflow-x: auto;
    scrollbar-width: none;
}
```

**Step 2: Replace `.bridge-tab` items**

```css
/* BEFORE (line 4908-4949): */
.bridge-tab { ... border-radius: 8px; font-family: monospace; ... }
.bridge-tab.active { ... border-color: cyan; ... }
.bridge-tab.active::after { ... bottom underline ... }

/* AFTER: */
.bridge-tab {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    background: none;
    border: none;
    border-radius: 14px;
    color: rgba(255, 255, 255, 0.35);
    font-family: 'Antonio', sans-serif;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    cursor: pointer;
    white-space: nowrap;
    transition: color 0.2s, background 0.2s;
    position: relative;
}
.bridge-tab:hover {
    color: rgba(255, 255, 255, 0.65);
}
.bridge-tab.active {
    color: #fff;
    background: rgba(0, 255, 255, 0.18);
    box-shadow: 0 0 20px rgba(0, 255, 255, 0.15), inset 0 0 8px rgba(0, 255, 255, 0.08);
}
.bridge-tab.active::after {
    content: '';
    position: absolute;
    bottom: 2px;
    left: 25%; right: 25%;
    height: 2px;
    border-radius: 1px;
    background: #00ffff;
    box-shadow: 0 0 8px rgba(0, 255, 255, 0.5);
}
.bridge-tab i, .bridge-tab svg { width: 14px; height: 14px; }
```

**Step 3: Apply same GlassNav to `.crew-subtabs`**

Replace rules at line 3113-3150:

```css
.crew-subtabs {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 2px;
    padding: 5px 6px;
    margin: 0 16px 12px;
    background: rgba(15, 15, 30, 0.6);
    backdrop-filter: blur(16px) saturate(1.4);
    -webkit-backdrop-filter: blur(16px) saturate(1.4);
    border: 1px solid rgba(139, 92, 246, 0.15);
    border-radius: 20px;
    box-shadow: 0 4px 30px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.04);
}
.crew-subtab {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 6px 12px;
    background: none;
    border: none;
    border-radius: 14px;
    color: rgba(255, 255, 255, 0.35);
    font-family: 'Antonio', sans-serif;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    cursor: pointer;
    white-space: nowrap;
    transition: color 0.2s, background 0.2s;
}
.crew-subtab:hover {
    color: rgba(255, 255, 255, 0.65);
}
.crew-subtab.active {
    color: #fff;
    background: rgba(139, 92, 246, 0.18);
    box-shadow: 0 0 20px rgba(139, 92, 246, 0.15), inset 0 0 8px rgba(139, 92, 246, 0.08);
}
.crew-subtab i, .crew-subtab svg { width: 14px; height: 14px; }
```

**Step 4: Update light mode tab rules**

```css
[data-theme="light"] .bridge-tabs,
body.light-mode .bridge-tabs {
    background: rgba(255, 255, 255, 0.7);
    border-color: rgba(0, 0, 0, 0.08);
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
[data-theme="light"] .bridge-tab,
body.light-mode .bridge-tab {
    color: rgba(0, 0, 0, 0.4);
}
[data-theme="light"] .bridge-tab:hover,
body.light-mode .bridge-tab:hover {
    color: rgba(0, 0, 0, 0.65);
}
[data-theme="light"] .bridge-tab.active,
body.light-mode .bridge-tab.active {
    color: #0969da;
    background: rgba(9, 105, 218, 0.1);
    box-shadow: none;
}
[data-theme="light"] .bridge-tab.active::after,
body.light-mode .bridge-tab.active::after {
    background: #0969da;
    box-shadow: none;
}
[data-theme="light"] .crew-subtabs,
body.light-mode .crew-subtabs {
    background: rgba(255, 255, 255, 0.7);
    border-color: rgba(139, 92, 246, 0.12);
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
[data-theme="light"] .crew-subtab.active,
body.light-mode .crew-subtab.active {
    color: #7c3aed;
    background: rgba(139, 92, 246, 0.1);
    box-shadow: none;
}
```

**Step 5: Restart and verify**

Navigate to Bridge → all tabs. Verify frosted glass pill nav. Check Crew sub-tabs match.

**Step 6: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): GlassNav tabs — frosted glass pill navigation"
```

---

### Task 3: HUD Pods → LCARS Stat Cards

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:5629-5672` (`.bridge-hud-*` rules)

**Step 1: Replace HUD pod styles**

```css
/* BEFORE (line 5635-5647): */
.bridge-hud-pod {
    flex: 1 1 0;
    ...
    border: 1px solid rgba(0, 255, 255, 0.12);
    border-radius: 12px;
    ...
}

/* AFTER: */
.bridge-hud-pod {
    flex: 1 1 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 12px 8px;
    background: rgba(0, 0, 0, 0.35);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(0, 255, 255, 0.12);
    border-left: 3px solid rgba(0, 255, 255, 0.4);
    border-radius: 2px 10px 10px 2px;
    transition: border-color 0.3s ease, box-shadow 0.3s ease;
    position: relative;
    overflow: hidden;
}
.bridge-hud-pod::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: linear-gradient(180deg,
        rgba(0,255,255,0.6) 0%,
        rgba(0,255,255,0.15) 50%,
        rgba(0,255,255,0.6) 100%);
    pointer-events: none;
}
.bridge-hud-pod:hover {
    border-color: rgba(0, 255, 255, 0.25);
    box-shadow: 0 0 12px rgba(0, 255, 255, 0.06);
}
```

**Step 2: Update label font to Antonio**

```css
/* BEFORE (line 5652-5658): */
.bridge-hud-label {
    font-family: var(--archie-font-mono, 'JetBrains Mono', monospace);
    ...
}

/* AFTER: */
.bridge-hud-label {
    font-family: 'Antonio', sans-serif;
    font-size: 0.6rem;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.5);
    text-transform: uppercase;
    letter-spacing: 0.15em;
}
```

**Step 3: Update light mode HUD pod overrides**

```css
[data-theme="light"] .bridge-hud-pod,
body.light-mode .bridge-hud-pod {
    background: rgba(255, 255, 255, 0.6);
    border-color: rgba(0, 0, 0, 0.08);
    border-left-color: rgba(0, 150, 200, 0.3);
}
[data-theme="light"] .bridge-hud-pod::before,
body.light-mode .bridge-hud-pod::before {
    background: linear-gradient(180deg,
        rgba(0,150,200,0.3) 0%,
        rgba(0,150,200,0.08) 50%,
        rgba(0,150,200,0.3) 100%);
}
```

**Step 4: Restart and verify**

Navigate to Bridge → Overview tab, Dispatch tab. Verify HUD pods have asymmetric radius, left bar.

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): LCARS HUD pods — asymmetric stat cards"
```

---

### Task 4: Status Bar → LCARS Readout Strip

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:283-346` (`.bridge-status-bar` rules)

**Step 1: Replace status bar styles**

```css
/* BEFORE (line 283-293): */
.bridge-status-bar {
    ...
    border: 1px solid rgba(0, 255, 255, 0.1);
    border-radius: 8px;
}

/* AFTER: */
.bridge-status-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 16px 8px 0;
    margin: 0 16px 12px;
    background: rgba(0, 0, 0, 0.3);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(0, 255, 255, 0.12);
    border-left: none;
    border-radius: 2px 8px 8px 2px;
    position: relative;
    overflow: hidden;
}
.bridge-status-bar::before {
    content: '';
    flex-shrink: 0;
    width: 8px;
    align-self: stretch;
    background: #00ffff;
    box-shadow: 0 0 8px rgba(0, 255, 255, 0.3);
    border-radius: 2px 0 0 2px;
}
```

**Step 2: Update `.status-bar-value` font**

```css
.status-bar-value {
    font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
    font-size: 0.75rem;
    font-weight: 600;
    color: #00ffff;
}
.status-bar-label {
    font-family: 'Antonio', sans-serif;
    font-size: 0.65rem;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.5);
    text-transform: uppercase;
    letter-spacing: 0.1em;
}
```

**Step 3: Update light mode status bar**

```css
[data-theme="light"] .bridge-status-bar,
body.light-mode .bridge-status-bar {
    background: rgba(255, 255, 255, 0.6);
    border-color: rgba(0, 0, 0, 0.1);
}
[data-theme="light"] .bridge-status-bar::before,
body.light-mode .bridge-status-bar::before {
    background: #0969da;
    box-shadow: none;
}
[data-theme="light"] .status-bar-value,
body.light-mode .status-bar-value {
    color: #0969da;
}
```

**Step 4: Restart and verify**

Navigate to Bridge → Overview tab. Verify status bar has left cyan endcap, asymmetric radius.

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): LCARS status bar — readout strip with endcap"
```

---

### Task 5: Form Elements → LCARS Inputs & Buttons

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html` (add new CSS rules before `</style>`)

**Step 1: Add LCARS form control styles**

Insert before `</style>` at line 5866:

```css
/* ── LCARS Form Controls ──────────────────────────── */
.bridge-tab-panel select,
.bridge-tab-panel input[type="text"],
.bridge-tab-panel textarea {
    width: auto;
    padding: 8px 12px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(139, 92, 246, 0.15);
    border-left: 3px solid rgba(139, 92, 246, 0.3);
    border-radius: 0 8px 8px 0;
    color: rgba(255, 255, 255, 0.9);
    font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
    font-size: 0.8rem;
    outline: none;
    transition: border-color 0.2s, box-shadow 0.2s;
}
.bridge-tab-panel select:focus,
.bridge-tab-panel input[type="text"]:focus,
.bridge-tab-panel textarea:focus {
    border-color: rgba(139, 92, 246, 0.5);
    border-left-color: rgba(139, 92, 246, 0.7);
    box-shadow: 0 0 12px rgba(139, 92, 246, 0.15), inset 0 0 6px rgba(139, 92, 246, 0.05);
    background: rgba(255, 255, 255, 0.04);
}
.bridge-tab-panel select option {
    background: #0d1117;
    color: rgba(255, 255, 255, 0.9);
}

/* LCARS pill buttons — all inline-styled buttons in tab panels */
.bridge-tab-panel button:not(.bridge-tab):not(.crew-subtab):not(.lcars-console-close) {
    padding: 6px 16px;
    background: rgba(0, 255, 65, 0.12);
    border: 1px solid rgba(0, 255, 65, 0.3);
    border-radius: 20px;
    color: rgba(0, 255, 65, 0.9);
    font-family: 'Antonio', sans-serif;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    cursor: pointer;
    overflow: hidden;
    position: relative;
    transition: background 0.2s, border-color 0.2s, box-shadow 0.2s;
}
.bridge-tab-panel button:not(.bridge-tab):not(.crew-subtab):not(.lcars-console-close):hover {
    background: rgba(0, 255, 65, 0.2);
    border-color: rgba(0, 255, 65, 0.5);
    box-shadow: 0 0 16px rgba(0, 255, 65, 0.2);
}

/* Danger buttons (REMOVE, Disable) */
.bridge-tab-panel button[onclick*="remove"],
.bridge-tab-panel button[onclick*="Remove"],
.bridge-tab-panel button[onclick*="disable"],
.bridge-tab-panel button[onclick*="Disable"] {
    background: rgba(239, 68, 68, 0.12);
    border-color: rgba(239, 68, 68, 0.3);
    color: rgba(239, 68, 68, 0.9);
}
.bridge-tab-panel button[onclick*="remove"]:hover,
.bridge-tab-panel button[onclick*="Remove"]:hover,
.bridge-tab-panel button[onclick*="disable"]:hover,
.bridge-tab-panel button[onclick*="Disable"]:hover {
    background: rgba(239, 68, 68, 0.2);
    border-color: rgba(239, 68, 68, 0.5);
    box-shadow: 0 0 16px rgba(239, 68, 68, 0.2);
}

/* Light mode form controls */
[data-theme="light"] .bridge-tab-panel select,
body.light-mode .bridge-tab-panel select,
[data-theme="light"] .bridge-tab-panel input[type="text"],
body.light-mode .bridge-tab-panel input[type="text"] {
    background: rgba(255, 255, 255, 0.8);
    border-color: rgba(139, 92, 246, 0.18);
    border-left-color: rgba(139, 92, 246, 0.25);
    color: #1f2937;
}
[data-theme="light"] .bridge-tab-panel button:not(.bridge-tab):not(.crew-subtab),
body.light-mode .bridge-tab-panel button:not(.bridge-tab):not(.crew-subtab) {
    background: rgba(0, 128, 40, 0.08);
    border-color: rgba(0, 128, 40, 0.25);
    color: #166534;
}
```

**Step 2: Restart and verify**

Navigate to Crew → Training (dropdowns), Lounge (text input, buttons), Network (Add Node button). Verify LCARS styling.

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): LCARS form controls — styled inputs, selects, pill buttons"
```

---

### Task 6: Crew Agent Cards + Contractor Cards → LCARS Panels

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:2951-2957` (`.crew-manifest-section`), and add new rules before `</style>`

**Step 1: Replace `.crew-manifest-section` styles**

```css
/* BEFORE (line 2951-2957): */
.crew-manifest-section {
    margin-top: 1.5rem;
    background: var(--archie-bg-secondary);
    border-radius: 8px;
    border: 1px solid var(--archie-border-default);
    overflow: hidden;
}

/* AFTER: */
.crew-manifest-section {
    margin-top: 1.5rem;
    background: rgba(0, 0, 0, 0.3);
    border: 1px solid rgba(139, 92, 246, 0.12);
    border-left: 3px solid rgba(139, 92, 246, 0.4);
    border-radius: 2px 12px 12px 2px;
    overflow: hidden;
    position: relative;
}
.crew-manifest-section::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: linear-gradient(180deg,
        rgba(139,92,246,0.6) 0%,
        rgba(139,92,246,0.15) 50%,
        rgba(139,92,246,0.6) 100%);
    pointer-events: none; z-index: 1;
}
```

**Step 2: Add LCARS styles for dynamically-rendered crew rows**

Insert before `</style>`:

```css
/* ── Crew Manifest Rows — LCARS ──────────────────── */
.crew-manifest-grid > div,
#crew-manifest-list > div {
    border-radius: 2px 8px 8px 2px !important;
    border-left: 3px solid var(--station-color, rgba(139,92,246,0.4)) !important;
    position: relative;
}

/* ── Contractor Firms — LCARS ────────────────────── */
.contractor-firm {
    border-radius: 2px 12px 12px 2px !important;
    border-left: 3px solid rgba(168, 85, 247, 0.4) !important;
    position: relative;
}
.contractor-firm::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: linear-gradient(180deg,
        rgba(168,85,247,0.6) 0%,
        rgba(168,85,247,0.15) 50%,
        rgba(168,85,247,0.6) 100%);
    pointer-events: none; z-index: 1;
}

/* ── Network Node Cards — LCARS ──────────────────── */
.node-card {
    border-radius: 2px 12px 12px 2px !important;
    border-left: 3px solid rgba(255,107,107,0.4) !important;
    position: relative;
}
.node-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: linear-gradient(180deg,
        rgba(255,107,107,0.6) 0%,
        rgba(255,107,107,0.15) 50%,
        rgba(255,107,107,0.6) 100%);
    pointer-events: none; z-index: 1;
}

/* Light mode crew/contractor/node */
[data-theme="light"] .crew-manifest-section,
body.light-mode .crew-manifest-section {
    background: rgba(255, 255, 255, 0.9);
    border-color: rgba(139, 92, 246, 0.15);
    border-left-color: rgba(139, 92, 246, 0.25);
}
[data-theme="light"] .contractor-firm,
body.light-mode .contractor-firm {
    border-left-color: rgba(168, 85, 247, 0.25) !important;
}
```

**Step 3: Restart and verify**

Navigate to Crew → Manifest (agent cards), Contractors (provider cards), Network (node cards). Verify LCARS asymmetric styling.

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): LCARS crew/contractor/node cards — asymmetric panels"
```

---

### Task 7: Leaderboard Rows → LCARS Styled

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:12306` (JS-rendered inline styles)

**Step 1: Update leaderboard row inline styles in JS**

Find at line 12306 the `row.style.cssText` and replace:

```javascript
// BEFORE (line 12306):
row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:6px 10px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:6px;font-size:0.75rem;';

// AFTER:
var accentRgb = rank === 1 ? '251,191,36' : rank === 2 ? '192,192,192' : rank === 3 ? '205,127,50' : '0,255,255';
row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 12px;background:rgba(255,255,255,0.03);border:1px solid rgba(' + accentRgb + ',0.12);border-left:3px solid rgba(' + accentRgb + ',0.4);border-radius:2px 8px 8px 2px;font-size:0.75rem;position:relative;';
```

**Step 2: Restart and verify**

Navigate to Crew → Leaderboard. Verify rows have asymmetric radius, gold/silver/bronze left bars for top 3.

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): LCARS leaderboard rows — asymmetric accent bars"
```

---

### Task 8: Responsive Breakpoint Updates

**Files:**
- Modify: `platform_v2/templates/tools/bridge.html:5834-5851` (responsive rules)

**Step 1: Update responsive overrides for new GlassNav**

Replace the responsive rules at line 5834-5851:

```css
@media (max-width: 768px) {
    .bridge-tabs {
        margin: 0 8px 8px;
        padding: 4px 4px;
    }
    .bridge-tab { padding: 6px 10px; font-size: 0.65rem; }
    .bridge-tab span { display: none; }  /* Icon-only on mobile */
    .crew-subtabs {
        margin: 0 8px 8px;
        padding: 4px 4px;
    }
    .crew-subtab span { display: none; }
    .crew-subtab { padding: 6px 10px; }

    .bridge-overview-cards { grid-template-columns: minmax(0, 1fr); }
    .bridge-hud-strip { flex-wrap: wrap; }
    .bridge-hud-pod { flex: 1 1 45%; min-width: 0; }
    .bridge-status-bar .status-bar-label { display: none; }
}
```

**Step 2: Restart and verify at mobile width**

Resize browser to ~500px. Verify GlassNav tabs go icon-only. Verify briefing cards stack single-column.

**Step 3: Commit**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): LCARS responsive — GlassNav mobile breakpoints"
```

---

### Task 9: Final Visual QA + Screenshot Baseline

**Step 1: Restart platform**

Run: `docker compose restart archie_platform`

**Step 2: Navigate through all tabs and take screenshots**

Using Playwright or manual browser:
- Bridge → Stations (unchanged)
- Bridge → Overview (LCARS briefing cards + HUD pods + status bar)
- Bridge → Dispatch (LCARS cards + station bars)
- Bridge → Crew → Manifest (LCARS agent cards)
- Bridge → Crew → Training (LCARS forms)
- Bridge → Crew → Lounge (LCARS forms + burnout alerts)
- Bridge → Crew → Contractors (LCARS provider cards)
- Bridge → Crew → Leaderboard (LCARS rows)
- Bridge → Network (LCARS node cards + model grid)

**Step 3: Verify checklist**
- [ ] All briefing cards have asymmetric radius + left gradient bar
- [ ] Tab nav is GlassNav frosted glass pill
- [ ] Crew sub-tabs match GlassNav pattern
- [ ] HUD pods have asymmetric radius + left bar
- [ ] Status bar has left cyan endcap
- [ ] Form selects/inputs have LCARS styling
- [ ] Buttons are pill-shaped
- [ ] Leaderboard rows have accent-colored left bars
- [ ] Contractor cards have left gradient bars
- [ ] Node cards have left gradient bars
- [ ] Light mode still works
- [ ] Stations tab is unchanged

**Step 4: Final commit (if any fixes needed)**

```bash
git add platform_v2/templates/tools/bridge.html
git commit -m "feat(bridge): LCARS redesign — final QA fixes"
```
