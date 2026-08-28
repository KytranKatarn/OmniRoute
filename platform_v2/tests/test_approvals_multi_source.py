"""Tests for multi-source approval helpers and endpoint routing.

Strategy:
  - Five unit tests exercise the per-source helper functions
    (_approve_autonomy, _approve_contractor, _approve_bridge) directly
    against the real DB — fast, isolated, no HTTP overhead.
  - One HTTP-level test uses a minimal Flask app that mounts only the
    approvals blueprint (bypassing the full-app circular-import issue
    caused by oauth_routes.py → `from app import User`).  This test
    proves the route guard itself rejects unknown prefixes — if the guard
    were removed, no unit test would catch it.
"""

import os
import sys
import pytest
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone


def _get_db_password():
    try:
        return open("/run/secrets/db_password").read().strip()
    except FileNotFoundError:
        return os.environ.get("DB_PASSWORD", "")


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "archie_database"),
        dbname=os.environ.get("DB_NAME", "archie"),
        user=os.environ.get("DB_USER", "archie"),
        password=_get_db_password(),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module", autouse=True)
def import_helpers():
    """Make the approvals_routes helpers importable by adding /app to sys.path."""
    app_path = "/app"
    if app_path not in sys.path:
        sys.path.insert(0, app_path)


def _get_helpers():
    """Import helpers from approvals_routes after path is set."""
    from tools.department_hq.approvals_routes import (
        _approve_autonomy,
        _approve_contractor,
        _approve_bridge,
    )

    return _approve_autonomy, _approve_contractor, _approve_bridge


def _seed_autonomy(db, action_type="test_action"):
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO autonomy_approval_queue
               (action_type, action_data, tier, status, priority, requested_by, reason)
               VALUES (%s, '{}'::jsonb, 2, 'pending', 5, 'test', 'test reason')
               RETURNING id""",
            (action_type,),
        )
        return cur.fetchone()["id"]


def _seed_contractor(db):
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO contractor_approval_requests
               (agent_id, task_type, task_description, status, priority,
                contractor_provider, contractor_model, estimated_cost, estimated_tokens)
               VALUES (NULL, 'test_task', 'test desc', 'pending', 'normal',
                       'openai', 'gpt-4o-mini', 0.02, 1000)
               RETURNING id"""
        )
        return cur.fetchone()["id"]


def _seed_bridge(db):
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO bridge_jobs
               (job_type, module_source, description, status, agent_name,
                total_steps, completed_steps)
               VALUES ('test', 'test_module', 'test desc', 'pending_approval',
                       'test_agent', 1, 0)
               RETURNING id"""
        )
        return cur.fetchone()["id"]


def _cleanup(db, table, row_id):
    with db.cursor() as cur:
        cur.execute(f"DELETE FROM {table} WHERE id=%s", (row_id,))


TEST_USER_ID = 2  # Kytran admin user — must exist in users table


# ---------------------------------------------------------------------------
# Minimal Flask client for HTTP-level tests
#
# The full ARCHIE app cannot be imported in tests because oauth_routes.py
# does `from app import User` and /app/__init__.py (package init) shadows
# app.py, creating an unresolvable circular import.  Instead we mount only
# the approvals blueprint on a bare Flask app — enough to exercise the
# route guard without pulling in the rest of the platform.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def approvals_client():
    """Minimal Flask test client with only the approvals blueprint mounted."""
    from flask import Flask, Blueprint
    from flask_login import LoginManager, UserMixin

    mini_app = Flask(__name__)
    mini_app.config["SECRET_KEY"] = "test-secret"
    mini_app.config["TESTING"] = True
    mini_app.config["WTF_CSRF_ENABLED"] = False

    login_manager = LoginManager(mini_app)

    class _User(UserMixin):
        def __init__(self, uid):
            self.id = uid

    @login_manager.user_loader
    def load_user(uid):
        return _User(int(uid))

    bp = Blueprint("department_hq", __name__, url_prefix="/tools/department-hq")

    # admin_required is a no-op in the test environment — we are only
    # verifying that the route guard (prefix validation) fires, not auth.
    def _no_op_admin_required(f):
        return f

    from tools.department_hq.approvals_routes import register_approvals_routes

    register_approvals_routes(bp, _no_op_admin_required)
    mini_app.register_blueprint(bp)

    return mini_app.test_client()


def _login_as_admin(client, user_id=TEST_USER_ID):
    """Inject a Flask-Login session for a known admin user."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


