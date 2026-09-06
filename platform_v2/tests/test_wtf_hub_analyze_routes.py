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
