"""
Family Tree — Duplicate detection and person merge service.

Uses SequenceMatcher for text similarity on person records.
Threshold: 0.75 for flagging potential duplicates.
"""

from difflib import SequenceMatcher
from typing import Any

from database import get_db_cursor

SIMILARITY_THRESHOLD = 0.75


def _similarity(a: str, b: str) -> float:
    """
    Return the case-insensitive SequenceMatcher similarity for two strings.

    The score is a float from 0.0 to 1.0, where 1.0 means the normalized
    strings are identical.
    """
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _person_text(p: dict[str, Any]) -> str:
    """Build a canonical text representation for comparison."""
    parts = [
        (p.get("first_name") or "").strip(),
        (p.get("last_name") or "").strip(),
    ]
    if p.get("birth_date"):
        parts.append(f"born {p['birth_date']}")
    if p.get("birth_place"):
        parts.append(f"at {p['birth_place']}")
    if p.get("death_date"):
        parts.append(f"died {p['death_date']}")
    if p.get("death_place"):
        parts.append(f"at {p['death_place']}")
    return " ".join(parts)


def find_duplicates(user_id: int) -> list[dict[str, Any]]:
    """
    Fetch all persons for *user_id*, compare every pair via
    SequenceMatcher on their text representations, and return
    pairs that score >= SIMILARITY_THRESHOLD.

    Returns list of dicts:
        [{"person_a": {…}, "person_b": {…}, "score": float}, …]
    sorted by score descending.
    """
    sql = """
        SELECT id, first_name, last_name, birth_date, birth_place,
               death_date, death_place
        FROM family_persons
        WHERE user_id = %(user_id)s
        ORDER BY id
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, {"user_id": user_id})
        persons = [dict(r) for r in cur.fetchall()]

    # Pre-compute text representations
    texts = [(p, _person_text(p)) for p in persons]

    candidates = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            p_a, t_a = texts[i]
            p_b, t_b = texts[j]
            score = _similarity(t_a, t_b)
            if score >= SIMILARITY_THRESHOLD:
                candidates.append(
                    {
                        "person_a": p_a,
                        "person_b": p_b,
                        "score": round(score, 4),
                    }
                )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def _transfer_relationships_person_a(cur: Any, user_id: int, keep_id: int, merge_id: int) -> int:
    """Re-point non-duplicate relationships where the merged person is person_a."""
    cur.execute(
        """UPDATE family_relationships
           SET person_a_id = %(keep)s
           WHERE person_a_id = %(merge)s AND user_id = %(uid)s
             AND NOT EXISTS (
                 SELECT 1 FROM family_relationships r2
                 WHERE r2.person_a_id = %(keep)s
                   AND r2.person_b_id = family_relationships.person_b_id
                   AND r2.relationship_type = family_relationships.relationship_type
                   AND r2.user_id = %(uid)s
             )""",
        {"keep": keep_id, "merge": merge_id, "uid": user_id},
    )
    return cur.rowcount


def _transfer_relationships_person_b(cur: Any, user_id: int, keep_id: int, merge_id: int) -> int:
    """Re-point non-duplicate relationships where the merged person is person_b."""
    cur.execute(
        """UPDATE family_relationships
           SET person_b_id = %(keep)s
           WHERE person_b_id = %(merge)s AND user_id = %(uid)s
             AND NOT EXISTS (
                 SELECT 1 FROM family_relationships r2
                 WHERE r2.person_b_id = %(keep)s
                   AND r2.person_a_id = family_relationships.person_a_id
                   AND r2.relationship_type = family_relationships.relationship_type
                   AND r2.user_id = %(uid)s
             )""",
        {"keep": keep_id, "merge": merge_id, "uid": user_id},
    )
    return cur.rowcount


def _transfer_documents(cur: Any, user_id: int, keep_id: int, merge_id: int) -> int:
    """Move documents attached to the merged person onto the kept person."""
    cur.execute(
        """UPDATE family_documents
           SET person_id = %(keep)s
           WHERE person_id = %(merge)s AND user_id = %(uid)s""",
        {"keep": keep_id, "merge": merge_id, "uid": user_id},
    )
    return cur.rowcount


def merge_persons(user_id: int, keep_id: int, merge_id: int) -> dict[str, Any]:
    """
    Merge *merge_id* into *keep_id* for the given user.

    Steps:
        1. Re-point relationships referencing merge_id → keep_id
        2. Re-point documents referencing merge_id → keep_id
        3. Delete the merged person record

    Returns dict with merge summary or raises ValueError.
    """
    if keep_id == merge_id:
        raise ValueError("keep_id and merge_id must differ")

    with get_db_cursor(commit=True) as (conn, cur):
        # Verify both persons belong to this user
        cur.execute(
            "SELECT id FROM family_persons WHERE id = %(id)s AND user_id = %(uid)s",
            {"id": keep_id, "uid": user_id},
        )
        if not cur.fetchone():
            raise ValueError(f"Person {keep_id} not found for user")

        cur.execute(
            "SELECT id FROM family_persons WHERE id = %(id)s AND user_id = %(uid)s",
            {"id": merge_id, "uid": user_id},
        )
        if not cur.fetchone():
            raise ValueError(f"Person {merge_id} not found for user")

        rels_a = _transfer_relationships_person_a(cur, user_id, keep_id, merge_id)
        rels_b = _transfer_relationships_person_b(cur, user_id, keep_id, merge_id)

        # Delete any remaining relationships that still reference merge_id
        # (duplicates that couldn't be transferred)
        cur.execute(
            """DELETE FROM family_relationships
               WHERE (person_a_id = %(merge)s OR person_b_id = %(merge)s)
                 AND user_id = %(uid)s""",
            {"merge": merge_id, "uid": user_id},
        )
        rels_deleted = cur.rowcount

        docs_moved = _transfer_documents(cur, user_id, keep_id, merge_id)

        # --- Delete merged person -----------------------------------------
        cur.execute(
            "DELETE FROM family_persons WHERE id = %(id)s AND user_id = %(uid)s",
            {"id": merge_id, "uid": user_id},
        )

    return {
        "keep_id": keep_id,
        "merged_id": merge_id,
        "relationships_transferred": rels_a + rels_b,
        "relationships_removed_duplicates": rels_deleted,
        "documents_transferred": docs_moved,
        "status": "merged",
    }
