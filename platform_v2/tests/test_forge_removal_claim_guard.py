"""Regression: a removal-critique cannot stand against a diff that removes nothing (#5286).

OBSERVED LIVE 2026-07-27 on PR #2503 (the ComfyUI idle-clock fix — a PURE-ADDITION diff,
0 deleted lines, 29 added). The freeform-gated review returned REQUEST CHANGES on:

    [CRITICAL] PR removes a needed guard — The `try-except` block is necessary to prevent
    bookkeeping failures from halting the wake operation. — Evidence: `except Exception as e:`

Every existing gate correctly PASSES this finding, which is exactly why it survived:
the cited line is a real ADDED line, so grounding (#5009) passes it and polarity (#5075)
returns 'added' — the _critiques_the_removal carve-out is never even consulted (it only
applies to removed_only evidence). The CLAIM is what is false: the guard it says was
removed is the very guard the PR ADDS, and no diff with zero removed lines can support
any "this PR removes X" finding. That is deterministically checkable from the diff.

The carve-out itself must survive intact — "this PR removes a needed guard" against a diff
that genuinely deletes the guard is a REAL and important finding class (gov-watch PR #45).

All externals are pure; no DB, no GitHub, no model.
"""

from tools.repair_bay.services.pr_diff_analyzer import (
    _count_ungrounded,
    _verify_evidence,
)

# Modeled on the live PR #2503 diff: additions only, zero removed lines.
DIFF_ADDITION_ONLY = """diff --git a/ai_bridge/comfyui_service.py b/ai_bridge/comfyui_service.py
index 72cc39e..abb3a3a 100644
--- a/ai_bridge/comfyui_service.py
+++ b/ai_bridge/comfyui_service.py
@@ -220,6 +220,10 @@ class ComfyUIService:
+        try:
+            from services.comfyui_lifecycle import record_last_used
+            record_last_used()
+        except Exception as e:  # never let bookkeeping break the wake
"""

# The verbatim false finding from the live review.
FALSE_REMOVAL_CRITICAL = {
    "severity": "CRITICAL",
    "title": "PR removes a needed guard",
    "why": "The `try-except` block is necessary to prevent bookkeeping failures " "from halting the wake operation.",
    "evidence": "except Exception as e:",
}

# The gov-watch PR #45 shape: the diff GENUINELY removes the guard.
DIFF_WITH_REMOVAL = """diff --git a/procure/contract_history.py b/procure/contract_history.py
index 1111111..2222222 100644
--- a/procure/contract_history.py
+++ b/procure/contract_history.py
@@ -40,7 +40,7 @@ def _row(row):
     return {
-        "contract_date": _to_date(_first(row, _DATE_COLS), "contract_date", event=True),
+        "contract_date": _to_date(_first(row, _DATE_COLS), "contract_date"),
         "vendor": row.get("vendor"),
     }
"""

REMOVED_LINE = '"contract_date": _to_date(_first(row, _DATE_COLS), "contract_date", event=True),'


class TestRemovalClaimWithoutRemoval:
    def test_removal_claim_dropped_on_pure_addition_diff(self):
        """The live #5286 finding: removal-critique + zero-removal diff -> dropped, tagged."""
        kept, dropped = _verify_evidence([dict(FALSE_REMOVAL_CRITICAL)], DIFF_ADDITION_ONLY)
        assert kept == []
        assert len(dropped) == 1
        assert dropped[0]["_drop_reason"] == "removal_claim_without_removal"

    def test_drop_is_not_counted_as_ungrounded(self):
        """The claim is false but the citation is REAL — it must not feed the #5009 floor."""
        _kept, dropped = _verify_evidence([dict(FALSE_REMOVAL_CRITICAL)], DIFF_ADDITION_ONLY)
        assert _count_ungrounded(dropped) == 0

    def test_legitimate_removal_critique_survives_when_diff_removes(self):
        """The carve-out is UNTOUCHED: a genuine dangerous-deletion critique must keep blocking."""
        issue = {
            "severity": "CRITICAL",
            "title": "This PR removes the event=True guard on contract_date",
            "why": "Award dates are retrospective; deleting the guard lets future dates in.",
            "evidence": REMOVED_LINE,
        }
        kept, dropped = _verify_evidence([issue], DIFF_WITH_REMOVAL)
        assert dropped == []
        assert len(kept) == 1

    def test_removal_claim_phrasing_with_real_removal_not_dropped_by_new_guard(self):
        """Same phrasing as the false finding, but the diff DOES remove lines -> guard stands down."""
        issue = {
            "severity": "CRITICAL",
            "title": "PR removes a needed guard",
            "why": "The event=True marker was required.",
            "evidence": REMOVED_LINE,
        }
        _kept, dropped = _verify_evidence([issue], DIFF_WITH_REMOVAL)
        assert all(d.get("_drop_reason") != "removal_claim_without_removal" for d in dropped)

    def test_fabricated_evidence_still_dominates_as_ungrounded(self):
        """A removal-claim citing a line NOT in the diff is a GROUNDING failure first (#5009)."""
        issue = {
            "severity": "CRITICAL",
            "title": "PR removes a needed guard",
            "why": "The retry wrapper was deleted.",
            "evidence": "def totally_invented_line_never_in_any_diff():",
        }
        _kept, dropped = _verify_evidence([issue], DIFF_ADDITION_ONLY)
        assert len(dropped) == 1
        assert dropped[0]["_drop_reason"] == "evidence_not_in_diff"
        assert _count_ungrounded(dropped) == 1

    def test_behavioral_drops_wording_is_not_a_removal_claim(self):
        """Narrow on purpose: 'the handler drops the connection' describes ADDED behavior,
        not a removal by the PR — it must keep its severity on a pure-addition diff."""
        issue = {
            "severity": "WARNING",
            "title": "Connection handling issue",
            "why": "The handler drops the connection when idle without reconnecting.",
            "evidence": "except Exception as e:",
        }
        kept, dropped = _verify_evidence([issue], DIFF_ADDITION_ONLY)
        assert dropped == []
        assert len(kept) == 1

    def test_empty_diff_fails_open(self):
        """No diff -> nothing to verify -> never drop (mirrors _evidence_polarity)."""
        kept, dropped = _verify_evidence([dict(FALSE_REMOVAL_CRITICAL)], "")
        assert len(kept) == 1
        assert dropped == []
