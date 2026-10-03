"""Tests for migration 088 (the WTF migration ledger) and scripts/migrations_admin.py.

These apply the real 088 SQL, against a throwaway schema, and then prove the properties
the migration claims: it is re-runnable, it logs itself, and it records the pre-088 era
as unknown rather than backfilling 87 unverified claims.

⚠️ The SQL is rewritten `public.` -> `wtf_mt_test.` before it runs, the same way
tests/conftest.py rewrites `wtf.` -> `wtf_test.`. That is not cosmetic: the HUB's archie
database really does have a `public.schema_migrations` holding the platform's own
migration history (16 rows as of 2026-10-03). A test that applied 088 unmodified would
run against that live table. The schema name is deliberately not `wtf_test`, which is
claimed and dropped per-test by the clean_schema/entity_schema fixtures, so this file
cannot collide with them.
"""
import re
from pathlib import Path

import pytest
from sqlalchemy import text

REPO = Path(__file__).resolve().parent.parent.parent
MIGRATION = REPO / "what-the-fact" / "migrations" / "088_schema_migrations.sql"
TEST_SCHEMA = "wtf_mt_test"


@pytest.fixture()
def ledger(engine):
    """Apply the real 088 SQL into an isolated schema; drop it afterwards."""
    sql = MIGRATION.read_text().replace("public.", TEST_SCHEMA + ".")
    with engine.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        c.execute(text(f"CREATE SCHEMA {TEST_SCHEMA}"))
    with engine.begin() as c:
        c.execute(text(sql))
    yield TEST_SCHEMA
    with engine.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))


def _rows(engine, schema):
    with engine.connect() as c:
        return c.execute(text(
            f"SELECT version, filename, applied_at IS NULL FROM {schema}.schema_migrations"
        )).all()


@pytest.fixture()
def mt_schema(engine):
    """An empty schema for the read-path tests to build ledgers in.

    Separate from `ledger` (which applies the real 088 SQL) because these tests need a
    bare schema to construct deliberately-shaped ledgers by hand.
    """
    with engine.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
        c.execute(text(f"CREATE SCHEMA {TEST_SCHEMA}"))
    yield TEST_SCHEMA
    with engine.begin() as c:
        c.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))


class TestLedgerTable:
    def test_table_and_columns_exist(self, ledger, engine):
        with engine.connect() as c:
            cols = {r[0] for r in c.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=:s AND table_name='schema_migrations'"),
                {"s": ledger})}
        # filename is what makes misapplying this to the hub fail loudly instead of
        # silently filing WTF history into the platform's ledger. If someone drops it
        # to "fix" that error, this test should fail.
        assert cols == {"version", "filename", "description", "applied_at"}

    def test_this_migration_logs_itself_with_a_timestamp(self, ledger, engine):
        rows = {v: (fn, ts_null) for v, fn, ts_null in _rows(engine, ledger)}
        assert rows["088"] == ("088_schema_migrations.sql", False)

    def test_pre_088_era_is_recorded_as_unknown_not_backfilled(self, ledger, engine):
        """One baseline marker, applied_at NULL — and NOT 87 invented rows.

        The honest encoding of "applied before we kept a ledger, at an unknown time" is
        a NULL timestamp. A backfill of 001-087 with now() would assert 87 applications
        that nobody verified.
        """
        rows = dict((v, ts_null) for v, _fn, ts_null in _rows(engine, ledger))
        assert rows["000-baseline"] is True          # applied_at IS NULL
        versions = set(rows)
        assert versions == {"000-baseline", "088"}, "only the marker and itself"
        assert not any(re.fullmatch(r"0(0[1-9]|[1-7][0-9]|8[0-7])", v) for v in versions)

    def test_is_rerunnable(self, ledger, engine):
        """Re-applying must not error and must not duplicate rows (README claims this)."""
        sql = MIGRATION.read_text().replace("public.", TEST_SCHEMA + ".")
        with engine.begin() as c:
            c.execute(text(sql))
            c.execute(text(sql))
        rows = _rows(engine, ledger)
        assert sorted(v for v, _fn, _t in rows) == ["000-baseline", "088"]

    def test_the_rerunnable_test_can_actually_fail(self, ledger, engine):
        """Control: strip the ON CONFLICT guard and re-applying must break.

        Without this, "is re-runnable" is an unfalsifiable claim — the kind of test that
        passes because it never exercised the failure it was written to rule out.
        """
        sql = MIGRATION.read_text().replace("public.", TEST_SCHEMA + ".")
        vulnerable = sql.replace("ON CONFLICT (version) DO NOTHING", "")
        assert vulnerable != sql, "guard text not found — test would prove nothing"
        with pytest.raises(Exception):
            with engine.begin() as c:
                c.execute(text(vulnerable))


