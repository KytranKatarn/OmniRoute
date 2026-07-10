"""Unit tests for cloud/contractor per-agent attribution (C.R.E.E.D.
accounting-integrity Fix #3).

Bug: when the DHQ dispatcher escalates to a cloud/contractor provider because
NO single internal agent could be matched (department capacity exhausted —
see ``dispatch()``'s "not agent and department_exhausted" branch), the
resulting ``task_execution_log`` row was logged with ``agent_id=None`` and a
synthetic ``agent_name`` (``"CONTRACTOR→x"`` / ``"CLOUD→x"``). Tokens were
still counted globally, but no real agent's per-agent K.I.N./budget view
(``services.agent_load_service.get_agent_load``, which JOINs
``task_execution_log`` on ``agent_id``) ever saw that cloud spend.

Fix: ``resolve_department_escalation_owner()`` picks the blocked
department's AI director as a best-effort proxy owner (pure function, no DB).
The escalation call sites stash it on ``DispatchResult.escalating_agent_id``/
``escalating_agent_name`` (new optional fields, default ``None`` — backward
compatible with every other ``DispatchResult(...)`` construction in the
file). ``_log_execution`` uses those two fields ONLY to choose what gets
written into the ``task_execution_log`` INSERT (``log_agent_id``/
``log_agent_name``) — ``result.agent_id``/``result.agent_name`` themselves are
left untouched, so welfare update, agent memory, performance-metric
crediting, and the Claude/Telegram notify path are byte-for-byte unchanged.
``worker_type`` stays ``'contract'`` for these rows (still derived from
``metadata.is_cloud``), so the carbon-accounting exclusion
(``worker_type IS DISTINCT FROM 'contract'``) is untouched.

Run from platform_v2/:
    docker exec archie_platform python3 -m pytest tests/test_dispatch_cloud_attribution.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import db  # noqa: F401 - the real container provides this; harmless if present
except ModuleNotFoundError:
    # Bare/dev checkouts outside the docker container have no top-level `db`
    # module on sys.path (department_dispatcher.py does `from db import
    # _get_db_password` at module load time - pre-existing, unrelated to this
    # fix). Provide a minimal stand-in so this test is importable/runnable
    # there too; inside the real container this branch never executes.
    import types

    _db_shim = types.ModuleType("db")
    _db_shim._get_db_password = lambda: ""  # type: ignore[attr-defined]
    _db_shim.get_db = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["db"] = _db_shim

from tools.department_hq.services.department_dispatcher import (  # noqa: E402
    DispatchResult,
    resolve_department_escalation_owner,
)


# ---------------------------------------------------------------------------
# resolve_department_escalation_owner — pure function, no DB, no self
# ---------------------------------------------------------------------------


def _cache(**agents):
    """Build an agent_cache dict shaped like DepartmentDispatcher._agent_cache
    (name -> {id, department, is_department_ai, ...})."""
    return agents


class TestResolveDepartmentEscalationOwner:
    def test_finds_the_department_director(self):
        cache = _cache(
            **{
                "F.O.R.G.E.": {
                    "id": 42,
                    "department": "Engineering & Technology",
                    "is_department_ai": True,
                },
                "P.R.O.B.E.": {
                    "id": 43,
                    "department": "Engineering & Technology",
                    "is_department_ai": False,
                },
            }
        )
        agent_id, agent_name = resolve_department_escalation_owner(cache, "Engineering & Technology")
        assert agent_id == 42
        assert agent_name == "F.O.R.G.E."

    def test_ignores_non_director_agents_in_the_same_department(self):
        cache = _cache(
            **{
                "P.R.O.B.E.": {
                    "id": 43,
                    "department": "Engineering & Technology",
                    "is_department_ai": False,
                },
            }
        )
        assert resolve_department_escalation_owner(cache, "Engineering & Technology") == (None, None)

    def test_fails_open_on_missing_department(self):
        cache = _cache(
            **{
                "F.O.R.G.E.": {
                    "id": 42,
                    "department": "Engineering & Technology",
                    "is_department_ai": True,
                },
            }
        )
        assert resolve_department_escalation_owner(cache, None) == (None, None)
        assert resolve_department_escalation_owner(cache, "") == (None, None)
        assert resolve_department_escalation_owner(cache, "Creative & Design") == (None, None)

    def test_fails_open_on_empty_cache(self):
        assert resolve_department_escalation_owner({}, "Engineering & Technology") == (None, None)

    def test_tolerates_malformed_cache_entries(self):
        """A non-dict cache value must never raise — fail-open, matching the
        rest of the dispatcher's defensive style."""
        cache = _cache(
            **{
                "GHOST": None,
                "F.O.R.G.E.": {"id": 42, "department": "Engineering & Technology", "is_department_ai": True},
            }
        )
        assert resolve_department_escalation_owner(cache, "Engineering & Technology") == (42, "F.O.R.G.E.")


# ---------------------------------------------------------------------------
# DispatchResult — new fields are additive/backward-compatible
# ---------------------------------------------------------------------------


