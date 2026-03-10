# Unified Operations Center — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Centralize all job/approval/loop visibility into a global alert bar + reorganized Autonomy ops center.

**Architecture:** New `ops_routes.py` provides a lightweight `/api/ops-summary` endpoint aggregating 4 job systems. Global alert bar in `base.html` polls it every 30s. Autonomy template reorganized into 4 concern-based tabs (Approvals, Active Jobs, Health, History). Audio chime for Tier 2 approvals.

**Tech Stack:** Flask (Python), Jinja2 templates, vanilla JS, existing LCARS CSS, APScheduler introspection, PostgreSQL COUNT queries.

**Security Note:** All dynamic content rendered via `textContent` or `escapeHtml()` — no raw innerHTML with untrusted data. Use existing `escHtml()` pattern from consciousness.js.

---

### Task 1: Backend — Unified Ops Summary API

**Files:**
- Create: `platform_v2/tools/autonomy/ops_routes.py`
- Modify: `platform_v2/tools/autonomy/__init__.py`

**Step 1: Create ops_routes.py with 4 endpoints**

Endpoints:
- `GET /api/ops-summary` — lightweight alert bar data (approval counts, active job counts, loop states, alerts array)
- `GET /api/ops-active-jobs` — detailed active jobs across all 4 systems (bridge_jobs, server loops, agent loop jobs, scheduler jobs)
- `GET /api/ops-health` — health grid data (per-job last_run, ok/error counts 24h, system component checks)
- `GET /api/ops-history` — unified history merging autonomy_loop_log + bridge_jobs with system/time filters

All endpoints: `@login_required @admin_required`, read-only queries, no heavy joins.

Key data sources:
- `autonomy_approval_queue` — pending/expired counts
- `bridge_jobs` — running/pending/stalled/failed counts
- `get_server_loops()` from `tools.consciousness.processing_routes`
- `current_app.config["AGENT_LOOP"].get_status()` — agent loop job list
- `current_app.config["CONSCIOUSNESS_SCHEDULER"].get_jobs()` — scheduler job list
- `autonomy_loop_log` — loop execution history
- Ollama `/api/tags` (GET, 3s timeout) — health check
- `telegram_users` WHERE is_authorized — Telegram health

Alert rules in ops-summary:
- Pending approvals > 0 → severity: high
- Agent loop stopped → severity: high
- Bridge job running > 30min → severity: medium (stalled)
- Failed jobs in last hour → severity: low

**Step 2: Register ops_routes in __init__.py**

Import `register_ops_routes` and call with blueprint + admin_required decorator (reuse existing pattern from routes.py).

**Step 3: Commit**

```bash
git add platform_v2/tools/autonomy/ops_routes.py platform_v2/tools/autonomy/__init__.py
git commit -m "feat(autonomy): unified ops-summary API aggregating 4 job systems"
```

---

### Task 2: Global Alert Bar — CSS + JS

**Files:**
- Create: `platform_v2/static/css/ops-alert-bar.css`
- Create: `platform_v2/static/js/ops-alert-bar.js`

**Step 1: Create LCARS-style alert bar CSS**

