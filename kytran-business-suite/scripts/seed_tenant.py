#!/usr/bin/env python3
"""Seed tenant #1: Kytran Empowerment at Enterprise tier.

Usage:
    KBS_DB_HOST=192.168.1.200 KBS_DB_NAME=archie KBS_DB_USER=archie \
    KBS_DB_PASSWORD=xxx python3 -m scripts.seed_tenant
"""
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash
from core.database import get_db_cursor, create_tenant_schema, set_tenant_search_path


def seed():
    print("Seeding tenant #1: Kytran Empowerment...")

    with get_db_cursor(dict_cursor=True) as (conn, cur):
        # Create admin user (sharing ARCHIE's users table which uses 'username')
        cur.execute(
            """
            INSERT INTO users (email, username, password_hash)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET username = EXCLUDED.username
            RETURNING id
            """,
            (
                "admin@kytranempowerment.com",
                "Kytran Admin",
                generate_password_hash(
                    os.getenv("KBS_ADMIN_PASSWORD", "KytranBiz2026!")
                ),
            ),
        )
        user_id = cur.fetchone()["id"]
        print(f"  User: admin@kytranempowerment.com (id={user_id})")

        # Create tenant
        cur.execute(
            """
            INSERT INTO tenants (name, slug, tier)
            VALUES ('Kytran Empowerment', 'kytran-empowerment', 'enterprise')
            ON CONFLICT (slug) DO UPDATE SET tier = 'enterprise'
            RETURNING id
            """
        )
        tenant_id = cur.fetchone()["id"]
        print(f"  Tenant: Kytran Empowerment (id={tenant_id})")

        # Link user as owner
        cur.execute(
            """
            INSERT INTO tenant_users (tenant_id, user_id, role)
            VALUES (%s, %s, 'owner')
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = 'owner'
            """,
            (tenant_id, user_id),
        )

    # Create tenant schema
    create_tenant_schema(tenant_id)
    print(f"  Schema: tenant_{tenant_id}")

    # Enable all Enterprise modules that exist in module_catalog
    with get_db_cursor(dict_cursor=True) as (conn, cur):
        cur.execute("SELECT slug FROM module_catalog WHERE is_active = true")
        rows = cur.fetchall()
        for row in rows:
            cur.execute(
                """
                INSERT INTO tenant_modules (tenant_id, module_slug, enabled, source)
                VALUES (%s, %s, true, 'tier_included')
                ON CONFLICT (tenant_id, module_slug) DO UPDATE SET enabled = true
                """,
                (tenant_id, row["slug"]),
            )
    print(f"  Modules: {len(rows)} modules enabled")

    # Run plugin migrations for this tenant
    plugins_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins"
    )
    with get_db_cursor() as (conn, cur):
        set_tenant_search_path(cur, tenant_id)
        for plugin_dir in sorted(os.listdir(plugins_dir)):
            migration_dir = os.path.join(plugins_dir, plugin_dir, "migrations")
            if not os.path.isdir(migration_dir):
                continue
            for sql_file in sorted(glob.glob(os.path.join(migration_dir, "*.sql"))):
                print(f"  Migration: {plugin_dir}/{os.path.basename(sql_file)}")
                with open(sql_file) as f:
                    cur.execute(f.read())
        conn.commit()
    print("  Plugin tables created in tenant schema")

    print(f"\nDone! Tenant #1 ready.")
    print(f"  Login: admin@kytranempowerment.com")
    print(f"  URL: https://business.kytranempowerment.com")


if __name__ == "__main__":
    seed()
