"""Portrait history: record what an approval replaced, and undo it (task #7429)."""

import contextlib
import pathlib

import pytest

from tools.media_studio.services import portrait_history as ph

MS = pathlib.Path(__file__).resolve().parents[1] / "tools" / "media_studio"
SERVICE = (MS / "services" / "portrait_service.py").read_text(encoding="utf-8")
ROUTES = (MS / "routes.py").read_text(encoding="utf-8")
MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2] / "database" / "migrations" / "497_agent_portrait_history.sql"
).read_text(encoding="utf-8")


class Cur:
    """Cursor that answers each fetchone() from a queue and logs every statement."""

    def __init__(self, ones=None, rows=None, fail_on_insert=False):
        self.ones, self.rows, self.log, self.fail_on_insert = list(ones or []), rows or [], [], fail_on_insert

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.log.append((flat, params))
        if self.fail_on_insert and flat.startswith("INSERT INTO agent_portrait_history"):
            raise RuntimeError("table missing")

    def fetchone(self):
        return self.ones.pop(0) if self.ones else None

    def fetchall(self):
        return self.rows


def factory(cur):
    @contextlib.contextmanager
    def get(*a, **k):
        yield (None, cur)

    return get


# --- snapshot ------------------------------------------------------------------------------------------------------


def test_snapshot_reads_the_current_canonical_avatar_and_library_row():
    cur = Cur(
        ones=[
            {"canonical_image_path": "/static/media/agents/2/a.png"},
            {"avatar_url": "media/agents/2/thumb_a.png"},
            {"id": 77},
        ]
    )
    snap = ph.snapshot_current(cur, 2)
    assert snap == {
        "prev_canonical_image_path": "/static/media/agents/2/a.png",
        "prev_avatar_url": "media/agents/2/thumb_a.png",
        "prev_media_id": 77,
    }
    assert (
        "ltrim(COALESCE(file_path, ''), '/') = ltrim(%s, '/')" in cur.log[-1][0]
    )  # '/static/x' and 'static/x' are the same file


def test_snapshot_takes_the_per_agent_lock_before_it_reads_anything():
    """The race the review flagged: two approvals must not both snapshot the same 'previous' portrait."""
    cur = Cur(ones=[None, {"avatar_url": None}])
    ph.snapshot_current(cur, 42)
    first_sql, first_params = cur.log[0]
    assert first_sql == "SELECT pg_advisory_xact_lock(%s, %s)" and first_params == (ph.PORTRAIT_LOCK_NS, 42)
    assert all("pg_advisory" not in sql for sql, _ in cur.log[1:])  # exactly one lock, taken first


def test_snapshot_of_an_agent_with_no_portrait_is_all_none():
    snap = ph.snapshot_current(Cur(ones=[None, {"avatar_url": None}]), 2)
    assert snap == {"prev_canonical_image_path": None, "prev_avatar_url": None, "prev_media_id": None}


# --- record_change -----------------------------------------------------------------------------------------------


PREV = {
    "prev_canonical_image_path": "/static/media/agents/2/old.png",
    "prev_avatar_url": "media/agents/2/thumb_old.png",
    "prev_media_id": 5,
}


def test_record_change_writes_what_was_replaced_and_returns_the_id():
    cur = Cur(ones=[{"id": 41}])
    hid = ph.record_change(
        2, PREV, "/static/media/agents/2/new.png", 9, actor="kytran", action="approve", get_cursor=factory(cur)
    )
    assert hid == 41
    sql, params = cur.log[0]
    assert sql.startswith("INSERT INTO agent_portrait_history") and "RETURNING id" in sql
    assert params == (
        2,
        "approve",
        "/static/media/agents/2/old.png",
        "media/agents/2/thumb_old.png",
        5,
        "/static/media/agents/2/new.png",
        9,
        "kytran",
    )


def test_approving_the_image_that_is_already_canonical_records_nothing():
    cur = Cur(ones=[{"id": 1}])
    assert (
        ph.record_change(2, PREV, "static/media/agents/2/old.png", 5, get_cursor=factory(cur)) is None
    )  # same file, slash differs
    assert cur.log == []


def test_a_history_write_failure_never_blocks_the_approval():
    assert ph.record_change(2, PREV, "/static/new.png", 9, get_cursor=factory(Cur(fail_on_insert=True))) is None


def test_an_unknown_action_is_stored_as_approve():
    cur = Cur(ones=[{"id": 1}])
    ph.record_change(2, PREV, "/static/new.png", 9, action="drop table", get_cursor=factory(cur))
    assert cur.log[0][1][1] == "approve"


# --- list_history --------------------------------------------------------------------------------------------------


def test_history_returns_browser_ready_thumbnails_and_flags_what_can_be_restored():
    rows = [
        {
            "id": 3,
            "action": "approve",
            "prev_canonical_image_path": "/static/x.png",
            "prev_avatar_url": "media/a/t.png",
            "prev_media_id": 5,
            "new_canonical_image_path": "/static/y.png",
            "new_media_id": 9,
            "actor": "k",
            "created_at": None,
            "prev_thumbnail": "media/agents/2/thumb_old.png",
            "prev_model": "juggernaut",
            "new_thumbnail": None,
            "new_model": "flux",
        },
        {
            "id": 2,
            "action": "approve",
            "prev_canonical_image_path": "/static/up.png",
            "prev_avatar_url": None,
            "prev_media_id": None,
            "new_canonical_image_path": "/static/z.png",
            "new_media_id": 8,
            "actor": None,
            "created_at": None,
            "prev_thumbnail": None,
            "prev_model": None,
            "new_thumbnail": None,
            "new_model": None,
        },
    ]
    out = ph.list_history(2, limit=999, get_cursor=factory(Cur(rows=rows)))
    assert out[0]["prev_thumbnail_url"] == "/static/media/agents/2/thumb_old.png"  # bare path normalised
    assert out[0]["can_revert"] is True and out[1]["can_revert"] is False  # no library row -> cannot be restored
    assert out[1]["prev_thumbnail_url"] == "/static/up.png"


