"""Load only the scanner; do not initialize Flask or the production database."""

from contextlib import contextmanager
import importlib.util
from pathlib import Path
import os
import unittest
from unittest.mock import patch

import psycopg2
from psycopg2.extras import RealDictCursor


spec = importlib.util.spec_from_file_location(
    "scanner_under_test", Path(__file__).resolve().parents[1] / "tools/security_network/compliance_service.py"
)
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)

noc_spec = importlib.util.spec_from_file_location(
    "noc_under_test", Path(__file__).resolve().parents[1] / "tools/security_network/noc_routes.py"
)
noc = importlib.util.module_from_spec(noc_spec)
noc_spec.loader.exec_module(noc)


class ConnectivityTests(unittest.TestCase):
    def test_database_failure_returns_unknown(self):
        with patch.object(noc, "get_db_cursor", side_effect=RuntimeError("telemetry unavailable")):
            self.assertEqual(noc._platform_connectivity()["status"], "unknown")

    def test_stale_and_fresh_statuses(self):
        from datetime import datetime, timezone

        for fresh, status in [(False, "stale"), (True, "online")]:

            @contextmanager
            def cursor(commit=False):
                class Cursor:
                    def execute(self, sql):
                        pass

                    def fetchone(self):
                        return {
                            "mesh_status": "connected",
                            "mesh_fresh": fresh,
                            "mesh_last_seen": datetime.now(timezone.utc),
                            "mesh_latency_ms": None,
                        }

                yield None, Cursor()

            with patch.object(noc, "get_db_cursor", cursor):
                result = noc._platform_connectivity()
                self.assertEqual(result["status"], status)
                self.assertIsNone(result["latency_ms"])


class CompliancePersistenceTests(unittest.TestCase):
    def scan(self, *, fail=False, packs=None):
        if packs is None:
            packs = [{"pack_id": "test", "name": "Test", "rules": [{"rule_id": "safe-test"}]}]
        updates = []
        writes = []

        class Cursor:
            def execute(self, sql, params=None):
                normalized = " ".join(sql.split()).lower()
                if normalized.startswith("insert into compliance_scan_results") and fail:
                    raise RuntimeError("simulated result persistence failure")
                if normalized.startswith("insert"):
                    writes.append(params)
                if normalized.startswith("update compliance_scans set"):
                    updates.append(params)

            def fetchall(self):
                return packs

        @contextmanager
        def cursor(commit=False):
            yield None, Cursor()

        with patch.object(service, "get_db_cursor", cursor), patch.object(
            service, "_clear_file_cache", lambda: None
        ), patch.object(service, "_get_host_client", lambda: {"available": lambda: False}), patch.object(
            service, "_execute_check", lambda _: {"status": "pass"}
        ):
            return service.run_scan(), updates, writes

    def test_failed_result_write_keeps_completed_at_null(self):
        result, updates, _ = self.scan(fail=True)
        self.assertEqual(result["status"], "persistence_error")
        self.assertEqual(result["result_persistence_errors"], 1)
        self.assertIsNone(updates[0][0])
        self.assertIn("incomplete", result["error"])

    def test_success_keeps_completed_contract(self):
        result, updates, writes = self.scan()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result_persistence_errors"], 0)
        self.assertIsNotNone(updates[0][0])
        self.assertEqual(len(writes), 2)

    def test_no_packs_do_not_create_scan_or_return_id(self):
        result, updates, writes = self.scan(packs=[])
        self.assertEqual(result["status"], "error")
        self.assertNotIn("scan_id", result)
        self.assertFalse(updates or writes)

    def test_empty_rules_do_not_create_scan_or_return_id(self):
        result, updates, writes = self.scan(packs=[{"pack_id": "test", "name": "Test", "rules": []}])
        self.assertEqual(result["status"], "error")
        self.assertNotIn("scan_id", result)
        self.assertFalse(updates or writes)


@unittest.skipUnless(os.environ.get("COMPLIANCE_TEST_DSN"), "isolated PostgreSQL DSN required")
class PostgresPersistenceTests(unittest.TestCase):
    def setUp(self):
        dsn = os.environ["COMPLIANCE_TEST_DSN"]
        conn = psycopg2.connect(dsn)
        self.addCleanup(conn.close)
        self.conn = conn
        self.assertTrue(conn.info.dbname.startswith("hub_compliance_test"), "refusing non-test database")
        with conn.cursor() as cur:
            cur.execute(
                """
                DROP SCHEMA public CASCADE; CREATE SCHEMA public;
                CREATE TABLE compliance_rule_packs(pack_id TEXT, name TEXT, rules JSONB);
                INSERT INTO compliance_rule_packs VALUES ('test', 'Test', '[{"rule_id":"test"}]');
                CREATE TABLE compliance_scans(scan_id TEXT PRIMARY KEY, triggered_by TEXT,
                    started_at TIMESTAMPTZ, pack_ids TEXT[], completed_at TIMESTAMPTZ,
                    total_rules INT, passed INT, failed INT, errors INT, score REAL);
                CREATE TABLE compliance_scan_results(scan_id TEXT, pack_id TEXT, rule_id TEXT,
                    severity TEXT, status TEXT, actual_value TEXT, expected_value TEXT,
                    details TEXT, soc2_controls TEXT[]);
            """
            )
        conn.commit()

        @contextmanager
        def cursor(commit=False):
            c = psycopg2.connect(dsn)
            try:
                with c.cursor(cursor_factory=RealDictCursor) as cur:
                    yield c, cur
                if commit:
                    c.commit()
            finally:
                c.close()

        for name, value in [
            ("get_db_cursor", cursor),
            ("_clear_file_cache", lambda: None),
            ("_get_host_client", lambda: {"available": lambda: False}),
            ("_execute_check", lambda _: {"status": "pass"}),
        ]:
            p = patch.object(service, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_success_has_persisted_scan_and_result(self):
        result = service.run_scan()
        self.assertEqual(result["status"], "completed")
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM compliance_scans WHERE completed_at IS NOT NULL")
            self.assertEqual(cur.fetchone()[0], 1)
            cur.execute("SELECT count(*) FROM compliance_scan_results")
            self.assertEqual(cur.fetchone()[0], 1)

    def test_real_insert_failure_has_no_completed_snapshot(self):
        with self.conn.cursor() as cur:
            cur.execute("ALTER TABLE compliance_scan_results ADD CONSTRAINT reject_result CHECK (false)")
        self.conn.commit()
        result = service.run_scan()
        self.assertEqual(result["status"], "persistence_error")
        with self.conn.cursor() as cur:
            cur.execute("SELECT completed_at, total_rules FROM compliance_scans")
            self.assertEqual(cur.fetchone(), (None, 1))
            cur.execute("SELECT count(*) FROM compliance_scan_results")
            self.assertEqual(cur.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
