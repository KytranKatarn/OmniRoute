# Media Hub Theme System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the standalone Media Hub a user-selectable 5-theme system driven by one CSS token layer, with a Settings picker and per-browser persistence, and re-skin the default to a neutral poster-forward look.

**Architecture:** A new `theme-tokens.css` defines a complete semantic token set on `:root` (= Neutral default) plus one override block per theme scoped to `html[data-mh-theme="…"]`. A synchronous no-flash `<head>` script applies the saved theme before first paint. `theme-switcher.js` owns the theme registry + `applyTheme()` + `localStorage`. The existing 135 KB `media-hub.css` is migrated component-by-component from color literals to `var(--mh-*)`; the old `body.light-mode` block becomes the **Light** theme and today's gold defaults become **Plex Classic**.

**Tech Stack:** Vanilla CSS custom properties + a tiny vanilla-JS switcher. Flask/Jinja2 templates (`maven_base.html`, `tools/media_hub.html`). No new dependencies. Image-baked standalone (`COPY .`), deployed via `scripts/deploy_with_sha.sh`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-15-media-hub-theme-system-design.md`. Project #385, task #4743.
- All work in `/mnt/archie_brain/standalone/media_hub/` on branch `feat/media-hub-theme-system`.
- **5 themes**, keys exactly: `neutral` (default), `lcars`, `light`, `plex`, `oled`.
- Attribute is `data-mh-theme` on `<html>`; `localStorage` key is exactly `mh-theme`.
- Token prefix is `--mh-*`. **Keep** existing aliases (`--mh-accent`, `--mh-accent-bright`, `--mh-accent-dim`, `--mh-accent-alpha-10/20/30`, `--mh-glow`) defined in every theme block for back-compat — never delete them mid-migration.
- Semantic colors (`--mh-good/--mh-warn/--mh-crit`) stay independent of `--mh-accent`.
- XSS rule: any external string rendered by JS uses `textContent` / the existing `_mhEsc()` — never `innerHTML` with dynamic data. (The picker renders only static theme labels, so this is not triggered, but hold the line.)
- Never edit `.env`; never deploy the prod container from a feature branch (deploy-provenance rule). Prod deploy = clean main only.
- Verified hex values per theme are in the spec's §3 table — copy them verbatim.

---

## REVISION (2026-07-15, mid-execution) — bridge supersedes Slices B/D

**Discovery (during Task 4):** `media-hub.css` does not use hex literals for chrome — it styles
through **555 `var(--archie-*)` platform-token references** (~30 distinct tokens; `--archie-gold`
alone ×124). The planned per-component 135 KB migration (Slices B/D — old Tasks 4, 5, 6, and Task 8's
sweep) is therefore the wrong, high-risk approach.

**New architecture — a token bridge (Task 5 below).** In `theme-tokens.css`, redefine the `--archie-*`
tokens the app uses to point at the active `--mh-*` theme, co-declared on `:root` so they co-resolve
with the per-theme `--mh-*` overrides on `html[data-mh-theme]` (both live on the `html` element, so a
theme block changing `--mh-accent` changes what `--archie-gold: var(--mh-accent)` resolves to; descendants
inherit the resolved `--archie-*`). This reskins **all 555 refs per theme with ZERO edits to
`media-hub.css`**. Task 4 (direct chrome conversion) was **reverted** — the file stays pristine.

**Revised remaining task list:** ~~Task 4~~ (reverted) · **Task 5 = the bridge** (replaces old Tasks
4/5/6 + Task 8 sweep) · Task 6 = Antonio font (was Task 7) · Task 7 = browser-verify all 5 themes in a
throwaway container (was Task 8) · Task 8 = PR/F.O.R.G.E./merge/prod-deploy (was Task 9). Tasks 1–3
unchanged and complete.

### Task 5: The `--archie-*` → `--mh-*` bridge

**Files:** Modify `standalone/media_hub/static/css/theme-tokens.css` (append the bridge block; do NOT touch media-hub.css).

Append to `theme-tokens.css`:

```css
/* Bridge: point the platform --archie-* tokens the app already uses at the active --mh-* theme.
   Co-declared on :root with the --mh-* defaults so both resolve on <html>; per-theme --mh-* overrides
   on html[data-mh-theme] flow through. Reskins every media-hub surface with zero media-hub.css edits.
   Categorical data-viz accents (cyan/blue/purple) are left at platform defaults for chart legibility. */
