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


def _has(path: str, *names: str) -> bool:
    return all(os.path.isdir(os.path.join(path, n)) for n in names)


def _discover_repo_root() -> str:
    """The repo root — never the FILESYSTEM root.

    The old expression was `dirname(__file__)/../..`. On the host that is /mnt/archie_brain,
    correct. In the container /app IS platform_v2, so that is one `..` too many and it
    resolved to **"/"**: os.walk then crawled the whole container, picked up the stale copies
    under /mnt/archie_sandbox/, and reported six "unwired" PRODUCTION files that were nothing
    of the sort — while being slow enough to look like a hang in a full-suite run.
    """
    env = os.environ.get("ARCHIE_REPO_ROOT")
    if env and _has(env, "platform_v2", "ai_bridge"):
        return env
    node = os.path.dirname(os.path.abspath(__file__))
    while True:
        if _has(node, "platform_v2", "ai_bridge"):
            return node
        parent = os.path.dirname(node)
        if parent == node:
            # Never fall through to "/" — see above.
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        node = parent


REPO_ROOT = _discover_repo_root()

# These scans assert a REPO-WIDE invariant, so they are only meaningful where the whole repo
# is present. In the container it is not: platform_v2 is bind-mounted at /app and the rest of
# the repo (ai_bridge included) sits under /mnt/archie_brain WITHOUT platform_v2 — no single
# tree holds both, and only 5 of the 6 _log_cycle implementations are reachable. The `>= 6`
# floors below exist precisely to catch a partial scan, so letting them run there would either
# fail for the wrong reason or, if the floors were lowered, pass vacuously.
# A skip states plainly that the invariant was not checked. Run it on the host, or point
# ARCHIE_REPO_ROOT at a complete checkout.
_REPO_COMPLETE = _has(REPO_ROOT, "platform_v2", "ai_bridge")
requires_full_repo = pytest.mark.skipif(
    not _REPO_COMPLETE,
    reason=(
        f"repo-wide scan needs platform_v2/ and ai_bridge/ under one root; "
        f"{REPO_ROOT!r} has neither pair (set ARCHIE_REPO_ROOT to a full checkout)"
    ),
)

#: Directories the invariant walkers below must not descend into.
#:
#: ``repos/`` is GITIGNORED third-party source (vendored skill repos). It is
#: absent in a clean CI checkout but present on any developer machine, so tests
#: that walked it passed in CI and crashed locally — 64 files under
#: ``repos/claude-skills/claude-pilot/launcher/`` are not valid UTF-8, and
#: ``UnicodeDecodeError`` is a ``ValueError``, so it slipped straight through the
#: ``except OSError`` guards. The invariants here are about OUR ``_log_cycle``
#: implementations; a vendored tree's unrelated code must never fail them.
#: The widened ``except`` clauses are belt-and-braces for the same hazard.
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".claude", "repos", ".venv", "venv"}


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


@requires_full_repo
def test_every_log_cycle_implementation_is_wired():
    """Invariant: a NEW _log_cycle copy cannot be added without the resolver.

    There are six copy-paste implementations. This test fails if a seventh
    appears unwired — which is exactly how 186 unwired call sites accumulated.
    """
    unwired = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    src = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            if not re.search(r"^\s*def _log_cycle\(", src, re.MULTILINE):
                continue
            if "tests/" in path.replace(os.sep, "/"):
                continue
            if "explain_failure" not in src:
                unwired.append(os.path.relpath(path, REPO_ROOT))

    assert not unwired, f"_log_cycle implementations missing the #5339 resolver: {unwired}"


@requires_full_repo
def test_the_wiring_search_actually_found_implementations():
    """Guard the guard: an empty search would make the test above vacuous."""
    found = 0
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                path = os.path.join(dirpath, name)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        src = fh.read()
                except (OSError, UnicodeDecodeError):
                    continue
                if re.search(r"^\s*def _log_cycle\(", src, re.MULTILINE):
                    found += 1

    assert found >= 6, f"expected at least 6 _log_cycle implementations, found {found}"


@requires_full_repo
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
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, REPO_ROOT)
            if rel.replace(os.sep, "/").startswith("platform_v2/tests/"):
                continue
            try:
                tree = ast.parse(open(path, "r", encoding="utf-8").read())
            except (OSError, SyntaxError, UnicodeDecodeError):
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


# ---------------------------------------------------------------------------
# #5339 follow-up (2026-08-02): reasons the job already recorded in `details`
#
# kin_welfare_digest wrote three concrete reasons into details['reasons'] and the
# row still said "(no reason recorded ... raised nothing)". True — the resolver
# was never handed details — but it overstated the remaining worklist and printed
# a contradiction next to the real reasons in the session briefing.
# ---------------------------------------------------------------------------


def test_reasons_recorded_in_details_are_used_instead_of_the_sentinel():
    """The kin_welfare_digest case, verbatim."""
    reason = explain_failure(
        "partial",
        items_failed=4,
        error_message=None,
        details={
            "reasons": [
                "4 agent(s) over budget",
                "14 idle agents (dispatcher routing gap)",
                "16 LLM-free scheduled workers (expected, no action needed)",
            ]
        },
    )
    assert not reason.startswith(NO_REASON_PREFIX)
    assert "4 agent(s) over budget" in reason
    assert "14 idle agents (dispatcher routing gap)" in reason


