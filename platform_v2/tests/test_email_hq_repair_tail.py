"""Regression evidence for Email HQ's remaining repair proposals.

DB checks use temporary tables on an explicitly isolated human_access_test* DB.
Run with the same HUMAN_ACCESS_TEST_DSN as test_human_agent_access.py.
"""

from contextlib import contextmanager
from pathlib import Path
import ast
import inspect
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Blueprint, Flask
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from services.code_health_checks import sql_finding_present
from services.code_issue_reconciler import finding_still_reproduces
from tools.email_manager import hq_routes, human_sla_service, triage_service


MODULE = Path(__file__).resolve().parents[1] / "tools" / "email_manager"


def test_import_registration_is_an_explicit_export():
    from tools import email_manager

    assert "imap_routes" in email_manager.__all__
    assert email_manager.imap_routes.email_manager_bp is email_manager.email_manager_bp
    assert (
        finding_still_reproduces(
            "PYFLAKES '.imap_routes' imported but unused", (MODULE / "__init__.py").read_text(), 13
        )
        is False
    )


@pytest.mark.parametrize("name", ["hq_routes.py", "human_sla_service.py", "triage_service.py"])
def test_sql_repairs_are_provable_not_merely_unknown(name):
    assert sql_finding_present((MODULE / name).read_text()) is False


def test_moved_sql_is_not_automatically_declared_fixed():
    assert sql_finding_present((MODULE / "imap_routes.py").read_text()) is None


