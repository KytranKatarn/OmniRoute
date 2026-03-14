# Google Work Suite Phase 2: Calendar + Drive Integration — Design Spec

## Overview

Activate the Calendar and Drive tabs in Google Work Suite. Full CRUD for Google Calendar events with agent auto-scheduling. Full Google Drive access — browse, upload, create Docs/Sheets, share files. Agents autonomously manage calendars (schedule from tasks) and create documents (reports, spreadsheets).

**Goal:** Complete the Google Work Suite trifecta: Gmail (Phase 1) + Calendar + Drive. Agents with Google accounts become fully autonomous workspace members who can schedule meetings, manage files, and generate reports.

## Scope

Four capabilities:
1. **Calendar CRUD** — list/create/update/delete events, week view, event modal
2. **Drive full access** — browse files, upload, create Docs/Sheets, share, folder navigation
3. **Agent autonomy** — auto-schedule from tasks, auto-generate reports as Docs/Sheets
4. **Frontend** — calendar week grid, drive file browser, modals for events/files

## Calendar Service

New file: platform_v2/tools/google_work_suite/services/calendar_service.py (~180 lines)

### Google API client

Add generic `get_google_client(account_id, api_name, api_version)` to google_api_service.py. Calendar uses `('calendar', 'v3')`.

### Functions

- `list_events(account_id, time_min, time_max, max_results)` — default current week, returns event list with id/summary/start/end/location/description/attendees
- `get_event(account_id, event_id)` — full detail
- `create_event(account_id, summary, start, end, description, location, attendees)` — insert event, return event_id + html_link
- `update_event(account_id, event_id, updates)` — patch event
- `delete_event(account_id, event_id)` — delete
- `list_calendars(account_id)` — all calendars (primary + shared)
- `auto_schedule_from_tasks(account_id, agent_name)` — query agent tasks, create events for upcoming deadlines not yet on calendar
- `schedule_meeting(account_id, summary, attendees, preferred_time, duration)` — find free slot via freebusy, create event

## Drive Service

New file: platform_v2/tools/google_work_suite/services/drive_service.py (~200 lines)

### Functions

- `list_files(account_id, folder_id, query, max_results)` — list files in folder, returns id/name/mimeType/size/modifiedTime/webViewLink
- `get_file(account_id, file_id)` — metadata + text content preview (export Docs/Sheets as plain text)
- `upload_file(account_id, name, content, mime_type, folder_id)` — upload small files (<10MB)
- `create_document(account_id, title, content, folder_id)` — create Google Doc
- `create_spreadsheet(account_id, title, data, folder_id)` — create Google Sheet with optional data (2D array)
- `share_file(account_id, file_id, email, role)` — share with user (reader/writer/commenter)
- `delete_file(account_id, file_id)` — trash file
- `create_folder(account_id, name, parent_id)` — create folder
- `agent_create_report(account_id, agent_name, title, sections)` — create structured Doc
- `agent_create_spreadsheet_from_data(account_id, agent_name, title, headers, rows)` — create Sheet with data

## OAuth Scope Upgrade

Update SCOPES in google_api_service.py: `drive.readonly` becomes `drive`. Existing accounts need re-auth — service handles 403 gracefully and prompts re-authorization.

## API Routes (10 endpoints)

Calendar (6):
- GET /api/calendar/<account_id>/events — list events
- GET /api/calendar/<account_id>/events/<event_id> — get event
- POST /api/calendar/<account_id>/events — create event
- PUT /api/calendar/<account_id>/events/<event_id> — update event
- DELETE /api/calendar/<account_id>/events/<event_id> — delete event
- GET /api/calendar/<account_id>/calendars — list calendars

Drive (4):
- GET /api/drive/<account_id>/files — list files
- GET /api/drive/<account_id>/files/<file_id> — get file + preview
- POST /api/drive/<account_id>/files — upload or create Doc/Sheet
- POST /api/drive/<account_id>/files/<file_id>/share — share file

All verify account ownership.

## APScheduler Job

Job #26: agent_calendar_drive — every 15 minutes. For each agent Google account: auto-schedule upcoming task deadlines as calendar events, generate pending reports as Drive documents.

## Frontend

### Calendar tab (activate from "coming soon")

Week view: 7-column CSS grid (Mon-Sun), hour rows (8am-8pm), event blocks positioned by time. Navigation arrows + Today button. Account selector.

Event modal: summary, start/end datetime, description, location, attendees, save/delete.

### Drive tab (activate from "coming soon")

File browser: breadcrumb path, file list (icon + name + date + size), click folder to navigate, click file for preview. Upload button. New dropdown (Folder/Document/Spreadsheet).

Share modal: email input + role selector.

### JS additions (~250 lines)

Calendar: loadCalendarEvents, renderWeekView, openEventModal, saveEvent, deleteEvent, navigateWeek
Drive: loadDriveFiles, renderFileList, navigateFolder, previewFile, uploadFile, createDocument, shareFile

### CSS additions (~40 lines)

Calendar grid, hour rows, event blocks, navigation. Drive file browser, breadcrumb, preview pane, new menu.

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| Create | services/calendar_service.py | Calendar CRUD + agent scheduling (~180 lines) |
| Create | services/drive_service.py | Drive operations + agent docs (~200 lines) |
| Modify | services/google_api_service.py | Generic client + drive scope (~15 lines) |
| Modify | routes.py | 10 new endpoints |
| Modify | google-work-suite.js | Calendar + Drive UI (~250 lines) |
| Modify | google_work_suite.html | Tab content + modals |
| Modify | google-work-suite.css | Calendar + Drive styles (~40 lines) |
| Modify | agent_loop.py | Job #26 |

Total: ~630 lines new, ~65 lines modified

## Scope constraints

- Primary calendar only
- No binary file download
- No real-time collaborative editing
- No Sheets formula execution
- Agent autonomy: task-based scheduling only
- Re-auth needed for Drive scope upgrade
