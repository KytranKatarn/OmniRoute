"""#6819 — clearing a FALSE finding must correct the INPUT, never override the OUTPUT.

⚠️ THE SAFETY HALF IS THE POINT OF THIS FILE. The whole risk of a dismissal affordance is that
it becomes a merge bypass. These tests pin the asymmetry: a dismissal removes ONE finding from
the set the verdict is computed over, and if anything blocking remains the PR STAYS blocked.
`verdict_refusal` and the tier ceiling are never consulted, let alone weakened — the verdict
legitimately changes, which is why "nothing merges on a non-approval" (decision #953) still holds.

MOTIVATING CASE, measured on PR #3418 att7: `[WARNING] Potential SQL Injection — the `like`
variable is constructed using f-string formatting with user-provided input (`q`)`. The code is
`like = f"%{q}%"` followed by `params.extend([like] * 6)` against a query containing only `%s`
placeholders — a textbook parameterised LIKE. The finding is specific, confident, non-hedged and
FALSE, so no severity gate touches it, and re-rolling was the only move available.
"""

from __future__ import annotations

from pathlib import Path

from tools.repair_bay.services.finding_dismissal import (
    apply_dismissals,
    dismiss_finding,
    finding_fingerprint,
)

FALSE_SQLI = "- [WARNING] Potential SQL Injection — the `like` variable is built with an f-string from `q`"
REAL_LEAK = "- [WARNING] Leak — the connection is never closed, leaking a handle per request"
NIT = "- [INFO] naming — prefer snake_case"


def _summary(*findings, verdict="REQUEST CHANGES"):
    return "SUMMARY\nreview\n\nISSUES\n" + "\n".join(findings) + f"\n\nVERDICT: {verdict}"


def _verdict(text):
    for line in text.splitlines():
        if line.startswith("VERDICT:"):
            return line.split(":", 1)[1].strip()
    return "<none>"


def _dis(line, who="kytran", why="verified false: the value is a bound parameter"):
    return {finding_fingerprint(line): {"rationale": why, "dismissed_by": who}}


class TestFingerprint:
    def test_it_survives_severity_and_whitespace_drift(self):
        a = "- [WARNING] Potential SQL Injection — the `like` variable is built with an f-string from `q`"
        b = "- [INFO]   Potential SQL Injection  —  the `like` variable is built with an f-string from `q`  "
        assert finding_fingerprint(a) == finding_fingerprint(b)

    def test_two_different_findings_never_collide(self):
        assert finding_fingerprint(FALSE_SQLI) != finding_fingerprint(REAL_LEAK)


class TestDismissingClearsAFalseBlock:
    def test_the_only_blocker_dismissed_relaxes_the_verdict(self):
        out, n = apply_dismissals(_summary(FALSE_SQLI, NIT), _dis(FALSE_SQLI))
        assert n == 1
        assert _verdict(out) == "APPROVE"

    def test_the_finding_is_kept_and_annotated_not_deleted(self):
        """A reader must see that a human OVERRULED an observation — not that it never existed."""
        out, _ = apply_dismissals(_summary(FALSE_SQLI), _dis(FALSE_SQLI, who="kytran", why="bound parameter"))
        assert "Potential SQL Injection" in out
        assert "[WARNING]" not in out
        assert "DISMISSED as a false positive by kytran" in out
        assert "bound parameter" in out
        assert "[dismissals]" in out


class TestItIsNotAMergeBypass:
    """⚠️ Each of these would make the affordance a bypass."""

    def test_a_remaining_real_finding_still_blocks(self):
        out, n = apply_dismissals(_summary(FALSE_SQLI, REAL_LEAK), _dis(FALSE_SQLI))
        assert n == 1
        assert _verdict(out) == "REQUEST CHANGES"
        assert "[WARNING] Leak" in out

    def test_dismissing_nothing_changes_nothing(self):
        s = _summary(REAL_LEAK)
        out, n = apply_dismissals(s, {})
        assert (out, n) == (s, 0)

    def test_a_dismissal_that_matches_no_finding_changes_nothing(self):
        s = _summary(REAL_LEAK)
        out, n = apply_dismissals(s, _dis(FALSE_SQLI))
        assert n == 0
        assert _verdict(out) == "REQUEST CHANGES"

    def test_it_fails_closed_on_empty_input(self):
        assert apply_dismissals("", _dis(FALSE_SQLI)) == ("", 0)
        assert apply_dismissals(None, _dis(FALSE_SQLI)) == (None, 0)


