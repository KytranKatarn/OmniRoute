#!/usr/bin/env python3
"""Create or reset the admin user for a business node."""
import os
import sys
import getpass
import bcrypt
import psycopg2


def main():
    print("=== A.R.C.H.I.E. Node Admin Setup ===")

    username = input("Admin username [admin]: ").strip() or "admin"
    email = input("Admin email [admin@node.local]: ").strip() or "admin@node.local"
    password = getpass.getpass("Admin password: ")
    if not password:
        print("Password cannot be empty")
        sys.exit(1)

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "node_database"),
        port=os.environ.get("DB_PORT", "5432"),
        database=os.environ.get("DB_NAME", "archie_node"),
        user=os.environ.get("DB_USER", "archie"),
        password=os.environ.get("DB_PASSWORD", ""),
    )
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (username, email, password_hash, role, is_active, is_admin)
        VALUES (%s, %s, %s, 'admin', true, true)
        ON CONFLICT (username) DO UPDATE SET
            password_hash = EXCLUDED.password_hash,
            email = EXCLUDED.email,
            is_admin = true
    """,
        (username, email, password_hash),
    )
    conn.commit()
    cur.close()
    conn.close()
    print(f"Admin user '{username}' created/updated successfully.")


if __name__ == "__main__":
    main()
