"""
Code Health Routes — Consciousness Module
==========================================
API endpoints for codebase metrics, audit progress, and snapshots.
"""

from flask import jsonify


def register_code_health_routes(bp, admin_required):
    @bp.route("/api/code-health/scan", methods=["POST"])
    @admin_required
    def code_health_scan():
        from services.code_metrics_service import scan_codebase, save_snapshot

        metrics = scan_codebase()
        snapshot_id = save_snapshot(metrics)
        return jsonify({"success": True, "snapshot_id": snapshot_id, "metrics": metrics})

    @bp.route("/api/code-health/current")
    @admin_required
    def code_health_current():
        from services.code_metrics_service import scan_codebase

        metrics = scan_codebase()
        return jsonify(metrics)

    @bp.route("/api/code-health/snapshots")
    @admin_required
    def code_health_snapshots():
        from services.code_metrics_service import get_snapshots

        snapshots = get_snapshots(limit=365)
        return jsonify({"snapshots": snapshots})

    @bp.route("/api/code-health/audit-log")
    @admin_required
    def code_health_audit_log():
        from services.code_metrics_service import get_audit_log

        entries = get_audit_log()
        return jsonify({"entries": entries})

    @bp.route("/api/code-health/module-status")
    @admin_required
    def code_health_module_status():
        from database import get_db_cursor

        modules = []
        summary = {"green": 0, "yellow": 0, "red": 0, "total": 0}

        with get_db_cursor() as (conn, cur):
            # Get module list from latest code_metrics_snapshot per_module JSONB
            cur.execute(
                """SELECT per_module FROM code_metrics_snapshots
                   ORDER BY scanned_at DESC LIMIT 1"""
            )
            row = cur.fetchone()
            per_module = row["per_module"] if row and row.get("per_module") else {}
            module_names = list(per_module.keys())

            # Get latest audit per module
            cur.execute(
                """SELECT DISTINCT ON (module_name)
                      module_name, audited_at, status, stale
                   FROM code_audit_log
                   ORDER BY module_name, audited_at DESC"""
            )
            audits = {
                r["module_name"]: {"audited_at": r["audited_at"], "status": r["status"], "stale": r["stale"]}
                for r in cur.fetchall()
            }

            # Get latest scan date
            cur.execute("SELECT scanned_at FROM code_metrics_snapshots ORDER BY scanned_at DESC LIMIT 1")
            scan_row = cur.fetchone()
            last_scan_date = scan_row["scanned_at"].isoformat() if scan_row else None

            for name in sorted(module_names):
                audit = audits.get(name)
                if not audit:
                    status = "red"
                elif audit["status"] == "violations_found":
                    status = "red"
                elif audit.get("stale"):
                    status = "yellow"
                else:
                    status = "green"

                summary[status] += 1
                summary["total"] += 1

                modules.append(
                    {
                        "module_name": name,
                        "status": status,
                        "last_audit_date": audit["audited_at"].isoformat() if audit else None,
                        "last_audit_status": audit["status"] if audit else None,
                        "stale": audit.get("stale", False) if audit else False,
                        "files_changed_since_audit": 0,
                        "last_scan_date": last_scan_date,
                    }
                )

        return jsonify({"success": True, "modules": modules, "summary": summary})

    @bp.route("/api/code-health/backfill-git", methods=["POST"])
    @admin_required
    def code_health_backfill_git():
        from services.code_metrics_service import backfill_git_history

        result = backfill_git_history()
        return jsonify(result)
