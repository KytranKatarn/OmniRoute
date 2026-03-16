# Mission Profiles — Reconfigurable Station Routing

**Date**: 2026-03-16
**Project**: #146 Station Operations
**Task**: #953
**Status**: Approved

## Overview

Mission profiles dynamically reconfigure how the Bridge dispatcher routes jobs, prioritizes agents, manages resources, and presents the UI. Six preset profiles cover security audits, development sprints, content creation, maintenance, emergency response, and standard operations. Profiles activate manually, via schedule, or triggered by security events.

## The 6 Profiles

| Profile | Color | Primary Stations | Key Behavior |
|---------|-------|-----------------|-------------|
| **Standard Operations** | #00d4ff (cyan) | All equal | Default routing, normal IAAE, standard warmup |
| **Security Audit** | #EF4444 (red) | SECURITY, OPERATIONS | Scans every 30min, SSH monitor every 2min, SECURITY agents skip rest, deprioritize CREATIVE |
| **Feature Sprint** | #32CD32 (green) | ENGINEERING, ANALYTICS | Code scans auto-trigger, low-risk proposals auto-approve, code models prioritized in warmup |
| **Content Push** | #FF69B4 (pink) | CREATIVE, COMMUNICATIONS | Content generation prioritized, image gen models warm, ENGINEERING deprioritized |
| **Maintenance** | #F59E0B (amber) | OPERATIONS, ENGINEERING | All loop jobs reduced to minimum, aggressive agent rest, only critical jobs processed |
| **Emergency Response** | #DC2626 (dark red) | ALL active | All agents wake from barracks, max throughput, skip IAAE rest, Telegram on all alerts, cloud auto-approved |

## Data Model

### Table: `mission_profiles`

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | Primary key |
| name | VARCHAR(50) UNIQUE | Internal name (e.g. "security_audit") |
| display_name | VARCHAR(100) | UI display name |
| description | TEXT | What this profile does |
| color | VARCHAR(7) | Hex accent color when active |
| icon | VARCHAR(50) | Lucide icon name |
| job_routing_overrides | JSONB | {job_type: station_code} overrides to JOB_TYPE_STATION_MAP |
| station_priorities | JSONB | {station_code: weight} — higher weight = more dispatch preference |
| agent_config | JSONB | {warmup_priority: [...], rest_threshold: N, skip_rest: bool} |
| loop_job_config | JSONB | {job_id: {enabled: bool, interval_override: seconds}} |
| event_triggers | JSONB | [{condition: "fail2ban_bans > 5", cooldown_min: 30}] |
| is_default | BOOLEAN DEFAULT FALSE | One profile is default (Standard Operations) |
| created_at | TIMESTAMP DEFAULT NOW() |
| updated_at | TIMESTAMP DEFAULT NOW() |

### Table: `mission_schedules`

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL PK | |
| profile_id | INTEGER FK | References mission_profiles |
| cron_expression | VARCHAR(100) | When to activate (e.g. "0 2 * * 0" for Sunday 2 AM) |
| duration_minutes | INTEGER | How long to stay active (NULL = until next schedule) |
| is_active | BOOLEAN DEFAULT TRUE | |
| created_at | TIMESTAMP DEFAULT NOW() |

### Active profile

Stored in `system_config` table (key: `active_mission_profile`, value: profile name). Cached in dispatcher with 60s TTL.

## Activation Mechanisms

### Manual
- Bridge Command UI: profile selector dropdown in top bar
- Confirmation dialog shows what will change
- API: `PUT /api/mission/activate/<profile_id>`

### Scheduled
- Cron rules in `mission_schedules` table
- Agent loop job `_check_mission_schedule()` runs every 5 minutes
- Schedule takes precedence over manual (manual can override with a flag)

### Event-triggered
- Rules in profile's `event_triggers` JSONB field
- Evaluated by the auto-block pipeline and security alert system
- Conditions: fail2ban_bans, critical_alerts_count, ssh_brute_force
- Cooldown prevents rapid switching
- Returns to previous profile after cooldown expires

### Transition Process
1. Log change to `governance_audit_log` (who/what/why)
2. Telegram notification with old → new profile + trigger reason
3. Bridge UI updates: accent color, mission banner, station highlights
4. Dispatcher reloads routing overrides (next dispatch uses new map)
5. Warmup priority adjusts on next warmup cycle
6. IAAE thresholds update immediately

## Bridge Integration

### Dispatcher (`bridge_dispatcher.py`)
- `_get_active_profile()` — cached DB lookup (60s TTL)
- `_resolve_station(job_type)` — checks profile overrides first, falls back to static map
- Station priority weights affect agent selection within escalation chain

### IAAE (`agent_loop.py`)
- `_check_mission_schedule()` — new 5-min loop job
- Welfare/rest jobs check profile's `rest_threshold` and `skip_rest` flag
- Emergency Response temporarily disables rest requirements

### Warmup (`app.py`)
- `_warmup_ollama_models()` reads profile's `warmup_priority` list
- Profile-prioritized models load first, others deferred to later cycles

### Bridge UI (`bridge.html`)
- Mission banner below tab bar: profile name + color + icon
- Profile selector (dropdown or modal)
- Station circles glow intensity based on profile priority weights
- Active mission shown on viewscreen

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/mission/active | Current active profile with full config |
| GET | /api/mission/profiles | List all 6 profiles |
| PUT | /api/mission/activate/\<id\> | Switch active profile (manual) |
| POST | /api/mission/schedule | Add/update schedule rules |
| GET | /api/mission/schedule | List schedule rules |
| DELETE | /api/mission/schedule/\<id\> | Remove schedule rule |

## New/Modified Files

### New files
- `database/migrations/173_mission_profiles.sql` — tables + 6 seed profiles
- `ai_bridge/mission_manager.py` — profile loading, activation, schedule, event triggers

### Modified files
- `ai_bridge/bridge_dispatcher.py` — `_resolve_station()` with profile overrides
- `ai_bridge/agent_loop.py` — `_check_mission_schedule()` job + welfare overrides
- `platform_v2/app.py` — warmup reads profile priority
- `platform_v2/tools/bridge/routes.py` — 6 mission API endpoints
- `platform_v2/templates/tools/bridge.html` — mission banner + profile selector

## Out of Scope
- Custom user-defined profiles (only 6 presets)
- Per-agent profile overrides (agents follow their station's weight)
- Profile-specific full dashboard layouts (just color/banner/glow changes)
- A/B testing between profiles
