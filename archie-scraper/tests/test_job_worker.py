import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import MagicMock, patch


def _make_worker():
    pool = MagicMock()
    page = MagicMock()
    pool.claim.return_value = (0, page)
    from job_worker import JobWorker
    return JobWorker(pool), pool, page


def test_enqueue_inserts_pending_row():
    with patch("job_worker.get_db") as mock_db_ctx:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {"id": 42}
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_db_ctx.return_value.__enter__ = lambda s: mock_conn
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        worker, _, _ = _make_worker()
        job_id = worker.enqueue(
            job_type="web_scrape",
            target_url="https://example.com",
            params={},
            egress_tier=1,
            requested_by="test",
        )
        assert job_id == 42
        sql = mock_cur.execute.call_args[0][0]
        assert "INSERT INTO scout_jobs" in sql


def test_unknown_job_type_fails_without_claiming_pool():
    with patch("job_worker.get_db") as mock_db_ctx:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = {
            "id": 99,
            "job_type": "nonexistent_skill",
            "target_url": "https://example.com",
            "params": {},
            "egress_tier": 1,
            "requested_by": "test",
        }
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_db_ctx.return_value.__enter__ = lambda s: mock_conn
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        worker, pool, _ = _make_worker()
        worker._process_next()
        pool.claim.assert_not_called()
