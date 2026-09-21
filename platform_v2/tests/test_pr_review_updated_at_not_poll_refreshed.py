"""`pr_reviews.updated_at` must mean "the review moved", never "we polled".

Measured 2026-09-20. The poll upsert in `pr_review_service.sync_open_prs` carried
`updated_at = NOW()` in its ON CONFLICT DO UPDATE SET, beside the column that
actually exists for poll bookkeeping (`last_polled_at`). Three consumers read
`updated_at` as a staleness clock:

    get_pending_reviews  (~L436)   retry an in_progress row after 20 minutes
    reap_stale_reviews   (~L994)   recover a dead review after 20 minutes
    review_progress      (~L1310)  elapsed time rendered in the Repair Bay UI

Both recovery paths ALSO filter `state = 'open'` — precisely the population the
upsert re-stamps every cycle — so `updated_at < NOW() - 20 min` was unreachable
for them and neither could ever fire. Evidence at the time: PR #3411 sat
'in_progress' for 6+ hours with reap_count = 0 (never reaped once), and four rows
spanning BOTH 'in_progress' and 'reviewed' shared a single updated_at to the
millisecond. A FINISHED review being re-stamped is the part with no innocent
explanation — nothing but a bulk poll writes a terminal row.

A source scan rather than a behavioural test on purpose: the defect lives in a SQL
string literal, so the only thing that can regress is that string. The same style
guards the merge-state UI rule in test_merge_state_ui.py.
"""

from __future__ import annotations

import os
import re

SERVICE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tools",
    "repair_bay",
    "services",
    "pr_review_service.py",
)


def _source() -> str:
    with open(SERVICE, "r") as fh:
        return fh.read()


def _upsert_set_block(src: str) -> str:
    """The ON CONFLICT ... DO UPDATE SET body of the pr_reviews poll upsert.

    Bounded at the next statement terminator so the scan cannot silently widen
    into unrelated SQL and start passing for the wrong reason.
    """
    start = src.index("ON CONFLICT (pr_number, repo) DO UPDATE SET")
    tail = src[start:]
    end = tail.index('"""')
    return tail[:end]


def test_the_poll_upsert_does_not_refresh_updated_at():
    block = _upsert_set_block(_source())
    # Only ASSIGNMENTS count — the explanatory comment names the column many times.
    assignments = [
        line
        for line in block.splitlines()
        if re.search(r"^\s*updated_at\s*=", line) and "--" not in line.split("updated_at")[0]
    ]
    assert not assignments, (
        "the poll upsert assigns updated_at, which disables the 20-minute staleness "
        f"clock for every OPEN pr: {assignments}"
    )


def test_the_poll_upsert_still_records_that_it_polled():
    # Removing the symptom must not remove the bookkeeping. last_polled_at is the
    # right column for "we polled"; if it went too, nothing would record the poll.
    block = _upsert_set_block(_source())
    assert re.search(
        r"^\s*last_polled_at\s*=\s*NOW\(\)", block, re.M
    ), "last_polled_at = NOW() must remain — it is where poll freshness belongs"


def test_the_staleness_consumers_still_read_updated_at():
    # Pins the PAIRING. The fix above is only meaningful while these readers exist;
    # if a future change moves them to another column, this guard should be revisited
    # deliberately rather than left passing vacuously.
    src = _source()
    assert "AND updated_at < NOW() - INTERVAL '20 minutes'" in src, "get_pending_reviews retry window"
    assert "AND updated_at < NOW() - make_interval(mins => %s)" in src, "reap_stale_reviews window"


def test_both_recovery_paths_are_scoped_to_open_prs():
    # Why the bug was total rather than partial: the two recovery paths look ONLY at
    # open PRs, which is exactly the set the poll upsert touches. Documented here so
    # the interaction is not rediscovered from scratch.
    src = _source()
    assert src.count("state = 'open'") >= 2