@pytest.fixture
def mail_cursor():
    dsn = os.environ.get("HUMAN_ACCESS_TEST_DSN")
    if not dsn:
        pytest.skip("isolated human_access_test* PostgreSQL required")
    conn = psycopg2.connect(dsn)
    try:
        assert conn.info.dbname.startswith("human_access_test"), "refusing non-test DB"
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TEMP TABLE agents(id INT, display_name TEXT, name TEXT);
                INSERT INTO agents VALUES(10,'Alice','alice'),(20,'Bob','bob');
                CREATE TEMP TABLE email_mailboxes(id INT, address TEXT, owner_agent_id INT,
                    mailbox_type TEXT, active BOOLEAN);
                INSERT INTO email_mailboxes VALUES
                    (1,'alice@example.test',10,'human_agent',true),
                    (2,'bob@example.test',20,'human_agent',true);
                CREATE TEMP TABLE email_messages(id INT, mailbox_id INT,
                    received_at TIMESTAMP, ai_priority TEXT);
                INSERT INTO email_messages VALUES(11,1,NOW()-INTERVAL '2 hours',NULL),
                    (22,2,NOW()-INTERVAL '2 hours',NULL);
                CREATE TEMP TABLE email_reply_events(id INT, mailbox_id INT,
                    source_message_id INT, sent_at TIMESTAMP, response_time_seconds INT);
                INSERT INTO email_reply_events VALUES(1,1,11,NOW(),3600);
                CREATE TEMP TABLE email_activity_log(id INT, mailbox_address TEXT,
                    direction TEXT, from_address TEXT, to_address TEXT, subject TEXT,
                    logged_at TIMESTAMP, read_at TIMESTAMP);
                INSERT INTO email_activity_log VALUES
                    (101,'alice@example.test','received','a@example.test','alice@example.test',
                     'Alice mail',NOW()-INTERVAL '2 days',NULL),
                    (202,'bob@example.test','received','b@example.test','bob@example.test',
                     'Bob mail',NOW()-INTERVAL '2 days',NULL);
                CREATE TEMP TABLE email_assignments(email_id INT, assigned_agent TEXT,
                    status TEXT, assigned_by TEXT, notes TEXT);
                """
            )

        @contextmanager
        def cursor(commit=False):
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield conn, cur

        yield cursor
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize("visible,expected", [(None, [1, 2]), ([], []), ([1], [1]), ([2], [2])])
def test_sla_scope_and_parameter_order(mail_cursor, visible, expected):
    with patch.object(human_sla_service, "get_db_cursor", mail_cursor), patch.object(
        human_sla_service, "get_sla_target_hours", return_value=4
    ):
        result = human_sla_service.per_agent_stats(days=7, visible_mailbox_ids=visible)
    assert sorted(row["mailbox_id"] for row in result["agents"]) == expected
    for row in result["agents"]:
        assert row["inbound_count"] == 1


@pytest.mark.parametrize("visible,expected", [(None, [101, 202]), ([], []), ([1], [101])])
@pytest.mark.parametrize(
    "path,key", [("/api/hq/unified-inbox", "emails"), ("/api/hq/oversight/unanswered", "unanswered")]
)
def test_hq_literal_queries_preserve_mailbox_scope(mail_cursor, visible, expected, path, key):
    app = Flask(__name__)
    app.config.update(TESTING=True, LOGIN_DISABLED=True)
    bp = Blueprint("repair_tail", __name__)
    hq_routes.register_hq_routes(bp, lambda f: f)
    app.register_blueprint(bp)
    with patch.object(hq_routes, "get_db_cursor", mail_cursor), patch.object(
        hq_routes, "get_visible_mailbox_ids", return_value=visible
    ):
        response = app.test_client().get(path, query_string={"status": "' OR 1=1 --"})
    assert response.status_code == 200
    assert sorted(row["id"] for row in response.get_json()[key]) == expected


def test_hq_rejects_forged_mailbox_scope(mail_cursor):
    app = Flask(__name__)
    app.config.update(TESTING=True, LOGIN_DISABLED=True)
    bp = Blueprint("repair_tail", __name__)
    hq_routes.register_hq_routes(bp, lambda f: f)
    app.register_blueprint(bp)
    with patch.object(hq_routes, "get_db_cursor", mail_cursor), patch.object(
        hq_routes, "get_visible_mailbox_ids", return_value=[1]
    ):
        assert app.test_client().get("/api/hq/unified-inbox?mailbox_id=2").status_code == 403


def test_triage_health_binds_interval_value(mail_cursor):
    with patch("database.get_db_cursor", mail_cursor), patch.object(
        triage_service, "_health_mailbox_types", return_value=["human_agent"]
    ), patch.object(triage_service, "_HEALTH_MIN_COUNT", 100):
        result = triage_service.run_triage_health_check()
    assert result == {"ok": True, "total": 2, "untriaged": 2, "alerted": False}


PAYLOAD = "x'; DROP TABLE email_messages; --"


@pytest.fixture
def captured_db():
    cur = Mock()
    cur.fetchone.return_value = {"count": 0, "total": 0, "c": 0, "id": 1}
    cur.fetchall.return_value = []
    cur.rowcount = 1
    conn = Mock()
    conn.cursor.return_value = cur

    @contextmanager
    def cursor(commit=False):
        yield conn, cur

    return conn, cur, cursor


@pytest.mark.parametrize(
    "module_name,function,db_name,path,method,data,args",
    [
        (
            "imap_settings_routes",
            "update_imap_setting",
            "get_db",
            "/",
            "PUT",
            {"name": PAYLOAD, PAYLOAD: "ignored"},
            (1,),
        ),
        ("imap_actions_routes", "update_draft", "get_db", "/", "PUT", {"subject": PAYLOAD, PAYLOAD: "ignored"}, (1,)),
        (
            "routes_templates",
            "update_settings",
            "get_db_connection",
            "/",
            "PUT",
            {"name": PAYLOAD, PAYLOAD: "ignored"},
            (1,),
        ),
        ("imap_inbox_routes", "get_inbox", "get_db", "/", "GET", None, ()),
        ("imap_inbox_routes", "get_inbox_stats", "get_db", "/", "GET", None, ()),
        ("routes_send", "get_logs", "get_db_connection", "/", "GET", None, ()),
    ],
)
def test_query_builders_bind_values_and_allowlist_structure(
    captured_db, module_name, function, db_name, path, method, data, args
):
    import importlib

    module = importlib.import_module("tools.email_manager." + module_name)
    conn, cur, _ = captured_db
    app = Flask(__name__)
    query = {"category": PAYLOAD, "search": PAYLOAD, "sort": PAYLOAD, "status": PAYLOAD}
    with app.test_request_context(path, method=method, json=data, query_string=query), patch.object(
        module, db_name, return_value=conn
    ), patch.object(module, "current_user", SimpleNamespace(id=7)):
        response = inspect.unwrap(getattr(module, function))(*args)
    assert not isinstance(response, tuple), response
    assert response.get_json()["success"] is True
    calls = cur.execute.call_args_list
    assert calls
    for call in calls:
        sql, params = call.args
        assert PAYLOAD not in sql
        assert params is not None
    if function != "get_inbox_stats":
        assert any(PAYLOAD in str(value) for call in calls for value in call.args[1])


@pytest.mark.parametrize("action", ["mark_read", "mark_unread", "archive", "star", "unstar", "delete"])
def test_bulk_id_values_never_become_sql_structure(captured_db, action):
    from tools.email_manager import imap_inbox_routes

    conn, cur, _ = captured_db
    app = Flask(__name__)
    with app.test_request_context("/", method="POST", json={"ids": [PAYLOAD], "action": action}), patch.object(
        imap_inbox_routes, "get_db", return_value=conn
    ), patch.object(imap_inbox_routes, "current_user", SimpleNamespace(id=7)):
        response = inspect.unwrap(imap_inbox_routes.bulk_action)()
    assert response.get_json()["success"] is True
    sql, params = cur.execute.call_args.args
    assert PAYLOAD not in sql
    assert "user_id = %s" in sql
    assert params == [PAYLOAD, 7]


@pytest.mark.parametrize(
    "path",
    [
        "/api/email/sidebar",
        "/api/email/counts",
        "/api/email/messages",
        "/api/email/views/action",
        "/api/email/views/starred",
        "/api/email/views/unread",
    ],
)
def test_message_builders_bind_search_and_retain_visibility(captured_db, path):
    from tools.email_manager import messages_routes, messages_routes_views

    _, cur, cursor = captured_db
    app = Flask(__name__)
    app.config.update(TESTING=True, LOGIN_DISABLED=True)
    bp = Blueprint("message_repair_tail", __name__)
    messages_routes.register_email_messages_routes(bp, lambda f: f)
    app.register_blueprint(bp)
    with patch.object(messages_routes, "get_db_cursor", cursor), patch.object(
        messages_routes_views, "get_db_cursor", cursor
    ), patch.object(messages_routes, "get_visible_mailbox_ids", return_value=[1]), patch.object(
        messages_routes_views, "get_visible_mailbox_ids", return_value=[1]
    ):
        response = app.test_client().get(path, query_string={"search": PAYLOAD, "view": PAYLOAD})
    assert response.status_code == 200
    for call in cur.execute.call_args_list:
        sql, params = call.args
        assert PAYLOAD not in sql
        assert [1] in params
    if path == "/api/email/messages":
        assert any(PAYLOAD in str(value) for call in cur.execute.call_args_list for value in call.args[1])


def test_manual_sql_review_covers_every_dynamic_query_builder():
    # This inventory deliberately does NOT turn the conservative verifier's
    # unknown into False. New dynamic SQL requires renewed explicit review.
    expected = {
        ("imap_settings_routes.py", "update_imap_setting"),
        ("imap_actions_routes.py", "update_draft"),
        ("imap_inbox_routes.py", "get_inbox"),
        ("imap_inbox_routes.py", "get_inbox_stats"),
        ("imap_inbox_routes.py", "bulk_action"),
        ("routes_templates.py", "update_settings"),
        ("routes_send.py", "get_logs"),
        ("messages_routes.py", "email_sidebar"),
        ("messages_routes.py", "email_counts"),
        ("messages_routes.py", "email_list_messages"),
        ("messages_routes_views.py", "_smart_view"),
    }
    actual = set()
    for path in MODULE.glob("*.py"):
        tree = ast.parse(path.read_text())

        def visit(node, function=None):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function = node.name
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("execute", "executemany")
            ):
                query = node.args[0] if node.args else None
                if not isinstance(query, ast.Constant) or not isinstance(query.value, str):
                    actual.add((path.name, function))
            for child in ast.iter_child_nodes(node):
                visit(child, function)

        visit(tree)
    assert actual == expected
