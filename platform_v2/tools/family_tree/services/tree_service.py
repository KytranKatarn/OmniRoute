"""
Family Tree Service — person/relationship CRUD + recursive ancestor/descendant queries.
All DB access uses the ARCHIE pattern: from database import get_db_cursor.
"""

from typing import Any

import psycopg2

from database import get_db_cursor


class FamilyTreeServiceError(ValueError):
    """Raised when a family-tree service operation cannot be completed."""


def _validate_id(value: Any, field_name: str) -> int:
    """Return a positive integer id or raise a clear validation error."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise FamilyTreeServiceError(f"{field_name} must be a positive integer") from None
    if parsed <= 0:
        raise FamilyTreeServiceError(f"{field_name} must be a positive integer")
    return parsed


def _db_error(action: str, error: psycopg2.Error) -> FamilyTreeServiceError:
    detail = getattr(error, "pgerror", None) or str(error)
    message = detail.strip() if detail else error.__class__.__name__
    return FamilyTreeServiceError(f"Database error while {action}: {message}")


def _person_exists(cur, user_id: int, person_id: int) -> bool:
    cur.execute(
        "SELECT 1 FROM family_persons WHERE id = %(id)s AND user_id = %(user_id)s",
        {"id": person_id, "user_id": user_id},
    )
    return cur.fetchone() is not None


def _would_create_parent_cycle(cur, user_id: int, parent_id: int, child_id: int) -> bool:
    """Return True if parent_id is already reachable below child_id."""
    cur.execute(
        """
        WITH RECURSIVE descendants AS (
            SELECT r.person_b_id AS id, ARRAY[r.person_a_id, r.person_b_id] AS path
            FROM family_relationships r
            WHERE r.user_id = %(user_id)s
              AND r.relationship_type = 'parent_child'
              AND r.person_a_id = %(child_id)s

            UNION ALL

            SELECT r.person_b_id, d.path || r.person_b_id
            FROM family_relationships r
            JOIN descendants d ON r.person_a_id = d.id
            WHERE r.user_id = %(user_id)s
              AND r.relationship_type = 'parent_child'
              AND NOT r.person_b_id = ANY(d.path)
        )
        SELECT 1 FROM descendants WHERE id = %(parent_id)s LIMIT 1
        """,
        {"user_id": user_id, "parent_id": parent_id, "child_id": child_id},
    )
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Allowed fields (whitelist prevents SQL injection in dynamic UPDATE/INSERT)
# ---------------------------------------------------------------------------

_PERSON_ALLOWED = {
    "maiden_name",
    "gender",
    "birth_date",
    "birth_date_approx",
    "birth_place",
    "death_date",
    "death_date_approx",
    "death_place",
    "notes",
    "confidence_score",
    "source_type",
    "avatar_path",
}

_RELATIONSHIP_ALLOWED = {
    "start_date",
    "end_date",
    "confidence_score",
    "source_id",
}


# ---------------------------------------------------------------------------
# Person CRUD
# ---------------------------------------------------------------------------


def create_person(user_id, first_name, last_name, **kwargs):
    """INSERT a new person and return the full row as a dict."""
    user_id = _validate_id(user_id, "user_id")
    fields = {"user_id": user_id, "first_name": first_name, "last_name": last_name}
    for k, v in kwargs.items():
        if k in _PERSON_ALLOWED:
            fields[k] = v

    cols = ", ".join(fields.keys())
    placeholders = ", ".join(f"%({k})s" for k in fields.keys())
    sql = f"INSERT INTO family_persons ({cols}) VALUES ({placeholders}) RETURNING *"

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(sql, fields)
            row = cur.fetchone()
            return dict(row) if row else None
    except psycopg2.Error as e:
        raise _db_error("creating person", e) from e


def get_person(user_id, person_id):
    """Return a single person dict or None."""
    user_id = _validate_id(user_id, "user_id")
    person_id = _validate_id(person_id, "person_id")
    sql = "SELECT * FROM family_persons WHERE id = %(id)s AND user_id = %(user_id)s"
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, {"id": person_id, "user_id": user_id})
            row = cur.fetchone()
            return dict(row) if row else None
    except psycopg2.Error as e:
        raise _db_error("loading person", e) from e


def update_person(user_id: int, person_id: int, **kwargs: Any) -> dict[str, Any] | None:
    """UPDATE allowed fields. Returns updated dict or None."""
    user_id = _validate_id(user_id, "user_id")
    person_id = _validate_id(person_id, "person_id")
    updates = {k: v for k, v in kwargs.items() if k in _PERSON_ALLOWED}
    if not updates:
        return get_person(user_id, person_id)

    set_clause = ", ".join(f"{k} = %({k})s" for k in updates.keys())
    sql = (
        f"UPDATE family_persons SET {set_clause}, updated_at = NOW() "
        f"WHERE id = %(id)s AND user_id = %(user_id)s RETURNING *"
    )
    params = {**updates, "id": person_id, "user_id": user_id}

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
    except psycopg2.Error as e:
        raise _db_error("updating person", e) from e


def delete_person(user_id, person_id):
    """DELETE a person. Returns True if a row was deleted."""
    user_id = _validate_id(user_id, "user_id")
    person_id = _validate_id(person_id, "person_id")
    sql = "DELETE FROM family_persons WHERE id = %(id)s AND user_id = %(user_id)s"
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(sql, {"id": person_id, "user_id": user_id})
            return cur.rowcount > 0
    except psycopg2.Error as e:
        raise _db_error("deleting person", e) from e


def list_persons(user_id: int) -> list[dict[str, Any]]:
    """Return all persons for a user ordered by last_name, first_name."""
    user_id = _validate_id(user_id, "user_id")
    sql = "SELECT * FROM family_persons WHERE user_id = %(user_id)s " "ORDER BY last_name, first_name"
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, {"user_id": user_id})
            return [dict(r) for r in cur.fetchall()]
    except psycopg2.Error as e:
        raise _db_error("listing persons", e) from e


# ---------------------------------------------------------------------------
# Relationship CRUD
# ---------------------------------------------------------------------------


def add_relationship(user_id, person_a_id, person_b_id, relationship_type, **kwargs):
    """
    INSERT a relationship between two persons.
    Uses ON CONFLICT DO NOTHING to prevent duplicates.
    Returns the new row dict or None if conflict.
    """
    user_id = _validate_id(user_id, "user_id")
    person_a_id = _validate_id(person_a_id, "person_a_id")
    person_b_id = _validate_id(person_b_id, "person_b_id")
    if person_a_id == person_b_id:
        raise FamilyTreeServiceError("Circular relationship: a person cannot be related to themselves")

    fields = {
        "user_id": user_id,
        "person_a_id": person_a_id,
        "person_b_id": person_b_id,
        "relationship_type": relationship_type,
        "confidence_score": kwargs.get("confidence_score", 1.00),
    }
    for k in ("start_date", "end_date", "source_id"):
        if k in kwargs:
            fields[k] = kwargs[k]

    cols = ", ".join(fields.keys())
    placeholders = ", ".join(f"%({k})s" for k in fields.keys())
    sql = f"INSERT INTO family_relationships ({cols}) VALUES ({placeholders}) " f"ON CONFLICT DO NOTHING RETURNING *"

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            if not _person_exists(cur, user_id, person_a_id):
                raise FamilyTreeServiceError(f"Person {person_a_id} not found")
            if not _person_exists(cur, user_id, person_b_id):
                raise FamilyTreeServiceError(f"Person {person_b_id} not found")
            if relationship_type == "parent_child" and _would_create_parent_cycle(
                cur, user_id, person_a_id, person_b_id
            ):
                raise FamilyTreeServiceError("Circular relationship: parent_child relationship would create a cycle")

            cur.execute(sql, fields)
            row = cur.fetchone()
            return dict(row) if row else None
    except psycopg2.Error as e:
        raise _db_error("adding relationship", e) from e


def remove_relationship(user_id, relationship_id):
    """DELETE a relationship. Returns True if deleted."""
    user_id = _validate_id(user_id, "user_id")
    relationship_id = _validate_id(relationship_id, "relationship_id")
    sql = "DELETE FROM family_relationships " "WHERE id = %(id)s AND user_id = %(user_id)s"
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(sql, {"id": relationship_id, "user_id": user_id})
            return cur.rowcount > 0
    except psycopg2.Error as e:
        raise _db_error("removing relationship", e) from e


def list_relationships(user_id):
    """Return all relationships for a user."""
    user_id = _validate_id(user_id, "user_id")
    sql = "SELECT * FROM family_relationships WHERE user_id = %(user_id)s"
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, {"user_id": user_id})
            return [dict(r) for r in cur.fetchall()]
    except psycopg2.Error as e:
        raise _db_error("listing relationships", e) from e


# ---------------------------------------------------------------------------
# Tree Queries — Recursive CTEs
# ---------------------------------------------------------------------------


def get_ancestors(user_id, person_id, max_depth=10):
    """
    Recursively walk parent_child relationships upward from person_id.
    Returns list of dicts with a 'depth' field (1 = direct parent).
    """
    user_id = _validate_id(user_id, "user_id")
    person_id = _validate_id(person_id, "person_id")
    max_depth = _validate_id(max_depth, "max_depth")
    sql = """
        WITH RECURSIVE ancestors AS (
            -- Base: direct parents
            SELECT
                p.id, p.first_name, p.last_name, p.maiden_name, p.gender,
                p.birth_date, p.birth_date_approx, p.birth_place,
                p.death_date, p.death_date_approx, p.death_place,
                p.avatar_path, p.confidence_score, p.notes,
                1 AS depth,
                ARRAY[%(person_id)s, p.id] AS path
            FROM family_persons p
            JOIN family_relationships r
                ON r.person_a_id = p.id
                AND r.relationship_type = 'parent_child'
                AND r.person_b_id = %(person_id)s
                AND r.user_id = %(user_id)s
            WHERE p.user_id = %(user_id)s

            UNION ALL

            -- Recursive: climb the tree
            SELECT
                p.id, p.first_name, p.last_name, p.maiden_name, p.gender,
                p.birth_date, p.birth_date_approx, p.birth_place,
                p.death_date, p.death_date_approx, p.death_place,
                p.avatar_path, p.confidence_score, p.notes,
                a.depth + 1,
                a.path || p.id
            FROM family_persons p
            JOIN family_relationships r
                ON r.person_a_id = p.id
                AND r.relationship_type = 'parent_child'
                AND r.user_id = %(user_id)s
            JOIN ancestors a ON r.person_b_id = a.id
            WHERE p.user_id = %(user_id)s
              AND a.depth < %(max_depth)s
              AND NOT p.id = ANY(a.path)
        )
        SELECT DISTINCT ON (id)
            id, first_name, last_name, maiden_name, gender,
            birth_date, birth_date_approx, birth_place,
            death_date, death_date_approx, death_place,
            avatar_path, confidence_score, notes, depth
        FROM ancestors
        ORDER BY id, depth
    """
    try:
        with get_db_cursor() as (conn, cur):
            if not _person_exists(cur, user_id, person_id):
                raise FamilyTreeServiceError(f"Person {person_id} not found")
            cur.execute(sql, {"user_id": user_id, "person_id": person_id, "max_depth": max_depth})
            return [dict(r) for r in cur.fetchall()]
    except psycopg2.Error as e:
        raise _db_error("loading ancestors", e) from e


def get_descendants(user_id, person_id, max_depth=10):
    """
    Recursively walk parent_child relationships downward from person_id.
    Returns list of dicts with a 'depth' field (1 = direct child).
    """
    user_id = _validate_id(user_id, "user_id")
    person_id = _validate_id(person_id, "person_id")
    max_depth = _validate_id(max_depth, "max_depth")
    sql = """
        WITH RECURSIVE descendants AS (
            -- Base: direct children
            SELECT
                p.id, p.first_name, p.last_name, p.maiden_name, p.gender,
                p.birth_date, p.birth_date_approx, p.birth_place,
                p.death_date, p.death_date_approx, p.death_place,
                p.avatar_path, p.confidence_score, p.notes,
                1 AS depth,
                ARRAY[%(person_id)s, p.id] AS path
            FROM family_persons p
            JOIN family_relationships r
                ON r.person_b_id = p.id
                AND r.relationship_type = 'parent_child'
                AND r.person_a_id = %(person_id)s
                AND r.user_id = %(user_id)s
            WHERE p.user_id = %(user_id)s

            UNION ALL

            -- Recursive: descend the tree
            SELECT
                p.id, p.first_name, p.last_name, p.maiden_name, p.gender,
                p.birth_date, p.birth_date_approx, p.birth_place,
                p.death_date, p.death_date_approx, p.death_place,
                p.avatar_path, p.confidence_score, p.notes,
                d.depth + 1,
                d.path || p.id
            FROM family_persons p
            JOIN family_relationships r
                ON r.person_b_id = p.id
                AND r.relationship_type = 'parent_child'
                AND r.user_id = %(user_id)s
            JOIN descendants d ON r.person_a_id = d.id
            WHERE p.user_id = %(user_id)s
              AND d.depth < %(max_depth)s
              AND NOT p.id = ANY(d.path)
        )
        SELECT DISTINCT ON (id)
            id, first_name, last_name, maiden_name, gender,
            birth_date, birth_date_approx, birth_place,
            death_date, death_date_approx, death_place,
            avatar_path, confidence_score, notes, depth
        FROM descendants
        ORDER BY id, depth
    """
    try:
        with get_db_cursor() as (conn, cur):
            if not _person_exists(cur, user_id, person_id):
                raise FamilyTreeServiceError(f"Person {person_id} not found")
            cur.execute(sql, {"user_id": user_id, "person_id": person_id, "max_depth": max_depth})
            return [dict(r) for r in cur.fetchall()]
    except psycopg2.Error as e:
        raise _db_error("loading descendants", e) from e


def get_full_tree(user_id):
    """Return all persons and relationships for a user as a combined dict."""
    return {
        "persons": list_persons(user_id),
        "relationships": list_relationships(user_id),
    }


# ---------------------------------------------------------------------------
# Source Management
# ---------------------------------------------------------------------------


def add_source(user_id, source_type, **kwargs):
    """INSERT a source record and return the full row as a dict."""
    user_id = _validate_id(user_id, "user_id")
    fields = {"user_id": user_id, "source_type": source_type}
    for k in ("external_id", "title", "url", "citation"):
        if k in kwargs:
            fields[k] = kwargs[k]

    cols = ", ".join(fields.keys())
    placeholders = ", ".join(f"%({k})s" for k in fields.keys())
    sql = f"INSERT INTO family_sources ({cols}) VALUES ({placeholders}) RETURNING *"

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(sql, fields)
            row = cur.fetchone()
            return dict(row) if row else None
    except psycopg2.Error as e:
        raise _db_error("adding source", e) from e


def link_source_to_person(person_id, source_id, field_name):
    """
    Link a source to a person (for a specific field).
    Uses ON CONFLICT DO NOTHING to prevent duplicates.
    """
    person_id = _validate_id(person_id, "person_id")
    source_id = _validate_id(source_id, "source_id")
    sql = """
        INSERT INTO family_person_sources (person_id, source_id, field_name)
        VALUES (%(person_id)s, %(source_id)s, %(field_name)s)
        ON CONFLICT DO NOTHING
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                sql,
                {
                    "person_id": person_id,
                    "source_id": source_id,
                    "field_name": field_name,
                },
            )
    except psycopg2.Error as e:
        raise _db_error("linking source to person", e) from e


def get_person_sources(person_id):
    """
    Return all sources linked to a person, with the field_name they reference.
    """
    person_id = _validate_id(person_id, "person_id")
    sql = """
        SELECT fs.*, fps.field_name
        FROM family_sources fs
        JOIN family_person_sources fps ON fps.source_id = fs.id
        WHERE fps.person_id = %(person_id)s
        ORDER BY fs.id
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, {"person_id": person_id})
            return [dict(r) for r in cur.fetchall()]
    except psycopg2.Error as e:
        raise _db_error("loading person sources", e) from e