class TestNoSilentDismissal:
    """The rationale is the audit trail. Refused in CODE as well as by the CHECK constraint, so
    the caller gets a real error instead of an IntegrityError."""

    def test_a_blank_rationale_is_refused(self):
        for bad in ("", "   ", None):
            r = dismiss_finding(1, "o/r", FALSE_SQLI, bad, "kytran")
            assert r["ok"] is False
            assert "rationale" in r["error"]

    def test_an_unattributed_dismissal_is_refused(self):
        r = dismiss_finding(1, "o/r", FALSE_SQLI, "because it is false", "")
        assert r["ok"] is False
        assert "attributed" in r["error"]

    def test_an_empty_finding_is_refused(self):
        r = dismiss_finding(1, "o/r", "", "because it is false", "kytran")
        assert r["ok"] is False


class TestTheRouteExistsAndIsGated:
    """A service nobody can call is not an affordance. Asserted on the SOURCE and the URL map,
    not by mocking a request — the #2737 lesson: the verdict rule stays server-side, so the test
    must check the real registration."""

    ROUTES = Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "github_routes.py"

    def test_the_route_is_declared(self):
        src = self.ROUTES.read_text()
        assert '"/api/forge/pr-reviews/<int:pr_number>/dismiss-finding"' in src
        assert "def forge_dismiss_finding(" in src

    def test_it_is_admin_gated(self):
        """@login_required AND @admin_required must both sit on it — a dismissal changes a
        verdict, so it is not an anonymous action."""
        src = self.ROUTES.read_text()
        i = src.index("def forge_dismiss_finding(")
        head = src[max(0, i - 400) : i]
        assert "@login_required" in head
        assert "@admin_required" in head

    def test_it_refuses_a_blank_rationale_at_the_route(self):
        src = self.ROUTES.read_text()
        i = src.index("def forge_dismiss_finding(")
        body = src[i : i + 2600]
        assert "rationale is required" in body
        assert "400" in body

    def test_it_does_not_merge_or_touch_the_verdict_gate(self):
        """⚠️ THE INVARIANT: this endpoint corrects an input. It must never call the merge path
        or re-implement/relax verdict_refusal.

        ⚠️ SCANS EXECUTABLE CODE ONLY — the docstring legitimately NAMES `verdict_refusal` to say
        it is not touched. A first cut of this test grepped the raw source and failed on its own
        prose: the same "documentation read as code" mistake as #3406, committed in a test."""
        import ast as _ast

        tree = _ast.parse(self.ROUTES.read_text())
        fn = next(
            (n for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef) and n.name == "forge_dismiss_finding"),
            None,
        )
        assert fn is not None, "route function not found"
        body = list(fn.body)
        if body and isinstance(body[0], _ast.Expr) and isinstance(getattr(body[0], "value", None), _ast.Constant):
            body = body[1:]  # drop the docstring
        code = "\n".join(_ast.unparse(n) for n in body)
        assert "merge_pr(" not in code, "a dismissal must never merge"
        assert "verdict_refusal" not in code, "a dismissal must not re-implement or relax the gate"
        assert "coverage_ack" not in code
        # and it MUST go through the service rather than writing the verdict directly
        assert "dismiss_finding(" in code


class TestWiredIntoEveryVerdictSurface:
    """#6819 — a corrected verdict visible on one pane and not another is a split brain. All
    THREE surfaces (list_reviews, get_review, stamp_merge_states) must consult dismissals."""

    SVC = Path(__file__).resolve().parents[1] / "tools" / "repair_bay" / "services" / "pr_review_service.py"

    def test_all_three_surfaces_apply_dismissals(self):
        src = self.SVC.read_text()
        # 1 definition + 3 call sites
        assert src.count("_summary_after_dismissals(") >= 4, "a verdict surface is not wired"

    def test_the_helper_fails_safe(self):
        src = self.SVC.read_text()
        i = src.index("def _summary_after_dismissals(")
        body = src[i : i + 1400]
        assert "return summary" in body, "on error it must return the ORIGINAL summary"
