"""Regression: the DHQ Dispatch panel must surface WHY a delegation is blocked.

The 2026-09-27 incident: 18 `translate` delegations sat status='blocked' for
33h. delegation_service had stamped the real cause onto
``unified_tasks.blockers`` the whole time --

    Dispatcher refused: Ollama Cloud API error: 410 - {"error":"minimax-m2.5
    was retired at 2026-07-31 ..."}

-- but the panel's query never SELECTed that column, so every row rendered as a
bare "blocked" with an empty REASON cell. The cause was in the database,
fully written, and invisible in the UI. That is what this pins shut.
"""

from __future__ import annotations

import ast
import pathlib
import re


import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTES = ROOT / "tools" / "department_hq" / "dispatch_routes.py"
JS = ROOT / "tools" / "department_hq" / "static" / "js" / "department-hq.js"


def _routes_src() -> str:
    return ROUTES.read_text(encoding="utf-8")


def _js_src() -> str:
    return JS.read_text(encoding="utf-8")


# ── the query ────────────────────────────────────────────────────────────────
def test_pending_query_selects_blockers():
    """The regression itself: blockers must be in the SELECT list."""
    src = _routes_src()
    m = re.search(
        r"SELECT\s+id,\s*status,\s*title,\s*delegation_args,\s*delegation_source,(?P<rest>.*?)\s*FROM\s+unified_tasks",
        src,
        re.S,
    )
    assert m, "could not find the pending-delegations SELECT; update this test"
    assert "blockers" in m.group("rest"), (
        "the pending-delegations query still does not SELECT blockers — a "
        "blocked row will render with no explanation again"
    )


def test_pending_rows_carry_blockers_through_to_the_payload():
    src = _routes_src()
    assert '"blockers": _flatten_blockers(' in src, (
        "pending.append() must pass blockers through to the JSON payload, or "
        "the column is selected and then thrown away"
    )


# ── the flattener ────────────────────────────────────────────────────────────
def _call_flaattener():
    """Compile ONLY ``_flatten_blockers`` from the real source.

    Does NOT import dispatch_routes. The helper is pure (it only uses ``json``),
    so it is lifted out with ``ast`` and exercised in isolation.

    An earlier version imported the module with ``sys.modules`` stubs for
    ``database`` / ``services`` and never restored them. That is a delayed
    grenade: the stub only takes effect if ``database`` had not already been
    imported, and when it did take effect it replaced the real module for the
    REST of the session, so a later test got ``get_db_cursor() is None`` and
    died with a TypeError in test_model_dispatch_reaper — a file this test
    never mentions. A test must not mutate global import state.
    """
    import ast
    import json as _json

    src = ROUTES.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_flatten_blockers":
            ns = {"json": _json}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROUTES), "exec"), ns)
            return ns["_flatten_blockers"]
    raise AssertionError("_flatten_blockers not found in dispatch_routes.py")


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        ("", ""),
        ("   \n  ", ""),
        ("plain refusal", "plain refusal"),
        ("multi\nline   refusal", "multi line refusal"),
        (["a", "b"], "a; b"),
        (["only"], "only"),
        ([{"code": 410}], '{"code": 410}'),
        ({"code": 410}, '{"code": 410}'),
        (410, "410"),
    ],
)
def test_flatten_blockers_normalises_every_jsonb_shape(raw, expected):
    """blockers is jsonb: string, list, dict, or null all have to render."""
    assert _call_flaattener()(raw) == expected


# ── the render ───────────────────────────────────────────────────────────────
def test_js_renders_a_blocked_by_column():
    js = _js_src()
    assert "BLOCKED BY" in js, "the panel never renders the blocker text"


def test_js_column_is_conditional_so_the_healthy_table_keeps_its_width():
    js = _js_src()
    assert "anyBlocked" in js, (
        "the column must be added only when a row is actually blocked, so the "
        "normal (nothing-stuck) table does not change shape"
    )
    # The header must be built conditionally, not hardcoded into every render.
    assert re.search(r"anyBlocked\s*\?\s*'<th>BLOCKED BY</th>'", js), (
        "BLOCKED BY is not gated on anyBlocked — the common table will grow a " "permanently-empty column"
    )


def test_js_escapes_the_blocker_text():
    """blockers is server-controlled text; it must go through esc()."""
    js = _js_src()
    m = re.search(r"var blockerCell = '';(.*?)\n\s*\}\n", js, re.S)
    assert m, "could not locate the blockerCell construction"
    body = m.group(1)
    assert "esc(b)" in body, "blocker text is interpolated unescaped (XSS)"
    assert "esc(p.blockers || '')" in body, "the title attribute is unescaped"


def test_blocker_text_is_truncated_not_dropped():
    """A 300-char refusal must still show its head, not vanish."""
    js = _js_src()
    assert "b.length > 120" in js and "slice(0, 117)" in js


# ── the guard against regressing to a bare "blocked" ─────────────────────────
def test_no_bare_blocked_rendering_path_remains():
    """A blocked row must always have somewhere to show its cause."""
    src = _routes_src()
    m = re.search(
        r"SELECT\s+id,\s*status,\s*title,\s*delegation_args,\s*delegation_source,(?P<rest>.*?)\s*FROM\s+unified_tasks",
        src,
        re.S,
    )
    assert m and "blockers" in m.group("rest")
    # And the JS must consume the key the route emits.
    assert "p.blockers" in _js_src()


def test_module_still_parses():
    ast.parse(_routes_src())
