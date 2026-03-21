# Directory Org Chart Redesign

**Date:** 2026-03-21
**Status:** Approved
**Priority:** 9
**Type:** Feature / UI Redesign

---

## Problem Statement

The current directory org chart uses a vertical flow tree that takes too long to load visually, doesn't match professional org chart conventions (Lucidchart-style), and isn't suitable for a public-facing "Meet Our Team" page. With 101 employees across 16 departments, the page needs a scannable layout that works for both internal users and public visitors.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Layout | Department Cards Grid | Responsive, mobile-friendly, scannable at a glance |
| Employee Cards | Hybrid (head featured + team compact) | Shows hierarchy within departments without overwhelming |
| Style | Dark Corporate + LCARS Stats | Matches /competitors page brand, professional but distinctive |
| Public Access | API-powered static page on www | Platform is source of truth, www is presentation layer |

---

## Architecture

### Two Versions, One Data Source

```
Platform DB (agents table)
    ↓
/api/directory + /api/directory/org-chart (JSON API, no auth, CORS enabled)
    ↓                          ↓
Internal Directory             Public Directory
(archie.kytranempowerment.com) (www.kytranempowerment.com)
Full features: chat,           Static page: view only,
profiles, Bridge dispatch      fetches from API
```

### Internal Directory (`/tools/directory`)
- **Route:** `archie.kytranempowerment.com/tools/directory` (login required)
- **Renderer:** Rewritten `directory.js` — cards grid layout with hybrid employee cards
- **Features:** Click profile → slide-out panel. Click chat → Bridge dispatch. Search/filter by department/status.
- **Data:** Fetches from `/api/directory/org-chart` (same as current)

### Public Directory (`www.kytranempowerment.com/directory`)
- **Hosting:** GitHub Pages (static HTML + JS)
- **Data:** Fetches from `archie.kytranempowerment.com/api/directory` via CORS
- **Features:** View-only — department grid, team cards, search. No chat, no profile slide-out, no login.
- **Style:** Same dark corporate LCARS as internal version

### API Changes
- Add CORS headers (`Access-Control-Allow-Origin: https://www.kytranempowerment.com`) to:
  - `GET /api/directory` — employee list with departments
  - `GET /api/directory/org-chart` — hierarchy with skills
- No auth changes — these endpoints are already public
- Performance scores already removed from response (commit d77e34d)

---

## UI Specification

### Page Structure

```
┌──────────────────────────────────────┐
│ KYTRAN EMPOWERMENT                    │
│ Meet Our Team                         │
│ 101 Members  ·  16 Departments  ·  24/7│
├──────────────────────────────────────┤
│ [Search...] [Department ▼] [Status ▼] │
├──────────────────────────────────────┤
│ LEADERSHIP BANNER                     │
│ ┌────┐  ┌────────┐  ┌──────┐         │
│ │ KY │  │ ARCHIE │  │Vigil │         │
│ │CEO │  │  COO   │  │Ethics│         │
│ └────┘  └────────┘  └──────┘         │
├──────────────────────────────────────┤
│ DEPARTMENTS (4-column grid)           │
│ ┌──────────┐ ┌──────────┐            │
│ │Analytics │ │Creative  │            │
│ │8 members │ │7 members │            │
│ │○○○ +5    │ │○○○ +4    │            │
│ └──────────┘ └──────────┘            │
│ ┌──────────┐ ┌──────────┐            │
│ │Engineer  │ │Research  │            │
│ │8 members │ │5 members │            │
│ └──────────┘ └──────────┘            │
│ ... (16 total, 4 per row)             │
├──────────────────────────────────────┤
│ EXPANDED DEPARTMENT (on click)        │
│ ┌─ HEAD ─────────────────────────┐   │
│ │ [Photo] Priya Krishnan  HEAD   │   │
│ │         Senior Data Scientist  │   │
│ │         ● Data  ● ML  ● SQL   │   │
│ └────────────────────────────────┘   │
│ ┌──────────────┐ ┌──────────────┐   │
│ │[av] Amara O. │ │[av] Jin Park │   │
│ │Data Analyst  │ │Vision Spec.  │   │
│ ├──────────────┤ ├──────────────┤   │
│ │[av] Diego C. │ │[av] Elena P. │   │
│ │Fund. Analyst │ │Pred. Analyst │   │
│ └──────────────┘ └──────────────┘   │
└──────────────────────────────────────┘
```

