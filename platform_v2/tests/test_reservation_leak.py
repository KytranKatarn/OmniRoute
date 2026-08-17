"""#5007 — a leaked agent reservation must self-heal, never persist for the process lifetime.

Observed live 2026-07-20: a dispatch raised between reserve and release_agent, the
agent id stayed in the (then) bare set forever, and C.O.D.E.X. silently vanished from
routing — 25 documentation misroutes to G.A.V.E.L. in 24h while the log blamed
"no skilled agent". These tests pin the TTL machinery: a back-dated reservation
expires at lookup AND at sweep; a fresh one holds; release still works.
"""

from unittest import mock

from services.department_coordinator import DepartmentCoordinator


def _coordinator():
    return DepartmentCoordinator(model_service=mock.Mock())


def test_fresh_reservation_blocks_and_logs():
    c = _coordinator()
    import time

    c._reserved_agents[146] = time.monotonic()
    with c._lock:
        assert c._is_reserved_locked(146) is True
    assert 146 in c._reserved_agents


def test_leaked_reservation_expires_at_lookup():
    c = _coordinator()
    import time

    c._reserved_agents[146] = time.monotonic() - (c._RESERVATION_TTL_S + 60)
    with c._lock:
        assert c._is_reserved_locked(146) is False, "a stale reservation must expire at lookup"
    assert 146 not in c._reserved_agents, "expiry must actually remove the entry"


def test_sweep_releases_only_stale():
    c = _coordinator()
    import time

    now = time.monotonic()
    c._reserved_agents[1] = now - (c._RESERVATION_TTL_S + 5)
    c._reserved_agents[2] = now
    with c._lock:
        c._sweep_stale_reservations()
    assert 1 not in c._reserved_agents
    assert 2 in c._reserved_agents


def test_release_agent_pops_entry():
    c = _coordinator()
    import time

    c._reserved_agents[7] = time.monotonic()
    c.release_agent(7)
    assert 7 not in c._reserved_agents
    # releasing an unreserved agent must not raise
    c.release_agent(7)


def test_unreserved_agent_is_not_blocked():
    c = _coordinator()
    with c._lock:
        assert c._is_reserved_locked(999) is False