def test_history_limit_is_clamped():
    cur = Cur()
    ph.list_history(2, limit=999, get_cursor=factory(cur))
    assert cur.log[0][1] == (2, 50)


# --- revert --------------------------------------------------------------------------------------------------------


def test_revert_re_approves_the_replaced_library_image_as_a_revert():
    calls = []

    def approve(agent_id, media_id, actor=None, action="approve"):
        calls.append((agent_id, media_id, actor, action))
        return {"status": "approved", "agent_id": agent_id, "media_id": media_id, "history_id": 99}

    cur = Cur(ones=[{"id": 4, "agent_id": 2, "prev_media_id": 5}])
    out = ph.revert(2, 4, "kytran", approve, get_cursor=factory(cur))
    assert calls == [(2, 5, "kytran", "revert")]
    assert out["status"] == "reverted" and out["reverted_history_id"] == 4 and out["history_id"] == 99
    assert "WHERE id = %s AND agent_id = %s" in cur.log[0][0]  # an entry of ANOTHER agent can never be applied


def test_reverting_an_entry_of_a_different_agent_is_refused():
    out = ph.revert(2, 4, None, lambda *a, **k: pytest.fail("must not approve"), get_cursor=factory(Cur(ones=[None])))
    assert "not found" in out["error"]


def test_revert_explains_when_the_old_image_is_gone_from_the_library():
    cur = Cur(ones=[{"id": 4, "agent_id": 2, "prev_media_id": None}])
    out = ph.revert(2, 4, None, lambda *a, **k: pytest.fail("must not approve"), get_cursor=factory(cur))
    assert "no longer in the media library" in out["error"]


def test_a_failed_re_approval_is_passed_through_not_reported_as_reverted():
    out = ph.revert(
        2,
        4,
        None,
        lambda *a, **k: {"error": "Media not found"},
        get_cursor=factory(Cur(ones=[{"id": 4, "agent_id": 2, "prev_media_id": 5}])),
    )
    assert out == {"error": "Media not found"}


# --- wiring --------------------------------------------------------------------------------------------------------


def test_approve_canonical_snapshots_before_the_upsert_and_records_after_the_avatar_update():
    body = SERVICE[SERVICE.index("def approve_canonical") : SERVICE.index("def revert_portrait")]
    assert body.index("portrait_history.snapshot_current(cur, agent_id)") < body.index("INSERT INTO agent_portraits")
    assert body.index("agent_service.update_agent(agent_id, avatar_url=thumb)") < body.index(
        "portrait_history.record_change("
    )
    assert '"history_id": history_id' in body


def test_the_card_reports_the_provenance_of_the_approved_image_not_the_newest_generation():
    assert "canon.canonical_model, canon.canonical_provider" in SERVICE
    assert "ltrim(COALESCE(cm.file_path, ''), '/') = ltrim(COALESCE(p.canonical_image_path, ''), '/')" in SERVICE
    assert 'result["canonical_model"]' in SERVICE and 'result["canonical_provider"]' in SERVICE


def test_the_routes_validate_history_id_and_pass_the_actor():
    assert 'actor=getattr(current_user, "username", None))' in ROUTES[ROUTES.index("def api_approve_canonical") :][:900]
    blk = ROUTES[ROUTES.index("def api_portrait_revert") :][:900]
    assert "isinstance(history_id, int)" in blk and "revert_portrait(agent_id, history_id" in blk


def test_the_migration_is_idempotent_and_cascades_with_the_agent():
    assert (
        "CREATE TABLE IF NOT EXISTS agent_portrait_history" in MIGRATION and "CREATE INDEX IF NOT EXISTS" in MIGRATION
    )
    assert "REFERENCES agents(id) ON DELETE CASCADE" in MIGRATION


def test_the_real_sql_runs_against_the_test_database():
    """Applies the migration (twice: idempotent) and runs the portrait list + history queries for real."""
    try:
        from database import get_db_cursor
        from tools.media_studio.services.portrait_service import get_all_agent_portraits

        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute(MIGRATION)
            cur.execute(MIGRATION)
        assert ph.list_history(1) == [] and isinstance(get_all_agent_portraits(), list)
        with get_db_cursor(commit=True) as (
            _c1,
            holder,
        ):  # a SECOND connection must be locked out while one approver is mid-way
            ph.snapshot_current(holder, 999998)
            with get_db_cursor() as (_c2, other):
                other.execute("SELECT pg_try_advisory_xact_lock(%s, %s) AS got", (ph.PORTRAIT_LOCK_NS, 999998))
                assert other.fetchone()["got"] is False
                other.execute("SELECT pg_try_advisory_xact_lock(%s, %s) AS got", (ph.PORTRAIT_LOCK_NS, 999997))
                assert other.fetchone()["got"] is True  # a DIFFERENT agent is not blocked
        with get_db_cursor(commit=True) as (
            _c,
            cur,
        ):  # the advisory-lock SQL itself must be valid, even for an unknown agent
            assert ph.snapshot_current(cur, 999999) == {
                "prev_canonical_image_path": None,
                "prev_avatar_url": None,
                "prev_media_id": None,
            }
    except Exception as exc:  # noqa: BLE001
        if "could not translate host name" in str(exc) or "connect" in str(exc).lower():
            pytest.skip(f"no database: {exc}")
        raise