:root{
  --archie-bg-primary:var(--mh-bg); --archie-bg-secondary:var(--mh-surface);
  --archie-bg-tertiary:var(--mh-surface-2); --archie-bg-elevated:var(--mh-surface-2);
  --archie-text-primary:var(--mh-text); --archie-text-secondary:var(--mh-text-muted);
  --archie-text-muted:var(--mh-text-muted); --archie-text-tertiary:var(--mh-text-faint);
  --archie-border-default:var(--mh-border-strong); --archie-border-muted:var(--mh-border);
  --archie-border-subtle:var(--mh-border);
  --archie-gold:var(--mh-accent); --archie-orange:var(--mh-accent); --archie-orange-dim:var(--mh-accent-dim);
  --archie-orange-alpha-10:var(--mh-accent-alpha-10); --archie-orange-alpha-20:var(--mh-accent-alpha-20);
  --archie-orange-alpha-30:var(--mh-accent-alpha-30); --archie-glow-orange:var(--mh-glow);
  --archie-green:var(--mh-good); --archie-red:var(--mh-crit); --archie-amber:var(--mh-warn);
  --archie-font-display:var(--mh-font-display); --archie-font-body:var(--mh-font-ui);
}
```

**Coverage check:** `grep -oE "var\(--archie-[a-z0-9-]+" static/css/media-hub.css | sort -u` — every
token that maps to CHROME (bg/surface/text/border/accent/gold/orange/green/red/amber/glow/font) must be
in the bridge. Uncovered = intentional data-viz (`--archie-cyan/blue/purple` + their `-alpha-20`) → leave.
The old `body.light-mode` overrides in media-hub.css become dead (the picker never adds that class) — leave them.

---

### Task 1: Token layer + no-flash bootstrap

**Files:**
- Create: `standalone/media_hub/static/css/theme-tokens.css`
- Modify: `standalone/media_hub/templates/maven_base.html` (head: no-flash script after `<head>` line 3; `<link>` theme-tokens.css before media-hub.css link at line 19)

**Interfaces:**
- Produces: the `--mh-*` token contract every later task styles through; the `data-mh-theme` attribute contract; `:root` (no attribute) == `neutral`.

- [ ] **Step 1: Create the token layer**

Create `static/css/theme-tokens.css` with the complete set. Values are verbatim from spec §3.

```css
/* Media Hub theme tokens — one set per theme. :root = Neutral Poster-Forward (default). */
:root {
  --mh-bg:#0d0f13; --mh-surface:#161a21; --mh-surface-2:#1e232c;
  --mh-text:#e9ecf1; --mh-text-muted:#98a0ad; --mh-text-faint:#6d7480;
  --mh-border:rgba(255,255,255,.09); --mh-border-strong:rgba(255,255,255,.16);
  --mh-accent:#6ea8fe; --mh-accent-ink:#0b1220; --mh-accent-soft:rgba(110,168,254,.14);
  --mh-good:#3ecf8e; --mh-warn:#e6b450; --mh-crit:#f87171; --mh-info:#6ea8fe;
  --mh-chip:rgba(255,255,255,.06);
  --mh-radius:12px; --mh-radius-sm:8px;
  --mh-font-ui:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --mh-font-display:var(--mh-font-ui);
  --mh-display-tt:none; --mh-display-ls:normal; --mh-display-weight:700;
  --mh-shadow:0 8px 30px rgba(0,0,0,.35);
  /* back-compat aliases (do not remove during migration) */
  --mh-accent-bright:#8fc0ff; --mh-accent-dim:#3f6aa8;
  --mh-accent-alpha-10:rgba(110,168,254,.10); --mh-accent-alpha-20:rgba(110,168,254,.20);
  --mh-accent-alpha-30:rgba(110,168,254,.30); --mh-glow:0 0 20px rgba(110,168,254,.35);
}
html[data-mh-theme="lcars"]{
  --mh-bg:#000; --mh-surface:#0c0b08; --mh-surface-2:#17130a;
  --mh-text:#f4e7d3; --mh-text-muted:#c7a061; --mh-text-faint:#8a6d3b;
  --mh-border:#ff9966; --mh-border-strong:#ffb380;
  --mh-accent:#ff9966; --mh-accent-ink:#150a03; --mh-accent-soft:rgba(255,153,102,.16);
  --mh-good:#77cc99; --mh-warn:#ffcc66; --mh-crit:#cc6666; --mh-info:#9999ff;
  --mh-chip:rgba(255,153,102,.13);
  --mh-radius:22px; --mh-radius-sm:16px;
  --mh-font-display:"Antonio","Arial Narrow",system-ui,sans-serif;
  --mh-display-tt:uppercase; --mh-display-ls:.06em; --mh-display-weight:600;
  --mh-accent-bright:#ffb380; --mh-accent-dim:#cc7a4d;
  --mh-accent-alpha-10:rgba(255,153,102,.10); --mh-accent-alpha-20:rgba(255,153,102,.20);
  --mh-accent-alpha-30:rgba(255,153,102,.30); --mh-glow:0 0 20px rgba(255,153,102,.35);
}
html[data-mh-theme="light"]{
  --mh-bg:#f4f6f9; --mh-surface:#fff; --mh-surface-2:#eef1f5;
  --mh-text:#171a1f; --mh-text-muted:#5b6472; --mh-text-faint:#8a93a1;
  --mh-border:rgba(20,24,31,.12); --mh-border-strong:rgba(20,24,31,.22);
  --mh-accent:#2f6bff; --mh-accent-ink:#fff; --mh-accent-soft:rgba(47,107,255,.10);
  --mh-good:#12a15f; --mh-warn:#b7791f; --mh-crit:#d64545; --mh-info:#2f6bff;
  --mh-chip:rgba(20,24,31,.05); --mh-shadow:0 8px 30px rgba(20,24,31,.12);
  --mh-accent-bright:#5a8bff; --mh-accent-dim:#274fbf;
  --mh-accent-alpha-10:rgba(47,107,255,.10); --mh-accent-alpha-20:rgba(47,107,255,.20);
  --mh-accent-alpha-30:rgba(47,107,255,.30); --mh-glow:0 0 20px rgba(47,107,255,.25);
}
html[data-mh-theme="plex"]{
  --mh-bg:#0a0a0f; --mh-surface:#14141c; --mh-surface-2:#1c1c26;
  --mh-text:#ececec; --mh-text-muted:#9a9aa8; --mh-text-faint:#6c6c7a;
  --mh-border:rgba(229,160,13,.18); --mh-border-strong:rgba(229,160,13,.30);
  --mh-accent:#e5a00d; --mh-accent-ink:#160f00; --mh-accent-soft:rgba(229,160,13,.14);
  --mh-good:#46b26a; --mh-warn:#e5a00d; --mh-crit:#e06666; --mh-info:#5aa0e5;
  --mh-chip:rgba(229,160,13,.10);
  --mh-accent-bright:#ffc230; --mh-accent-dim:#b8860b;
  --mh-accent-alpha-10:rgba(229,160,13,.10); --mh-accent-alpha-20:rgba(229,160,13,.20);
  --mh-accent-alpha-30:rgba(229,160,13,.30); --mh-glow:0 0 20px rgba(229,160,13,.40);
}
html[data-mh-theme="oled"]{
  --mh-bg:#000; --mh-surface:#0a0a0a; --mh-surface-2:#141414;
  --mh-text:#fff; --mh-text-muted:#8b8b8b; --mh-text-faint:#5c5c5c;
  --mh-border:rgba(255,255,255,.10); --mh-border-strong:rgba(255,255,255,.20);
  --mh-accent:#22d3ee; --mh-accent-ink:#00181c; --mh-accent-soft:rgba(34,211,238,.12);
  --mh-good:#34d399; --mh-warn:#fbbf24; --mh-crit:#fb7185; --mh-info:#22d3ee;
  --mh-chip:rgba(255,255,255,.05);
  --mh-accent-bright:#67e8f9; --mh-accent-dim:#0e7490;
  --mh-accent-alpha-10:rgba(34,211,238,.10); --mh-accent-alpha-20:rgba(34,211,238,.20);
  --mh-accent-alpha-30:rgba(34,211,238,.30); --mh-glow:0 0 20px rgba(34,211,238,.35);
}
```

- [ ] **Step 2: Add the no-flash script + token link to `maven_base.html`**

Immediately after `<head>` (line 3), insert (before any CSS `<link>`):

```html
<script>try{var t=localStorage.getItem('mh-theme');if(t)document.documentElement.setAttribute('data-mh-theme',t);}catch(e){}</script>
```

Immediately BEFORE the media-hub.css link (line 19: `<link rel="stylesheet" href="{{ url_for('static', filename='css/media-hub.css') }}">`), insert:

```html
    <link rel="stylesheet" href="{{ url_for('static', filename='css/theme-tokens.css') }}">
