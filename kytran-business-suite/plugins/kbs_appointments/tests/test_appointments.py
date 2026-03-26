"""Tests for the Appointments plugin — types, availability, booking, stats."""

import json
import os

import pytest

os.environ.setdefault("KBS_DB_HOST", "192.168.1.200")
os.environ.setdefault("KBS_DB_NAME", "archie")
os.environ.setdefault("KBS_DB_USER", "archie")
os.environ.setdefault("KBS_DB_PASSWORD", os.getenv("DB_PASSWORD", ""))

from core.database import (
    create_tenant_schema,
    drop_tenant_schema,
    get_db_cursor,
    run_migration_file,
    set_tenant_search_path,
)

# Use a test tenant ID in the 9xxx range to avoid collisions
TEST_TENANT_ID = 9902
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_EMAIL = "appttest@example.com"
TEST_PASSWORD = "TestPass123!"

CRM_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "kbs_crm", "migrations", "001_crm_tables.sql"
)
APPT_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "migrations", "001_appointments_tables.sql"
)


@pytest.fixture(scope="module")
def appt_app():
    """Create the Flask app with CRM + Appointments plugins loaded."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture(scope="module")
def appt_setup(appt_app):
    """Create test tenant, user, schema, CRM + Appointments tables, enable both modules.

    Yields the tenant_id. Cleans up afterwards.
    """
    from werkzeug.security import generate_password_hash

    pw_hash = generate_password_hash(TEST_PASSWORD)

    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        # Clean up any leftovers from a previous failed run
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))

        # Create user
        cur.execute(
            """
            INSERT INTO users (email, username, password_hash, is_active)
            VALUES (%s, 'Appt Tester', %s, TRUE)
            RETURNING id
            """,
            (TEST_EMAIL, pw_hash),
        )
        user_id = cur.fetchone()["id"]

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Appt Test Tenant', 'appt-test-tenant', 'business', TRUE)
            """,
            (TEST_TENANT_ID,),
        )

        # Link user to tenant
        cur.execute(
            "INSERT INTO tenant_users (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (TEST_TENANT_ID, user_id),
        )

        # Enable CRM module (dependency)
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'crm', TRUE)
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (TEST_TENANT_ID,),
        )

        # Enable Appointments module
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'appointments', TRUE)
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (TEST_TENANT_ID,),
        )

    # Create tenant schema and run both migrations (CRM first — appointments FK depends on it)
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(CRM_MIGRATION_PATH, schema=TEST_SCHEMA)
    run_migration_file(APPT_MIGRATION_PATH, schema=TEST_SCHEMA)

    yield {"tenant_id": TEST_TENANT_ID, "user_id": user_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM tenant_users WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))
        cur.execute("DELETE FROM users WHERE email = %s", (TEST_EMAIL,))


@pytest.fixture()
def authed_client(appt_app, appt_setup):
    """Yield a test client that is logged in and has the tenant session set."""
    with appt_app.test_client() as client:
        resp = client.post(
            "/auth/login",
            data={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200), f"Login failed: {resp.status_code}"
        yield client


# ======================================================================
# Tests
# ======================================================================


class TestAppointmentTypes:
    """Appointment type CRUD tests."""

    def test_create_type(self, authed_client):
        resp = authed_client.post(
            "/plugins/appointments/api/types",
            data=json.dumps({
                "name": "Initial Consultation",
                "description": "First meeting with client",
                "duration_minutes": 45,
                "price": 75.00,
                "color": "#8b5cf6",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "Initial Consultation"
        assert data["duration_minutes"] == 45
        assert data["id"] is not None

    def test_list_types(self, authed_client):
        # Ensure at least one type exists
        authed_client.post(
            "/plugins/appointments/api/types",
            data=json.dumps({"name": "Follow-Up Session", "duration_minutes": 30}),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/appointments/api/types")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "types" in data
        names = [t["name"] for t in data["types"]]
        assert "Follow-Up Session" in names


class TestAvailabilitySlots:
    """Availability slot tests."""

    def test_create_availability_slot(self, authed_client):
        resp = authed_client.post(
            "/plugins/appointments/api/availability",
            data=json.dumps({
                "day_of_week": 1,
                "start_time": "09:00",
                "end_time": "17:00",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["day_of_week"] == 1
        assert data["id"] is not None

    def test_list_availability_slots(self, authed_client):
        resp = authed_client.get("/plugins/appointments/api/availability")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "slots" in data
        assert len(data["slots"]) >= 1


class TestAppointmentBooking:
    """Appointment booking and lifecycle tests."""

    def _create_type(self, authed_client):
        """Helper — create a type and return its id."""
        resp = authed_client.post(
            "/plugins/appointments/api/types",
            data=json.dumps({"name": "Test Service", "duration_minutes": 60}),
            content_type="application/json",
        )
        assert resp.status_code == 201
        return resp.get_json()["id"]

    def test_book_appointment(self, authed_client):
        type_id = self._create_type(authed_client)
        resp = authed_client.post(
            "/plugins/appointments/api/appointments",
            data=json.dumps({
                "title": "Meeting with Alex",
                "start_time": "2026-04-01T10:00:00",
                "appointment_type_id": type_id,
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["title"] == "Meeting with Alex"
        assert data["status"] == "scheduled"
        assert data["end_time"] is not None
        assert data["id"] is not None

    def test_list_appointments(self, authed_client):
        type_id = self._create_type(authed_client)
        authed_client.post(
            "/plugins/appointments/api/appointments",
            data=json.dumps({
                "title": "List Test Appointment",
                "start_time": "2026-04-02T14:00:00",
                "appointment_type_id": type_id,
            }),
            content_type="application/json",
        )
        resp = authed_client.get("/plugins/appointments/api/appointments")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "appointments" in data
        assert len(data["appointments"]) >= 1
        titles = [a["title"] for a in data["appointments"]]
        assert "List Test Appointment" in titles

    def test_cancel_appointment(self, authed_client):
        type_id = self._create_type(authed_client)
        create_resp = authed_client.post(
            "/plugins/appointments/api/appointments",
            data=json.dumps({
                "title": "Cancel Me",
                "start_time": "2026-04-03T09:00:00",
                "appointment_type_id": type_id,
            }),
            content_type="application/json",
        )
        appt_id = create_resp.get_json()["id"]

        resp = authed_client.post(f"/plugins/appointments/api/appointments/{appt_id}/cancel")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "cancelled"

    def test_complete_appointment(self, authed_client):
        type_id = self._create_type(authed_client)
        create_resp = authed_client.post(
            "/plugins/appointments/api/appointments",
            data=json.dumps({
                "title": "Complete Me",
                "start_time": "2026-03-01T10:00:00",
                "appointment_type_id": type_id,
            }),
            content_type="application/json",
        )
        appt_id = create_resp.get_json()["id"]

        resp = authed_client.post(f"/plugins/appointments/api/appointments/{appt_id}/complete")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "completed"


class TestAppointmentStats:
    """Stats endpoint tests."""

    def test_stats(self, authed_client):
        resp = authed_client.get("/plugins/appointments/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_appointments" in data
        assert "upcoming_count" in data
        assert "completed_this_month" in data
        assert "cancellation_rate" in data
