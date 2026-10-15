"""tools/wtf_hub/routes.py's /api/analyze task registry — completeness guard.

WHY THIS FILE EXISTS. Adding a new task to /api/analyze requires FOUR
consistent edits: the `task not in (...)` allowlist, the `prompts` dict, the
`agent_names` dict, the `capabilities` dict — AND a matching key (plus a
resolution line in `_resolve_agents()`) in the MODULE-LEVEL `_AGENT_IDS`
dict. Missing that last one is invisible in code review (every other dict
looks complete) and doesn't raise an exception: `agent_id = _AGENT_IDS.get(
task)` silently returns None for an unregistered task, and the route's own
`if not agent_id: return 503` turns that into a plain 503 — indistinguishable
from a real hub outage from the caller's side.

Measured live, 2026-09-06 (task #6524's "dispute" task, added in PR #3226):
every /divergence dispute dispatch 503'd instantly while unrelated tasks
(bias, factcheck, geo) kept working normally, because "dispute" was added to
`agent_names`/`capabilities` but never to `_AGENT_IDS` or `_resolve_agents()`.
Root-caused and fixed same day. This test makes that specific gap loud.
"""

import ast
import pathlib

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "tools" / "wtf_hub" / "routes.py"


def _dict_literal_keys(tree: ast.AST, *, target_name: str | None, in_function: str | None) -> set[str]:
    """Collect string keys from a dict literal, found either as a module-level
    assignment (`target_name` set) or a local variable inside a named function
    (`in_function` set)."""
    keys: set[str] = set()
    for node in ast.walk(tree):
        if target_name is not None and isinstance(node, (ast.Assign, ast.AnnAssign)):
            # `_AGENT_IDS: dict[str, int | None] = {...}` parses as AnnAssign,
            # not Assign — its `target` is singular, not a `targets` list.
            if isinstance(node, ast.AnnAssign):
                targets = [node.target] if node.target is not None else []
                value = node.value
            else:
                targets = node.targets
                value = node.value
            if any(isinstance(t, ast.Name) and t.id == target_name for t in targets):
                if isinstance(value, ast.Dict):
                    keys |= {k.value for k in value.keys if isinstance(k, ast.Constant)}
        if in_function is not None and isinstance(node, ast.FunctionDef) and node.name == in_function:
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Assign)
                    and len(inner.targets) == 1
                    and isinstance(inner.targets[0], ast.Name)
                    and inner.targets[0].id == target_name
                    and isinstance(inner.value, ast.Dict)
                ):
                    keys |= {k.value for k in inner.value.keys if isinstance(k, ast.Constant)}
    return keys


def _agent_ids_keys() -> set[str]:
    tree = ast.parse(ROUTES.read_text())
    return _dict_literal_keys(tree, target_name="_AGENT_IDS", in_function=None)


def _analyze_local_dict_keys(dict_name: str) -> set[str]:
    tree = ast.parse(ROUTES.read_text())
    return _dict_literal_keys(tree, target_name=dict_name, in_function="analyze")


def test_every_agent_names_task_has_an_agent_ids_entry():
    agent_names_tasks = _analyze_local_dict_keys("agent_names")
    agent_ids_tasks = _agent_ids_keys()
    missing = agent_names_tasks - agent_ids_tasks
    assert not missing, (
        f"tasks {missing} are in analyze()'s agent_names dict but have no "
        f"entry in the module-level _AGENT_IDS dict — agent_id = _AGENT_IDS."
        f"get(task) returns None for these, and the route turns that into a "
        f"plain 503 indistinguishable from a real outage"
    )


def test_every_capabilities_task_has_an_agent_ids_entry():
    capabilities_tasks = _analyze_local_dict_keys("capabilities")
    agent_ids_tasks = _agent_ids_keys()
    missing = capabilities_tasks - agent_ids_tasks
    assert not missing, f"tasks {missing} are in analyze()'s capabilities dict but missing from _AGENT_IDS"


