"""QW-4 (verdict-menu echo) + QW-6 (file-boundary truncation) for F.O.R.G.E. review.

QW-4 (RC-3d): a weak 7B echoing the verdict MENU ("VERDICT: APPROVE | REQUEST CHANGES | NEEDS
REVIEW") must not be misread as a real REQUEST CHANGES by the reject-first parser — an un-chosen
menu routes to NEEDS REVIEW.
QW-6 (RC-3b): _truncate_diff prefers a file boundary (\\ndiff --git) so a long single-hunk migration
is never sliced mid-statement (the false 'missing semicolon' class).
Diagnosis: .claude/plans/2026-06-22-forge-review-quality-diagnosis.md
"""

import tools.repair_bay.services.pr_diff_analyzer as pda
from tools.repair_bay.services.pr_review_service import parse_verdict


# --- QW-4: verdict menu echo -------------------------------------------------------------------
def test_menu_echo_routes_to_needs_review():
    assert parse_verdict("VERDICT: APPROVE | REQUEST CHANGES | NEEDS REVIEW") == "NEEDS REVIEW"


def test_menu_echo_inside_full_review():
    text = "SUMMARY\nFine.\n\nISSUES\nNo issues found.\n\nVERDICT: APPROVE | REQUEST CHANGES | NEEDS REVIEW"
    assert parse_verdict(text) == "NEEDS REVIEW"


def test_real_single_verdicts_unaffected():
    assert parse_verdict("VERDICT: APPROVE") == "APPROVE"
    assert parse_verdict("VERDICT: REQUEST CHANGES") == "REQUEST CHANGES"
    assert parse_verdict("VERDICT: NEEDS REVIEW") == "NEEDS REVIEW"


def test_genuine_request_changes_still_blocks():
    text = "ISSUES\n- [CRITICAL] real bug — Evidence: +x\n\nVERDICT: REQUEST CHANGES"
    assert parse_verdict(text) == "REQUEST CHANGES"


def test_approve_with_other_words_elsewhere():
    # 'request changes' / 'needs review' on OTHER lines must not trigger the menu guard.
    text = "SUMMARY\nNo need to request changes; nothing needs review.\n\nVERDICT: APPROVE"
    assert parse_verdict(text) == "APPROVE"


# --- QW-6: truncation boundary -----------------------------------------------------------------
def test_short_diff_not_truncated(monkeypatch):
    monkeypatch.setattr(pda, "_DIFF_MAX_CHARS", 1000)
    diff = "diff --git a/f b/f\n@@ -1 +1 @@\n+x\n"
    content, truncated = pda._truncate_diff(diff)
    assert not truncated and content == diff


def test_prefers_file_boundary(monkeypatch):
    monkeypatch.setattr(pda, "_DIFF_MAX_CHARS", 120)
    file1 = "diff --git a/f1 b/f1\n@@ -1 +1 @@\n+" + "a" * 50 + "\n"
    diff = file1 + "diff --git a/f2 b/f2\n@@ -1 +1 @@\n+" + "b" * 200 + "\n"
    content, truncated = pda._truncate_diff(diff)
    assert truncated
    assert "a/f1" in content  # first file kept whole
    assert "a/f2" not in content  # second file dropped at the boundary (no mid-statement slice)


def test_falls_back_to_hunk_when_file_boundary_too_early(monkeypatch):
    monkeypatch.setattr(pda, "_DIFF_MAX_CHARS", 120)
    # Only file boundary is at index 0 (no preceding \n) -> use the later hunk boundary instead.
    diff = "diff --git a/f b/f\n" + "@@ -1 +1 @@\n+" + "a" * 30 + "\n" + "@@ -2 +2 @@\n+" + "b" * 200 + "\n"
    content, truncated = pda._truncate_diff(diff)
    assert truncated
    assert "@@ -1" in content
    assert "@@ -2" not in content  # cut at the second hunk boundary, complete first hunk kept


def test_raw_byte_cut_last_resort(monkeypatch):
    monkeypatch.setattr(pda, "_DIFF_MAX_CHARS", 50)
    diff = "x" * 200  # no \ndiff --git and no \n@@ anywhere
    content, truncated = pda._truncate_diff(diff)
    assert truncated and len(content) == 50
