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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS beat_subscriptions (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            email                  TEXT    NOT NULL,
            beat_slug              TEXT    NOT NULL,
            stripe_subscription_id TEXT    NOT NULL,
            stripe_price_id        TEXT    NOT NULL,
            status                 TEXT    NOT NULL DEFAULT 'active',
            created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (email, beat_slug)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_beat_subs_email ON beat_subscriptions (email)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_beat_subs_slug  ON beat_subscriptions (beat_slug, status)")
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


def get_user_beats(email: str) -> list:
    """Return list of active beat slugs for this email."""
    if not email:
        return []
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT beat_slug FROM beat_subscriptions WHERE LOWER(email)=LOWER(?) AND status='active'",
            (email,)
        ).fetchall()
        return [r["beat_slug"] for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def upsert_beat_subscription(email, beat_slug, stripe_sub_id, stripe_price_id, status="active"):
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO beat_subscriptions (email, beat_slug, stripe_subscription_id, stripe_price_id, status, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(email, beat_slug) DO UPDATE SET
                stripe_subscription_id = excluded.stripe_subscription_id,
                stripe_price_id        = excluded.stripe_price_id,
                status                 = excluded.status,
                updated_at             = CURRENT_TIMESTAMP
        """, (email, beat_slug, stripe_sub_id, stripe_price_id, status))
        conn.commit()
    finally:
        conn.close()


def cancel_beat_by_stripe_sub(stripe_sub_id: str):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE beat_subscriptions SET status='cancelled', updated_at=CURRENT_TIMESTAMP"
            " WHERE stripe_subscription_id = ?",
            (stripe_sub_id,)
        )
        conn.commit()
    finally:
        conn.close()
