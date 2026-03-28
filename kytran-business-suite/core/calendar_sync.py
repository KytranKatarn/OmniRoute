"""Google Calendar sync service for appointments.

Syncs KBS appointments to Google Calendar events using the
Google Calendar API. Requires google-api-python-client (already installed).

Usage:
    from core.calendar_sync import CalendarSyncService
    svc = CalendarSyncService(credentials_json={...})
    event = svc.create_event(calendar_id="primary", summary="Haircut", ...)
"""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Lazy import to avoid hard dependency
_google_service = None


def _build_service(credentials):
    """Build a Google Calendar API service client.

    Args:
        credentials: Google OAuth2 credentials object.

    Returns:
        Google Calendar API service resource.
    """
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=credentials)


class CalendarSyncService:
    """Sync appointments with Google Calendar.

    Args:
        credentials: Google OAuth2 credentials object, or None for testing.
        service: Optional pre-built service (for testing/mocking).
    """

    def __init__(self, credentials=None, service=None):
        if service:
            self._service = service
        elif credentials:
            self._service = _build_service(credentials)
        else:
            self._service = None

    def _ensure_service(self):
        if not self._service:
            raise RuntimeError(
                "Google Calendar service not initialized. "
                "Provide credentials or a service object."
            )
        return self._service

    def create_event(
        self,
        calendar_id,
        summary,
        start_time,
        end_time,
        description=None,
        location=None,
        attendee_email=None,
        timezone="America/Toronto",
    ):
        """Create a calendar event.

        Args:
            calendar_id: Google Calendar ID (e.g. "primary").
            summary: Event title.
            start_time: Start as ISO string or datetime.
            end_time: End as ISO string or datetime.
            description: Optional event description.
            location: Optional location string.
            attendee_email: Optional attendee email to invite.
            timezone: Timezone for the event (default America/Toronto).

        Returns:
            Dict with created event data from Google.
        """
        svc = self._ensure_service()

        if isinstance(start_time, datetime):
            start_time = start_time.isoformat()
        if isinstance(end_time, datetime):
            end_time = end_time.isoformat()

        event_body = {
            "summary": summary,
            "start": {"dateTime": start_time, "timeZone": timezone},
            "end": {"dateTime": end_time, "timeZone": timezone},
        }

        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location
        if attendee_email:
            event_body["attendees"] = [{"email": attendee_email}]

        result = (
            svc.events()
            .insert(calendarId=calendar_id, body=event_body, sendUpdates="all")
            .execute()
        )

        logger.info("Created Google Calendar event: %s", result.get("id"))
        return result

    def update_event(
        self,
        calendar_id,
        event_id,
        summary=None,
        start_time=None,
        end_time=None,
        description=None,
        location=None,
        timezone="America/Toronto",
    ):
        """Update an existing calendar event.

        Args:
            calendar_id: Google Calendar ID.
            event_id: Google event ID to update.
            summary: Optional new title.
            start_time: Optional new start time.
            end_time: Optional new end time.
            description: Optional new description.
            location: Optional new location.
            timezone: Timezone.

        Returns:
            Dict with updated event data.
        """
        svc = self._ensure_service()

        # Fetch existing event
        existing = svc.events().get(calendarId=calendar_id, eventId=event_id).execute()

        if summary:
            existing["summary"] = summary
        if start_time:
            if isinstance(start_time, datetime):
                start_time = start_time.isoformat()
            existing["start"] = {"dateTime": start_time, "timeZone": timezone}
        if end_time:
            if isinstance(end_time, datetime):
                end_time = end_time.isoformat()
            existing["end"] = {"dateTime": end_time, "timeZone": timezone}
        if description is not None:
            existing["description"] = description
        if location is not None:
            existing["location"] = location

        result = (
            svc.events()
            .update(calendarId=calendar_id, eventId=event_id, body=existing)
            .execute()
        )

        logger.info("Updated Google Calendar event: %s", event_id)
        return result

    def delete_event(self, calendar_id, event_id):
        """Delete a calendar event.

        Args:
            calendar_id: Google Calendar ID.
            event_id: Google event ID to delete.
        """
        svc = self._ensure_service()
        svc.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        logger.info("Deleted Google Calendar event: %s", event_id)

    def list_events(self, calendar_id, time_min=None, time_max=None, max_results=50):
        """List upcoming events from a calendar.

        Args:
            calendar_id: Google Calendar ID.
            time_min: Optional start time filter (ISO string or datetime).
            time_max: Optional end time filter.
            max_results: Max events to return.

        Returns:
            List of event dicts.
        """
        svc = self._ensure_service()

        if time_min is None:
            time_min = datetime.now(tz=__import__("datetime").timezone.utc).isoformat()
        elif isinstance(time_min, datetime):
            time_min = time_min.isoformat() + "Z"

        params = {
            "calendarId": calendar_id,
            "timeMin": time_min,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if time_max:
            if isinstance(time_max, datetime):
                time_max = time_max.isoformat() + "Z"
            params["timeMax"] = time_max

        result = svc.events().list(**params).execute()
        return result.get("items", [])

    def sync_appointment(
        self,
        calendar_id,
        appointment_data,
        google_event_id=None,
    ):
        """Sync a KBS appointment to Google Calendar.

        Creates a new event or updates an existing one.

        Args:
            calendar_id: Google Calendar ID.
            appointment_data: Dict with appointment fields:
                - service_name: str
                - appointment_date: str (YYYY-MM-DD)
                - appointment_time: str (HH:MM)
                - duration_minutes: int
                - customer_name: str (optional)
                - customer_email: str (optional)
                - notes: str (optional)
                - location: str (optional)
            google_event_id: If set, update existing event.

        Returns:
            Dict with Google event ID and link.
        """
        summary = appointment_data.get("service_name", "Appointment")
        date = appointment_data.get("appointment_date", "")
        time_str = appointment_data.get("appointment_time", "00:00")
        duration = appointment_data.get("duration_minutes", 60)

        start_dt = datetime.fromisoformat(f"{date}T{time_str}:00")
        end_dt = start_dt + timedelta(minutes=duration)

        description_parts = []
        if appointment_data.get("customer_name"):
            description_parts.append(f"Customer: {appointment_data['customer_name']}")
        if appointment_data.get("notes"):
            description_parts.append(f"Notes: {appointment_data['notes']}")
        description = "\n".join(description_parts) if description_parts else None

        if google_event_id:
            event = self.update_event(
                calendar_id=calendar_id,
                event_id=google_event_id,
                summary=summary,
                start_time=start_dt,
                end_time=end_dt,
                description=description,
                location=appointment_data.get("location"),
            )
        else:
            event = self.create_event(
                calendar_id=calendar_id,
                summary=summary,
                start_time=start_dt,
                end_time=end_dt,
                description=description,
                location=appointment_data.get("location"),
                attendee_email=appointment_data.get("customer_email"),
            )

        return {
            "google_event_id": event.get("id"),
            "html_link": event.get("htmlLink"),
        }