class TestDispatchResultEscalatingFields:
    def test_defaults_to_none_for_every_existing_call_site(self):
        result = DispatchResult(success=True, response="ok", agent_name="F.O.R.G.E.", agent_id=7)
        assert result.escalating_agent_id is None
        assert result.escalating_agent_name is None

    def test_carries_the_proxy_owner_when_set(self):
        result = DispatchResult(
            success=True,
            response="ok",
            agent_name="CONTRACTOR→OpenAI",
            agent_id=None,
            metadata={"is_cloud": True},
            escalating_agent_id=42,
            escalating_agent_name="F.O.R.G.E.",
        )
        assert result.escalating_agent_id == 42
        assert result.escalating_agent_name == "F.O.R.G.E."
        # The orphaned-cloud shape is untouched — agent_id stays None so every
        # OTHER consumer of result.agent_id (welfare, memory, perf metrics)
        # behaves exactly as it did before this fix.
        assert result.agent_id is None
        assert result.agent_name == "CONTRACTOR→OpenAI"


# ---------------------------------------------------------------------------
# The exact attribution logic _log_execution applies to the INSERT tuple.
# Mirrors (does not re-import, since it's inline in a DB-touching method) the
# few lines in department_dispatcher.DepartmentDispatcher._log_execution that
# compute log_agent_id/log_agent_name from a DispatchResult.
# ---------------------------------------------------------------------------


def _compute_log_attribution(result: DispatchResult) -> tuple:
    """Same logic as _log_execution's log_agent_id/log_agent_name derivation."""
    meta = result.metadata or {}
    is_contractor = meta.get("is_cloud", False)
    log_agent_id = result.agent_id
    log_agent_name = result.agent_name
    if is_contractor and getattr(result, "escalating_agent_id", None):
        log_agent_id = result.escalating_agent_id
        esc_name = result.escalating_agent_name or "?"
        log_agent_name = f"{esc_name} →{result.agent_name}" if result.agent_name else esc_name
    worker_type = "contract" if is_contractor else "internal"
    return log_agent_id, log_agent_name, worker_type


class TestLogExecutionAttribution:
    def test_orphaned_cloud_dispatch_attributes_to_the_director_and_stays_contract(self):
        """The bug, reproduced and fixed: a contractor escalation with no
        internal agent selected (agent_id=None, synthetic agent_name) now logs
        the department director's real agent_id — while worker_type stays
        'contract' so carbon-accounting's exclusion is unaffected."""
        result = DispatchResult(
            success=True,
            response="ok",
            agent_name="CONTRACTOR→OpenAI",
            agent_id=None,
            metadata={"is_cloud": True, "escalation": "contractor_capability"},
            escalating_agent_id=42,
            escalating_agent_name="F.O.R.G.E.",
        )
        log_agent_id, log_agent_name, worker_type = _compute_log_attribution(result)

        assert log_agent_id == 42, "cloud spend must be attributed to a real agent, not NULL"
        assert log_agent_name == "F.O.R.G.E. →CONTRACTOR→OpenAI"
        assert worker_type == "contract", "must stay 'contract' so carbon-accounting keeps excluding it"

    def test_no_director_available_falls_back_to_the_old_shape(self):
        """Fail-open: if resolve_department_escalation_owner found no director,
        the row logs exactly as it did before this fix (agent_id=None)."""
        result = DispatchResult(
            success=True,
            response="ok",
            agent_name="CLOUD→llama3.1:8b",
            agent_id=None,
            metadata={"is_cloud": True},
            escalating_agent_id=None,
            escalating_agent_name=None,
        )
        log_agent_id, log_agent_name, worker_type = _compute_log_attribution(result)

        assert log_agent_id is None
        assert log_agent_name == "CLOUD→llama3.1:8b"
        assert worker_type == "contract"

    def test_normal_internal_dispatch_is_completely_unaffected(self):
        """A regular local dispatch (is_cloud not set) never touches the new
        fields — byte-for-byte identical to pre-fix behaviour."""
        result = DispatchResult(
            success=True,
            response="ok",
            agent_name="F.O.R.G.E.",
            agent_id=7,
            metadata={"department": "Engineering & Technology"},
        )
        log_agent_id, log_agent_name, worker_type = _compute_log_attribution(result)

        assert log_agent_id == 7
        assert log_agent_name == "F.O.R.G.E."
        assert worker_type == "internal"

    def test_fleet_node_dispatch_with_real_agent_id_is_unaffected(self):
        """Fleet-node dispatch (provider='fleet_node') is not cloud — is_cloud
        is not set, so this fix must not alter its attribution at all,
        regardless of whether escalating_agent_id happens to be set."""
        result = DispatchResult(
            success=True,
            response="ok",
            agent_name="F.O.R.G.E.",
            agent_id=7,
            provider="fleet_node",
            metadata={"is_remote": True},
        )
        log_agent_id, log_agent_name, worker_type = _compute_log_attribution(result)

        assert log_agent_id == 7
        assert log_agent_name == "F.O.R.G.E."
        assert worker_type == "internal"
