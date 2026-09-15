"""A hire row must reach the HIRE handler, not the generic one.

THE BUG (live until this fix, reported by the owner as
"when i hit approve in approvals tab for new hire i get error : Invalid approval ID format")

Six steps, each individually reasonable:

  1. `approvals_pending` builds the hire row with `"category": "hiring"`  (approvals_routes ~577)
  2. ...then OVERWRITES it: `a["category"] = category_of(a["action_type"])`  (~725)
  3. `category_of("hire_candidate")` returns **'agents'** — and 'hiring' is not a value
     in that taxonomy AT ALL, so the original label cannot survive the round trip
  4. the template branched on `a.category === 'hiring'` -> now false
  5. -> the else branch, `_dhqApproveApproval(a.id)`, POSTs the raw "hire:<id>" to the
     GENERIC endpoint
  6. whose guard admits only autonomy/contractor/bridge -> "Invalid approval ID format"

The same break hit the REJECT path (approvals_routes ~1035) and the SHORTLIST renderer,
which is why the cards rendered as bare text with no candidate picker.

⚠️ THE FIX IS NOT TO WIDEN THE GUARD. Letting "hire:" through the generic endpoint would
hand a hire to a handler that cannot hire anyone. The dedicated
`/api/approvals/hire/<id>/approve` route exists and works — the row just has to be
recognised so the right handler is chosen. These tests therefore pin the ROUTING, and
deliberately assert the generic guard STAYS narrow.

WHY `source` AND NOT `category`: `source` is set once per builder and never reassigned;
`category` is a PRESENTATION taxonomy that the server re-stamps and is free to change
(#2736 added the sub-tabs for good reasons). Identity, not presentation.
"""

import ast
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_TEMPLATE = _ROOT / "tools" / "department_hq" / "templates" / "department_hq.html"
_ROUTES = _ROOT / "tools" / "department_hq" / "approvals_routes.py"


def _template() -> str:
    return _TEMPLATE.read_text(encoding="utf-8")


def _routes() -> str:
    return _ROUTES.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The premise: category really is re-stamped, and really does lose 'hiring'
# --------------------------------------------------------------------------- #


def test_category_of_hire_candidate_is_not_hiring():
    """THE PREMISE. If this ever returns 'hiring', the original bug is gone by another
    route and the branch below could safely key off category again — but until then,
    a template that trusts `category` for hires is broken by construction."""
    from tools.department_hq.services.approvals_bulk import ACTION_CATEGORY, category_of

    assert category_of("hire_candidate") != "hiring", (
        "category_of now yields 'hiring' — re-read this test's premise before relying on it"
    )
    assert "hiring" not in set(ACTION_CATEGORY.values()), (
        "'hiring' has become a real category value; the taxonomy changed under this test"
    )


def test_the_pending_list_still_restamps_category():
    """The overwrite is the mechanism. If it disappears, this test should be revisited."""
    src = _routes()
    assert 'a["category"] = category_of(' in src, (
        "the category re-stamp is gone — the failure mode this guards may no longer exist"
    )


# --------------------------------------------------------------------------- #
# The fix: hires are recognised by SOURCE
# --------------------------------------------------------------------------- #


def test_hire_rows_are_branched_on_source_not_category():
    """THE REGRESSION. Pre-fix the template had three `a.category === 'hiring'` tests,
    every one of them dead."""
    tpl = _template()
    assert "a.category === 'hiring'" not in tpl, (
        "a hire branch still keys off the re-stamped `category` — it can never be true"
    )
    assert tpl.count("a.source === 'hire'") >= 3, (
        "expected the shortlist, approve and deny branches to key off source"
    )


def test_the_hire_handlers_are_the_ones_wired_up():
    """Branching correctly is worthless if it calls the generic handler anyway."""
    tpl = _template()
    for marker, handler in (
        ("approveBtn.textContent = 'Approve Selected'", "_dhqApproveHire"),
        ("denyBtn.textContent = 'Reject'", "_dhqRejectHire"),
    ):
        idx = tpl.index(marker)
        window = tpl[idx : idx + 400]
        assert handler in window, f"{marker!r} does not lead to {handler}"


def test_source_is_assigned_once_and_never_restamped():
    """The whole argument for using `source` is that nothing rewrites it."""
    src = _routes()
    assert '"source": "hire"' in src
    assert not re.search(r'\[\s*["\']source["\']\s*\]\s*=', src), (
        "something now reassigns `source` — it is no longer a stable identity field"
    )


# --------------------------------------------------------------------------- #
# The guard must STAY narrow — widening it is the tempting wrong fix
# --------------------------------------------------------------------------- #


def test_the_generic_endpoint_still_refuses_a_hire_id():
    """Do NOT 'fix' this by adding 'hire' here.

    The generic handler resolves autonomy/contractor/bridge rows. A hire needs
    `/api/approvals/hire/<id>/approve`, which creates an agent. Admitting "hire:" would
    route a hire into a handler that cannot hire anyone — a silent wrong action, worse
    than the loud 400 the owner saw.
    """
    src = _routes()
    guards = re.findall(r"prefix not in \(([^)]*)\)", src)
    assert guards, "the prefix guard is gone entirely"
    for g in guards:
        assert "hire" not in g, (
            "'hire' was added to the generic approve/reject guard — see this test's docstring"
        )


def test_the_dedicated_hire_routes_exist():
    """The routing fix assumes these are real."""
    tree = ast.parse(_routes())
    routed = {
        d.args[0].value
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        for d in n.decorator_list
        if isinstance(d, ast.Call)
        and d.args
        and isinstance(d.args[0], ast.Constant)
        and isinstance(d.args[0].value, str)
    }
    for path in ("/api/approvals/hire/<int:hire_id>/approve", "/api/approvals/hire/<int:hire_id>/reject"):
        assert any(path == r for r in routed), f"missing dedicated hire route: {path}  (have: {sorted(r for r in routed if 'hire' in r)})"