class TestApprove:
    def test_approve_autonomy_ok(self, db):
        _approve_autonomy, _, _ = _get_helpers()
        row_id = _seed_autonomy(db)
        try:
            ok, action_type = _approve_autonomy(row_id, TEST_USER_ID)
            assert ok is True
            assert action_type == "test_action"
            with db.cursor() as cur:
                cur.execute(
                    "SELECT status, approved_by FROM autonomy_approval_queue WHERE id=%s",
                    (row_id,),
                )
                row = cur.fetchone()
            assert row["status"] == "approved"
            assert row["approved_by"] == TEST_USER_ID
        finally:
            _cleanup(db, "autonomy_approval_queue", row_id)

    def test_approve_contractor_sets_14d_expiry(self, db):
        _, _approve_contractor, _ = _get_helpers()
        row_id = _seed_contractor(db)
        try:
            ok, task_type = _approve_contractor(row_id, TEST_USER_ID)
            assert ok is True
            assert task_type == "test_task"
            with db.cursor() as cur:
                cur.execute(
                    "SELECT status, approved_by, expires_at FROM contractor_approval_requests WHERE id=%s",
                    (row_id,),
                )
                row = cur.fetchone()
            assert row["status"] == "approved"
            assert row["approved_by"] == TEST_USER_ID
            # contractor_approval_requests.expires_at is `timestamp WITHOUT time zone`
            # (so is created_at), so psycopg2 hands back a NAIVE datetime. The old code
            # stripped tzinfo from the DB value — a no-op — and left `expected` AWARE, so
            # the subtraction raised:
            #     TypeError: can't subtract offset-naive and offset-aware datetimes
            # Compare naive-to-naive, and strip on the side that is actually aware.
            #
            # ⚠️ This is a THIRD table deviating from the platform's TIMESTAMPTZ convention;
            # .claude/rules/database.md already names agent_emotional_state.timestamp and
            # agent_learning_records.learned_at. Check the column type before assuming.
            expected = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=14)
            assert abs((row["expires_at"] - expected).total_seconds()) < 3600
        finally:
            _cleanup(db, "contractor_approval_requests", row_id)

    def test_approve_bridge_flips_status(self, db):
        _, _, _approve_bridge = _get_helpers()
        row_id = _seed_bridge(db)
        try:
            ok, job_type = _approve_bridge(row_id, TEST_USER_ID)
            assert ok is True
            assert job_type == "test"
            with db.cursor() as cur:
                cur.execute(
                    "SELECT status, approved_by FROM bridge_jobs WHERE id=%s",
                    (row_id,),
                )
                row = cur.fetchone()
            assert row["status"] == "approved"
            assert row["approved_by"] == TEST_USER_ID
        finally:
            _cleanup(db, "bridge_jobs", row_id)

    def test_approve_invalid_prefix_returns_400_via_http(self, approvals_client):
        """HTTP-level: route guard returns 400 for unknown prefix.

        This is the only test that actually exercises the Flask route.
        If the prefix-validation guard in approvals_approve() is removed,
        this test will catch it — the unit tests above cannot.
        """
        _login_as_admin(approvals_client)
        resp = approvals_client.post("/tools/department-hq/api/approvals/junk:123/approve")
        assert resp.status_code == 400
        assert resp.is_json
        assert resp.json["success"] is False

    def test_approve_already_processed_404(self, db):
        _approve_autonomy, _, _ = _get_helpers()
        row_id = _seed_autonomy(db)
        try:
            ok1, _ = _approve_autonomy(row_id, TEST_USER_ID)
            assert ok1 is True
            # Second call — row is now 'approved', not 'pending' → should return False
            ok2, _ = _approve_autonomy(row_id, TEST_USER_ID)
            assert ok2 is False
        finally:
            _cleanup(db, "autonomy_approval_queue", row_id)


def _get_deny_helpers():
    """Import deny helpers from approvals_routes after path is set."""
    from tools.department_hq.approvals_routes import (
        _deny_autonomy,
        _deny_contractor,
        _deny_bridge,
    )

    return _deny_autonomy, _deny_contractor, _deny_bridge


