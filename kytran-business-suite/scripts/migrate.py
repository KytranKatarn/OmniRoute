"""
Migration runner for Kytran Business Suite.

Usage:
    python -m scripts.migrate              # run core migrations
    python -m scripts.migrate --tenant 1  # run plugin migrations for tenant 1
    python -m scripts.migrate --all       # core + all tenants with active modules
"""

import argparse
import os
import sys

# Allow running as module from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import get_db_cursor, run_migration_file

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")
PLUGINS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins")


def run_core_migrations():
    """Run all migrations/*.sql files in sorted order against the public schema."""
    if not os.path.isdir(MIGRATIONS_DIR):
        print(f"[migrate] No migrations directory found at {MIGRATIONS_DIR}")
        return

    migration_files = sorted(
        f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql")
    )

    if not migration_files:
        print("[migrate] No migration files found.")
        return

    for filename in migration_files:
        filepath = os.path.join(MIGRATIONS_DIR, filename)
        print(f"[migrate] Running core migration: {filename}")
        run_migration_file(filepath)
        print(f"[migrate] Done: {filename}")

    print(f"[migrate] Core migrations complete ({len(migration_files)} files).")


def run_plugin_migrations(tenant_id: int):
    """
    Run each enabled plugin's migrations/*.sql in the tenant's schema.

    Looks for enabled modules in tenant_modules for the given tenant,
    then checks plugins/{slug}/migrations/*.sql.
    """
    schema = f"tenant_{tenant_id}"

    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute(
            """
            SELECT tm.module_slug
            FROM tenant_modules tm
            WHERE tm.tenant_id = %s AND tm.enabled = TRUE
            """,
            (tenant_id,),
        )
        rows = cur.fetchall()

    if not rows:
        print(f"[migrate] No enabled plugins for tenant {tenant_id}.")
        return

    for row in rows:
        slug = row["module_slug"]
        plugin_migrations_dir = os.path.join(PLUGINS_DIR, slug, "migrations")

        if not os.path.isdir(plugin_migrations_dir):
            print(f"[migrate] No migrations dir for plugin '{slug}' — skipping.")
            continue

        migration_files = sorted(
            f for f in os.listdir(plugin_migrations_dir) if f.endswith(".sql")
        )

        for filename in migration_files:
            filepath = os.path.join(plugin_migrations_dir, filename)
            print(f"[migrate] Running plugin '{slug}' migration for tenant {tenant_id}: {filename}")
            run_migration_file(filepath, schema=schema)
            print(f"[migrate] Done: {filename}")

    print(f"[migrate] Plugin migrations complete for tenant {tenant_id}.")


def run_all_migrations():
    """Run core migrations, then plugin migrations for every active tenant."""
    run_core_migrations()

    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute("SELECT id FROM tenants WHERE is_active = TRUE")
        tenants = cur.fetchall()

    if not tenants:
        print("[migrate] No active tenants found — skipping plugin migrations.")
        return

    for tenant in tenants:
        run_plugin_migrations(tenant["id"])

    print(f"[migrate] All migrations complete ({len(tenants)} tenants).")


def main():
    parser = argparse.ArgumentParser(description="KBS migration runner")
    parser.add_argument(
        "--tenant",
        type=int,
        help="Run plugin migrations for a specific tenant ID",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run core migrations + plugin migrations for all active tenants",
    )
    args = parser.parse_args()

    if args.all:
        run_all_migrations()
    elif args.tenant is not None:
        run_plugin_migrations(args.tenant)
    else:
        run_core_migrations()


if __name__ == "__main__":
    main()
