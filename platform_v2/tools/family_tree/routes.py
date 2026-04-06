"""Family Tree — main routes: dashboard, tree CRUD, person CRUD, GEDCOM."""

import io

from flask import jsonify, render_template, request, send_file
from flask_login import current_user, login_required

from . import family_tree_bp
from .services.gedcom_service import export_gedcom, import_gedcom
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
    return jsonify(tree)


# ---------------------------------------------------------------------------
# Persons
# ---------------------------------------------------------------------------


@family_tree_bp.route("/api/persons")
@login_required
def api_list_persons():
    persons = list_persons(current_user.id)
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
    return jsonify(person), 201


@family_tree_bp.route("/api/persons/<int:person_id>")
@login_required
def api_get_person(person_id):
    person = get_person(current_user.id, person_id)
    if person is None:
        return jsonify({"error": "Not found"}), 404
    person["sources"] = get_person_sources(person_id)
    return jsonify(person)


@family_tree_bp.route("/api/persons/<int:person_id>", methods=["PUT"])
@login_required
def api_update_person(person_id):
    data = request.get_json(silent=True) or {}
    person = update_person(current_user.id, person_id, **data)
    if person is None:
        return jsonify({"error": "Not found or no valid fields"}), 404
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
    gedcom_text = export_gedcom(current_user.id)
    buf = io.BytesIO(gedcom_text.encode("utf-8"))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="text/plain",
        as_attachment=True,
        download_name="family_tree.ged",
    )