### Visual Style

- **Background:** `#0a0e1a` (near-black with blue tint)
- **Card background:** `#111827` with `#1e293b` border
- **Header gradient:** `linear-gradient(135deg, #0f172a, #1a1040)`
- **Hero stats:** Orbitron font, teal (#00e5ff) numbers
- **Department colors:** Match station colors — purple, pink, yellow, green, red, cyan, orange, indigo
- **Department head card:** Left border 3px in department color, larger portrait
- **Team member cards:** Compact rows, 2-column grid on desktop, 1-column on mobile
- **Typography:** Orbitron for headings/stats, system-ui for body text
- **Portraits:** Show agent `avatar_url` where available, initials fallback with department color

### Leadership Banner

- **Kytran:** Gold border (#f59e0b), initials "KY", "CEO & Founder"
- **A.R.C.H.I.E.:** Teal border (#00e5ff), holographic portrait, "COO & AI Director"
- **Vigil:** Teal border, portrait, "Chief Ethics & Governance Officer"
- Horizontal layout, centered, connected by subtle lines

### Department Cards (Collapsed)

- Department name in department color
- Member count
- 3 avatar thumbnails + "+N" overflow
- Click to expand/collapse (accordion style, one department open at a time)
- Responsive: 4 columns desktop, 2 columns tablet, 1 column mobile

### Employee Cards (Expanded Department)

**Department Head (featured):**
- Larger portrait (48px)
- Full name + "HEAD" badge in department color
- Title
- Top 3 skill tags
- Left border in department color

**Team Members (compact grid):**
- Small portrait (28px)
- Name + title
- 2-column grid on desktop, 1-column on mobile
- Click to open profile slide-out (internal only)

### Search & Filter

- Search: filters by name, title, department, expertise (client-side filtering)
- Department dropdown: scrolls to and expands that department
- Status dropdown: Online / Off Duty (internal only, hidden on public version)

---

## Responsive Breakpoints

| Width | Columns | Behavior |
|-------|---------|----------|
| 1024px+ | 4 dept cards, 2 team members | Full layout |
| 768px | 3 dept cards, 2 team members | Tablet |
| 480px | 2 dept cards, 1 team member | Phone |
| 360px | 1 dept card, 1 team member | Narrow phone |

---

## Files to Modify/Create

| File | Action | Purpose |
|------|--------|---------|
| `static/js/directory.js` | Rewrite | Replace renderOrgChart with cards grid + hybrid expansion |
| `static/css/directory.css` | Modify | Add cards grid, hybrid card, leadership banner styles |
| `tools/directory/routes.py` | Modify | Add CORS headers to public API endpoints |
| `www-site/directory/index.html` | Create | Static public page for GitHub Pages |
| `www-site/directory/directory.js` | Create | Lightweight public renderer (fetch + render, no chat) |

---

## What NOT to Change

- API response format — already correct (`members`, `by_department`, `nodes`)
- Profile slide-out panel — keep existing, just triggered from card click instead of tree node
- Chat panel — keep existing (internal only)
- Agent data in DB — no schema changes needed
- Performance scores — already removed (commit d77e34d)

---

## Success Criteria

1. Department cards grid renders 16 departments with correct colors and member counts
2. Clicking a department expands to show head + team members in hybrid layout
3. Search filters cards client-side in real-time
4. Profile slide-out opens when clicking any team member (internal)
5. Public version loads on www.kytranempowerment.com/directory via API fetch
6. Responsive: works on 360px phone through 1440px desktop
7. Page loads in under 3 seconds (API fetch + render)
8. Matches /competitors page visual style (dark corporate LCARS)
