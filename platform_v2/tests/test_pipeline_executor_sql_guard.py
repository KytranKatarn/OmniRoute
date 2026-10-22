"""_wait_for_completion interpolates the table AND the id column into its query; both must be allow-listed."""

import pytest

from tools.media_studio.services import pipeline_executor as pe


@pytest.fixture
def no_db(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the database must not be touched for a rejected name")

    monkeypatch.setattr(pe, "get_db_cursor", boom)


def test_unknown_table_is_rejected_before_any_query(no_db):
    assert "Unknown table" in pe._wait_for_completion("users", "id", 1, timeout=1)["error"]


@pytest.mark.parametrize("col", ["id; DROP TABLE media_edits --", "status", "", "ID", "id OR 1=1"])
def test_unknown_id_column_is_rejected_before_any_query(no_db, col):
    assert "Unknown id column" in pe._wait_for_completion("media_edits", col, 1, timeout=1)["error"]


def test_the_three_real_call_shapes_pass_the_guard(monkeypatch):
    """The guard must not reject what the executor actually passes."""
    calls = []

    class Cur:
        def execute(self, sql, params):
            calls.append(sql)

        def fetchone(self):
            return {"status": "completed", "error_message": None}

    import contextlib

    @contextlib.contextmanager
    def fake(*a, **k):
        yield (None, Cur())

    monkeypatch.setattr(pe, "get_db_cursor", fake)
    for table in ("media_generation_queue", "media_edits", "media_batches"):
        r = pe._wait_for_completion(table, "id", 7, timeout=5)
        assert "error" not in r or "Unknown" not in r["error"]
    assert len(calls) == 3 and all(" WHERE id = %s" in c for c in calls)
