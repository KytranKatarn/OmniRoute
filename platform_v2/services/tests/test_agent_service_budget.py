"""Tests for agent_service budget reset functions.

These tests require a live database connection (integration tests).
Run from platform_v2/: python -m pytest services/tests/test_agent_service_budget.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from database import get_db_cursor


@pytest.fixture
def setup_test_agent():
    """Create a test agent with exhausted budget, clean up after."""
    agent_id = None
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO agents (name, display_name, department, floor, status, shift_state, model)
            VALUES ('TestBudgetAgent', 'Test Budget Agent', 'Analytics & Intelligence',
                    'SERVICES', 'active', 'cooldown', 'test-model')
            RETURNING id
        """
        )
        agent_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO agent_budgets (agent_id, current_task_count, task_queue_limit,
                                       tokens_used_today, token_limit_per_day, token_reset_at)
            VALUES (%s, 10, 10, 50000, 100000, NOW() - INTERVAL '1 day')
            ON CONFLICT (agent_id) DO UPDATE SET
                current_task_count = 10, task_queue_limit = 10,
                tokens_used_today = 50000, token_reset_at = NOW() - INTERVAL '1 day'
        """,
            (agent_id,),
        )

    yield agent_id

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM governance_audit_log WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agent_rotation_log WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agent_budgets WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agent_emotional_state WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))


def test_reset_budgets_zeroes_task_count(setup_test_agent):
    from services.agent_service import reset_budgets

    result = reset_budgets()
    assert result["reset_count"] > 0
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT current_task_count, tokens_used_today FROM agent_budgets WHERE agent_id = %s",
            (setup_test_agent,),
        )
        row = cur.fetchone()
        assert row["current_task_count"] == 0
        assert row["tokens_used_today"] == 0


def test_transition_cleared_cooldowns(setup_test_agent):
    from services.agent_service import reset_budgets, transition_cleared_cooldowns

    reset_budgets()
    result = transition_cleared_cooldowns()
    assert result["transitioned_count"] > 0
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT shift_state FROM agents WHERE id = %s", (setup_test_agent,))
        row = cur.fetchone()
        assert row["shift_state"] == "active"


def test_transition_cleared_cooldowns_skips_high_stress(setup_test_agent):
    from services.agent_service import reset_budgets, transition_cleared_cooldowns

    reset_budgets()
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM agent_emotional_state WHERE agent_id = %s",
            (setup_test_agent,),
        )
        cur.execute(
            """
            INSERT INTO agent_emotional_state (agent_id, stress_level, energy_level)
            VALUES (%s, 0.90, 0.10)
        """,
            (setup_test_agent,),
        )

    transition_cleared_cooldowns()

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT shift_state FROM agents WHERE id = %s", (setup_test_agent,))
        row = cur.fetchone()
        assert row["shift_state"] == "cooldown"
