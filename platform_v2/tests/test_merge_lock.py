"""One merge at a time, and say so on the UI (owner, 2026-09-22).

There was NO merge lock of any kind. The only related thing was
`pending_push_service.is_freeze_active()`, a stub that always returns False. So two merges
could interleave, and nothing told the owner one was running.

That is not cosmetic. A merge runs merge_pr -> GitHub -> branch delete -> sync_closed_prs ->
approval reconciliation. Two of those interleaving is how the "already merged / CANCELLED"
confusion appeared earlier today, where an approval row was retired 2s after a merge and
read as a failure.

⚠️ DB-BACKED, NOT IN-PROCESS. archie_platform runs `--workers 4` and archie_scheduler is a
separate process entirely, so a module-level flag would guard one worker and let the other
three straight through (KB #282671).

⚠️ TTL-EXPIRING, AND THAT IS THE POINT. A lock that can WEDGE is worse than no lock — it
would block every merge on the platform forever. The backup lock learned this the hard way
(`/backups/.backup_lock`, released only on PROOF the owner is dead). Here the safe direction
is the opposite: a merge is short, so an old lock is a crash, not a long job.

⚠️ FAIL-OPEN if the store cannot be read. The real merge gates are the verdict, governance
and dependency checks; this lock is an improvement over nothing, not a safety-critical gate.
Failing closed would let a DB blip block every merge — strictly worse than today.
"""

from __future__ import annotations

import pytest

from services.merge_lock_service import (
    LOCK_TTL_SECONDS,
    acquire,
    current,
    release,
)


@pytest.fixture(autouse=True)
def clean():
    release(None, force=True)
    yield
    release(None, force=True)


def test_a_free_lock_can_be_acquired():
    ok, reason = acquire(3433, "KytranKatarn/archie-platform", by="pytest")
    assert ok is True, reason


def test_a_second_pr_is_refused_while_the_first_holds_it():
    acquire(3433, "r", by="pytest")
    ok, reason = acquire(3434, "r", by="pytest")
    assert ok is False
    assert "3433" in reason, f"the refusal must name the PR in flight, got {reason!r}"


def test_the_same_pr_may_re_acquire():
    """A retry of the same merge must not deadlock against its own lock."""
    acquire(3433, "r", by="pytest")
    ok, _ = acquire(3433, "r", by="pytest")
    assert ok is True


def test_release_frees_it():
    acquire(3433, "r", by="pytest")
    release(3433)
    ok, _ = acquire(3434, "r", by="pytest")
    assert ok is True


def test_release_by_a_different_pr_does_not_steal_the_lock():
    acquire(3433, "r", by="pytest")
    release(9999)
    ok, reason = acquire(3434, "r", by="pytest")
    assert ok is False, "a stray release must not free another PR's lock"
    assert "3433" in reason


def test_current_reports_the_holder():
    acquire(3433, "r", by="pytest")
    held = current()
    assert held and held.get("pr") == 3433


def test_current_is_none_when_free():
    assert current() is None


# --- the wedge case: this is the half that matters --------------------------


def test_a_stale_lock_expires_instead_of_wedging_the_platform(monkeypatch):
    """A lock older than the TTL must not block merges forever."""
    import services.merge_lock_service as m

    acquire(3433, "r", by="pytest")
    real = m._now
    monkeypatch.setattr(m, "_now", lambda: real() + LOCK_TTL_SECONDS + 1)
    assert current() is None, "an expired lock must read as free"
    ok, _ = acquire(3434, "r", by="pytest")
    assert ok is True, "an expired lock must not block a new merge"


def test_an_unreadable_store_fails_OPEN(monkeypatch):
    """A DB blip must not block every merge — that would be worse than no lock."""
    import services.merge_lock_service as m

    def boom(*a, **k):
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(m, "_read", boom)
    ok, _ = acquire(3433, "r", by="pytest")
    assert ok is True


# --- wiring: a lock nobody takes is decoration ------------------------------


def test_merge_pr_acquires_and_releases_in_a_finally():
    """Parsed with `ast`, not grepped: a source-grep matches this docstring.

    The release MUST be in a finally — a merge that raises would otherwise leave the lock
    held until the TTL, blocking every other merge for its duration.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("/app/tools/repair_bay/services/github_service.py").read_text())
    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "merge_pr"),
        None,
    )
    assert fn is not None, "merge_pr not found — the wiring target moved"

    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "") for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "acquire" in called or "acquire_merge_lock" in called, "merge_pr never takes the lock"

    released_in_finally = any(
        (getattr(c.func, "id", "") or getattr(c.func, "attr", "")) in ("release", "release_merge_lock")
        for t in ast.walk(fn)
        if isinstance(t, ast.Try)
        for stmt in t.finalbody
        for c in ast.walk(stmt)
        if isinstance(c, ast.Call)
    )
    assert released_in_finally, "the lock is not released in a finally — a raise would wedge it"
