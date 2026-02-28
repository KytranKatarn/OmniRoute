# Bridge Command Module — LCARS Alignment & Final Review

## Context

Bridge Command is a 14,000-line template with 5,853 lines of inline CSS, 724 custom classes, and 7,659 lines of routes. The nav bar (via `admin_ops_nav.html`) is already gold standard. The isometric 3D room layout is unique to Bridge and should be preserved. The core finding is that Bridge's **shared UI components** (tabs, modals, cards, buttons) don't use the LCARS design system — they're bespoke inline styles.

**No ghost column bugs found** — `archie_emotional_state`, `archie_core_identity`, `archie_personality` all exist and work correctly.

**Cross-links already work** — `viewPersonnelFile()` at line 12851 links to `/tools/consciousness#team`.

---

## Plan

### Step 1: Add Antonio Font + LCARS CSS Variables

**File:** `bridge.html` line 6 (font import) and line 13+ (CSS vars)

- Add `Antonio:wght@400;500;600;700` to the Google Fonts import
- Add LCARS accent CSS vars under `:root` for Bridge's operations theme:
  ```css
  --lcars-accent: #FFAA00;
  --lcars-accent-rgb: 255, 170, 0;
  --lcars-accent-dim: #cc8800;
  ```

### Step 2: LCARS Tab Navigation

**File:** `bridge.html` — CSS lines 4897-4980, HTML lines 5947-5968

Convert `.bridge-tab` from rounded-square underline tabs to LCARS pill buttons:

**CSS changes:**
- `border-radius: 8px` → `border-radius: 2px 12px 12px 2px` (asymmetric LCARS pill)
- Add `border-left: 3px solid rgba(255,170,0,0.3)` (left accent bar)
- Active state: `border-left-color: var(--archie-cyan)` + glow
- Remove `::after` underline indicator (LCARS uses the border-left instead)
- Font: Add `font-family: 'Antonio', sans-serif` for tab labels
- Remove light-mode overrides (lines 4960-4979) — platform is dark-only

### Step 3: LCARS Briefing Cards

**File:** `bridge.html` — CSS lines 5674-5730

The `.briefing-card` pattern is close to LCARS but needs alignment:

**CSS changes:**
- `border-radius: 12px` → `border-radius: 0 12px 12px 0` (asymmetric LCARS)
- Add `border-left: 3px solid var(--card-accent, #00ffff)` (left accent bar)
- Add `::before` gradient bar on the left (LCARS signature)
- Header font: `font-family: 'Antonio', sans-serif` (labels use Antonio)
- Value font stays `Orbitron` (numbers/values)

### Step 4: LCARS Modal Treatment

**File:** `bridge.html` — CSS lines 3344-3430 (provider modal), 3544-3700 (assignment modal), 4832-4893 (node modal)

All 3 modal types get unified LCARS treatment:

**CSS changes (`.assignment-modal`, `.provider-modal`, `.node-modal`):**
- `border-radius: 12px` → `border-radius: 0 12px 12px 0`
- Add `border-left: 3px solid` with accent color
- Header: Add `::before` left gradient bar, use `font-family: 'Antonio', sans-serif`
- Add `.lcars-panel::before` gradient on left edge
- Remove `box-shadow: 0 0 40px rgba(...)` glow → replace with subtle `box-shadow: 0 8px 32px rgba(0,0,0,0.5)`
- Keep `backdrop-filter: blur` on overlay

### Step 5: LCARS Buttons

**File:** `bridge.html` — scattered button CSS (lines 3405-3430, 3686+, etc.)

Convert button patterns to LCARS pill shape:

**CSS changes:**
- `.provider-modal-buttons button`, `.assignment-modal-footer button`, `.btn-submit`, `.btn-save`, `.btn-cancel`, `.btn-delete`:
  - `border-radius: 4-6px` → `border-radius: 2px 12px 12px 2px`
  - Add `border-left: 3px solid <accent-color>`
  - Font: `'Antonio', sans-serif` for button text

### Step 6: HUD Pods LCARS Treatment

**File:** `bridge.html` — CSS lines 5620-5672

The `.bridge-hud-pod` components get LCARS alignment:

**CSS changes:**
- `border-radius: 8px` → `border-radius: 0 12px 12px 0`
- Add `border-left: 3px solid rgba(0, 255, 255, 0.3)`
- Labels: `font-family: 'Antonio', sans-serif` (currently mono)

### Step 7: Clean Up Light Mode CSS (~80 lines)

**File:** `bridge.html` — lines 4960-4979 and scattered `[data-theme="light"]` blocks

The platform is dark-only. Remove all `[data-theme="light"]` and `body.light-mode` CSS blocks to reduce bloat.

### Step 8: Verify & Test

1. Restart Docker: `docker compose restart archie_platform`
2. Navigate to Bridge Command → verify:
   - Tabs show LCARS pill shape with left accent bars
   - Overview cards have left accent bars + asymmetric radius
   - Modals (click agent profile, click "View All" on Vigil) show LCARS frame
   - Buttons use pill shape
   - HUD pods have left accent bars
   - Antonio font renders on tab labels and card headers
3. Check isometric room still works (no layout regression)
4. Check responsive at 500px/768px breakpoints
5. Test CREW tab → agent profile → "Personnel File" link → Consciousness Team tab

---

## Files Modified (Summary)

| File | Changes |
|------|---------|
| `templates/tools/bridge.html` | Add Antonio font, LCARS CSS vars, convert tabs/cards/modals/buttons/HUD to LCARS patterns, remove light-mode CSS |

## NOT Changed

- **Isometric 3D room** — Unique to Bridge, preserved as-is
- **Routes** — No ghost columns found, no dead routes removed (many "unused" routes are actually API endpoints used by frontend JS)
- **Status bar** — Already well-designed, no changes needed
- **Cross-links** — Already working (Personnel File → Consciousness Team tab)
- **JavaScript** — No logic changes needed, only CSS/font alignment
