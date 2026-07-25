"""A blocked delegation must always carry a reason.

17 tasks sat in the DHQ Dispatch panel marked 'blocked' with an EMPTY blockers field.
The reason existed in both code paths — it was written to work_notes and simply never
stamped on the row the panel reads. The cost was not cosmetic: with no reason on the
row, a FALSE block (#5116/#5118, blocked while their QA work had actually succeeded)
was indistinguishable from a real failure, so nobody could triage the queue.

The invariant these tests pin: the reason is never empty, and it never silently
swallows the attempt context that tells you whether a retry is left.
"""

from services.delegation_service import _blocker_reason


class TestNeverEmpty:
    def test_normal_error_is_preserved(self):
        out = _blocker_reason("dispatcher returned no agent", 1, 3)
        assert "dispatcher returned no agent" in out

    def test_empty_error_still_yields_a_reason(self):
        # The whole point: writing nothing is what broke triage.
        out = _blocker_reason("", 2, 3)
        assert out.strip()
        assert "no error text" in out

    def test_none_error_still_yields_a_reason(self):
        out = _blocker_reason(None, 1, 3)
        assert out.strip()
        assert "no error text" in out

    def test_whitespace_only_error_counts_as_empty(self):
        out = _blocker_reason("   \n\t ", 1, 3)
        assert "no error text" in out


class TestAttemptContext:
    def test_reports_attempt_and_cap(self):
        # "attempt 2 of 3" tells the owner a retry remains — the actionable part.
        assert "attempt 2 of 3" in _blocker_reason("boom", 2, 3)

    def test_uncapped_omits_the_of_clause(self):
        out = _blocker_reason("boom", 4, 0)
        assert "attempt 4" in out
        assert " of " not in out


class TestBounding:
    def test_long_error_is_truncated_not_dropped(self):
        # A stack trace must not bloat every row, but must not vanish either.
        out = _blocker_reason("E" * 5000, 1, 3)
        assert len(out) < 500
        assert out.startswith("E")
        assert "..." in out
        assert "attempt 1 of 3" in out

    def test_result_is_a_single_line_string(self):
        assert isinstance(_blocker_reason("x", 1, 1), str)
