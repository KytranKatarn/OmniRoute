"""
Code Health Routes — Consciousness Module
==========================================
API endpoints for codebase metrics, audit progress, and snapshots.
"""

from flask import jsonify
from flask_login import login_required

from database import get_db_cursor


def register_code_health_routes(bp, admin_required):
    @bp.route("/api/code-health/scan", methods=["POST"])
    @login_required
    @admin_required
    def code_health_scan():
        from services.code_metrics_service import scan_codebase, save_snapshot

        metrics = scan_codebase()
        snapshot_id = save_snapshot(metrics)
        return jsonify({"success": True, "snapshot_id": snapshot_id, "metrics": metrics})

    @bp.route("/api/code-health/current")
    @login_required
    @admin_required
    def code_health_current():
        from services.code_metrics_service import scan_codebase

        metrics = scan_codebase()
        return jsonify(metrics)

    @bp.route("/api/code-health/snapshots")
    @login_required
    @admin_required
    def code_health_snapshots():
        from services.code_metrics_service import get_snapshots

        snapshots = get_snapshots(limit=365)
        return jsonify({"snapshots": snapshots})

    @bp.route("/api/code-health/audit-log")
    @login_required
    @admin_required
    def code_health_audit_log():
        from services.code_metrics_service import get_audit_log

        entries = get_audit_log()
        return jsonify({"entries": entries})

    @bp.route("/api/code-health/module-status")
    @login_required
    @admin_required
    def code_health_module_status():
        modules = []
        summary = {"green": 0, "yellow": 0, "red": 0, "total": 0}

        # Map folder names to proper display names
        from module_registry import MODULES

        display_names = {m.id: m.name for m in MODULES}
        display_names.update(
            {
                "[AI_BRIDGE]": "AI Bridge",
                "[APP_CORE]": "App Core",
                "[MIGRATIONS]": "Migrations",
                "[SHARED]": "Shared Assets",
            }
        )

        # Add standalone product display names
        from services.code_metrics_service import STANDALONE_PRODUCTS

        for product in STANDALONE_PRODUCTS:
            display_names[product["module_key"]] = product["name"]

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
                        "display_name": display_names.get(name, name.replace("_", " ").title()),
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
    @login_required
    @admin_required
    def code_health_backfill_git():
        from services.code_metrics_service import backfill_git_history

        result = backfill_git_history()
        return jsonify(result)

    @bp.route("/api/code-health/standalone-status")
    @login_required
    @admin_required
    def code_health_standalone_status():
        """Return standalone product metrics with compliance tier info."""
        from services.code_metrics_service import STANDALONE_PRODUCTS, _get_standalone_stats

        standalone_stats = _get_standalone_stats()
        results = []
        for product in STANDALONE_PRODUCTS:
            key = product["module_key"]
            stats = standalone_stats.get(key, {})

            # Check compliance scan results if available
            compliance_score = None
            last_scan = None
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """SELECT overall_score, scanned_at
                           FROM compliance_scans
                           WHERE scan_target = %s
                           ORDER BY scanned_at DESC LIMIT 1""",
                        (product["name"],),
                    )
                    row = cur.fetchone()
                    if row:
                        compliance_score = float(row["overall_score"]) if row.get("overall_score") else None
                        last_scan = row["scanned_at"].isoformat() if row.get("scanned_at") else None
            except Exception:
                pass

            results.append(
                {
                    "name": product["name"],
                    "module_key": key,
                    "tier": product["tier"],
                    "path": product["path"],
                    "files": stats.get("files", 0),
                    "lines": stats.get("lines", 0),
                    "by_type": stats.get("by_type", {}),
                    "compliance_score": compliance_score,
                    "last_compliance_scan": last_scan,
                    "compliance_packs": product.get("compliance_packs", []),
                }
            )

        return jsonify({"success": True, "standalones": results})
