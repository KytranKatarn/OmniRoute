"""Tests for public booking page — no login required, tenant by slug."""

import json
import os

import pytest

os.environ["KBS_DB_HOST"] = "kbs-postgres"
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

TEST_TENANT_ID = 9903
TEST_SCHEMA = f"tenant_{TEST_TENANT_ID}"
TEST_SLUG = "public-booking-test"

CRM_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "kbs_crm",
    "migrations",
    "001_crm_tables.sql",
)
APPT_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "kbs_appointments",
    "migrations",
    "001_appointments_tables.sql",
)


@pytest.fixture(scope="module")
def public_app():
    """Create the Flask app with the public booking blueprint registered."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False

    # Register public booking blueprint at root
    from plugins.kbs_appointments import create_public_blueprint

    public_bp = create_public_blueprint()
    application.register_blueprint(public_bp)

    return application


@pytest.fixture(scope="module")
def public_setup(public_app):
    """Create test tenant, schema, and tables for public booking tests."""
    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        # Cleanup leftovers
        cur.execute(
            "DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,)
        )
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (id, name, slug, tier, is_active)
            VALUES (%s, 'Public Booking Test Biz', %s, 'business', TRUE)
            """,
            (TEST_TENANT_ID, TEST_SLUG),
        )

        # Enable appointments module
        cur.execute(
            """
            INSERT INTO tenant_modules (tenant_id, module_slug, enabled)
            VALUES (%s, 'appointments', TRUE)
            ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = TRUE
            """,
            (TEST_TENANT_ID,),
        )

    # Create schema and run migrations
    create_tenant_schema(TEST_TENANT_ID)
    run_migration_file(CRM_MIGRATION_PATH, schema=TEST_SCHEMA)
    run_migration_file(APPT_MIGRATION_PATH, schema=TEST_SCHEMA)

    # Seed a service type and availability
    with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
        set_tenant_search_path(cur, TEST_TENANT_ID)
        cur.execute(
            """
            INSERT INTO appointment_types (name, description, duration_minutes, price, is_active)
            VALUES ('Test Consultation', 'A test service', 30, 50.00, TRUE)
            RETURNING id
            """
        )
        type_id = cur.fetchone()["id"]

        # Add availability for all weekdays (Monday-Friday, 09:00-17:00)
        for dow in range(0, 5):
            cur.execute(
                """
                INSERT INTO availability_slots (day_of_week, start_time, end_time, is_active)
                VALUES (%s, '09:00', '17:00', TRUE)
                """,
                (dow,),
            )

    yield {"tenant_id": TEST_TENANT_ID, "slug": TEST_SLUG, "type_id": type_id}

    # Cleanup
    drop_tenant_schema(TEST_TENANT_ID)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM tenant_modules WHERE tenant_id = %s", (TEST_TENANT_ID,)
        )
        cur.execute("DELETE FROM tenants WHERE id = %s", (TEST_TENANT_ID,))


@pytest.fixture()
def client(public_app, public_setup):
    """Yield a plain (unauthenticated) test client."""
    with public_app.test_client() as c:
        yield c


# ======================================================================
# Tests
# ======================================================================


class TestPublicBookingPage:
    """Tests for the public booking page rendering."""

    def test_booking_page_renders(self, client, public_setup):
        resp = client.get(f"/{public_setup['slug']}")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Public Booking Test Biz" in html
        assert "Test Consultation" in html

    def test_booking_page_404_for_unknown_slug(self, client):
        resp = client.get("/nonexistent-slug-12345")
        assert resp.status_code == 404


