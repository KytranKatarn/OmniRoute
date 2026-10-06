"""The receiver records who has been delivering data, and drift_guard alarms when one goes quiet.

2026-10-05: gov-watch pushed into the graph for ~17 days with every batch refused (its URL named
the hub), 61,022 failed batches, nobody told — its own monitor had no heartbeat writer in the
deployed image. A receipt written by the RECEIVER cannot fail with the sender. Recording fakes.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from consumer import entity_graph_routes as routes  # noqa: E402
from ingest.parliament import drift_guard  # noqa: E402
from ingest.shared import entity_push_receipts as rc  # noqa: E402


class _Savepoint:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.savepoints += 1
        return self

    def __exit__(self, et, ev, tb):
        return False


class FakeConn:
    def __init__(self, rowcount=1, boom=False):
        self.rowcount, self.boom, self.calls, self.savepoints = rowcount, boom, [], 0

    def begin_nested(self):
        return _Savepoint(self)

    def execute(self, clause, params=None):
        if self.boom:
            raise RuntimeError("db exploded")
        self.calls.append((" ".join(str(clause).split()), params))
        return type("R", (), {"rowcount": self.rowcount})()


class TestRecordPush:
    def test_writes_one_receipt_for_a_batch_with_data(self):
        c = FakeConn()
        assert rc.record_push(c, "gov-watch", 120, 80) is True
        sql, params = c.calls[0]
        assert "INSERT INTO parliament.ingest_log" in sql and "NOT EXISTS" in sql
        assert params == {"t": "entity_push_gov-watch", "seen": 120, "saved": 80, "m": 30}

    def test_is_throttled_in_sql_not_in_python(self):
        """A 3,000-batch catch-up must not write 3,000 rows: the guard is the INSERT's own WHERE."""
        sql = FakeConn() and rc._INSERT
        assert "run_at > now() - make_interval(mins => :m)" in " ".join(sql.split())

    def test_a_throttled_insert_reports_false(self):
        assert rc.record_push(FakeConn(rowcount=0), "gov-watch", 5, 5) is False

    def test_an_empty_batch_is_not_proof_of_a_feed(self):
        c = FakeConn()
        assert rc.record_push(c, "gov-watch", 0, 0) is False and c.calls == []

    def test_an_unknown_product_is_ignored(self):
        c = FakeConn()
        assert rc.record_push(c, "wtf", 5, 5) is False and c.calls == []

    def test_a_failing_insert_never_raises(self):
        assert rc.record_push(FakeConn(boom=True), "gov-watch", 5, 5) is False

    def test_runs_in_a_savepoint_so_it_cannot_abort_the_ingest(self):
        c = FakeConn()
        rc.record_push(c, "gov-watch", 5, 5)
        assert c.savepoints == 1


class TestDriftGuardWatchesTheReceipts:
    def test_every_pushing_product_is_watched(self):
        for task in rc.PUSH_TASKS.values():
            assert task in drift_guard._MAX_AGE_DAYS, task

    def test_gov_watch_is_required_and_has_a_short_window(self):
        assert "entity_push_gov-watch" in drift_guard._REQUIRED_TASKS
        assert drift_guard._MAX_AGE_DAYS["entity_push_gov-watch"] <= 3, "gov-watch pushes NIGHTLY"

    def test_the_slower_products_are_watched_but_not_required(self):
        for t in ("entity_push_legal-watch", "entity_push_civic-watch", "entity_push_market-watch"):
            assert t in drift_guard._MAX_AGE_DAYS and t not in drift_guard._REQUIRED_TASKS


def test_the_endpoint_records_a_receipt_only_when_data_landed():
    seen = {}

    class FakeCur:
        def execute(self, *a, **k):
            self._rows = []

        def fetchall(self):
            return []

        def close(self):
            pass

    class FakeConnection:
        connection = type("C", (), {"cursor": staticmethod(lambda: FakeCur())})()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeEngine:
        def begin(self):
            return FakeConnection()

    def fake_execute_values(cur, sql, rows, template=None, page_size=None, fetch=False):
        if "shared.entities" in sql and fetch:
            return [(100 + i, r[2], True) for i, r in enumerate(rows)]
        return None

    def fake_record(conn, product, seen_n, saved_n):
        seen.setdefault("calls", []).append((product, seen_n, saved_n))

    orig = (routes._eng, routes.execute_values, routes.record_push)
    routes._eng, routes.execute_values, routes.record_push = (lambda: FakeEngine()), fake_execute_values, fake_record
    os.environ["INTERNAL_API_KEY"] = "k"
    try:
        from flask import Flask
        app = Flask(__name__)
        app.register_blueprint(routes.entity_graph_bp)
        post = lambda payload: app.test_client().post(  # noqa: E731
            "/api/internal/entity-graph/ingest", data=json.dumps(payload),
            headers={"X-Internal-Key": "k", "Content-Type": "application/json"})
        ent = {"canonical_name": "Acme Ltd", "entity_type": "organization"}
        assert post({"product": "gov-watch", "entities": [ent]}).status_code == 200
    finally:
        routes._eng, routes.execute_values, routes.record_push = orig
    (product, seen_n, saved_n), = seen["calls"]
    assert product == "gov-watch" and seen_n >= 1 and saved_n >= 1
