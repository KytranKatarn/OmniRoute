"""inject_learnings queried a column that does not exist, on every dispatch.

THE BUG (measured 2026-09-08):

`ai_bridge/bridge_learning.inject_learnings()` filtered on
    AND is_archived = FALSE
but `knowledge_base` has NO `is_archived` column. So the query raised
UndefinedColumn on EVERY call, the surrounding `except Exception` swallowed it at
`logger.debug` (invisible at INFO), and the function returned the prompt UNCHANGED.

Agent-learning injection has therefore never once worked. It is called from
`department_dispatcher` on EVERY dispatch — 85 occurrences of
`column "is_archived" does not exist` in a single hour of archie_database logs.

⚠️ The corpus being empty is NOT a second bug: `capture_learning` only fires on the
cloud-escalation success path, and cloud escalation is deliberately `local_only`
(escalation_mode). Zero "Captured learning" lines in 24h is expected. Fixing the
reader is a prerequisite for that feature ever working, not a behaviour change today.

The load-bearing test here is the SCHEMA one: it re-executes the real query against
the real table, so it catches ANY phantom column a future edit introduces — not just
this one. Source-string checks alone would not.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_bridge_learning_injection.py -v
"""

import inspect
import logging
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "platform_v2"))
sys.path.insert(0, str(_ROOT / "ai_bridge"))

import bridge_learning as bl  # noqa: E402


def _query_sql(strip_comments=False):
    """The SELECT inject_learnings actually issues, pulled from its source.

    strip_comments=True removes `--` lines. Assertions about what the query DOES
    must read executable SQL only — otherwise the explanatory comment naming the
    old phantom column trips the very test that forbids it. (Same comment-vs-code
    distinction as scripts/dr/test_no_retired_targets.sh.)
    """
    src = inspect.getsource(bl.inject_learnings)
    m = re.search(r'"""\s*(SELECT\s+title.*?LIMIT\s+%s\s*)"""', src, re.S)
    assert m, "could not locate the SELECT in inject_learnings"
    sql = m.group(1)
    if strip_comments:
        sql = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    return sql


# ── the schema check: catches ANY phantom column, now and later ──────────────


def test_the_query_executes_against_the_real_knowledge_base_schema():
    """Re-run the real SELECT with dummy params. A phantom column raises here.

    This is the assertion that would have caught the bug the day it shipped, and it
    keeps catching successors — it validates against the LIVE table, not a list of
    column names someone has to remember to update.
    """
    from database import get_db_cursor

    sql = _query_sql()
    with get_db_cursor() as (_conn, cur):
        cur.execute(sql, ("SomeAgent", "some_capability", 1))
        cur.fetchall()  # must not raise


def test_is_archived_is_gone():
    """The specific phantom column, pinned so it cannot be reintroduced."""
    assert "is_archived" not in _query_sql(strip_comments=True), "knowledge_base has no is_archived column"


def test_quarantine_filter_still_present():
    """Removing the broken filter must not silently drop the EXCLUSION it intended.

    Rejected cards must stay out of prompts; the fix keeps that using the column that
    exists (review_status), matching mcp_server/tools/knowledge.py:209.
    """
    sql = _query_sql(strip_comments=True)
    assert "review_status" in sql, "the rejected-card exclusion was dropped, not fixed"


# ── the swallow must be visible, but not spam a per-dispatch path ────────────


def test_failure_warns_once_per_process(monkeypatch, caplog):
    """~every dispatch calls this. Silent was the bug; per-call would be unreadable."""
    monkeypatch.setattr(bl, "_inject_warned", False, raising=False)

    def boom():
        raise RuntimeError("simulated DB failure")

    import database

    monkeypatch.setattr(database, "get_db", boom, raising=True)

    with caplog.at_level(logging.WARNING, logger=bl.logger.name):
        for _ in range(3):
            bl.inject_learnings("A", "cap", "PROMPT")

    warns = [r for r in caplog.records if "inject_learnings failed" in r.getMessage()]
    assert len(warns) == 1, f"expected exactly ONE warning across 3 calls, got {len(warns)}"


def test_failure_still_returns_the_ORIGINAL_prompt(monkeypatch):
    """Fail-safe is the one behaviour that must survive: a broken lookup degrades to
    an ungrounded prompt, it never breaks the dispatch."""
    monkeypatch.setattr(bl, "_inject_warned", True, raising=False)  # silence

    def boom():
        raise RuntimeError("simulated DB failure")

    import database

    monkeypatch.setattr(database, "get_db", boom, raising=True)
    assert bl.inject_learnings("A", "cap", "PROMPT") == "PROMPT"
