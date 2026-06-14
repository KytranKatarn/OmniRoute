"""Regression guard for the K.I.N. welfare token-keying fix (2026-06-13).

~48% of `task_execution_log` rows logged a NULL `agent_id` (fleet-dispatched work via
fleet_mesh_routes / fleet_node_routes), so `get_welfare_cache`'s old `GROUP BY agent_id`
undercounted real 24h token usage and the #4090 dispatch throttle never fired on
over-budget agents (V.E.R.I.F.Y. read 15% of its true tokens → 0.15 instead of 1.62).

The fix resolves identity by `COALESCE(agent_id, agents.id by name)` and strips the
' (CLI)' telemetry suffix so external CLI workers join their roster row. This test locks
that in so a refactor can't silently revert to agent_id-only keying.

Behavioral proof was live: post-fix `get_welfare_cache()` showed P.R.O.O.F. 2.50 /
V.E.R.I.F.Y. 1.62 (THROTTLED). A full DB behavioral test belongs in the archie_test-backed
P.R.O.B.E. suite.
"""

import inspect

from services.agent_service import _TOKENS_24H_SUBQUERY, get_welfare_cache


def test_get_welfare_cache_resolves_token_usage_by_name_not_just_agent_id():
    # FIX-2 (#4130): the 24h token source moved into the shared
    # _TOKENS_24H_SUBQUERY constant so the dispatch throttle, the K.I.N. rollup
    # and the per-agent outliers all read ONE definition and can't drift apart.
    # get_welfare_cache must reference the shared constant...
    assert "_TOKENS_24H_SUBQUERY" in inspect.getsource(get_welfare_cache)
    # ...and the canonical source must keep the NULL-agent_id name-lookup keying.
    sub = _TOKENS_24H_SUBQUERY
    # Identity resolved by id OR name (so rows with a NULL agent_id still count).
    assert "COALESCE(t.agent_id" in sub, "must COALESCE agent_id with a name lookup"
    # CLI telemetry suffix stripped so '<Name> (CLI)' rows join the plain roster name.
    assert "split_part(t.agent_name, ' (CLI)', 1)" in sub
    # Grouping is by the resolved identity, not the raw (often-NULL) agent_id.
    assert "GROUP BY COALESCE(t.agent_id" in sub