- `.ops-alert-bar` — hidden by default, flex row when `.visible`, collapses to 3px gradient line when no alerts
- `.ops-alert-section` — clickable segments for approvals/jobs/loops/errors
- `.severity-high` (red #ff6b6b, pulse animation), `.severity-medium` (amber #ff9f43), `.severity-low` (yellow #ffd93d), `.ok` (cyan #00e5ff)
- `.ops-alert-right` — right-aligned sound toggle + snooze button
- Font: Antonio, letter-spacing 0.5px (matches LCARS aesthetic)

**Step 2: Create alert bar JS**

IIFE module that:
- Polls `/tools/autonomy/api/ops-summary` every 30s
- Renders sections using safe DOM methods (createElement + textContent, NOT innerHTML with untrusted data)
- Each section onclick navigates to `/tools/autonomy#approvals` or `#active`
- Sound toggle stored in localStorage (`opsSoundEnabled`)
- Snooze stores `opsSnoozedUntil` timestamp in localStorage (1hr)
- Audio chime: plays `/static/audio/lcars-chime.mp3` (volume 0.3) when new high-severity alerts appear
- Tracks last-seen alert IDs in localStorage to prevent repeat chimes
- Gracefully handles 401/403 (non-admin users see nothing)

**Step 3: Commit**

```bash
git add platform_v2/static/css/ops-alert-bar.css platform_v2/static/js/ops-alert-bar.js
git commit -m "feat(ops): global LCARS alert bar CSS + JS with audio chime"
```

---

### Task 3: Inject Alert Bar into Base Template + Audio

**Files:**
- Modify: `platform_v2/templates/base.html` (after adminNotificationBar, ~line 285)
- Create: `platform_v2/static/audio/lcars-chime.mp3`

**Step 1: Add CSS/JS includes and alert bar div**

After the existing `adminNotificationBar` block, add (admin-only):
- Link to `ops-alert-bar.css`
- Empty `<div id="opsAlertBar" class="ops-alert-bar"></div>`
- Script tag for `ops-alert-bar.js`

**Step 2: Create or generate LCARS chime**

Short synthesized tone. If no audio file available, add a Web Audio API fallback in JS that generates a brief ascending two-tone beep.

**Step 3: Commit**

```bash
git add platform_v2/templates/base.html platform_v2/static/audio/
git commit -m "feat(ops): inject global alert bar into base template"
```

---

### Task 4: Autonomy Template — Reorganize to 4 Concern-Based Tabs

**Files:**
- Modify: `platform_v2/templates/tools/autonomy.html` (~line 152 tab_nav, lines 160-247 tab divs, lines 253-728 inline JS)

**Step 1: Replace tab navigation**

Change tabs from `[overview, approvals, history, config]` to `[approvals, active, health, history]`.
Config tab content moves into Health tab as a collapsible section.

**Step 2: Replace tab content divs**

- **tab-approvals** (default active): Move existing approval queue HTML here. Add "Bulk Approve All" / "Bulk Reject All" buttons for same-type pending items. Keep existing filter buttons (pending/approved/rejected/all).
- **tab-active**: 4 source sections — Bridge Jobs (progress bars), Server Loops (toggle switches), Agent Loop (17 jobs with next_run), Scheduler (10 cron jobs with next_run). Each section has collapsible header with count badge.
- **tab-health**: Grid of job health cards (name, frequency, last_run, status dot, 24h ok/err counts). System components row at bottom (Ollama, Telegram, DB). Status: green/amber/red based on staleness vs interval.
- **tab-history**: Existing history HTML + system filter dropdown (All/Bridge/Agent Loop). Uses `/api/ops-history`.

**Step 3: Update inline JS**

- Add `loadActiveJobs()` → fetches `/api/ops-active-jobs`, renders 4 sections
- Add `loadHealth()` → fetches `/api/ops-health`, renders health grid
- Update `loadHistory()` → uses `/api/ops-history` with system param
- Update `switchTab()` → calls correct loader per tab
- Add hash-based tab routing: read `window.location.hash` on load → `switchTab(hash)`
- Add `toggleServerLoop(op)` → POST to `/tools/consciousness/processing/server-loop/toggle`
- Active jobs tab auto-refreshes every 10s when visible
- All rendering uses `textContent` or `escapeHtml()` for user-facing data

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/autonomy.html
git commit -m "feat(autonomy): reorganize to 4 concern-based ops center tabs"
```

---

### Task 5: Bulk Approve Endpoint + Polish

**Files:**
- Modify: `platform_v2/tools/autonomy/routes.py`

**Step 1: Add bulk approve/reject endpoint**

`POST /api/approvals/bulk` — accepts `{"action": "approve"|"reject", "ids": [1,2,3]}`.
Iterates and calls existing per-item approve/reject logic. Returns `{"ok": N, "failed": N}`.

**Step 2: Commit**

```bash
git add platform_v2/tools/autonomy/routes.py
git commit -m "feat(autonomy): bulk approve/reject endpoint"
```

---

### Task 6: Deploy + Integration Test + Dev HQ

**Files:**
- None (operational)

**Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

**Step 2: Verify**

- Dashboard: alert bar visible with pending approval count
- Click alert bar → navigates to `/tools/autonomy#approvals`
- Autonomy: 4 tabs load correctly
- Active Jobs: shows running bridge job (translate), server loop states, agent loop jobs, scheduler jobs
- Health: green/amber/red cards for all jobs
- History: unified log with system filter
- Sound toggle + snooze work
- Bulk approve works on the 6 pending cloud escalations

**Step 3: Dev HQ updates**

```
mcp create_project
mcp create_task per component
mcp complete_task as verified
mcp log_decision for centralized ops architecture
mcp update_project_understanding
```

**Step 4: Final commit + push**

```bash
git push
```
