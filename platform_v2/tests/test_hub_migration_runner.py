"""Run ``python -m unittest tests.test_hub_migration_runner -v`` from platform_v2.

No application or production DB fixtures are loaded. Package-qualified loading
avoids tests/services shadowing the actual services package.

Integration tests require HUB_MIGRATION_TEST_DSN naming an isolated database
whose name starts with hub_migration_test. Never point this at archie/archie_test.
"""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import psycopg2

from services.hub_migration_runner import LOCK_KEY, MigrationError, load_allowlist, run_migrations


class AllowlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def allow(self, *files):
        entries = []
        for name, sql in files:
            raw = sql.encode()
            (self.root / name).write_bytes(raw)
            entries.append({"filename": name, "sha256": hashlib.sha256(raw).hexdigest()})
        (self.root / "hub_allowlist.json").write_text(json.dumps({"migrations": entries}))

    def test_repository_allowlist_matches_approved_bytes(self):
        self.assertEqual(
            [m["filename"] for m in load_allowlist()],
            ["022_skill_review_columns.sql", "023_approvals_queue.sql", "024_lane_handover.sql"],
        )

    def test_unlisted_file_is_never_loaded(self):
        self.allow(("001_ok.sql", "SELECT 1;"))
        (self.root / "002_unapproved.sql").write_text("DROP TABLE users;")
        self.assertEqual(len(load_allowlist(self.root)), 1)

    def test_modified_file_fails_before_database_access(self):
        self.allow(("001_ok.sql", "SELECT 1;"))
        (self.root / "001_ok.sql").write_text("SELECT 2;")
        with self.assertRaisesRegex(MigrationError, "checksum mismatch"):
            run_migrations(None, "unused", root=self.root, apply=True)

    def test_duplicate_file_is_rejected(self):
        self.allow(("001_ok.sql", "SELECT 1;"), ("001_ok.sql", "SELECT 1;"))
        with self.assertRaisesRegex(MigrationError, "duplicate"):
            load_allowlist(self.root)

    def test_path_traversal_is_rejected(self):
        (self.root / "hub_allowlist.json").write_text(
            json.dumps({"migrations": [{"filename": "../001_bad.sql", "sha256": "a" * 64}]})
        )
        with self.assertRaisesRegex(MigrationError, "filename"):
            load_allowlist(self.root)

    def test_symlink_is_rejected(self):
        self.allow(("001_ok.sql", "SELECT 1;"))
        (self.root / "001_ok.sql").rename(self.root / "outside.sql")
        (self.root / "001_ok.sql").symlink_to(self.root / "outside.sql")
        with self.assertRaisesRegex(MigrationError, "local regular file"):
            load_allowlist(self.root)

    def test_explicit_transaction_control_is_rejected(self):
        self.allow(("001_bad.sql", "CREATE TABLE example(id int); COMMIT;"))
        with self.assertRaisesRegex(MigrationError, "control"):
            load_allowlist(self.root)