class TestDeny:
    def test_deny_autonomy_records_reason(self, db):
        _deny_autonomy, _, _ = _get_deny_helpers()
        row_id = _seed_autonomy(db)
        try:
            ok = _deny_autonomy(row_id, TEST_USER_ID, "test denial reason")
            assert ok is True
            with db.cursor() as cur:
                cur.execute(
                    "SELECT status, approved_by, rejected_reason FROM autonomy_approval_queue WHERE id=%s",
                    (row_id,),
                )
                row = cur.fetchone()
            assert row["status"] == "rejected"
            assert row["approved_by"] == TEST_USER_ID
            assert row["rejected_reason"] == "test denial reason"
        finally:
            _cleanup(db, "autonomy_approval_queue", row_id)

    def test_deny_contractor_records_reason(self, db):
        _, _deny_contractor, _ = _get_deny_helpers()
        row_id = _seed_contractor(db)
        try:
            ok = _deny_contractor(row_id, TEST_USER_ID, "contractor denial reason")
            assert ok is True
            with db.cursor() as cur:
                cur.execute(
                    "SELECT status, denied_by, denial_reason FROM contractor_approval_requests WHERE id=%s",
                    (row_id,),
                )
                row = cur.fetchone()
            assert row["status"] == "denied"
            assert row["denied_by"] == TEST_USER_ID
            assert row["denial_reason"] == "contractor denial reason"
        finally:
            _cleanup(db, "contractor_approval_requests", row_id)

    def test_deny_bridge_cancels(self, db):
        _, _, _deny_bridge = _get_deny_helpers()
        row_id = _seed_bridge(db)
        try:
            ok = _deny_bridge(row_id, TEST_USER_ID, "bridge cancel reason")
            assert ok is True
            with db.cursor() as cur:
                cur.execute(
                    "SELECT status, cancelled_by, cancellation_reason FROM bridge_jobs WHERE id=%s",
                    (row_id,),
                )
                row = cur.fetchone()
            assert row["status"] == "cancelled"
            assert row["cancelled_by"] == TEST_USER_ID
            assert row["cancellation_reason"] == "bridge cancel reason"
        finally:
            _cleanup(db, "bridge_jobs", row_id)

    def test_deny_invalid_prefix_returns_400_via_http(self, approvals_client):
        """HTTP-level: route guard returns 400 for unknown prefix."""
        _login_as_admin(approvals_client)
        resp = approvals_client.post(
            "/tools/department-hq/api/approvals/junk:123/deny",
            json={"reason": "test"},
        )
        assert resp.status_code == 400
        assert resp.is_json
        assert resp.json["success"] is False


class TestPendingEscalationChain:
    def test_pending_includes_escalation_chain(self, db, approvals_client):
        """A real agent with department resolves to a non-null chain."""
        _login_as_admin(approvals_client)
        # Find a real agent with a resolvable department
        with db.cursor() as cur:
            cur.execute(
                "SELECT id, display_name FROM agents "
                "WHERE department IS NOT NULL AND display_name IS NOT NULL "
                "AND shift_state != 'decommissioned' LIMIT 1"
            )
            agent_row = cur.fetchone()
        if not agent_row:
            pytest.skip("No agent with department found")
        agent_id = agent_row["id"]
        display_name = agent_row["display_name"]

        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO contractor_approval_requests
                   (agent_id, task_type, task_description, status, priority,
                    contractor_provider, contractor_model, estimated_cost, estimated_tokens)
                   VALUES (%s, 'chain_test', 'chain test', 'pending', 'normal',
                           'openai', 'gpt-4o-mini', 0.01, 500)
                   RETURNING id""",
                (agent_id,),
            )
            row_id = cur.fetchone()["id"]

        try:
            resp = approvals_client.get("/tools/department-hq/api/approvals/pending")
            assert resp.status_code == 200
            body = resp.get_json()
            target = next((a for a in body["approvals"] if a["id"] == f"contractor:{row_id}"), None)
            assert target is not None, "Seeded row not returned in pending"
            chain = target.get("escalation_chain")
            assert chain is not None, f"Expected chain, got None for agent {display_name}"
            assert chain[0] == display_name
            assert chain[-1] == "A.R.C.H.I.E."
            assert len(chain) >= 2
        finally:
            _cleanup(db, "contractor_approval_requests", row_id)

    def test_pending_null_chain_when_agent_missing(self, db, approvals_client):
        """Row with agent_id=NULL → escalation_chain is null."""
        _login_as_admin(approvals_client)
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO contractor_approval_requests
                   (agent_id, task_type, task_description, status, priority,
                    contractor_provider, contractor_model, estimated_cost, estimated_tokens)
                   VALUES (NULL, 'chain_test_null', 'null agent', 'pending', 'normal',
                           'openai', 'gpt-4o-mini', 0.01, 500)
                   RETURNING id""",
            )
            row_id = cur.fetchone()["id"]
        try:
            resp = approvals_client.get("/tools/department-hq/api/approvals/pending")
            assert resp.status_code == 200
            body = resp.get_json()
            target = next((a for a in body["approvals"] if a["id"] == f"contractor:{row_id}"), None)
            assert target is not None
            assert target.get("escalation_chain") is None
        finally:
            _cleanup(db, "contractor_approval_requests", row_id)


