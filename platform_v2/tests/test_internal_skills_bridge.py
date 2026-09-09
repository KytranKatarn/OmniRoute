"""#5333 skill bridge: the internal-key delegation surface must be usable by archie_engine.

Three defects this pins, all measured live on 2026-08-22:

1. The invokable-skills registry was served ONLY at
   /tools/department-hq/api/dispatch/invokable-skills behind a SESSION-based admin
   gate. archie_engine holds INTERNAL_API_KEY and no session, so it got 401 with
   every credential it has -- the listing endpoint was unreachable by the only two
   surfaces it exists for, while its sibling WRITE path was reachable.
2. /api/internal/delegation/submit HARDCODED delegation_source='web_chat', so the
   'tui'/'cockpit' sources added by #5291 could never be emitted by anything.
3. /api/internal/delegation/<id>/status filtered WHERE delegation_source = 'web_chat',
   so a 'tui' task would 404 on its own status poll.

These assert against the PARSED AST, never raw text: the fix's own comments mention
'web_chat' by name, so a substring grep would match prose and pass while the code
regressed. Docstrings and comments are invisible to ast.
"""

import ast
import os

APP_PY = os.path.join(os.path.dirname(__file__), "..", "app.py")


def _func(name):
    tree = ast.parse(open(APP_PY).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in app.py")


def _decorators(fn):
    out = []
    for d in fn.decorator_list:
        if isinstance(d, ast.Name):
            out.append(d.id)
        elif isinstance(d, ast.Attribute):
            out.append(d.attr)
        elif isinstance(d, ast.Call):
            f = d.func
            out.append(getattr(f, "attr", getattr(f, "id", "")))
    return out


def _route_paths(fn):
    paths = []
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant):
            paths.append(d.args[0].value)
    return paths


def _string_constants(fn):
    """Every string literal in the function body, EXCLUDING its docstring."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]  # drop the docstring
    out = []
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.append(node.value)
    return out


# --------------------------------------------------------------------------
# 1. the registry is reachable on the internal-key surface
# --------------------------------------------------------------------------


def test_internal_registry_route_exists_and_is_internal_key_gated():
    fn = _func("api_internal_invokable_skills")
    assert "/api/internal/delegation/invokable-skills" in _route_paths(fn)
    # The whole point: the engine's bearer must be accepted. A session-only gate
    # here would reproduce the 401 this endpoint exists to fix.
    assert any(d.startswith("require_internal_scope") for d in _decorators(fn)), _decorators(fn)


def test_internal_registry_uses_the_generated_builder_not_a_curated_list():
    fn = _func("api_internal_invokable_skills")
    called = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "build_invokable_skills_registry" in called, "registry must be GENERATED"
    assert "resolve_department_directors" in called, "directors must come from the shared resolver"


def test_both_registry_routes_share_one_director_resolver():
    """A second copy of the director query is how the two surfaces drift apart."""
    dispatch_routes = os.path.join(os.path.dirname(__file__), "..", "tools", "department_hq", "dispatch_routes.py")
    src = open(dispatch_routes).read()
    assert "resolve_department_directors" in src
    # the inlined query must be gone from the DHQ route
    assert "is_department_ai = TRUE" not in src, "DHQ route still has its own director query"


# --------------------------------------------------------------------------
# 2. submit stamps the REAL source
# --------------------------------------------------------------------------


def test_submit_inserts_the_variable_source_not_a_hardcoded_literal():
    fn = _func("api_internal_delegation_submit")
    tuples_with_source = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Tuple):
            names = {e.id for e in node.elts if isinstance(e, ast.Name)}
            if "delegation_source" in names:
                tuples_with_source.append(node)
    assert tuples_with_source, "no INSERT param tuple passes delegation_source as a variable"
    for t in tuples_with_source:
        literals = {e.value for e in t.elts if isinstance(e, ast.Constant)}
        assert "web_chat" not in literals, "INSERT still hardcodes the 'web_chat' source"


def test_submit_validates_the_source_against_the_canonical_set():
    fn = _func("api_internal_delegation_submit")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "VALID_DELEGATION_SOURCES" in names, "submit accepts an unvalidated source"


def test_submit_still_defaults_to_web_chat_for_the_existing_caller():
    """archie-comms sends no source; its behaviour must be byte-identical."""
    fn = _func("api_internal_delegation_submit")
    assert "web_chat" in _string_constants(fn), "the back-compat default was dropped"


# --------------------------------------------------------------------------
# 3. status is not web_chat-only
# --------------------------------------------------------------------------


def test_status_does_not_filter_to_web_chat_only():
    fn = _func("api_internal_delegation_status")
    for s in _string_constants(fn):
        norm = " ".join(s.split())
        assert (
            "delegation_source = 'web_chat'" not in norm
        ), "status still filters to web_chat -- a 'tui' task 404s on its own poll"


def test_status_still_requires_a_delegated_task():
    """Broadened, not removed: a non-delegated task must not be readable here."""
    fn = _func("api_internal_delegation_status")
    sql = " ".join(" ".join(_string_constants(fn)).split())
    assert "delegation_source IS NOT NULL" in sql
