"""Family Tree — main routes: dashboard, tree CRUD, person CRUD, GEDCOM."""

import io

from flask import jsonify, render_template, request, send_file
from flask_login import current_user, login_required

from . import family_tree_bp
from .services.gedcom_service import export_gedcom, import_gedcom
from .services.research_service import generate_life_story
from .services.tree_service import (
    add_relationship,
    create_person,
    delete_person,
    get_full_tree,
    get_person,
    get_person_sources,
    list_persons,
    remove_relationship,
    update_person,
)


def _serialize_person(p):
    """Convert date fields to ISO strings for JSON serialization."""
    if p is None:
        return p
    import datetime

    for key in ("birth_date", "death_date", "created_at"):
        val = p.get(key)
        if isinstance(val, (datetime.date, datetime.datetime)):
            p[key] = val.isoformat()
    return p


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@family_tree_bp.route("/")
@login_required
def index():
    return render_template("family_tree.html")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@family_tree_bp.route("/api/status")
@login_required
def status():
    return jsonify({"status": "ok", "module": "family_tree"})


# ---------------------------------------------------------------------------
# Tree
# ---------------------------------------------------------------------------


@family_tree_bp.route("/api/tree")
@login_required
def api_get_tree():
    tree = get_full_tree(current_user.id)
    if tree and "persons" in tree:
        tree["persons"] = [_serialize_person(p) for p in tree["persons"]]
    return jsonify(tree)


# ---------------------------------------------------------------------------
# Persons
# ---------------------------------------------------------------------------


@family_tree_bp.route("/api/persons")
@login_required
def api_list_persons():
    persons = [_serialize_person(p) for p in list_persons(current_user.id)]
    return jsonify(persons)


@family_tree_bp.route("/api/persons", methods=["POST"])
@login_required
def api_create_person():
    data = request.get_json(silent=True) or {}
    first_name = data.get("first_name", "").strip()
    if not first_name:
        return jsonify({"error": "first_name is required"}), 400

    allowed_kwargs = {
        k: v
        for k, v in data.items()
        if k
        not in (
            "first_name",
            "last_name",
            "user_id",
        )
    }
    person = create_person(
        current_user.id,
        first_name,
        data.get("last_name", ""),
        **allowed_kwargs,
    )
    if person is None:
        return jsonify({"error": "Failed to create person"}), 500
    return jsonify(_serialize_person(person)), 201


@family_tree_bp.route("/api/persons/<int:person_id>")
@login_required
def api_get_person(person_id):
    person = get_person(current_user.id, person_id)
    if person is None:
        return jsonify({"error": "Not found"}), 404
    _serialize_person(person)
    person["sources"] = get_person_sources(person_id)
    return jsonify(person)


@family_tree_bp.route("/api/persons/<int:person_id>", methods=["PUT"])
@login_required
def api_update_person(person_id):
    data = request.get_json(silent=True) or {}
    person = update_person(current_user.id, person_id, **data)
    if person is None:
        return jsonify({"error": "Not found or no valid fields"}), 404
    _serialize_person(person)
    return jsonify(person)


@family_tree_bp.route("/api/persons/<int:person_id>", methods=["DELETE"])
@login_required
def api_delete_person(person_id):
    deleted = delete_person(current_user.id, person_id)
    if not deleted:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"deleted": True})


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------


@family_tree_bp.route("/api/relationships", methods=["POST"])
@login_required
def api_add_relationship():
    data = request.get_json(silent=True) or {}
    person_a_id = data.get("person_a_id")
    person_b_id = data.get("person_b_id")
    relationship_type = data.get("relationship_type", "").strip()

    if not person_a_id or not person_b_id or not relationship_type:
        return jsonify({"error": "person_a_id, person_b_id, and relationship_type are required"}), 400

    rel = add_relationship(
        current_user.id,
        person_a_id,
        person_b_id,
        relationship_type,
        **{k: v for k, v in data.items() if k not in ("person_a_id", "person_b_id", "relationship_type")},
    )
    if rel is None:
        return jsonify({"error": "Relationship already exists or invalid persons"}), 409
    return jsonify(rel), 201


