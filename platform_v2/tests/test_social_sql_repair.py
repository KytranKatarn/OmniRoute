"""Exercise literal account updates and conservative security-finding closure."""

import sqlite3
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from urllib.parse import quote
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, jsonify

import database
from services import code_issue_reconciler as reconciler, signal_accounts
from services.code_health_checks import sql_finding_present
from tools.department_hq.social_routes import register_social_routes


@pytest.fixture
def account_config(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE agent_platform_accounts (account_key TEXT PRIMARY KEY, daily_action_budget INTEGER, voice_key TEXT)"
    )
    conn.executemany(
        "INSERT INTO agent_platform_accounts VALUES (?, ?, ?)", [("target", 5, "original"), ("other", 9, "protected")]
    )
    conn.commit()
    state = {"admin": True, "queries": [], "commits": []}

    class Cursor:
        def execute(self, sql, params):
            state["queries"].append((sql, params))
            self.cursor = conn.execute(sql.replace("%s", "?"), params)

        @property
        def rowcount(self):
            return self.cursor.rowcount

    @contextmanager
    def db(commit=False):
        state["commits"].append(commit)
        yield conn, Cursor()
        if commit:
            conn.commit()

    monkeypatch.setattr(database, "get_db_cursor", db)
    invalidation = Mock()
    monkeypatch.setattr(signal_accounts, "invalidate", invalidation)
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="isolated-social-config-test")

    def admin_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not state["admin"]:
                return jsonify({"error": "not_admin"}), 403
            return fn(*args, **kwargs)

        return wrapped

    bp = Blueprint("social-config-test", __name__)
    register_social_routes(bp, admin_required)
    app.register_blueprint(bp)
    yield app.test_client(), conn, state, invalidation
    conn.close()


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"daily_action_budget": "8"}, (8, "original")),
        ({"voice_key": " new "}, (5, "new")),
        ({"daily_action_budget": "8", "voice_key": " new "}, (8, "new")),
        ({"daily_action_budget": -5}, (0, "original")),
        ({"voice_key": "  "}, (5, None)),
    ],
)
def test_supported_updates_preserve_partial_values_and_other_accounts(account_config, payload, expected):
    client, conn, state, invalidation = account_config
    response = client.post("/api/social/signal/agent-config/target", json=payload)
    assert response.status_code == 200
    assert (
        conn.execute(
            "SELECT daily_action_budget,voice_key FROM agent_platform_accounts WHERE account_key=?", ("target",)
        ).fetchone()
        == expected
    )
    assert conn.execute(
        "SELECT daily_action_budget,voice_key FROM agent_platform_accounts WHERE account_key=?", ("other",)
    ).fetchone() == (9, "protected")
    assert state["commits"] == [True]
    assert state["queries"][0][1][-1] == "target"
    invalidation.assert_called_once_with()


def test_voice_sql_payload_is_stored_as_data(account_config):
    client, conn, _, _ = account_config
    malicious = "'; UPDATE agent_platform_accounts SET voice_key='hacked'; --"
    response = client.post("/api/social/signal/agent-config/target", json={"voice_key": malicious})
    assert response.status_code == 200
    assert conn.execute(
        "SELECT voice_key FROM agent_platform_accounts WHERE account_key=?", ("target",)
    ).fetchone() == (malicious,)
    assert conn.execute("SELECT voice_key FROM agent_platform_accounts WHERE account_key=?", ("other",)).fetchone() == (
        "protected",
    )


def test_account_sql_payload_cannot_match_other_rows(account_config):
    client, conn, _, invalidation = account_config
    key = "target' OR 1=1 --"
    response = client.post("/api/social/signal/agent-config/" + quote(key, safe=""), json={"daily_action_budget": 99})
    assert response.status_code == 404
    assert conn.execute("SELECT daily_action_budget FROM agent_platform_accounts ORDER BY account_key").fetchall() == [
        (9,),
        (5,),
    ]
    invalidation.assert_not_called()


@pytest.mark.parametrize(
    "payload", [{}, {"unknown_column": "value"}, {"daily_action_budget": None}, {"daily_action_budget": "invalid"}]
)
def test_invalid_updates_never_execute_sql(account_config, payload):
    client, _, state, invalidation = account_config
    assert client.post("/api/social/signal/agent-config/target", json=payload).status_code == 400
    assert not state["queries"]
    invalidation.assert_not_called()


def test_account_update_still_requires_admin(account_config):
    client, _, state, invalidation = account_config
    state["admin"] = False
    assert client.post("/api/social/signal/agent-config/target", json={"daily_action_budget": 99}).status_code == 403
    assert not state["queries"]
    invalidation.assert_not_called()


