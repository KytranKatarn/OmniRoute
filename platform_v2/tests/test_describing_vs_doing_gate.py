"""Gate 5 — DESCRIBING vs DOING (#6029).

The four existing integrity gates ask: is the citation REAL, is it an ADDED line, is the claim
CHECKABLE, does the label match the CONTENT. On a plan or postmortem all four pass *correctly*
and the review is still wrong, because a document about defects is a diff made almost entirely
of defect DESCRIPTIONS.

Measured 2026-08-25 on PR #2839 — a plan file plus a revert script, no code — which returned
REQUEST CHANGES with four [CRITICAL]s. Every citation below is copied from that review.

⚠️ The negative controls are the point of this file. A gate that demotes real findings is worse
than the bug it fixes, so the "must STILL block" cases outnumber the demotions.
"""

from __future__ import annotations

import pytest

from tools.repair_bay.services.pr_diff_analyzer import (
    _demote_nonblocking_lines,
    _evidence_is_prose_not_code,
    _normalize_severity,
)


def _issue(ev: str, sev: str = "CRITICAL") -> dict:
    return {"severity": sev, "title": "Some Finding", "why": "because reasons", "evidence": ev}


class TestTheRealPR2839Findings:
    """Verbatim citations from the review that motivated this gate."""

    @pytest.mark.parametrize(
        "evidence",
        [
            "+- Route Lane 3 inference through the hub dispatcher instead of raw Ollama.",
            "+- `build_loop|pull_work|opened PR` → **0 log lines in 7 days**.",
            "+- Ship `tests/` into the image, or add a CI job that runs them against the built image.",
            "+  * bypassed the DHQ dispatcher entirely, in violation of ADR-013",
            "+### 1. Lane 3 does not use the cluster (the headline finding)",
            "+| `OLLAMA_HOST` | `http://100.64.0.4:11434` | **direct to hub** |",
            "+> the plan argues from the spec, so the spec travels with it",
        ],
    )
    def test_prose_evidence_is_recognised(self, evidence):
        assert _evidence_is_prose_not_code(_issue(evidence)) is True

    def test_they_are_demoted_not_dropped(self):
        """Demote-only — a human must still read the text."""
        issues = [_issue("+- Route Lane 3 inference through the hub dispatcher instead of raw Ollama.")]
        out = _normalize_severity(issues)
        assert len(out) == 1, "the finding must survive, only its severity changes"
        assert out[0]["severity"] == "INFO"
        assert out[0]["_demoted_from"] == "CRITICAL"


class TestNegativeControls:
    """⚠️ Real findings MUST still block. These outnumber the demotions deliberately."""

    @pytest.mark.parametrize(
        "evidence",
        [
            "+    password = 'hunter2'",  # assignment
            "+    subprocess.run(cmd, shell=True)",  # call
            "+  - name: Build",  # YAML list item — dash, but code
            "+  - run: echo ${{ github.event.issue.title }}",  # YAML + injection
            "+def _hub_complete(self, prompt):",  # def
            "+    return None",  # keyword
            "+        }",  # block punctuation
            "+import requests",  # import
            "+  redis_url: redis://localhost:6379",  # key: value
        ],
    )
    def test_code_evidence_is_not_treated_as_prose(self, evidence):
        assert _evidence_is_prose_not_code(_issue(evidence)) is False

    def test_a_real_code_finding_keeps_its_severity(self):
        issues = [_issue("+    subprocess.run(user_input, shell=True)")]
        out = _normalize_severity(issues)
        assert out[0]["severity"] == "CRITICAL", "a genuine defect must not be demoted"
        assert "_demoted_from" not in out[0]

    def test_empty_or_missing_evidence_is_not_prose(self):
        """An ungrounded finding is the #5009 floor's business, not this gate's."""
        assert _evidence_is_prose_not_code(_issue("")) is False
        assert _evidence_is_prose_not_code({}) is False
        assert _evidence_is_prose_not_code({"severity": "CRITICAL"}) is False

    def test_prose_without_markdown_structure_is_not_matched(self):
        """Structure is required — a bare sentence is not enough to demote on."""
        assert _evidence_is_prose_not_code(_issue("+the config is wrong")) is False


