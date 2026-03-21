# Directory Org Chart Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the vertical tree org chart with a department cards grid + hybrid employee cards, matching the dark corporate LCARS style of the /competitors page.

**Architecture:** Rewrite the rendering functions in directory.js (renderOrgChart → renderCardsGrid, renderAccordion → integrated into card expansion). Add CORS headers for public API. Create static public page for www site. Keep existing profile/chat panels — just change how cards trigger them.

**Tech Stack:** Vanilla JS (no framework), CSS Grid/Flexbox, Flask CORS headers, GitHub Pages static HTML

**Spec:** `docs/superpowers/specs/2026-03-21-directory-org-chart-redesign-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `platform_v2/static/js/directory.js` | Modify | Replace renderOrgChart + renderAccordion with cards grid renderer |
| `platform_v2/static/css/directory.css` | Modify | Add cards grid, leadership banner, hybrid card, department expansion styles |
| `platform_v2/tools/directory/templates/directory_content.html` | Modify | Update org chart container markup for new layout |
| `platform_v2/tools/directory/routes.py` | Modify | Add CORS headers to public API endpoints |

---

## Task 1: Update CSS — Leadership Banner + Department Cards Grid

**Files:**
- Modify: `platform_v2/static/css/directory.css`

- [ ] **Step 1: Read current org chart CSS**

Read lines containing `.dir-org` in `directory.css` to understand existing styles.

- [ ] **Step 2: Replace org chart CSS with cards grid styles**

Replace the existing `.dir-org-chart`, `.dir-org-level`, `.dir-org-node` CSS block with new styles. Keep all non-org styles intact. Add these new classes:

```css
/* === LEADERSHIP BANNER === */
.dir-leadership {
    display: flex;
    justify-content: center;
    gap: 24px;
    padding: 32px 16px;
    flex-wrap: wrap;
}

