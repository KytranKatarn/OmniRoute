"""#5942 — a green tile must mean "no findings", not "no RED findings"."""

import sys

sys.path.insert(0, "/app")

from services.code_metrics_service import audit_status_for  # noqa: E402

_RED = {"severity": "red", "code": "X"}
_YEL = {"severity": "yellow", "code": "LARGE_FILE"}
_INF = {"severity": "info", "code": "DEBUG_PRINT"}


def test_nothing_found_is_green():
    assert audit_status_for([]) == "completed"
    assert audit_status_for(None) == "completed"


def test_findings_without_red_are_no_longer_green():
    """THE DEFECT. Measured in code_audit_log: 16 of 34 `completed` modules carried
    findings and rendered clean — e.g. faith, issues_found 0, notes
    "LARGE_FILE: routes.py (1553 lines)"."""
    assert audit_status_for([_YEL]) == "findings_open"
    assert audit_status_for([_INF, _YEL, _YEL]) == "findings_open"


def test_red_still_wins():
    assert audit_status_for([_RED]) == "violations_found"
    assert audit_status_for([_YEL, _RED, _INF]) == "violations_found"


def test_malformed_entries_do_not_crash_the_audit():
    assert audit_status_for([None]) == "findings_open"
    assert audit_status_for([{}]) == "findings_open"


def test_it_returns_a_STATUS_and_never_a_COUNT():
    """⚠️ `issues_found` must stay len(red_issues): log_audit derives
    `priority = "high" if issues_found >= 10` and drives repair-task creation from it, so
    redefining it would silently change what raises a task. This function is the STATUS
    half only — if it ever starts returning a number, that separation has collapsed.

    (Asserted behaviourally. An earlier version of this test grepped the source for
    "issues_found" and failed on its own docstring — asserting on prose is not a test.)
    """
    for arg in ([], None, [_RED], [_YEL], [_INF, _RED], [None], [{}]):
        out = audit_status_for(arg)
        assert isinstance(out, str)
        assert out in {"completed", "findings_open", "violations_found"}


def test_severity_is_matched_exactly_not_by_substring():
    """ "reddish"/"not-red" must not count as red, or a cosmetic severity rename would
    silently re-hide findings behind a violations_found badge."""
    assert audit_status_for([{"severity": "reddish"}]) == "findings_open"
    assert audit_status_for([{"severity": "RED"}]) == "findings_open"
