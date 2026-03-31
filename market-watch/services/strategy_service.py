"""Strategy Service — CRUD for named trading strategies."""

import json
import logging
from datetime import datetime

from db import get_db

logger = logging.getLogger(__name__)


def _row_to_dict(row):
    """Convert sqlite3.Row to dict, parsing rules JSON back to dict."""
    d = dict(row)
    if d.get("rules") and isinstance(d["rules"], str):
        try:
            d["rules"] = json.loads(d["rules"])
        except (json.JSONDecodeError, ValueError):
            pass
    return d


def get_strategies(active_only=False):
    """Return all strategies, optionally filtered to active only."""
    conn = get_db()
    try:
        cur = conn.cursor()
        if active_only:
            cur.execute(
                "SELECT * FROM strategies WHERE is_active = 1 ORDER BY created_at DESC"
            )
        else:
            cur.execute("SELECT * FROM strategies ORDER BY created_at DESC")
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_strategy(strategy_id):
    """Return a single strategy by ID, or None if not found."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def create_strategy(name, rules, description=""):
    """Insert a new strategy and return the created dict."""
    if isinstance(rules, dict):
        rules = json.dumps(rules)
    now = datetime.utcnow().isoformat()
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO strategies (name, description, rules, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (name, description, rules, now, now),
        )
        conn.commit()
        strategy_id = cur.lastrowid
        return get_strategy(strategy_id)
    finally:
        conn.close()


def update_strategy(strategy_id, **kwargs):
    """Update whitelisted fields on a strategy. Returns updated dict or None."""
    allowed = {"name", "description", "rules", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_strategy(strategy_id)

    if "rules" in fields and isinstance(fields["rules"], dict):
        fields["rules"] = json.dumps(fields["rules"])

    fields["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [strategy_id]

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE strategies SET {set_clause} WHERE id = ?", values
        )
        conn.commit()
        return get_strategy(strategy_id)
    finally:
        conn.close()


def delete_strategy(strategy_id):
    """Delete a strategy by ID."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
        conn.commit()
    finally:
        conn.close()
