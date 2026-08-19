"""The per-capability timeout must REACH the fleet leg — task #5810.

`request_work` resolves a per-capability budget from ``CAPABILITY_TIMEOUTS`` (up to
600s), but ``_dispatch_to_node`` used to hardcode ``timeout=240`` and take no timeout
parameter at all. The computed value was silently discarded, so EVERY fleet dispatch of
EVERY capability was capped at 240s — defeating the 600s deliberately granted to
documentation / translate / research / code_analysis, which is exactly the heavy 7B work
``CAPABILITY_NODE_AFFINITY`` (#3955) routes to the fleet on purpose.

Measured 2026-08-18 on PR #2697: 11 of 16 ``code_review`` dispatches died at exactly the
cap; the structured JSON review never completed and fell back to the freeform path, where
the #5009 ungrounded-evidence floor turned a clean PR into NEEDS REVIEW.

These are STRUCTURAL (AST) checks rather than behavioural ones on purpose:
``department_dispatcher`` pulls heavy DB/network deps at import, which is why the sibling
dispatcher tests (e.g. ``test_dispatch_scoring.py``) never import it either. The invariant
being protected is a wiring invariant, so wiring is what we assert — and
``test_checks_actually_catch_the_regression`` proves these checks FAIL against the old
code, per `.claude/rules/repair-bay.md` ("tests that cannot fail are worse than no tests").
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_DISPATCHER = Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "services" / "department_dispatcher.py"

_FLOOR = 240  # the cold-load headroom 240 was introduced to provide (KB #266396)


# ---------------------------------------------------------------------------
# Helpers — all take SOURCE TEXT so the same checks can run against a
# deliberately-defective copy without ever touching the live file.
# ---------------------------------------------------------------------------


def _find_function(source: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found — did it get renamed?")


def _node_post_timeout(source: str) -> ast.expr:
    """Return the AST expr passed as `timeout=` to requests.post inside _dispatch_to_node."""
    fn = _find_function(source, "_dispatch_to_node")
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "post"
            and isinstance(func.value, ast.Name)
            and func.value.id == "requests"
        ):
            for kw in node.keywords:
                if kw.arg == "timeout":
                    return kw.value
            raise AssertionError("requests.post in _dispatch_to_node passes no timeout at all")
    raise AssertionError("no requests.post found inside _dispatch_to_node")


def _call_sites(source: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_dispatch_to_node"
    ]


def _capability_timeouts(source: str) -> dict[str, int]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "CAPABILITY_TIMEOUTS" for t in node.targets
        ):
            return {
                k.value: v.value
                for k, v in zip(node.value.keys, node.value.values)
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
            }
    raise AssertionError("CAPABILITY_TIMEOUTS not found")


def _fleet_leg_is_wired(source: str) -> bool:
    """The whole invariant as one predicate, so the defect-proof test can assert it flips."""
    try:
        fn = _find_function(source, "_dispatch_to_node")
        if not any(a.arg == "timeout" for a in fn.args.args + fn.args.kwonlyargs):
            return False
        if isinstance(_node_post_timeout(source), ast.Constant):
            return False  # hardcoded literal — the caller's budget is being discarded
        sites = _call_sites(source)
        return bool(sites) and all(any(kw.arg == "timeout" for kw in site.keywords) for site in sites)
    except AssertionError:
        return False


@pytest.fixture(scope="module")
def source() -> str:
    return _DISPATCHER.read_text()


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------


def test_dispatch_to_node_accepts_a_timeout(source):
    fn = _find_function(source, "_dispatch_to_node")
    args = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
    assert "timeout" in args, (
        "_dispatch_to_node must accept a timeout — without it the per-capability "
        "budget resolved in request_work cannot reach the fleet leg (#5810)"
    )


def test_node_http_call_does_not_hardcode_its_timeout(source):
    passed = _node_post_timeout(source)
    assert not isinstance(passed, ast.Constant), (
        "requests.post inside _dispatch_to_node passes a LITERAL timeout. That is the "
        "#5810 defect: it silently overrides CAPABILITY_TIMEOUTS for every fleet dispatch."
    )
    assert isinstance(passed, ast.Name) and passed.id == "timeout"


def test_every_call_site_passes_a_timeout(source):
    sites = _call_sites(source)
    assert len(sites) == 4, f"expected 4 _dispatch_to_node call sites, found {len(sites)}"
    for site in sites:
        kwargs = {kw.arg for kw in site.keywords}
        assert "timeout" in kwargs, (
            f"_dispatch_to_node call at line {site.lineno} passes no timeout — it would "
            f"silently fall back to the 240s default and re-open #5810"
        )


def test_call_sites_floor_the_timeout_never_shrink_it(source):
    """Explicit SHORT caller timeouts (e.g. 120 for email_composition) must not reduce the
    fleet leg below the cold-load headroom. Widening only; never narrowing."""
    for site in _call_sites(source):
        expr = next(kw.value for kw in site.keywords if kw.arg == "timeout")
        assert (
            isinstance(expr, ast.Call) and getattr(expr.func, "id", None) == "max"
        ), f"call site at line {site.lineno} must floor its timeout with max(timeout, {_FLOOR})"
        floors = [a.value for a in expr.args if isinstance(a, ast.Constant)]
        assert _FLOOR in floors, f"line {site.lineno}: floor must be {_FLOOR} (KB #266396)"


def test_code_review_has_a_capability_timeout(source):
    timeouts = _capability_timeouts(source)
    assert "code_review" in timeouts, (
        "code_review must carry an explicit budget — it is the same full-diff 7B profile " "as code_analysis (#5810)"
    )
    # NB it was NOT missing, as first assumed: it sat at 300, which equals the default the
    # `if timeout == 300` branch tests for, so the reassignment was a no-op — and 300 never
    # applied on the fleet leg anyway. Present-but-inert, which reads as configured.
    assert timeouts["code_review"] >= 600


def test_capability_timeouts_has_no_duplicate_keys(source):
    """A duplicate key is SILENT — the later entry wins and the earlier one reads as
    applied while doing nothing. Hit for real while fixing #5810: `code_review` was
    already present at 300, so an added `code_review: 600` was shadowed and the table
    looked correct at a glance. Only a value assertion caught it."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "CAPABILITY_TIMEOUTS" for t in node.targets
        ):
            keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            dupes = {k for k in keys if keys.count(k) > 1}
            assert not dupes, f"CAPABILITY_TIMEOUTS has shadowed duplicate key(s): {sorted(dupes)}"
            return
    pytest.fail("CAPABILITY_TIMEOUTS not found")


