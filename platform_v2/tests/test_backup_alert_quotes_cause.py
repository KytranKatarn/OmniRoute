"""A backup-posture alert must QUOTE the recorded failure, not just count failures.

BACKGROUND (#5619). On 2026-08-15 the off-site gdrive tier had been dead for 440 hours. The
alert fired correctly and named the stale tier — then offered only STATIC advice whose most
prominent suggestion was "check the account storage quota". That was wrong, and an
investigation followed it for the better part of an hour.

Every one of the 43 failed rows already held the answer in `backup_log.error_message`:

    Work Suite Drive creds unavailable, falling through:
    ('invalid_grant: Bad Request', {'error': 'invalid_grant', ...})

An expired OAuth refresh token, not a full Drive. The cause was one column away from the alert
and nothing read it. (The 1.8 GB dump later uploading fine is the disproof of quota: a
quota-bound tier rejects the large object while small files still fit.)

⚠️ TRAP THAT COST TIME: `backup_log` has BOTH `notes` and `error_message`. The failure text
lives in `error_message`; `notes` is unused for errors. Querying `notes` returns NULL and looks
exactly like "nothing was recorded" — which is what I initially and wrongly concluded.

⚠️ WHY THESE TESTS TARGET PURE FUNCTIONS, NOT check_backup_posture():
pytest's conftest points at a TEST database with no `backup_log` rows. Every tier therefore
reports `unknown` and no alert is emitted, so an end-to-end assertion like "a fresh tier
produces no alert" PASSES WITHOUT EXERCISING ANYTHING. An earlier draft of this file did
exactly that. `short_cause` / `cause_line` are the real decision points and are DB-free.
Live behaviour was additionally verified by hand against the production DB (gdrive quoted
`invalid_grant`; vps correctly reported no recorded cause).
"""

import sys

import pytest

sys.path.insert(0, "/app")

from services.backup_posture_monitor import _CAUSE_MAX, cause_line, short_cause  # noqa: E402


# Verbatim shape of the live gdrive row: actionable sentence, then a long traceback.
_GDRIVE_REAL = (
    "Work Suite Drive creds unavailable, falling through: ('invalid_grant: Bad Request', "
    "{'error': 'invalid_grant', 'error_description': 'Bad Request'})\n"
    "Traceback (most recent call last):\n"
    '  File "/app/tools/google_work_suite/services/drive_service.py", line 88, in _client\n'
    "    creds.refresh(Request())\n" + ("  padding padding padding\n" * 40)
)


class TestShortCause:
    def test_cause_survives_an_appended_traceback(self):
        """THE REGRESSION: a traceback must not evict the real cause from the budget."""
        out = short_cause(_GDRIVE_REAL)
        assert "invalid_grant" in out, "the real cause was pushed out of the message"
        assert "Traceback" not in out
        assert "padding" not in out
        assert len(out) <= _CAUSE_MAX

    def test_traceback_only_message_still_yields_text(self):
        """A message with no prose head must not render blank — blank reads as 'no cause'."""
        out = short_cause("Traceback (most recent call last):\n  File x\n  ValueError: boom")
        assert out.strip(), "an error with no prose head produced an empty cause"

    def test_is_bounded(self):
        assert len(short_cause("x" * 5000)) <= _CAUSE_MAX

    def test_newlines_are_collapsed(self):
        """The body is a single Telegram message; embedded newlines break its shape."""
        assert "\n" not in short_cause("line one\nline two\nline three")

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_empty_inputs_are_falsy(self, empty):
        assert not short_cause(empty).strip()


class TestCauseLine:
    def test_quotes_the_cause_when_one_exists(self):
        line = cause_line(short_cause(_GDRIVE_REAL))
        assert "RECORDED CAUSE" in line
        assert "invalid_grant" in line

    def test_is_honest_when_no_cause_is_recorded(self):
        """The vps tier's historical rows are all NULL. Say so, and name the file that has it.

        Never imply the DB holds an answer it does not — that is the failure this fixes.
        """
        line = cause_line(None)
        assert "No error_message recorded" in line
        assert "archie_backup.log" in line, "must point at where the cause actually is"
        assert "RECORDED CAUSE" not in line

    @pytest.mark.parametrize("blank", [None, "", 0])
    def test_all_falsy_causes_take_the_honest_branch(self, blank):
        assert "No error_message recorded" in cause_line(blank)

    def test_the_two_branches_are_distinguishable(self):
        """A reader must be able to tell 'we know why' from 'we do not know why'."""
        assert cause_line("boom") != cause_line(None)
