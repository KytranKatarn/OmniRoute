# Unified Operations Center — Design Document

**Date**: 2026-03-10
**Status**: Approved
**Problem**: Jobs, approvals, and background processes are scattered across 4 systems (Autonomy, Bridge Command, Consciousness Server Loops, Consciousness Scheduler) with no single visibility point. Pending approvals go unnoticed. No way to see what's running across all systems.

---

## Architecture

### Global Alert Bar (every page)

Persistent LCARS strip injected via base layout template:

```
┌──────────────────────────────────────────────────────────────────────┐
│ ⚠ 6 APPROVALS PENDING  │  1 JOB RUNNING  │  2 LOOPS ACTIVE  │  🔊  │
└──────────────────────────────────────────────────────────────────────┘
```

- Polls `GET /api/ops-summary` every 30s
- Each section clickable → navigates to Autonomy ops center
- Red pulse for pending approvals, amber for stalled/failed
- Audio chime (configurable, off by default) for new Tier 2 approvals
- Dismiss/snooze individual alerts (1hr)
- Collapses to thin indicator line when no alerts
- Stores last-seen alert IDs in localStorage to prevent repeat chimes

### Autonomy Ops Center — 4 Concern-Based Tabs

Replaces current Autonomy tabs (Overview, Approvals, History, Config).

**Tab 1: Approvals** (what needs attention NOW)
- Pending items from `autonomy_approval_queue` — approve/reject/defer
- Grouped by urgency: Tier 2 at top, expired below
- Card: action type, requesting agent, reason, timestamp, age
- Bulk approve/reject for same-type items

**Tab 2: Active Jobs** (what's running across ALL systems)
- Unified live feed:
  - `bridge_jobs` WHERE status IN ('running', 'pending')
  - Agent Loop 17 jobs — last heartbeat, items this cycle
  - Consciousness Scheduler 10 cron jobs — next run, last result
  - Server Loops 4 toggles — on/off with toggle buttons
- Each: source badge, description, progress bar, agent, duration
- Filter by source system

**Tab 3: Health** (are all systems working?)
- Grid of all 31+ scheduled jobs across 4 systems
- Each card: name, frequency, last run, status (green/red/amber), error count (24h)
- Stale detection: amber if missed 2x interval
- System health: Ollama, DB pool, Telegram bot

**Tab 4: History** (what happened)
- Unified log: `autonomy_loop_log` + `bridge_jobs` (completed/failed) + `task_execution_log`
- Chronological, filterable by system/status/time/agent
- Searchable by description

### Backend — Unified Ops API

`GET /api/ops-summary` — lightweight aggregation endpoint:

```json
{
  "approvals": { "pending": 6, "expired": 27, "oldest_age_mins": 240 },
  "active_jobs": {
    "bridge": { "running": 1, "pending": 0, "stalled": 0 },
    "server_loops": { "translate": true, "analysis": false, "embedding": false, "reindex": false },
    "agent_loop": { "running": true, "job_count": 17 },
    "scheduler": { "running": true, "job_count": 10 }
  },
  "errors_1h": { "bridge_failed": 2, "loop_errors": 0 },
  "alerts": [
    { "type": "approval", "severity": "high", "message": "6 cloud escalations pending", "count": 6 },
    { "type": "stalled", "severity": "medium", "message": "Translation job running 45min", "job_id": 4511 }
  ]
}
```

Alert rules:
- Pending approvals > 0 → high severity
- Bridge job running > 30min → medium (stalled)
- Scheduled job missed 2x interval → medium
- Agent loop stopped → high
- Failed jobs in last hour → low

---

## Files

**New:**
- `platform_v2/tools/autonomy/ops_routes.py` — unified ops API
- `platform_v2/static/js/ops-alert-bar.js` — global alert bar + audio
- `platform_v2/static/css/ops-alert-bar.css` — LCARS alert bar styles
- `platform_v2/static/audio/lcars-chime.mp3` — alert tone

**Modified:**
- `platform_v2/templates/layouts/lcars.html` — inject alert bar
- `platform_v2/templates/tools/autonomy.html` — 4 concern-based tabs
- `platform_v2/tools/autonomy/routes.py` — register ops_routes, new endpoints
- `platform_v2/tools/autonomy/__init__.py` — wire up routes

**Not touching:**
- Bridge Command (read-only from ops center)
- Consciousness processing_routes (server loop toggles appear in both places)
- Agent Loop internals (read-only)
- Consciousness Scheduler (read-only)

---

## Out of Scope
- Fixing Telegram notification gap (separate bug)
- Refactoring job creation/tracking internals
- Moving server loop toggles out of Consciousness
