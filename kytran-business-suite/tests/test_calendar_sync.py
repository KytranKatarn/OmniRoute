"""Tests for Google Calendar sync service -- all API calls mocked."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_service():
    """Mock Google Calendar API service."""
    svc = MagicMock()
    return svc


@pytest.fixture
def sync_service(mock_service):
    from core.calendar_sync import CalendarSyncService

    return CalendarSyncService(service=mock_service)


def test_create_event(sync_service, mock_service):
    mock_service.events().insert().execute.return_value = {
        "id": "evt-1",
        "htmlLink": "https://calendar.google.com/event?id=evt-1",
        "summary": "Haircut",
    }

    result = sync_service.create_event(
        calendar_id="primary",
        summary="Haircut",
        start_time="2026-03-28T10:00:00",
        end_time="2026-03-28T11:00:00",
        description="Regular haircut",
        location="123 Main St",
        attendee_email="jane@test.com",
    )

    assert result["id"] == "evt-1"
    assert "calendar.google.com" in result["htmlLink"]


def test_create_event_with_datetime(sync_service, mock_service):
    mock_service.events().insert().execute.return_value = {
        "id": "evt-2",
        "summary": "Consultation",
    }

    result = sync_service.create_event(
        calendar_id="primary",
        summary="Consultation",
        start_time=datetime(2026, 3, 28, 10, 0),
        end_time=datetime(2026, 3, 28, 11, 0),
    )

    assert result["id"] == "evt-2"


def test_create_event_minimal(sync_service, mock_service):
    mock_service.events().insert().execute.return_value = {"id": "evt-3"}

    result = sync_service.create_event(
        calendar_id="primary",
        summary="Quick meeting",
        start_time="2026-03-28T10:00:00",
        end_time="2026-03-28T10:30:00",
    )

    assert result["id"] == "evt-3"


def test_update_event(sync_service, mock_service):
    mock_service.events().get().execute.return_value = {
        "id": "evt-1",
        "summary": "Old Title",
        "start": {"dateTime": "2026-03-28T10:00:00"},
        "end": {"dateTime": "2026-03-28T11:00:00"},
    }
    mock_service.events().update().execute.return_value = {
        "id": "evt-1",
        "summary": "New Title",
    }

    result = sync_service.update_event(
        calendar_id="primary",
        event_id="evt-1",
        summary="New Title",
    )

    assert result["summary"] == "New Title"


def test_delete_event(sync_service, mock_service):
    mock_service.events().delete().execute.return_value = None

    # Should not raise
    sync_service.delete_event(calendar_id="primary", event_id="evt-1")
    mock_service.events().delete.assert_called()


def test_list_events(sync_service, mock_service):
    mock_service.events().list().execute.return_value = {
        "items": [
            {"id": "evt-1", "summary": "Event 1"},
            {"id": "evt-2", "summary": "Event 2"},
        ]
    }

    events = sync_service.list_events(calendar_id="primary", max_results=10)

    assert len(events) == 2
    assert events[0]["id"] == "evt-1"


def test_list_events_empty(sync_service, mock_service):
    mock_service.events().list().execute.return_value = {"items": []}

    events = sync_service.list_events(calendar_id="primary")
    assert events == []


def test_sync_appointment_new(sync_service, mock_service):
    mock_service.events().insert().execute.return_value = {
        "id": "evt-new",
        "htmlLink": "https://calendar.google.com/event?id=evt-new",
    }

    result = sync_service.sync_appointment(
        calendar_id="primary",
        appointment_data={
            "service_name": "Haircut",
            "appointment_date": "2026-03-28",
            "appointment_time": "10:00",
            "duration_minutes": 60,
            "customer_name": "Jane Doe",
            "customer_email": "jane@test.com",
            "notes": "Regular customer",
            "location": "123 Main St",
        },
    )

    assert result["google_event_id"] == "evt-new"
    assert "calendar.google.com" in result["html_link"]


def test_sync_appointment_update(sync_service, mock_service):
    mock_service.events().get().execute.return_value = {
        "id": "evt-existing",
        "summary": "Old Service",
        "start": {"dateTime": "2026-03-27T10:00:00"},
        "end": {"dateTime": "2026-03-27T11:00:00"},
    }
    mock_service.events().update().execute.return_value = {
        "id": "evt-existing",
        "htmlLink": "https://calendar.google.com/event?id=evt-existing",
    }

    result = sync_service.sync_appointment(
        calendar_id="primary",
        appointment_data={
            "service_name": "Updated Service",
            "appointment_date": "2026-03-29",
            "appointment_time": "14:00",
            "duration_minutes": 30,
        },
        google_event_id="evt-existing",
    )

    assert result["google_event_id"] == "evt-existing"


def test_no_service_raises():
    from core.calendar_sync import CalendarSyncService

    svc = CalendarSyncService()
    with pytest.raises(RuntimeError, match="not initialized"):
        svc.create_event(
            calendar_id="primary",
            summary="Test",
            start_time="2026-03-28T10:00:00",
            end_time="2026-03-28T11:00:00",
        )
