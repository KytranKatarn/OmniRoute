"""GATE 6 — a hedged finding is not a defect, and must not block a merge (#6822).

MEASURED 2026-09-21 across every open PR: **CRITICAL=0, HIGH=0** — not one review claimed a
defect anywhere — yet 5 of 6 were non-APPROVE. The only approval was the PR whose findings
list was EMPTY: it approved because the review said nothing, not because it was judged
sounder. Both demotion paths treat any surviving WARNING as blocking and
`_apply_severity_gate` downgrades only when findings are ALL INFO, so one hedged WARNING
forces REQUEST CHANGES and leaves the author nothing to fix.

Every string in BLOCKED_TODAY is a VERBATIM finding that actually blocked a real PR. Not one
names a concrete failure. That is the whole defect: a conditional whose premise is unverified
cannot be disproved from a diff, so it blocks forever.

⚠️ THE SAFETY PROPERTY IS THE ASYMMETRY, and MUST_STILL_BLOCK is the half of this file that
matters. A hedge demotes ONLY when no definite fault is named anywhere in the finding — so a
hedge used as DECORATION on a real claim ("this may be slow, and the function fails to close
the connection") keeps its severity. If someone later loosens `_DEFINITE_FAULT_RE`, those
cases go green and this file turns red.

⚠️ The veto is about PREDICATIVE FAULTS, not scary consequence NOUNS, following
`_DEFECT_ASSERTION_RE`'s own comment ("not the mere presence of a scary noun"). "potential
information leakage" is hedged security FUD — the commonest unfalsifiable finding — while
"the old path is still vulnerable" is an assertion and blocks.
"""

from __future__ import annotations

import pytest

from tools.repair_bay.services.pr_diff_analyzer import (
    _demote_nonblocking_lines,
    _FALSE_POSITIVE_RUBRIC,
    _is_hedged_without_failure_path,
    _normalize_severity,
)

# Verbatim findings that blocked a real PR today. Each must now demote to INFO.
BLOCKED_TODAY = [
    (
        "#3419",
        "Removed unused code — Removing dead weight reduces complexity but should be confirmed all usages are gone.",
    ),
    (
        "#3419",
        "Dynamic class member assignment — Potential security risk if rec.recommended_ollama or node.ollama_models contains user input.",
    ),
    (
        "#3418",
        "Potential Debug Logging in Production Code — Debug logging should be avoided in production code to prevent unnecessary information leakage and potential security risks.",
    ),
    (
        "#3411",
        "Complexity in Decision Logic — Adding a significant amount of conditional logic and external imports can introduce potential bugs or make the code harder to understand and maintain.",
    ),
    (
        "#3411",
        "Import Guarded by Exception — The import statement is guarded by an exception block which might not be necessary and could hide potential issues during development.",
    ),
    (
        "#3401",
        "Logging of Patch Sanity Checks — The logging level is set to WARNING, which might not provide enough visibility during development or testing.",
    ),
    (
        "#3401",
        "Path Import for Test File — The test file imports several internal functions, which might not be covered by other tests or documentation.",
    ),
    (
        "#3401",
        "Potential DB Error Handling Issue — repos_for_pr_number does not distinguish a failed lookup from an empty result, which could lead to unexpected behavior.",
    ),
]

# Real defect claims. These MUST keep their severity — several hedge deliberately.
MUST_STILL_BLOCK = [
    "The new guard prevents injection but the old path is still vulnerable.",
    "This may be slow, and the function fails to close the connection.",
    "should be confirmed — otherwise a race condition occurs on concurrent writes.",
    "The repo argument is missing, so the lookup will fail for cross-repo PRs.",
    "Potentially unbounded loop: the retry breaks the idempotency guarantee.",
    "Error handling is incorrect here.",
    "No error handling around the subprocess call.",
    "The connection is never closed — this leaks a handle per request and does not handle EINTR.",
    # ⚠️ REGRESSIONS MY FIRST CUT CAUSED, caught by the EXISTING gate tests. Kept here so the
    # next person widening the hedge detector sees them fail in this file too.
    # 1. test_forge_severity_normalizer MUST_KEEP: hedges the VALUE while asserting what the
    #    code DOES. "may be" is not the reviewer hedging about their own confidence.
    "Null dereference — obj may be None and is dereferenced",
    # 2. test_speculative_coverage_gate: a speculative claim WITH a concrete exemplar is a
    #    failure path. _CONCRETE_EXEMPLAR_RE is a veto in both gates for this reason.
    "may not cover all edge cases, such as multiple retries",
]


