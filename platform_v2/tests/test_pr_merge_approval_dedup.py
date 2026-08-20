"""pr_merge approvals must dedup per-PR, not per-action_type (#5829).

The coarse action_type-only dedup meant ONLY ONE PR could await approval at a
time. Measured 2026-08-19: 108 PRs flagged kytran_approval_sent, 78 with a row.
While #2703's approval sat pending 19:32-22:41, the escalations for
#2697/#2705/#2706/#2700/#2707 all evaporated — and were still marked as asked.

Third occurrence of this trap; the docstring in _check_existing_approval already
records it for contractor_dispatch and linkedin_post (#3944).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai_bridge.agent_loop import _check_existing_approval  # noqa: E402


class _Cur:
    """Records the SQL + params, returns a canned row."""

    def __init__(self, row=None):
        self.row, self.sql, self.params = row, None, None

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params

    def fetchone(self):
        return self.row


def test_same_pr_is_deduped():
    cur = _Cur(row=(1,))
    assert _check_existing_approval("pr_merge", {"pr_number": 2709}, cur) is True
    assert "action_data->>'pr_number'" in cur.sql
    assert cur.params == ("pr_merge", "2709")


def test_a_DIFFERENT_pr_is_not_deduped():
    """The actual bug: PR B was dropped because PR A was pending."""
    cur = _Cur(row=None)
    assert _check_existing_approval("pr_merge", {"pr_number": 2710}, cur) is False


def test_pr_number_is_compared_as_text():
    """action_data->>'pr_number' yields TEXT; comparing to an int silently matches
    nothing, which would disable dedup and queue duplicates for the same PR."""
    cur = _Cur(row=(1,))
    _check_existing_approval("pr_merge", {"pr_number": 2709}, cur)
    assert cur.params[1] == "2709" and isinstance(cur.params[1], str)


def test_missing_pr_number_falls_back_to_coarse_dedup_not_bypass():
    """A payload without pr_number must NOT skip dedup entirely — same fallback
    rule contractor_dispatch uses. It falls through to the coarse query."""
    cur = _Cur(row=(1,))
    assert _check_existing_approval("pr_merge", {}, cur) is True
    assert "action_data->>'pr_number'" not in (cur.sql or "")


def test_other_action_types_are_untouched():
    cur = _Cur(row=(1,))
    assert _check_existing_approval("deploy_approve", {"pr_number": 1}, cur) is True
    assert "action_data->>'pr_number'" not in (cur.sql or "")
