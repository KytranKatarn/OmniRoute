"""
Family Tree Service — person/relationship CRUD + recursive ancestor/descendant queries.
All DB access uses the ARCHIE pattern: from database import get_db_cursor.
"""

from database import get_db_cursor

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
    fields = {"user_id": user_id, "first_name": first_name, "last_name": last_name}
    for k, v in kwargs.items():
        if k in _PERSON_ALLOWED:
            fields[k] = v

    cols = ", ".join(fields.keys())
    placeholders = ", ".join(f"%({k})s" for k in fields.keys())
    sql = f"INSERT INTO family_persons ({cols}) VALUES ({placeholders}) RETURNING *"

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(sql, fields)
        row = cur.fetchone()
        return dict(row) if row else None


def get_person(user_id, person_id):
    """Return a single person dict or None."""
    sql = "SELECT * FROM family_persons WHERE id = %(id)s AND user_id = %(user_id)s"
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, {"id": person_id, "user_id": user_id})
        row = cur.fetchone()
        return dict(row) if row else None


def update_person(user_id, person_id, **kwargs):
    """UPDATE allowed fields. Returns updated dict or None."""
    updates = {k: v for k, v in kwargs.items() if k in _PERSON_ALLOWED}
    if not updates:
        return get_person(user_id, person_id)

    set_clause = ", ".join(f"{k} = %({k})s" for k in updates.keys())
    sql = (
        f"UPDATE family_persons SET {set_clause}, updated_at = NOW() "
        f"WHERE id = %(id)s AND user_id = %(user_id)s RETURNING *"
    )
    params = {**updates, "id": person_id, "user_id": user_id}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def delete_person(user_id, person_id):
    """DELETE a person. Returns True if a row was deleted."""
    sql = "DELETE FROM family_persons WHERE id = %(id)s AND user_id = %(user_id)s"
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(sql, {"id": person_id, "user_id": user_id})
        return cur.rowcount > 0


def list_persons(user_id):
    """Return all persons for a user ordered by last_name, first_name."""
    sql = "SELECT * FROM family_persons WHERE user_id = %(user_id)s " "ORDER BY last_name, first_name"
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, {"user_id": user_id})
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Relationship CRUD
# ---------------------------------------------------------------------------


def add_relationship(user_id, person_a_id, person_b_id, relationship_type, **kwargs):
    """
    INSERT a relationship between two persons.
    Uses ON CONFLICT DO NOTHING to prevent duplicates.
    Returns the new row dict or None if conflict.
    """
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

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(sql, fields)
        row = cur.fetchone()
        return dict(row) if row else None


def remove_relationship(user_id, relationship_id):
    """DELETE a relationship. Returns True if deleted."""
    sql = "DELETE FROM family_relationships " "WHERE id = %(id)s AND user_id = %(user_id)s"
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(sql, {"id": relationship_id, "user_id": user_id})
        return cur.rowcount > 0


def list_relationships(user_id):
    """Return all relationships for a user."""
    sql = "SELECT * FROM family_relationships WHERE user_id = %(user_id)s"
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, {"user_id": user_id})
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Tree Queries — Recursive CTEs
# ---------------------------------------------------------------------------


def get_ancestors(user_id, person_id, max_depth=10):
    """
    Recursively walk parent_child relationships upward from person_id.
    Returns list of dicts with a 'depth' field (1 = direct parent).
    """
    sql = """
        WITH RECURSIVE ancestors AS (
            -- Base: direct parents
            SELECT
                p.id, p.first_name, p.last_name, p.maiden_name, p.gender,
                p.birth_date, p.birth_date_approx, p.birth_place,
                p.death_date, p.death_date_approx, p.death_place,
                p.avatar_path, p.confidence_score, p.notes,
                1 AS depth
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
                a.depth + 1
            FROM family_persons p
            JOIN family_relationships r
                ON r.person_a_id = p.id
                AND r.relationship_type = 'parent_child'
                AND r.user_id = %(user_id)s
            JOIN ancestors a ON r.person_b_id = a.id
            WHERE p.user_id = %(user_id)s
              AND a.depth < %(max_depth)s
        )
        SELECT DISTINCT ON (id) * FROM ancestors ORDER BY id, depth
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, {"user_id": user_id, "person_id": person_id, "max_depth": max_depth})
        return [dict(r) for r in cur.fetchall()]


def get_descendants(user_id, person_id, max_depth=10):
    """
    Recursively walk parent_child relationships downward from person_id.
    Returns list of dicts with a 'depth' field (1 = direct child).
    """
    sql = """
        WITH RECURSIVE descendants AS (
            -- Base: direct children
            SELECT
                p.id, p.first_name, p.last_name, p.maiden_name, p.gender,
                p.birth_date, p.birth_date_approx, p.birth_place,
                p.death_date, p.death_date_approx, p.death_place,
                p.avatar_path, p.confidence_score, p.notes,
                1 AS depth
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
                d.depth + 1
            FROM family_persons p
            JOIN family_relationships r
                ON r.person_b_id = p.id
                AND r.relationship_type = 'parent_child'
                AND r.user_id = %(user_id)s
            JOIN descendants d ON r.person_a_id = d.id
            WHERE p.user_id = %(user_id)s
              AND d.depth < %(max_depth)s
        )
        SELECT DISTINCT ON (id) * FROM descendants ORDER BY id, depth
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, {"user_id": user_id, "person_id": person_id, "max_depth": max_depth})
        return [dict(r) for r in cur.fetchall()]


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
    fields = {"user_id": user_id, "source_type": source_type}
    for k in ("external_id", "title", "url", "citation"):
        if k in kwargs:
            fields[k] = kwargs[k]

    cols = ", ".join(fields.keys())
    placeholders = ", ".join(f"%({k})s" for k in fields.keys())
    sql = f"INSERT INTO family_sources ({cols}) VALUES ({placeholders}) RETURNING *"

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(sql, fields)
        row = cur.fetchone()
        return dict(row) if row else None


def link_source_to_person(person_id, source_id, field_name):
    """
    Link a source to a person (for a specific field).
    Uses ON CONFLICT DO NOTHING to prevent duplicates.
    """
    sql = """
        INSERT INTO family_person_sources (person_id, source_id, field_name)
        VALUES (%(person_id)s, %(source_id)s, %(field_name)s)
        ON CONFLICT DO NOTHING
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(sql, {"person_id": person_id, "source_id": source_id, "field_name": field_name})


def get_person_sources(person_id):
    """
    Return all sources linked to a person, with the field_name they reference.
    """
    sql = """
        SELECT fs.*, fps.field_name
        FROM family_sources fs
        JOIN family_person_sources fps ON fps.source_id = fs.id
        WHERE fps.person_id = %(person_id)s
        ORDER BY fs.id
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, {"person_id": person_id})
        return [dict(r) for r in cur.fetchall()]
