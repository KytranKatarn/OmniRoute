"""Photography Studio plugin routes — packages, shoots, galleries, editing queue, stats."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Photography Studio routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("industry-photography")
    def index():
        return render_template("photography.html")

    # ------------------------------------------------------------------
    # Packages
    # ------------------------------------------------------------------

    @bp.route("/api/packages", methods=["GET"])
    @login_required
    @require_module("industry-photography")
    def list_packages():
        active_only = request.args.get("active_only", "true").lower() == "true"
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if active_only:
                cur.execute(
                    """
                    SELECT id, name, description, includes, price, duration_hours,
                           max_images, digital_delivery, print_included, is_active, created_at
                    FROM photo_packages WHERE is_active = TRUE ORDER BY price
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id, name, description, includes, price, duration_hours,
                           max_images, digital_delivery, print_included, is_active, created_at
                    FROM photo_packages ORDER BY price
                    """
                )
            packages = cur.fetchall()
        return jsonify({"packages": packages})

    @bp.route("/api/packages", methods=["POST"])
    @login_required
    @require_module("industry-photography")
    def create_package():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO photo_packages
                    (name, description, includes, price, duration_hours,
                     max_images, digital_delivery, print_included, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, name, description, includes, price, duration_hours,
                          max_images, digital_delivery, print_included, is_active, created_at
                """,
                (
                    name,
                    data.get("description"),
                    Json(data.get("includes", [])),
                    data.get("price"),
                    data.get("duration_hours"),
                    data.get("max_images"),
                    data.get("digital_delivery", True),
                    data.get("print_included", False),
                    data.get("is_active", True),
                ),
            )
            pkg = cur.fetchone()
        return jsonify(pkg), 201

    @bp.route("/api/packages/<int:package_id>", methods=["PUT"])
    @login_required
    @require_module("industry-photography")
    def update_package(package_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM photo_packages WHERE id = %s", (package_id,))
            if not cur.fetchone():
                return jsonify({"error": "Package not found"}), 404
            cur.execute(
                """
                UPDATE photo_packages SET
                    name             = COALESCE(%s, name),
                    description      = COALESCE(%s, description),
                    price            = COALESCE(%s, price),
                    duration_hours   = COALESCE(%s, duration_hours),
                    max_images       = COALESCE(%s, max_images),
                    digital_delivery = COALESCE(%s, digital_delivery),
                    print_included   = COALESCE(%s, print_included),
                    is_active        = COALESCE(%s, is_active)
                WHERE id = %s
                RETURNING id, name, description, includes, price, duration_hours,
                          max_images, digital_delivery, print_included, is_active, created_at
                """,
                (
                    data.get("name"),
                    data.get("description"),
                    data.get("price"),
                    data.get("duration_hours"),
                    data.get("max_images"),
                    data.get("digital_delivery"),
                    data.get("print_included"),
                    data.get("is_active"),
                    package_id,
                ),
            )
            pkg = cur.fetchone()
        return jsonify(pkg)

    # ------------------------------------------------------------------
    # Shoots
    # ------------------------------------------------------------------

    @bp.route("/api/shoots", methods=["GET"])
    @login_required
    @require_module("industry-photography")
    def list_shoots():
        status = request.args.get("status")
        shoot_type = request.args.get("shoot_type")
        conditions = []
        params: list = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if shoot_type:
            conditions.append("shoot_type = %s")
            params.append(shoot_type)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(f"SELECT COUNT(*) AS cnt FROM photo_shoots {where}", params)
            total = cur.fetchone()["cnt"]
            cur.execute(
                f"""
                SELECT id, job_id, customer_id, shoot_type, shoot_date, location,
                       duration_hours, status, package_id, total_images, delivered_images,
                       notes, metadata, created_at
                FROM photo_shoots {where}
                ORDER BY shoot_date DESC NULLS LAST, created_at DESC
                """,
                params,
            )
            shoots = cur.fetchall()
        return jsonify({"shoots": shoots, "total": total})

    @bp.route("/api/shoots", methods=["POST"])
    @login_required
    @require_module("industry-photography")
    def create_shoot():
        data = request.get_json(force=True)
        shoot_type = (data.get("shoot_type") or "").strip()
        shoot_date = data.get("shoot_date")
        if not shoot_type:
            return jsonify({"error": "shoot_type is required"}), 400
        if not shoot_date:
            return jsonify({"error": "shoot_date is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO photo_shoots
                    (job_id, customer_id, shoot_type, shoot_date, location,
                     duration_hours, status, package_id, total_images, notes, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, customer_id, shoot_type, shoot_date, location,
                          duration_hours, status, package_id, total_images, delivered_images,
                          notes, metadata, created_at
                """,
                (
                    data.get("job_id"),
                    data.get("customer_id"),
                    shoot_type,
                    shoot_date,
                    data.get("location"),
                    data.get("duration_hours"),
                    data.get("status", "booked"),
                    data.get("package_id"),
                    data.get("total_images", 0),
                    data.get("notes"),
                    Json(data.get("metadata", {})),
                ),
            )
            shoot = cur.fetchone()

        event_bus.emit("shoot.booked", {
            "shoot_id": shoot["id"],
            "shoot_type": shoot["shoot_type"],
            "shoot_date": str(shoot["shoot_date"]) if shoot["shoot_date"] else None,
            "_tenant_id": g.tenant_id,
        })
        return jsonify(shoot), 201

    @bp.route("/api/shoots/<int:shoot_id>", methods=["GET"])
    @login_required
    @require_module("industry-photography")
    def get_shoot(shoot_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, job_id, customer_id, shoot_type, shoot_date, location,
                       duration_hours, status, package_id, total_images, delivered_images,
                       notes, metadata, created_at
                FROM photo_shoots WHERE id = %s
                """,
                (shoot_id,),
            )
            shoot = cur.fetchone()
        if not shoot:
            return jsonify({"error": "Shoot not found"}), 404

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, name, url, password, expiry_date, is_public, download_enabled,"
                " view_count, created_at FROM photo_galleries WHERE shoot_id = %s ORDER BY created_at",
                (shoot_id,),
            )
            shoot["galleries"] = cur.fetchall()
            cur.execute(
                "SELECT id, editor, status, total_images, edited_images, style_preset,"
                " due_date, notes, created_at FROM photo_editing_queue WHERE shoot_id = %s ORDER BY created_at",
                (shoot_id,),
            )
            shoot["editing"] = cur.fetchall()
        return jsonify(shoot)

    @bp.route("/api/shoots/<int:shoot_id>", methods=["PUT"])
    @login_required
    @require_module("industry-photography")
    def update_shoot(shoot_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM photo_shoots WHERE id = %s", (shoot_id,))
            if not cur.fetchone():
                return jsonify({"error": "Shoot not found"}), 404
            cur.execute(
                """
                UPDATE photo_shoots SET
                    shoot_type       = COALESCE(%s, shoot_type),
                    shoot_date       = COALESCE(%s, shoot_date),
                    location         = COALESCE(%s, location),
                    duration_hours   = COALESCE(%s, duration_hours),
                    status           = COALESCE(%s, status),
                    package_id       = COALESCE(%s, package_id),
                    total_images     = COALESCE(%s, total_images),
                    delivered_images = COALESCE(%s, delivered_images),
                    notes            = COALESCE(%s, notes)
                WHERE id = %s
                RETURNING id, job_id, customer_id, shoot_type, shoot_date, location,
                          duration_hours, status, package_id, total_images, delivered_images,
                          notes, metadata, created_at
                """,
                (
                    data.get("shoot_type"),
                    data.get("shoot_date"),
                    data.get("location"),
                    data.get("duration_hours"),
                    data.get("status"),
                    data.get("package_id"),
                    data.get("total_images"),
                    data.get("delivered_images"),
                    data.get("notes"),
                    shoot_id,
                ),
            )
            shoot = cur.fetchone()
        return jsonify(shoot)

    @bp.route("/api/shoots/<int:shoot_id>/deliver", methods=["POST"])
    @login_required
    @require_module("industry-photography")
    def deliver_shoot(shoot_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE photo_shoots SET status = 'delivered'"
                " WHERE id = %s RETURNING id, shoot_type, status, delivered_images",
                (shoot_id,),
            )
            shoot = cur.fetchone()
        if not shoot:
            return jsonify({"error": "Shoot not found"}), 404
        event_bus.emit("shoot.delivered", {
            "shoot_id": shoot_id,
            "shoot_type": shoot["shoot_type"],
            "_tenant_id": g.tenant_id,
        })
        return jsonify(shoot)

    # ------------------------------------------------------------------
    # Galleries
    # ------------------------------------------------------------------

    @bp.route("/api/shoots/<int:shoot_id>/galleries", methods=["GET"])
    @login_required
    @require_module("industry-photography")
    def list_galleries(shoot_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, shoot_id, name, url, password, expiry_date, is_public,"
                " download_enabled, view_count, created_at"
                " FROM photo_galleries WHERE shoot_id = %s ORDER BY created_at",
                (shoot_id,),
            )
            galleries = cur.fetchall()
        return jsonify({"galleries": galleries})

    @bp.route("/api/shoots/<int:shoot_id>/galleries", methods=["POST"])
    @login_required
    @require_module("industry-photography")
    def create_gallery(shoot_id):
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM photo_shoots WHERE id = %s", (shoot_id,))
            if not cur.fetchone():
                return jsonify({"error": "Shoot not found"}), 404
            cur.execute(
                """
                INSERT INTO photo_galleries
                    (shoot_id, name, url, password, expiry_date, is_public, download_enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, shoot_id, name, url, password, expiry_date, is_public,
                          download_enabled, view_count, created_at
                """,
                (
                    shoot_id,
                    name,
                    data.get("url"),
                    data.get("password"),
                    data.get("expiry_date"),
                    data.get("is_public", False),
                    data.get("download_enabled", True),
                ),
            )
            gallery = cur.fetchone()

        event_bus.emit("gallery.created", {
            "gallery_id": gallery["id"],
            "shoot_id": shoot_id,
            "name": gallery["name"],
            "_tenant_id": g.tenant_id,
        })
        return jsonify(gallery), 201

    @bp.route("/api/galleries/<int:gallery_id>/view", methods=["POST"])
    @login_required
    @require_module("industry-photography")
    def increment_gallery_views(gallery_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "UPDATE photo_galleries SET view_count = view_count + 1"
                " WHERE id = %s RETURNING id, name, view_count",
                (gallery_id,),
            )
            gallery = cur.fetchone()
        if not gallery:
            return jsonify({"error": "Gallery not found"}), 404
        return jsonify(gallery)

    # ------------------------------------------------------------------
    # Editing Queue
    # ------------------------------------------------------------------

    @bp.route("/api/editing", methods=["GET"])
    @login_required
    @require_module("industry-photography")
    def list_editing_queue():
        status = request.args.get("status")
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if status:
                cur.execute(
                    "SELECT id, shoot_id, editor, status, total_images, edited_images,"
                    " style_preset, due_date, notes, created_at"
                    " FROM photo_editing_queue WHERE status = %s ORDER BY due_date NULLS LAST",
                    (status,),
                )
            else:
                cur.execute(
                    "SELECT id, shoot_id, editor, status, total_images, edited_images,"
                    " style_preset, due_date, notes, created_at"
                    " FROM photo_editing_queue ORDER BY due_date NULLS LAST"
                )
            queue = cur.fetchall()
        return jsonify({"queue": queue})

    @bp.route("/api/shoots/<int:shoot_id>/editing", methods=["POST"])
    @login_required
    @require_module("industry-photography")
    def create_editing_entry(shoot_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM photo_shoots WHERE id = %s", (shoot_id,))
            if not cur.fetchone():
                return jsonify({"error": "Shoot not found"}), 404
            cur.execute(
                """
                INSERT INTO photo_editing_queue
                    (shoot_id, editor, status, total_images, edited_images, style_preset, due_date, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, shoot_id, editor, status, total_images, edited_images,
                          style_preset, due_date, notes, created_at
                """,
                (
                    shoot_id,
                    data.get("editor"),
                    data.get("status", "pending"),
                    data.get("total_images"),
                    data.get("edited_images", 0),
                    data.get("style_preset"),
                    data.get("due_date"),
                    data.get("notes"),
                ),
            )
            entry = cur.fetchone()
        return jsonify(entry), 201

    @bp.route("/api/editing/<int:entry_id>", methods=["PUT"])
    @login_required
    @require_module("industry-photography")
    def update_editing_entry(entry_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute("SELECT id FROM photo_editing_queue WHERE id = %s", (entry_id,))
            if not cur.fetchone():
                return jsonify({"error": "Editing entry not found"}), 404
            cur.execute(
                """
                UPDATE photo_editing_queue SET
                    editor        = COALESCE(%s, editor),
                    status        = COALESCE(%s, status),
                    total_images  = COALESCE(%s, total_images),
                    edited_images = COALESCE(%s, edited_images),
                    style_preset  = COALESCE(%s, style_preset),
                    due_date      = COALESCE(%s, due_date),
                    notes         = COALESCE(%s, notes)
                WHERE id = %s
                RETURNING id, shoot_id, editor, status, total_images, edited_images,
                          style_preset, due_date, notes, created_at
                """,
                (
                    data.get("editor"),
                    data.get("status"),
                    data.get("total_images"),
                    data.get("edited_images"),
                    data.get("style_preset"),
                    data.get("due_date"),
                    data.get("notes"),
                    entry_id,
                ),
            )
            entry = cur.fetchone()
        return jsonify(entry)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("industry-photography")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE shoot_date >= date_trunc('month', CURRENT_DATE)
                        AND shoot_date < date_trunc('month', CURRENT_DATE) + INTERVAL '1 month')
                        AS shoots_this_month,
                    COUNT(*) FILTER (WHERE status = 'delivered') AS delivered_total,
                    COALESCE(SUM(p.price) FILTER (WHERE s.status = 'delivered'), 0) AS revenue
                FROM photo_shoots s
                LEFT JOIN photo_packages p ON s.package_id = p.id
                """
            )
            shoot_stats = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS pending_edits FROM photo_editing_queue WHERE status IN ('pending','in_progress')"
            )
            edit_stats = cur.fetchone()

            cur.execute(
                "SELECT COUNT(*) AS galleries_live FROM photo_galleries"
                " WHERE (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)"
            )
            gallery_stats = cur.fetchone()

        return jsonify({
            "shoots_this_month": shoot_stats["shoots_this_month"],
            "pending_edits": edit_stats["pending_edits"],
            "galleries_live": gallery_stats["galleries_live"],
            "revenue": float(shoot_stats["revenue"]),
        })


# ----------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ----------------------------------------------------------------------

def on_job_created(data):
    """No-op placeholder — reserved for future auto-shoot-from-job logic."""
    pass
