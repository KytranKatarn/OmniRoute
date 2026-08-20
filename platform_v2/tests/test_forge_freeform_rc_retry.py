"""#5287 — the freeform fallback is where false verdicts come from.

OBSERVED 2026-07-27: the SAME diff (PR #2503, commit 8aab57e0e) produced a false blocking
CRITICAL on the freeform path (`structured=freeform-gated quality=freeform_fallback`) and a
clean APPROVE on the structured path (`structured=json confidence=1.0`). The merge gate
(`verdict_is_approved` + #5194) treats both verdicts as equal in authority, so a
degraded-path hallucination can block a correct PR — or contribute an APPROVE the gate then
trusts. Two deterministic responses (task #5287, both bounded, neither retry-until-APPROVE):

1. RETRY   — a blocking verdict produced OFF the structured path triggers exactly ONE
             structured retry. A parsed structured verdict supersedes (whatever it says — a
             persistent REQUEST CHANGES stands); an unavailable structured path leaves the
             degraded verdict untouched and annotated.
2. DEMOTE  — an RC resting SOLELY on blocking issues that cite no evidence demotes to
             NEEDS REVIEW (never APPROVE). The `blocking_issue_without_evidence` flag was
             already self-reported on the #2501 row — stored as a label nobody consumed.

All externals mocked at the dispatch boundary only; gate logic runs for real.
"""

import tools.repair_bay.services.pr_diff_analyzer as pda
from tools.repair_bay.services.pr_review_service import parse_verdict

DIFF = """diff --git a/x.py b/x.py
index 1111111..2222222 100644
--- a/x.py
+++ b/x.py
@@ -1,2 +1,5 @@
+        try:
+            record_last_used()
+        except Exception as e:  # never let bookkeeping break the wake
"""

FREEFORM_RC = """SUMMARY
Something looks wrong.

ISSUES
- [CRITICAL] Wake bookkeeping is unsafe — the wake path can fail silently — Evidence: except Exception as e:  # never let bookkeeping break the wake

VERDICT: REQUEST CHANGES
[review-meta] structured=freeform-gated quality=freeform_fallback"""

FREEFORM_APPROVE = """SUMMARY
Looks fine.

ISSUES
No issues found.

VERDICT: APPROVE
[review-meta] structured=freeform-gated quality=freeform_fallback"""

STRUCTURED_APPROVE = """SUMMARY
The change is a safe addition.

ISSUES
No issues found.

VERDICT: APPROVE
[review-meta] structured=json model=default confidence=1.0"""

STRUCTURED_RC = """SUMMARY
Real problem found.

ISSUES
- [CRITICAL] Real defect — breaks the wake path — Evidence: except Exception as e:  # never let bookkeeping break the wake

VERDICT: REQUEST CHANGES
[review-meta] structured=json model=default confidence=1.0"""

REVIEW = {"pr_number": 999, "title": "t", "repo": "r", "body": ""}


def _arm(monkeypatch, structured_results, freeform_text):
    """Stub the two dispatch boundaries; return the call-count dict."""
    calls = {"structured": 0, "freeform": 0}

    # **_kw so this double tolerates keyword growth on _structured_review. It has broken
    # twice on additive params (ground_diff #5848 t2, dockerfile_findings #5848 t5) while
    # testing neither — these tests pin the #5287 RETRY semantics, not the signature.
    def fake_structured(review, diff, pr_number=None, repo=None, **_kw):
        calls["structured"] += 1
        idx = min(calls["structured"], len(structured_results)) - 1
        return structured_results[idx]

    def fake_freeform(prompt, pr_number=None, repo=None, diff=None):
        calls["freeform"] += 1
        return freeform_text

    monkeypatch.setattr(pda, "_structured_review", fake_structured)
    monkeypatch.setattr(pda, "_run_forge_review", fake_freeform)
    monkeypatch.setattr(pda, "_build_prompt", lambda review, diff: "PROMPT")
    return calls


