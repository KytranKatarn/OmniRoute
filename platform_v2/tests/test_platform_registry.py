"""Living Platform Registry invariants (task #5230, Phase 1).

Two properties carry the whole design, and both are the kind that fail silently:

1. **The collector must never touch `notes`.** The curated half of the index
   ("SABnzbd set_config is unreliable — edit sabnzbd.ini directly") cannot be
   derived from a dataclass; it is the accumulated cost of real outages. If a
   regen wipes it, everyone reverts to hand-editing the markdown and the
   generator is a net deletion. A test is the only thing that keeps an
   innocent-looking change to _COLLECTED from destroying it.

2. **Nothing is ever deleted.** A module that vanishes becomes status='absent'
   with last_seen_at frozen. A disappearance is the single most interesting
   event this table records — the phantom-table failure (`backups` documented,
   never existed) in reverse. Deleting the row erases the evidence.
"""

import pytest

pytest.importorskip("psycopg2")

from tests.dbguard import db_or_skip, import_or_skip  # noqa: E402

try:
    from database import get_db_cursor
    from services import platform_registry_service as prs
except Exception as exc:  # pragma: no cover - import/env dependent
    import_or_skip(exc, "platform_registry_service")

_TEST_ID = "zz_test_module_5230"


@pytest.fixture()
def registry():
    """Ensure the table exists; always clean up our synthetic rows."""
    try:
        with get_db_cursor(commit=True) as (_c, cur):
            # get_db_cursor() is a RealDictCursor — row[0] raises KeyError: 0.
            cur.execute("SELECT to_regclass('public.platform_registry_module') AS t")
            row = cur.fetchone()
            if (row["t"] if isinstance(row, dict) else row[0]) is None:
                pytest.skip("migration 465 not applied to this database")
            cur.execute("DELETE FROM platform_registry_module WHERE module_id = %s", (_TEST_ID,))
        yield
    except pytest.skip.Exception:
        raise
    except Exception as exc:
        db_or_skip(exc)
    finally:
        try:
            with get_db_cursor(commit=True) as (_c, cur):
                cur.execute("DELETE FROM platform_registry_module WHERE module_id = %s", (_TEST_ID,))
        except Exception:  # pragma: no cover - cleanup best-effort
            pass


def _synthetic(**over):
    base = {
        "module_id": _TEST_ID,
        "name": "ZZ Test",
        "description": "synthetic",
        "category": "admin_operations",
        "route": "/tools/zz",
        "blueprint_import": None,
        "external_url": None,
        "required_permissions": ["admin:zz"],
        "minimum_role": "ADMIN",
        "minimum_tier": "staff",
        "enabled": True,
        "beta": False,
        "coming_soon": False,
        "version": "1.0",
        "tags": ["zz"],
        "show_on_dashboard": True,
    }
    base.update(over)
    return base


def _row(mid=_TEST_ID):
    with get_db_cursor() as (_c, cur):
        cur.execute("SELECT * FROM platform_registry_module WHERE module_id=%s", (mid,))
        r = cur.fetchone()
        return dict(r) if r else None


# ------------------------------------------------------------ notes safety ---
def test_collector_never_overwrites_curated_notes(registry):
    """THE ONE THAT MATTERS. Notes are hand-written and underivable."""
    live = prs.collect_modules()
    prs.reconcile(live + [_synthetic()])
    assert prs.set_notes(_TEST_ID, "SABnzbd set_config is unreliable — edit sabnzbd.ini directly")

    # A second collection with CHANGED collected fields must refresh those and
    # leave the note untouched.
    prs.reconcile(live + [_synthetic(name="ZZ Renamed", enabled=False)])

    r = _row()
    assert r["name"] == "ZZ Renamed", "collected fields must refresh"
    assert r["enabled"] is False
    assert r["notes"] == "SABnzbd set_config is unreliable — edit sabnzbd.ini directly", (
        "the collector destroyed a curated note — regeneration is now a net "
        "DELETION of the only underivable content in the index (#5230)"
    )


def test_notes_is_not_in_the_collected_column_set():
    """Structural guard: the SQL literally cannot write notes."""
    assert "notes" not in prs._COLLECTED


# ----------------------------------------------------------- never deletes ---
def test_vanished_module_is_marked_absent_not_deleted(registry):
    live = prs.collect_modules()
    prs.reconcile(live + [_synthetic()])
    assert _row()["status"] == "present"

    summary = prs.reconcile(live)  # synthetic no longer collected

    r = _row()
    assert r is not None, "row was DELETED — the disappearance evidence is gone (#5230)"
    assert r["status"] == "absent"
    assert summary["absent"] >= 1


def test_absent_row_freezes_last_seen_at(registry):
    """last_seen_at must answer 'when did it go?', so it stops advancing."""
    live = prs.collect_modules()
    prs.reconcile(live + [_synthetic()])
    seen_when_present = _row()["last_seen_at"]

    prs.reconcile(live)
    assert _row()["last_seen_at"] == seen_when_present, "last_seen_at moved after the module vanished"


def test_absent_module_keeps_its_notes(registry):
    """A vanished module's hard-won gotchas are exactly what you need when it
    comes back or when you are working out why it went."""
    live = prs.collect_modules()
    prs.reconcile(live + [_synthetic()])
    prs.set_notes(_TEST_ID, "why this existed")
    prs.reconcile(live)
    assert _row()["notes"] == "why this existed"


def test_reappearance_is_reported(registry):
    live = prs.collect_modules()
    prs.reconcile(live + [_synthetic()])
    prs.reconcile(live)
    summary = prs.reconcile(live + [_synthetic()])
    assert _row()["status"] == "present"
    assert summary["reappeared"] >= 1


# ------------------------------------------------------------- fail-closed ---
def test_empty_module_set_is_refused(registry):
    """An empty collection would mark EVERY module absent and render an empty
    index — a confident wrong answer, which is the failure this task removes."""
    with pytest.raises(ValueError, match="empty module set"):
        prs.reconcile([])


def test_collect_reads_the_live_registry(registry):
    """Not prose, not a cached copy: the objects the app itself loads."""
    import module_registry as mr

    collected = prs.collect_modules()
    assert len(collected) == len(mr.MODULES)
    assert {m["module_id"] for m in collected} == {m.id for m in mr.MODULES}


def test_summary_reports_freshness(registry):
    """The generated doc must be able to DECLARE ITS OWN STALENESS."""
    prs.reconcile()
    s = prs.registry_summary()
    assert s["collected_at"] is not None
    assert s["present"] >= 1
    assert s["enabled"] <= s["present"]
