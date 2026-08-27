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


def test_ruff_backtick_quoting_matches_pyflakes_output():
    """ruff quotes names with BACKTICKS (`os`); pyflakes emits single quotes ('os').
    Production F401 rows carry the ruff spelling, and the mismatch made every such finding
    read as 'provably gone' while still present — archived daily by the reconciler, then
    recreated by the next audit (the 11259/11235 oscillator, 2026-08-27)."""
    pytest.importorskip("pyflakes")
    msg = "F401 `os` imported but unused"
    assert finding_still_reproduces(msg, "import os\n") is True
    assert finding_still_reproduces(msg, "x = 1\n") is False


def test_ruff_backtick_unused_import_not_excused_by_from_import():
    """A bare `import psycopg2` left unused must stay open even when a USED
    `from psycopg2.extras import ...` sits right beside it — pyflakes distinguishes the
    bindings, and the needle match must not lose that by failing to match at all."""
    pytest.importorskip("pyflakes")
    src = "import psycopg2\nfrom psycopg2.extras import RealDictCursor\n\nx = RealDictCursor\n"
    assert finding_still_reproduces("F401 `psycopg2` imported but unused", src) is True


def test_finding_fingerprint_unifies_detector_spellings():
    """The ruff (F401, backticks) and static (PYFLAKES, single quotes) spellings of the SAME
    defect must share one fingerprint — that identity is what creation-time dedup keys on.
    Different import names must NOT collide."""
    from services.code_issue_reconciler import finding_fingerprint

    ruff = finding_fingerprint("F401", "`psycopg2` imported but unused (line 15)")
    pyf = finding_fingerprint("PYFLAKES", "'psycopg2' imported but unused (line 15)")
    assert ruff and ruff == pyf
    assert finding_fingerprint("F401", "`os` imported but unused (line 3)") != ruff


# --- the module's contract ----------------------------------------------------------------


def test_status_constant_is_distinct_from_the_existing_ones():
    """resolved_stale must not collide with 'resolved'/'fixed', which mean a human or the
    proposal pipeline closed it — provenance matters when auditing what closed a finding."""
    assert RESOLVED_STALE == "resolved_stale"
    assert RESOLVED_STALE not in ("resolved", "fixed", "open", "batch_eligible")


# --- line-precise line-length checking (#5004 follow-up) ----------------------------------
# The whole-file rule was safe but wildly imprecise on clustered findings: agent_loop.py
# carried 422 line-length findings while the file had FIFTEEN long lines. One survivor kept
# all 422 open, so the backlog reported 28x its real debt and its size meant nothing.

LONG = "x" * 124
SHORT = "y" * 40
MIXED = "\n".join([LONG, SHORT, "z" * 130])  # long at 1 and 3, short at 2


def test_line_precise_uses_the_cited_line():
    assert finding_still_reproduces(LINELEN, MIXED, 1) is True
    assert finding_still_reproduces(LINELEN, MIXED, 3) is True


def test_line_precise_closes_a_finding_whose_own_line_is_now_short():
    """THE POINT: the file still violates elsewhere, but THIS finding's line does not."""
    assert finding_still_reproduces(LINELEN, MIXED, 2) is False


def test_out_of_range_line_falls_back_to_whole_file():
    """A shrunken file must not silently close findings — fall back, don't guess."""
    assert finding_still_reproduces(LINELEN, MIXED, 999) is True


def test_omitting_the_line_number_preserves_whole_file_behaviour():
    """Back-compat: every existing caller and test passes two args."""
    assert finding_still_reproduces(LINELEN, MIXED) is True
    assert finding_still_reproduces(LINELEN, SHORT) is False


def test_line_precise_does_not_leak_into_other_checkers():
    """line_number is only meaningful for line-length; other detectors ignore it."""
    assert finding_still_reproduces(PRINT, 'print("hi")\n', 1) is True
    assert finding_still_reproduces(SQLI, "x = 1\n", 1) is None


# --- #6054: beyond-EOF close for UNRECOGNISED messages only ---------------------------------

_PROSE = "The server is loading tools from the database, which could be slow and resource-intensive."
_SHORT3 = "a = 1\nb = 2\nc = 3\n"


def test_unrecognised_message_beyond_eof_closes():
    """The #8393 shape: prose finding, no checker, cited line past EOF -> provably dead."""
    assert finding_still_reproduces(_PROSE, _SHORT3, 25847) is False


def test_unrecognised_message_in_range_stays_unverifiable():
    assert finding_still_reproduces(_PROSE, _SHORT3, 2) is None


def test_unrecognised_message_without_line_stays_unverifiable():
    assert finding_still_reproduces(_PROSE, _SHORT3, None) is None


def test_recognised_class_keeps_its_own_fallback_over_the_eof_rule():
    """ORDER PIN: line-length's whole-file fallback must win over the #6054 rule --
    a shrunken file with real debt elsewhere stays open (the existing
    test_out_of_range_line_falls_back_to_whole_file contract)."""
    assert finding_still_reproduces(LINELEN, MIXED, 999) is True


def test_non_integer_line_number_is_safe():
    assert finding_still_reproduces(_PROSE, _SHORT3, "not-a-number") is None
