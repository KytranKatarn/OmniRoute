"""A scheduled window must never ship a list the owner has not seen (task #5235).

Owner directive 2026-07-26: Repair Bay schedules a window, batches multiple fixes
into it, announces the time AND the fix list ahead of time, and only then deploys.

Every test here pins an invariant that, if it broke, would turn the feature into
theatre — the window would still "work" while quietly defeating its own purpose:

  * opening UNANNOUNCED     -> the owner never saw the list; coordination is fake
  * opening an EMPTY window -> DR suppressed for no work at all
  * appending after ANNOUNCE-> ships something the owner did not approve
  * announce that FAILED to send marked as announced -> silent approval
  * close without per-item outcomes -> "closed" hides what actually shipped

The schema is applied idempotently here because archie_test drifts from prod
(#5231) — a DB-backed test that silently SKIPS is worse than no test.
"""

import sys
from datetime import datetime, timedelta, timezone

import pytest
from tests.dbguard import db_or_skip, import_or_skip  # noqa: E402

sys.path.insert(0, "/app")

pytest.importorskip("psycopg2")
mss = pytest.importorskip("services.maintenance_schedule_service")

DDL = """
CREATE TABLE IF NOT EXISTS maintenance_windows (
    id SERIAL PRIMARY KEY,
    scheduled_start TIMESTAMPTZ NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 90,
    status VARCHAR(16) NOT NULL DEFAULT 'planned',
    reason TEXT,
    created_by VARCHAR(64) NOT NULL DEFAULT 'repair_bay',
    announced_at TIMESTAMPTZ,
    opened_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    suppression_verified BOOLEAN NOT NULL DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS maintenance_window_items (
    id SERIAL PRIMARY KEY,
    window_id INTEGER NOT NULL REFERENCES maintenance_windows(id) ON DELETE CASCADE,
    item_type VARCHAR(16) NOT NULL DEFAULT 'other',
    ref VARCHAR(128),
    title TEXT NOT NULL,
    added_by VARCHAR(64) NOT NULL DEFAULT 'repair_bay',
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(16) NOT NULL DEFAULT 'planned',
    notes TEXT
);
"""


@pytest.fixture(autouse=True)
def schema_and_stubs(monkeypatch):
    """Ensure tables exist, silence Telegram, stub the DR side."""
    try:
        from database import get_db_cursor
    except Exception as exc:
        import_or_skip(exc, "database module")
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(DDL)
    except Exception as e:
        db_or_skip(e)

    monkeypatch.setattr(mss, "_announce", lambda *a, **k: True)
    yield
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM maintenance_windows WHERE created_by = 'pytest'")
    except Exception:
        pass


def _mk(reason="test", minutes=30, when=None):
    return mss.schedule_window(
        when or datetime.now(timezone.utc) + timedelta(hours=1),
        duration_minutes=minutes,
        reason=reason,
        created_by="pytest",
    )


@pytest.fixture
def dr(monkeypatch):
    """Stub the DR service so no SSH happens."""

    class Fake:
        started = None
        ended = False

        def start_window(self, **kw):
            self.started = kw
            return {"ok": True, "suppression_verified": True}

        def end_window(self, **kw):
            self.ended = True
            return {"ok": True, "dr_cover_restored": False, "warnings": ["promoted fork"]}

    f = Fake()
    import services.maintenance_window_service as real

    monkeypatch.setattr(real, "start_window", lambda **kw: f.start_window(**kw))
    monkeypatch.setattr(real, "end_window", lambda **kw: f.end_window(**kw))
    return f


# ----------------------------------------------------------- the manifest ----
def test_repair_bay_can_batch_several_fixes_into_one_window():
    w = _mk()
    for n in (2471, 2472, 2473):
        r = mss.add_item(w["id"], f"fix PR #{n}", item_type="pr", ref=str(n))
        assert r["ok"], r
    assert len(mss.get_manifest(w["id"])) == 3


