"""Tests for agent_service lifecycle functions (Phase 2).

These tests require a live database connection (integration tests).
Run from platform_v2/: python -m pytest services/tests/test_agent_lifecycle.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from database import get_db_cursor


@pytest.fixture
def setup_lifecycle_agent():
    """Create a test agent with budget, clean up after."""
    agent_id = None
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO agents (name, display_name, department, floor, status, shift_state, model)
            VALUES ('TestLifecycleAgent', 'Test Lifecycle Agent', 'Analytics & Intelligence',
                    'SERVICES', 'active', 'active', 'test-model')
            RETURNING id
        """
        )
        agent_id = cur.fetchone()["id"]

        cur.execute(
            """
            INSERT INTO agent_budgets (agent_id, current_task_count, task_queue_limit,
                                       tokens_used_today, token_limit_per_day, token_reset_at)
            VALUES (%s, 0, 100, 0, 100000, NOW() + INTERVAL '1 day')
            ON CONFLICT (agent_id) DO UPDATE SET
                current_task_count = 0, task_queue_limit = 100,
                tokens_used_today = 0, token_reset_at = NOW() + INTERVAL '1 day'
        """,
            (agent_id,),
        )

    yield agent_id

    # Cleanup
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM agent_rotation_log WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agent_budgets WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agent_emotional_state WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM task_execution_log WHERE agent_id = %s", (agent_id,))
        cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))


@pytest.fixture
def setup_two_agents():
    """Create two agents in the same department for replacement testing."""
    ids = []
    with get_db_cursor(commit=True) as (conn, cur):
        # Primary agent (active)
        cur.execute(
            """
            INSERT INTO agents (name, display_name, department, floor, status, shift_state, model)
            VALUES ('TestPrimaryAgent', 'Test Primary', 'Analytics & Intelligence',
                    'SERVICES', 'active', 'active', 'test-model')
            RETURNING id
        """
        )
        primary_id = cur.fetchone()["id"]
        ids.append(primary_id)

        # Backup agent (barracked, with max-level skills to guarantee it wins scoring)
        cur.execute(
            """
            INSERT INTO agents (name, display_name, department, floor, status, shift_state, model)
            VALUES ('TestBackupAgent', 'Test Backup', 'Analytics & Intelligence',
                    'SERVICES', 'active', 'barracked', 'test-model')
            RETURNING id
        """
        )
        backup_id = cur.fetchone()["id"]
        ids.append(backup_id)

        # Give backup agent max proficiency skills so it wins over any real agents
        cur.execute(
            """
            INSERT INTO agent_skills (agent_id, skill_name, skill_category, proficiency_level)
            VALUES (%s, 'test_mastery_1', 'analytics', 5),
                   (%s, 'test_mastery_2', 'analytics', 5),
                   (%s, 'test_mastery_3', 'analytics', 5)
        """,
            (backup_id, backup_id, backup_id),
        )

    yield ids  # [primary_id, backup_id]

    # Cleanup both agents
    with get_db_cursor(commit=True) as (conn, cur):
        for aid in ids:
            cur.execute("DELETE FROM agent_rotation_log WHERE agent_id = %s", (aid,))
            cur.execute("DELETE FROM agent_budgets WHERE agent_id = %s", (aid,))
            cur.execute("DELETE FROM agent_emotional_state WHERE agent_id = %s", (aid,))
            cur.execute("DELETE FROM agent_skills WHERE agent_id = %s", (aid,))
            cur.execute("DELETE FROM agent_rotation_log WHERE replaced_by = %s", (aid,))
        for aid in ids:
            cur.execute("DELETE FROM agents WHERE id = %s", (aid,))


# -----------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------


def test_transition_shift_state_to_cooldown(setup_lifecycle_agent):
    from services.agent_service import transition_shift_state

    agent_id = setup_lifecycle_agent
    result = transition_shift_state(agent_id, "cooldown", "test_exhaust")

    assert result["success"] is True
    assert result["new_state"] == "cooldown"

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT shift_state FROM agents WHERE id = %s", (agent_id,))
        row = cur.fetchone()
        assert row["shift_state"] == "cooldown"


def test_transition_shift_state_logs_rotation(setup_lifecycle_agent):
    from services.agent_service import transition_shift_state

    agent_id = setup_lifecycle_agent
    transition_shift_state(agent_id, "winding_down", "test_wind_down")

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT shift_state, reason, ended_at
            FROM agent_rotation_log
            WHERE agent_id = %s
            ORDER BY started_at DESC
            LIMIT 1
        """,
            (agent_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["shift_state"] == "winding_down"
        assert row["reason"] == "test_wind_down"
        assert row["ended_at"] is None  # Current entry should be open


def test_increment_budget(setup_lifecycle_agent):
    from services.agent_service import increment_budget

    agent_id = setup_lifecycle_agent
    result = increment_budget(agent_id, tokens_used=500)

    assert result["success"] is True
    assert result["task_count"] == 1
    assert result["tokens_used_today"] == 500


def test_increment_budget_accumulates(setup_lifecycle_agent):
    from services.agent_service import increment_budget

    agent_id = setup_lifecycle_agent
    increment_budget(agent_id, tokens_used=300)
    result = increment_budget(agent_id, tokens_used=200)

    assert result["success"] is True
    assert result["task_count"] == 2
    assert result["tokens_used_today"] == 500


def test_update_welfare_after_task(setup_lifecycle_agent):
    from services.agent_service import update_welfare_after_task

    agent_id = setup_lifecycle_agent
    result = update_welfare_after_task(agent_id, success=True)

    assert result["success"] is True
    assert "stress" in result
    assert "energy" in result
    assert "mood" in result
    # Verify CHECK constraints
    assert result["stress"] <= 0.9
    assert result["energy"] >= 0.1


def test_check_shift_transitions_triggers_cooldown(setup_lifecycle_agent):
    from services.agent_service import check_shift_transitions

    agent_id = setup_lifecycle_agent

    # Set budget to 100% (task_count = task_limit)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE agent_budgets
            SET current_task_count = 100, task_queue_limit = 100
            WHERE agent_id = %s
        """,
            (agent_id,),
        )

    result = check_shift_transitions()

    # Verify the agent was transitioned
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT shift_state FROM agents WHERE id = %s", (agent_id,))
        row = cur.fetchone()
        assert row["shift_state"] == "cooldown"

    # Verify it appears in transitions list
    agent_names = [t["agent"] for t in result["transitions"]]
    assert "TestLifecycleAgent" in agent_names


def test_find_replacement_activates_barracked(setup_two_agents):
    from services.agent_service import transition_shift_state

    primary_id, backup_id = setup_two_agents

    # Transition primary to cooldown — should auto-find replacement
    result = transition_shift_state(primary_id, "cooldown", "test_replacement")

    assert result["success"] is True
    assert result["replacement"] is not None
    assert result["replacement"]["id"] == backup_id
    assert result["replacement"]["score"] == 5.0  # avg of three level-5 skills

    # Verify backup agent is now active
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT shift_state FROM agents WHERE id = %s", (backup_id,))
        row = cur.fetchone()
        assert row["shift_state"] == "active"