```

- [ ] **Step 3: Verify token file parses + all 5 keys present**

Run:
```bash
cd /mnt/archie_brain/standalone/media_hub
grep -c 'data-mh-theme="' static/css/theme-tokens.css   # expect 5
grep -oE 'data-mh-theme="[a-z]+"' static/css/theme-tokens.css | sort -u   # neutral absent(:root), 4 keys listed
grep -q 'localStorage.getItem(.mh-theme.)' templates/maven_base.html && echo "no-flash OK"
grep -q "theme-tokens.css" templates/maven_base.html && echo "link OK"
```
Expected: `5` blocks (lcars/light/plex/oled + `:root`=neutral → the 4 attribute blocks print), both OK lines.

- [ ] **Step 4: Commit**

```bash
git add static/css/theme-tokens.css templates/maven_base.html
git commit -m "feat(media-hub): theme token layer + no-flash bootstrap (Slice A, #4743)"
```

---

### Task 2: theme-switcher.js (registry + apply + persist)

**Files:**
- Create: `standalone/media_hub/static/js/theme-switcher.js`
- Modify: `standalone/media_hub/templates/maven_base.html` (add `<script src=…theme-switcher.js>` near the other JS includes, ~line 139)

**Interfaces:**
- Produces: global `window.MHTheme = { THEMES, applyTheme(name), current() }`.
  - `THEMES`: ordered array `[{key,label,swatch:{bg,surface,accent}}]`.
  - `applyTheme(name)`: sets `<html data-mh-theme>`, writes `localStorage['mh-theme']`, dispatches a `mh:theme` CustomEvent, returns the applied key (falls back to `neutral` for unknown).
  - `current()`: returns the active key (attribute or `neutral`).

- [ ] **Step 1: Create the switcher**

```javascript
/* Media Hub theme switcher — single source of truth for the theme registry. */
(function (w, d) {
  var THEMES = [
    { key: 'neutral', label: 'Neutral',      swatch: { bg:'#0d0f13', surface:'#161a21', accent:'#6ea8fe' } },
    { key: 'lcars',   label: 'LCARS',        swatch: { bg:'#000000', surface:'#17130a', accent:'#ff9966' } },
    { key: 'light',   label: 'Light',        swatch: { bg:'#f4f6f9', surface:'#ffffff', accent:'#2f6bff' } },
    { key: 'plex',    label: 'Plex Classic', swatch: { bg:'#0a0a0f', surface:'#14141c', accent:'#e5a00d' } },
    { key: 'oled',    label: 'OLED',         swatch: { bg:'#000000', surface:'#141414', accent:'#22d3ee' } }
  ];
  var KEYS = THEMES.map(function (t) { return t.key; });
  function current() {
    var a = d.documentElement.getAttribute('data-mh-theme');
    return KEYS.indexOf(a) >= 0 ? a : 'neutral';
  }
  function applyTheme(name) {
    var key = KEYS.indexOf(name) >= 0 ? name : 'neutral';
    if (key === 'neutral') d.documentElement.removeAttribute('data-mh-theme');
    else d.documentElement.setAttribute('data-mh-theme', key);
    try { localStorage.setItem('mh-theme', key); } catch (e) {}
    try { w.dispatchEvent(new CustomEvent('mh:theme', { detail: { key: key } })); } catch (e) {}
    return key;
  }
  w.MHTheme = { THEMES: THEMES, applyTheme: applyTheme, current: current };
})(window, document);
```

- [ ] **Step 2: Include it in `maven_base.html`**

After the existing `<script src="…/js/i18n.js">` (~line 138), add:
```html
<script src="{{ url_for('static', filename='js/theme-switcher.js') }}"></script>
```

- [ ] **Step 3: Verify JS parses**

```bash
node --check static/js/theme-switcher.js && echo "SYNTAX OK"
grep -q "theme-switcher.js" templates/maven_base.html && echo "include OK"
```
Expected: `SYNTAX OK`, `include OK`.

- [ ] **Step 4: Commit**

```bash
git add static/js/theme-switcher.js templates/maven_base.html
git commit -m "feat(media-hub): theme-switcher.js registry + applyTheme + persistence (#4743)"
```

---

### Task 3: Settings → Appearance picker

**Files:**
- Modify: `standalone/media_hub/templates/tools/media_hub.html` (insert a new `.settings-section` in the Settings tab, just before the "Admin Tools" section at line 676)
- Modify: `standalone/media_hub/static/js/media-hub.js` (render the picker from `MHTheme.THEMES` in `loadSettings()`, ~line 81)

**Interfaces:**
- Consumes: `window.MHTheme` from Task 2.
- Produces: a `#mh-theme-picker` container whose buttons call `MHTheme.applyTheme` and reflect `aria-pressed`.

