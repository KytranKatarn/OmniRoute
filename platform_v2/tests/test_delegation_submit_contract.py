"""The HTTP delegation surface must store everything the worker reads back.

#6723. /api/internal/delegation/submit validated ``reason`` as REQUIRED, wrote it
to unified_tasks.title + .description, and then omitted it from ``delegation_args``
-- the one place ``execute_delegated_task`` looks for it. The worker's
``reason = args.get("reason", "")`` therefore returned "" on every task from this
endpoint, and ``_execute_via_dispatcher``'s ``if reason:`` skipped the
``Reason: <text>`` line, so the agent was handed only::

    Delegated task -- capability: research
    Args: {"files": [], "working_dir": "/workspace", "history_length": 5}

Measured on task #6722, where the agent replied asking what to research and
quoted those exact three keys back. The task was still marked ``completed``.

Split measured 2026-09-12: delegation_source 'automation' (1118) and 'claude'
(1107) carry a reason 100% of the time -- they go through ``delegate_task()``,
which sets it. 'web_chat' (28), 'tui' (5), 'cockpit' (5/6) and the legacy
NULL-source rows (29) carried it 0% of the time: every human-facing delegation
surface ran instruction-free.

These assert against the PARSED AST of both sides, and derive the expected key
set from the WORKER rather than a hand-written list -- so adding a new
``args.get("x")`` read to the worker fails this test until the endpoint stores
``x``. A hardcoded list would silently stop covering the contract it exists for.
"""

import ast
import os

_HERE = os.path.dirname(__file__)
APP_PY = os.path.join(_HERE, "..", "app.py")
DELEGATION_PY = os.path.join(_HERE, "..", "services", "delegation_service.py")


def _func(path, name):
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path}")


def _delegation_args_keys(fn):
    """Keys of the dict literal the endpoint wraps in psycopg2.extras.Json().

    That call is how delegation_args reaches the INSERT; reading the dict
    literal directly is what makes this test see the real stored shape.
    """
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        target = getattr(node.func, "attr", getattr(node.func, "id", ""))
        if target != "Json" or not node.args:
            continue
        if isinstance(node.args[0], ast.Dict):
            return {k.value for k in node.args[0].keys if isinstance(k, ast.Constant)}
    raise AssertionError("no Json({...}) dict literal found in the submit endpoint")


def _worker_reads(fn, var="args"):
    """Every literal key read as ``<var>.get("key")`` in the worker."""
    keys = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == var
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            keys.add(node.args[0].value)
    return keys


def test_submit_stores_the_reason_it_requires():
    """The endpoint 400s on a missing reason -- so it must persist one."""
    stored = _delegation_args_keys(_func(APP_PY, "api_internal_delegation_submit"))
    assert "reason" in stored, (
        "delegation_args has no 'reason' key, so the worker's "
        "args.get('reason', '') yields '' and the agent is dispatched with no "
        f"instruction. Stored keys: {sorted(stored)}"
    )


def test_endpoint_stores_every_key_the_worker_reads():
    """The real contract: writer keys must cover reader keys.

    Derived from the worker's own source, so a new read is covered automatically.
    """
    stored = _delegation_args_keys(_func(APP_PY, "api_internal_delegation_submit"))
    read = _worker_reads(_func(DELEGATION_PY, "execute_delegated_task"))
    # delegation_source has a documented fallback to the task COLUMN of the same
    # name (task.get(...) or args.get(...)), so it is legitimately optional here.
    read -= {"delegation_source"}
    missing = read - stored
    assert not missing, (
        f"execute_delegated_task reads {sorted(missing)} from delegation_args, "
        f"but the submit endpoint never stores them. Stored: {sorted(stored)}"
    )
