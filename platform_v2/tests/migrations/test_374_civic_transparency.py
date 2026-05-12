import os

import psycopg2
import pytest


def _get_db_password():
    """Read DB password from Docker secret file or env var."""
    secret_path = "/run/secrets/db_password"
    if os.path.exists(secret_path):
        with open(secret_path) as f:
            return f.read().strip()
    return os.getenv("DB_PASSWORD", "")


@pytest.fixture
def conn():
    c = psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )
    yield c
    c.close()


EXPECTED_TABLES = {
    "org_units",
    "federal_employees",
    "geds_snapshots",
    "geds_movements",
    "geds_raw_pages",
}


def test_schema_exists(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM information_schema.schemata WHERE schema_name='civic_transparency'")
        assert cur.fetchone() is not None


def test_all_tables_present(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='civic_transparency'
        """
        )
        actual = {r[0] for r in cur.fetchall()}
    assert EXPECTED_TABLES.issubset(actual), f"Missing: {EXPECTED_TABLES - actual}"


def test_coverage_check_constraint(conn):
    with conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                """
                INSERT INTO civic_transparency.org_units
                  (dn, dn_b64, level, name_en, coverage)
                VALUES ('OU=TEST,O=GC,C=CA', 'dGVzdA==', 0, 'Test', 'invalid_value')
            """
            )
        conn.rollback()
