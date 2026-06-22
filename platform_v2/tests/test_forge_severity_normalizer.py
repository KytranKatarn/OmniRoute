"""QW-2 (#381) — F.O.R.G.E. severity normalizer.

True-but-trivial nit categories (missing tests / type hints / docstrings / duplication / naming /
style / sys.path / magic numbers) must be demoted to INFO on BOTH the structured (dict) and freeform
(text) review paths, so the 7B's habit of self-labelling them WARNING/CRITICAL can no longer block a
merge. Real bug classes — and the deliberately-excluded bare/broad except (KB #270617) — must keep
their blocking severity. Diagnosis: .claude/plans/2026-06-22-forge-review-quality-diagnosis.md (RC-2).
"""

import pytest

from tools.repair_bay.services.pr_diff_analyzer import (
    _apply_severity_gate,
    _demote_nonblocking_lines,
    _normalize_severity,
    _recompute_verdict,
)

# (title, why) nits the 7B mislabels CRITICAL/WARNING but that must NOT block.
NONBLOCKING = [
    ("Missing unit tests", "this module has no unit tests"),
    ("No tests added", "there are no tests for the new endpoint"),
    ("Lack of test coverage", "test coverage is insufficient"),
    ("Missing type hints", "the function lacks type hints"),
    ("No type annotations", "add type annotations to the signature"),
    ("Missing docstring", "the function has no docstring"),
    ("Code duplication", "this duplicates logic from the shared helper"),
    ("Duplicate code", "duplicated code block could be a function"),
    ("Naming convention", "variable naming is inconsistent"),
    ("Style issue", "stylistic nit, prefer f-strings"),
    ("Formatting", "inconsistent formatting; run black"),
    ("PEP8", "pep-8 line length"),
    ("sys.path manipulation", "uses sys.path.insert"),
    ("Magic number", "magic number 86400 should be a constant"),
    ("Nitpick", "nit-pick: trailing whitespace"),
]

# Real bug classes that MUST keep their blocking severity (never demoted). Includes bare/broad
# except, which is intentionally NOT a non-blocking category here (documented leak history).
MUST_KEEP = [
    ("SQL injection", "user input concatenated into the query"),
    ("Data loss", "this migration drops the column without a backup"),
    ("Null dereference", "obj may be None and is dereferenced"),
    ("Race condition", "two threads write the counter without a lock"),
    ("Buffer overflow", "unbounded copy into a fixed buffer"),
    ("Auth bypass", "the endpoint skips the permission check"),
    ("Connection leak", "the cursor is never closed on exception"),
    ("Duplicate primary key", "duplicate insert causes a constraint violation and data corruption"),
    ("Hardcoded secret", "API key is committed in plaintext"),
    ("Infinite loop", "the while condition never becomes false"),
    ("Bare except", "bare except clause swallows the error and leaks the connection"),
    ("Broad except", "broad except hides the real failure"),
]


@pytest.mark.parametrize("title,why", NONBLOCKING)
@pytest.mark.parametrize("sev", ["WARNING", "CRITICAL"])
def test_nonblocking_demoted_to_info(title, why, sev):
    issues = [{"severity": sev, "title": title, "why": why, "evidence": "+x"}]
    _normalize_severity(issues)
    assert issues[0]["severity"] == "INFO", f"should demote {sev}: {title}"
    assert issues[0]["_demoted_from"] == sev


@pytest.mark.parametrize("title,why", MUST_KEEP)
@pytest.mark.parametrize("sev", ["WARNING", "CRITICAL"])
def test_real_bugs_keep_severity(title, why, sev):
    issues = [{"severity": sev, "title": title, "why": why, "evidence": "+x"}]
    _normalize_severity(issues)
    assert issues[0]["severity"] == sev, f"must NOT demote real bug: {title}"
    assert "_demoted_from" not in issues[0]


def test_info_untouched():
    issues = [{"severity": "INFO", "title": "Missing tests", "why": "no tests", "evidence": "+x"}]
    _normalize_severity(issues)
    assert issues[0]["severity"] == "INFO"
    assert "_demoted_from" not in issues[0]


def test_recompute_verdict_approves_after_normalize():
    issues = [{"severity": "WARNING", "title": "Missing unit tests", "why": "no tests", "evidence": "+x"}]
    _normalize_severity(issues)
    assert _recompute_verdict(issues, 1.0, 0.7) == "APPROVE"


def test_recompute_verdict_still_blocks_real_bug():
    issues = [{"severity": "CRITICAL", "title": "SQL injection", "why": "concat user input", "evidence": "+x"}]
    _normalize_severity(issues)
    assert _recompute_verdict(issues, 1.0, 0.7) == "REQUEST CHANGES"


def test_mixed_blocks_only_on_the_real_bug():
    issues = [
        {"severity": "WARNING", "title": "Missing tests", "why": "no tests", "evidence": "+a"},
        {"severity": "CRITICAL", "title": "Auth bypass", "why": "skips permission check", "evidence": "+b"},
    ]
    _normalize_severity(issues)
    assert issues[0]["severity"] == "INFO"
    assert issues[1]["severity"] == "CRITICAL"
    assert _recompute_verdict(issues, 1.0, 0.7) == "REQUEST CHANGES"


def test_freeform_gate_relaxes_when_only_nits():
    text = (
        "SUMMARY\nLooks fine.\n\nISSUES\n"
        "- [WARNING] Missing unit tests — no tests for the new path — Evidence: +def foo():\n"
        "- [INFO] style nit — prefer f-strings — Evidence: +x = y\n\n"
        "VERDICT: REQUEST CHANGES"
    )
    out = _apply_severity_gate(text)
    assert "VERDICT: APPROVE" in out
    assert "[severity-gate]" in out


def test_freeform_gate_keeps_block_on_real_warning():
    text = (
        "SUMMARY\nProblem.\n\nISSUES\n"
        "- [WARNING] Connection leak — cursor not closed on exception — Evidence: +cur = conn.cursor()\n\n"
        "VERDICT: REQUEST CHANGES"
    )
    out = _apply_severity_gate(text)
    assert "VERDICT: REQUEST CHANGES" in out


def test_demote_lines_only_rewrites_matching():
    text = "- [WARNING] Missing tests — none — Evidence: +x\n- [CRITICAL] SQL injection — concat — Evidence: +q\n"
    out = _demote_nonblocking_lines(text)
    assert "[INFO] Missing tests" in out
    assert "[CRITICAL] SQL injection" in out
