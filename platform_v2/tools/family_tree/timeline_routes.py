"""Family Tree — Timeline events and migration map routes."""

from flask import jsonify
from flask_login import current_user, login_required

from database import get_db_cursor


def register_timeline_routes(bp, admin_required):
    """Register timeline endpoints on the blueprint."""

    @bp.route("/api/timeline")
    @login_required
    def api_timeline():
        sql = """
            SELECT
                id,
                first_name,
                last_name,
                birth_date,
                birth_date_approx,
                birth_place,
                death_date,
                death_date_approx,
                death_place
            FROM family_persons
            WHERE user_id = %(user_id)s
            ORDER BY birth_date ASC NULLS LAST
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, {"user_id": current_user.id})
            persons = [dict(r) for r in cur.fetchall()]

        events = []
        for p in persons:
            name = f"{p['first_name']} {p['last_name']}".strip()
            pid = p["id"]

            if p.get("birth_date") or p.get("birth_date_approx"):
                events.append(
                    {
                        "type": "birth",
                        "person_id": pid,
                        "person_name": name,
                        "date": p.get("birth_date"),
                        "date_approx": p.get("birth_date_approx"),
                        "place": p.get("birth_place"),
                    }
                )

            if p.get("death_date") or p.get("death_date_approx"):
                events.append(
                    {
                        "type": "death",
                        "person_id": pid,
                        "person_name": name,
                        "date": p.get("death_date"),
                        "date_approx": p.get("death_date_approx"),
                        "place": p.get("death_place"),
                    }
                )

        # Sort: known dates first, then approximate, nulls last
        def sort_key(e):
            d = e.get("date")
            return str(d) if d else "9999-99-99"

        events.sort(key=sort_key)
        return jsonify(events)

    @bp.route("/api/timeline/migration")
    @login_required
    def api_migration_map():
        """Return geocoded migration data for the map view."""
        from .services.map_service import get_migration_data

        try:
            data = get_migration_data(current_user.id)
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e), "locations": [], "paths": []}), 500
