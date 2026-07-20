"""Unit tests for the stale-finding reconciler's checkers (#5004).

This module decides whether a code_issues row gets CLOSED, so the tests are written around
one invariant above all others:

    None ("cannot verify") must NEVER behave like False ("provably gone").

A wrong True merely keeps a dead finding open — harmless. A wrong False silently closes a
REAL finding and hides work forever. Every ambiguous input below therefore asserts None.

The checkers exist because measuring the table corrected the premise: it holds no pyflakes
findings at all (those live in improvement_proposals, a different queue). What it actually
holds, measured 2026-07-20: print 1129 · line-length 725 · SQL injection 275 · TODO 31 ·
secret 10 · bare-except 6.
"""

import pytest

from services.code_issue_reconciler import RESOLVED_STALE, finding_still_reproduces

PRINT = "Print statement found (use logging instead)"
TODO = "TODO/FIXME comment found"
BARE = "Bare except clause catches all exceptions"
LINELEN = "Line exceeds 120 characters (124)"
SQLI = "Potential SQL injection vulnerability"
SECRET = "Potential hardcoded secret detected"

UNPARSEABLE = "def broken(\n"


# --- print statements: the biggest bucket (1129) -----------------------------------------


def test_print_still_present():
    assert finding_still_reproduces(PRINT, 'print("hi")\n') is True


def test_print_resolved():
    assert finding_still_reproduces(PRINT, 'import logging\nlogging.info("hi")\n') is False


def test_print_inside_a_string_is_not_a_print():
    """AST, not regex. A regex scan would see 'print(' here and keep a fixed finding open
    forever; worse, the inverse mistake would close a real one."""
    assert finding_still_reproduces(PRINT, 's = "print(x)"\n') is False


def test_print_method_call_is_not_a_bare_print():
    """obj.print() is not the builtin — only a bare Name call counts."""
    assert finding_still_reproduces(PRINT, "logger.print('x')\n") is False


def test_print_unparseable_source_is_none():
    assert finding_still_reproduces(PRINT, UNPARSEABLE) is None


# --- bare except (6) ----------------------------------------------------------------------


def test_bare_except_still_present():
    assert finding_still_reproduces(BARE, "try:\n    x = 1\nexcept:\n    pass\n") is True


def test_bare_except_resolved_when_typed():
    assert finding_still_reproduces(BARE, "try:\n    x = 1\nexcept ValueError:\n    pass\n") is False


def test_bare_except_matches_llm_prose_wording():
    """Real rows are LLM prose, not a fixed string: 'Bare except block silently swallows
    exceptions in release_db(). ...' — the checker keys off the phrase, not an exact match."""
    msg = "Bare except block silently swallows exceptions in release_db(). This can hide bugs."
    assert finding_still_reproduces(msg, "try:\n    x = 1\nexcept:\n    pass\n") is True
    assert finding_still_reproduces(msg, "try:\n    x = 1\nexcept OSError:\n    pass\n") is False


def test_bare_except_unparseable_source_is_none():
    assert finding_still_reproduces(BARE, UNPARSEABLE) is None


# --- TODO/FIXME (31) ----------------------------------------------------------------------


@pytest.mark.parametrize("src", ["# TODO: fix this\n", "# FIXME later\n", 's = "TODO"\n'])
def test_todo_present_including_inside_a_string(src):
    """Deliberately not comment-aware: a marker anywhere KEEPS the finding open."""
    assert finding_still_reproduces(TODO, src) is True


def test_todo_resolved():
    assert finding_still_reproduces(TODO, "x = 1\n") is False


def test_todo_does_not_need_a_parseable_file():
    """The TODO scan is textual, so it still answers for a file that does not parse."""
    assert finding_still_reproduces(TODO, "def broken(  # TODO\n") is True


# --- line-length regression (725) ---------------------------------------------------------


def test_line_length_unchanged():
    assert finding_still_reproduces(LINELEN, "x" * 124) is True
    assert finding_still_reproduces(LINELEN, "x" * 80) is False


def test_line_length_boundary():
    assert finding_still_reproduces(LINELEN, "x" * 120) is False
    assert finding_still_reproduces(LINELEN, "x" * 121) is True


# --- the heuristics that must stay unverifiable (285) -------------------------------------


@pytest.mark.parametrize("msg", [SQLI, SECRET])
def test_heuristic_detectors_are_never_verifiable(msg):
    """SQL injection and hardcoded-secret are over-flagging heuristics — the platform's own
    _AUTO_FIX_EXCLUDED_ISSUE_CODES says so. They cannot be DISPROVED, so they must never be
    closed automatically, no matter how clean the file looks."""
    assert finding_still_reproduces(msg, "x = 1\n") is None
    assert finding_still_reproduces(msg, "") is None


def test_unrecognised_detector_is_none():
    assert finding_still_reproduces("CYCLOMATIC_COMPLEXITY function too complex (18)", "x = 1\n") is None


def test_empty_message_is_none():
    assert finding_still_reproduces("", "x = 1\n") is None


# --- pyflakes port (inert for this table today, but must behave) --------------------------


def test_pyflakes_finding_round_trip():
    pytest.importorskip("pyflakes")
    msg = "F401 'os' imported but unused"
    assert finding_still_reproduces(msg, "import os\n") is True
    assert finding_still_reproduces(msg, "x = 1\n") is False


def test_pyflakes_syntax_error_is_none_not_resolved():
    """pyflakes emits ONLY the syntax error for an unparseable file. Treating that silence as
    'the finding is gone' would close real findings on any broken file."""
    pytest.importorskip("pyflakes")
    assert finding_still_reproduces("F401 'os' imported but unused", UNPARSEABLE) is None


# --- the module's contract ----------------------------------------------------------------


def test_status_constant_is_distinct_from_the_existing_ones():
    """resolved_stale must not collide with 'resolved'/'fixed', which mean a human or the
    proposal pipeline closed it — provenance matters when auditing what closed a finding."""
    assert RESOLVED_STALE == "resolved_stale"
    assert RESOLVED_STALE not in ("resolved", "fixed", "open", "batch_eligible")
