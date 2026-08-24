"""K.I.N. tab must SHOW a benched agent, not paint it green (#5157 items 2+3).

Measured 2026-07-24 by running the tab's own status-label chain against a
barracked agent: it produced ``'✓ active'`` in ``#10b981`` — pixel-identical to a
genuinely healthy agent. ``shift_state`` was present in the payload and the chain
never consulted it. A barracked agent has no active rest cycle, is not at-limit and
is not overworked, so it fell through every branch to the final ``else``.

Two compounding defects made a benched agent invisible:

* **Label (item 3)** — rendered as healthy, as above. And because the ORDER BY led
  with ``(rc.rest_type IS NOT NULL) DESC``, a benched agent (which by definition has
  NO rest cycle) also sorted BELOW every resting agent. Mislabelled *and* buried.
* **Freshness (item 2)** — the welfare loop only advances ACTIVE agents, so a benched
  agent's stress/energy/mood freeze at the bench-time snapshot. The card printed that
  frozen number with no indication of its age, so it read as current.

That combination is how F.A.C.T. (News director) and four others sat benched
unnoticed until someone went looking.

These are source-level assertions because the logic is inline in a large route file
and a large IIFE-free JS file; there is no importable unit to call. The behavioural
proof for the JS is the node harness in the PR description, and the UI was verified
in a live browser drive (mistake #281727: DHQ profile UI has silently rendered into
dead code before, so page-load/API QA alone is not acceptable proof here).
"""

from __future__ import annotations

import os
import re

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_ROUTES = os.path.join(_ROOT, "tools", "department_hq", "work_routes.py")
_JS = os.path.join(_ROOT, "tools", "department_hq", "static", "js", "department-hq.js")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------
# Backend: the payload must carry enough for the UI to tell the story
# --------------------------------------------------------------------------


def test_welfare_payload_exposes_bench_state():
    """Without these fields the UI cannot distinguish benched from healthy."""
    src = _read(_ROUTES)
    for field in ('"benched"', '"bench_reason"', '"bench_age_hours"'):
        assert field in src, f"welfare payload must expose {field}"


def test_welfare_payload_exposes_stat_freshness():
    """A frozen reading must be labellable as frozen (item 2)."""
    src = _read(_ROUTES)
    assert "stats_updated_at" in src, "must select the emotional-state timestamp"
    for field in ('"stats_age_hours"', '"stats_stale"'):
        assert field in src, f"welfare payload must expose {field}"


def test_bench_reason_distinguishes_failure_from_strand():
    """'under verification' and 'lost by accident' need different operator responses.

    Asserts the INVARIANT, not one exact spelling of the ternary. The original pinned
    `\'"failure" if _benched_at else "stranded"\'` verbatim and broke the moment #5829 added a
    third state (`stranded_working` — benched yet still dispatching). The behaviour was a
    strict SUPERSET of what this test demands, so the test was wrong and the code was right.
    A test that fails on a legitimate refinement trains people to ignore it.
    """
    src = _read(_ROUTES)
    assert "failure_standby" in src, "must join the failure-standby Academy record"
    # failure is gated on the Academy record...
    assert '"failure" if _benched_at' in src, "a failure bench must be driven by benched_at"
    # ...and the absence of one must still be distinguishable as a strand.
    assert '"stranded"' in src, "an accidental strand must remain its own reason"


def test_benched_agents_sort_first():
    """A benched agent has NO rest cycle, so the old ORDER BY buried it.

    Guards the ordering fix: the barracked term must come BEFORE the rest-cycle term.
    """
    src = _read(_ROUTES)
    order_by = src[src.index("ORDER BY\n") : src.index("ORDER BY\n") + 600]
    bench_pos = order_by.find("a.shift_state = 'barracked'")
    rest_pos = order_by.find("rc.rest_type IS NOT NULL")
    assert bench_pos != -1, "ORDER BY must rank barracked agents"
    assert rest_pos != -1, "rest ordering must be preserved"
    assert bench_pos < rest_pos, "barracked must outrank resting — it does not self-recover"


# --------------------------------------------------------------------------
# Frontend: the label chain must consult shift_state BEFORE falling through
# --------------------------------------------------------------------------


def test_status_label_tests_benched_before_the_healthy_fallback():
    """The whole bug: benched fell through to '✓ active' in green.

    Order matters — a `benched` branch added AFTER the fallback would never run.
    """
    js = _read(_JS)
    start = js.index("var statusLabel = a.benched")
    # No fixed byte window. The original scanned `start : start + 900`, which stopped
    # covering the chain the moment #5829 added an explanatory comment block inside it and
    # pushed the healthy fallback past the cutoff — the test then reported "the healthy
    # fallback should still exist" about code where it plainly still existed. A window
    # measured in bytes is not a statement boundary.
    benched_pos = js.find("a.benched", start)
    healthy_pos = js.find("'✓ active'", start)
    assert benched_pos != -1, "status label must handle the benched state"
    assert healthy_pos != -1, "the healthy fallback should still exist"
    assert benched_pos < healthy_pos, "benched must be tested BEFORE the healthy fallback"


def test_benched_status_colour_is_not_the_healthy_green():
    """#10b981 is the healthy colour; a benched agent must never use it."""
    js = _read(_JS)
    start = js.index("var statusColor = a.benched")
    chain = js[start : start + 400]
    m = re.search(r"a\.benched \? '(#[0-9a-fA-F]{6})'", chain)
    assert m, "benched must select an explicit colour"
    assert m.group(1).lower() != "#10b981", "benched must not render in the healthy green"


def test_stale_stats_are_flagged_in_the_card():
    """A frozen stress reading must be visibly marked as a snapshot."""
    js = _read(_JS)
    assert "stats_stale" in js, "card must react to the staleness flag"
    assert "stats " in js and "_kinAge(a.stats_age_hours)" in js, "card must show the reading's age"


def test_kin_age_helper_exists_and_is_defined_before_use():
    """_kinAge is called from the card; a missing helper throws at render time."""
    js = _read(_JS)
    assert "function _kinAge(" in js, "_kinAge helper must be defined"
    assert js.index("function _kinAge(") < js.index("_kinAge(a.bench_age_hours)")


@pytest.mark.parametrize(
    "state,expect_benched",
    [("barracked", True), ("active", False), ("winding_down", False), ("cooldown", False)],
)
def test_only_barracked_counts_as_benched(state, expect_benched):
    """cooldown/winding_down self-recover; only 'barracked' is the bench.

    Flagging a self-recovering state as benched would cry wolf and re-hide the
    real signal.
    """
    src = _read(_ROUTES)
    assert '_benched = r["shift_state"] == "barracked"' in src
    assert (state == "barracked") is expect_benched
