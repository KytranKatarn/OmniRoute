"""Tests for services/dispatch_queue_reaper.

⚠️ These are PURE tests of the selection logic and the fail-safe behaviour. They do
NOT seed the queue, because pytest forces the empty `archie_test` DB and a content
assertion there passes on zero rows — the vacuity trap this repo has hit before.
What is asserted instead is the shape that can actually be wrong:

  * the TTL must never resolve to 0 (a 0 expires live work on the next sweep)
  * dry_run must default True (an accidental import must not mutate the queue)
  * the predicate must require BOTH "never claimed" AND "past TTL"
  * a row that WAS claimed must be unreachable by the sweep at any age

The SQL itself was verified live against the real table on 2026-09-14 by executing
both enqueue statements inside a rolled-back transaction (arity + column alignment).
"""

import importlib

import pytest

MOD = "services.dispatch_queue_reaper"


@pytest.fixture()
def reaper():
    return importlib.import_module(MOD)


def test_dry_run_defaults_to_true(reaper):
    """An accidental call must COUNT, never mutate. The signature is the guard."""
    import inspect

    sig = inspect.signature(reaper.reap_orphaned_queue_rows)
    assert sig.parameters["dry_run"].default is True, (
        "dry_run must default True — a reaper that writes by default turns an "
        "exploratory import into a bulk mutation of the live queue"
    )


def test_ttl_never_resolves_to_zero(monkeypatch, reaper):
    """A 0/negative/garbage TTL must fall back to the default, NOT to 0.

    A TTL of 0 makes every row already-expired, so the very next sweep would expire
    work a caller is still polling for. Fail-safe means fail LONG, not fail short.
    """

    class _Cur:
        def __init__(self, val):
            self._val = val

        def execute(self, *a, **k):
            return None

        def fetchone(self):
            return {"value": self._val}

    class _Ctx:
        def __init__(self, val):
            self._val = val

        def __enter__(self):
            return (None, _Cur(self._val))

        def __exit__(self, *a):
            return False

    for bad in ("0", "-5", "not-a-number", "", None):
        monkeypatch.setattr("database.get_db_cursor", lambda *a, _v=bad, **k: _Ctx(_v), raising=False)
        got = reaper.get_ttl_minutes()
        assert got == reaper.DEFAULT_TTL_MINUTES, f"TTL {bad!r} -> {got}, expected default"
        assert got > 0


def test_ttl_accepts_a_sane_override(monkeypatch, reaper):
    class _Cur:
        def execute(self, *a, **k):
            return None

        def fetchone(self):
            return {"value": "45"}

    class _Ctx:
        def __enter__(self):
            return (None, _Cur())

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("database.get_db_cursor", lambda *a, **k: _Ctx(), raising=False)
    assert reaper.get_ttl_minutes() == 45


def test_predicate_requires_never_claimed_and_past_ttl(reaper):
    """The selection must not be able to touch a claimed row, at ANY age.

    Read from the module source: the WHERE clause is the entire safety property, and
    it is the thing a future edit is most likely to loosen.
    """
    import inspect

    src = inspect.getsource(reaper.reap_orphaned_queue_rows)
    assert "claimed_at IS NULL" in src, "sweep must exclude rows a worker ever claimed"
    assert "status = 'queued'" in src, "sweep must only touch queued rows"
    assert (
        "expires_at" in src and "queued_at <" in src
    ), "sweep must honour an explicit expires_at AND still handle legacy NULL rows by age"


def test_sweep_is_bounded_and_reports_truncation(reaper):
    """An unreported cap reads as 'all clear' — the exact shape of the bug being fixed."""
    import inspect

    assert isinstance(reaper.MAX_SWEEP, int) and reaper.MAX_SWEEP > 0
    src = inspect.getsource(reaper.reap_orphaned_queue_rows)
    assert "truncated" in src, "a truncated sweep must be reported, never silent"


def test_failure_is_fail_safe_not_fail_open(monkeypatch, reaper):
    """On error the reaper reports ok=False and writes nothing."""

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("database.get_db_cursor", _boom, raising=False)
    res = reaper.reap_orphaned_queue_rows(dry_run=False)
    assert res["ok"] is False
    assert res["reaped"] == 0
    assert "error" in res
