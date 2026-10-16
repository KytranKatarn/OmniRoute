"""Opt-in, checksum-pinned hub migrations; never scan historical migrations.

Run ``python -m services.hub_migration_runner --database NAME`` to plan, then
add ``--apply`` to execute. This does NOT bootstrap the platform's base schema
or wire itself into production startup. See migrations/HUB_RUNNER.md.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from psycopg2 import extensions
from psycopg2.extras import RealDictCursor


ROOT = Path(__file__).resolve().parents[1] / "migrations"
LOCK_KEY = 7247276
LEDGER = "public.hub_migration_runs"
# Deliberately conservative: also refuses procedural blocks / quoted mentions.
# Approved migrations are plain transactional DDL/DML, not arbitrary SQL programs.
TRANSACTION_CONTROL = re.compile(r"\b(BEGIN|COMMIT|ROLLBACK|ABORT|SAVEPOINT|RELEASE|END|PREPARE)\b", re.I)


class MigrationError(RuntimeError):
    """A failed precondition or migration; do not start the app after this."""


def load_allowlist(root=ROOT):
    """Read only approved, hash-pinned files; preflight the entire batch first."""
    root = Path(root).resolve()
    manifest = json.loads((root / "hub_allowlist.json").read_text())
    if set(manifest) != {"migrations"} or not isinstance(manifest["migrations"], list):
        raise MigrationError("allowlist must contain a migrations array")
    migrations = []
    seen = set()
    for entry in manifest["migrations"]:
        if not isinstance(entry, dict) or set(entry) != {"filename", "sha256"}:
            raise MigrationError("each allowlist entry needs filename and sha256")
        name, expected = entry["filename"], entry["sha256"]
        if not isinstance(name, str) or not re.fullmatch(r"[0-9]+_[A-Za-z0-9_]+\.sql", name):
            raise MigrationError("invalid migration filename")
        if name in seen:
            raise MigrationError(f"duplicate migration: {name}")
        seen.add(name)
        path = root / name
        if path.is_symlink() or path.resolve().parent != root:
            raise MigrationError(f"migration must be a local regular file: {name}")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected) or digest != expected:
            raise MigrationError(f"allowlist checksum mismatch: {name}")
        sql = raw.decode("utf-8")
        if not sql.strip() or TRANSACTION_CONTROL.search(sql):
            raise MigrationError(f"empty SQL or transaction/procedural control is not allowed: {name}")
        migrations.append({"filename": name, "sha256": digest, "sql": sql})
    return migrations


def run_migrations(conn, database, *, root=ROOT, apply=False):
    """Own ONE transaction on an idle connection; roll back the WHOLE batch.

    DDL, data changes and the dedicated ledger commit together. The transaction
    advisory lock is released automatically on either commit or rollback. The
    caller must close/release the connection. No schema_migrations rows are
    inferred as applied: legacy version-only records cannot establish a hash.
    """
    migrations = load_allowlist(root)
    if conn.autocommit or conn.get_transaction_status() != extensions.TRANSACTION_STATUS_IDLE:
        raise MigrationError("runner requires an idle, non-autocommit connection")
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if not apply:
                cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SELECT current_database() AS name")
            if cur.fetchone()["name"] != database:
                raise MigrationError("connected database does not match explicit target")
            if apply:
                cur.execute("SELECT pg_try_advisory_xact_lock(%s) AS acquired", (LOCK_KEY,))
                if not cur.fetchone()["acquired"]:
                    raise MigrationError("another hub migration runner owns the lock")
                cur.execute("SET LOCAL lock_timeout = '5s'")
                cur.execute("SET LOCAL statement_timeout = '60s'")
            cur.execute("SELECT to_regclass(%s) AS ledger", (LEDGER,))
            recorded = {}
            if cur.fetchone()["ledger"]:
                cur.execute(f"SELECT filename, sha256 FROM {LEDGER}")
                recorded = {row["filename"]: row["sha256"] for row in cur.fetchall()}
            approved = {m["filename"]: m["sha256"] for m in migrations}
            for name, digest in recorded.items():
                if approved.get(name) != digest:
                    raise MigrationError(f"applied migration missing from allowlist or changed: {name}")
            plan = [
                {
                    "filename": m["filename"],
                    "sha256": m["sha256"],
                    "status": "applied" if m["filename"] in recorded else "pending",
                }
                for m in migrations
            ]
            if apply:
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {LEDGER} ("
                    "filename TEXT PRIMARY KEY, sha256 CHAR(64) NOT NULL, "
                    "applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
                )
                for migration in migrations:
                    name = migration["filename"]
                    if name in recorded:
                        continue
                    try:
                        cur.execute(migration["sql"])
                    except Exception as exc:
                        # Do not echo SQL, connection strings or credentials.
                        raise MigrationError(f"migration failed; entire batch rolled back: {name}") from exc
                    cur.execute(
                        f"INSERT INTO {LEDGER} (filename, sha256) VALUES (%s, %s)",
                        (name, migration["sha256"]),
                    )
            conn.commit()
        return {"database": database, "mode": "apply" if apply else "plan", "migrations": plan}
    except Exception:
        conn.rollback()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="explicit target DB; no production default")
    parser.add_argument("--apply", action="store_true", help="apply the allowlisted batch atomically")
    args = parser.parse_args(argv)
    # Set before database creates its pool. Credentials stay in the existing
    # runtime configuration / secret provider; never accept them on the CLI.
    os.environ["DB_NAME"] = args.database
    from database import get_db_cursor

    try:
        with get_db_cursor(commit=False) as (conn, _):
            result = run_migrations(conn, args.database, apply=args.apply)
        print(json.dumps(result))
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, MigrationError) else "migration preflight/database failure"
        print(json.dumps({"success": False, "error": message}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
