"""QW-1 (#381) — F.O.R.G.E. freeform-path gating (RC-1, the dominant root cause).

The ~80% of reviews where the 7B doesn't emit clean JSON fell back to an UNGATED freeform path that
ran only a relax-only severity gate, so a fabricated [CRITICAL] (evidence not in the diff) blocked
unconditionally. _gate_freeform_review parses the freeform issue lines into dicts and runs them
through the SAME evidence-verification + severity normalizer + verdict recompute as the structured
path. Diagnosis: .claude/plans/2026-06-22-forge-review-quality-diagnosis.md (RC-1 / QW-1).
"""

import pytest

import tools.repair_bay.services.pr_diff_analyzer as pda

# A real diff with two added lines we can cite as evidence.
DIFF = (
    "diff --git a/x.py b/x.py\n"
    "--- a/x.py\n"
    "+++ b/x.py\n"
    "@@ -1,2 +1,4 @@\n"
    " def f(user_input):\n"
    '+    q = "SELECT * FROM t WHERE id = " + user_input\n'
    "+    log.debug(q)\n"
    "     return q\n"
)
_REAL_INJECTION_LINE = '+    q = "SELECT * FROM t WHERE id = " + user_input'
_REAL_BENIGN_LINE = "+    log.debug(q)"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # Pin the DB-backed flags so the gate runs deterministically with no DB / no KB writeback.
    monkeypatch.setattr(pda, "_freeform_gate_enabled", lambda: True)
    monkeypatch.setattr(pda, "_evidence_verification_enabled", lambda: True)
    monkeypatch.setattr(pda, "_writeback_enabled", lambda: False)
    monkeypatch.setattr(pda, "_review_confidence_min", lambda: 0.7)


def _line(sev, title, why, ev):
    return f"- [{sev}] {title} — {why} — Evidence: {ev}"


def _review(lines, verdict="REQUEST CHANGES"):
    return "SUMMARY\nReview.\n\nISSUES\n" + "\n".join(lines) + f"\n\nVERDICT: {verdict}"


def test_parse_freeform_issues():
    issues = pda._parse_freeform_issues(_review([_line("WARNING", "Missing tests", "no tests", _REAL_BENIGN_LINE)]))
    assert len(issues) == 1
    assert issues[0]["severity"] == "WARNING"
    assert issues[0]["title"] == "Missing tests"
    assert "no tests" in issues[0]["why"]
    assert issues[0]["evidence"] == _REAL_BENIGN_LINE


def test_parse_handles_info_and_multiple():
    issues = pda._parse_freeform_issues(
        _review(
            [
                _line("CRITICAL", "A", "why a", "+a"),
                _line("INFO", "B", "why b", "+b"),
            ]
        )
    )
    assert [i["severity"] for i in issues] == ["CRITICAL", "INFO"]


def test_fabricated_critical_does_not_block_but_no_longer_auto_approves():
    # Evidence is NOT in the diff -> dropped by evidence-verification -> nothing BLOCKS.
    # (The cited line is a fabricated test fixture, not real code — it does not appear in DIFF.)
    #
    # CHANGED 2026-07-20 (#5009): this used to assert APPROVE. The original intent — stated in the
    # old comment as "nothing blocks" — is PRESERVED: a hallucination still never produces
    # REQUEST CHANGES. What changed is that it no longer produces APPROVE either.
    #
    # Why: the model's ONLY output here was a fabrication, so the run yields zero grounded
    # judgement about the change — and APPROVE is what fires AUTO-MERGE. That combination let
    # PR #2351 (+147/-23) auto-merge on a review whose summary said the diff "does not contain any
    # actual code changes" (truncation ruled out — it received all 9,782 chars). The approval was
    # an artifact of the anti-hallucination filter emptying the issue list, not a judgement.
    #
    # NEEDS REVIEW is the honest middle: it withholds auto-merge without blocking, so a human
    # merges it. See _should_floor_ungrounded + tests/test_forge_ungrounded_floor.py.
    out = pda._gate_freeform_review(
        _review([_line("CRITICAL", "Command injection", "danger", "+    danger_call(user_input)")]), DIFF
    )
    assert "VERDICT: NEEDS REVIEW" in out
    assert "REQUEST CHANGES" not in out, "a fabricated CRITICAL must still never BLOCK (original PR-C intent)"


def test_real_critical_survives_request_changes():
    out = pda._gate_freeform_review(
        _review([_line("CRITICAL", "SQL injection", "concatenates user input", _REAL_INJECTION_LINE)]), DIFF
    )
    assert "VERDICT: REQUEST CHANGES" in out


def test_nit_warning_normalized_to_approve():
    # Evidence is a real changed line (survives verification), then the nit category is demoted to INFO.
    out = pda._gate_freeform_review(
        _review([_line("WARNING", "Missing unit tests", "no tests added", _REAL_BENIGN_LINE)]), DIFF
    )
    assert "VERDICT: APPROVE" in out
    assert "[INFO]" in out


def test_real_and_nit_mixed_still_blocks():
    out = pda._gate_freeform_review(
        _review(
            [
                _line("WARNING", "Missing tests", "no tests", _REAL_BENIGN_LINE),
                _line("CRITICAL", "SQL injection", "concatenates user input", _REAL_INJECTION_LINE),
            ]
        ),
        DIFF,
    )
    assert "VERDICT: REQUEST CHANGES" in out


def test_no_issues_text_stays_approve():
    text = "SUMMARY\nFine.\n\nISSUES\nNo issues found.\n\nVERDICT: APPROVE"
    out = pda._gate_freeform_review(text, DIFF)
    assert "VERDICT: APPROVE" in out


def test_no_diff_falls_back_safely(monkeypatch):
    # No diff -> can't verify evidence -> fall back to the QW-2 severity gate (which still demotes nits).
    text = _review([_line("WARNING", "Missing tests", "no tests", _REAL_BENIGN_LINE)])
    out = pda._gate_freeform_review(text, "")
    assert "VERDICT: APPROVE" in out


def test_flag_off_falls_back(monkeypatch):
    monkeypatch.setattr(pda, "_freeform_gate_enabled", lambda: False)
    text = _review([_line("WARNING", "Missing tests", "no tests", _REAL_BENIGN_LINE)])
    out = pda._gate_freeform_review(text, DIFF)
    # _apply_severity_gate (QW-2) demotes the nit line and relaxes the verdict.
    assert "VERDICT: APPROVE" in out


def test_extract_summary_block():
    assert pda._extract_summary_block("SUMMARY\nHello world.\n\nISSUES\n- x") == "Hello world."


def test_gate_marks_freeform():
    out = pda._gate_freeform_review(_review([_line("WARNING", "Missing tests", "no tests", _REAL_BENIGN_LINE)]), DIFF)
    assert "structured=freeform-gated" in out