- [ ] **Step 1: Add the picker markup** — before line 676 (`<div class="settings-section"> … Admin Tools`), insert:

```html
                <div class="settings-section">
                    <h2><i data-lucide="palette"></i> Appearance</h2>
                    <p class="settings-hint">Pick a theme. Saved to this browser.</p>
                    <div id="mh-theme-picker" class="theme-picker" role="group" aria-label="Theme"></div>
                </div>
```

- [ ] **Step 2: Render + wire the picker** — in `media-hub.js`, add a `renderThemePicker()` and call it from `loadSettings()`:

```javascript
function renderThemePicker() {
  var host = document.getElementById('mh-theme-picker');
  if (!host || !window.MHTheme) return;
  var cur = window.MHTheme.current();
  host.innerHTML = '';
  window.MHTheme.THEMES.forEach(function (t) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'theme-card';
    b.dataset.key = t.key;
    b.setAttribute('aria-pressed', String(t.key === cur));
    var sw = document.createElement('span');
    sw.className = 'theme-card-swatch';
    sw.style.background = t.swatch.bg;
    sw.style.borderColor = t.swatch.accent;
    var dot = document.createElement('span');
    dot.className = 'theme-card-dot';
    dot.style.background = t.swatch.accent;
    sw.appendChild(dot);
    var label = document.createElement('span');
    label.className = 'theme-card-label';
    label.textContent = t.label;              // static label — textContent (XSS rule)
    b.appendChild(sw); b.appendChild(label);
    b.addEventListener('click', function () {
      window.MHTheme.applyTheme(t.key);
      host.querySelectorAll('.theme-card').forEach(function (c) {
        c.setAttribute('aria-pressed', String(c.dataset.key === t.key));
      });
    });
    host.appendChild(b);
  });
}
```
Then inside `loadSettings()` (~line 81), after its existing body, add: `renderThemePicker();`