class TestHistory:
    def test_history_unions_all_three_sources(self, db, approvals_client):
        """History endpoint returns rows from all 3 tables with source-prefixed IDs."""
        _login_as_admin(approvals_client)
        _approve_autonomy, _approve_contractor, _approve_bridge = _get_helpers()
        from tools.department_hq.approvals_routes import (
            _deny_contractor,
        )

        aut_id = _seed_autonomy(db)
        con_id = _seed_contractor(db)
        brd_id = _seed_bridge(db)

        # Resolve each via helpers (mixed approve/deny to cover both status branches).
        _approve_autonomy(aut_id, TEST_USER_ID)
        _deny_contractor(con_id, TEST_USER_ID, "too expensive")
        _approve_bridge(brd_id, TEST_USER_ID)

        try:
            resp = approvals_client.get("/tools/department-hq/api/approvals/history?limit=200")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["success"] is True
            history = body["history"]
            ids = {h["id"] for h in history}
            assert f"autonomy:{aut_id}" in ids
            assert f"contractor:{con_id}" in ids
            assert f"bridge:{brd_id}" in ids

            auto_row = next(h for h in history if h["id"] == f"autonomy:{aut_id}")
            con_row = next(h for h in history if h["id"] == f"contractor:{con_id}")
            brd_row = next(h for h in history if h["id"] == f"bridge:{brd_id}")

            assert auto_row["status"] == "approved"
            assert con_row["status"] == "denied"
            assert brd_row["status"] == "approved"
            for r in (auto_row, con_row, brd_row):
                assert r["decided_at"] is not None
                assert r["source"] in ("autonomy_approval_queue", "contractor_approval_requests", "bridge_jobs")
        finally:
            _cleanup(db, "autonomy_approval_queue", aut_id)
            _cleanup(db, "contractor_approval_requests", con_id)
            _cleanup(db, "bridge_jobs", brd_id)


class TestEscalationLogging:
    def test_escalation_logs_to_coms_feed(self, db):
        """send_escalation_notification inserts a telegram_message_log row so
        the DHQ COMs tab surfaces escalations."""
        import sys

        # ai_bridge modules use bare `from db import ...` — add ai_bridge to path.
        if "/mnt/archie_brain/ai_bridge" not in sys.path:
            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

        try:
            from ai_bridge.telegram_gateway import TelegramGateway
        except Exception as e:
            pytest.skip(f"telegram_gateway still not importable: {e}")

        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO telegram_users (telegram_id, is_authorized) "
                "VALUES (%s, TRUE) ON CONFLICT (telegram_id) DO NOTHING",
                (999_888,),
            )

        gw = TelegramGateway.__new__(TelegramGateway)
        gw._running = True

        class _FakeBot:
            @staticmethod
            async def send_message(chat_id, text, reply_markup):
                return type("M", (), {"message_id": 123})

        class _FakeApp:
            bot = _FakeBot()

        gw._application = _FakeApp()

        import asyncio
        import threading

        loop = asyncio.new_event_loop()
        gw._loop = loop

        # run_coroutine_threadsafe requires the loop to actually be running in a
        # background thread — otherwise the scheduled coroutine is never executed.
        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()

        approval_id = 99123456
        gw.send_escalation_notification(
            approval_id=approval_id,
            context={
                "agent_name": "TestAgent",
                "department": "ENGINEERING",
                "capability": "cap",
                "failure_count": 1,
                "original_model": "mA",
                "escalated_model": "mB",
                "est_cost": 0.02,
                "module_id": "mod",
                "recommendation": "Approve",
            },
        )
        import time

        time.sleep(2.0)
        loop.call_soon_threadsafe(loop.stop)

        with db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM telegram_message_log "
                "WHERE category = 'escalation' AND source_agent = 'TestAgent' "
                "AND message LIKE %s",
                (f"%{approval_id}%",),
            )
            count = cur.fetchone()["n"]
        assert count >= 1, f"Expected escalation row, got {count}"

        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM telegram_message_log WHERE source_agent='TestAgent' AND message LIKE %s",
                (f"%{approval_id}%",),
            )
            cur.execute("DELETE FROM telegram_users WHERE telegram_id=999888")


