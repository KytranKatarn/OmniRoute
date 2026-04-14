# Unified Alert System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate 3 disconnected alert systems (bell modal, dashboard mission briefing, elbow flash) into one unified pipeline backed by a single endpoint.

**Architecture:** New `alert_service.py` queries 7 tables, returns categorized alerts with per-user read tracking. One new endpoint `/api/alerts/unified` serves all three consumers. Old endpoints become thin wrappers.

**Tech Stack:** Python/Flask, PostgreSQL, vanilla JS (lcars-header.js, dashboard.js)

**Spec:** `docs/superpowers/specs/2026-04-13-unified-alert-system-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `database/migrations/052_unified_alert_reads.sql` | CREATE | New read-tracking table |
| `services/alert_service.py` | CREATE | `get_unified_alerts()`, `mark_alert_read()`, `mark_all_alerts_read()` |
| `app.py` | MODIFY | Add 3 new `/api/alerts/unified*` routes |
| `services/notification_service.py` | MODIFY | `get_notifications()` wraps unified |
| `services/dashboard_service.py` | MODIFY | `get_alerts()` wraps unified |
| `static/js/lcars-header.js` | MODIFY | Polling + bell modal use new endpoint |
| `templates/includes/lcars-header.html` | MODIFY | Mark All Read button uses new endpoint |
| `static/js/dashboard.js` | MODIFY | `fetchAlerts()` uses new endpoint with categories |

---

### Task 1: Database Migration

**Files:**
- Create: `platform_v2/database/migrations/052_unified_alert_reads.sql`

- [ ] **Step 1: Write migration** — Create `unified_alert_reads` table with composite `alert_key`, per-user unique constraint, and indexes on `user_id` and `alert_key`.

- [ ] **Step 2: Run migration** via `docker exec archie_database psql`

- [ ] **Step 3: Verify** with `\d unified_alert_reads`

- [ ] **Step 4: Commit**

---

### Task 2: Alert Service

**Files:**
- Create: `platform_v2/services/alert_service.py`

- [ ] **Step 1: Create service** with `get_unified_alerts(user_id, is_admin)` querying all 7 tables. Uses composite keys (sn-, svc-, job-, sa-, sh-, arc-, fl-) and checks `unified_alert_reads` for read state. Returns `{critical, categories, counts}`.

- [ ] **Step 2: Add `mark_alert_read(user_id, alert_key)`** — INSERT ON CONFLICT DO NOTHING into `unified_alert_reads`.

- [ ] **Step 3: Add `mark_all_alerts_read(user_id, is_admin)`** — Fetches all current alerts, bulk inserts read records using `execute_values`.

- [ ] **Step 4: Commit**

---

### Task 3: API Routes

**Files:**
- Modify: `platform_v2/app.py`

- [ ] **Step 1: Add routes** — `GET /api/alerts/unified`, `POST /api/alerts/unified/mark-read`, `POST /api/alerts/unified/mark-all-read`. All `@login_required`.

- [ ] **Step 2: Deploy and test** — `docker compose restart archie_platform`, verify endpoint returns data.

- [ ] **Step 3: Commit**

---

### Task 4: LCARS Header JS — Polling + Bell

**Files:**
- Modify: `platform_v2/static/js/lcars-header.js`
- Modify: `platform_v2/templates/includes/lcars-header.html`

- [ ] **Step 1: Update `_pollNotifications()`** — Change from `/api/notifications` to `/api/alerts/unified`. Use `counts.critical` / `counts.unread` for elbow state. Cache response as `window._lastUnifiedAlerts`.

- [ ] **Step 2: Rewrite `_loadNotificationList()`** — Render critical items at top with red dots, then category sections with counts, then "VIEW FULL DASHBOARD" link. Use DOM methods only (textContent, createElement) — no setting of content via markup strings for XSS safety.

- [ ] **Step 3: Add `_renderAlertItem(a)` helper** — Builds DOM element for one alert: severity dot + title + message. Click marks read via `/api/alerts/unified/mark-read`.

- [ ] **Step 4: Update Mark All Read button** in `lcars-header.html` to call `/api/alerts/unified/mark-all-read`.

- [ ] **Step 5: Commit**

---

### Task 5: Dashboard Mission Briefing

**Files:**
- Modify: `platform_v2/static/js/dashboard.js`

- [ ] **Step 1: Update `fetchAlerts()`** — Call `/api/alerts/unified` instead of `/api/dashboard/alerts`.

- [ ] **Step 2: Add `renderAlertsUnified(data)`** — Critical alerts at top, then expandable category sections (Infrastructure, Agents, Security, Jobs) with badge counts. Uses existing `briefing-alert-item` CSS classes. All DOM built with createElement/textContent.

- [ ] **Step 3: Commit**

---

### Task 6: Wire Old Endpoints as Wrappers

**Files:**
- Modify: `platform_v2/services/notification_service.py`
- Modify: `platform_v2/services/dashboard_service.py`

- [ ] **Step 1: Wrap `notification_service.get_notifications()`** — Call `get_unified_alerts()`, flatten to old format. Keep old implementation as `_get_notifications_legacy()`.

- [ ] **Step 2: Wrap `dashboard_service.get_alerts()`** — Call `get_unified_alerts()`, split into `{alerts, service_issues}` format. Keep old implementation as `_get_alerts_legacy()`.

- [ ] **Step 3: Commit**

---

### Task 7: Deploy + End-to-End Verification

- [ ] **Step 1: Restart** — `docker compose restart archie_platform`

- [ ] **Step 2: Test unified endpoint** — Browser console `fetch('/api/alerts/unified')`, verify all 7 sources present.

- [ ] **Step 3: Test bell modal** — Click ALERTS on any AI Command module, verify critical + categories + dashboard link visible.

- [ ] **Step 4: Test elbow flash** — Unread errors should pulse bottom elbow. Mark All Read should stop flash.

- [ ] **Step 5: Test dashboard** — Mission Briefing System Alerts should show same categorized data.

- [ ] **Step 6: Final commit**
