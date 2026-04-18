"""pytest fixtures: isolated DB per test using the `wtf_test` schema."""
import os
import pytest
from sqlalchemy import create_engine, text

TEST_DB_URL = os.environ.get(
    "WTF_TEST_DATABASE_URL",
    "postgresql+psycopg2://archie:archie@192.168.1.200:5432/archie",
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL, future=True)
    return eng


@pytest.fixture()
def clean_schema(engine):
    """Drop + recreate wtf_test schema, apply migration, yield."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS wtf_test CASCADE"))
        conn.execute(text("CREATE SCHEMA wtf_test"))
    # Apply migration with schema substitution
    with open("what-the-fact/migrations/001_wtf_schema.sql") as f:
        sql = f.read().replace("wtf.", "wtf_test.").replace("SCHEMA wtf", "SCHEMA wtf_test")
    with engine.begin() as conn:
        for stmt in sql.split(";\n"):
            if stmt.strip():
                conn.execute(text(stmt))
    yield
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS wtf_test CASCADE"))
