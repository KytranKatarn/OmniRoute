# Agent Directory & AI Directors Website Rebuild

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the AI Directors page, Directory page, and portrait system so agent data is accurate, portraits exist for all 16 directors, and both pages pull from a single source of truth.

**Architecture:** Export fresh agent data from the platform DB into `directory-fallback.json`. Add director-specific fields (description, floor, acronym_expansion) to a new `directors.json`. Rebuild `ai-directors.html` to read from `directors.json` dynamically instead of hardcoded HTML. Generate SDXL portraits for any director missing one. Copy portrait assets to website `assets/portraits/`.

**Tech Stack:** Python (DB export script), JavaScript (dynamic page rendering), ComfyUI/SDXL (portrait generation), Hostinger API (deployment)

**Note:** The JS rendering uses trusted data from our own JSON files (not user input). DOM construction uses safe patterns.

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `website/.../data/directory-fallback.json` | Regenerate | Fresh export of all 128 agents from DB |
| `website/.../data/directors.json` | Create | 16 directors with descriptions, floors, acronym expansions |
| `website/.../ai-directors.html` | Rewrite main section | Dynamic rendering from directors.json |
| `website/.../js/ai-directors.js` | Create | Fetch directors.json, render cards with portraits |
| `website/.../assets/portraits/` | Add missing | SDXL portraits for directors without images |
| `website/.../_export_agents.py` | Create | Script to export agent data from platform DB |
| `website/.../css/pages/ai-directors.css` | Modify | Add portrait image styles to director cards |
| `website/.../js/directory.js` | Modify | Fix avatar paths, use local JSON as primary |

---

### Task 1: Export Fresh Agent Data from Platform DB

**Files:**
- Create: `website/kytranempowerment.com/_export_agents.py`
- Regenerate: `website/kytranempowerment.com/data/directory-fallback.json`
- Create: `website/kytranempowerment.com/data/directors.json`

- [ ] **Step 1:** Write `_export_agents.py` that connects to 192.168.1.200 DB, queries agents table, exports `directory-fallback.json` (all 128 agents) and `directors.json` (16 directors with floor, color, description, acronym_expansion fields). Use the FLOOR_MAP: Executive Office=BRIDGE, Ops/Logistics/Finance=OPERATIONS, Tech/Security/R&D=ENGINEERING, Design/Marketing/Docs=CREATIVE, Support/HR/Medical/Legal/Diplomatic/Analytics=SERVICES.

- [ ] **Step 2:** Run the export: `python3 _export_agents.py`
  Expected: "Exported 128 agents" + "Exported 16 directors"

- [ ] **Step 3:** Verify output: `python3 -c "import json; d=json.load(open('data/directors.json')); print(len(d), 'directors'); [print(f'  {x[\"acronym\"]} - {x[\"floor\"]}') for x in d]"`

- [ ] **Step 4:** Commit: `git add data/ _export_agents.py && git commit -m "chore: export fresh agent data"`

---

### Task 2: Audit & Copy Portrait Assets

**Files:**
- Populate: `website/kytranempowerment.com/assets/portraits/`

- [ ] **Step 1:** Check which director portraits exist in `static/media/portraits/` by cross-referencing `data/directors.json` names

- [ ] **Step 2:** `mkdir -p assets/portraits && cp static/media/portraits/*.png assets/portraits/`

- [ ] **Step 3:** List missing director portraits (directors with no matching PNG)

- [ ] **Step 4:** For each missing director, generate a 512x512 SDXL portrait via ComfyUI (192.168.1.200:8188). Style: sci-fi headshot, dark background, department accent color glow. Save as `assets/portraits/{name_lowercase}.png`

- [ ] **Step 5:** Verify all 16 exist: check each director name against `assets/portraits/`

- [ ] **Step 6:** Commit: `git add assets/portraits/ && git commit -m "feat: add director portraits"`

---

### Task 3: Create Dynamic AI Directors Page

**Files:**
- Create: `website/kytranempowerment.com/js/ai-directors.js`
- Modify: `website/kytranempowerment.com/ai-directors.html` (main content section)
- Modify: `website/kytranempowerment.com/css/pages/ai-directors.css`

- [ ] **Step 1:** Write `js/ai-directors.js` that fetches `/data/directors.json`, groups directors by floor, and renders cards with: avatar (80px circle, fallback to initial letter), acronym (colored by floor), acronym_expansion, department, description, shift_state badge. Use safe DOM construction (createElement/textContent, not innerHTML with user data — data is from our own trusted JSON).

- [ ] **Step 2:** Add portrait CSS to `css/pages/ai-directors.css`: `.dir-card__avatar` (80px circle, centered), `.dir-card__avatar-fallback` (initial letter with floor color), `.dir-card__status` badges (color-coded by shift_state: active=green, barracked=purple, deployed=cyan)

- [ ] **Step 3:** Replace the hardcoded floor sections in `ai-directors.html` main content with: hero, C.R.E.E.D. governance panel, `<div id="directorsContainer">Loading...</div>`, "How They Work Together" panel, CTA section. Add `<script defer src="js/ai-directors.js?v=..."></script>` before closing body.

- [ ] **Step 4:** Test in browser — confirm 16 cards render across 5 floors with portraits

- [ ] **Step 5:** Commit: `git add js/ai-directors.js css/pages/ai-directors.css ai-directors.html && git commit -m "feat: dynamic AI Directors page with portraits"`

---

### Task 4: Update Directory Page Avatar Paths

**Files:**
- Modify: `website/kytranempowerment.com/js/directory.js`

- [ ] **Step 1:** In `directory.js`, change avatar base path from `/static/media/portraits/` to `/assets/portraits/`. Change primary API URL to `/data/directory-fallback.json` (local fallback as primary since `api.kytranempowerment.com` doesn't exist). Disable live polling until API is deployed.

- [ ] **Step 2:** Verify directory.html loads agents from local JSON with correct avatar paths

- [ ] **Step 3:** Commit: `git add js/directory.js && git commit -m "fix: directory uses local JSON + correct avatar paths"`

---

### Task 5: Deploy & Verify

- [ ] **Step 1:** Run nav sync: `python3 _replace_nav.py`
- [ ] **Step 2:** Bump cache-bust across all HTML files
- [ ] **Step 3:** Build tarball (exclude dev files)
- [ ] **Step 4:** Deploy to Hostinger via API
- [ ] **Step 5:** Playwright screenshot verification at 1280px and 344px for both ai-directors.html and directory.html
- [ ] **Step 6:** Create feature branch, commit, push, PR