class TestEscalationUnifiedChat:
    def test_escalation_logs_to_unified_messages(self, db):
        """send_escalation_notification must also append to unified_messages under
        an 'A.R.C.H.I.E. Escalations' conversation for the linked user."""
        import sys

        if "/mnt/archie_brain/ai_bridge" not in sys.path:
            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        try:
            from ai_bridge.telegram_gateway import TelegramGateway
        except Exception as e:
            pytest.skip(f"telegram_gateway not importable: {e}")

        # Pick a telegram_id and link it to TEST_USER_ID=2 (Kytran admin).
        test_chat_id = 999_777
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO telegram_users (telegram_id, user_id, is_authorized) "
                "VALUES (%s, %s, TRUE) "
                "ON CONFLICT (telegram_id) DO UPDATE SET user_id=EXCLUDED.user_id, is_authorized=TRUE",
                (test_chat_id, TEST_USER_ID),
            )

        gw = TelegramGateway.__new__(TelegramGateway)
        gw._running = True

        class _FakeBot:
            @staticmethod
            async def send_message(chat_id, text, reply_markup):
                return type("M", (), {"message_id": 456})

        class _FakeApp:
            bot = _FakeBot()

        gw._application = _FakeApp()

        # Start event loop in background thread (per T7 pattern).
        import asyncio
        import threading

        gw._loop = asyncio.new_event_loop()
        loop_thread = threading.Thread(target=gw._loop.run_forever, daemon=True)
        loop_thread.start()

        approval_id = 99_234_567
        try:
            gw.send_escalation_notification(
                approval_id=approval_id,
                context={
                    "agent_name": "Pixel",
                    "department": "CREATIVE",
                    "capability": "image_generation",
                    "failure_count": 2,
                    "original_model": "sdxl",
                    "escalated_model": "gpt-image-1",
                    "est_cost": 0.08,
                    "module_id": "media_studio",
                    "recommendation": "Approve",
                },
            )
            import time

            time.sleep(2.0)

            with db.cursor() as cur:
                cur.execute(
                    """SELECT um.id, um.channel, um.direction, um.sender, um.content
                       FROM unified_messages um
                       JOIN unified_conversations uc ON uc.id = um.conversation_id
                       WHERE uc.user_id = %s
                         AND uc.topic = 'A.R.C.H.I.E. Escalations'
                         AND um.content LIKE %s
                       ORDER BY um.id DESC LIMIT 1""",
                    (TEST_USER_ID, f"%{approval_id}%"),
                )
                row = cur.fetchone()
            assert row is not None, "Expected unified_messages row for escalation"
            assert row["channel"] == "telegram"
            assert row["direction"] == "outbound"
            assert row["sender"] == "A.R.C.H.I.E."
            assert str(approval_id) in row["content"]
        finally:
            # Stop loop + cleanup
            gw._loop.call_soon_threadsafe(gw._loop.stop)
            with db.cursor() as cur:
                cur.execute(
                    "DELETE FROM unified_messages WHERE content LIKE %s",
                    (f"%{approval_id}%",),
                )
                cur.execute(
                    "DELETE FROM unified_conversations WHERE user_id=%s AND topic='A.R.C.H.I.E. Escalations'",
                    (TEST_USER_ID,),
                )
                cur.execute(
                    "DELETE FROM telegram_message_log WHERE message LIKE %s",
                    (f"%{approval_id}%",),
                )
                cur.execute("DELETE FROM telegram_users WHERE telegram_id=%s", (test_chat_id,))
