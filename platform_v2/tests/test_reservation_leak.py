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


# ---------------------------------------------------------------------------
# The CONTRACT (#5993). #5007 changed `_reserved_agents` from a bare set to a
# TTL map, and 30 test fixtures still built the old shape — they blew up with
# `AttributeError: 'set' object has no attribute 'get'` pointing at PRODUCTION
# code, which reads like a live dispatch bug until you check the live object.
#
# One shape change should fail in ONE obvious place, not 30 scattered ones.
# ---------------------------------------------------------------------------


def test_reserved_agents_is_a_MAPPING_of_agent_id_to_timestamp():
    """A set satisfies `in` but not `.get()` — which is exactly how #5993 hid.

    If a future change swaps the container again, this is the test that should
    fail first and say what the shape is supposed to be."""
    c = _coordinator()
    assert isinstance(c._reserved_agents, dict), (
        "_reserved_agents must be a Dict[int, float] (agent_id -> time.monotonic()); "
        "a set passes `in` checks but has no .get(), so _is_reserved_locked raises"
    )
    assert c._reserved_agents == {}, "a fresh coordinator must hold no reservations"


def test_the_production_write_site_stores_a_MONOTONIC_TIMESTAMP():
    """The TTL machinery does arithmetic on the value (`now - t`).

    A bool or None would satisfy an isinstance(dict) check and still break
    _sweep_stale_reservations() and _is_reserved_locked(). There is no
    reserve_agent() to call — the reservation is written inline inside
    select_agent — so this pins the WRITE SITE itself rather than a value a
    test hand-built, which would only prove the test's own assumption."""
    import inspect

    from services import department_coordinator

    src = inspect.getsource(department_coordinator)
    assert "self._reserved_agents[agent_id] = time.monotonic()" in src, (
        "the reservation write site changed shape — the value must stay a "
        "time.monotonic() float, because _is_reserved_locked and "
        "_sweep_stale_reservations subtract it from time.monotonic()"
    )


def test_no_test_fixture_rebuilds_the_pre_5007_SET_shape():
    """Grep guard. The 30 #5993 failures were all `_reserved_agents = set()` in fixtures.

    Asserted over the test tree because a stale fixture is invisible until the whole
    suite runs — and until 2026-08-24 the suite could not finish (#5998), so these sat
    undetected. This makes a revert fail loudly in one place instead of scattering."""
    import pathlib
    import re

    tests_dir = pathlib.Path(__file__).parent
    offenders = []
    for path in tests_dir.rglob("test_*.py"):
        if path.name == pathlib.Path(__file__).name:
            continue  # this file names the bad pattern on purpose, in prose
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"_reserved_agents\s*=\s*set\(", line):
                offenders.append(f"{path.name}:{i}")
    assert not offenders, (
        "_reserved_agents is a TTL map since #5007, not a set — these fixtures build "
        "the pre-#5007 shape and will raise AttributeError inside production code: " + ", ".join(offenders)
    )
