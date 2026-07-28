"""Regression: a failing job must record WHY (#5339).

Measured 2026-07-28 over 7 days of ``autonomy_loop_log``: 64 `partial` + 43
`error` rows, and **107 of 107 recorded no reason at all**. vps_health 38,
delegate_task_worker 25, approvals 11, code_health_backlog_drain 9,
kin_welfare_digest 7, ollama_model_health 6, creed_accounting_audit 5,
warden_backup_verify 2.

A failure row with a NULL reason reports that something broke while withholding
the only field that makes it actionable, and renders identically to a healthy
job in anything that counts statuses.

The fix lives in the resolver, not the 186 call sites that pass no message: most
of those calls happen inside an ``except`` block, where the exception is still
live in ``sys.exc_info()``.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.loop_log import NO_REASON_PREFIX, explain_failure  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_captures_the_live_exception_without_the_caller_passing_it():
    """The core fix: the reason was always available, nobody asked for it."""
    try:
        raise ValueError("ollama refused the connection")
    except ValueError:
        reason = explain_failure("error", items_failed=1, error_message=None)

    assert reason == "ValueError: ollama refused the connection"


def test_caller_message_always_wins():
    """Never overwrite what the code that actually failed chose to say."""
    try:
        raise ValueError("generic boom")
    except ValueError:
        reason = explain_failure("error", items_failed=1, error_message="node 246 unreachable")

    assert reason == "node 246 unreachable"


def test_success_rows_stay_null():
    """Do not decorate healthy runs."""
    assert explain_failure("success", items_failed=0, error_message=None) is None


def test_failure_without_an_exception_records_an_explicit_admission():
    """A job that counts failures without raising must still say something.

    NULL reads as 'nothing went wrong'. An admission is greppable, so the
    remaining gap stays countable per job.
    """
    reason = explain_failure("partial", items_failed=3, error_message=None)
    assert reason.startswith(NO_REASON_PREFIX)
    assert "3 item(s)" in reason
    assert "5339" in reason


def test_no_stale_exception_leaks_into_a_later_call():
    """Python 3 clears the handler's exception on exit — verify, don't assume.

    If a stale exception leaked, an unrelated later failure would be labelled
    with the wrong cause, which is worse than NULL.
    """
    try:
        raise RuntimeError("earlier unrelated failure")
    except RuntimeError:
        pass

    reason = explain_failure("partial", items_failed=1, error_message=None)
    assert "earlier unrelated failure" not in reason
    assert reason.startswith(NO_REASON_PREFIX)


def test_resolver_never_raises():
    """A reason-resolver that can crash takes the whole job log down with it."""
    for args in (
        ("error", None, None),
        ("partial", 0, None),
        (None, None, None),
        ("error", "not-an-int", None),
    ):
        explain_failure(*args)  # must not raise


def test_long_messages_are_truncated():
    reason = explain_failure("error", 1, "x" * 5000)
    assert len(reason) <= 500


def test_every_log_cycle_implementation_is_wired():
    """Invariant: a NEW _log_cycle copy cannot be added without the resolver.

    There are six copy-paste implementations. This test fails if a seventh
    appears unwired — which is exactly how 186 unwired call sites accumulated.
    """
    unwired = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules", ".claude"}]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    src = fh.read()
            except OSError:
                continue
            if not re.search(r"^\s*def _log_cycle\(", src, re.MULTILINE):
                continue
            if "tests/" in path.replace(os.sep, "/"):
                continue
            if "explain_failure" not in src:
                unwired.append(os.path.relpath(path, REPO_ROOT))

    assert not unwired, f"_log_cycle implementations missing the #5339 resolver: {unwired}"


def test_the_wiring_search_actually_found_implementations():
    """Guard the guard: an empty search would make the test above vacuous."""
    found = 0
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules", ".claude"}]
        for name in filenames:
            if name.endswith(".py"):
                path = os.path.join(dirpath, name)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        src = fh.read()
                except OSError:
                    continue
                if re.search(r"^\s*def _log_cycle\(", src, re.MULTILINE):
                    found += 1

    assert found >= 6, f"expected at least 6 _log_cycle implementations, found {found}"


def test_resolver_call_is_guarded_in_every_log_cycle():
    """The resolver runs on the LOGGING path — it must never break it.

    F.O.R.G.E. flagged this on PR #2546 and was right: not every caller reaches
    _log_cycle with platform_v2 on sys.path (fleet_jobs inserts it explicitly
    before its own service imports), so a bare `from services.loop_log import
    explain_failure` could raise ImportError and turn a LOGGED failure into an
    UNLOGGED crash — strictly worse than the bug being fixed.

    Checked structurally via AST, not by text match: this asserts the call has a
    Try ancestor inside the function, which the pre-guard code would fail.
    """
    import ast

    unguarded = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules", ".claude"}]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, REPO_ROOT)
            if rel.replace(os.sep, "/").startswith("platform_v2/tests/"):
                continue
            try:
                tree = ast.parse(open(path, "r", encoding="utf-8").read())
            except (OSError, SyntaxError):
                continue

            for node in ast.walk(tree):
                if not (isinstance(node, ast.FunctionDef) and node.name == "_log_cycle"):
                    continue
                # Collect every node that sits underneath a Try within this function.
                inside_try = set()
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Try):
                        for guarded in ast.walk(sub):
                            inside_try.add(id(guarded))
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Call)
                        and getattr(sub.func, "id", None) == "explain_failure"
                        and id(sub) not in inside_try
                    ):
                        unguarded.append(rel)

    assert not unguarded, f"explain_failure() called unguarded on the logging path in: {unguarded}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
