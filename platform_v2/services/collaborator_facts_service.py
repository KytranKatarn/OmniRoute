"""Curated per-collaborator facts — grounding source for persona email drafts (#4959).

Small, owner-curated fact sets per agent. Read into the collaborator draft prompt AND
passed to validate_draft_no_fabrication as the allowed-facts source, so a recalled figure
passes the guard while pure invention still fails closed. Pure DB; no inference.

get_db_cursor yields RealDictCursor dict rows (KB #268832) — access by column name.
"""

import logging

from database import get_db_cursor

logger = logging.getLogger(__name__)

_COLS = "id, agent_id, fact_text, category, importance, is_active, created_at, created_by"


def _row(r) -> dict:
    return {
        "id": r["id"],
        "agent_id": r["agent_id"],
        "fact_text": r["fact_text"],
        "category": r["category"],
        "importance": int(r["importance"]) if r["importance"] is not None else 5,
        "is_active": bool(r["is_active"]),
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "created_by": r["created_by"],
    }


def get_active_facts(agent_id: int) -> list:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"SELECT {_COLS} FROM collaborator_facts "
            "WHERE agent_id=%s AND is_active=TRUE ORDER BY importance DESC, id",
            (agent_id,),
        )
        return [_row(r) for r in cur.fetchall()]


def list_for_agent(agent_id: int) -> list:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"SELECT {_COLS} FROM collaborator_facts " "WHERE agent_id=%s ORDER BY is_active DESC, importance DESC, id",
            (agent_id,),
        )
        return [_row(r) for r in cur.fetchall()]


def get_fact(fact_id: int):
    with get_db_cursor() as (conn, cur):
        cur.execute(f"SELECT {_COLS} FROM collaborator_facts WHERE id=%s", (fact_id,))
        r = cur.fetchone()
        return _row(r) if r else None


def add_fact(agent_id, fact_text, category=None, importance=5, created_by=None) -> dict:
    fact_text = (fact_text or "").strip()
    if not fact_text:
        raise ValueError("fact_text is required")
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO collaborator_facts (agent_id, fact_text, category, importance, created_by) "
            f"VALUES (%s,%s,%s,%s,%s) RETURNING {_COLS}",
            (agent_id, fact_text, category, importance, created_by),
        )
        return _row(cur.fetchone())


def update_fact(fact_id, fact_text=None, category=None, importance=None):
    sets, vals = [], []
    if fact_text is not None:
        sets.append("fact_text=%s")
        vals.append(fact_text.strip())
    if category is not None:
        sets.append("category=%s")
        vals.append(category)
    if importance is not None:
        sets.append("importance=%s")
        vals.append(importance)
    if not sets:
        return get_fact(fact_id)
    sets.append("updated_at=now()")
    vals.append(fact_id)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE collaborator_facts SET {', '.join(sets)} WHERE id=%s RETURNING {_COLS}",
            vals,
        )
        r = cur.fetchone()
        return _row(r) if r else None


def set_active(fact_id, is_active):
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE collaborator_facts SET is_active=%s, updated_at=now() WHERE id=%s RETURNING {_COLS}",
            (bool(is_active), fact_id),
        )
        r = cur.fetchone()
        return _row(r) if r else None


def delete_fact(fact_id) -> bool:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM collaborator_facts WHERE id=%s", (fact_id,))
        return cur.rowcount > 0


def facts_as_prompt_block(facts: list) -> str:
    """Prompt block listing the citable facts. Empty string when there are none."""
    if not facts:
        return ""
    lines = "\n".join(f"- {f['fact_text']}" for f in facts)
    return (
        "ALLOWED FACTS — you MAY reference these; do not invent anything beyond them " "or the message below:\n" + lines
    )


def facts_allowed_text(facts: list) -> str:
    """Newline-joined fact text — the allowed-facts source for the validator."""
    return "\n".join(f.get("fact_text", "") for f in (facts or []))
