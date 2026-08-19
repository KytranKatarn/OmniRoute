"""Bench-integrity detector (#5829) — pure decision table, no DB.

Pins the real incident of 2026-08-19: four agents flagged 'barracked' while
logging 855 runs/24h between them, with zero open rest cycles.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.bench_integrity import (  # noqa: E402
    BENCH_STATES,
    RESTING,
    STRANDED_IDLE,
    STRANDED_WORKING,
    classify_bench,
    is_contradiction,
    summarize,
)


def test_active_agent_is_not_benched_at_all():
    assert classify_bench("active", 0, 500) is None
    assert classify_bench("deployed", 0, 0) is None


def test_the_real_incident_is_caught():
    """P.U.B.L.I.S.H.: barracked, 0 open rest cycles, 582 runs."""
    assert classify_bench("barracked", 0, 582) == STRANDED_WORKING
    assert is_contradiction(classify_bench("barracked", 0, 582))


def test_a_genuine_rest_is_not_a_contradiction():
    """An open rest cycle OUTRANKS activity — a task begun before the bench may
    still log after it, and paging on that would train everyone to ignore this."""
    assert classify_bench("barracked", 1, 40) == RESTING
    assert not is_contradiction(classify_bench("barracked", 1, 40))


def test_quiet_bench_is_reported_but_never_alerted():
    """Benched, no rest cycle, no activity: suspicious, yet fully consistent with
    a deliberate manual bench. Report it; do not alert on it."""
    c = classify_bench("barracked", 0, 0)
    assert c == STRANDED_IDLE
    assert not is_contradiction(c)


def test_every_bench_state_is_covered_not_just_barracked():
    """off_duty / cooldown / winding_down hide the same contradiction."""
    for state in BENCH_STATES:
        assert classify_bench(state, 0, 10) == STRANDED_WORKING, state


def test_none_and_junk_states_are_safe():
    for value in (None, "", "nonsense"):
        assert classify_bench(value, 0, 99) is None


def test_summarize_counts_and_flags_health():
    rows = [
        {"name": "P.U.B.L.I.S.H.", "classification": STRANDED_WORKING, "runs_in_window": 582},
        {"name": "C.O.D.E.X.", "classification": STRANDED_WORKING, "runs_in_window": 173},
        {"name": "SLEEPY", "classification": RESTING, "runs_in_window": 0},
        {"name": "QUIET", "classification": STRANDED_IDLE, "runs_in_window": 0},
    ]
    out = summarize(rows)
    assert out["stranded_working"] == 2
    assert out["runs_stranded"] == 755
    assert out["resting"] == 1 and out["stranded_idle"] == 1
    assert out["healthy"] is False
    assert set(out["agents"]) == {"P.U.B.L.I.S.H.", "C.O.D.E.X."}


def test_a_clean_fleet_reports_healthy():
    out = summarize([{"name": "SLEEPY", "classification": RESTING, "runs_in_window": 0}])
    assert out["healthy"] is True and out["stranded_working"] == 0
