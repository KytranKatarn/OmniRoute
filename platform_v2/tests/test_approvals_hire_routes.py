"""Route tests for the hire: source in the unified approvals endpoint.

Strategy mirrors test_approvals_multi_source.py:
  - Direct psycopg2 ``db`` fixture for DB seeding/cleanup.
  - Minimal Flask ``approvals_client`` fixture (no full-app import).
  - _login_as_admin() injects a Flask-Login session.
"""

from __future__ import annotations

import os
import sys
import pytest
import psycopg2
import psycopg2.extras


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
    """Add /app to sys.path so approvals_routes is importable."""
    app_path = "/app"
    if app_path not in sys.path:
        sys.path.insert(0, app_path)


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

    def _no_op_admin_required(f):
        return f

    from tools.department_hq.approvals_routes import register_approvals_routes

    register_approvals_routes(bp, _no_op_admin_required)
    mini_app.register_blueprint(bp)

    return mini_app.test_client()


TEST_USER_ID = 2  # Kytran admin user — must exist in users table


def _login_as_admin(client, user_id=TEST_USER_ID):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _seed_hire(db, capability="translate", status="pending"):
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO hiring_candidates
                   (capability, gap_reason, shortlist, narrative, status)
               VALUES (%s, 'only 2 active', '[]'::jsonb, 'why these 3', %s)
               RETURNING id""",
            (capability, status),
        )
        return cur.fetchone()["id"]


def _cleanup_hire(db, hire_id):
    with db.cursor() as cur:
        cur.execute("DELETE FROM hiring_candidates WHERE id = %s", (hire_id,))


class TestHireSourceInPendingEndpoint:
    def test_pending_endpoint_unions_hire_rows(self, db, approvals_client):
        """Seed a pending hiring_candidates row, hit the endpoint, assert hire:<id> shows up."""
        _login_as_admin(approvals_client)
        hire_id = _seed_hire(db)
        try:
            resp = approvals_client.get("/tools/department-hq/api/approvals/pending")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["success"] is True
            approvals = body["approvals"]
            ids = [r.get("id") for r in approvals]
            assert f"hire:{hire_id}" in ids, f"hire:{hire_id} missing from {ids}"

            hire_row = next(r for r in approvals if r.get("id") == f"hire:{hire_id}")
            assert hire_row["source"] == "hire"
            # #2736's approvals_bulk.category_of() overwrites every row's category with
            # the sub-tab taxonomy (All/Ship/Social/Mail/Agents/Other) — hire_candidate
            # maps to "agents" (see ACTION_CATEGORY), not the pre-#2736 ad-hoc "hiring"
            # literal list_pending_approvals() stamps first and category_of() overwrites.
            assert hire_row["category"] == "agents"
            assert hire_row["display_name"] == "translate"
            assert hire_row["payload"]["shortlist"] == []
            assert hire_row["payload"]["gap_reason"] == "only 2 active"
            assert hire_row["payload"]["narrative"] == "why these 3"
            assert hire_row["agent_name"] == "K.I.N."  # no proposer_agent_id seeded
        finally:
            _cleanup_hire(db, hire_id)

    def test_pending_endpoint_excludes_non_pending_hire_rows(self, db, approvals_client):
        """Rows with status != 'pending' must not appear in the unified pending list."""
        _login_as_admin(approvals_client)
        hire_id = _seed_hire(db, capability="summarize", status="approved")
        try:
            resp = approvals_client.get("/tools/department-hq/api/approvals/pending")
            assert resp.status_code == 200
            body = resp.get_json()
            ids = [r.get("id") for r in body["approvals"]]
            assert f"hire:{hire_id}" not in ids, "Approved hire row should not appear in pending"
        finally:
            _cleanup_hire(db, hire_id)

    def test_hire_row_shape(self, db, approvals_client):
        """Verify every required field is present and correctly typed."""
        _login_as_admin(approvals_client)
        hire_id = _seed_hire(db, capability="code_review")
        try:
            resp = approvals_client.get("/tools/department-hq/api/approvals/pending")
            assert resp.status_code == 200
            body = resp.get_json()
            hire_row = next(
                (r for r in body["approvals"] if r.get("id") == f"hire:{hire_id}"),
                None,
            )
            assert hire_row is not None, f"hire:{hire_id} not found in approvals"
            # Required shape fields
            assert hire_row["source"] == "hire"
            # See test_pending_endpoint_unions_hire_rows above: category_of() (#2736)
            # stamps "agents" for hire_candidate rows, superseding the pre-#2736
            # "hiring" literal.
            assert hire_row["category"] == "agents"
            assert isinstance(hire_row["display_name"], str)
            assert isinstance(hire_row["payload"], dict)
            assert isinstance(hire_row["payload"]["shortlist"], list)
            # by_source must include hire count
            assert body["by_source"].get("hire", 0) >= 1
        finally:
            _cleanup_hire(db, hire_id)

    def test_hire_count_reflected_in_by_source(self, db, approvals_client):
        """by_source['hire'] accurately counts the pending hire rows."""
        _login_as_admin(approvals_client)
        id1 = _seed_hire(db, capability="cap_a")
        id2 = _seed_hire(db, capability="cap_b")
        try:
            resp = approvals_client.get("/tools/department-hq/api/approvals/pending")
            assert resp.status_code == 200
            body = resp.get_json()
            hire_count = body["by_source"].get("hire", 0)
            assert hire_count >= 2, f"Expected at least 2 hire rows, got {hire_count}"
        finally:
            _cleanup_hire(db, id1)
            _cleanup_hire(db, id2)


class TestApproveHireEndpoint:
    def test_post_approve_hire_calls_service_and_returns_200(self, approvals_client):
        from services import hiring_service as _svc
        from unittest.mock import patch as _patch

        _login_as_admin(approvals_client)
        with _patch.object(
            _svc,
            "approve_candidate",
            return_value={"ok": True, "reason": "approved", "agent_id": 42},
        ) as mock_approve:
            resp = approvals_client.post(
                "/tools/department-hq/api/approvals/hire/17/approve",
                json={"chosen_agent_id": 42, "notes": "go for it"},
            )
        assert resp.status_code == 200
        mock_approve.assert_called_once()
        call_kwargs = mock_approve.call_args.kwargs
        assert call_kwargs.get("hire_id") == 17
        assert call_kwargs.get("chosen_agent_id") == 42

    def test_post_approve_hire_returns_409_on_precheck_failure(self, approvals_client):
        from services import hiring_service as _svc
        from unittest.mock import patch as _patch

        _login_as_admin(approvals_client)
        with _patch.object(
            _svc,
            "approve_candidate",
            return_value={
                "ok": False,
                "reason": "model_missing",
                "agent_id": None,
                "message": "Model X missing",
            },
        ):
            resp = approvals_client.post(
                "/tools/department-hq/api/approvals/hire/17/approve",
                json={"chosen_agent_id": 42},
            )
        assert resp.status_code == 409
        body = resp.get_json()
        assert body.get("reason") == "model_missing"

    def test_post_approve_hire_returns_400_on_missing_chosen_agent(self, approvals_client):
        """Empty body / no chosen_agent_id → 400."""
        _login_as_admin(approvals_client)
        resp = approvals_client.post(
            "/tools/department-hq/api/approvals/hire/17/approve",
            json={},
        )
        assert resp.status_code == 400


class TestRejectHireEndpoint:
    def test_post_reject_hire_calls_service_and_returns_200(self, approvals_client):
        from services import hiring_service as _svc
        from unittest.mock import patch as _patch

        _login_as_admin(approvals_client)

        with _patch.object(
            _svc,
            "reject_candidate",
            return_value={"ok": True, "reason": "rejected"},
        ) as mock_reject:
            resp = approvals_client.post(
                "/tools/department-hq/api/approvals/hire/17/reject",
                json={"notes": "not a fit"},
            )
        assert resp.status_code == 200
        mock_reject.assert_called_once()
        assert mock_reject.call_args.kwargs.get("hire_id") == 17


class TestSuggestHireName:
    def test_suggest_name_returns_generated_name(self, db, approvals_client):
        """Seed a candidate, POST suggest-name, assert the generated identity comes
        back and the capability was derived server-side from the row (not the
        client)."""
        from unittest.mock import patch as _patch

        from services import agent_identity_builder as _aib

        _login_as_admin(approvals_client)
        hire_id = _seed_hire(db, capability="fact_check")
        try:
            with _patch.object(
                _aib,
                "build_identity",
                return_value={
                    "name": "V.E.R.I.F.Y.",
                    "expansion": "Validation Engine ...",
                    "title": "Fact Checker",
                    "bio": "b",
                    "personality": "p",
                    "system_prompt": "x" * 500,
                    "portrait_prompt": "sci-fi ...",
                    "source": "llm",
                },
            ) as mock_gen:
                resp = approvals_client.post(
                    f"/tools/department-hq/api/approvals/hire/{hire_id}/suggest-name",
                    json={},
                )
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["ok"] is True
            assert body["name"] == "V.E.R.I.F.Y."
            assert body["title"] == "Fact Checker"
            assert mock_gen.call_args.args[0] == "fact_check"
        finally:
            _cleanup_hire(db, hire_id)

    def test_suggest_name_not_found(self, approvals_client):
        """Unknown hire_id -> 404 {ok: false}."""
        _login_as_admin(approvals_client)
        resp = approvals_client.post(
            "/tools/department-hq/api/approvals/hire/999999/suggest-name",
            json={},
        )
        assert resp.status_code == 404
        assert resp.get_json()["ok"] is False

    def test_suggest_name_failsoft_on_generator_error(self, db, approvals_client):
        """A generator exception -> HTTP 200 {ok: false} (never blocks approval)."""
        from unittest.mock import patch as _patch

        from services import agent_identity_builder as _aib

        _login_as_admin(approvals_client)
        hire_id = _seed_hire(db, capability="translate")
        try:
            with _patch.object(_aib, "build_identity", side_effect=RuntimeError("boom")):
                resp = approvals_client.post(
                    f"/tools/department-hq/api/approvals/hire/{hire_id}/suggest-name",
                    json={},
                )
            assert resp.status_code == 200
            assert resp.get_json()["ok"] is False
        finally:
            _cleanup_hire(db, hire_id)

    def test_suggest_name_returns_full_identity(self, db, approvals_client, monkeypatch):
        """The route now returns the FULL identity package (bio, personality,
        system_prompt, portrait_prompt) — a superset of the old
        name/expansion/title/source response. Deterministic: monkeypatches
        agent_identity_builder.build_identity so no live fleet is needed."""
        from services import agent_identity_builder

        _login_as_admin(approvals_client)
        hire_id = _seed_hire(db, capability="fact_check")
        try:
            monkeypatch.setattr(
                agent_identity_builder,
                "build_identity",
                lambda cap, **k: {
                    "name": "V.E.R.I.F.Y.",
                    "expansion": "Validation Engine ...",
                    "title": "Fact Checker",
                    "bio": "b",
                    "personality": "p",
                    "system_prompt": "x" * 500,
                    "portrait_prompt": "sci-fi ...",
                    "source": "llm",
                },
            )
            resp = approvals_client.post(
                f"/tools/department-hq/api/approvals/hire/{hire_id}/suggest-name",
                json={},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert data["bio"] == "b"
            assert data["system_prompt"] == "x" * 500
            assert data["portrait_prompt"] == "sci-fi ..."
            assert data["name"] == "V.E.R.I.F.Y."
        finally:
            _cleanup_hire(db, hire_id)