- [ ] **Step 3: Style the picker** — append to `static/css/theme-tokens.css`:

```css
.theme-picker{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;}
.theme-card{display:flex;flex-direction:column;align-items:center;gap:6px;cursor:pointer;
  background:var(--mh-surface-2);border:1px solid var(--mh-border);border-radius:var(--mh-radius-sm);
  padding:10px;color:var(--mh-text);font:inherit;font-size:.78rem;min-width:78px;}
.theme-card:hover{border-color:var(--mh-border-strong);}
.theme-card[aria-pressed="true"]{border-color:var(--mh-accent);box-shadow:0 0 0 1px var(--mh-accent);}
.theme-card:focus-visible{outline:2px solid var(--mh-accent);outline-offset:2px;}
.theme-card-swatch{width:52px;height:34px;border-radius:6px;border:2px solid;
  display:flex;align-items:flex-end;justify-content:flex-end;padding:4px;}
.theme-card-dot{width:10px;height:10px;border-radius:50%;}
.theme-card-label{color:var(--mh-text-muted);}
.theme-card[aria-pressed="true"] .theme-card-label{color:var(--mh-text);}
```

- [ ] **Step 4: Verify** — `node --check static/js/media-hub.js` → SYNTAX OK; `grep -q 'mh-theme-picker' templates/tools/media_hub.html && echo MARKUP` → MARKUP; `grep -q 'renderThemePicker' static/js/media-hub.js && echo WIRED` → WIRED.