class TestThePredicate:
    @pytest.mark.parametrize("pr,text", BLOCKED_TODAY, ids=[f"{p}-{i}" for i, (p, _) in enumerate(BLOCKED_TODAY)])
    def test_findings_that_blocked_today_are_hedged(self, pr, text):
        assert _is_hedged_without_failure_path(text) is True, f"{pr}: still reads as a defect claim"

    @pytest.mark.parametrize("text", MUST_STILL_BLOCK)
    def test_a_real_defect_claim_is_never_demoted(self, text):
        assert _is_hedged_without_failure_path(text) is False, "a real fault must keep its severity"

    def test_it_fails_closed_on_nothing(self):
        # An unreadable/empty finding keeps its severity — never demoted by default.
        for blob in ("", None, "   "):
            assert _is_hedged_without_failure_path(blob) is False


class TestWiredIntoBothPaths:
    """A predicate nobody calls is not a gate. #5194 and #5862 are the house precedent — a
    correct guard written and left unwired, twice in one week."""

    def test_the_structured_path_demotes(self):
        issues = [
            {
                "severity": "WARNING",
                "title": "Import Guarded by Exception",
                "why": "might not be necessary and could hide potential issues",
            }
        ]
        out = _normalize_severity(issues)
        assert out[0]["severity"] == "INFO"
        assert out[0]["_demoted_from"] == "WARNING"

    def test_the_structured_path_leaves_a_real_fault_alone(self):
        issues = [
            {
                "severity": "WARNING",
                "title": "Leak",
                "why": "the connection is never closed and fails to release the lock",
            }
        ]
        assert _normalize_severity(issues)[0]["severity"] == "WARNING"

    def test_the_freeform_path_demotes(self):
        line = "- [WARNING] Removed unused code — should be confirmed all usages are gone. — Evidence: +x = 1"
        assert "[INFO]" in _demote_nonblocking_lines(line)

    def test_the_freeform_path_leaves_a_real_fault_alone(self):
        line = "- [WARNING] Leak — the handle is never closed and fails to unwind. — Evidence: +open(p)"
        assert "[WARNING]" in _demote_nonblocking_lines(line)

    def test_a_critical_is_demotable_too(self):
        """#3401's blocker was a CRITICAL, not a WARNING — the gate must cover both."""
        issues = [
            {
                "severity": "CRITICAL",
                "title": "Potential DB Error Handling Issue",
                "why": "could lead to unexpected behavior",
            }
        ]
        assert _normalize_severity(issues)[0]["severity"] == "INFO"


class TestTheRubricTeachesItToo:
    """Belt and braces: the deterministic gate is the enforcement, but a model that labels
    honestly in the first place produces a review a human can act on. The rubric already sits
    at the top of every prompt."""

    def test_the_severity_rule_is_in_the_prompt(self):
        assert "SEVERITY RULE" in _FALSE_POSITIVE_RUBRIC

    def test_it_names_the_hedges_it_is_about(self):
        rubric = _FALSE_POSITIVE_RUBRIC.lower()
        for phrase in ("should be", "potential", "might", "consider"):
            assert phrase in rubric, f"the rule should name {phrase!r} so the model recognises it"

    def test_it_still_reserves_blocking_for_definite_faults(self):
        # The rule must not read as "prefer INFO" — that would suppress real findings.
        assert "DEFINITE fault" in _FALSE_POSITIVE_RUBRIC
