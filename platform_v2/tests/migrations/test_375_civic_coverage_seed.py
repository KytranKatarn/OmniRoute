import os
import psycopg2
import pytest
from pathlib import Path


def _get_db_password():
    """Read DB password from /run/secrets/db_password (Docker secret pattern)."""
    secret = Path("/run/secrets/db_password")
    if secret.exists():
        return secret.read_text().strip()
    return os.getenv("DB_PASSWORD", "")


@pytest.fixture
def conn():
    c = psycopg2.connect(
        host=os.getenv("DB_HOST", "192.168.1.200"),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )
    yield c
    c.close()


MIGRATION_375 = Path("/mnt/archie_brain/database/migrations/375_civic_coverage_seed.sql")


def _insert_test_unit(cur, abbr: str):
    """Insert a top-level org_unit with the given abbreviation_en for testing."""
    dn = f"OU={abbr}-TEST,O=GC,C=CA"
    dn_b64 = "dGVzdA=="  # not validated — placeholder
    cur.execute(
        """
        INSERT INTO civic_transparency.org_units
          (parent_id, dn, dn_b64, level, name_en, abbreviation_en, coverage)
        VALUES (NULL, %s, %s, 0, %s, %s, 'unknown')
        ON CONFLICT (dn) DO NOTHING
        """,
        (dn, dn_b64, f"Test {abbr}", abbr),
    )


def _select_coverage(cur, abbr: str):
    cur.execute(
        "SELECT coverage FROM civic_transparency.org_units " "WHERE abbreviation_en = %s AND parent_id IS NULL",
        (abbr,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def test_migration_seeds_full_coverage_for_known_depts(conn):
    sql = MIGRATION_375.read_text()
    with conn.cursor() as cur:
        # Setup: insert TBS as 'unknown'
        _insert_test_unit(cur, "TBS")
        assert _select_coverage(cur, "TBS") == "unknown"

        # Apply migration
        cur.execute(sql)

        assert _select_coverage(cur, "TBS") == "full", "TBS not seeded to 'full'"
    conn.rollback()  # leave DB clean


def test_migration_seeds_partial_for_security_orgs(conn):
    sql = MIGRATION_375.read_text()
    with conn.cursor() as cur:
        _insert_test_unit(cur, "CSIS")
        _insert_test_unit(cur, "RCMP")

        cur.execute(sql)

        assert _select_coverage(cur, "CSIS") == "partial"
        assert _select_coverage(cur, "RCMP") == "partial"
    conn.rollback()


def test_migration_does_not_touch_unrelated_orgs(conn):
    sql = MIGRATION_375.read_text()
    with conn.cursor() as cur:
        _insert_test_unit(cur, "ZZZUNRELATED")

        cur.execute(sql)

        assert _select_coverage(cur, "ZZZUNRELATED") == "unknown"
    conn.rollback()
