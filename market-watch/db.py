"""SQLite database connection and initialization for Market Watch."""

import logging
import os
import sqlite3

DB_PATH = os.environ.get("MW_DB_PATH", "/app/data/market.db")
logger = logging.getLogger(__name__)


def get_db():
    """Get a database connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _run_migrations(conn):
    """Run any pending SQL migrations from the migrations/ directory."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """
    )
    conn.commit()

    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    if not os.path.isdir(migrations_dir):
        return

    applied = {
        row[0]
        for row in conn.execute("SELECT filename FROM _migrations").fetchall()
    }

    for filename in sorted(os.listdir(migrations_dir)):
        if not filename.endswith(".sql"):
            continue
        if filename in applied:
            continue

        migration_path = os.path.join(migrations_dir, filename)
        with open(migration_path) as f:
            sql = f.read()

        try:
            conn.executescript(sql)
            logger.info("Applied migration: %s", filename)
        except Exception as e:
            logger.warning("Migration %s error (may be OK if columns exist): %s", filename, e)
        finally:
            # Always record migration as applied — schema.sql may have created
            # columns/tables already on a fresh install, making ALTERs redundant.
            conn.execute(
                "INSERT OR IGNORE INTO _migrations (filename) VALUES (?)", (filename,)
            )
            conn.commit()


def init_db():
    """Initialize database with schema."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        conn.executescript(f.read())
    _run_migrations(conn)
    conn.close()
