# Google Work Suite Phase 2: Calendar + Drive — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate Calendar and Drive tabs with full CRUD, agent auto-scheduling, Drive file management, and document generation — completing the Google Work Suite trifecta.

**Architecture:** `calendar_service.py` and `drive_service.py` alongside existing `gmail_service.py`, all sharing `google_api_service.py` for OAuth. Generic `get_google_client()` builds API clients. APScheduler job #26 handles agent autonomy. Frontend activates both "coming soon" tabs.

**Tech Stack:** Flask, google-api-python-client (Calendar v3, Drive v3), vanilla JS

**Key patterns:**
- Services: `from .services.google_api_service import get_google_client`
- Routes: `@google_work_suite_bp.route(...)` + `@login_required`, `_verify_ownership(account_id)`
- Agent loop: `with_app_context`, `IntervalTrigger`
- Frontend: IIFE, `api(method, path, body)`, createElement/textContent, `gws-` CSS prefix
- Google packages already installed (Docker rebuilt earlier this session)

---

## Task 1: Upgrade google_api_service + Calendar Service

**Files:**
- Modify: `platform_v2/tools/google_work_suite/services/google_api_service.py`
- Create: `platform_v2/tools/google_work_suite/services/calendar_service.py`

- [ ] **Step 1: Add generic get_google_client() to google_api_service.py**

Read the file, find `get_gmail_client()`. Add a generic version:
```python
def get_google_client(account_id, api_name, api_version):
    """Build any Google API client with stored credentials."""
    # Same token loading + refresh logic as get_gmail_client
    # Return build(api_name, api_version, credentials=creds)
```

Also update SCOPES: change `drive.readonly` to `drive`.

- [ ] **Step 2: Write calendar_service.py (~180 lines)**

All functions use `get_google_client(account_id, 'calendar', 'v3')`.

Functions: list_events, get_event, create_event, update_event, delete_event, list_calendars, auto_schedule_from_tasks, schedule_meeting.

For auto_schedule_from_tasks: query `unified_tasks` table for tasks assigned to agent with due dates, check if event already exists (search by summary), create if missing.

For schedule_meeting: use `freebusy.query()` to find available slot, then create event.

- [ ] **Step 3: Verify + commit**

```bash
docker exec archie_platform python3 -c "from tools.google_work_suite.services.calendar_service import list_events, create_event, auto_schedule_from_tasks; print('OK')"
git add platform_v2/tools/google_work_suite/services/google_api_service.py platform_v2/tools/google_work_suite/services/calendar_service.py
git commit -m "feat(google-work-suite): add calendar service + generic Google client"
```

---

## Task 2: Drive Service

**Files:**
- Create: `platform_v2/tools/google_work_suite/services/drive_service.py`

- [ ] **Step 1: Write drive_service.py (~200 lines)**

Uses `get_google_client(account_id, 'drive', 'v3')`.

Functions: list_files, get_file (with text export for Docs/Sheets), upload_file, create_document, create_spreadsheet, share_file, delete_file, create_folder, agent_create_report, agent_create_spreadsheet_from_data.

For create_document: create with mimeType `application/vnd.google-apps.document`. If content provided, use Docs API to insert text.

For create_spreadsheet: create with mimeType `application/vnd.google-apps.spreadsheet`. If data provided, use Sheets API `spreadsheets.values.update()`.

For text preview in get_file: export Docs as `text/plain`, Sheets as `text/csv`.

- [ ] **Step 2: Verify + commit**

```bash
docker exec archie_platform python3 -c "from tools.google_work_suite.services.drive_service import list_files, create_document, upload_file; print('OK')"
git add platform_v2/tools/google_work_suite/services/drive_service.py
git commit -m "feat(google-work-suite): add Drive service — files, docs, sheets, sharing"
```

---

## Task 3: Routes + APScheduler

**Files:**
- Modify: `platform_v2/tools/google_work_suite/routes.py`
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Add 10 routes to routes.py**

