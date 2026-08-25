import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from services.civic_geds_refresh import run_geds_refresh

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_run_geds_refresh_chains_passes_in_order():
    calls = []

    async def fake_walk(*a, **kw):
        calls.append("A")
        return 5

    async def fake_sweep(*a, **kw):
        calls.append("B")
        return 50

    def fake_resolve(*a, **kw):
        calls.append("B2")
        return 10

    async def fake_quick(*a, **kw):
        calls.append("C")
        return {"minister": 1, "deputy_minister": 1, "senator": 1, "mp": 1}

    def fake_open(conn):
        calls.append("open")
        return 99

    def fake_close(conn, snap, **kw):
        calls.append("close")
        return None

    def fake_detect(conn, snap):
        calls.append("detect")
        # Must mirror the FULL movement taxonomy in civic_geds_refresh.py — production
        # reads movements["role_changed"] directly, so a partial fake raises KeyError
        # rather than failing an assertion. Production gained "role_changed"; this fake
        # did not follow.
        return {
            "new": 0,
            "departed": 0,
            "title_changed": 0,
            "org_changed": 0,
            "role_changed": 0,
            "classification_changed": 0,
        }

    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [(1, "DN_LEAF")]
    fake_conn.cursor.return_value.__enter__.return_value = fake_cur

    with patch("services.civic_geds_refresh.walk_org_tree", side_effect=fake_walk), patch(
        "services.civic_geds_refresh.sweep_people", side_effect=fake_sweep
    ), patch("services.civic_geds_refresh.resolve_managers", side_effect=fake_resolve), patch(
        "services.civic_geds_refresh.enrich_quick_lists", side_effect=fake_quick
    ), patch(
        "services.civic_geds_refresh.open_snapshot", side_effect=fake_open
    ), patch(
        "services.civic_geds_refresh.close_snapshot", side_effect=fake_close
    ), patch(
        "services.civic_geds_refresh.detect_movements", side_effect=fake_detect
    ), patch(
        "services.civic_geds_refresh._db", return_value=fake_conn
    ), patch(
        "services.civic_geds_refresh.GedsClient"
    ) as Client:
        Client.return_value.__aenter__.return_value = AsyncMock()
        await run_geds_refresh()

    assert calls == ["open", "A", "B", "B2", "C", "detect", "close"]


async def test_run_geds_refresh_marks_failed_on_exception():
    closed_with = {}

    async def fake_walk(*a, **kw):
        raise RuntimeError("boom")

    def fake_open(conn):
        return 99

    def fake_close(conn, snap, **kw):
        closed_with.update(kw)
        closed_with["snap"] = snap

    fake_conn = MagicMock()

    with patch("services.civic_geds_refresh.walk_org_tree", side_effect=fake_walk), patch(
        "services.civic_geds_refresh.open_snapshot", side_effect=fake_open
    ), patch("services.civic_geds_refresh.close_snapshot", side_effect=fake_close), patch(
        "services.civic_geds_refresh._db", return_value=fake_conn
    ), patch(
        "services.civic_geds_refresh.GedsClient"
    ) as Client:
        Client.return_value.__aenter__.return_value = AsyncMock()
        await run_geds_refresh()

    assert closed_with["status"] == "failed"
    assert "boom" in closed_with["error_message"]
    assert closed_with["snap"] == 99