def test_every_agent_ids_key_is_resolved_in_resolve_agents():
    """A key sitting in _AGENT_IDS with no matching `_AGENT_IDS["x"] = ...`
    line in _resolve_agents() stays None forever — same failure shape,
    different missing piece."""
    src = ROUTES.read_text()
    start = src.index("def _resolve_agents(")
    body = src[start : src.index("\n\n\n", start)]
    for key in _agent_ids_keys():
        assert f'_AGENT_IDS["{key}"] = _get_agent_id(' in body, (
            f'"{key}" has an _AGENT_IDS entry but _resolve_agents() never '
            f"assigns it a real agent id — it stays None forever"
        )


def test_task_allowlist_matches_agent_names_keys():
    """The `task not in (...)` tuple and agent_names' keys must describe the
    SAME set of valid tasks — a task allowed through the gate with no
    agent_names entry raises a KeyError instead of a clean 400/503."""
    tree = ast.parse(ROUTES.read_text())
    allowlist: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.NotIn)
            and isinstance(node.comparators[0], ast.Tuple)
        ):
            allowlist = {elt.value for elt in node.comparators[0].elts if isinstance(elt, ast.Constant)}
            break
    assert allowlist, "could not find the `task not in (...)` allowlist tuple"
    agent_names_tasks = _analyze_local_dict_keys("agent_names")
    assert allowlist == agent_names_tasks, (
        f"allowlist {allowlist} != agent_names keys {agent_names_tasks} — "
        f"a task can pass the gate with no agent_names entry, or vice versa"
    )


# ── concurrency cap on the synchronous /api/analyze (hub overload, 2026-10-15) ─────────────────────────────────────────────────────────────


def _cap_app(monkeypatch, limit, auth_ok=True):
    """A throwaway Flask app whose single view is wrapped by the REAL decorator, with auth stubbed."""
    import importlib
    import sys
    import threading

    from flask import Flask, jsonify

    sys.path.insert(0, str(ROUTES.parents[2]))
    routes = importlib.import_module("tools.wtf_hub.routes")
    monkeypatch.setattr(routes, "_auth_ok", lambda req: auth_ok)

    gate = threading.Event()
    entered = threading.Event()
    app = Flask(__name__)

    @app.post("/slow")
    @routes._cap_concurrency(limit, 7)
    def slow():
        entered.set()
        gate.wait(5)
        return jsonify({"ok": True, "result": {"done": True}})

    return app, gate, entered


def test_analyze_is_wrapped_by_the_cap():
    tree = ast.parse(ROUTES.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "analyze")
    names = [ast.unparse(d) for d in fn.decorator_list]
    assert any("_cap_concurrency" in n for n in names), names


def test_cap_defers_over_limit_with_existing_rate_limited_shape(monkeypatch):
    import threading

    app, gate, entered = _cap_app(monkeypatch, 1)
    first = {}

    def hold():
        first["r"] = app.test_client().post("/slow").get_json()

    t = threading.Thread(target=hold)
    t.start()
    assert entered.wait(5)
    over = app.test_client().post("/slow").get_json()
    gate.set()
    t.join(5)
    assert over == {"ok": True, "result": None, "rate_limited": True, "retry_after": 7}
    assert first["r"]["result"] == {"done": True}


def test_cap_releases_slot_after_each_request(monkeypatch):
    app, gate, _ = _cap_app(monkeypatch, 1)
    gate.set()
    for _ in range(3):
        assert app.test_client().post("/slow").get_json()["result"] == {"done": True}


def test_cap_zero_disables_it(monkeypatch):
    app, gate, _ = _cap_app(monkeypatch, 0)
    gate.set()
    assert app.test_client().post("/slow").get_json()["result"] == {"done": True}


def test_unauthenticated_caller_does_not_consume_a_slot(monkeypatch):
    app, gate, _ = _cap_app(monkeypatch, 1, auth_ok=False)
    gate.set()
    for _ in range(3):  # would be deferred after the first if a slot were taken while unauthenticated
        assert app.test_client().post("/slow").get_json().get("rate_limited") is None