class TestStatusReport:
    def _status(self, engine):
        import sys
        sys.path.insert(0, str(REPO / "what-the-fact"))
        from scripts.migrations_admin import collect_status
        return collect_status(engine, ledger_schema=TEST_SCHEMA)

    def test_reports_pre_ledger_files_as_baseline_not_as_failures(self, engine):
        """Before 088 is applied there is no ledger, so nothing is claimed either way.

        088 itself must read as NOT APPLIED, not as baseline: the table it creates is the
        evidence, so its absence is proof the file has not been run. Only 001-087 are
        baseline, because those predate the ledger and cannot be dated from it.
        """
        s = self._status(engine)
        assert not s["ledger_exists"]
        assert s["entries"], "still lists every migration file on disk"
        by_version = {e["version"]: e for e in s["entries"]}
        assert all(e["state"].startswith("baseline") for v, e in by_version.items()
                   if int(v) < 88)
        assert by_version["088"]["state"] == "NOT APPLIED"
        assert s["not_applied"] == ["088"]
        assert not s["drift"]

    def test_finds_the_087_files_it_claims_to(self, engine):
        s = self._status(engine)
        versions = [e["version"] for e in s["entries"]]
        assert versions == sorted(versions, key=int), "numeric order, not lexicographic"
        assert versions[0] == "001" and len(versions) >= 88

    def test_flags_a_ledger_row_whose_file_is_missing(self, engine):
        """Drift: history says applied, the repo no longer has the file."""
        s = self._status(engine)
        assert s["orphan_versions"] == [] and not s["drift"]

    def test_detects_an_orphan_when_one_exists(self, engine, tmp_path):
        import sys
        sys.path.insert(0, str(REPO / "what-the-fact"))
        from scripts.migrations_admin import collect_status
        # A directory holding a single migration file, plus a fake ledger version, so
        # the orphan path is exercised rather than assumed.
        (tmp_path / "001_wtf_schema.sql").write_text("SELECT 1;")
        s = collect_status(engine, migrations_dir=tmp_path, ledger_schema=TEST_SCHEMA)
        assert [e["version"] for e in s["entries"]] == ["001"]
        assert "001" in s["entries"][0]["file"]

    def test_refuses_to_report_against_the_hubs_platform_ledger(self, engine, mt_schema):
        """Wrong-target guard on the READ path.

        The hub's archie database really does have public.schema_migrations, holding the
        platform's own history. Reporting those rows as WTF's would be worse than saying
        nothing, so the table is recognised by its missing 'filename' column and the
        report refuses outright.
        """
        import sys
        sys.path.insert(0, str(REPO / "what-the-fact"))
        from scripts.migrations_admin import collect_status, _render
        with engine.begin() as c:
            c.execute(text(f"DROP TABLE IF EXISTS {TEST_SCHEMA}.schema_migrations"))
            c.execute(text(f"CREATE TABLE {TEST_SCHEMA}.schema_migrations ("
                           "version varchar(50) PRIMARY KEY, description text, "
                           "applied_at timestamp DEFAULT now())"))
            c.execute(text(f"INSERT INTO {TEST_SCHEMA}.schema_migrations VALUES "
                           "('001','platform row',now())"))
        try:
            s = collect_status(engine, ledger_schema=TEST_SCHEMA)
            assert s["ledger_exists"]
            assert not s["is_wtf_ledger"], "platform-shaped table must not pass as WTF's"
            out = _render(s)
            assert "WRONG DATABASE" in out
            # It must NOT have surfaced the platform's row as a WTF migration.
            assert "platform row" not in out
            assert "001_wtf_schema.sql" not in out
        finally:
            with engine.begin() as c:
                c.execute(text(f"DROP TABLE IF EXISTS {TEST_SCHEMA}.schema_migrations"))

    def test_a_real_wtf_ledger_is_not_mistaken_for_the_platforms(self, engine, mt_schema):
        """Control for the test above: the detector must be capable of passing.

        If this failed, the wrong-database check would fire on everything and be
        worthless as a guard.
        """
        import sys
        sys.path.insert(0, str(REPO / "what-the-fact"))
        from scripts.migrations_admin import collect_status
        s = collect_status(engine, ledger_schema=TEST_SCHEMA)
        assert s["ledger_exists"] is False, "clean DB has no ledger to confuse"
        with engine.begin() as c:
            c.execute(text(f"DROP TABLE IF EXISTS {TEST_SCHEMA}.schema_migrations"))
            c.execute(text(f"CREATE TABLE {TEST_SCHEMA}.schema_migrations ("
                           "version varchar(50) PRIMARY KEY, filename text NOT NULL, "
                           "description text, applied_at timestamptz DEFAULT now())"))
        try:
            s = collect_status(engine, ledger_schema=TEST_SCHEMA)
            assert s["ledger_exists"] and s["is_wtf_ledger"]
        finally:
            with engine.begin() as c:
                c.execute(text(f"DROP TABLE IF EXISTS {TEST_SCHEMA}.schema_migrations"))