@unittest.skipUnless(os.environ.get("HUB_MIGRATION_TEST_DSN"), "isolated PostgreSQL DSN required")
class PostgresTests(AllowlistTests):
    def setUp(self):
        super().setUp()
        self.conn = psycopg2.connect(os.environ["HUB_MIGRATION_TEST_DSN"])
        self.addCleanup(self.conn.close)
        self.db = self.conn.info.dbname
        if not self.db.startswith("hub_migration_test"):
            self.fail("refusing integration tests outside hub_migration_test* database")
        with self.conn.cursor() as cur:
            cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        self.conn.commit()

    def query(self, sql):
        with self.conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        self.conn.rollback()
        return rows

    def test_plan_is_read_only_and_does_not_create_ledger(self):
        self.allow(("001_ok.sql", "CREATE TABLE example(id int);"))
        result = run_migrations(self.conn, self.db, root=self.root)
        self.assertEqual(result["migrations"][0]["status"], "pending")
        self.assertEqual(
            self.query("SELECT to_regclass('public.hub_migration_runs'), to_regclass('example')"), [(None, None)]
        )

    def test_apply_then_skip_without_replaying_data_change(self):
        self.allow(("001_ok.sql", "CREATE TABLE example(id int); INSERT INTO example VALUES (1);"))
        run_migrations(self.conn, self.db, root=self.root, apply=True)
        result = run_migrations(self.conn, self.db, root=self.root, apply=True)
        self.assertEqual(result["migrations"][0]["status"], "applied")
        self.assertEqual(self.query("SELECT count(*) FROM example"), [(1,)])

    def test_bad_second_migration_rolls_back_first_and_ledger(self):
        self.allow(("001_ok.sql", "CREATE TABLE example(id int);"), ("002_bad.sql", "SELECT 1 / 0;"))
        with self.assertRaisesRegex(MigrationError, "002_bad.sql"):
            run_migrations(self.conn, self.db, root=self.root, apply=True)
        self.assertEqual(
            self.query("SELECT to_regclass('example'), to_regclass('public.hub_migration_runs')"), [(None, None)]
        )
        # The failed batch released its transaction-scoped advisory lock.
        with self.conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK_KEY,))
            self.assertTrue(cur.fetchone()[0])
        self.conn.rollback()

    def test_failed_new_batch_preserves_previous_committed_batch(self):
        self.allow(("001_ok.sql", "CREATE TABLE example(id int);"))
        run_migrations(self.conn, self.db, root=self.root, apply=True)
        self.allow(("001_ok.sql", "CREATE TABLE example(id int);"), ("002_bad.sql", "SELECT 1 / 0;"))
        with self.assertRaises(MigrationError):
            run_migrations(self.conn, self.db, root=self.root, apply=True)
        self.assertEqual(self.query("SELECT filename FROM public.hub_migration_runs"), [("001_ok.sql",)])

    def test_lock_contention_refuses_without_writes(self):
        self.allow(("001_ok.sql", "CREATE TABLE example(id int);"))
        with psycopg2.connect(os.environ["HUB_MIGRATION_TEST_DSN"]) as other:
            with other.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
                with self.assertRaisesRegex(MigrationError, "owns the lock"):
                    run_migrations(self.conn, self.db, root=self.root, apply=True)
        self.assertEqual(self.query("SELECT to_regclass('public.hub_migration_runs')"), [(None,)])

    def test_repinning_previously_applied_file_is_rejected(self):
        self.allow(("001_ok.sql", "SELECT 1;"))
        run_migrations(self.conn, self.db, root=self.root, apply=True)
        self.allow(("001_ok.sql", "SELECT 2;"))
        with self.assertRaisesRegex(MigrationError, "applied migration.*changed"):
            run_migrations(self.conn, self.db, root=self.root, apply=True)

    def test_wrong_database_target_refuses_without_writes(self):
        self.allow(("001_ok.sql", "SELECT 1;"))
        with self.assertRaisesRegex(MigrationError, "explicit target"):
            run_migrations(self.conn, "archie", root=self.root, apply=True)
        self.assertEqual(self.query("SELECT to_regclass('public.hub_migration_runs')"), [(None,)])

    def test_real_allowlist_on_minimal_base_and_repeated_run(self):
        with self.conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE github_skills(id INTEGER PRIMARY KEY, status TEXT); "
                "INSERT INTO github_skills VALUES(1, 'analyzed'); "
                "CREATE TABLE schema_migrations(version TEXT PRIMARY KEY);"
            )
        self.conn.commit()
        run_migrations(self.conn, self.db, apply=True)
        self.assertEqual(self.query("SELECT count(*) FROM lane_handover"), [(3,)])
        self.assertEqual(self.query("SELECT count(*) FROM approvals_queue"), [(1,)])
        self.assertEqual(self.query("SELECT count(*) FROM public.hub_migration_runs"), [(3,)])
        result = run_migrations(self.conn, self.db, apply=True)
        self.assertTrue(all(m["status"] == "applied" for m in result["migrations"]))


if __name__ == "__main__":
    unittest.main()
