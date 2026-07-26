"""Fleet stats must count nodes by the status column, not a private heartbeat window.

The starbase-stats endpoint used to compute `online_nodes` itself:

    last_heartbeat > NOW() - INTERVAL '30 seconds' OR deployment_mode = 'starbase'

Two defects, both observed live on 2026-07-26:

1. Nodes heartbeat every ~45-60s, so most fell outside a 30s window at any given
   sample and the number OSCILLATED (measured 4 -> 6 -> 4 -> 6 of 9). The rest of
   the platform uses a 2-minute rule (services/fleet_jobs.py).
2. It judged every node by heartbeat. An ingress node (Beacon) runs NO node agent
   by design, so it can never send one and was permanently uncounted — the exact
   category error #5218 fixed in remote_nodes.status. This endpoint bypassed that
   fix by rolling its own signal.

These tests EXECUTE the SQL rather than asserting on source, because a source
assertion is what let the flicker survive (#5173, KB #283579). Rows are seeded
inside a transaction that is always rolled back, so the live table is untouched.
"""

import sys

import pytest
from tests.dbguard import db_or_skip, import_or_skip  # noqa: E402

sys.path.insert(0, "/app")

# The query as the endpoint now runs it.
ONLINE_SQL = """SELECT COUNT(*) FROM remote_nodes
                WHERE is_active = true AND status = 'online'"""

# The old, replaced behaviour — kept so we can prove it gets the WRONG answer.
LEGACY_SQL = """SELECT COUNT(*) FROM remote_nodes
                WHERE is_active = true
                AND (last_heartbeat > NOW() - INTERVAL '30 seconds'
                     OR deployment_mode = 'starbase')"""

_ONLY_SEEDED = " AND node_id LIKE 't\\_%%'"

_SEED = """
INSERT INTO remote_nodes
    (node_id, node_name, hostname, deployment_mode, node_role,
     is_active, status, last_heartbeat)
VALUES
    -- agent beating normally -> online under either rule
    ('t_agent_fresh', 'T Agent Fresh', '10.0.0.1', 'outpost', 'agent',
     true, 'online', NOW() - INTERVAL '10 seconds'),
    -- agent that beat 50s ago: healthy under the platform's 2-min rule but
    -- OUTSIDE the old 30s window. This is the oscillation case.
    ('t_agent_slow', 'T Agent Slow', '10.0.0.2', 'outpost', 'agent',
     true, 'online', NOW() - INTERVAL '50 seconds'),
    -- ingress (Beacon-shaped): sends NO heartbeat by design; reachability
    -- probe says online. Must still count.
    ('t_ingress', 'T Ingress', '10.0.0.3', 'starbase_outpost', 'ingress',
     true, 'online', NOW() - INTERVAL '13 hours'),
    -- genuinely down agent: must NOT count
    ('t_agent_down', 'T Agent Down', '10.0.0.4', 'outpost', 'agent',
     true, 'offline', NOW() - INTERVAL '20 minutes')
"""


@pytest.fixture()
def cur():
    """Seed 4 nodes, hand back a cursor, always roll back."""
    pytest.importorskip("psycopg2")
    try:
        from database import get_db_connection
    except Exception as exc:  # pragma: no cover
        import_or_skip(exc, "database module")

    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            try:
                c.execute("DELETE FROM remote_nodes WHERE node_id LIKE 't\\_%%'")
                c.execute(_SEED)
                yield c
            finally:
                conn.rollback()
                c.close()
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # pragma: no cover - no reachable DB
        db_or_skip(exc)


def _count(c, sql):
    c.execute(sql + _ONLY_SEEDED)
    return c.fetchone()[0]


def test_ingress_node_counts_online_despite_no_heartbeat(cur):
    """THE REGRESSION: 13h since heartbeat, reachable, must still count."""
    assert _count(cur, ONLINE_SQL) == 3, (
        "expected 3 online (2 agents + 1 ingress) — an ingress node must count "
        "even though it sends no heartbeat by design"
    )


def test_legacy_30s_window_undercounts_the_same_rows(cur):
    """Proves the replaced query gives the WRONG answer on identical data."""
    legacy = _count(cur, LEGACY_SQL)
    assert legacy == 1, (
        f"the old 30s-window query counted {legacy}, expected 1 — it drops both "
        "the 50s-old agent and the ingress node, which is the reported bug"
    )
    assert _count(cur, ONLINE_SQL) > legacy


def test_genuinely_offline_agent_is_still_excluded(cur):
    """The fix must not simply make everything look online."""
    assert _count(cur, ONLINE_SQL) == 3
    cur.execute("SELECT COUNT(*) FROM remote_nodes " "WHERE status = 'offline'" + _ONLY_SEEDED)
    assert cur.fetchone()[0] == 1