- [ ] **Step 5: Commit**

```bash
git add templates/tools/media_hub.html static/js/media-hub.js static/css/theme-tokens.css
git commit -m "feat(media-hub): Settings Appearance theme picker (Slice C, #4743)"
```

---

### Task 4: Migrate core chrome to tokens (header / nav / stat-card)

**Files:**
- Modify: `standalone/media_hub/static/css/media-hub.css` (rules for `.hub-header`, `.hub-nav`, `.nav-tab`, `.stat-card` and children)

**Transformation rule (apply to every color literal in the listed rules):** replace hardcoded backgrounds/text/borders with the matching token — `background:#0a0a0f`→`var(--mh-bg)`; card/panel bg (`#14141c`/`#0a0a0f` surfaces)→`var(--mh-surface)`; secondary surface→`var(--mh-surface-2)`; primary text (`#ECECEC`/`#fff`)→`var(--mh-text)`; muted text→`var(--mh-text-muted)`; borders→`var(--mh-border)`; the gold accent (`#E5A00D` and its rgba tints) is ALREADY `var(--mh-accent*)` in most places — leave those (aliases resolve per-theme). Add `font-family:var(--mh-font-display);text-transform:var(--mh-display-tt);letter-spacing:var(--mh-display-ls);` to `.nav-tab` and section/logo headings so LCARS gets its treatment.

- [ ] **Step 1: Convert the rules** — locate each rule (`grep -n '\.hub-header\|\.hub-nav\|\.nav-tab\|\.stat-card' static/css/media-hub.css`) and apply the transformation rule above, one selector block at a time.

- [ ] **Step 2: Verify no raw dark literals remain in those blocks**

```bash
# Show the migrated blocks; confirm they read var(--mh-*), not #hex backgrounds/text:
awk '/\.hub-header|\.hub-nav|\.nav-tab|\.stat-card/{p=1} p&&/}/{print;p=0} p' static/css/media-hub.css | grep -nE "#[0-9a-fA-F]{3,6}" || echo "NO RAW LITERALS in core chrome"
```
Expected: `NO RAW LITERALS in core chrome` (or only intentional non-theme values like shadows).

- [ ] **Step 3: Commit** — `git add static/css/media-hub.css && git commit -m "refactor(media-hub): header/nav/stat-card → theme tokens (Slice B, #4743)"`

---

### Task 5: Migrate poster grid + panel + modal to tokens

**Files:**
- Modify: `standalone/media_hub/static/css/media-hub.css` (rules for `.poster-card` + children, `.panel` + children, `.media-modal` + children)

