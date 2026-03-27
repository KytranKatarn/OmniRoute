# Civic Intelligence Dashboard — Phase 2 Design Spec

**Date:** 2026-03-27
**Site:** civic.kytranempowerment.com
**Agent:** W.A.T.C.H. (Watchdog for Accountability, Transparency, Civic Health)
**Status:** Approved

---

## Overview

Single-page civic intelligence dashboard at civic.kytranempowerment.com. Tab-based navigation with dashboard landing page showing all data at a glance. Calls W.A.T.C.H. API for live Canadian civic data (360+ events across federal, provincial, municipal levels). Deployed as static site on Hostinger.

## Layout

- **Top tab bar** with W.A.T.C.H. branding + 5 tabs (Dashboard, Contracts, Parliament, Spending, Events)
- **Dashboard (landing)** = single-page grid: hero stats row, full-width Canada map embed (iframe of thenews filtered to Canada), 4 widget panels with latest 5 items each + "View All" links
- **Sub-pages** = dedicated filterable/searchable tables rendered in the same HTML via tab switching (no page reload)

## Visual Identity

| Element | Value |
|---------|-------|
| Background | `#0a0e17` (dark navy) |
| Surface | `#1a1f2e` (panel backgrounds) |
| Primary accent | `#ffd740` (amber/gold — W.A.T.C.H. authority) |
| Secondary accent | `#00bfa5` (teal — civic data) |
| Text primary | `#e0e0e0` |
| Text secondary | `#8892a4` |
| Contracts color | `#00bfa5` (teal) |
| Parliament color | `#ffd740` (gold) |
| Spending color | `#69f0ae` (green) |
| Events color | `#ff6d00` (orange) |
| Fonts | Antonio (nav), Orbitron (titles/stats), IBM Plex Mono (data/tables) |
| LCARS elements | Elbow corners on panels, rounded segment bars in header, glow on live data |

## Pages

### 1. Dashboard (Landing Tab)

- **Hero stats row:** 4 cards — Contracts count, Active Bills, Total Spending, Recent Votes
- **Map section:** Embedded iframe of thenews.kytranempowerment.com with civic layers active, zoomed to Canada
- **Widget grid (2x2):**
  - Contracts: latest 5 contracts (title, department, amount, date)
  - Parliament: latest 3 bills + 2 votes (title, status/result)
  - Spending: top 5 departments by amount
  - Events: latest 5 events chronologically (type icon, title, date)
- Each widget has "View All →" link that switches to the corresponding tab

### 2. Contracts Tab

- **Filters bar:** Level dropdown (All/Federal/Provincial/Municipal), Jurisdiction text search, Department text search, Amount range (min/max), Timespan (30d/90d/1y)
- **Table columns:** Title, Department, Jurisdiction, Level, Amount, Date, Source
- **Sort:** Click column headers to sort
- **Export:** CSV download button
- **API:** `GET /api/contracts?level=...&jurisdiction=...&department=...&min_amount=...&timespan=...&limit=50`

### 3. Parliament Tab

- **Sub-sections:** Bills | Votes (toggle)
- **Bills view:** Title, Bill Number, Sponsor, Status (badge: introduced/committee/passed/defeated), Date
- **Votes view:** Description, Bill Number, Result (passed/defeated badge), Yeas/Nays (bar chart), Date
- **Search:** Keyword search across title/description
- **API:** `GET /api/parliament/bills?keyword=...&status=...` and `GET /api/parliament/votes?recent=true`

### 4. Spending Tab

- **Filters:** Level, Jurisdiction, Department, Fiscal Year, Category (operating/capital/grants/transfer)
- **Table columns:** Department, Jurisdiction, Level, Category, Amount, Fiscal Year
- **Sort:** By amount (default desc), date
- **API:** `GET /api/spending?level=...&jurisdiction=...&department=...&category=...`

### 5. Events Tab

- **Filters:** Type checkboxes (contract/bill/vote/spending), Level dropdown, Jurisdiction search, Timespan
- **Feed view:** Chronological list with type icon + color, title, jurisdiction badge, date, source link
- **API:** `GET /api/events?type=...&level=...&region=...&timespan=...&limit=100`

## File Structure

```
civic-dashboard/
  index.html          — Single HTML file with tab structure
  css/base.css        — Variables, reset, dark theme, fonts, responsive
  css/dashboard.css   — Hero stats, widget grid, map embed
  css/tables.css      — Table styling, filters bar, badges, sort indicators
  css/lcars.css       — LCARS elbow corners, segment bars, glow effects
  js/app.js           — Tab switching, init, URL hash routing
  js/api.js           — Fetch wrapper for W.A.T.C.H. API with error handling
  js/dashboard.js     — Hero stats fetch, widget panels, map embed init
  js/contracts.js     — Contract table, filters, search, sort, CSV export
  js/parliament.js    — Bills/votes toggle, tables, search, status badges
  js/spending.js      — Spending table, filters, department breakdown
  js/events.js        — Event feed, type filters, chronological list
  favicon.svg         — W.A.T.C.H. shield icon
```

## Technical Details

- **No build tools** — vanilla JS with IIFE modules, matches Kytran News pattern
- **Tab switching** via `data-tab` attributes + hash routing (`#contracts`, `#parliament`, etc.)
- **API base URL:** `https://civic.kytranempowerment.com/api` (already proxied via NPM)
- **Map embed:** `<iframe src="https://thenews.kytranempowerment.com/?region=americas&layers=contracts,parliament,spending" />`
- **Responsive breakpoints:** 480px (stack everything), 768px (2-col widgets), 1024px (full layout)
- **Deploy:** `tar czf` + Hostinger `hosting_deployStaticWebsite` API to `civic.kytranempowerment.com` (needs Hostinger website created for this subdomain, or deploy to main domain with path routing)

## Deployment Note

civic.kytranempowerment.com currently points to the W.A.T.C.H. API (port 8099). The static dashboard needs a different approach:
- **Option A:** Deploy dashboard to Hostinger on a different subdomain (e.g., `watch.kytranempowerment.com`) and keep `civic` for API
- **Option B:** Serve dashboard from the Flask app itself (add static file serving to the W.A.T.C.H. container)
- **Recommended: Option B** — Flask can serve static files at `/` while API lives at `/api/*`. No extra infrastructure needed. Add `app.static_folder` config to serve the dashboard HTML/CSS/JS.

## Testing

- Browser test: navigate all 5 tabs, verify data loads from API
- Filter test: apply filters on each table, verify results change
- Responsive test: check at 480px, 768px, 1024px
- Fallback: disconnect API, verify graceful "No data" messages (not crashes)
- Export: download CSV from Contracts tab, verify file contents
