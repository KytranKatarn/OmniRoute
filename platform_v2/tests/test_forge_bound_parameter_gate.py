"""GATE 7 — a bound parameter is not an injection (#3418).

F.O.R.G.E. blocked PR #3418 with `[WARNING] Potential SQL Injection` citing

    like = f"%{q}%"

That f-string builds a LIKE-pattern **value**. The value is then passed to
`params.extend([like] * 6)` against a query containing only `%s` placeholders, so it
never touches query text and cannot be injected. The finding was verified false by
hand and dismissed by hand — this gate makes that judgement systematic.

WHY THE EXISTING GUARD CANNOT CATCH IT: `_is_spurious_injection` drops an injection
flag whose cited line contains NO string-building marker, which covers a constant or
a `%s` query. Here `f"` IS a string-building marker, so that guard correctly declines
to drop. It reasons about ONE line in isolation, and in one line an f-string building
a VALUE is indistinguishable from one building QUERY TEXT. Only the surrounding diff
separates them.

⚠️ THIS GATE DEMOTES, IT DOES NOT DROP — deliberately, unlike its `spurious_injection`
sibling. A misfiring predicate that DROPS silently erases a CRITICAL security finding;
one that DEMOTES leaves it on the page for a human while unblocking the merge. The cost
is a little noise; the benefit is that this gate can never hide a real vulnerability.

⚠️ MUST_STILL_BLOCK IS THE HALF OF THIS FILE THAT MATTERS. The gate fires only when the
variable is provably bound AND provably absent from query text. A variable that reaches
SQL text — by concatenation, by f-string, or by BOTH binding and interpolation — keeps
its severity. If someone later loosens the "never in SQL text" condition, those cases go
green and this file turns red.
"""

from __future__ import annotations

from tools.repair_bay.services.pr_diff_analyzer import (
    _binds_the_interpolated_value,
    _normalize_severity,
)

# ---------------------------------------------------------------------------
# The VERBATIM finding that blocked PR #3418, and the real diff it cited.
# ---------------------------------------------------------------------------

PR3418_FINDING = {
    "severity": "WARNING",
    "title": "Potential SQL Injection",
    "why": (
        "The `like` variable is constructed using f-string formatting with user-provided "
        "input (`q`). This creates a SQL injection vulnerability if the input is not "
        "properly sanitized."
    ),
    "evidence": 'like = f"%{q}%"',
}

PR3418_DIFF = """diff --git a/platform_v2/services/proposal_service.py b/platform_v2/services/proposal_service.py
--- a/platform_v2/services/proposal_service.py
+++ b/platform_v2/services/proposal_service.py
@@ -130,6 +136,12 @@ def list_proposals(q=None):
+        if q:
+            like = f"%{q}%"
+            where.append(
+                "(title ILIKE %s OR description ILIKE %s OR file_path ILIKE %s"
+                " OR issue_type ILIKE %s OR module ILIKE %s OR status ILIKE %s)"
+            )
+            params.extend([like] * 6)
"""


def _finding(**over):
    out = dict(PR3418_FINDING)
    out.update(over)
    return out


# ---------------------------------------------------------------------------
# The gate fires on the real case
# ---------------------------------------------------------------------------


def test_the_3418_finding_is_recognised_as_a_bound_value():
    assert _binds_the_interpolated_value(PR3418_FINDING, PR3418_DIFF) is True


def test_the_3418_finding_demotes_to_info():
    issues = [_finding()]
    _normalize_severity(issues, PR3418_DIFF)
    assert issues[0]["severity"] == "INFO"
    assert issues[0]["_demoted_from"] == "WARNING"


def test_a_critical_injection_flag_on_a_bound_value_also_demotes():
    issues = [_finding(severity="CRITICAL")]
    _normalize_severity(issues, PR3418_DIFF)
    assert issues[0]["severity"] == "INFO"


# ---------------------------------------------------------------------------
# MUST_STILL_BLOCK — a real injection must survive
# ---------------------------------------------------------------------------

