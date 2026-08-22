"""Code Health: the displayed finding count must track the audit, not a cap (#5926).

`notes` is the SINGLE source every UI surface counts from -- #5881 made the badge
(`/severity-summary`), the audit-log table and the details drilldown all derive from
`_parse_audit_findings(notes)`. `notes` was built as `"; ".join(issues[:30])`, so the
count was PINNED at 30: a re-audit that genuinely found fewer changed nothing on
screen. Measured on department_hq 2026-08-22: 33 true findings, badge stuck at 30,
while the re-audit modal reported 12 (the RED subset) -- three numbers, one module.

These tests are source/round-trip level on purpose: the defect lived in a slice
expression and in which variable was returned, neither of which needs a database.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_SERVICE = Path(__file__).resolve().parents[1] / "services" / "code_metrics_service.py"
_ROUTES = Path(__file__).resolve().parents[1] / "tools" / "consciousness" / "code_health_routes.py"


@pytest.fixture(scope="module")
def service_src() -> str:
    return _SERVICE.read_text()


@pytest.fixture(scope="module")
def routes_src() -> str:
    return _ROUTES.read_text()


def _notes_cap(src: str) -> int:
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_NOTES_MAX_FINDINGS" for t in node.targets
        ):
            assert isinstance(node.value, ast.Constant)
            return node.value.value
    raise AssertionError("_NOTES_MAX_FINDINGS not found")


def test_notes_are_not_truncated_at_thirty(service_src):
    """The exact defect: `issues[:30]` pinned every count at 30."""
    assert "issues[:30]" not in service_src, (
        "notes truncation at 30 reintroduced -- the displayed finding count will pin "
        "at 30 and a re-audit reporting fewer findings will not move it (#5926)"
    )


def test_every_notes_join_uses_the_shared_cap(service_src):
    """All three audit profiles (module / website / config) must share one bound.

    Fixing one and leaving another is how a module silently keeps the old ceiling.
    """
    joins = re.findall(r'"; "\.join\(issues\[:([A-Za-z_0-9]+)\]\)', service_src)
    assert len(joins) == 3, f"expected 3 notes joins, found {len(joins)}: {joins}"
    assert set(joins) == {"_NOTES_MAX_FINDINGS"}, f"a join still uses its own bound: {joins}"


def test_the_cap_is_a_sanity_bound_not_a_display_limit(service_src):
    """It must sit far above any real module so it cannot become the reported number.

    department_hq measured 33. A bound near that range would silently re-pin counts.
    """
    cap = _notes_cap(service_src)
    assert cap >= 200, f"_NOTES_MAX_FINDINGS={cap} is low enough to pin a real module's count"


def test_audit_result_reports_total_and_red_separately(routes_src):
    """A re-audit said 12 while the tab said 30 -- same module, same instant.

    12 was the RED subset; the surfaces count every severity. Both must be reported,
    so neither number has to be inferred by the reader.
    """
    assert '"issues": len(issues_list)' in routes_src, "_audit_one must report the TOTAL finding count"
    assert '"issues_red": issues_found' in routes_src, "the red-severity subset must still be reported"


def test_a_forty_five_finding_module_round_trips(routes_src):
    """End-to-end on the real parser: 45 findings must survive notes and come back 45.

    Under `issues[:30]` this returns 30 -- the failing case, proven below.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_ch_routes_probe", _ROUTES)
    assert spec and spec.loader
    # `_parse_audit_findings` is module-level and import-light; grab it without Flask.
    src = _ROUTES.read_text()
    ns: dict = {}
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_parse_audit_findings":
            exec(compile(ast.Module([node], []), str(_ROUTES), "exec"), ns)
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id.startswith("_FINDING_") for t in node.targets
        ):
            exec(compile(ast.Module([node], []), str(_ROUTES), "exec"), ns)
    parse = ns["_parse_audit_findings"]

    issues = [f"LARGE_FILE: module_{i}.py ({500 + i} lines)" for i in range(45)]

    full = "; ".join(issues)
    assert len(parse(full)) == 45, "the parser cannot read an untruncated notes string"

    truncated = "; ".join(issues[:30])
    assert len(parse(truncated)) == 30, "defect-injection no longer reproduces -- update this test"
