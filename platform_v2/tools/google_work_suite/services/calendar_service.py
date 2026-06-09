"""
Google Calendar Service — event management, scheduling, and agent automation.
"""

import logging
from datetime import datetime, timedelta, timezone

from database import get_db_cursor

from .google_api_service import get_google_client

logger = logging.getLogger(__name__)


def _get_service(account_id):
    return get_google_client(account_id, "calendar", "v3")


def _parse_event(event):
    """Normalise a raw Calendar API event dict to a consistent shape."""
    start_raw = event.get("start", {})
    end_raw = event.get("end", {})
    return {
        "id": event.get("id"),
        "summary": event.get("summary", "(No title)"),
        "start": start_raw.get("dateTime") or start_raw.get("date"),
        "end": end_raw.get("dateTime") or end_raw.get("date"),
        "all_day": "date" in start_raw and "dateTime" not in start_raw,
        "location": event.get("location"),
        "description": event.get("description"),
        "attendees": [
            {
                "email": a.get("email"),
                "display_name": a.get("displayName"),
                "response": a.get("responseStatus"),
            }
            for a in event.get("attendees", [])
        ],
        "status": event.get("status"),
        "html_link": event.get("htmlLink"),
    }


def list_events(account_id, time_min=None, time_max=None, max_results=50):
    """List calendar events. Defaults to the current week if no range supplied."""
    try:
        service = _get_service(account_id)

        if not time_min:
            now = datetime.now(timezone.utc)
            week_start = now - timedelta(days=now.weekday())
            time_min = week_start.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        if not time_max:
            # End of the week (7 days from time_min start)
            start_dt = datetime.fromisoformat(time_min.replace("Z", "+00:00"))
            time_max = (start_dt + timedelta(days=7)).isoformat()

        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return [_parse_event(e) for e in result.get("items", [])]
    except Exception as exc:
        logger.error("list_events failed for account %s: %s", account_id, exc)
        raise


def get_event(account_id, event_id):
    """Fetch full detail for a single calendar event."""
    try:
        service = _get_service(account_id)
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        return _parse_event(event)
    except Exception as exc:
        logger.error("get_event failed for account %s, event %s: %s", account_id, event_id, exc)
        raise


