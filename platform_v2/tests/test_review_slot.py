"""Cross-PR F.O.R.G.E. review slot (#7322): only one review runs at a time."""

from __future__ import annotations

import sys
import threading
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

from services import review_slot as rs
from services.review_slot import Config, ReviewQueued, review_slot

ROOT = Path(__file__).resolve().parents[1]
CFG = Config(concurrency=1, ttl_seconds=180, max_hold_seconds=2700, max_wait_seconds=600)


class FakeStore:
    """In-memory twin of PgStore; one shared fake clock stands in for DB NOW()."""

    def __init__(self):
        self.t = 1000.0
        self.slots = {}  # slot -> dict(repo, pr, holder, acquired, beat)
        self.waiters = {}  # (repo, pr) -> dict(since, seen, behind)
        self.fail = False

    def _chk(self):
        if self.fail:
            raise RuntimeError("db down")

    def now_iso(self):
        self._chk()
        return repr(self.t)

    def _live(self, s, cfg):
        return (
            s["holder"] is not None
            and self.t - s["beat"] <= cfg.ttl_seconds
            and self.t - s["acquired"] <= cfg.max_hold_seconds
        )

    def try_acquire(self, slot, repo, pr, holder, cfg):
        self._chk()
        s = self.slots.get(slot)
        if s is not None and self._live(s, cfg):
            return False
        self.slots[slot] = dict(repo=repo, pr=pr, holder=holder, acquired=self.t, beat=self.t)
        return True

    def heartbeat(self, slot, holder):
        self._chk()
        s = self.slots.get(slot)
        if s and s["holder"] == holder:
            s["beat"] = self.t
            return True
        return False

    def release(self, slot, holder):
        self._chk()
        s = self.slots.get(slot)
        if s and s["holder"] == holder:
            s["holder"] = None

    def current_holder(self, cfg):
        self._chk()
        live = [s for s in self.slots.values() if self._live(s, cfg)]
        if not live:
            return None
        s = min(live, key=lambda x: x["acquired"])
        return (s["repo"], s["pr"])

    def mark_waiting(self, repo, pr, since, behind):
        self._chk()
        self.waiters[(repo, pr)] = dict(since=float(since), seen=self.t, behind=behind)

    def clear_waiting(self, repo, pr):
        self.waiters.pop((repo, pr), None)

    def older_waiters(self, repo, pr, since):
        self._chk()
        return sum(
            1
            for k, w in self.waiters.items()
            if k != (repo, pr) and w["since"] < float(since) and self.t - w["seen"] <= rs.WAITER_FRESH_SECONDS
        )


def _no_sleep(_s):
    raise AssertionError("review_slot slept: it waited when it should have acquired or queued at once")


def _slot(store, pr, **kw):
    kw.setdefault("sleep", _no_sleep)  # a test that expects waiting passes its own sleep
    kw.setdefault("config", CFG)
    kw.setdefault("heartbeat_seconds", 3600)  # keep the real heartbeat thread idle in unit tests
    return review_slot("r/x", pr, store=store, clock=lambda: store.t, **kw)


def test_acquire_and_release():
    st = FakeStore()
    with _slot(st, 1) as slot:
        assert slot == 0
        assert st.slots[0]["holder"] is not None
    assert st.slots[0]["holder"] is None


def test_second_review_is_queued_then_runs_after_the_first_finishes():
    """The task's acceptance: second shows queued, then runs; it never runs concurrently."""
    st = FakeStore()
    first = _slot(st, 1)
    first.__enter__()
    seen = {}

    def sleep(s):
        st.t += s
        seen.setdefault("marker", dict(st.waiters.get(("r/x", 2), {})))  # visible while queued
        if st.t >= 1020 and st.slots[0]["holder"] is not None:
            first.__exit__(None, None, None)  # first review finishes

    ran_at = {}
    with _slot(st, 2, sleep=sleep, poll_seconds=5) as slot:
        ran_at["t"], ran_at["slot"] = st.t, slot
    assert ran_at["slot"] == 0 and ran_at["t"] >= 1020  # waited for the first
    assert seen["marker"]["behind"] == ("r/x", 1)  # the PR tab can say "queued behind #1"
    assert ("r/x", 2) not in st.waiters  # marker cleared once running


def test_non_waiting_caller_is_queued_immediately():
    st = FakeStore()
    with _slot(st, 1):
        with pytest.raises(ReviewQueued) as ei:
            with _slot(st, 2, wait=False):
                pytest.fail("must not run while the slot is held")
        assert ei.value.behind_pr == 1 and ei.value.position == 1
    with _slot(st, 2, wait=False) as slot:  # free again
        assert slot == 0


def test_wait_times_out_with_reviewqueued():
    st = FakeStore()
    with _slot(st, 1):

        def sleep(s):
            st.t += s

        with pytest.raises(ReviewQueued):
            with _slot(st, 2, sleep=sleep, max_wait=30, poll_seconds=10):
                pytest.fail("must not run")
    assert ("r/x", 2) not in st.waiters  # a timed-out waiter leaves no stale marker


def test_stale_heartbeat_lease_is_taken_over():
    st = FakeStore()
    st.slots[0] = dict(repo="r/x", pr=9, holder="dead", acquired=st.t, beat=st.t)
    st.t += CFG.ttl_seconds + 1  # crashed process: no heartbeat for > TTL
    with _slot(st, 2, wait=False) as slot:
        assert slot == 0 and st.slots[0]["pr"] == 2


