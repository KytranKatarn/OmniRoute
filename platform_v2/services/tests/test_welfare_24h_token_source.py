"""#4130 FIX-2 — shared 24h rolling-token source across welfare reads.

The dispatch throttle (``get_welfare_cache``) was fixed in #4090 to read a 24h
ROLLING SUM of ``task_execution_log.tokens_used`` (with a NULL-``agent_id``
name-lookup), but the K.I.N. digest rollup (``_get_department_budget_rollup``)
and per-agent outliers (``_get_agent_welfare_outliers``) still read the
since-midnight ``agent_budgets.tokens_used_today`` column — so an agent that did
2x its budget in the trailing 24h read as healthy right after Toronto midnight
(KB mistake #272470 / ADR-004). FIX-2 routes all three through one shared source
(``_TOKENS_24H_SUBQUERY`` + ``get_agent_tokens_24h``).

These are INTEGRATION tests — they need a live DB.
Run from platform_v2/:
    docker exec archie_platform python3 -m pytest services/tests/test_welfare_24h_token_source.py -v
"""

import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from database import get_db_cursor

from services.agent_service import (
    _TOKENS_24H_SUBQUERY,
    _get_agent_welfare_outliers,
    _get_department_budget_rollup,
    get_agent_tokens_24h,
)

_NAME = "_TestW24hAgent"
# Must be a real department — agents.department has a CHECK constraint
# (chk_agents_department). The rollup assertion therefore can't isolate this
# agent's department; the OUTLIERS test (keyed on agent_id) is the definitive
# per-agent RED->GREEN proof of the 24h fix.
_DEPT = "Analytics & Intelligence"
_LIMIT = 10000
# 24h rolling tokens = 5000 (by id) + 4500 (by NAME, NULL agent_id) = 9500 = 95%
# of the 10k budget — over the 90% threshold. The 50000-token row is 30h old and
# MUST be excluded by the 24h window.
_EXPECTED_24H = 9500


def _purge(cur):
    cur.execute("DELETE FROM task_execution_log WHERE agent_name = %s", (_NAME,))
    cur.execute(
        "DELETE FROM agent_budgets WHERE agent_id IN (SELECT id FROM agents WHERE name = %s)",
        (_NAME,),
    )
    cur.execute("DELETE FROM agents WHERE name = %s", (_NAME,))


@pytest.fixture
def w24h_agent():
    """An active AI agent whose since-midnight token column is 0 but whose 24h
    rolling token use is 95% of budget. Yields its agent_id; cleans up after."""
    agent_id = None
    with get_db_cursor(commit=True) as (conn, cur):
        _purge(cur)  # clear any leftovers from a crashed prior run
        cur.execute(
            """
            INSERT INTO agents (name, display_name, department, floor, status, shift_state, worker_type, model)
            VALUES (%s, 'Test W24h Agent', %s, 'SERVICES', 'active', 'active', 'ai', 'test-model')
            RETURNING id
            """,
            (_NAME, _DEPT),
        )
        agent_id = cur.fetchone()["id"]
        # tokens_used_today = 0 (the since-midnight column) — the trap: a buggy
        # reader sees 0% and never flags the agent.
        cur.execute(
            """
            INSERT INTO agent_budgets (agent_id, current_task_count, task_queue_limit,
                                       tokens_used_today, token_limit_per_day, token_reset_at)
            VALUES (%s, 1, 100, 0, %s, NOW() + INTERVAL '1 day')
            ON CONFLICT (agent_id) DO UPDATE SET
                current_task_count = 1, tokens_used_today = 0, token_limit_per_day = %s
            """,
            (agent_id, _LIMIT, _LIMIT),
        )
        # In-window row keyed by agent_id.
        cur.execute(
            """INSERT INTO task_execution_log (agent_id, agent_name, capability, module_source,
                                               success, tokens_used, created_at)
               VALUES (%s, %s, 'test_w24h', 'test', TRUE, 5000, NOW() - INTERVAL '1 hour')""",
            (agent_id, _NAME),
        )
        # In-window row with NULL agent_id — must be resolved by NAME.
        cur.execute(
            """INSERT INTO task_execution_log (agent_id, agent_name, capability, module_source,
                                               success, tokens_used, created_at)
               VALUES (NULL, %s, 'test_w24h', 'test', TRUE, 4500, NOW() - INTERVAL '2 hours')""",
            (_NAME,),
        )
        # OUT-of-window row (30h ago) — must be excluded by the 24h window.
        cur.execute(
            """INSERT INTO task_execution_log (agent_id, agent_name, capability, module_source,
                                               success, tokens_used, created_at)
               VALUES (%s, %s, 'test_w24h', 'test', TRUE, 50000, NOW() - INTERVAL '30 hours')""",
            (agent_id, _NAME),
        )
    try:
        yield agent_id
    finally:
        with get_db_cursor(commit=True) as (conn, cur):
            _purge(cur)


# ── Behavioral: the shared helper ─────────────────────────────────────────────


def test_get_agent_tokens_24h_sums_window_and_resolves_null_agent_id_by_name(w24h_agent):
    tokens = get_agent_tokens_24h()
    # 5000 (by id) + 4500 (by name, NULL agent_id); the 30h/50000 row excluded.
    assert tokens.get(w24h_agent) == _EXPECTED_24H


# ── Behavioral: the two formerly-drifting readers now see the 24h truth ───────


def test_outliers_flag_over_budget_from_24h_not_since_midnight(w24h_agent):
    flags = _get_agent_welfare_outliers(over_budget_threshold=0.90)
    mine = [f for f in flags if f["agent_id"] == w24h_agent]
    assert len(mine) == 1, "agent should be flagged exactly once"
    assert mine[0]["flag"] == "over_budget", (
        "agent at 95% of budget over 24h must be over_budget even though " "tokens_used_today (since-midnight) is 0"
    )
    assert mine[0]["token_usage_pct"] == pytest.approx(0.95, abs=0.01)


def test_department_rollup_counts_over_budget_from_24h_not_since_midnight(w24h_agent):
    # Shares a real department with live agents, so we can only assert our
    # over-budget agent is counted (>= 1). The since-midnight bug would have
    # contributed 0 here (tokens_used_today = 0); the outliers test above is the
    # isolated per-agent proof.
    rollup = _get_department_budget_rollup()
    assert _DEPT in rollup, "the agent's department should appear in the rollup"
    assert int(rollup[_DEPT]["agents_over_budget"]) >= 1


# ── Source-guard: all readers share the one canonical 24h definition ──────────


def test_canonical_subquery_resolves_id_or_name_over_24h():
    sub = _TOKENS_24H_SUBQUERY
    assert "COALESCE(t.agent_id" in sub
    assert "split_part(t.agent_name, ' (CLI)', 1)" in sub
    assert "INTERVAL '24 hours'" in sub
    assert "GROUP BY COALESCE(t.agent_id" in sub


def test_rollup_and_outliers_use_shared_subquery_not_since_midnight():
    for fn in (_get_department_budget_rollup, _get_agent_welfare_outliers):
        src = inspect.getsource(fn)
        assert "_TOKENS_24H_SUBQUERY" in src, f"{fn.__name__} must read the shared 24h source, not its own SQL"
        assert "tk.tokens_24h" in src, f"{fn.__name__} must join the 24h token sum"