class TestFreeformPath:
    """The freeform review path carries its citation as a trailing `Evidence:` string."""

    def test_prose_line_is_demoted(self):
        line = (
            "- [CRITICAL] Engine Bypassing Dispatcher — violates ADR-013 — "
            "Evidence: +- Route Lane 3 inference through the hub dispatcher instead of raw Ollama."
        )
        assert "[INFO]" in _demote_nonblocking_lines(line)

    def test_code_line_still_blocks(self):
        line = (
            "- [CRITICAL] Shell Injection — user input reaches a shell — "
            "Evidence: +    subprocess.run(user_input, shell=True)"
        )
        out = _demote_nonblocking_lines(line)
        assert "[CRITICAL]" in out and "[INFO]" not in out

    def test_line_without_evidence_is_untouched_by_this_gate(self):
        line = "- [CRITICAL] Something Bad — no citation at all"
        assert "[CRITICAL]" in _demote_nonblocking_lines(line)

    def test_citation_containing_the_word_evidence_splits_on_the_FIRST_one(self):
        """Split on the FIRST `Evidence:` — it is a FIELD MARKER, not a delimiter.

        Everything after it is the citation, which may itself contain the word. `rsplit`
        would keep only the tail (` was missing from the log.`), losing the leading bullet
        and so failing to recognise obvious prose. My first draft used rsplit with a comment
        confidently defending it; this test is what caught it.
        """
        line = "- [CRITICAL] Doc Finding — x — Evidence: +- The report says Evidence: was missing from the log."
        assert "[INFO]" in _demote_nonblocking_lines(line)


class TestPR3089UnicodeBullets:
    """PR #3089 (2026-09-03) — a DOCS-ONLY PR failed with a [CRITICAL] "rounding issue in SQL".

    The PR is one .md file, +32 lines, ZERO code files. The review quoted the file's own prose
    DESCRIBING the #3087 fix and re-flagged that fix as the defect. Gate 5 should have demoted it.

    It did not, because `module-capability-index.md` bullets with `·` and `⚠️`, and neither is in
    _PROSE_EVIDENCE_RE's `[-*+]` class.

    ⚠️ Why the suite stayed green: EVERY case in TestTheRealPR2839Findings is `+`-prefixed, so the
    `^[+-]\\s?` strip removes the `+` and the bullet survives. Un-prefixed prose was never tested.
    A self-chosen fixture proves a property of the FIXTURE (KB #302084).
    """

    @pytest.mark.parametrize(
        "evidence",
        [
            # verbatim from the two #3089 reviews
            "· **`margin_pct` is rounded to 2dp in SQL, deliberately** (#3087). At 1dp a 12-vote"
            " win in 57,349 becomes exactly 0.0",
            "⚠️ `margin_pct` is rounded to 2dp in SQL, deliberately",
            "⚠️ **PARTY NAMES ARE CANONICALISED IN SQL, BEFORE AGGREGATION**",
            # other house-style markers used across .claude/rules/
            "🔴 **`sc-live` / `sc-static` DO NOT EXIST** — corrected 2026-09-01.",
            "• the winner is the row with a non-empty Majority",
        ],
    )
    def test_unicode_bulleted_prose_is_recognised(self, evidence):
        assert _evidence_is_prose_not_code(_issue(evidence)) is True

    def test_the_3089_finding_is_demoted_not_dropped(self):
        issues = [_issue("⚠️ `margin_pct` is rounded to 2dp in SQL, deliberately")]
        out = _normalize_severity(issues)
        assert len(out) == 1, "the finding must survive, only its severity changes"
        assert out[0]["severity"] == "INFO"
        assert out[0]["_demoted_from"] == "CRITICAL"


class TestUnicodeBulletNegativeControls:
    """The point of the gate is to not demote real defects. These MUST still block."""

    @pytest.mark.parametrize(
        "evidence",
        [
            # a unicode bullet in a COMMENT above real code must not launder the code
            "+    margin_pct = round(margin / total * 100, 2)",
            "+  · cur.execute('SELECT round(x, 1)')",
            "+config = {'margin': 1}",
            "+  - name: Build",  # YAML list item — the #6029 regression case
            "+    return None",
            "+self.assertEqual(margin_pct, 0.0)",
        ],
    )
    def test_code_still_blocks_even_with_unicode_nearby(self, evidence):
        assert _evidence_is_prose_not_code(_issue(evidence)) is False

    def test_a_real_defect_with_an_emoji_in_the_message_still_blocks(self):
        """An emoji inside a string literal is not a bullet."""
        ev = "+    raise ValueError('⚠️ margin_pct must be positive')"
        assert _evidence_is_prose_not_code(_issue(ev)) is False

    def test_bare_ascii_bullet_remains_unmatched_by_design(self):
        """DELIBERATE limitation, asserted so it cannot regress silently.

        `- **bold prose**` with no diff marker is indistinguishable from a diff-REMOVED line
        (`-    return None` has no code shape either). Widening `[-*+]` here would demote real
        findings, so #3089 fixed only the unambiguous non-ASCII markers.
        """
        ev = "- **`margin_pct` is rounded to 2dp in SQL, deliberately**"
        assert _evidence_is_prose_not_code(_issue(ev)) is False
