# Google Work Suite Phase 3-4: Agent Autonomy + Module Consolidation — Design Spec

## Overview

Upgrade agent email processing with AI-driven action decisions (reply, schedule meeting, create task, forward, archive). Add smart scheduling with conflict detection and working hours. Auto-generate daily summary reports as Drive docs. Consolidate Email Manager + Scheduler + Google Workspace modules into Google Work Suite by disabling old modules and adding redirect routes.

## Phase 3: Agent Autonomy

### Enhanced email processing (gmail_service.py)

Upgrade `process_agent_inbox()` Bridge prompt to return structured JSON: {priority, category, action, draft_reply, meeting_details, task_details}. Execute actions: reply→send_email, schedule_meeting→calendar_service, create_task→unified_tasks INSERT, forward→send with forwarded body, archive→apply label, ignore→mark read.

### Smart scheduling (calendar_service.py)

Upgrade `auto_schedule_from_tasks()`: check conflicts via freebusy before creating, priority-based slot selection, 15min buffer between meetings, working hours 9am-6pm only.

### Daily summary (drive_service.py)

New `generate_daily_summary(account_id, agent_name)`: query 24h agent activity (emails processed, meetings scheduled, tasks completed), build structured text, create Google Doc, share with owner. Called daily at 18:00 via APScheduler.

## Phase 4: Module Consolidation

Disable 3 old modules in module_registry.py (enabled=False): email_manager, scheduler, google_workspace. Add redirect routes in Google Work Suite for old URL prefixes. No data migration needed (Email Manager uses SMTP, Scheduler calendar_events stays unused, Google Workspace was a stub).

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| Modify | services/gmail_service.py | Enhanced AI analysis + action execution (~60 lines) |
| Modify | services/calendar_service.py | Smart scheduling (~30 lines) |
| Modify | services/drive_service.py | Daily summary generation (~40 lines) |
| Modify | module_registry.py | Disable 3 old modules |
| Modify | routes.py | 3 redirect routes |
| Modify | agent_loop.py | Upgrade email job + daily summary trigger |

Total: ~130 lines added, ~10 lines modified. No new files/tables/frontend.
