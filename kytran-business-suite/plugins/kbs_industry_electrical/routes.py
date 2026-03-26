"""Electrical industry vertical plugin routes."""

import logging
import math

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Electrical plugin routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("industry-electrical")
    def index():
        return render_template("electrical.html")

    # ------------------------------------------------------------------
    # Panels
    # ------------------------------------------------------------------

    @bp.route("/api/panels", methods=["GET"])
    @login_required
    @require_module("industry-electrical")
    def list_panels():
        job_id = request.args.get("job_id")
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if job_id:
                cur.execute(
                    """
                    SELECT id, job_id, name, panel_type, amperage, voltage, phases,
                           spaces, spaces_used, location, notes, created_at
                    FROM electrical_panels
                    WHERE job_id = %s
                    ORDER BY created_at DESC
                    """,
                    (job_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, job_id, name, panel_type, amperage, voltage, phases,
                           spaces, spaces_used, location, notes, created_at
                    FROM electrical_panels
                    ORDER BY created_at DESC
                    """
                )
            panels = cur.fetchall()
        return jsonify({"panels": panels})

    @bp.route("/api/panels", methods=["POST"])
    @login_required
    @require_module("industry-electrical")
    def create_panel():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        amperage = data.get("amperage")
        if not name:
            return jsonify({"error": "name is required"}), 400
        if not amperage:
            return jsonify({"error": "amperage is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO electrical_panels
                    (job_id, name, panel_type, amperage, voltage, phases,
                     spaces, spaces_used, location, notes, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, name, panel_type, amperage, voltage, phases,
                          spaces, spaces_used, location, notes, created_at
                """,
                (
                    data.get("job_id"),
                    name,
                    data.get("panel_type", "main"),
                    amperage,
                    data.get("voltage", 120),
                    data.get("phases", 1),
                    data.get("spaces"),
                    data.get("spaces_used", 0),
                    data.get("location"),
                    data.get("notes"),
                    Json(data.get("metadata") or {}),
                ),
            )
            panel = cur.fetchone()

        event_bus.emit("panel.designed", {"panel_id": panel["id"], "tenant_id": g.tenant_id})
        return jsonify(panel), 201

    @bp.route("/api/panels/<int:panel_id>", methods=["GET"])
    @login_required
    @require_module("industry-electrical")
    def get_panel(panel_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, job_id, name, panel_type, amperage, voltage, phases,
                       spaces, spaces_used, location, notes, metadata, created_at
                FROM electrical_panels
                WHERE id = %s
                """,
                (panel_id,),
            )
            panel = cur.fetchone()
            if not panel:
                return jsonify({"error": "panel not found"}), 404

            cur.execute(
                """
                SELECT id, panel_id, circuit_number, description, amperage,
                       wire_size, breaker_type, load_watts, is_dedicated, notes, created_at
                FROM electrical_circuits
                WHERE panel_id = %s
                ORDER BY circuit_number
                """,
                (panel_id,),
            )
            panel["circuits"] = cur.fetchall()

        return jsonify(panel)

    # ------------------------------------------------------------------
    # Circuits
    # ------------------------------------------------------------------

    @bp.route("/api/panels/<int:panel_id>/circuits", methods=["POST"])
    @login_required
    @require_module("industry-electrical")
    def add_circuit(panel_id):
        data = request.get_json(force=True)
        circuit_number = data.get("circuit_number")
        description = (data.get("description") or "").strip()
        amperage = data.get("amperage")
        if circuit_number is None:
            return jsonify({"error": "circuit_number is required"}), 400
        if not description:
            return jsonify({"error": "description is required"}), 400
        if not amperage:
            return jsonify({"error": "amperage is required"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            # Verify panel exists
            cur.execute("SELECT id FROM electrical_panels WHERE id = %s", (panel_id,))
            if not cur.fetchone():
                return jsonify({"error": "panel not found"}), 404

            cur.execute(
                """
                INSERT INTO electrical_circuits
                    (panel_id, circuit_number, description, amperage,
                     wire_size, breaker_type, load_watts, is_dedicated, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, panel_id, circuit_number, description, amperage,
                          wire_size, breaker_type, load_watts, is_dedicated, notes, created_at
                """,
                (
                    panel_id,
                    circuit_number,
                    description,
                    amperage,
                    data.get("wire_size"),
                    data.get("breaker_type", "standard"),
                    data.get("load_watts", 0),
                    data.get("is_dedicated", False),
                    data.get("notes"),
                ),
            )
            circuit = cur.fetchone()

            # Update spaces_used count
            cur.execute(
                """
                UPDATE electrical_panels
                SET spaces_used = (
                    SELECT COUNT(*) FROM electrical_circuits WHERE panel_id = %s
                )
                WHERE id = %s
                """,
                (panel_id, panel_id),
            )

        return jsonify(circuit), 201

    @bp.route("/api/circuits/<int:circuit_id>", methods=["DELETE"])
    @login_required
    @require_module("industry-electrical")
    def delete_circuit(circuit_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "DELETE FROM electrical_circuits WHERE id = %s RETURNING id, panel_id",
                (circuit_id,),
            )
            deleted = cur.fetchone()
            if not deleted:
                return jsonify({"error": "circuit not found"}), 404

            # Update spaces_used on parent panel
            cur.execute(
                """
                UPDATE electrical_panels
                SET spaces_used = (
                    SELECT COUNT(*) FROM electrical_circuits WHERE panel_id = %s
                )
                WHERE id = %s
                """,
                (deleted["panel_id"], deleted["panel_id"]),
            )

        return jsonify({"deleted": True, "id": circuit_id})

    # ------------------------------------------------------------------
    # Load Calculations
    # ------------------------------------------------------------------

    @bp.route("/api/load-calculations", methods=["POST"])
    @login_required
    @require_module("industry-electrical")
    def create_load_calculation():
        data = request.get_json(force=True)
        building_type = (data.get("building_type") or "").strip()
        total_sqft = data.get("total_sqft")
        if not building_type:
            return jsonify({"error": "building_type is required"}), 400
        if not total_sqft:
            return jsonify({"error": "total_sqft is required"}), 400

        # NEC-based auto-calculations (VA values)
        general_lighting = float(data.get("general_lighting_load") or (total_sqft * 3))  # 3 VA/sqft
        small_appliance = float(data.get("small_appliance_load") or 3000)               # 2 circuits × 1500VA
        fixed_appliance = float(data.get("fixed_appliance_load") or 0)
        hvac = float(data.get("hvac_load") or 0)

        # NEC demand factors: first 3000VA @ 100%, remainder @ 35%
        total_raw = general_lighting + small_appliance + fixed_appliance + hvac
        if total_raw <= 3000:
            total_calculated = total_raw
        else:
            total_calculated = 3000 + (total_raw - 3000) * 0.35

        # Required service amps: total VA / 240V, rounded up to nearest standard size
        raw_amps = total_calculated / 240.0
        standard_sizes = [100, 150, 200, 400, 600, 800, 1000, 1200]
        required_amps = next((s for s in standard_sizes if s >= math.ceil(raw_amps)), 1200)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO electrical_load_calculations
                    (job_id, building_type, total_sqft, general_lighting_load,
                     small_appliance_load, fixed_appliance_load, hvac_load,
                     total_calculated_load, required_service_amps, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, building_type, total_sqft, general_lighting_load,
                          small_appliance_load, fixed_appliance_load, hvac_load,
                          total_calculated_load, required_service_amps, notes, created_at
                """,
                (
                    data.get("job_id"),
                    building_type,
                    total_sqft,
                    general_lighting,
                    small_appliance,
                    fixed_appliance,
                    hvac,
                    total_calculated,
                    required_amps,
                    data.get("notes"),
                ),
            )
            calc = cur.fetchone()

        event_bus.emit("load_calc.completed", {"calc_id": calc["id"], "tenant_id": g.tenant_id})
        return jsonify(calc), 201

    @bp.route("/api/load-calculations", methods=["GET"])
    @login_required
    @require_module("industry-electrical")
    def list_load_calculations():
        job_id = request.args.get("job_id")
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if job_id:
                cur.execute(
                    """
                    SELECT id, job_id, building_type, total_sqft, total_calculated_load,
                           required_service_amps, created_at
                    FROM electrical_load_calculations
                    WHERE job_id = %s
                    ORDER BY created_at DESC
                    """,
                    (job_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, job_id, building_type, total_sqft, total_calculated_load,
                           required_service_amps, created_at
                    FROM electrical_load_calculations
                    ORDER BY created_at DESC
                    """
                )
            calcs = cur.fetchall()
        return jsonify({"load_calculations": calcs})

    @bp.route("/api/load-calculations/<int:calc_id>", methods=["GET"])
    @login_required
    @require_module("industry-electrical")
    def get_load_calculation(calc_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, job_id, building_type, total_sqft, general_lighting_load,
                       small_appliance_load, fixed_appliance_load, hvac_load,
                       total_calculated_load, required_service_amps, notes, created_at
                FROM electrical_load_calculations
                WHERE id = %s
                """,
                (calc_id,),
            )
            calc = cur.fetchone()
        if not calc:
            return jsonify({"error": "load calculation not found"}), 404
        return jsonify(calc)

    # ------------------------------------------------------------------
    # Materials
    # ------------------------------------------------------------------

    @bp.route("/api/materials", methods=["GET"])
    @login_required
    @require_module("industry-electrical")
    def list_materials():
        job_id = request.args.get("job_id")
        status = request.args.get("status")
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            filters = []
            params = []
            if job_id:
                filters.append("job_id = %s")
                params.append(job_id)
            if status:
                filters.append("status = %s")
                params.append(status)
            where = ("WHERE " + " AND ".join(filters)) if filters else ""
            cur.execute(
                f"""
                SELECT id, job_id, name, category, quantity, unit, unit_cost,
                       total_cost, supplier, status, created_at
                FROM electrical_materials
                {where}
                ORDER BY created_at DESC
                """,
                params,
            )
            materials = cur.fetchall()
        return jsonify({"materials": materials})

    @bp.route("/api/materials", methods=["POST"])
    @login_required
    @require_module("industry-electrical")
    def add_material():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        quantity = float(data.get("quantity") or 1)
        unit_cost = data.get("unit_cost")
        total_cost = (quantity * float(unit_cost)) if unit_cost is not None else None

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO electrical_materials
                    (job_id, name, category, quantity, unit, unit_cost, total_cost, supplier, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, name, category, quantity, unit, unit_cost,
                          total_cost, supplier, status, created_at
                """,
                (
                    data.get("job_id"),
                    name,
                    data.get("category"),
                    quantity,
                    data.get("unit", "each"),
                    unit_cost,
                    total_cost,
                    data.get("supplier"),
                    data.get("status", "needed"),
                ),
            )
            material = cur.fetchone()

        return jsonify(material), 201

    @bp.route("/api/materials/<int:material_id>", methods=["PUT"])
    @login_required
    @require_module("industry-electrical")
    def update_material(material_id):
        data = request.get_json(force=True)
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, quantity, unit_cost FROM electrical_materials WHERE id = %s",
                (material_id,),
            )
            existing = cur.fetchone()
            if not existing:
                return jsonify({"error": "material not found"}), 404

            quantity = float(data.get("quantity") or existing["quantity"])
            unit_cost_raw = data.get("unit_cost")
            unit_cost = float(unit_cost_raw) if unit_cost_raw is not None else (float(existing["unit_cost"]) if existing["unit_cost"] is not None else None)
            total_cost = (quantity * unit_cost) if unit_cost is not None else None

            cur.execute(
                """
                UPDATE electrical_materials
                SET status     = COALESCE(%s, status),
                    quantity   = %s,
                    unit_cost  = %s,
                    total_cost = %s,
                    supplier   = COALESCE(%s, supplier)
                WHERE id = %s
                RETURNING id, job_id, name, category, quantity, unit, unit_cost,
                          total_cost, supplier, status, created_at
                """,
                (
                    data.get("status"),
                    quantity,
                    unit_cost,
                    total_cost,
                    data.get("supplier"),
                    material_id,
                ),
            )
            material = cur.fetchone()

        return jsonify(material)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("industry-electrical")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            cur.execute("SELECT COUNT(*) AS total_panels FROM electrical_panels")
            total_panels = cur.fetchone()["total_panels"]

            cur.execute("SELECT COUNT(*) AS total_circuits FROM electrical_circuits")
            total_circuits = cur.fetchone()["total_circuits"]

            cur.execute(
                "SELECT COUNT(*) AS materials_needed FROM electrical_materials WHERE status = 'needed'"
            )
            materials_needed = cur.fetchone()["materials_needed"]

            cur.execute(
                "SELECT COUNT(*) AS load_calcs_done FROM electrical_load_calculations"
            )
            load_calcs_done = cur.fetchone()["load_calcs_done"]

        return jsonify(
            {
                "total_panels": total_panels,
                "total_circuits": total_circuits,
                "materials_needed": materials_needed,
                "load_calcs_done": load_calcs_done,
            }
        )


# ---------------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ---------------------------------------------------------------------------

def on_job_created(payload):
    logger.info("electrical: job.created received — job_id=%s", payload.get("job_id"))


def on_job_completed(payload):
    logger.info("electrical: job.completed received — job_id=%s", payload.get("job_id"))
