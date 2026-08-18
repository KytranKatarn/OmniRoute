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
    _is_design_observation,
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


# ── design observations (2026-08-18) ─────────────────────────────────────────
#
# A third shape of non-finding that neither existing gate caught: a neutral remark about
# SHAPE. _asserts_no_defect needs APPROVAL wording; _NONBLOCKING_CATEGORY_RE needs a known
# nit CATEGORY. "introduces new functions which add complexity" is neither, so it blocked.
#
# Measured on three consecutive PRs (#2686/#2687/#2688), every one REQUEST CHANGES on a
# WARNING of this shape. #2687 — an auth + rate-limit fix closing a LIVE anonymous path into
# hub LLM work — was blocked twice by it. "This change adds code" cannot be a defect in a PR
# whose whole purpose is to add a security gate.

DESIGN_OBSERVATIONS = [
    (
        "Additional Functionality Introduced",
        "Introduces new functions _rate_limited, _require_session and _public_api which add "
        "complexity to the codebase.",
    ),
    ("Increased complexity", "this increases complexity in the module"),
    ("New helpers", "introduces new helpers for the gate"),
    (
        "Hard-coded threshold",
        "The threshold value of 180 minutes may be too long or too short, depending on the "
        "expected update frequency.",
    ),
    ("Hardcoded timeout", "the timeout is hardcoded rather than configurable"),
]

# The carve-outs. A hardcoded SECRET or ADDRESS is a real bug in this codebase (the .env rules
# and the mesh mandate exist because of exactly these), and any predicative fault claim wins
# over the observation wording — so "adds complexity AND is vulnerable" must still block.
DESIGN_LOOKALIKES_THAT_MUST_BLOCK = [
    ("Hardcoded credential", "the API key is hard-coded in the module"),
    ("Hardcoded secret", "password hard-coded in the source"),
    ("Hardcoded token", "the bearer token is hardcoded"),
    ("Hardcoded IP", "the mesh ip address is hardcoded, bypassing config"),
    ("Hardcoded connection string", "the connection string is hard-coded"),
    ("Complexity plus a fault", "adds complexity to the codebase and the new path is vulnerable to injection"),
    ("New functions but broken", "introduces new helpers which fail to handle the None case"),
    ("Complexity and a crash", "increases complexity and will crash on empty input"),
    ("New class that lacks a guard", "introduces new classes which lack a permission check"),
]


@pytest.mark.parametrize("title,why", DESIGN_OBSERVATIONS)
@pytest.mark.parametrize("sev", ["WARNING", "CRITICAL"])
def test_design_observations_demoted_to_info(title, why, sev):
    issues = [{"severity": sev, "title": title, "why": why, "evidence": "+x"}]
    _normalize_severity(issues)
    assert issues[0]["severity"] == "INFO", f"should demote {sev}: {title}"
    assert issues[0]["_demoted_from"] == sev


@pytest.mark.parametrize("title,why", DESIGN_LOOKALIKES_THAT_MUST_BLOCK)
@pytest.mark.parametrize("sev", ["WARNING", "CRITICAL"])
def test_design_lookalikes_keep_severity(title, why, sev):
    """The safety half. If these ever demote, the gate has started swallowing real findings."""
    issues = [{"severity": sev, "title": title, "why": why, "evidence": "+x"}]
    _normalize_severity(issues)
    assert issues[0]["severity"] == sev, f"must NOT demote: {title}"
    assert "_demoted_from" not in issues[0]


def test_hedged_security_language_still_blocks():
    """Deliberately NOT demoted, and this test exists to keep it that way.

    "could lead to bugs or security vulnerabilities if not thoroughly tested" is hedged and
    arguably unfalsifiable — but it NAMES security vulnerabilities, so it reaches a human.
    This is the finding that still blocks PR #2687 after this change shipped; loosening the
    fault-assertion guard to clear it would be the author grading their own homework.
    """
    blob = (
        "Introducing conditional logic for session checks could lead to bugs or "
        "security vulnerabilities if not thoroughly tested."
    )
    assert not _is_design_observation(blob)
    issues = [{"severity": "WARNING", "title": "Complexity in Session Handling", "why": blob, "evidence": "+x"}]
    _normalize_severity(issues)
    assert issues[0]["severity"] == "WARNING"


def test_design_observation_needs_the_phrase_not_just_absence_of_faults():
    """A benign-sounding finding with no design-observation phrase is NOT demoted by this gate —
    it must fall through to the other gates or block. Absence of fault language is not enough."""
    assert not _is_design_observation("The endpoint returns 200 for an empty result set.")


def test_empty_blob_is_not_a_design_observation():
    assert not _is_design_observation("")
    assert not _is_design_observation(None)


def test_freeform_path_demotes_design_observations_too():
    """Both review paths must agree — a structured-only fix leaves freeform reviews blocking."""
    text = (
        "SUMMARY\nok\n\nISSUES\n"
        "- [WARNING] Additional Functionality Introduced — introduces new functions which "
        "add complexity to the codebase — Evidence: +def _require_session():\n"
        "\nVERDICT: REQUEST CHANGES"
    )
    out = _demote_nonblocking_lines(text)
    assert "[INFO] Additional Functionality" in out
    assert _apply_severity_gate(out).strip().endswith("APPROVE") or "APPROVE" in _apply_severity_gate(out)
