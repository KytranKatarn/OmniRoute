"""#5780 — a review row can reach a state NEITHER owner will finalize.

Two guards split responsibility for stuck rows and BOTH filter on state='open':

    sync_closed_prs      UPDATE ... WHERE repo = %s AND state = 'open'
    reap_stale_reviews   WHERE review_status='in_progress' AND state='open'
                         ("Only OPEN PRs are reaped (closed ones are handled by
                          sync_closed_prs)")

So a row that reaches state='closed' while still 'pending'/'in_progress' is owned by
neither and is stuck FOREVER. Measured 2026-08-22: 20 such rows, all dated 2026-05-31;
the in_progress one had sat 83 days on an already-MERGED PR. sync_closed_prs' own
comment already asserted the invariant ("must be terminated to 'skipped' — otherwise
they accumulate forever"); its WHERE clause did not enforce it.
"""

import pathlib
import re

import pytest

_SVC = pathlib.Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "services" / "pr_review_service.py"
_MDS = pathlib.Path(__file__).resolve().parents[1] / "services" / "model_dispatch_service.py"


def _sync_body() -> str:
    src = _SVC.read_text(encoding="utf-8")
    start = src.index("def sync_closed_prs(")
    return src[start : src.index("\ndef ", start + 10)]


def test_closed_rows_with_a_nonterminal_status_are_finalized():
    """THE FIX. There must be a statement that reaches rows ALREADY closed."""
    body = _sync_body()
    assert "state <> 'open'" in body, "nothing finalizes rows that are already closed"
    assert "review_status IN ('pending', 'in_progress')" in body


def test_the_finalize_is_not_gated_on_this_polls_open_set():
    """⚠️ `pr_number NOT IN %s` belongs to the FIRST statement (which transitions
    open->closed). Applying it to the orphan sweep would re-create the hole: a closed
    PR is closed regardless of whether it appeared in this poll."""
    body = _sync_body()
    orphan = body[body.index("state <> 'open'") - 400 : body.index("state <> 'open'") + 260]
    assert "NOT IN" not in orphan


def test_the_two_owners_still_have_complementary_filters():
    """If reap_stale_reviews ever drops its `state='open'` filter, the two would both
    claim closed rows. The split is fine; the GAP between them was the bug."""
    src = _SVC.read_text(encoding="utf-8")
    reaper = src[src.index("def reap_stale_reviews(") :]
    reaper = reaper[: reaper.index("\ndef ", 10)]
    assert re.search(r"state\s*=\s*'open'", reaper), "reaper must still scope to open PRs"


def test_the_callback_shouts_when_it_matches_no_rows():
    """A zero-row UPDATE is a SILENT no-op: the review ran, the artifact exists, and the
    verdict is dropped — then the merge gate fails closed with no explanation."""
    body = _MDS.read_text(encoding="utf-8")
    seg = body[body.index('elif cb_type == "pr_review_result"') :][:2200]
    assert "cur.rowcount == 0" in seg
    assert "log.warning" in seg


def test_the_callback_does_not_try_to_self_repair():
    """It must REPORT the miss, not guess at a row to write instead — an UPDATE aimed at
    a guessed pr_number/repo would corrupt a different PR's verdict."""
    body = _MDS.read_text(encoding="utf-8")
    seg = body[body.index('elif cb_type == "pr_review_result"') :][:2200]
    assert seg.count("UPDATE pr_reviews") == 1


@pytest.mark.parametrize("count,expected", [(0, "reset"), (2, "reset"), (3, "skip"), (9, "skip")])
def test_reap_escalates_to_skip_rather_than_looping(count, expected):
    """Unchanged behaviour, pinned: a permanently-broken review must stop cycling
    pending<->in_progress forever."""
    import sys

    sys.path.insert(0, "/app")
    from tools.repair_bay.services.pr_review_service import decide_reap_action

    assert decide_reap_action(count) == expected
