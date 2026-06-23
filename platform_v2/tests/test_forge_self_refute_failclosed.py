"""Unit tests for ST-2: fail-closed self-refute on unverified CRITICALs.

Two defects fixed:
  1. The self-refute audit reply is ``{"confirmed": [...]}`` (no ``issues`` key), so the old
     ``_parse_review_json`` always returned None -> the audit was a silent no-op (fail-open).
     ``_parse_confirmed_indices`` parses it correctly via the ST-1 balanced scanner.
  2. When the gemma3:12b auditor is UNAVAILABLE (dispatch error / cold-queued / unparseable), an
     unverified CRITICAL no longer auto-blocks (REQUEST CHANGES). It is kept VISIBLE but the verdict
     floors to NEEDS REVIEW so a human adjudicates. Flag forge:self_refute_failclosed_enabled (ON).
"""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.fixture
def pda():
    from tools.repair_bay.services import pr_diff_analyzer

    return pr_diff_analyzer


# --------------------------------------------------------------------------- #
# _parse_confirmed_indices                                                     #
# --------------------------------------------------------------------------- #


def test_parse_confirmed_plain(pda):
    assert pda._parse_confirmed_indices('{"confirmed": [1, 3]}') == {1, 3}


def test_parse_confirmed_fenced(pda):
    assert pda._parse_confirmed_indices('```json\n{"confirmed": [2]}\n```') == {2}


def test_parse_confirmed_prose_wrapped(pda):
    assert pda._parse_confirmed_indices('Audit done: {"confirmed": [1]} ok') == {1}


def test_parse_confirmed_empty_is_retract_all(pda):
    # An empty list is a VALID parse (retract everything) -> empty set, NOT None.
    out = pda._parse_confirmed_indices('{"confirmed": []}')
    assert out == set() and out is not None


def test_parse_confirmed_coerces_and_skips_garbage(pda):
    assert pda._parse_confirmed_indices('{"confirmed": [1, "2", "x", null, 3]}') == {1, 2, 3}


def test_parse_confirmed_no_key_is_none(pda):
    # The review JSON has 'issues' not 'confirmed' -> None (auditor reply absent).
    assert pda._parse_confirmed_indices('{"issues": []}') is None


def test_parse_confirmed_non_json_is_none(pda):
    assert pda._parse_confirmed_indices("I confirm issue 1 and 2.") is None


def test_parse_confirmed_empty_text_is_none(pda):
    assert pda._parse_confirmed_indices("") is None
    assert pda._parse_confirmed_indices(None) is None


# --------------------------------------------------------------------------- #
# _self_refute_criticals -> (confirmed, audit_ran)                             #
# --------------------------------------------------------------------------- #

_CRITS = [{"severity": "CRITICAL", "title": "a"}, {"severity": "CRITICAL", "title": "b"}]


def _res(success=True, response="", queued=False):
    return SimpleNamespace(success=success, response=response, queued=queued)


def _refute(pda, dispatch_obj=None, raises=False):
    """Patch the dispatcher import target used inside _self_refute_criticals."""
    target = "tools.department_hq.services.department_dispatcher.dispatch"
    if raises:
        return patch(target, side_effect=RuntimeError("boom"))
    return patch(target, return_value=dispatch_obj)


def test_refute_empty_criticals(pda):
    assert pda._self_refute_criticals({}, "d", []) == ([], True)


def test_refute_confirms_subset(pda):
    with _refute(pda, _res(response='{"confirmed": [1]}')):
        confirmed, ran = pda._self_refute_criticals({"pr_number": 1}, "d", _CRITS)
    assert ran is True
    assert confirmed == [_CRITS[0]]


def test_refute_confirms_all(pda):
    with _refute(pda, _res(response='{"confirmed": [1, 2]}')):
        confirmed, ran = pda._self_refute_criticals({"pr_number": 1}, "d", _CRITS)
    assert ran is True and confirmed == _CRITS


def test_refute_retracts_all(pda):
    with _refute(pda, _res(response='{"confirmed": []}')):
        confirmed, ran = pda._self_refute_criticals({"pr_number": 1}, "d", _CRITS)
    assert ran is True and confirmed == []  # empty confirmed = retract all, audit DID run


def test_refute_dispatch_raises_failclosed(pda):
    with _refute(pda, raises=True):
        confirmed, ran = pda._self_refute_criticals({"pr_number": 1}, "d", _CRITS)
    assert ran is False and confirmed == _CRITS  # unavailable -> caller fails closed