def test_heavy_capabilities_keep_their_budgets(source):
    """Guard the budgets other tasks fought for: #3549/#3551, #3624-#3630, #3967."""
    timeouts = _capability_timeouts(source)
    for cap in (
        "code_analysis",
        "knowledge_analysis",
        "research",
        "compliance",
        "code",
        "analyze",
        "documentation",
        "translate",
    ):
        assert timeouts.get(cap) == 600, f"{cap} lost its 600s budget"


def test_timeout_error_message_reports_the_real_budget(source):
    """The message hardcoded '240s'. Now that the budget is per-capability, a stale literal
    would send the next investigation hunting a cap that no longer applies."""
    fn = _find_function(source, "_dispatch_to_node")
    seg = ast.get_source_segment(source, fn) or ""
    assert "timeout after 240s" not in seg
    assert "{timeout}s" in seg


# ---------------------------------------------------------------------------
# Proof the checks can fail — reintroduce the defect in a COPY, never the live file
# ---------------------------------------------------------------------------


def test_checks_actually_catch_the_regression(source):
    assert _fleet_leg_is_wired(source), "live source should satisfy the invariant"

    # 1. the original defect: a hardcoded literal in the HTTP call
    defective = source.replace(
        "            resp = requests.post(\n                _gen_url,\n"
        "                json=payload,\n                timeout=timeout,\n            )",
        "            resp = requests.post(\n                _gen_url,\n"
        "                json=payload,\n                timeout=240,\n            )",
    )
    assert defective != source, "defect-injection pattern no longer matches — update this test"
    assert not _fleet_leg_is_wired(
        defective
    ), "the checks PASSED against the reintroduced defect — they cannot catch #5810"

    # 2. a call site that forgets to pass the budget through
    dropped = source.replace(
        "                        timeout=max(timeout, 240),  # #5810 — see the floor note above\n", "", 1
    )
    assert dropped != source
    assert not _fleet_leg_is_wired(dropped)
