"""Unit tests for ST-1: collapse to one grounded F.O.R.G.E. review path.

Two parts:
  Part A — robust JSON extraction (`_balanced_json_candidates` + `_parse_review_json`):
           recovers JSON wrapped in markdown fences / prose / with braces inside strings,
           which previously dropped the review to the ungated-then-gated freeform path.
  Part B — one JSON re-prompt (`_dispatch_json_review` + `_structured_review`): on a real
           non-JSON reply (`parse_fail`), re-prompt once for clean JSON before falling back.
           Flag `forge:json_reprompt_enabled` (default ON).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def pda():
    from tools.repair_bay.services import pr_diff_analyzer

    return pr_diff_analyzer


# --------------------------------------------------------------------------- #
# Part A — balanced-object scanner                                            #
# --------------------------------------------------------------------------- #


def test_balanced_candidates_plain(pda):
    assert pda._balanced_json_candidates('{"a": 1}') == ['{"a": 1}']


def test_balanced_candidates_fenced(pda):
    text = '```json\n{"issues": [], "summary": "x"}\n```'
    c = pda._balanced_json_candidates(text)
    assert c and c[0] == '{"issues": [], "summary": "x"}'


def test_balanced_candidates_prose_wrapped(pda):
    text = 'Sure! Here is the review:\n{"issues": []}\nLet me know!'
    assert '{"issues": []}' in pda._balanced_json_candidates(text)


def test_balanced_candidates_brace_in_string_not_split(pda):
    text = '{"summary": "use {placeholder} here", "issues": []}'
    c = pda._balanced_json_candidates(text)
    assert c[0] == text  # the in-string { } must NOT terminate the object


def test_balanced_candidates_escaped_quote_in_string(pda):
    text = '{"summary": "he said \\"hi\\" }", "issues": []}'
    c = pda._balanced_json_candidates(text)
    assert c[0] == text  # escaped quote keeps us inside the string


def test_balanced_candidates_nested_largest_first(pda):
    text = '{"issues": [{"severity": "INFO"}], "summary": "s"}'
    c = pda._balanced_json_candidates(text)
    assert c[0] == text  # outer (largest) object ranks first
    assert '{"severity": "INFO"}' in c  # nested object also surfaced


def test_balanced_candidates_none(pda):
    assert pda._balanced_json_candidates("no braces here") == []


# --------------------------------------------------------------------------- #
# Part A — _parse_review_json                                                  #
# --------------------------------------------------------------------------- #


def test_parse_review_json_recovers_fenced(pda):
    text = '```json\n{"summary": "s", "issues": [{"severity": "INFO", "title": "t"}]}\n```'
    d = pda._parse_review_json(text)
    assert d and isinstance(d["issues"], list) and len(d["issues"]) == 1


def test_parse_review_json_recovers_prose_wrapped(pda):
    text = 'Here is my review: {"summary": "s", "issues": []} — done.'
    assert pda._parse_review_json(text) == {"summary": "s", "issues": []}


def test_parse_review_json_rejects_non_json(pda):
    assert pda._parse_review_json("VERDICT: APPROVE\nNo issues found.") is None


def test_parse_review_json_requires_issues_key(pda):
    # Preserves the self-refute audit contract: {"confirmed": [...]} must stay None.
    assert pda._parse_review_json('{"confirmed": [1, 2]}') is None


def test_parse_review_json_coerces_nonlist_issues(pda):
    d = pda._parse_review_json('{"summary": "s", "issues": "oops"}')
    assert d is not None and d["issues"] == []


def test_parse_review_json_empty(pda):
    assert pda._parse_review_json("") is None
    assert pda._parse_review_json(None) is None


# --------------------------------------------------------------------------- #
# Part B — re-prompt flag + _structured_review orchestration                   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "val,expected",
    [("true", True), ("1", True), ("on", True), ("false", False), ("0", False), ("", False), (None, False)],
)
def test_json_reprompt_enabled_flag(pda, val, expected):
    with patch.object(pda, "_get_setting", return_value=val):
        assert pda._json_reprompt_enabled() is expected


def _patch_structured(pda, dispatch_side_effect, reprompt_enabled=True):
    """Common patch set so _structured_review runs without DB/dispatch, exercising only the
    parse/re-prompt control flow. Evidence + self-refute disabled to keep the post-parse path trivial."""
    return [
        patch.object(pda, "_structured_review_enabled", return_value=True),
        patch("tools.repair_bay.services.pr_review_service.classify_pr_tier", return_value=1),
        patch.object(pda, "_dispatch_json_review", side_effect=dispatch_side_effect),
        patch.object(pda, "_json_reprompt_enabled", return_value=reprompt_enabled),
        patch.object(pda, "_evidence_verification_enabled", return_value=False),
        patch.object(pda, "_self_refute_enabled", return_value=False),
    ]


def test_structured_review_reprompts_on_parse_fail(pda):
    review = {"pr_number": 1, "title": "t", "repo": "r"}
    calls = []

    def fake(prompt, kw):
        calls.append(prompt)
        if len(calls) == 1:
            return None, "parse_fail"
        return {"summary": "ok", "issues": [], "confidence": 0.95, "verdict": "APPROVE"}, "parsed"

    from contextlib import ExitStack

    with ExitStack() as stack:
        for c in _patch_structured(pda, fake):
            stack.enter_context(c)
        out = pda._structured_review(review, "diff", 1, "r")

    assert out is not None
    assert "VERDICT: APPROVE" in out
    assert len(calls) == 2  # first parse_fail, then the re-prompt recovered it
    assert "NOT valid JSON" in calls[1]  # the second prompt is the strict re-prompt


def test_structured_review_no_reprompt_when_flag_off(pda):
    review = {"pr_number": 1, "title": "t", "repo": "r"}
    calls = []

    def fake(prompt, kw):
        calls.append(prompt)
        return None, "parse_fail"

    from contextlib import ExitStack

    with ExitStack() as stack:
        for c in _patch_structured(pda, fake, reprompt_enabled=False):
            stack.enter_context(c)
        out = pda._structured_review(review, "diff", 1, "r")

    assert out is None
    assert len(calls) == 1  # flag off -> no re-prompt, straight to freeform fallback


def test_structured_review_queued_never_reprompts(pda):
    review = {"pr_number": 1, "title": "t", "repo": "r"}
    calls = []

    def fake(prompt, kw):
        calls.append(prompt)
        return None, "queued"

    from contextlib import ExitStack

    with ExitStack() as stack:
        for c in _patch_structured(pda, fake):
            stack.enter_context(c)
        out = pda._structured_review(review, "diff", 1, "r")

    assert out is None
    assert len(calls) == 1  # a cold/queued model is handled by the freeform callback, not a re-prompt


def test_structured_review_first_pass_json_no_reprompt(pda):
    review = {"pr_number": 1, "title": "t", "repo": "r"}
    calls = []

    def fake(prompt, kw):
        calls.append(prompt)
        return {"summary": "ok", "issues": [], "confidence": 0.95, "verdict": "APPROVE"}, "parsed"

    from contextlib import ExitStack

    with ExitStack() as stack:
        for c in _patch_structured(pda, fake):
            stack.enter_context(c)
        out = pda._structured_review(review, "diff", 1, "r")

    assert out is not None and "VERDICT: APPROVE" in out
    assert len(calls) == 1  # clean JSON first try -> no extra dispatch