**Transformation rule:** same mapping as Task 4. For `.media-modal`'s local `--mh-accent*` re-declaration block (~line 2121), DELETE the local overrides (they hardcode gold) so the modal inherits the active theme's accent from `:root`/`[data-mh-theme]`. Poster overlay gradients over artwork stay literal (they're image scrims, not theme chrome).

- [ ] **Step 1: Convert `.poster-*`, `.panel*`, `.media-modal*` blocks** per the mapping; remove the local `--mh-accent*` set inside `.media-modal`.

- [ ] **Step 2: Verify**

```bash
grep -n "\-\-mh-accent:#E5A00D" static/css/media-hub.css || echo "no hardcoded modal accent"
awk '/\.poster-card|\.panel|\.media-modal/{p=1} p&&/}/{print;p=0} p' static/css/media-hub.css | grep -nE "background:\s*#[0-9a-fA-F]{3,6}" || echo "NO RAW SURFACE LITERALS in cards/panels"
```
Expected: both "no…" lines.

- [ ] **Step 3: Commit** — `git commit -am "refactor(media-hub): poster/panel/modal → theme tokens (Slice B, #4743)"`

---

### Task 6: Fold light-mode → Light theme; gold defaults → Plex Classic

**Files:**
- Modify: `standalone/media_hub/static/css/media-hub.css` (the `body.light-mode .*` blocks ~line 2754+, and any remaining top-level gold defaults)

- [ ] **Step 1: Convert `body.light-mode` overrides** — for each `body.light-mode .X { … }` rule, move its intent into the `html[data-mh-theme="light"]` token block in `theme-tokens.css` (most collapse to token values already set in Task 1). Then DELETE the now-redundant `body.light-mode` component overrides. If any component needs a light-specific shape (not just color), keep a minimal `html[data-mh-theme="light"] .X{…}` rule in media-hub.css.

- [ ] **Step 2: Confirm Plex Classic == today's gold** — the `plex` token block already carries the old gold values. Verify nothing in media-hub.css still hardcodes a base dark background that would override the token (search `background:#0a0a0f` outside gradients).

```bash
grep -n "body.light-mode" static/css/media-hub.css | wc -l   # trending toward 0 (only shape-specific rules may remain)
```

- [ ] **Step 3: Commit** — `git commit -am "refactor(media-hub): light-mode→Light theme, gold→Plex Classic (Slice B, #4743)"`

---

### Task 7: LCARS display font (Antonio, self-hosted)

**Files:**
- Create: `standalone/media_hub/static/fonts/antonio-600.woff2` (+ `@font-face` in `theme-tokens.css`)

- [ ] **Step 1: Source the Antonio woff2** — the platform already ships Antonio (`.claude/rules/frontend.md`). Copy the existing woff2 from the main platform static assets into the standalone (self-hosted, CSP-safe):

```bash
cd /mnt/archie_brain
F=$(find platform_v2/static -iname "*antonio*.woff2" 2>/dev/null | head -1); echo "found: $F"
# if found: cp "$F" standalone/media_hub/static/fonts/antonio-600.woff2
mkdir -p standalone/media_hub/static/fonts
[ -n "$F" ] && cp "$F" standalone/media_hub/static/fonts/antonio-600.woff2 && echo "vendored"
```
If no Antonio woff2 exists anywhere in-repo, SKIP this task — LCARS falls back to `"Arial Narrow",system-ui` (already the fallback in the token block); log it as follow-up #4743-font and move on. **Do not fetch fonts over the network.**

- [ ] **Step 2: Add `@font-face`** (only if vendored) — prepend to `theme-tokens.css`:

```css
@font-face{font-family:"Antonio";font-style:normal;font-weight:600;font-display:swap;
  src:url("../fonts/antonio-600.woff2") format("woff2");}
```

- [ ] **Step 3: Verify** — `ls -la static/fonts/antonio-600.woff2` (if vendored) and `grep -q '@font-face' static/css/theme-tokens.css`.

- [ ] **Step 4: Commit** — `git add static/fonts static/css/theme-tokens.css && git commit -m "feat(media-hub): self-host Antonio for LCARS display (#4743)"` (skip if fell back).

---

### Task 8: Long-tail sweep + full local browser verification

**Files:**
- Modify: `standalone/media_hub/static/css/media-hub.css`, `static/css/tv-mode.css` (remaining literals)

- [ ] **Step 1: Sweep remaining literals** — `grep -nE "#[0-9a-fA-F]{6}" static/css/media-hub.css | grep -viE "gradient|shadow|rgba\(0,0,0" | head -40` → convert chrome colors (badges, chips, chart axes, discover/series sub-views) to tokens using the Task 4 mapping. Leave chart data colors + image gradients literal.

- [ ] **Step 2: Build a THROWAWAY test container (not prod) and verify all 5 themes**

```bash
cd /mnt/archie_brain
ALLOW_DIRTY_DEPLOY=1 GIT_SHA=$(git rev-parse --short HEAD) \
  docker compose -p mhtest -f standalone/media_hub/docker-compose.yml up -d --build mediahub_app
# (or run against the existing dev/sandbox instance)
```
Then, as the media-hub identity (P.R.O.B.E./Playwright), for each theme: open Settings → Appearance → click each of the 5 cards and confirm header/nav/stats/poster-grid/downloading-panel reskin; reload and confirm the theme persists (no flash); confirm the "Stalled"/error state stays red in all 5; check 1280/768/480 px. Capture one screenshot per theme.

- [ ] **Step 3: Tear down the test container** — `docker compose -p mhtest -f standalone/media_hub/docker-compose.yml down`.

- [ ] **Step 4: Commit** — `git commit -am "refactor(media-hub): long-tail color sweep → tokens (Slice D, #4743)"`

---

### Task 9: PR → F.O.R.G.E. review → merge → prod deploy → live verify

- [ ] **Step 1: Push + open PR** via `/commit-push-pr` (registers with Repair Bay). Title: `feat(media-hub): swappable 5-theme system + poster-forward default (#385/#4743)`. Body links the spec + the mock artifact + the per-theme screenshots.

- [ ] **Step 2: F.O.R.G.E. review** via `/merge-pr <PR#>` — address any findings with fix-and-re-review; do not merge on FLAGGED.

- [ ] **Step 3: Merge** (squash) once APPROVE + owner OK for a user-visible default change.

- [ ] **Step 4: Sync main + prod deploy from clean main**

```bash
cd /mnt/archie_brain && git checkout main && git fetch origin && git merge --ff-only origin/main
scripts/deploy_with_sha.sh standalone/media_hub mediahub_app
scripts/deploy_drift_check.py   # media_hub baked SHA == main HEAD
```

- [ ] **Step 5: Live-verify** all 5 themes + persistence + no-flash on media.kytranempowerment.com (or the running container); confirm existing users land on Light (was light-mode) / Plex == old look. Complete task #4743 with notes + `update_project_understanding(385)`.

---

## Self-Review

**Spec coverage:** token layer (T1) · no-flash + switch (T1/T2) · switcher registry + persistence (T2) · Settings picker (T3) · 5 themes with verbatim hex (T1) · phased 135 KB migration Slices A–D (T4/T5/T6/T8) · light-mode→Light + gold→Plex (T6) · LCARS Antonio (T7) · deploy + drift + live verify (T9) · back-compat aliases (T1, Global Constraints). All spec §§ mapped.

**Placeholders:** none — every code step carries full content; the only conditional is T7 (font vendoring) with an explicit fallback + follow-up.

**Type consistency:** `MHTheme.applyTheme`/`current`/`THEMES` names identical across T2 (def) and T3 (use); attribute `data-mh-theme` and key `mh-theme` consistent across T1/T2; token names identical between `theme-tokens.css` (T1) and the migration mapping (T4/T5).

## Notes on adaptation
CSS has no unit-test cycle; each task's "test" is a grep gate (literal-removed / token-present / syntax-OK) plus, at T8, a real multi-theme browser pass in a throwaway container. Per-slice commits keep the 135 KB migration reviewable; back-compat aliases mean the app renders correctly at every intermediate commit.
