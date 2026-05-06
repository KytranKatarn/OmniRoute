"""
Report API Routes
=================
Security report endpoints: list (DB + filesystem), detail, generate,
scan report, assessment, export, download, and daily report generation.
"""

import logging
from datetime import datetime

from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

# Import report service (filesystem-based reports)
try:
    from .report_service import (
        generate_scan_report,
        generate_assessment_report,
        export_vulnerabilities,
        list_reports,
        REPORTS_DIR,
    )

    REPORT_SERVICE_AVAILABLE = True
except ImportError:
    REPORT_SERVICE_AVAILABLE = False
    REPORTS_DIR = None


def register_report_routes(bp, admin_required_decorator):
    """Register all report endpoints on the security_network blueprint."""

    @bp.route("/api/reports/dns-stats")
    @login_required
    @admin_required_decorator
    def reports_dns_stats():
        """Live DNS stats from AdGuard — queries, blocked, top domains, top clients."""
        try:
            from .adguard_service import AdGuardService

            adguard = AdGuardService()
            stats = adguard.get_stats()
            if not stats:
                return jsonify({"success": False, "error": "AdGuard unreachable"}), 503

            # Enrich top clients with device names
            from database import get_db_cursor

            top_clients = []
            for item in (stats.get("top_clients") or [])[:10]:
                for ip, count in item.items():
                    label = ip
                    try:
                        with get_db_cursor() as (conn, cur):
                            cur.execute(
                                """SELECT ndu.device_label, ndu.user_name
                                   FROM network_device_users ndu
                                   JOIN network_devices nd ON nd.mac_address = ndu.mac_address
                                   WHERE nd.ip_address = %s LIMIT 1""",
                                (ip,),
                            )
                            row = cur.fetchone()
                            if row:
                                label = row["device_label"] or row["user_name"] or ip
                    except Exception:
                        pass
                    top_clients.append({"ip": ip, "label": label, "count": count})

            total = stats.get("num_dns_queries", 0)
            blocked = stats.get("num_blocked_filtering", 0)
            rate = round((blocked / total * 100), 1) if total > 0 else 0

            top_blocked = []
            for item in (stats.get("top_blocked_domains") or [])[:10]:
                for domain, count in item.items():
                    top_blocked.append({"domain": domain, "count": count})

            return jsonify(
                {
                    "success": True,
                    "stats": {
                        "total_queries": total,
                        "blocked": blocked,
                        "block_rate_pct": rate,
                        "avg_processing_ms": round((stats.get("avg_processing_time", 0) or 0) * 1000, 2),
                        "top_blocked": top_blocked,
                        "top_clients": top_clients,
                        "hourly_queries": stats.get("dns_queries", []),
                        "hourly_blocked": stats.get("blocked_filtering", []),
                    },
                }
            )
        except Exception as exc:
            logger.error("dns_stats error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/reports/list")
    @login_required
    @admin_required_decorator
    def reports_list():
        """List daily reports with optional type filter (ReportService-backed)."""
        report_type = request.args.get("type")
        limit = request.args.get("limit", 50, type=int)
        try:
            from .report_service import ReportService

            reports = ReportService().get_reports(report_type=report_type, limit=limit)
            return jsonify({"success": True, "reports": reports})
        except Exception as exc:
            logger.error("reports_list error: %s", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/reports")
    @login_required
    @admin_required_decorator
    def api_list_reports():
        """List all generated reports from DB + filesystem."""
        from database import get_db_cursor

        try:
            db_reports = []
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, report_type, title, date_range_start, date_range_end,
                              format, file_path, created_at
                       FROM security_reports
                       ORDER BY created_at DESC
                       LIMIT 100"""
                )
                for row in cur.fetchall():
                    db_reports.append(
                        {
                            "id": row[0],
                            "report_type": row[1],
                            "title": row[2],
                            "date_range_start": row[3].isoformat() if row[3] else None,
                            "date_range_end": row[4].isoformat() if row[4] else None,
                            "format": row[5],
                            "file_path": row[6],
                            "created_at": row[7].isoformat() if row[7] else None,
                            "source": "db",
                        }
                    )

            # Also include filesystem reports if available
            file_reports = []
            if REPORT_SERVICE_AVAILABLE:
                try:
                    for fr in list_reports():
                        fr["source"] = "file"
                        file_reports.append(fr)
                except Exception as e:
                    logger.debug("Failed to list filesystem reports: %s", e)

            return jsonify({"success": True, "reports": db_reports, "file_reports": file_reports})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/reports/generate", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_generate_report():
        """Generate a security report and store in DB."""
        from database import get_db_cursor
        from psycopg2.extras import Json

        data = request.get_json() or {}

        # Handle daily_device / daily_user reports via ReportService
        report_type = data.get("type") or data.get("report_type", "daily_summary")
        if report_type in ("daily_device", "daily_user"):
            try:
                from .report_service import ReportService

                svc = ReportService()
                report_date = data.get("date")
                if report_type == "daily_device":
                    result = svc.generate_daily_device_report(report_date)
                else:
                    result = svc.generate_daily_user_report(report_date)
                return jsonify({"success": True, "data": result})
            except Exception as e:
                logger.exception("Report generation error: %s", e)
                return jsonify({"success": False, "error": str(e)}), 500

        date_start = data.get("date_start")
        date_end = data.get("date_end")

        valid_types = [
            "daily_summary",
            "weekly_report",
            "device_audit",
            "dns_analysis",
            "dns_summary",
        ]
        if report_type not in valid_types:
            return jsonify({"success": False, "error": f"Invalid report type: {report_type}"}), 400

        type_labels = {
            "daily_summary": "Daily Summary",
            "weekly_report": "Weekly Report",
            "device_audit": "Device Audit",
            "dns_analysis": "DNS Analysis",
            "dns_summary": "DNS Summary (7-Day)",
        }
        title = f"{type_labels[report_type]} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        try:
            content = _gather_report_content(report_type, date_start, date_end)

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO security_reports
                       (report_type, title, date_range_start, date_range_end, content, format)
                       VALUES (%s, %s, %s, %s, %s, 'json')
                       RETURNING id""",
                    (
                        report_type,
                        title,
                        date_start,
                        date_end,
                        Json(content),
                    ),
                )
                row = cur.fetchone()
                report_id = row["id"] if isinstance(row, dict) else row[0]

            return jsonify({"success": True, "id": report_id, "title": title})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/reports/<int:report_id>")
    @login_required
    @admin_required_decorator
    def api_view_report(report_id):
        """View a single report from DB."""
        from database import get_db_cursor

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id, report_type, title, date_range_start, date_range_end,
                              content, format, created_at
                       FROM security_reports WHERE id = %s""",
                    (report_id,),
                )
                row = cur.fetchone()
                if not row:
                    return jsonify({"success": False, "error": "Report not found"}), 404

                return jsonify(
                    {
                        "success": True,
                        "report": {
                            "id": row[0],
                            "report_type": row[1],
                            "title": row[2],
                            "date_range_start": row[3].isoformat() if row[3] else None,
                            "date_range_end": row[4].isoformat() if row[4] else None,
                            "content": row[5],
                            "format": row[6],
                            "created_at": row[7].isoformat() if row[7] else None,
                        },
                    }
                )
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/reports/scan/<filename>", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_generate_scan_report(filename):
        """Generate report for a single scan."""
        if not REPORT_SERVICE_AVAILABLE:
            return jsonify({"success": False, "error": "Report service not available"}), 503

        try:
            result = generate_scan_report(filename)
            return jsonify(result)
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/reports/assessment", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_generate_assessment_report():
        """Generate combined assessment report."""
        if not REPORT_SERVICE_AVAILABLE:
            return jsonify({"success": False, "error": "Report service not available"}), 503

        data = request.get_json() or {}
        scan_files = data.get("scans", [])
        client_name = data.get("client", "Assessment")
        assessment_name = data.get("name", "Security Assessment")

        if not scan_files:
            return jsonify({"success": False, "error": "No scan files specified"}), 400

        try:
            result = generate_assessment_report(scan_files, client_name, assessment_name)
            return jsonify(result)
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/reports/export/<filename>")
    @login_required
    @admin_required_decorator
    def api_export_vulnerabilities(filename):
        """Export vulnerabilities from a scan."""
        if not REPORT_SERVICE_AVAILABLE:
            return jsonify({"success": False, "error": "Report service not available"}), 503

        fmt = request.args.get("format", "json")

        try:
            result = export_vulnerabilities(filename, fmt)

            if result.get("success") and fmt == "csv":
                from flask import Response

                return Response(
                    result["csv"],
                    mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename.rsplit('.', 1)[0]}_vulns.csv"},
                )

            return jsonify(result)
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/reports/download/<filename>")
    @login_required
    @admin_required_decorator
    def api_download_report(filename):
        """Download a generated report."""
        if not REPORT_SERVICE_AVAILABLE:
            return jsonify({"success": False, "error": "Report service not available"}), 503

        import os

        # Security: validate filename
        if ".." in filename or "/" in filename or "\\" in filename:
            return jsonify({"success": False, "error": "Invalid filename"}), 400

        filepath = os.path.join(REPORTS_DIR, filename)

        if not os.path.exists(filepath):
            return jsonify({"success": False, "error": "Report not found"}), 404

        try:
            from flask import send_file

            return send_file(filepath, as_attachment=True)
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # --- Weekly security report ---

    @bp.route("/api/reports/weekly")
    @login_required
    @admin_required_decorator
    def api_weekly_report():
        """Get the latest weekly security report (or generate on demand)."""
        try:
            from .report_generator import generate_weekly_report

            report = generate_weekly_report()
            return jsonify({"success": True, "report": report})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/reports/weekly/send", methods=["POST"])
    @login_required
    @admin_required_decorator
    def api_send_weekly_report():
        """Generate and send weekly report to Telegram now."""
        try:
            from .report_generator import generate_weekly_report, format_report_telegram
            from .security_alerts import create_security_alert

            report = generate_weekly_report()
            telegram_text = format_report_telegram(report)
            notif_id = create_security_alert(
                "scan_result",
                "Weekly Security Report",
                telegram_text,
                priority="normal",
                telegram=True,
            )
            return jsonify({"success": True, "notification_id": notif_id})
        except Exception as e:
            logger.exception("Route error: %s", e)
            return jsonify({"success": False, "error": "Internal server error"}), 500


def _gather_report_content(report_type, date_start=None, date_end=None):
    """Gather report content based on type by querying relevant DB data."""
    from database import get_db_cursor

    content = {"report_type": report_type, "generated_at": datetime.now().isoformat()}

    with get_db_cursor() as (conn, cur):
        date_filter = ""
        date_params = []
        if date_start:
            date_filter += " AND created_at >= %s"
            date_params.append(date_start)
        if date_end:
            date_filter += " AND created_at <= %s"
            date_params.append(date_end)

        if report_type == "daily_summary":
            # Security events from last 24h (or date range)
            df = date_filter if date_start else " AND created_at >= NOW() - INTERVAL '24 hours'"
            dp = date_params if date_start else []
            try:
                cur.execute(
                    "SELECT severity, COUNT(*) as cnt FROM security_events WHERE 1=1"
                    + df
                    + " GROUP BY severity ORDER BY cnt DESC",
                    dp,
                )
                content["events_by_severity"] = [{"severity": r[0], "count": r[1]} for r in cur.fetchall()]
            except Exception as e:
                logger.debug("Report query failed (events_by_severity): %s", e)
                conn.rollback()
                content["events_by_severity"] = []

            try:
                cur.execute(
                    "SELECT event_type, description, severity, status, created_at FROM security_events WHERE 1=1"
                    + df
                    + " ORDER BY created_at DESC LIMIT 50",
                    dp,
                )
                content["recent_events"] = [
                    {
                        "type": r[0],
                        "description": r[1],
                        "severity": r[2],
                        "status": r[3],
                        "created_at": r[4].isoformat() if r[4] else None,
                    }
                    for r in cur.fetchall()
                ]
            except Exception as e:
                logger.debug("Report query failed (recent_events): %s", e)
                conn.rollback()
                content["recent_events"] = []

        elif report_type == "weekly_report":
            df = date_filter if date_start else " AND created_at >= NOW() - INTERVAL '7 days'"
            dp = date_params if date_start else []
            try:
                cur.execute(
                    "SELECT DATE(created_at) as day, severity, COUNT(*) FROM security_events WHERE 1=1"
                    + df
                    + " GROUP BY day, severity ORDER BY day DESC",
                    dp,
                )
                daily = {}
                for r in cur.fetchall():
                    day_str = r[0].isoformat()
                    if day_str not in daily:
                        daily[day_str] = {}
                    daily[day_str][r[1]] = r[2]
                content["daily_breakdown"] = daily
            except Exception as e:
                logger.debug("Report query failed (daily_breakdown): %s", e)
                conn.rollback()
                content["daily_breakdown"] = {}

            try:
                cur.execute(
                    "SELECT COUNT(*) FROM security_events WHERE 1=1" + df,
                    dp,
                )
                content["total_events"] = cur.fetchone()[0]
            except Exception as e:
                logger.debug("Report query failed (total_events): %s", e)
                conn.rollback()
                content["total_events"] = 0

            # Scan results summary
            try:
                cur.execute(
                    "SELECT severity, COUNT(*) FROM security_scan_results WHERE 1=1"
                    + df
                    + " GROUP BY severity ORDER BY COUNT(*) DESC",
                    dp,
                )
                content["scan_findings"] = [{"severity": r[0], "count": r[1]} for r in cur.fetchall()]
            except Exception as e:
                logger.debug("Report query failed (scan_findings): %s", e)
                conn.rollback()
                content["scan_findings"] = []

        elif report_type == "device_audit":
            try:
                cur.execute(
                    """SELECT hostname, ip_address::text, mac_address, device_type,
                              status, security_zone, is_registered, last_seen_at
                       FROM network_devices
                       ORDER BY last_seen_at DESC NULLS LAST LIMIT 200"""
                )
                content["devices"] = [
                    {
                        "hostname": r[0],
                        "ip": r[1],
                        "mac": r[2],
                        "type": r[3],
                        "status": r[4],
                        "zone": r[5],
                        "registered": r[6],
                        "last_seen": r[7].isoformat() if r[7] else None,
                    }
                    for r in cur.fetchall()
                ]
                content["total_devices"] = len(content["devices"])
            except Exception as e:
                logger.debug("Report query failed (devices): %s", e)
                conn.rollback()
                content["devices"] = []
                content["total_devices"] = 0

            # Zone summary
            try:
                cur.execute(
                    """SELECT security_zone, COUNT(*) FROM network_devices
                       GROUP BY security_zone ORDER BY COUNT(*) DESC"""
                )
                content["zone_summary"] = [{"zone": r[0], "count": r[1]} for r in cur.fetchall()]
            except Exception as e:
                logger.debug("Report query failed (zone_summary): %s", e)
                conn.rollback()
                content["zone_summary"] = []

        elif report_type == "dns_analysis":
            df = date_filter if date_start else " AND created_at >= NOW() - INTERVAL '7 days'"
            dp = date_params if date_start else []
            # DNS changes
            try:
                cur.execute(
                    "SELECT source, action, domain, changed_by, created_at FROM security_dns_changes WHERE 1=1"
                    + df
                    + " ORDER BY created_at DESC LIMIT 100",
                    dp,
                )
                content["dns_changes"] = [
                    {
                        "source": r[0],
                        "action": r[1],
                        "domain": r[2],
                        "changed_by": r[3],
                        "created_at": r[4].isoformat() if r[4] else None,
                    }
                    for r in cur.fetchall()
                ]
            except Exception as e:
                logger.debug("Report query failed (dns_changes): %s", e)
                conn.rollback()
                content["dns_changes"] = []

            # DNS providers
            try:
                cur.execute(
                    """SELECT provider_name, provider_type, is_active
                       FROM dns_providers ORDER BY provider_name"""
                )
                content["dns_providers"] = [{"name": r[0], "type": r[1], "active": r[2]} for r in cur.fetchall()]
            except Exception as e:
                logger.debug("Report query failed (dns_providers): %s", e)
                conn.rollback()
                content["dns_providers"] = []

        elif report_type == "dns_summary":
            # Pull live AdGuard stats for DNS summary report
            try:
                from .adguard_service import AdGuardService

                adguard = AdGuardService()
                stats = adguard.get_stats() or {}
                total = stats.get("num_dns_queries", 0)
                blocked = stats.get("num_blocked_filtering", 0)

                content["total_queries"] = total
                content["blocked"] = blocked
                content["block_rate_pct"] = round(blocked / total * 100, 1) if total > 0 else 0
                content["avg_processing_ms"] = round((stats.get("avg_processing_time", 0) or 0) * 1000, 2)

                # Top blocked domains
                top_blocked = []
                for item in (stats.get("top_blocked_domains") or [])[:15]:
                    for domain, count in item.items():
                        top_blocked.append({"domain": domain, "count": count})
                content["top_blocked_domains"] = top_blocked

                # Top clients with device name enrichment
                top_clients = []
                for item in (stats.get("top_clients") or [])[:10]:
                    for ip, count in item.items():
                        label = ip
                        try:
                            cur.execute(
                                """SELECT ndu.device_label, ndu.user_name
                                   FROM network_device_users ndu
                                   JOIN network_devices nd
                                     ON nd.mac_address = ndu.mac_address
                                   WHERE nd.ip_address = %s LIMIT 1""",
                                (ip,),
                            )
                            row = cur.fetchone()
                            if row:
                                label = row[0] or row[1] or ip
                        except Exception:
                            conn.rollback()
                        top_clients.append({"ip": ip, "label": label, "count": count})
                content["top_clients"] = top_clients

                # Hourly trend data
                content["hourly_queries"] = stats.get("dns_queries", [])
                content["hourly_blocked"] = stats.get("blocked_filtering", [])

                # Upstream performance
                upstreams = []
                for item in (stats.get("top_upstreams_avg_time") or [])[:5]:
                    for upstream, avg_time in item.items():
                        upstreams.append(
                            {
                                "upstream": upstream,
                                "avg_time_ms": round(avg_time * 1000, 2),
                            }
                        )
                content["upstream_performance"] = upstreams

                # Filter status
                filtering = adguard._request("GET", "filtering/status") or {}
                active_filters = [f["name"] for f in filtering.get("filters", []) if f.get("enabled")]
                content["active_filters"] = active_filters
                content["user_rules_count"] = len(filtering.get("user_rules", []))
            except Exception as e:
                logger.debug("Report query failed (dns_summary): %s", e)
                content["error"] = str(e)

    return content