class TestAvailableSlots:
    """Tests for the available time slots API."""

    def test_get_available_slots(self, client, public_setup):
        # Pick a future Monday (day_of_week=0)
        from datetime import date, timedelta

        today = date.today()
        days_until_monday = (0 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_monday = today + timedelta(days=days_until_monday)

        resp = client.get(
            f"/{public_setup['slug']}/api/slots"
            f"?date={next_monday.isoformat()}&type_id={public_setup['type_id']}"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "slots" in data
        # 30-min service in 9:00-17:00 window should produce multiple slots
        assert len(data["slots"]) >= 1

    def test_get_slots_missing_params(self, client, public_setup):
        resp = client.get(f"/{public_setup['slug']}/api/slots")
        assert resp.status_code == 400

    def test_get_slots_invalid_date(self, client, public_setup):
        resp = client.get(
            f"/{public_setup['slug']}/api/slots?date=not-a-date&type_id={public_setup['type_id']}"
        )
        assert resp.status_code == 400


class TestPublicBooking:
    """Tests for the public booking POST endpoint."""

    def _future_monday(self):
        from datetime import date, timedelta

        today = date.today()
        days_until_monday = (0 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        return today + timedelta(days=days_until_monday)

    def test_book_appointment_success(self, client, public_setup):
        monday = self._future_monday()
        resp = client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps(
                {
                    "customer_name": "Test User",
                    "customer_email": "testuser@example.com",
                    "appointment_type_id": public_setup["type_id"],
                    "date": monday.isoformat(),
                    "time": "10:00",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "confirmed"
        assert "appointment_id" in data
        assert (
            "confirmation" in data["message"].lower()
            or "booked" in data["message"].lower()
        )

    def test_book_appointment_creates_crm_customer(self, client, public_setup):
        monday = self._future_monday()
        resp = client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps(
                {
                    "customer_name": "New Lead",
                    "customer_email": "newlead@example.com",
                    "customer_phone": "555-1234",
                    "appointment_type_id": public_setup["type_id"],
                    "date": monday.isoformat(),
                    "time": "14:00",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 201

        # Verify CRM customer was created
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, public_setup["tenant_id"])
            cur.execute(
                "SELECT name, email, source FROM crm_customers WHERE email = 'newlead@example.com'"
            )
            customer = cur.fetchone()
            assert customer is not None
            assert customer["name"] == "New Lead"
            assert customer["source"] == "booking_page"

    def test_book_appointment_missing_fields(self, client, public_setup):
        resp = client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps({"customer_name": "Incomplete"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_book_appointment_conflict(self, client, public_setup):
        monday = self._future_monday()
        # Book the 11:00 slot
        client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps(
                {
                    "customer_name": "First Booker",
                    "customer_email": "first@example.com",
                    "appointment_type_id": public_setup["type_id"],
                    "date": monday.isoformat(),
                    "time": "11:00",
                }
            ),
            content_type="application/json",
        )
        # Try to book the same 11:00 slot again
        resp = client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps(
                {
                    "customer_name": "Second Booker",
                    "customer_email": "second@example.com",
                    "appointment_type_id": public_setup["type_id"],
                    "date": monday.isoformat(),
                    "time": "11:00",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 409

    def test_book_appointment_unknown_slug(self, client):
        resp = client.post(
            "/fake-slug-xyz/book",
            data=json.dumps(
                {
                    "customer_name": "Nobody",
                    "customer_email": "nobody@example.com",
                    "appointment_type_id": 1,
                    "date": "2026-04-07",
                    "time": "10:00",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 404


class TestCancelByToken:
    """Tests for the public cancel-by-token endpoint."""

    def test_cancel_by_token(self, client, public_setup):
        from datetime import date, timedelta

        monday = date.today() + timedelta(
            days=(0 - date.today().weekday()) % 7 or 7
        )

        # Book an appointment
        book_resp = client.post(
            f"/{public_setup['slug']}/book",
            data=json.dumps(
                {
                    "customer_name": "Cancel Tester",
                    "customer_email": "cancel@example.com",
                    "appointment_type_id": public_setup["type_id"],
                    "date": monday.isoformat(),
                    "time": "15:00",
                }
            ),
            content_type="application/json",
        )
        assert book_resp.status_code == 201
        appt_id = book_resp.get_json()["appointment_id"]

        # Get the cancel token from the DB
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, public_setup["tenant_id"])
            cur.execute(
                "SELECT metadata->>'cancel_token' AS token FROM appointments WHERE id = %s",
                (appt_id,),
            )
            token = cur.fetchone()["token"]

        # Cancel via POST
        resp = client.post(
            f"/{public_setup['slug']}/cancel",
            data=json.dumps({"token": token}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["cancelled"] is True

    def test_cancel_invalid_token(self, client, public_setup):
        resp = client.post(
            f"/{public_setup['slug']}/cancel",
            data=json.dumps({"token": "invalid-token-value"}),
            content_type="application/json",
        )
        assert resp.status_code == 404