def test_next_window_is_where_repair_bay_appends():
    w = _mk()
    nxt = mss.next_window()
    assert nxt is not None and nxt["id"] == w["id"]


# --------------------------------------------------- the coordination gate ---
def test_a_window_will_not_open_unannounced(dr):
    """The owner seeing the list beforehand IS the feature."""
    w = _mk()
    mss.add_item(w["id"], "some fix")
    rep = mss.open_scheduled(w["id"])
    assert rep["ok"] is False
    assert "never announced" in rep["error"]
    assert dr.started is None, "DR suppression must not be armed"


def test_an_empty_window_will_not_open(dr):
    """No work means no reason to suppress DR."""
    w = _mk()
    mss.announce_plan(w["id"])
    rep = mss.open_scheduled(w["id"])
    assert rep["ok"] is False
    assert "empty" in rep["error"]
    assert dr.started is None


def test_announced_then_opens_and_arms_dr(dr):
    w = _mk()
    mss.add_item(w["id"], "fix A", item_type="pr", ref="2471")
    ann = mss.announce_plan(w["id"])
    assert ann["ok"] and ann["items"] == 1
    assert "fix A" in ann["body"], "the fix list must be IN the announcement"
    rep = mss.open_scheduled(w["id"])
    assert rep["ok"] is True
    assert dr.started is not None, "DR suppression was never armed"


def test_adding_a_fix_after_announcement_forces_re_announcement():
    """Otherwise we ship something the owner never approved."""
    w = _mk()
    mss.add_item(w["id"], "fix A")
    mss.announce_plan(w["id"])
    r = mss.add_item(w["id"], "fix B — snuck in later")
    assert r["ok"] and r["reannounce_required"] is True
    assert mss.list_windows()[0]["status"] == "planned", "must fall back to planned"


def test_a_failed_announcement_does_not_count_as_announced(monkeypatch):
    """A send that never reached the owner must not unlock the window."""
    monkeypatch.setattr(mss, "_announce", lambda *a, **k: False)
    w = _mk()
    mss.add_item(w["id"], "fix A")
    ann = mss.announce_plan(w["id"])
    assert ann["ok"] is False and ann["announced"] is False
    with_status = [x for x in mss.list_windows() if x["id"] == w["id"]][0]
    assert with_status["status"] == "planned"


def test_manifest_is_frozen_once_open(dr):
    w = _mk()
    mss.add_item(w["id"], "fix A")
    mss.announce_plan(w["id"])
    mss.open_scheduled(w["id"])
    r = mss.add_item(w["id"], "late addition")
    assert r["ok"] is False and "frozen" in r["error"]


# ------------------------------------------------------------------ close ----
def test_close_reports_per_item_outcomes_not_just_closed(dr):
    w = _mk()
    mss.add_item(w["id"], "fix A")
    mss.add_item(w["id"], "fix B")
    mss.announce_plan(w["id"])
    mss.open_scheduled(w["id"])
    items = mss.get_manifest(w["id"])
    rep = mss.close_scheduled(w["id"], {items[0]["id"]: "deployed", items[1]["id"]: "failed"})
    assert rep["tally"].get("deployed") == 1
    assert rep["tally"].get("failed") == 1
    assert dr.ended is True


def test_close_stays_honest_that_dr_cover_is_not_restored(dr):
    """boston-2 is a promoted fork — scanning again is not cover."""
    w = _mk()
    mss.add_item(w["id"], "fix A")
    mss.announce_plan(w["id"])
    mss.open_scheduled(w["id"])
    rep = mss.close_scheduled(w["id"])
    assert rep["dr_cover_restored"] is False


def test_unreported_items_stay_visible_as_planned(dr):
    """An item nobody reported on is NOT the same as one that succeeded."""
    w = _mk()
    mss.add_item(w["id"], "fix A")
    mss.announce_plan(w["id"])
    mss.open_scheduled(w["id"])
    rep = mss.close_scheduled(w["id"])  # no outcomes supplied
    assert rep["tally"].get("planned") == 1
    assert "deployed" not in rep["tally"]
