"""Regression: K.I.N. Welfare subtab must show BOUNDED rests + not stack overlaps (2026-06-08).

Two bug classes fixed:
1. The welfare query's rest LATERAL used `ended_at IS NULL` only, so bounded COO/approved
   8h rests (ended_at = NOW()+8h) were invisible → resting agents showed no card/timer.
2. The overlap guards used `started_at > NOW() - INTERVAL '30 minutes'`, so a long rest
   started >30 min ago slipped past and a second cycle stacked (over-benching the agent).
"""

from __future__ import annotations

import os

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_welfare_query_matches_bounded_rests_and_sends_rest_until():
    src = _read("tools/department_hq/work_routes.py")
    assert "ended_at IS NULL OR ended_at > NOW()" in src, "welfare rest LATERAL must match bounded rests"
    assert "rest_until" in src, "welfare payload must surface the rest end time for the countdown"


def test_overlap_guards_dont_use_the_flawed_30min_window():
    flawed = "AND started_at > NOW() - INTERVAL '30 minutes'"
    checked = 0
    for rel in (
        "tools/department_hq/approvals_routes.py",
        "services/agent_jobs.py",
        "../ai_bridge/telegram_gateway.py",  # may be off-path inside the container
    ):
        path = os.path.join(_ROOT, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            assert flawed not in fh.read(), f"{rel} still has the flawed 30-min overlap guard"
        checked += 1
    assert checked >= 2, "expected at least the two platform-side guards to be checked"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