.dir-leader-card {
    background: #111827;
    border: 2px solid #1e293b;
    border-radius: 12px;
    padding: 16px 24px;
    text-align: center;
    min-width: 140px;
    transition: border-color 0.3s, transform 0.2s;
    cursor: pointer;
}
.dir-leader-card:hover {
    transform: translateY(-2px);
}
.dir-leader-card--ceo { border-color: #f59e0b; }
.dir-leader-card--ai { border-color: #00e5ff; }

.dir-leader-portrait {
    width: 64px;
    height: 64px;
    border-radius: 50%;
    margin: 0 auto 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 18px;
    background-size: cover;
    background-position: center;
}
.dir-leader-name {
    font-weight: 700;
    font-size: 14px;
    color: #e2e8f0;
}
.dir-leader-title {
    font-size: 11px;
    color: #94a3b8;
    margin-top: 2px;
}

/* Connector line from leadership to departments */
.dir-leadership-connector {
    width: 2px;
    height: 24px;
    background: #1e293b;
    margin: 0 auto;
}

/* === DEPARTMENT CARDS GRID === */
.dir-dept-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    padding: 0 16px 24px;
}
@media (max-width: 1024px) { .dir-dept-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 768px) { .dir-dept-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 480px) { .dir-dept-grid { grid-template-columns: 1fr; } }

.dir-dept-card {
    background: #111827;
    border: 1px solid #1e293b;
    border-left: 3px solid var(--dept-color, #64748b);
    border-radius: 8px;
    padding: 14px;
    cursor: pointer;
    transition: background 0.2s, border-color 0.2s;
}
.dir-dept-card:hover {
    background: #1e293b;
}
.dir-dept-card.expanded {
    border-color: var(--dept-color, #64748b);
    background: #0f172a;
}
.dir-dept-card-name {
    font-weight: 600;
    font-size: 13px;
    color: var(--dept-color, #e2e8f0);
}
.dir-dept-card-count {
    font-size: 11px;
    color: #64748b;
    margin-top: 2px;
}
.dir-dept-card-avatars {
    display: flex;
    gap: 4px;
    margin-top: 8px;
    align-items: center;
}
.dir-dept-card-avatar {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 8px;
    font-weight: 600;
    flex-shrink: 0;
    background-size: cover;
    background-position: center;
}
.dir-dept-card-overflow {
    font-size: 10px;
    color: #64748b;
}

/* === EXPANDED DEPARTMENT PANEL === */
.dir-dept-expanded {
    grid-column: 1 / -1;
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 8px;
    padding: 20px;
    margin-top: -4px;
    animation: dir-expand 0.2s ease-out;
}
@keyframes dir-expand {
    from { opacity: 0; max-height: 0; }
    to { opacity: 1; max-height: 2000px; }
}

/* Department head — featured card */
.dir-head-card {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 14px;
    background: #1e293b;
    border-radius: 8px;
    border-left: 3px solid var(--dept-color, #8b5cf6);
    margin-bottom: 12px;
}
.dir-head-portrait {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    border: 2px solid var(--dept-color, #8b5cf6);
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 14px;
    flex-shrink: 0;
    background-size: cover;
    background-position: center;
}
.dir-head-info { flex: 1; }
.dir-head-name {
    font-weight: 700;
    font-size: 14px;
    color: #e2e8f0;
}
.dir-head-badge {
    font-size: 9px;
    font-weight: 600;
    padding: 1px 6px;
    border-radius: 3px;
    margin-left: 6px;
}
.dir-head-title {
    font-size: 12px;
    color: #94a3b8;
    margin-top: 2px;
}
.dir-head-skills {
    display: flex;
    gap: 4px;
    margin-top: 6px;
    flex-wrap: wrap;
}
.dir-skill-tag {
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 4px;
}

/* Team members — compact grid */
.dir-team-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
}
@media (max-width: 480px) { .dir-team-grid { grid-template-columns: 1fr; } }

.dir-team-member {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    background: #1e293b;
    border-radius: 6px;
    cursor: pointer;
    transition: background 0.15s;
}
.dir-team-member:hover {
    background: #334155;
}
.dir-team-portrait {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 600;
    flex-shrink: 0;
    background-size: cover;
    background-position: center;
}
.dir-team-name {
    font-weight: 600;
    font-size: 12px;
    color: #e2e8f0;
}
.dir-team-title {
    font-size: 10px;
    color: #94a3b8;
}
```

- [ ] **Step 3: Remove old org chart CSS**

Delete these class blocks from directory.css (they're being replaced):
- `.dir-org-chart`, `.dir-org-loading`, `.dir-org-level`, `.dir-org-level-*`
- `.dir-org-node`, `.dir-org-node-*`, `.dir-org-connector-*`
- `.dir-org-badge`, `.dir-org-badge-*`
- `.dir-org-dept-*`
- `.dir-accordion-*` (replaced by integrated expansion)

Keep: `.dir-hero*`, `.dir-filters*`, `.dir-profile*`, `.dir-chat*`, `.dir-search*`, `.dir-stat*`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/css/directory.css
git commit -m "feat(directory): CSS for cards grid + hybrid employee cards"
```

---

## Task 2: Update HTML Template

**Files:**
- Modify: `platform_v2/tools/directory/templates/directory_content.html`

- [ ] **Step 1: Read the current template**

Read `directory_content.html` (149 lines) to understand the structure.

- [ ] **Step 2: Replace the org chart and accordion sections**

Replace the `dir-org-section` and `dir-accordion-section` with:

```html
    <!-- Leadership Banner -->
    <section class="dir-leadership" id="dirLeadership">
        <!-- JS renders: Kytran, ARCHIE, Vigil cards -->
    </section>

    <div class="dir-leadership-connector"></div>

    <!-- Department Cards Grid -->
    <section class="dir-dept-grid" id="dirDeptGrid">
        <!-- JS renders: 16 department cards + expansion panels -->
    </section>
```

Remove the old:
```html
    <section class="dir-org-section">
        <h2>Organization</h2>
        <div class="dir-org-chart" id="orgChart">
            <div class="dir-org-loading">Loading org chart...</div>
        </div>
    </section>

    <section class="dir-accordion-section" id="dirAccordion">
        <div class="dir-org-loading">Loading team directory...</div>
    </section>
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/directory/templates/directory_content.html
git commit -m "feat(directory): update template for cards grid layout"
```

---

## Task 3: Rewrite JavaScript Renderer

**Files:**
- Modify: `platform_v2/static/js/directory.js`

- [ ] **Step 1: Read current renderOrgChart and renderAccordion functions**

Read lines 140-470 of `directory.js` to understand the current rendering logic and what data it receives.

- [ ] **Step 2: Replace renderOrgChart with renderCardsGrid**

Replace the `renderOrgChart(nodes)` function (lines ~140-255) and `renderAccordion(nodes)` function (lines ~396-480) with a single new renderer. Also replace helper functions that only served the old tree: `createOrgNode`, `createMemberBadge`, `createConnector`, `createHorizontalConnector`, `createDeptDropLines`, `createAccordionItem`.

New functions to write:

```javascript
function renderCardsGrid(nodes) {
    // 1. Find leadership: ARCHIE, Vigil, + Kytran placeholder
    // 2. Group remaining nodes by department
    // 3. Render leadership banner into #dirLeadership
    // 4. Render department cards into #dirDeptGrid
    // 5. Wire click handlers for expansion
}

function renderLeadershipBanner(leaders, container) {
    // Render Kytran (CEO, gold), ARCHIE (COO, cyan), Vigil (Ethics, cyan)
    // Each is a .dir-leader-card with portrait + name + title
    // Click opens profile slide-out
}

function renderDeptCard(deptName, members, color, container) {
    // Collapsed card: dept name, member count, 3 avatar thumbnails + overflow
    // Click triggers expandDepartment()
}

function expandDepartment(deptName, members, color, gridContainer) {
    // Close any currently expanded department
    // Insert .dir-dept-expanded panel after the clicked card
    // Render department head (featured card) + team members (compact grid)
    // Head = member with is_head=true or highest title
    // Team = remaining members in 2-column grid
}

function createPortrait(person, size, color) {
    // Reusable: returns div with avatar_url background or initials fallback
    // size: 'sm' (24px), 'md' (32px), 'lg' (48px), 'xl' (64px)
}

function getInitials(name) {
    // Already exists — keep as-is
}
```

- [ ] **Step 3: Update loadOrgChart to call new renderer**

Change `loadOrgChart()` to call `renderCardsGrid(data.nodes)` instead of `renderOrgChart(data.nodes)` and `renderAccordion(data.nodes)`.

- [ ] **Step 4: Update applyFilters for new layout**

Modify `applyFilters()` to work with the cards grid — filter department cards by hiding/showing them, and filter expanded members within visible departments.

- [ ] **Step 5: Verify via Playwright**

Navigate to `http://192.168.1.200:3000/tools/directory`, wait 4 seconds, take screenshot. Verify:
- Leadership banner shows Kytran, ARCHIE, Vigil
- 16 department cards visible in grid
- Click a department card — team expands with head + members
- Search filters cards

- [ ] **Step 6: Commit**

```bash
git add platform_v2/static/js/directory.js
git commit -m "feat(directory): cards grid renderer with hybrid employee cards"
```

---

## Task 4: Add CORS Headers to Directory API

**Files:**
- Modify: `platform_v2/tools/directory/routes.py`

- [ ] **Step 1: Read current API endpoints**

Read `routes.py` lines 54-132 (api_directory) and 203-252 (api_directory_org_chart).

- [ ] **Step 2: Add CORS headers to public API responses**

Add `after_request` handler to the blueprint that adds CORS headers for the www domain:

```python
@bp.after_request
def add_cors_headers(response):
    """Allow cross-origin requests from the public www site."""
    origin = request.headers.get("Origin", "")
    allowed_origins = [
        "https://www.kytranempowerment.com",
        "https://kytranempowerment.com",
        "http://localhost",  # dev
    ]
    if origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response
```

Add this after the blueprint definition (around line 14).

- [ ] **Step 3: Verify CORS headers**

```bash
docker exec archie_platform python3 -c "
import requests
r = requests.get('http://localhost:5000/api/directory',
    headers={'Origin': 'https://www.kytranempowerment.com'})
print('CORS:', r.headers.get('Access-Control-Allow-Origin', 'NOT SET'))
print('Status:', r.status_code)
"
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/directory/routes.py
git commit -m "feat(directory): add CORS headers for www cross-origin API access"
```

---

## Task 5: Restart + Full Verification

- [ ] **Step 1: Restart platform**

```bash
docker compose -f /mnt/archie_brain/docker-compose.yml restart archie_platform
```

- [ ] **Step 2: Verify internal directory via Playwright**

Navigate to `http://192.168.1.200:3000/tools/directory`. Wait 4 seconds. Verify:
- Hero stats: 101 Members, 16 Departments
- Leadership banner: Kytran (gold), ARCHIE (cyan), Vigil (cyan)
- 16 department cards in responsive grid
- Click Analytics department — expands with head card + team grid
- Click a team member — profile slide-out opens
- Search "engineer" — filters to matching departments/members
- No console errors

- [ ] **Step 3: Push and complete Dev HQ tracking**

```bash
git push origin main
```

Complete Dev HQ task with verification evidence (screenshots, API responses).

- [ ] **Step 4: Log Dev HQ completion**

```
mcp complete_task #1155 with verification notes
mcp complete_task #1162 with verification notes
```