def create_event(account_id, summary, start, end, description=None, location=None, attendees=None):
    """Create a new calendar event and return its id and link."""
    try:
        service = _get_service(account_id)
        body = {
            "summary": summary,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": end, "timeZone": "UTC"},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees]

        result = service.events().insert(calendarId="primary", body=body).execute()
        logger.info(
            "Created calendar event '%s' (id=%s) for account %s",
            summary,
            result.get("id"),
            account_id,
        )
        return {"event_id": result["id"], "html_link": result.get("htmlLink")}
    except Exception as exc:
        logger.error("create_event failed for account %s: %s", account_id, exc)
        raise


def update_event(account_id, event_id, updates):
    """Patch an existing event with the provided field updates."""
    try:
        service = _get_service(account_id)
        body = dict(updates or {})
        # Frontend sends start/end as plain ISO strings; Calendar API needs {dateTime,timeZone}
        if isinstance(body.get("start"), str):
            body["start"] = {"dateTime": body["start"], "timeZone": "UTC"}
        if isinstance(body.get("end"), str):
            body["end"] = {"dateTime": body["end"], "timeZone": "UTC"}
        # Map attendee email strings to API objects; drop empty list so we don't wipe attendees
        if "attendees" in body:
            att = body["attendees"]
            if isinstance(att, list) and att and isinstance(att[0], str):
                body["attendees"] = [{"email": e} for e in att]
            elif not att:
                body.pop("attendees")
        # Don't blank optional text fields when the modal submits them empty
        for _k in ("location", "description"):
            if body.get(_k) == "":
                body.pop(_k, None)
        result = service.events().patch(calendarId="primary", eventId=event_id, body=body).execute()
        logger.info("Updated calendar event %s for account %s", event_id, account_id)
        return _parse_event(result)
    except Exception as exc:
        logger.error(
            "update_event failed for account %s, event %s: %s",
            account_id,
            event_id,
            exc,
        )
        raise


def delete_event(account_id, event_id):
    """Delete (cancel) a calendar event."""
    try:
        service = _get_service(account_id)
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        logger.info("Deleted calendar event %s for account %s", event_id, account_id)
        return {"success": True, "event_id": event_id}
    except Exception as exc:
        logger.error(
            "delete_event failed for account %s, event %s: %s",
            account_id,
            event_id,
            exc,
        )
        raise


def list_calendars(account_id):
    """Return all calendars visible to this account."""
    try:
        service = _get_service(account_id)
        result = service.calendarList().list().execute()
        return [
            {
                "id": cal.get("id"),
                "summary": cal.get("summary"),
                "primary": cal.get("primary", False),
                "access_role": cal.get("accessRole"),
            }
            for cal in result.get("items", [])
        ]
    except Exception as exc:
        logger.error("list_calendars failed for account %s: %s", account_id, exc)
        raise


def _check_conflicts(service, start, end):
    """Check if a time slot has conflicts. Returns True if busy."""
    try:
        body = {
            "timeMin": start,
            "timeMax": end,
            "items": [{"id": "primary"}],
        }
        result = service.freebusy().query(body=body).execute()
        busy = result.get("calendars", {}).get("primary", {}).get("busy", [])
        return len(busy) > 0
    except Exception as exc:
        logger.warning("_check_conflicts failed: %s", exc)
        return False  # assume free on error


def _find_available_slot(service, date, duration_minutes=60):
    """Find first available slot on given date within working hours (9-18)."""
    start = datetime(date.year, date.month, date.day, 9, 0)
    end_of_day = datetime(date.year, date.month, date.day, 18, 0)
    while start + timedelta(minutes=duration_minutes + 15) <= end_of_day:
        slot_end = start + timedelta(minutes=duration_minutes)
        if not _check_conflicts(service, start.isoformat() + "Z", slot_end.isoformat() + "Z"):
            return start, slot_end
        start = slot_end + timedelta(minutes=15)  # 15 min buffer
    return None, None  # no available slot found


def auto_schedule_from_tasks(account_id, agent_name):
    """
    Pull in-progress tasks for agent_name that have a due_date and ensure
    each has a corresponding calendar event.  Returns the count created.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, title, due_date FROM unified_tasks "
                "WHERE assigned_to = %s AND status = 'in_progress' AND due_date IS NOT NULL",
                (agent_name,),
            )
            tasks = cur.fetchall()

        service = _get_service(account_id)
        created = 0
        for task in tasks:
            task_id = task["id"]
            title = task["title"]
            due_date = task["due_date"]
            # Check if an event with this title already exists around the due date
            # Search window: ±1 day around due date
            search_min = (due_date - timedelta(days=1)).isoformat()
            search_max = (due_date + timedelta(days=1)).isoformat()
            existing = list_events(account_id, time_min=search_min, time_max=search_max, max_results=100)
            already_scheduled = any(e["summary"] == title for e in existing)

            if not already_scheduled:
                # Try to find a conflict-free slot on the due date
                slot_start, slot_end = _find_available_slot(service, due_date, duration_minutes=60)
                if slot_start is None:
                    # Fall back to 1h before due time regardless of conflicts
                    slot_start = due_date - timedelta(hours=1)
                    slot_end = due_date
                create_event(
                    account_id,
                    summary=title,
                    start=(slot_start.isoformat() if hasattr(slot_start, "isoformat") else str(slot_start)),
                    end=(slot_end.isoformat() if hasattr(slot_end, "isoformat") else str(slot_end)),
                    description=f"Auto-scheduled from ARCHIE task #{task_id}",
                )
                created += 1

        logger.info(
            "auto_schedule_from_tasks: created %d events for agent %s",
            created,
            agent_name,
        )
        return {"events_created": created, "tasks_checked": len(tasks)}
    except Exception as exc:
        logger.error(
            "auto_schedule_from_tasks failed for account %s, agent %s: %s",
            account_id,
            agent_name,
            exc,
        )
        raise


def schedule_meeting(account_id, summary, attendee_emails, preferred_time=None, duration_minutes=30):
    """
    Find the first available slot (within the next 7 days) and create a meeting.
    Uses freebusy query to avoid conflicts.  preferred_time (ISO string) sets the
    search start; defaults to now.
    """
    try:
        service = _get_service(account_id)

        now = datetime.now(timezone.utc)
        search_start = datetime.fromisoformat(preferred_time.replace("Z", "+00:00")) if preferred_time else now
        search_end = search_start + timedelta(days=7)

        freebusy_body = {
            "timeMin": search_start.isoformat(),
            "timeMax": search_end.isoformat(),
            "items": [{"id": "primary"}],
        }
        fb_result = service.freebusy().query(body=freebusy_body).execute()
        busy_slots = fb_result.get("calendars", {}).get("primary", {}).get("busy", [])

        # Convert busy periods to (start, end) datetime tuples
        busy_ranges = []
        for slot in busy_slots:
            b_start = datetime.fromisoformat(slot["start"].replace("Z", "+00:00"))
            b_end = datetime.fromisoformat(slot["end"].replace("Z", "+00:00"))
            busy_ranges.append((b_start, b_end))

        # Walk forward in duration_minutes increments to find a free slot
        slot_start = search_start
        meeting_duration = timedelta(minutes=duration_minutes)
        found_start = None
        found_end = None

        while slot_start < search_end:
            slot_end = slot_start + meeting_duration
            conflict = any(not (slot_end <= b[0] or slot_start >= b[1]) for b in busy_ranges)
            if not conflict:
                found_start = slot_start
                found_end = slot_end
                break
            slot_start += timedelta(minutes=30)

        if not found_start:
            raise RuntimeError("No available slot found in the next 7 days")

        result = create_event(
            account_id,
            summary=summary,
            start=found_start.isoformat(),
            end=found_end.isoformat(),
            attendees=attendee_emails,
        )
        logger.info(
            "Scheduled meeting '%s' at %s for account %s",
            summary,
            found_start,
            account_id,
        )
        return {
            "event_id": result["event_id"],
            "html_link": result["html_link"],
            "start": found_start.isoformat(),
            "end": found_end.isoformat(),
        }
    except Exception as exc:
        logger.error("schedule_meeting failed for account %s: %s", account_id, exc)
        raise