# ⚠️ Each diff below ALSO binds the variable, deliberately. Without that line the case is
# refused by the binding condition and never reaches the safety condition at all — so the
# test would still pass with `_reaches_sql_text` broken. Verified by disabling that helper:
# before this, 2 of 3 cases did not flip. The binding line is what makes these tests bite.
CONCAT_DIFF = """diff --git a/x.py b/x.py
+++ b/x.py
@@
+        val = f"{user_input}"
+        params.append(val)
+        sql = "SELECT * FROM t WHERE name = '" + val + "'"
+        cur.execute(sql)
"""

IDENTIFIER_DIFF = """diff --git a/x.py b/x.py
+++ b/x.py
@@
+        table = f"{requested}"
+        params.append(table)
+        cur.execute(f"SELECT * FROM {table} WHERE id = %s", (pk,))
"""

BOTH_DIFF = """diff --git a/x.py b/x.py
+++ b/x.py
@@
+        needle = f"%{q}%"
+        params.append(needle)
+        sql = f"SELECT * FROM t WHERE tag = '{needle}'"
"""


def test_concatenation_into_sql_still_blocks():
    issue = _finding(evidence='val = f"{user_input}"')
    assert _binds_the_interpolated_value(issue, CONCAT_DIFF) is False
    issues = [issue]
    _normalize_severity(issues, CONCAT_DIFF)
    assert issues[0]["severity"] == "WARNING"


def test_an_interpolated_identifier_still_blocks():
    issue = _finding(evidence='table = f"{requested}"')
    assert _binds_the_interpolated_value(issue, IDENTIFIER_DIFF) is False
    issues = [issue]
    _normalize_severity(issues, IDENTIFIER_DIFF)
    assert issues[0]["severity"] == "WARNING"


def test_bound_AND_interpolated_still_blocks():
    """Fail-closed: being bound somewhere does not excuse reaching SQL text elsewhere."""
    issue = _finding(evidence='needle = f"%{q}%"')
    assert _binds_the_interpolated_value(issue, BOTH_DIFF) is False
    issues = [issue]
    _normalize_severity(issues, BOTH_DIFF)
    assert issues[0]["severity"] == "WARNING"


def test_a_value_never_bound_anywhere_still_blocks():
    """Absence of interpolation is not enough — binding must be POSITIVELY shown."""
    diff = 'diff --git a/x.py b/x.py\n+++ b/x.py\n@@\n+        like = f"%{q}%"\n+        log.info(like)\n'
    assert _binds_the_interpolated_value(_finding(), diff) is False


# ---------------------------------------------------------------------------
# Fail-closed on anything the gate cannot read
# ---------------------------------------------------------------------------


def test_no_diff_leaves_the_finding_untouched():
    """Every pre-existing caller passes no diff — they must stay byte-identical."""
    issues = [_finding()]
    _normalize_severity(issues)
    assert issues[0]["severity"] == "WARNING"
    assert "_demoted_from" not in issues[0]


def test_evidence_that_is_not_an_assignment_is_left_alone():
    assert _binds_the_interpolated_value(_finding(evidence="params.extend([like] * 6)"), PR3418_DIFF) is False


def test_a_non_injection_finding_is_not_this_gates_business():
    issue = _finding(title="Inefficient loop", why="This rebuilds the list on every pass.")
    assert _binds_the_interpolated_value(issue, PR3418_DIFF) is False


# ---------------------------------------------------------------------------
# The wiring itself is the thing most likely to rot (#3424's lesson)
# ---------------------------------------------------------------------------


def test_every_normalize_severity_call_passes_a_diff():
    """GATE 7 cannot fire without a diff, so a call that omits one silently disables it.

    This is the #3424 shape: the gates ran per pass and were discarded at the fold, so they
    bound nothing in production while every unit test still passed. A diff-less call here
    would fail NO other test in this file — the predicate tests construct their own input.

    Parsed with `ast`, not grepped: a source-grep matches this docstring and passes vacuously.
    """
    import ast
    import pathlib

    src = pathlib.Path("/app/tools/repair_bay/services/pr_diff_analyzer.py").read_text()
    tree = ast.parse(src)
    calls = [
        n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_normalize_severity"
    ]
    assert calls, "no _normalize_severity call sites found — the parse found nothing to check"
    thin = [c.lineno for c in calls if len(c.args) < 2]
    assert not thin, f"_normalize_severity called without a diff at line(s) {thin} — GATE 7 is dead there"