Calendar (6): events list/get/create/update/delete + calendars list.
Drive (4): files list/get, files create/upload, file share.

All routes verify ownership via `_verify_ownership(account_id)`. Local service imports. Datetime serialization on responses.

- [ ] **Step 2: Add APScheduler job #26**

In agent_loop.py, add:
```python
self.scheduler.add_job(
    with_app_context(self._agent_calendar_drive_tasks),
    trigger=IntervalTrigger(minutes=15),
    id="agent_calendar_drive",
    name="Agent Loop: Calendar + Drive Autonomy",
    replace_existing=True,
)
```

Method queries agent Google accounts, calls auto_schedule_from_tasks for each.

Update job count to 26, add to stop() list.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/google_work_suite/routes.py ai_bridge/agent_loop.py
git commit -m "feat(google-work-suite): add 10 calendar+drive routes + APScheduler job #26"
```

---

## Task 4: Frontend — Calendar + Drive Tabs

**Files:**
- Modify: `platform_v2/static/js/google-work-suite.js`
- Modify: `platform_v2/templates/tools/google_work_suite.html`
- Modify: `platform_v2/static/css/google-work-suite.css`

- [ ] **Step 1: Activate Calendar + Drive tabs in HTML**

Remove `gws-coming-soon-tab` class from Calendar and Drive tab buttons. Add tab content containers:

Calendar tab content: week navigation bar (prev/today/next), calendar grid container, account selector.

Drive tab content: breadcrumb path, file list container, preview pane, New dropdown (Folder/Document/Spreadsheet), upload button.

Event modal: summary, start datetime, end datetime, description, location, attendees, save/delete buttons.

Share modal: email input, role select (reader/writer/commenter), share button.

- [ ] **Step 2: Add Calendar + Drive JS (~250 lines)**

Calendar functions:
- `loadCalendarEvents(accountId, weekStart)` — GET events for the week
- `renderWeekView(events)` — 7-column grid, position events by time
- `openEventModal(eventId)` — populate modal for create/edit
- `saveEvent()` — POST or PUT
- `deleteEvent(eventId)` — DELETE
- `navigateWeek(dir)` — shift weekStart by +-7 days, reload

Drive functions:
- `loadDriveFiles(accountId, folderId)` — GET files list
- `renderFileList(files)` — file rows with type icons
- `navigateFolder(folderId)` — update breadcrumb stack, reload
- `previewFile(fileId)` — GET file content, show in preview pane
- `uploadFile()` — file input → FormData → POST
- `createDocument(type)` — prompt name → POST
- `shareFile(fileId)` — open share modal → POST

Update `setTab()` to handle 'calendar' and 'drive' tabs (load data on tab switch).

- [ ] **Step 3: Add CSS (~40 lines)**

Calendar: `.gws-calendar-grid` (7-col grid), `.gws-calendar-event` (colored block), `.gws-calendar-nav`, `.gws-calendar-hour`.

Drive: `.gws-drive-browser`, `.gws-drive-file-row`, `.gws-drive-breadcrumb`, `.gws-drive-preview`, `.gws-drive-new-menu`.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/templates/tools/google_work_suite.html platform_v2/static/js/google-work-suite.js platform_v2/static/css/google-work-suite.css
git commit -m "feat(google-work-suite): activate Calendar + Drive tabs with full UI"
```

---

## Task 5: Integration Test

- [ ] **Step 1: Write + run test**

Test: calendar_service + drive_service imports, 10+ new routes registered, HTML has calendar/drive tab content (gwsCalendarGrid, gwsDriveFiles, gwsEventModal), JS has loadCalendarEvents/renderWeekView/loadDriveFiles/uploadFile, CSS has .gws-calendar-grid/.gws-drive-browser, APScheduler job count includes agent_calendar_drive.

- [ ] **Step 2: Fix failures + re-test**

---

## Task 6: Push + Dev HQ

- [ ] **Step 1: Push**

```bash
git push origin main
```

- [ ] **Step 2: Update Dev HQ**

- store_memory — GWS Phase 2 complete
