"""Cold-load queue handling belongs to the DISPATCHER, not to each caller (#6023).

`request_work` returns `queued=True` when the target model is cold — the work is REAL,
it is on `dispatch_pending_queue`, and `model_dispatch_worker` will run it. A caller that
does not poll sees a falsy result and treats live work as failure (KB #276153).

That was being fixed PER CALLER: `services/cluster_dispatch.py` and
`tools/email_manager/fleet_dispatch.py` each grew a near-identical `queued_dispatch_text`,
and seven modules call one or the other. The F.O.R.G.E. review path never got the
workaround, so an escalated review silently degraded to the weak model on a truncated
diff. N workarounds for one gap is why #276153 keeps recurring.

Now: one implementation, `department_dispatcher.dispatch_awaiting_queue`, with both
helpers delegating to it.
"""

import ast
import inspect


def _src(mod):
    return inspect.getsource(mod)


# ------------------------------------------------- the choke-point implementation


def test_the_dispatcher_owns_the_queue_aware_entry_point():
    from tools.department_hq.services.department_dispatcher import dispatch_awaiting_queue

    params = inspect.signature(dispatch_awaiting_queue).parameters
    for needed in ("capability", "prompt", "poll_timeout_s", "model_override", "prefer_agent"):
        assert needed in params, f"dispatch_awaiting_queue must accept {needed!r}"


def test_it_polls_the_queue_rather_than_giving_up():
    """The whole point: `queued` is live work, not a failure."""
    from tools.department_hq.services.department_dispatcher import dispatch_awaiting_queue

    src = _src(dispatch_awaiting_queue)
    assert "dispatch_pending_queue" in src, "must poll the queue the worker writes to"
    assert "queued" in src, "must distinguish queued from a hard failure"


# ---------------------------------- ⚠️ THE INVARIANT MOST LIKELY TO BE 'IMPROVED' AWAY


def test_dispatch_and_dispatch_json_have_NO_blocking_path():
    """`dispatch()`/`dispatch_json()` are called from WEB REQUEST paths. Blocking them on
    a queue poll would hold a gunicorn worker for up to poll_timeout_s — the
    'never sync-dispatch on the web thread' rule, and the shape of the #1901 cascade.

    Waiting is a SEPARATE opt-in entry point. If someone later makes it the default
    'for convenience', this test is what stops it.
    """
    from tools.department_hq.services import department_dispatcher as dd

    for fname in ("dispatch", "dispatch_json"):
        fn = getattr(dd, fname)
        src = _src(fn)
        assert "dispatch_pending_queue" not in src, f"{fname}() must not poll the queue"
        assert "sleep" not in src, f"{fname}() must not sleep — it runs on request paths"
        params = inspect.signature(fn).parameters
        assert "poll_timeout_s" not in params, f"{fname}() must not grow a wait parameter"


# ------------------------------- the path-safe facade (learned the hard way)


def test_cluster_dispatch_keeps_ensure_import_paths_BEFORE_the_dispatcher_import():
    """⚠️ `cluster_dispatch` is not merely a duplicate — it is the PATH-SAFE facade.

    The scheduler sidecar and bare execs cannot import department_dispatcher cold: it does
    `from db import ...` (ai_bridge) at module scope and raises ModuleNotFoundError
    (KB #272154). Measured while building this: importing the dispatcher directly from a
    bare exec failed exactly that way.

    Flattening this facade into the dispatcher would break every sidecar caller — and only
    at job time, hours later. The ORDER matters, so it is asserted on the AST, not by
    substring presence.
    """
    from services import cluster_dispatch

    fn = next(
        n
        for n in ast.parse(_src(cluster_dispatch)).body
        if isinstance(n, ast.FunctionDef) and n.name == "queued_dispatch_text"
    )
    ensure_line = import_line = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_ensure_import_paths":
            ensure_line = node.lineno
        if isinstance(node, ast.ImportFrom) and "department_dispatcher" in (node.module or ""):
            import_line = node.lineno
    assert ensure_line is not None, "cluster_dispatch must still call _ensure_import_paths()"
    assert import_line is not None, "cluster_dispatch must import the dispatcher lazily"
    assert ensure_line < import_line, "_ensure_import_paths() MUST run BEFORE the dispatcher import"


# ------------------------------------------------- both helpers delegate, none re-implement


def test_both_helpers_delegate_and_neither_reimplements_the_poll():
    """One implementation. If either regrows its own loop the duplication is back, and so
    is the drift that let the review path fall behind."""
    from services import cluster_dispatch
    from tools.email_manager import fleet_dispatch

    for mod, name in ((cluster_dispatch, "cluster_dispatch"), (fleet_dispatch, "fleet_dispatch")):
        fn = next(
            n for n in ast.parse(_src(mod)).body if isinstance(n, ast.FunctionDef) and n.name == "queued_dispatch_text"
        )
        body = ast.dump(fn)
        assert "dispatch_awaiting_queue" in body, f"{name} must delegate to the dispatcher"
        # Asserted on the AST, NOT the source text: `dispatch_pending_queue` appears in
        # this module's own PROSE explaining the delegation, so a substring check goes RED
        # on a docstring — the mirror of the green-on-a-comment trap (#2817).
        assert not any(isinstance(n, ast.While) for n in ast.walk(fn)), f"{name} must not keep its own poll loop"
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        assert not any(
            getattr(c.func, "attr", None) == "execute" for c in calls
        ), f"{name} must not run its own SQL — the poll belongs to the dispatcher"
        assert not any(getattr(c.func, "attr", None) == "sleep" for c in calls), f"{name} must not sleep"


def test_the_public_signatures_are_unchanged_so_callers_are_untouched():
    """Seven modules call these. A signature change would be a silent breakage at job time."""
    from services.cluster_dispatch import queued_dispatch_text as cluster_q
    from tools.email_manager.fleet_dispatch import queued_dispatch_text as mail_q

    for fn, extras in ((cluster_q, ("model_override", "job_id", "prefer_agent")), (mail_q, ())):
        p = inspect.signature(fn).parameters
        for needed in (
            "capability",
            "prompt",
            "system_prompt",
            "json_mode",
            "module_id",
            "local_only",
            "poll_timeout_s",
        ):
            assert needed in p, f"{fn.__module__} lost {needed!r}"
        for extra in extras:
            assert extra in p, f"{fn.__module__} lost {extra!r}"
