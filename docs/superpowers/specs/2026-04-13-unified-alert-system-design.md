# Unified Alert System — Design Spec

**Date:** 2026-04-13
**Project:** #251 (LCARS Header Standardization) — Alert Consolidation
**Status:** Approved

## Problem

Three disconnected alert systems query different tables, show different data, and confuse the user:

- **Bell modal** (`/api/notifications`) → `system_notifications` + bridge failures + security
- **Dashboard Mission Briefing** (`/api/dashboard/alerts`) → `service_status`, `system_alerts`, `stack_health_alerts`, `task_execution_log`, `agent_rest_cycles`, `failed_logins`
- **Elbow flash** → same as bell, misses infrastructure alerts

Result: elbow flashes red but bell shows "All clear." Dashboard shows alerts the bell doesn't. No single view of what's wrong.

## Solution

### New Service: `services/alert_service.py`

Single function `get_unified_alerts(user_id, is_admin)` that queries all 7 tables:

| # | Table | Category | Who sees it |
|---|-------|----------|-------------|
| 1 | `system_notifications` | varies (by type) | admin=all, user=own visibility |
| 2 | `service_status` | infrastructure | admin only |
| 3 | `task_execution_log` | jobs | admin only |
| 4 | `system_alerts` | infrastructure | admin only |
| 5 | `stack_health_alerts` | infrastructure | admin only |
| 6 | `agent_rest_cycles` | agents | admin only |
| 7 | `failed_logins` | security | admin only |

### Response Shape

```json
{
  "success": true,
  "critical": [
    {"id": "sn-6856", "source": "system_notifications", "category": "infrastructure",
     "type": "error", "priority": "high", "title": "SSL Renewal Failed",
     "message": "...", "is_read": false, "timestamp": "..."}
  ],
  "categories": {
    "infrastructure": [...],
    "agents": [...],
    "security": [...],
    "jobs": [...]
  },
  "counts": {
    "total": 12,
    "unread": 5,
    "critical": 1
  }
}
```

Each alert item has a composite `id` (`{source_prefix}-{db_id}`) to support per-user read tracking across tables.

### New Endpoint: `/api/alerts/unified`

- `GET /api/alerts/unified` — returns full unified response
- `POST /api/alerts/unified/mark-read` — marks alerts as read (accepts list of composite IDs)
- `POST /api/alerts/unified/mark-all-read` — marks all current alerts as read

### Read Tracking

Uses existing `notification_reads` table. For non-`system_notifications` sources, composite IDs are stored (e.g., `svc-15`, `job-2841`). The `notification_id` column may need to become `alert_id VARCHAR` or a new `unified_alert_reads` table.

**Decision:** New table `unified_alert_reads`:
```sql
CREATE TABLE IF NOT EXISTS unified_alert_reads (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    alert_key VARCHAR(64) NOT NULL,  -- e.g. "sn-6856", "svc-15"
    read_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, alert_key)
);
CREATE INDEX idx_uar_user ON unified_alert_reads(user_id);
```

### Three Consumers

#### 1. Elbow Flash (`lcars-header.js`)

Polls `/api/alerts/unified` every 30s. Logic:
- `counts.critical > 0` → `lcarsSetAlertState("critical")` (red pulse)
- `counts.unread > 0` → `lcarsSetAlertState("warning")` (orange pulse)
- else → `lcarsSetAlertState("normal")`

Only the bottom elbow box flashes (already implemented).

#### 2. Bell Modal (compact view)

Shows on click from any LCARS-header module:
- **Top section:** Critical items listed individually (red dots)
- **Below:** Category summary cards showing count per category
  - "Infrastructure: 3 alerts" / "Jobs: 2 failures" / etc.
- **Footer:** "View Full Dashboard →" link to `/dashboard#mission-briefing`
- "Mark All Read" button calls `/api/alerts/unified/mark-all-read`

#### 3. Dashboard Mission Briefing (full view)

Same data, expanded:
- **Critical alerts** always expanded at top
- **Category sections** (Infrastructure, Agents, Security, Jobs) — expandable, show individual items
- Badge counts per section

### Backwards Compatibility

- `/api/notifications` stays, becomes thin wrapper around `get_unified_alerts()` returning flat list format
- `/api/dashboard/alerts` stays, becomes thin wrapper returning `{alerts, service_issues}` format
- Both old endpoints will be deprecated over time

### Files to Create/Modify

| File | Action |
|------|--------|
| `services/alert_service.py` | **CREATE** — `get_unified_alerts()`, `mark_alert_read()`, `mark_all_read()` |
| `database/migrations/NNN_unified_alert_reads.sql` | **CREATE** — new table |
| `app.py` | **MODIFY** — add `/api/alerts/unified` endpoints |
| `static/js/lcars-header.js` | **MODIFY** — polling uses new endpoint, bell renders compact view |
| `static/js/dashboard.js` | **MODIFY** — `fetchAlerts()` calls new endpoint, renders categories |
| `services/notification_service.py` | **MODIFY** — `get_notifications()` wraps `get_unified_alerts()` |
| `services/dashboard_service.py` | **MODIFY** — `get_alerts()` wraps `get_unified_alerts()` |

### Testing

1. Check `/api/alerts/unified` returns all 7 sources merged
2. Bell modal shows critical items + category counts on all AI Command modules
3. Dashboard mission briefing shows expanded category view
4. Elbow flashes on any unread critical/error from any source
5. "Mark All Read" in bell clears elbow flash
6. Per-user isolation — non-admin users see only their visibility scope