def test_caller_message_still_beats_details_reasons():
    """Priority is unchanged: the failing code's own words win."""
    reason = explain_failure("partial", 1, "explicit cause", details={"reasons": ["a rollup reason"]})
    assert reason == "explicit cause"


def test_live_exception_still_beats_details_reasons():
    """A raised exception is the acute cause; the rollup is context.

    This ordering is what makes the change provably safe: the details lookup sits
    LAST, so it can only affect rows that would otherwise carry the sentinel.
    """
    try:
        raise ValueError("the thing that actually broke")
    except ValueError:
        reason = explain_failure("error", 1, None, details={"reasons": ["a rollup reason"]})

    assert reason == "ValueError: the thing that actually broke"


def test_details_without_reasons_still_admits_the_gap():
    """weekly_knowledge_report's pre-fix shape must STAY on the worklist.

    Its details carried counts but no reasons — that is a genuine gap, and the
    sentinel is how it stays countable.
    """
    reason = explain_failure("partial", 2, None, details={"candidates": 46, "succeeded": 44, "failed": 2})
    assert reason.startswith(NO_REASON_PREFIX)
    assert "5339" in reason


def test_malformed_details_never_raise_and_never_fabricate():
    """details comes from arbitrary job code and runs on the logging path."""
    for bad in (
        None,
        "not a dict",
        123,
        {"reasons": None},
        {"reasons": []},
        {"reasons": [None, "", "   "]},
        {"reasons": 42},
        {"reasons": {"nested": "dict"}},
        [("reasons", "tuple-of-tuples")],
    ):
        reason = explain_failure("partial", 1, None, details=bad)
        # Must fall through to the honest admission, never invent a reason.
        assert reason.startswith(NO_REASON_PREFIX), f"details={bad!r} produced {reason!r}"


def test_a_bare_string_reason_is_one_reason_not_a_pile_of_characters():
    reason = explain_failure("partial", 1, None, details={"reasons": "single reason"})
    assert reason == "single reason"


def test_details_reasons_are_truncated():
    reason = explain_failure("partial", 1, None, details={"reasons": ["y" * 5000]})
    assert len(reason) <= 500


@requires_full_repo
def test_every_log_cycle_passes_details_to_the_resolver():
    """Invariant: a 7th _log_cycle cannot be wired WITHOUT forwarding details.

    The resolver silently falls back to the sentinel when details is omitted, so
    a partially-wired copy would look correct and quietly lose the reasons. This
    is the same failure mode that let 186 unwired call sites accumulate.
    """
    import ast

    missing = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, REPO_ROOT)
            if rel.replace(os.sep, "/").startswith("platform_v2/tests/"):
                continue
            try:
                tree = ast.parse(open(path, "r", encoding="utf-8").read())
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                if not (isinstance(node, ast.FunctionDef) and node.name == "_log_cycle"):
                    continue
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and getattr(sub.func, "id", None) == "explain_failure":
                        forwards = any(isinstance(a, ast.Name) and a.id == "details" for a in sub.args) or any(
                            k.arg == "details" for k in sub.keywords
                        )
                        if not forwards:
                            missing.append(rel)

    assert not missing, f"_log_cycle does not forward `details` to explain_failure in: {missing}"


@requires_full_repo
def test_the_details_forwarding_search_is_not_vacuous():
    """Guard the guard — an empty walk would make the test above always pass."""
    import ast

    checked = 0
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, REPO_ROOT)
            if rel.replace(os.sep, "/").startswith("platform_v2/tests/"):
                continue
            try:
                tree = ast.parse(open(path, "r", encoding="utf-8").read())
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "_log_cycle":
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Call) and getattr(sub.func, "id", None) == "explain_failure":
                            checked += 1

    assert checked >= 6, f"expected >=6 explain_failure call sites inside _log_cycle, found {checked}"


@requires_full_repo
def test_weekly_knowledge_report_records_its_per_project_reasons():
    """The reason existed at the failure site and was dropped before the row.

    2026-08-02: the job logged "2 of 46 failed" with details {candidates,
    succeeded, failed} and no reasons, so nobody could tell WHICH two projects
    failed or why without grepping container logs that may have rotated.
    """
    import ast

    path = os.path.join(REPO_ROOT, "platform_v2", "tools", "consciousness", "jobs.py")
    tree = ast.parse(open(path, "r", encoding="utf-8").read())

    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "generate_weekly_reports"),
        None,
    )
    assert fn is not None, "generate_weekly_reports not found — did it move?"

    details_keys = set()
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call) and getattr(sub.func, "id", None) == "_log_cycle":
            for kw in sub.keywords:
                if kw.arg == "details" and isinstance(kw.value, ast.Dict):
                    details_keys |= {k.value for k in kw.value.keys if isinstance(k, ast.Constant)}

    assert "reasons" in details_keys, (
        "generate_weekly_reports must pass details['reasons'] — " f"found keys: {sorted(details_keys)}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
