"""WTF Consumer — local SQLite DB for billing subscriptions."""
import os
import sqlite3

_DB_PATH = os.environ.get("WTF_BILLING_DB_PATH", "/app/data/wtf_billing.db")


def get_db():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_billing_table():
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS billing_subscriptions (
            email      TEXT PRIMARY KEY,
            tier       TEXT NOT NULL DEFAULT 'free',
            stripe_customer_id      TEXT,
            stripe_subscription_id  TEXT,
            status     TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def get_billing_tier(email: str) -> str:
    if not email:
        return "free"
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT tier FROM billing_subscriptions WHERE LOWER(email) = LOWER(?) AND status = 'active'",
            (email,),
        ).fetchone()
        conn.close()
        return row["tier"] if row else "free"
    except Exception:
        return "free"