@family_tree_bp.route("/api/relationships/<int:rel_id>", methods=["DELETE"])
@login_required
def api_remove_relationship(rel_id):
    deleted = remove_relationship(current_user.id, rel_id)
    if not deleted:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"deleted": True})


# ---------------------------------------------------------------------------
# GEDCOM Import / Export
# ---------------------------------------------------------------------------


@family_tree_bp.route("/api/gedcom/import", methods=["POST"])
@login_required
def api_gedcom_import():
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "No file provided"}), 400

    filename = f.filename or ""
    if not filename.lower().endswith((".ged", ".gedcom")):
        return jsonify({"error": "File must be a .ged or .gedcom file"}), 400

    content = f.read().decode("utf-8", errors="replace")
    result = import_gedcom(current_user.id, content)
    return jsonify(result)


@family_tree_bp.route("/api/gedcom/export")
@login_required
def api_gedcom_export():
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM family_persons WHERE user_id = %s ORDER BY id",
            (current_user.id,),
        )
        persons = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT * FROM family_relationships WHERE user_id = %s ORDER BY id",
            (current_user.id,),
        )
        relationships = [dict(r) for r in cur.fetchall()]
    gedcom_text = export_gedcom(current_user.id, persons, relationships)
    buf = io.BytesIO(gedcom_text.encode("utf-8"))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="text/plain",
        as_attachment=True,
        download_name="family_tree.ged",
    )


# ---------------------------------------------------------------------------
# AI Story Generation
# ---------------------------------------------------------------------------


@family_tree_bp.route("/api/persons/<int:person_id>/story", methods=["POST"])
@login_required
def api_generate_story(person_id):
    """Generate a narrative biography for a person using AI (H.E.R.I.T.A.G.E.)."""
    from database import get_db_cursor

    user_id = current_user.id

    # Fetch person with ownership check
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM family_persons WHERE id = %s AND user_id = %s",
            (person_id, user_id),
        )
        person = cur.fetchone()
        if person is None:
            return jsonify({"error": "Person not found"}), 404

        # Convert to dict if needed (RealDictCursor returns dict already)
        if not isinstance(person, dict):
            columns = [desc[0] for desc in cur.description]
            person = dict(zip(columns, person))

        # Fetch relationships with connected person names
        cur.execute(
            """
            SELECT r.relationship_type,
                   CASE
                       WHEN r.person_a_id = %s THEN r.person_b_id
                       ELSE r.person_a_id
                   END AS other_person_id,
                   COALESCE(
                       CASE
                           WHEN r.person_a_id = %s THEN pb.first_name || ' ' || COALESCE(pb.last_name, '')
                           ELSE pa.first_name || ' ' || COALESCE(pa.last_name, '')
                       END, 'Unknown'
                   ) AS person_name
            FROM family_relationships r
            LEFT JOIN family_persons pa ON pa.id = r.person_a_id
            LEFT JOIN family_persons pb ON pb.id = r.person_b_id
            WHERE (r.person_a_id = %s OR r.person_b_id = %s)
            """,
            (person_id, person_id, person_id, person_id),
        )
        relationships = [
            {"relationship_type": row[0], "other_person_id": row[1], "person_name": row[2].strip()}
            for row in cur.fetchall()
        ]

        # Fetch life events if the table exists
        events = []
        try:
            cur.execute(
                "SELECT event_type, date, place FROM family_events WHERE person_id = %s ORDER BY date",
                (person_id,),
            )
            events = [
                {"event_type": row[0], "date": str(row[1]) if row[1] else "", "place": row[2] or ""}
                for row in cur.fetchall()
            ]
        except Exception:
            # family_events table may not exist yet — not critical
            conn.rollback()

    # Build person context for the story generator
    person_data = {
        "first_name": person.get("first_name", ""),
        "last_name": person.get("last_name", ""),
        "birth_date": str(person.get("birth_date", "") or ""),
        "birth_place": person.get("birth_place", ""),
        "death_date": str(person.get("death_date", "") or ""),
        "death_place": person.get("death_place", ""),
        "gender": person.get("gender", ""),
        "notes": person.get("notes", ""),
    }

    story = generate_life_story(person_data, relationships, events)
    return jsonify({"story": story, "person_id": person_id})