class TestFreeformRcRetry:
    def test_degraded_rc_triggers_one_structured_retry_and_supersedes(self, monkeypatch):
        calls = _arm(monkeypatch, [None, STRUCTURED_APPROVE], FREEFORM_RC)
        out = pda._obtain_review_summary(REVIEW, DIFF, 999, "r")
        assert calls == {"structured": 2, "freeform": 1}
        assert parse_verdict(out) == "APPROVE"
        assert "superseded by structured retry" in out

    def test_degraded_rc_stands_when_retry_unavailable(self, monkeypatch):
        calls = _arm(monkeypatch, [None, None], FREEFORM_RC)
        out = pda._obtain_review_summary(REVIEW, DIFF, 999, "r")
        assert calls == {"structured": 2, "freeform": 1}
        assert parse_verdict(out) == "REQUEST CHANGES"
        assert "structured retry unavailable" in out

    def test_persistent_structured_rc_stands(self, monkeypatch):
        """NOT approval laundering: a structured retry that ALSO blocks becomes the verdict."""
        calls = _arm(monkeypatch, [None, STRUCTURED_RC], FREEFORM_RC)
        out = pda._obtain_review_summary(REVIEW, DIFF, 999, "r")
        assert calls == {"structured": 2, "freeform": 1}
        assert parse_verdict(out) == "REQUEST CHANGES"
        assert "structured=json" in out

    def test_degraded_approve_is_not_retried(self, monkeypatch):
        calls = _arm(monkeypatch, [None, None], FREEFORM_APPROVE)
        out = pda._obtain_review_summary(REVIEW, DIFF, 999, "r")
        assert calls == {"structured": 1, "freeform": 1}
        assert out == FREEFORM_APPROVE

    def test_structured_rc_is_not_retried(self, monkeypatch):
        calls = _arm(monkeypatch, [STRUCTURED_RC], FREEFORM_RC)
        out = pda._obtain_review_summary(REVIEW, DIFF, 999, "r")
        assert calls == {"structured": 1, "freeform": 0}
        assert out == STRUCTURED_RC

    def test_retry_flag_off_leaves_degraded_rc_alone(self, monkeypatch):
        calls = _arm(monkeypatch, [None, STRUCTURED_APPROVE], FREEFORM_RC)
        monkeypatch.setattr(pda, "_freeform_rc_retry_enabled", lambda: False)
        out = pda._obtain_review_summary(REVIEW, DIFF, 999, "r")
        assert calls == {"structured": 1, "freeform": 1}
        assert out == FREEFORM_RC


class TestUnevidencedBlockingDemotion:
    def test_gate_demotes_rc_resting_only_on_unevidenced_blocking(self):
        text = (
            "SUMMARY\nBad.\n\nISSUES\n"
            "- [CRITICAL] Data loss on retry path — will crash on empty input — Evidence:\n"
            "\nVERDICT: REQUEST CHANGES"
        )
        out = pda._gate_freeform_review(text, DIFF)
        assert parse_verdict(out) == "NEEDS REVIEW"
        assert "#5287" in out
        assert "blocking_issue_without_evidence" in out

    def test_gate_keeps_rc_when_blocking_evidence_grounded(self):
        text = (
            "SUMMARY\nBad.\n\nISSUES\n"
            "- [CRITICAL] Data loss on retry path — will crash on empty input — "
            "Evidence: except Exception as e:  # never let bookkeeping break the wake\n"
            "\nVERDICT: REQUEST CHANGES"
        )
        out = pda._gate_freeform_review(text, DIFF)
        assert parse_verdict(out) == "REQUEST CHANGES"

    def test_predicate_narrowness(self):
        unevidenced = {"severity": "CRITICAL", "title": "x", "why": "y", "evidence": ""}
        evidenced = {"severity": "WARNING", "title": "x", "why": "y", "evidence": "real line"}
        info = {"severity": "INFO", "title": "x", "why": "y", "evidence": ""}
        assert pda._demote_unevidenced_blocking("REQUEST CHANGES", [unevidenced]) is True
        assert pda._demote_unevidenced_blocking("REQUEST CHANGES", [unevidenced, evidenced]) is False
        assert pda._demote_unevidenced_blocking("APPROVE", [unevidenced]) is False
        assert pda._demote_unevidenced_blocking("REQUEST CHANGES", [info]) is False
        assert pda._demote_unevidenced_blocking("REQUEST CHANGES", []) is False


class TestFreeformMetaHonesty:
    def test_no_grounded_evidence_flag_reaches_freeform_meta(self):
        """The gate dropped every issue as ungrounded but rendered meta with n_ungrounded=0,
        so `no_grounded_evidence` could never appear on a freeform-gated row (#5287)."""
        text = (
            "SUMMARY\nBad.\n\nISSUES\n"
            "- [CRITICAL] Invented — problem — Evidence: this_line_is_not_in_any_diff_at_all()\n"
            "\nVERDICT: REQUEST CHANGES"
        )
        out = pda._gate_freeform_review(text, DIFF)
        assert "no_grounded_evidence" in out
