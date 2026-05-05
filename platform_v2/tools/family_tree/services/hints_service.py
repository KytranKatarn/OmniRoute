"""
Hints Service — AI Record Hints (like Ancestry ThruLines).

Searches all 8 genealogy research APIs for each person in a user's tree,
scores matches by name similarity and date proximity, and stores results
as actionable hints in the family_hints table.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from database import get_db_cursor

from .research_service import search_all_sources
from .tree_service import add_source, link_source_to_person

logger = logging.getLogger(__name__)

# Skip persons who already have hints generated within this window
HINT_FRESHNESS_DAYS = 7


def _name_similarity(name_a, name_b):
    """Return 0.0-1.0 similarity between two name strings."""
    if not name_a or not name_b:
        return 0.0
    return SequenceMatcher(None, name_a.lower().strip(), name_b.lower().strip()).ratio()


def _extract_year(date_str):
    """Try to extract a 4-digit year from a date string."""
    if not date_str:
        return None
    match = re.search(r"\b(\d{4})\b", str(date_str))
    return int(match.group(1)) if match else None


def _date_proximity_score(date_a, date_b):
    """
    Return 0.0-1.0 score based on how close two year values are.
    Exact match = 1.0, 50+ years apart = 0.0.
    """
    year_a = _extract_year(date_a)
    year_b = _extract_year(date_b)
    if year_a is None or year_b is None:
        return 0.3  # neutral when we can't compare
    diff = abs(year_a - year_b)
    if diff == 0:
        return 1.0
    if diff >= 50:
        return 0.0
    return max(0.0, 1.0 - (diff / 50.0))


def _calculate_confidence(person, result):
    """
    Calculate a 0.00-1.00 confidence score for a search result matching a person.
    Weights: name similarity 60%, date proximity 30%, has-URL bonus 10%.
    """
    full_name_person = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()

    # Result may have first_name/last_name (genealogy sources) or just title
    result_name = ""
    if result.get("first_name") or result.get("last_name"):
        result_name = f"{result.get('first_name', '')} {result.get('last_name', '')}".strip()
    if not result_name:
        result_name = result.get("title", "")

    name_score = _name_similarity(full_name_person, result_name)

    person_birth = person.get("birth_date", "")
    result_date = result.get("birth_date") or result.get("date", "")
    date_score = _date_proximity_score(person_birth, result_date)

    url_bonus = 0.10 if result.get("url") else 0.0

    confidence = (name_score * 0.60) + (date_score * 0.30) + url_bonus
    return round(min(1.0, max(0.0, confidence)), 2)


def _get_persons_for_user(user_id):
    """Fetch all persons in the user's tree."""
    sql = """
        SELECT id, first_name, last_name, birth_date, birth_place,
               death_date, death_place, gender
        FROM family_persons
        WHERE user_id = %(user_id)s
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, {"user_id": user_id})
        return [dict(r) for r in cur.fetchall()]


def _person_has_recent_hints(user_id, person_id):
    """Check if this person already has hints generated within the freshness window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=HINT_FRESHNESS_DAYS)
    sql = """
        SELECT COUNT(*) AS cnt FROM family_hints
        WHERE user_id = %(user_id)s
          AND person_id = %(person_id)s
          AND created_at >= %(cutoff)s
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, {"user_id": user_id, "person_id": person_id, "cutoff": cutoff})
        row = cur.fetchone()
        return row["cnt"] > 0


def _store_hint(user_id, person_id, result, confidence):
    """Insert a single hint row."""
    sql = """
        INSERT INTO family_hints
            (user_id, person_id, source_api, external_id, title, snippet, url, confidence_score, status)
        VALUES
            (%(user_id)s, %(person_id)s, %(source_api)s, %(external_id)s,
             %(title)s, %(snippet)s, %(url)s, %(confidence)s, 'pending')
    """
    snippet = result.get("snippet") or result.get("description", "")
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            sql,
            {
                "user_id": user_id,
                "person_id": person_id,
                "source_api": result.get("source", "unknown"),
                "external_id": result.get("external_id", ""),
                "title": result.get("title", ""),
                "snippet": str(snippet)[:500] if snippet else "",
                "url": result.get("url", ""),
                "confidence": confidence,
            },
        )


def generate_hints(user_id):
    """
    For each person in the user's tree, search all research APIs and store
    scored hints. Skips persons with recent hints (within HINT_FRESHNESS_DAYS).

    Returns dict with counts: persons_searched, hints_created, persons_skipped.
    """
    persons = _get_persons_for_user(user_id)
    stats = {"persons_searched": 0, "hints_created": 0, "persons_skipped": 0}

    for person in persons:
        first_name = (person.get("first_name") or "").strip()
        last_name = (person.get("last_name") or "").strip()
        if not first_name and not last_name:
            stats["persons_skipped"] += 1
            continue

        if _person_has_recent_hints(user_id, person["id"]):
            stats["persons_skipped"] += 1
            continue

        kwargs = {}
        if person.get("birth_place"):
            kwargs["birth_place"] = person["birth_place"]
        if person.get("birth_date"):
            kwargs["birth_date"] = person["birth_date"]
            year = _extract_year(person["birth_date"])
            if year:
                kwargs["birth_year"] = str(year)
        if person.get("death_date"):
            kwargs["death_date"] = person["death_date"]
            year = _extract_year(person["death_date"])
            if year:
                kwargs["death_year"] = str(year)

        try:
            results = search_all_sources(first_name, last_name, **kwargs)
        except Exception as e:
            logger.error("search_all_sources failed for person %s: %s", person["id"], e)
            continue

        stats["persons_searched"] += 1

        for result in results:
            confidence = _calculate_confidence(person, result)
            if confidence < 0.20:
                continue  # too low to bother storing
            _store_hint(user_id, person["id"], result, confidence)
            stats["hints_created"] += 1

    logger.info(
        "generate_hints for user %s: searched=%d, created=%d, skipped=%d",
        user_id,
        stats["persons_searched"],
        stats["hints_created"],
        stats["persons_skipped"],
    )
    return stats


def get_hints(user_id, person_id=None):
    """
    Retrieve stored hints for a user, optionally filtered by person_id.
    Returns list of hint dicts ordered by confidence descending.
    """
    params = {"user_id": user_id}
    where = "WHERE h.user_id = %(user_id)s"

    if person_id is not None:
        where += " AND h.person_id = %(person_id)s"
        params["person_id"] = person_id

    sql = f"""
        SELECT h.*, fp.first_name, fp.last_name
        FROM family_hints h
        LEFT JOIN family_persons fp ON fp.id = h.person_id
        {where}
        ORDER BY h.confidence_score DESC, h.created_at DESC
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def dismiss_hint(user_id, hint_id):
    """Mark a hint as dismissed. Returns True if updated, False if not found."""
    sql = """
        UPDATE family_hints SET status = 'dismissed'
        WHERE id = %(hint_id)s AND user_id = %(user_id)s AND status = 'pending'
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(sql, {"hint_id": hint_id, "user_id": user_id})
        return cur.rowcount > 0


def accept_hint(user_id, hint_id):
    """
    Accept a hint: mark it as accepted and create a source record
    linked to the person. Returns the hint dict or None if not found.
    """
    # Fetch the hint
    fetch_sql = """
        SELECT * FROM family_hints
        WHERE id = %(hint_id)s AND user_id = %(user_id)s AND status = 'pending'
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(fetch_sql, {"hint_id": hint_id, "user_id": user_id})
        hint = cur.fetchone()

    if not hint:
        return None

    hint = dict(hint)

    # Mark as accepted
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE family_hints SET status = 'accepted' WHERE id = %(hint_id)s",
            {"hint_id": hint_id},
        )

    # Create a source record using the existing tree_service helpers
    citation = f"Auto-accepted from {hint['source_api']} hint (confidence: {hint['confidence_score']})"
    source = add_source(
        user_id=user_id,
        source_type=hint["source_api"],
        external_id=hint.get("external_id", ""),
        title=hint["title"] or "Research hint",
        url=hint["url"] or "",
        citation=citation,
    )

    source_id = source["id"] if source else None
    hint["source_record_id"] = source_id

    # Link the source to the person
    if source_id:
        try:
            link_source_to_person(
                person_id=hint["person_id"],
                source_id=source_id,
                field_name="hint",
            )
        except Exception as e:
            logger.warning("Could not link source %s to person %s: %s", source_id, hint["person_id"], e)

    return hint