@pytest.mark.parametrize(
    "source,expected",
    [
        ('cur.execute("SELECT * FROM records WHERE id = %s", (user_id,))', False),
        ('cur.execute("SELECT 1"); cur.executemany("INSERT INTO t VALUES (%s)", values)', False),
        ('cur.execute(f"SELECT * FROM t WHERE id = {user_id}")', True),
        ('cur.execute("SELECT * FROM t WHERE id = %s" % user_id)', True),
        ("cur.execute(query)", None),
        ('cur.execute("SELECT " + value)', None),
        ('cur.execute("SELECT {}".format(value))', None),
        ('cur.execute(sql.SQL("SELECT {}" ).format(sql.Identifier(column)))', None),
        ('cur.execute(query="SELECT 1")', None),
        ('cur.execute("SELECT 1"); run = cur.execute; run(query)', None),
        ('cur.execute("SELECT 1"); execute(query)', None),
        ('cur.execute("SELECT 1"); getattr(cur, "execute")(query)', None),
        ('cur.execute("SELECT 1"); builtins.eval(code)', None),
        ('exec(code); cur.execute("SELECT 1")', None),
        ('from builtins import eval as run; run(code); cur.execute("SELECT 1")', None),
        ('runner = eval; runner(code); cur.execute("SELECT 1")', None),
        ('from executor import execute as run; run(query); cur.execute("SELECT 1")', None),
        ('return\ncur.execute("SELECT 1")', None),
        ('from helper import *; cur.execute("SELECT 1"); run(query)', None),
        ("def broken(", None),
        ('query = "SELECT 1"', None),
        ('cur.execute(query); cur.execute(f"SELECT {value}")', True),
    ],
)
def test_sql_checker_preserves_ambiguous_and_dynamic_findings(source, expected):
    assert sql_finding_present(source) is expected
    assert reconciler.finding_still_reproduces("SQL_INJECTION_RISK", source) is expected


def test_complete_social_source_is_provably_literal():
    root = Path(__file__).parents[1] / "tools/department_hq"
    assert sql_finding_present((root / "social_routes.py").read_text()) is False
    assert sql_finding_present((root / "work_routes.py").read_text()) is True


@pytest.mark.parametrize(
    "source,stale,unverifiable",
    [
        ('cur.execute("UPDATE t SET value=%s", (value,))', 1, 0),
        ("cur.execute(query)", 0, 1),
        ('cur.execute(f"UPDATE t SET value={value}")', 0, 0),
    ],
)
def test_native_reconciliation_closes_only_proven_literal_sql(monkeypatch, source, stale, unverifiable):
    row = {
        "id": 2570,
        "runtime_file": "/app/tools/department_hq/social_routes.py",
        "file_path": "platform_v2/tools/department_hq/social_routes.py",
        "issue_code": "SQL_INJECTION_RISK",
        "detail": "",
        "line": "",
    }
    cursor = Mock()
    cursor.fetchall.return_value = [row]
    commits = []

    @contextmanager
    def db(commit=False):
        commits.append(commit)
        yield None, cursor

    monkeypatch.setattr(reconciler, "get_db_cursor", db)
    monkeypatch.setattr(reconciler, "_read_proposal_file", lambda *args: source)
    result = reconciler.reconcile_open_proposals(dry_run=True, module_name="department_hq")
    assert result["stale"] == stale
    assert result["unverifiable"] == unverifiable
    assert result["archived"] == 0
    assert commits == [False]


@pytest.mark.parametrize(
    "source,flagged",
    [
        ('cur.execute("SELECT 1")', False),
        ('cur.execute("SELECT 1")\n# cur.execute(f"SELECT {unsafe}")', False),
        ('cur.execute(f"SELECT {value}")', True),
        ('exec(code); cur.execute(f"SELECT {value}")', True),
        ('def broken(\n    cur.execute(f"SELECT {value}")', True),
    ],
)
def test_real_audit_shares_verification_and_preserves_unknown_fallback(tmp_path, source, flagged):
    from services.code_metrics_service import _audit_module_python

    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "queries.py").write_text(source)
    results = [_audit_module_python("test", str(tmp_path)) for _ in range(2)]
    assert results[0] == results[1]
    findings = results[0][2]
    assert any(finding["code"] == "SQL_INJECTION_RISK" for finding in findings) is flagged


def test_compiler_recursion_failure_keeps_the_legacy_security_finding(tmp_path):
    from services.code_metrics_service import _audit_module_python

    source = "x = " + "+".join(["1"] * 1500) + '\ncur.execute(f"SELECT {value}")\n'
    assert sql_finding_present(source) is not False
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "queries.py").write_text(source)
    findings = _audit_module_python("test", str(tmp_path))[2]
    assert any(finding["code"] == "SQL_INJECTION_RISK" for finding in findings)