def test_hung_but_heartbeating_holder_expires_at_max_hold():
    st = FakeStore()
    st.slots[0] = dict(repo="r/x", pr=9, holder="hung", acquired=st.t, beat=st.t)
    st.t += CFG.max_hold_seconds + 1
    st.slots[0]["beat"] = st.t  # heartbeat thread still alive, review is not
    with _slot(st, 2, wait=False) as slot:
        assert slot == 0 and st.slots[0]["pr"] == 2


def test_live_lease_is_not_taken_over():
    st = FakeStore()
    st.slots[0] = dict(repo="r/x", pr=9, holder="ok", acquired=st.t, beat=st.t)
    st.t += CFG.ttl_seconds - 1
    with pytest.raises(ReviewQueued):
        with _slot(st, 2, wait=False):
            pass


def test_heartbeat_loop_keeps_a_long_review_alive_and_stops_when_lost():
    st = FakeStore()
    st.slots[0] = dict(repo="r/x", pr=1, holder="me", acquired=st.t, beat=st.t - 100)
    stop = threading.Event()
    done = threading.Thread(target=rs._heartbeat_loop, args=(st, 0, "me", stop, 0.01), daemon=True)
    done.start()
    for _ in range(200):
        if st.slots[0]["beat"] == st.t:
            break
        threading.Event().wait(0.01)
    assert st.slots[0]["beat"] == st.t  # refreshed by the thread
    st.slots[0]["holder"] = "someone-else"  # lease taken over
    done.join(timeout=2)
    assert not done.is_alive()  # thread exits instead of spinning forever
    stop.set()


def test_fifo_older_waiter_goes_first():
    st = FakeStore()
    st.waiters[("r/x", 7)] = dict(since=st.t - 50, seen=st.t, behind=None)  # a live, older waiter
    with pytest.raises(ReviewQueued) as ei:
        with _slot(st, 8, wait=False):  # slot is FREE, but PR 7 queued first
            pytest.fail("must yield to the older waiter")
    assert ei.value.position == 2
    del st.waiters[("r/x", 7)]
    with _slot(st, 8, wait=False):
        pass


def test_dead_waiter_does_not_block_forever():
    st = FakeStore()
    st.waiters[("r/x", 7)] = dict(since=st.t - 500, seen=st.t - 500, behind=None)  # not seen for 500s
    with _slot(st, 8, wait=False) as slot:
        assert slot == 0


def test_concurrency_two_admits_two_then_queues_the_third():
    st = FakeStore()
    cfg = Config(concurrency=2, ttl_seconds=180, max_hold_seconds=2700, max_wait_seconds=600)
    with _slot(st, 1, config=cfg) as a, _slot(st, 2, config=cfg) as b:
        assert {a, b} == {0, 1}
        with pytest.raises(ReviewQueued):
            with _slot(st, 3, config=cfg, wait=False):
                pass


def test_slot_released_when_the_review_raises():
    st = FakeStore()
    with pytest.raises(ValueError):
        with _slot(st, 1):
            raise ValueError("review blew up")  # must propagate, not be eaten by fail-open
    assert st.slots[0]["holder"] is None


def test_db_failure_fails_open_and_runs_the_review():
    st = FakeStore()
    st.fail = True
    ran = []
    with _slot(st, 1) as slot:
        ran.append(slot)
    assert ran == [None]


def test_release_failure_is_not_fatal():
    st = FakeStore()
    with _slot(st, 1):
        st.fail = True  # DB dies mid-review; the lease will expire by TTL
    st.fail = False
    assert st.slots[0]["holder"] is not None  # still held until TTL, but nothing crashed


def _stub_database(monkeypatch, rows=None, boom=False):
    class Cur:
        def execute(self, *_a):
            if boom:
                raise RuntimeError("db down")

        def fetchall(self):
            return rows or []

    @contextmanager
    def get_db_cursor(commit=False):
        yield (None, Cur())

    monkeypatch.setitem(sys.modules, "database", types.SimpleNamespace(get_db_cursor=get_db_cursor))


def test_config_defaults_and_bounds(monkeypatch):
    _stub_database(monkeypatch, boom=True)
    assert rs.load_config() == Config()
    _stub_database(
        monkeypatch,
        rows=[
            {"key": "forge:review_concurrency", "value": "3"},
            {"key": "forge:review_slot_ttl_seconds", "value": "1"},  # below the 30s floor
            {"key": "forge:review_queue_max_wait_seconds", "value": "junk"},
        ],
    )
    cfg = rs.load_config()
    assert cfg.concurrency == 3 and cfg.ttl_seconds == 30 and cfg.max_wait_seconds == 1800


def test_review_pr_takes_the_slot_after_owned_attempt_and_before_the_review():
    src = (ROOT / "tools/repair_bay/services/pr_diff_analyzer.py").read_text()
    body = src.split("def review_pr(", 1)[1].split("def _review_pr_owned", 1)[0]
    assert body.index("owned_attempt(") < body.index("review_slot(") < body.index("_review_pr_owned(")
    assert "ReviewQueued" in body and '"queued_behind"' in body


def test_sidecar_never_blocks_on_the_slot():
    src = (ROOT / "tools/repair_bay/services/pr_diff_analyzer.py").read_text()
    body = src.split("def analyze_pending_prs", 1)[1].split("logger.info(", 1)[0]
    assert "wait_for_slot=False" in body and "queued_behind" in body


def test_migration_defines_the_lease_table():
    sql = (ROOT.parent / "database/migrations/495_review_slots.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS review_slots" in sql
    for col in ("slot", "holder", "acquired_at", "heartbeat_at"):
        assert col in sql
