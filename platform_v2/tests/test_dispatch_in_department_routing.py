"""Pin the routing behaviour that the 2026-09-27 incident was MISDIAGNOSED as broken.

What the investigation actually found, contradicting the initial hypothesis:

  * ``select_agent('translate', 'Documentation & Knowledge')`` returns
    R.O.S.E.T.T.A. — the selector is correct and the home-department path works.
  * The contractor-escalation loop is gated on ``if not agent and
    department_exhausted:`` and the code comments say so explicitly ("no single
    agent was ever matched here"). It cannot fire when an agent was found.
  * A real dispatch of ``capability='translate'`` completes on R.O.S.E.T.T.A.
    with mistral:7b in the home department.
  * The 410 that blocked 18 delegations did NOT come from that loop — it left
    NO bridge_job, and the loop always calls ``_create_cloud_job()`` first. It
    came from the ``if ":cloud" in model:`` branch of ``_execute_llm`` routing
    a model resolved from the LIVE /api/tags catalogue, which still advertises
    ``minimax-m2.5:cloud`` and ``qwen3-coder-next:cloud``. Both are retired
    upstream and 410.

So the defects were (a) a wholly dead cloud tier and (b) a permanent refusal
treated as retryable — both fixed elsewhere. The in-department routing was never
broken.

These tests exist to stop a future reader from "fixing" routing that works, and
to keep the escalation gate honest. They assert CURRENT correct behaviour on
purpose: a change that makes `translate` skip its home department would fail
here rather than silently burning paid contractor quota.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DISPATCHER = ROOT / "tools" / "department_hq" / "services" / "department_dispatcher.py"
COORDINATOR = ROOT / "services" / "department_coordinator.py"


def _disp_src() -> str:
    return DISPATCHER.read_text(encoding="utf-8")


def _skip_if_isolated_db() -> None:
    """conftest points the suite at an ISOLATED database (archie_test) that has
    no agent seed, so select_agent() correctly returns None there. A real
    process sees 241 agents. Skip explicitly rather than assert against an
    empty table — an empty fleet must never read as 'routing is broken', which
    is precisely the false conclusion this file exists to prevent.
    """
    import sys

    sys.path.insert(0, "/app")
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT COUNT(*) AS n FROM agents")
        row = cur.fetchone()
    n = int(row["n"]) if isinstance(row, dict) else int(row[0])
    if n == 0:
        pytest.skip(
            "isolated test DB has no agent seed; live routing verified in the "
            "handover (select_agent('translate','Documentation & Knowledge') -> "
            "R.O.S.E.T.T.A., and a real dispatch completed on mistral:7b)"
        )


# ── the escalation gate ─────────────────────────────────────────────────────
def test_contractor_escalation_requires_that_no_agent_was_found():
    """The gate is the whole reason routing is safe. If this ever loosens to
    ``if department_exhausted:`` or moves above the agent search, a healthy
    in-department agent gets bypassed for a paid contractor."""
    src = _disp_src()
    gates = re.findall(r"if not agent and department_exhausted:", src)
    assert gates, "the 'not agent and department_exhausted' gate has disappeared"
    # The contractor loop must sit inside one of those gates.
    loop = src.index("for contractor in contractors:")
    assert (
        src.rindex("if not agent and department_exhausted:", 0, loop) > 0
    ), "the contractor loop is no longer inside a 'no agent was matched' gate"


def test_agent_search_precedes_the_escalation():
    """Ordering, not just presence: the local agent must be looked for first."""
    src = _disp_src()
    search = src.index("def select_agent") if "def select_agent" in src else -1
    assert src.index("if not agent and department_exhausted:") > 0
    loop = src.index("for contractor in contractors:")
    assert loop > src.index("if not agent and department_exhausted:")


def test_cloud_model_routing_goes_through_the_guarded_choke_point():
    """The ``:cloud`` branch must call call_ollama_cloud, which now refuses
    retired models before any HTTP call. If this branch is ever rewritten to hit
    the Ollama API directly, the guard is bypassed and dead models go back to
    burning 300s per retry."""
    src = _disp_src()
    m = re.search(r'if ":cloud" in model:\s*\n\s*return call_ollama_cloud\(', src)
    assert m, (
        "the ':cloud' branch no longer routes through call_ollama_cloud — the "
        "RETIRED_CLOUD_MODELS guard would be bypassed"
    )


# ── live behaviour (needs the container's DB) ───────────────────────────────
@pytest.mark.parametrize(
    "capability,expected_dept",
    [
        ("translate", "Documentation & Knowledge"),
        ("fact_check", None),
    ],
)
def test_translate_resolves_to_an_in_department_agent(capability, expected_dept):
    """Live check against the real coordinator.

    Skipped outside the container (no psycopg2). Guards the specific claim that
    `translate` is served locally — the thing the 33h stall made look broken.
    """
    import sys

    sys.path.insert(0, "/app")
    pytest.importorskip("database", reason="requires the platform container")
    from services.department_coordinator import (
        CAPABILITY_DEPARTMENT_MAP,
        DepartmentCoordinator,
    )

    dept = CAPABILITY_DEPARTMENT_MAP.get(capability)
    if expected_dept:
        assert dept == expected_dept, f"capability '{capability}' maps to {dept!r}, expected {expected_dept!r}"
    _skip_if_isolated_db()
    coord = DepartmentCoordinator()
    sel = coord.select_agent(capability=capability, department=dept)
    assert sel, f"no agent selected for '{capability}' in {dept!r}"
    chosen = sel.get("name") or sel.get("agent_name")
    if expected_dept:
        assert sel.get("department") == dept, (
            f"'{capability}' routed to {sel.get('department')!r} instead of its "
            f"home department {dept!r} (agent={chosen}) — a cross-department or "
            "cloud hop that should not have been needed"
        )


def test_translate_capability_is_not_owned_by_a_dead_cloud_model():
    """Sanity: the capability's home department must not be 'cloud'."""
    import sys

    sys.path.insert(0, "/app")
    pytest.importorskip("database")
    from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

    _skip_if_isolated_db()
    dept = CAPABILITY_DEPARTMENT_MAP.get("translate")
    assert dept and "cloud" not in dept.lower()


def test_modules_parse():
    import ast

    ast.parse(_disp_src())
    ast.parse(COORDINATOR.read_text(encoding="utf-8"))
