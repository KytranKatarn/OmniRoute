from unittest.mock import MagicMock
from services.civic_geds_snapshot import open_snapshot, close_snapshot, detect_movements


def test_open_snapshot_inserts_running_row():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = (42,)

    snap_id = open_snapshot(conn)
    assert snap_id == 42

    sql = cur.execute.call_args.args[0]
    assert "geds_snapshots" in sql
    assert "running" in sql.lower()
    conn.commit.assert_called_once()


def test_close_snapshot_marks_completed_with_counts():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    close_snapshot(
        conn,
        42,
        status="completed",
        org_units_seen=10,
        employees_seen=100,
        employees_new=5,
        employees_departed=2,
        employees_changed=3,
    )
    args = cur.execute.call_args.args[1]
    # Snapshot id is last positional in the binding tuple
    assert 42 in args
    assert "completed" in args
    assert 10 in args
    assert 100 in args
    conn.commit.assert_called_once()


def test_detect_movements_skips_first_run():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    # First call: SELECT prior snapshot — no row found
    cur.fetchone.return_value = None

    counts = detect_movements(conn, snapshot_id=1)
    # "role_changed" is part of the movement taxonomy — an exact-dict assertion has to
    # carry every key production returns, or it fails on a legitimate addition.
    assert counts == {
        "new": 0,
        "departed": 0,
        "title_changed": 0,
        "org_changed": 0,
        "role_changed": 0,
        "classification_changed": 0,
    }
