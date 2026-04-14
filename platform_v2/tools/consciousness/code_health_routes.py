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

        metrics = scan_codebase(force=True)
        snapshot_id = save_snapshot(metrics)
        return jsonify({"success": True, "snapshot_id": snapshot_id, "metrics": metrics})

    @bp.route("/api/code-health/current")
    @login_required
    @admin_required
    def code_health_current():
        from flask import request as req

        # Use latest DB snapshot by default (instant), live scan only if ?live=1
        if req.args.get("live") == "1":
            from services.code_metrics_service import scan_codebase

            metrics = scan_codebase()
            return jsonify(metrics)

        # Try loading from latest snapshot first (instant — no filesystem walk)
        row = None
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT total_files, total_lines, total_folders,
                          python_files, python_lines, js_files, js_lines,
                          css_files, css_lines, html_files, html_lines,
                          sql_files, sql_lines, per_module, scanned_at
                   FROM code_metrics_snapshots
                   ORDER BY scanned_at DESC LIMIT 1"""
            )
            row = cur.fetchone()

        if row and row.get("per_module"):
            import json as _json

            per_module = _json.loads(row["per_module"]) if isinstance(row["per_module"], str) else row["per_module"]

            # Reconstruct per-language totals from per_module by_type data
            lang_totals = {}
            for mod_data in per_module.values():
                for lang, counts in (mod_data.get("by_type") or {}).items():
                    if lang not in lang_totals:
                        lang_totals[lang] = {"files": 0, "lines": 0}
                    lang_totals[lang]["files"] += counts.get("files", 0)
                    lang_totals[lang]["lines"] += counts.get("lines", 0)

            metrics = {
                "total_files": row["total_files"],
                "total_lines": row["total_lines"],
                "total_folders": row.get("total_folders", 0),
                "modules": per_module,
                "python": lang_totals.get(
                    "python", {"files": row.get("python_files", 0), "lines": row.get("python_lines", 0)}
                ),
                "js": lang_totals.get("js", {"files": row.get("js_files", 0), "lines": row.get("js_lines", 0)}),
                "css": lang_totals.get("css", {"files": row.get("css_files", 0), "lines": row.get("css_lines", 0)}),
                "html": lang_totals.get("html", {"files": row.get("html_files", 0), "lines": row.get("html_lines", 0)}),
                "sql": lang_totals.get("sql", {"files": row.get("sql_files", 0), "lines": row.get("sql_lines", 0)}),
                "shell": lang_totals.get("shell", {"files": 0, "lines": 0}),
                "json": lang_totals.get("json", {"files": 0, "lines": 0}),
                "yaml": lang_totals.get("yaml", {"files": 0, "lines": 0}),
                "markdown": lang_totals.get("markdown", {"files": 0, "lines": 0}),
                "go": lang_totals.get("go", {"files": 0, "lines": 0}),
                "svg": lang_totals.get("svg", {"files": 0, "lines": 0}),
                "config": lang_totals.get("config", {"files": 0, "lines": 0}),
                "text": lang_totals.get("text", {"files": 0, "lines": 0}),
                "orphans": {},
                "snapshot_age": row["scanned_at"].isoformat() if row["scanned_at"] else None,
            }

            # Add structural audits (lightweight, no filesystem walk)
            try:
                from services.code_metrics_service import (
                    _audit_kbs_plugins,
                    _audit_standalone_products,
                    _calculate_health_score,
                    _detect_retired_modules,
                    _find_orphan_files,
                )

                orphans = _find_orphan_files(set(per_module.keys()))
                metrics["orphans"] = orphans
                metrics["kbs_audit"] = _audit_kbs_plugins()
                metrics["standalone_audit"] = _audit_standalone_products()
                metrics["retired_modules"] = _detect_retired_modules()
                metrics["health_score"] = _calculate_health_score(metrics)
            except Exception:
                pass

            return jsonify(metrics)

        # Fallback: live scan if no snapshot exists
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
        summary = {"green": 0, "yellow": 0, "orange": 0, "red": 0, "total": 0}

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
        from services.code_metrics_service import STANDALONE_PRODUCTS, WEBSITE_PRODUCTS

        for product in STANDALONE_PRODUCTS:
            display_names[product["module_key"]] = product["name"]

        # Add website product display names
        for site in WEBSITE_PRODUCTS:
            display_names[site["module_key"]] = site["name"]

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
                    status = "red"  # never audited
                elif audit["status"] == "violations_found":
                    status = "orange"  # audited but has issues
                elif audit.get("stale"):
                    status = "yellow"  # audit expired (>30 days)
                else:
                    status = "green"  # clean

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

    @bp.route("/api/code-health/severity-summary")
    @login_required
    @admin_required
    def code_health_severity_summary():
        """Return per-module severity breakdown for badge coloring.

        For each module, parses the latest code_audit_log notes to determine
        the highest severity: red (security), yellow (quality), green (clean).
        """
        RED_CODES = {"SQL_INJECTION", "HARDCODED_SECRET", "DIRECT_OLLAMA", "DIRECT_CLOUD"}
        YELLOW_CODES = {"BARE_EXCEPT", "LARGE_FILE", "MISSING_INIT"}

        modules = {}
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT DISTINCT ON (module_name)
                      module_name, issues_found, notes, status, audited_at
                   FROM code_audit_log
                   ORDER BY module_name, audited_at DESC"""
            )
            for row in cur.fetchall():
                name = row["module_name"]
                notes = row["notes"] or ""
                issues_found = row["issues_found"] or 0

                red_count = 0
                yellow_count = 0
                info_count = 0

                if issues_found > 0 and notes:
                    for code in RED_CODES:
                        if code in notes:
                            red_count += notes.count(code)
                    for code in YELLOW_CODES:
                        if code in notes:
                            yellow_count += notes.count(code)
                    info_count = max(0, issues_found - red_count - yellow_count)

                if red_count > 0:
                    highest = "red"
                elif yellow_count > 0:
                    highest = "yellow"
                else:
                    highest = "green"

                modules[name] = {
                    "highest_severity": highest,
                    "red": red_count,
                    "yellow": yellow_count,
                    "info": info_count,
                    "total_issues": issues_found,
                    "last_audit": row["audited_at"].isoformat() if row["audited_at"] else None,
                }

        return jsonify({"success": True, "modules": modules})

    @bp.route("/api/code-health/backfill-git", methods=["POST"])
    @login_required
    @admin_required
    def code_health_backfill_git():
        from services.code_metrics_service import backfill_git_history

        result = backfill_git_history()
        return jsonify(result)

    @bp.route("/api/code-health/governance-log")
    @login_required
    @admin_required
    def code_health_governance_log():
        """Return F.O.R.G.E. self-healing actions from governance audit log."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT event_type, action, outcome, details, timestamp
                   FROM governance_audit_log
                   WHERE event_category = 'self_healing'
                   ORDER BY timestamp DESC LIMIT 50"""
            )
            entries = []
            for r in cur.fetchall():
                e = dict(r)
                if hasattr(e.get("timestamp"), "isoformat"):
                    e["timestamp"] = e["timestamp"].isoformat()
                entries.append(e)
        return jsonify({"success": True, "entries": entries})

    @bp.route("/api/code-health/standalone-status")
    @login_required
    @admin_required
    def code_health_standalone_status():
        """Return standalone product metrics with compliance tier info.
        Uses latest snapshot for stats (fast), DB for compliance scores."""
        from services.code_metrics_service import STANDALONE_PRODUCTS
        import json as _json

        # Get stats from latest snapshot (no filesystem walk)
        standalone_stats = {}
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT per_module FROM code_metrics_snapshots
                   ORDER BY scanned_at DESC LIMIT 1"""
            )
            row = cur.fetchone()
            if row and row.get("per_module"):
                pm = _json.loads(row["per_module"]) if isinstance(row["per_module"], str) else row["per_module"]
                for k, v in pm.items():
                    if k.startswith("standalone_"):
                        standalone_stats[k] = v

        # Get all compliance scores in one query
        compliance_map = {}
        try:
            product_names = [p["name"] for p in STANDALONE_PRODUCTS]
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT DISTINCT ON (scan_target) scan_target, overall_score, scanned_at
                       FROM compliance_scans
                       WHERE scan_target = ANY(%s)
                       ORDER BY scan_target, scanned_at DESC""",
                    (product_names,),
                )
                for r in cur.fetchall():
                    compliance_map[r["scan_target"]] = {
                        "score": float(r["overall_score"]) if r.get("overall_score") else None,
                        "scanned_at": r["scanned_at"].isoformat() if r.get("scanned_at") else None,
                    }
        except Exception:
            pass

        results = []
        for product in STANDALONE_PRODUCTS:
            key = product["module_key"]
            stats = standalone_stats.get(key, {})
            comp = compliance_map.get(product["name"], {})

            results.append(
                {
                    "name": product["name"],
                    "module_key": key,
                    "tier": product["tier"],
                    "path": product["path"],
                    "files": stats.get("files", 0),
                    "lines": stats.get("lines", 0),
                    "by_type": stats.get("by_type", {}),
                    "compliance_score": comp.get("score"),
                    "last_compliance_scan": comp.get("scanned_at"),
                    "compliance_packs": product.get("compliance_packs", []),
                }
            )

        return jsonify({"success": True, "standalones": results})

    @bp.route("/api/code-health/website-status")
    @login_required
    @admin_required
    def code_health_website_status():
        """Return website product metrics."""
        from services.code_metrics_service import WEBSITE_PRODUCTS, _get_website_stats

        website_stats = _get_website_stats()
        results = []
        for site in WEBSITE_PRODUCTS:
            key = site["module_key"]
            stats = website_stats.get(key, {})
            results.append(
                {
                    "name": site["name"],
                    "module_key": key,
                    "path": site["path"],
                    "files": stats.get("files", 0),
                    "lines": stats.get("lines", 0),
                    "folders": stats.get("folders", 0),
                    "by_type": stats.get("by_type", {}),
                }
            )

        return jsonify({"success": True, "websites": results})

    @bp.route("/api/code-health/audit", methods=["POST"])
    @login_required
    @admin_required
    def code_health_audit():
        """Trigger audit for one or all modules. Dispatched via F.O.R.G.E."""
        from flask import request as req
        from services.code_metrics_service import (
            audit_single_module,
            log_audit,
            scan_codebase,
        )

        data = req.get_json(silent=True) or {}
        module_key = data.get("module")  # single module key, or None for all

        # Get current module data for profile detection
        metrics = scan_codebase()
        all_modules = metrics.get("modules", {})

        if module_key:
            if module_key not in all_modules:
                return jsonify({"success": False, "error": f"Module not found: {module_key}"}), 404
            targets = [module_key]
        else:
            targets = list(all_modules.keys())

        results = []
        for key in targets:
            mod_data = all_modules.get(key, {})
            try:
                issues_found, notes, status, issues_list, profile = audit_single_module(key, module_data=mod_data)
                log_audit(
                    module_name=key,
                    category=profile.upper(),
                    files_reviewed=mod_data.get("files", 0),
                    lines_before=mod_data.get("lines", 0),
                    lines_after=mod_data.get("lines", 0),
                    issues_found=issues_found,
                    notes=notes,
                    status=status,
                    audit_profile=profile,
                    trigger_reason="manual",
                    dispatched_via="F.O.R.G.E.",
                )
                results.append(
                    {
                        "module": key,
                        "profile": profile,
                        "issues": issues_found,
                        "status": status,
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "module": key,
                        "profile": "unknown",
                        "issues": -1,
                        "status": f"error: {str(e)[:100]}",
                    }
                )

        return jsonify(
            {
                "success": True,
                "audited": len(results),
                "results": results,
                "trigger": "manual",
            }
        )

    @bp.route("/api/code-health/audit/<int:audit_id>/details")
    @login_required
    @admin_required
    def code_health_audit_details(audit_id):
        """Get full audit details including findings for a specific audit entry."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, module_name, category, files_reviewed, lines_before,
                          lines_after, issues_found, issues_fixed, notes, status,
                          audited_at, audit_profile, trigger_reason, dispatched_via
                   FROM code_audit_log WHERE id = %s""",
                (audit_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Audit entry not found"}), 404

            # Parse notes into structured findings
            findings = []
            notes = row["notes"] or ""
            if notes and notes != "clean — all checks passed" and notes != "clean":
                for part in notes.split("; "):
                    part = part.strip()
                    if not part:
                        continue
                    code = part.split(":")[0].strip() if ":" in part else part
                    detail = part.split(":", 1)[1].strip() if ":" in part else ""
                    severity = "info"
                    red_codes = {
                        "SQL_INJECTION_RISK",
                        "HARDCODED_SECRET",
                        "DIRECT_OLLAMA",
                        "DIRECT_CLOUD",
                        "INSECURE_DEFAULT",
                    }
                    yellow_codes = {
                        "BARE_EXCEPT",
                        "LARGE_FILE",
                        "MISSING_INIT",
                        "INLINE_SCRIPT",
                        "CONSOLE_LOG",
                        "LATEST_TAG",
                        "MISSING_RESOURCE_LIMIT",
                    }
                    if code in red_codes:
                        severity = "red"
                    elif code in yellow_codes:
                        severity = "yellow"
                    findings.append({"code": code, "detail": detail, "severity": severity})

            # Check if proposals already exist for this module (use metadata for accuracy)
            proposal_status = {"total": 0, "by_status": {}}
            try:
                module_path_pattern = f"platform_v2/tools/{row['module_name']}/%"
                cur.execute(
                    """SELECT status, COUNT(*) as cnt
                       FROM improvement_proposals
                       WHERE metadata->>'source' = 'code_health_audit'
                         AND metadata->>'file_path' LIKE %s
                         AND status NOT IN ('archived', 'rejected', 'deployed')
                       GROUP BY status""",
                    (module_path_pattern,),
                )
                for pr in cur.fetchall():
                    proposal_status["by_status"][pr["status"]] = pr["cnt"]
                    proposal_status["total"] += pr["cnt"]
            except Exception:
                pass

            result = {
                "success": True,
                "audit": {
                    "id": row["id"],
                    "module_name": row["module_name"],
                    "category": row["category"],
                    "files_reviewed": row["files_reviewed"],
                    "lines_before": row["lines_before"],
                    "issues_found": row["issues_found"],
                    "issues_fixed": row["issues_fixed"],
                    "status": row["status"],
                    "audited_at": row["audited_at"].isoformat() if row["audited_at"] else None,
                    "audit_profile": row.get("audit_profile", "python"),
                    "trigger_reason": row.get("trigger_reason", "unknown"),
                    "dispatched_via": row.get("dispatched_via"),
                },
                "findings": findings,
                "notes_raw": notes,
                "proposals": proposal_status,
            }
            return jsonify(result)

    @bp.route("/api/code-health/audit/<int:audit_id>/submit-repair", methods=["POST"])
    @login_required
    @admin_required
    def code_health_submit_repair(audit_id):
        """Submit audit findings to Repair Bay as improvement proposals."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT module_name, notes, issues_found, status FROM code_audit_log WHERE id = %s",
                (audit_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Audit entry not found"}), 404
            if row["status"] == "completed" and row["issues_found"] == 0:
                return jsonify(
                    {
                        "success": False,
                        "error": "No issues to submit — module is clean",
                    }
                )

        # Parse notes into issues_list format for process_audit_findings
        issues_list = []
        notes = row["notes"] or ""
        for part in notes.split("; "):
            part = part.strip()
            if not part:
                continue
            code = part.split(":")[0].strip() if ":" in part else part
            detail = part.split(":", 1)[1].strip() if ":" in part else ""
            red_codes = {
                "SQL_INJECTION_RISK",
                "HARDCODED_SECRET",
                "DIRECT_OLLAMA",
                "DIRECT_CLOUD",
                "INSECURE_DEFAULT",
            }
            yellow_codes = {
                "BARE_EXCEPT",
                "LARGE_FILE",
                "MISSING_INIT",
                "INLINE_SCRIPT",
                "CONSOLE_LOG",
                "LATEST_TAG",
                "MISSING_RESOURCE_LIMIT",
            }
            if code in red_codes:
                severity = "red"
            elif code in yellow_codes:
                severity = "yellow"
            else:
                severity = "info"
            issues_list.append(
                {
                    "code": code,
                    "severity": severity,
                    "file": row["module_name"],
                    "detail": detail,
                }
            )

        try:
            from services.audit_pipeline import process_audit_findings

            result = process_audit_findings(row["module_name"], issues_list)
            return jsonify(
                {
                    "success": True,
                    "proposals_created": result.get("proposals_created", 0),
                    "skipped_duplicates": result.get("skipped_duplicates", 0),
                    "module": row["module_name"],
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/code-health/structural-audit")
    @login_required
    @admin_required
    def code_health_structural_audit():
        """Full structural audit — KBS plugins, standalone tiers, retired modules, health score."""
        from services.code_metrics_service import (
            _audit_kbs_plugins,
            _audit_standalone_products,
            _calculate_health_score,
            _detect_retired_modules,
            _find_orphan_files,
        )

        # Gather orphan data (need module names from scan)
        from services.code_metrics_service import _get_module_stats

        module_stats = _get_module_stats()
        orphans = _find_orphan_files(set(module_stats.keys()))

        kbs_audit = _audit_kbs_plugins()
        standalone_audit = _audit_standalone_products()
        retired_modules = _detect_retired_modules()

        # Build partial report for health score calculation
        partial = {
            "orphans": orphans,
            "kbs_audit": kbs_audit,
            "standalone_audit": standalone_audit,
            "retired_modules": retired_modules,
        }
        health_score = _calculate_health_score(partial)

        return jsonify(
            {
                "success": True,
                "health_score": health_score,
                "orphans": {k: len(v) for k, v in orphans.items()},
                "kbs_audit": {
                    "total": kbs_audit["total"],
                    "healthy": kbs_audit["healthy"],
                    "issues": kbs_audit["issues"],
                },
                "standalone_audit": {
                    "total": standalone_audit["total"],
                    "healthy": standalone_audit["healthy"],
                    "issues": standalone_audit["issues"],
                    "products": [
                        {
                            "name": p["name"],
                            "type": p["type"],
                            "exists": p["exists"],
                            "tier1": p["tier1"],
                            "issues": p["issues"],
                        }
                        for p in standalone_audit["products"]
                    ],
                },
                "retired_modules": retired_modules,
            }
        )

    @bp.route("/api/code-health/repair-pipeline")
    @login_required
    @admin_required
    def code_health_repair_pipeline():
        """Aggregate Repair Bay data for Code Health integration."""
        try:
            with get_db_cursor() as (conn, cur):
                # Repair queue stats by status
                cur.execute(
                    """
                    SELECT status, COUNT(*) as count
                    FROM repair_queue
                    GROUP BY status
                """
                )
                queue_by_status = {r["status"]: r["count"] for r in cur.fetchall()}

                # Repair queue by severity (pending/triaged only)
                cur.execute(
                    """
                    SELECT severity, COUNT(*) as count
                    FROM repair_queue
                    WHERE status IN ('pending', 'triaged', 'in_progress')
                    GROUP BY severity
                """
                )
                queue_by_severity = {r["severity"]: r["count"] for r in cur.fetchall()}

                # Proposal stats by status
                cur.execute(
                    """
                    SELECT status, COUNT(*) as count
                    FROM improvement_proposals
                    GROUP BY status
                """
                )
                proposals_by_status = {r["status"]: r["count"] for r in cur.fetchall()}

                # Recent governance actions (self-healing)
                cur.execute(
                    """
                    SELECT event_category, action, details, timestamp,
                           agent_id, reason
                    FROM governance_audit_log
                    WHERE event_category = 'forge_self_heal'
                    ORDER BY timestamp DESC
                    LIMIT 10
                """
                )
                governance = [
                    {
                        "event": r["event_category"],
                        "action": r["action"],
                        "details": r["details"],
                        "reason": r["reason"],
                        "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                    }
                    for r in cur.fetchall()
                ]

            return jsonify(
                {
                    "success": True,
                    "queue": {
                        "by_status": queue_by_status,
                        "by_severity": queue_by_severity,
                        "total": sum(queue_by_status.values()),
                    },
                    "proposals": {
                        "by_status": proposals_by_status,
                        "total": sum(proposals_by_status.values()),
                    },
                    "governance": governance,
                    "repair_bay_url": "/tools/repair-bay",
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e), "queue": {}, "proposals": {}, "governance": []})
