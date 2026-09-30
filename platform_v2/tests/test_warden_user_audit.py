"""Tests for services.warden_user_audit — the W.A.R.D.E.N. daily user audit.

The job used to ask an LLM to audit users with NO data in the prompt; its output
was templates and invented figures (a report of 42 inactive users on a 35-user
platform). These tests pin the replacement: the facts come from SQL, with the
same definitions the auth code enforces.

Seeded tests measure a before/after DELTA on uniquely-named rows, so whatever
else sits in the test DB cannot make them pass or fail vacuously.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from psycopg2.extras import RealDictCursor

from services.auth_service import LOCKOUT_MINUTES, MAX_FAILED_ATTEMPTS
from services.warden_user_audit import (
    INACTIVE_DAYS,
    NAME_LIST_LIMIT,
    STALE_INVITE_DAYS,
    collect_user_audit,
    format_report,
    needs_attention,
)


@pytest.fixture
def cur(db_conn):
    with db_conn.cursor(cursor_factory=RealDictCursor) as c:
        yield c


def _user(cur, tag, *, active=True, last_login_days=None, created_days=1, failed=0):
    """Insert a uniquely-named user. ``last_login_days=None`` means never logged in."""
    name = f"wua-{tag}-{uuid.uuid4().hex[:8]}"
    # Explicit id: the cloned archie_test.users sequence can lag behind MAX(id), so a
    # defaulted id collides with users_pkey. The db_conn fixture rolls this back.
    cur.execute(
        """
        INSERT INTO users (id, username, email, password_hash, is_active, last_login, created_at, failed_login_count)
        VALUES ((SELECT COALESCE(MAX(id), 0) + 1 FROM users), %s, %s, 'x', %s,
                CASE WHEN %s::int IS NULL THEN NULL ELSE NOW() - make_interval(days => %s::int) END,
                NOW() - make_interval(days => %s), %s)
        RETURNING id, username
        """,
        (name, f"{name}@example.invalid", active, last_login_days, last_login_days, created_days, failed),
    )
    return cur.fetchone()


def _failed_login(cur, username, minutes_ago):
    cur.execute(
        "INSERT INTO failed_logins (username, attempted_at) VALUES (%s, NOW() - make_interval(mins => %s))",
        (username, minutes_ago),
    )


def _invite(cur, inviter_id, *, status, created_days, expires_days_from_now):
    cur.execute(
        """
        INSERT INTO user_invites (email, invited_by, token, status, created_at, expires_at)
        VALUES (%s, %s, %s, %s, NOW() - make_interval(days => %s), NOW() + make_interval(days => %s))
        """,
        (
            f"inv-{uuid.uuid4().hex[:8]}@example.invalid",
            inviter_id,
            uuid.uuid4().hex,
            status,
            created_days,
            expires_days_from_now,
        ),
    )


def test_inactive_counts_only_active_accounts_past_the_window(cur):
    before = collect_user_audit(cur)
    stale = _user(cur, "stale", last_login_days=INACTIVE_DAYS + 30)
    never = _user(cur, "never", last_login_days=None, created_days=INACTIVE_DAYS + 15)
    _user(cur, "recent", last_login_days=1)  # fresh login -> not inactive
    _user(cur, "newborn", last_login_days=None, created_days=2)  # never logged in but brand new
    _user(cur, "deactivated", active=False, last_login_days=INACTIVE_DAYS + 90)  # already off
    after = collect_user_audit(cur)

    assert after["inactive_count"] - before["inactive_count"] == 2
    assert stale["username"] in after["inactive_names"] or after["inactive_count"] > NAME_LIST_LIMIT
    assert never["username"] in after["inactive_names"] or after["inactive_count"] > NAME_LIST_LIMIT
    assert after["users_total"] - before["users_total"] == 5


def test_locked_mirrors_is_account_locked(cur):
    before = collect_user_audit(cur)
    hot = _user(cur, "hot", failed=MAX_FAILED_ATTEMPTS)
    _failed_login(cur, hot["username"], minutes_ago=1)  # inside the lockout window -> locked
    cooled = _user(cur, "cooled", failed=MAX_FAILED_ATTEMPTS)
    _failed_login(cur, cooled["username"], minutes_ago=LOCKOUT_MINUTES + 60)  # window over -> not locked
    few = _user(cur, "few", failed=MAX_FAILED_ATTEMPTS - 1)
    _failed_login(cur, few["username"], minutes_ago=1)  # recent but under the threshold -> not locked
    after = collect_user_audit(cur)

    assert after["locked_count"] - before["locked_count"] == 1


def test_stale_and_expired_invites(cur):
    inviter = _user(cur, "inviter", last_login_days=0)
    before = collect_user_audit(cur)
    _invite(cur, inviter["id"], status="pending", created_days=STALE_INVITE_DAYS + 3, expires_days_from_now=30)  # stale
    _invite(
        cur, inviter["id"], status="pending", created_days=STALE_INVITE_DAYS + 3, expires_days_from_now=-1
    )  # stale AND past expiry
    _invite(cur, inviter["id"], status="pending", created_days=1, expires_days_from_now=6)  # fresh
    _invite(
        cur, inviter["id"], status="accepted", created_days=STALE_INVITE_DAYS + 3, expires_days_from_now=-1
    )  # settled
    after = collect_user_audit(cur)

    assert after["stale_pending_invites"] - before["stale_pending_invites"] == 2
    assert after["pending_invites_past_expiry"] - before["pending_invites_past_expiry"] == 1


def _facts(**over):
    base = {
        "users_total": 35,
        "users_active": 26,
        "inactive_count": 0,
        "inactive_names": [],
        "locked_count": 0,
        "locked_names": [],
        "stale_pending_invites": 0,
        "pending_invites_past_expiry": 0,
    }
    base.update(over)
    return base


def test_report_uses_only_the_facts_and_never_a_placeholder():
    facts = _facts(inactive_count=24, inactive_names=["a", "b"], stale_pending_invites=3)
    report = format_report(facts)
    assert "26 active of 35 total" in report
    assert "24: a, b (+22 more)" in report  # exact count, truncated names, remainder stated
    assert "Invites pending >" in report and ": 3" in report
    assert "[Insert" not in report and "TBD" not in report
    assert "Attention needed." in report


def test_clean_audit_says_nothing_needs_attention():
    facts = _facts()
    assert needs_attention(facts) is False
    assert "Nothing needs attention." in format_report(facts)


@pytest.mark.parametrize(
    "field", ["inactive_count", "locked_count", "stale_pending_invites", "pending_invites_past_expiry"]
)
def test_each_finding_alone_needs_attention(field):
    assert needs_attention(_facts(**{field: 1})) is True


def _job_source():
    """Parse agent_loop.py and return the AST of _run_warden_user_audit (no import —
    importing agent_loop drags the whole scheduler in, and other tests stub it)."""
    for root in (Path(__file__).resolve().parents[2], Path("/mnt/archie_brain")):
        path = root / "ai_bridge" / "agent_loop.py"
        if path.exists():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "_run_warden_user_audit":
                    return node
    pytest.fail("could not locate _run_warden_user_audit in ai_bridge/agent_loop.py")


def test_job_reads_the_database_and_never_asks_an_llm():
    fn = _job_source()
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    imported = {a.name for n in ast.walk(fn) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "collect_user_audit" in imported
    # The regression: a data-less prompt to the dispatch queue.
    assert "queued_dispatch_text" not in imported | names
    assert not any("dispatch" in name.lower() for name in imported | names)


def test_job_logs_a_reason_when_the_audit_fails():
    # A bare logger.error left NO autonomy_loop_log row and later "(no reason recorded)".
    fn = _job_source()
    handlers = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
    assert handlers, "the job must catch failures"
    logged_with_reason = [
        c
        for h in handlers
        for c in ast.walk(h)
        if isinstance(c, ast.Call)
        and getattr(c.func, "attr", "") == "_log_cycle"
        and any(k.arg == "error_message" for k in c.keywords)
    ]
    assert logged_with_reason, "the except path must call _log_cycle(error_message=...)"