def test_refute_queued_failclosed(pda):
    with _refute(pda, _res(queued=True)):
        confirmed, ran = pda._self_refute_criticals({"pr_number": 1}, "d", _CRITS)
    assert ran is False and confirmed == _CRITS


def test_refute_no_response_failclosed(pda):
    with _refute(pda, _res(success=False, response="")):
        confirmed, ran = pda._self_refute_criticals({"pr_number": 1}, "d", _CRITS)
    assert ran is False and confirmed == _CRITS


def test_refute_unparseable_failclosed(pda):
    with _refute(pda, _res(response="sorry I cannot produce JSON")):
        confirmed, ran = pda._self_refute_criticals({"pr_number": 1}, "d", _CRITS)
    assert ran is False and confirmed == _CRITS


@pytest.mark.parametrize(
    "val,expected",
    [("true", True), ("1", True), ("on", True), ("false", False), ("0", False), ("", False), (None, False)],
)
def test_failclosed_flag(pda, val, expected):
    with patch.object(pda, "_get_setting", return_value=val):
        assert pda._self_refute_failclosed_enabled() is expected


# --------------------------------------------------------------------------- #
# _structured_review integration — the fail-closed verdict floor               #
# --------------------------------------------------------------------------- #


def _payload(issues):
    return {"summary": "s", "issues": issues, "confidence": 0.95, "verdict": "REQUEST CHANGES"}


def _run_structured(pda, issues, refute_fn, failclosed=True):
    """Run _structured_review with self-refute mocked; returns the rendered review text."""
    ctxs = [
        patch.object(pda, "_structured_review_enabled", return_value=True),
        patch("tools.repair_bay.services.pr_review_service.classify_pr_tier", return_value=1),
        patch.object(pda, "_dispatch_json_review", return_value=(_payload(issues), "parsed")),
        patch.object(pda, "_json_reprompt_enabled", return_value=True),
        patch.object(pda, "_evidence_verification_enabled", return_value=False),
        patch.object(pda, "_self_refute_enabled", return_value=True),
        patch.object(pda, "_self_refute_criticals", side_effect=lambda review, diff, crits: refute_fn(crits)),
        patch.object(pda, "_self_refute_failclosed_enabled", return_value=failclosed),
        patch.object(pda, "_review_confidence_min", return_value=0.7),
    ]
    with ExitStack() as stack:
        for c in ctxs:
            stack.enter_context(c)
        return pda._structured_review({"pr_number": 1, "title": "t"}, "diff", 1, "r")


def _crit():
    return {"severity": "CRITICAL", "title": "unclosed loop", "why": "w", "evidence": "+x"}


def _warn():
    return {"severity": "WARNING", "title": "real warning", "why": "w", "evidence": "+y"}


def test_unverified_critical_floors_to_needs_review(pda):
    # Auditor unavailable + a lone CRITICAL -> NEEDS REVIEW, critical still visible.
    out = _run_structured(pda, [_crit()], lambda crits: (crits, False), failclosed=True)
    assert "VERDICT: NEEDS REVIEW" in out
    assert "unclosed loop" in out  # kept visible for the human
    assert "unverified" in out  # the explanatory note


def test_unverified_critical_does_not_downgrade_real_block(pda):
    # Auditor unavailable, but a real WARNING also blocks -> stays REQUEST CHANGES, not downgraded.
    out = _run_structured(pda, [_crit(), _warn()], lambda crits: (crits, False), failclosed=True)
    assert "VERDICT: REQUEST CHANGES" in out


def test_failclosed_off_keeps_legacy_failopen_block(pda):
    # Flag OFF -> legacy behavior: an unverified CRITICAL stays blocking.
    out = _run_structured(pda, [_crit()], lambda crits: (crits, False), failclosed=False)
    assert "VERDICT: REQUEST CHANGES" in out


def test_audit_ran_retract_drops_critical(pda):
    # Auditor ran and retracted the critical -> dropped -> APPROVE.
    out = _run_structured(pda, [_crit()], lambda crits: ([], True), failclosed=True)
    assert "VERDICT: APPROVE" in out
    assert "unclosed loop" not in out


def test_audit_ran_confirm_keeps_block(pda):
    # Auditor ran and confirmed the critical -> it blocks (REQUEST CHANGES).
    out = _run_structured(pda, [_crit()], lambda crits: (crits, True), failclosed=True)
    assert "VERDICT: REQUEST CHANGES" in out
    assert "unclosed loop" in out
