#!/usr/bin/env python3
"""Re-attach the `id` column DEFAULTs that `archie_test` lost, deriving every one from prod.

WHY THIS EXISTS
---------------
Measured 2026-09-21:

    archie       tables with an `id` DEFAULT nextval(...)   674
    archie_test  tables with an `id` DEFAULT nextval(...)     0
    archie_test  `id` columns with NO default                706
    archie_test  sequences present                          677

The SEQUENCES are there. Only the column DEFAULTs are missing — the signature of a schema
copy that created the sequence objects but never re-ran `ALTER COLUMN ... SET DEFAULT`.

The consequence is not cosmetic: **every test that INSERTs a row without naming `id`
fails in archie_test**, and pytest forces archie_test. Found via
`tests/test_fleet_stats_node_count.py`, whose 3 tests error at SETUP with

    psycopg2.errors.NotNullViolation: null value in column "id" of relation "remote_nodes"

They error rather than fail, which reads as environment noise, so they have looked like
coverage while never once executing. That is worse than being absent — the filename
implies the behaviour is pinned. Task #6821.

DESIGN
------
* **Prod is the source of truth.** Every DEFAULT written here is copied verbatim from
  `archie`. The script cannot invent a default that prod does not have, so it can only ever
  move archie_test TOWARD parity.
* **Bulk ops are N decisions** (house rule). 706 - 677 = 29 `id` columns have no matching
  sequence; those are not serial columns and are deliberately left alone. The join against
  prod's own default is what separates them — not a name guess.
* **The sequence must already exist in archie_test.** A default pointing at a missing
  sequence would turn a clean NotNullViolation into a confusing UndefinedTable at INSERT
  time. Any such row is REPORTED and skipped, never written.
* **Dry-run by DEFAULT.** `--apply` is required to write anything.
* **Refuses to run against a non-test database.** The target name must end in `_test`.
  This script has no legitimate use on prod: prod already has these defaults, and being
  wrong about which DB you are attached to is the expensive mistake here.

USAGE
-----
    docker exec -i archie_platform python3 /app/../scripts/repair_test_db_id_defaults.py
    docker exec -i archie_platform python3 .../repair_test_db_id_defaults.py --apply

(or from the host with psql reachable; see main() for the connection env vars)
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg2
import psycopg2.extras

PROD_DB = "archie"
DEFAULT_TEST_DB = "archie_test"


def _db_password() -> str:
    """Mirror platform_v2/database.py: the SECRET FILE first, env only as a fallback.

    ⚠️ `os.getenv("DB_PASSWORD")` alone returns "" inside `archie_platform` — the password
    arrives as a Docker secret, not an env var (compliance-standards.md: no secrets in env).
    A first cut of this script used getenv and died with `fe_sendauth: no password supplied`,
    which reads like a network or pg_hba problem rather than a missing credential.
    """
    path = os.environ.get("DB_PASSWORD_FILE", "/run/secrets/db_password")
    try:
        with open(path) as fh:
            secret = fh.read().strip()
        if secret:
            return secret
    except OSError:
        pass
    return os.environ.get("DB_PASSWORD", "")


def _connect(dbname: str):
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER", "archie"),
        password=_db_password(),
        dbname=dbname,
    )


def prod_id_defaults(conn) -> dict:
    """{(table, column): default_expression} for every serial-ish column prod declares."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT table_name, column_name, column_default
              FROM information_schema.columns
             WHERE table_schema = 'public'
               AND column_default LIKE 'nextval(%%'
            """
        )
        return {(r["table_name"], r["column_name"]): r["column_default"] for r in cur.fetchall()}


def test_state(conn) -> tuple:
    """(columns lacking a default, sequence names present) for the test DB."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT table_name, column_name
              FROM information_schema.columns
             WHERE table_schema = 'public' AND column_default IS NULL
            """
        )
        missing = {(r["table_name"], r["column_name"]) for r in cur.fetchall()}
        cur.execute("SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema='public'")
        seqs = {r["sequence_name"] for r in cur.fetchall()}
    return missing, seqs


def _seq_name(default_expr: str) -> str | None:
    """Pull the sequence name out of `nextval('public.foo_id_seq'::regclass)`."""
    if "'" not in default_expr:
        return None
    inner = default_expr.split("'")[1]
    name = inner.split("::")[0].strip('"')
    return name.split(".")[-1].strip('"')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--db", default=DEFAULT_TEST_DB, help="target test database")
    args = ap.parse_args()

    if not args.db.endswith("_test"):
        print(f"REFUSING: {args.db!r} is not a *_test database. This script never touches prod.")
        return 2

    prod = _connect(PROD_DB)
    test = _connect(args.db)
    try:
        wanted = prod_id_defaults(prod)
        missing, seqs = test_state(test)

        todo, no_seq = [], []
        for (tbl, col), expr in sorted(wanted.items()):
            if (tbl, col) not in missing:
                continue  # already has a default, or the column/table is absent here
            seq = _seq_name(expr)
            if not seq or seq not in seqs:
                no_seq.append((tbl, col, seq))
                continue
            todo.append((tbl, col, seq))

        print(f"prod declares {len(wanted)} serial column defaults")
        print(f"{args.db}: {len(todo)} to re-attach, {len(no_seq)} skipped (sequence absent)")
        for tbl, col, seq in no_seq:
            print(f"  SKIP {tbl}.{col}: sequence {seq!r} not present in {args.db}")

        if not args.apply:
            for tbl, col, seq in todo[:10]:
                print(f"  would set {tbl}.{col} DEFAULT nextval('{seq}')")
            if len(todo) > 10:
                print(f"  ... and {len(todo) - 10} more")
            print("\nDRY RUN — re-run with --apply to write.")
            return 0

        done = 0
        with test.cursor() as cur:
            for tbl, col, seq in todo:
                # Quoted identifiers: a table named e.g. "user" is legal and would otherwise
                # be a syntax error. Values are schema names read from the catalog, not input.
                cur.execute(f'ALTER TABLE public."{tbl}" ALTER COLUMN "{col}" SET DEFAULT nextval(\'{seq}\')')
                # Ownership so a DROP TABLE takes its sequence with it, matching prod.
                cur.execute(f'ALTER SEQUENCE "{seq}" OWNED BY public."{tbl}"."{col}"')
                done += 1
        test.commit()
        print(f"APPLIED: {done} column defaults re-attached in {args.db}")
        return 0
    finally:
        prod.close()
        test.close()


if __name__ == "__main__":
    sys.exit(main())
