"""#5921 — a guard test's FAILURE MESSAGE quoted as proof the failure exists.

Reproduces the real PR #2759 finding. All four existing ADR-001 gates pass on it,
which is the whole reason a fifth exists.
"""

import sys

sys.path.insert(0, "/app")

from tools.repair_bay.services.pr_diff_analyzer import (  # noqa: E402
    _is_inverted_guard_assertion,
    _verify_evidence,
)

# the literal added line from PR #2759's guard test
_EV = 'assert not missing, f"_TABLES entries with no DEFAULTS key (KeyError at prune time): {missing}"'
_DIFF = "diff --git a/t.py b/t.py\n--- a/t.py\n+++ b/t.py\n@@ -1 +1,2 @@\n+    " + _EV + "\n"

_REAL_INVERSION = {
    "title": "_TABLES entries with no DEFAULTS key",
    "why": "These tables will cause a KeyError at runtime, potentially stopping retention for all tables.",
    "evidence": _EV,
    "severity": "CRITICAL",
}


def test_catches_the_real_2759_inversion():
    assert _is_inverted_guard_assertion(_REAL_INVERSION, _DIFF) is True


def test_it_is_dropped_by_verify_evidence_with_the_right_reason():
    kept, dropped = _verify_evidence([_REAL_INVERSION], _DIFF)
    assert kept == []
    assert dropped[0]["_drop_reason"] == "inverted_guard_assertion"


def test_it_does_NOT_count_toward_the_ungrounded_floor():
    """#5009's floor must stay reserved for evidence that was NOT in the diff. This citation
    IS real — the model was reading, it read the assertion backwards. Counting it would
    re-block correct PRs."""
    from tools.repair_bay.services.pr_diff_analyzer import _count_ungrounded

    _, dropped = _verify_evidence([_REAL_INVERSION], _DIFF)
    assert _count_ungrounded(dropped) == 0


def test_a_legitimate_finding_on_the_same_line_survives():
    """THE FALSE-POSITIVE GUARD. A finding that cites the same assert but says something the
    message does NOT say must be untouched — otherwise this gate silences real review."""
    legit = {
        "title": "f-string in assert message is evaluated eagerly",
        "why": "Building the message on every call is wasteful in a hot loop.",
        "evidence": _EV,
        "severity": "WARNING",
    }
    assert _is_inverted_guard_assertion(legit, _DIFF) is False
    kept, _ = _verify_evidence([legit], _DIFF)
    assert len(kept) == 1


def test_a_short_message_does_not_trip_it():
    """Below the 24-char literal floor an overlap is coincidence, not restatement."""
    issue = {"title": "bad value", "why": "bad value", "evidence": 'assert x, "bad value"', "severity": "CRITICAL"}
    assert _is_inverted_guard_assertion(issue, _DIFF) is False


def test_evidence_without_an_assert_is_untouched():
    issue = {
        "title": "_TABLES entries with no DEFAULTS key",
        "why": "KeyError at runtime",
        "evidence": "_TABLES = {'a': 1}",
        "severity": "CRITICAL",
    }
    assert _is_inverted_guard_assertion(issue, _DIFF) is False
