"""GitHub Insights Routes -- Analysis, dependencies, stats

Split from github_routes.py. Handles:
- GitHub auth status and rate limits
- Dependency scanning and vulnerability detection
- Dependency reports and upgrade suggestions
- GitHub-specific stats and embedding coverage
"""

import base64
import json
import logging
import os

import requests
from psycopg2.extras import RealDictCursor
from flask import jsonify, request
from flask_login import login_required

from .github_routes import (
    _get_db,
    _get_github_headers,
    _store_dependency_scan,
)

logger = logging.getLogger(__name__)


def register_github_insights_routes(bp, admin_required):
    """Register analysis and intelligence routes on the consciousness blueprint."""

    # ==================================================================
    # AUTH STATUS
    # ==================================================================

    @bp.route("/github/auth-status", methods=["GET"])
    @login_required
    @admin_required
    def github_auth_status():
        """Check GitHub token validity and rate limit status."""
        headers, has_token = _get_github_headers()
        if not has_token:
            return jsonify(
                {
                    "success": True,
                    "authenticated": False,
                    "rate_limit": 60,
                    "rate_remaining": None,
                    "message": "No token configured — 60 requests/hour limit",
                }
            )
        try:
            resp = requests.get("https://api.github.com/rate_limit", headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                core = data.get("resources", {}).get("core", {})
                return jsonify(
                    {
                        "success": True,
                        "authenticated": True,
                        "rate_limit": core.get("limit", 5000),
                        "rate_remaining": core.get("remaining", 0),
                        "rate_reset": core.get("reset", 0),
                        "message": f"Authenticated — {core.get('remaining', 0)}/{core.get('limit', 5000)} requests remaining",
                    }
                )
            return jsonify(
                {
                    "success": True,
                    "authenticated": False,
                    "message": f"Token invalid (HTTP {resp.status_code})",
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    # ==================================================================
    # DEPENDENCY SCANNING
    # ==================================================================

    @bp.route("/github/scan-dependencies", methods=["POST"])
    @login_required
    @admin_required
    def github_scan_dependencies():
        """Scan GitHub repos for dependency updates and vulnerabilities."""
        from .dependency_scanner import DependencyScanner

        data = request.get_json() or {}
        repo_id = data.get("repo_id")
        include_platform = data.get("include_platform", True)

        # Load GitHub token from env or file
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            try:
                with open("/mnt/archie_brain/secrets/api/github_token.txt", "r") as f:
                    github_token = f.read().strip()
            except FileNotFoundError:
                pass

        scanner = DependencyScanner(github_token=github_token)
        results_summary = {
            "scans_performed": 0,
            "entries_created": 0,
            "total_updates": 0,
            "total_vulnerabilities": 0,
            "critical_count": 0,
            "scan_details": [],
        }

        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Get repos to scan
            if repo_id:
                cur.execute(
                    "SELECT id, repo_name FROM github_repositories WHERE id = %s",
                    (repo_id,),
                )
            else:
                cur.execute("SELECT id, repo_name FROM github_repositories WHERE status IN ('cloned', 'indexed')")
            repos = cur.fetchall()

            dep_files = ["package.json", "requirements.txt"]

            for repo in repos:
                repo_name = repo["repo_name"]
                # repo_name is already in owner/repo format
                owner_repo = repo_name

                headers = {}
                if github_token:
                    headers["Authorization"] = f"Bearer {github_token}"
                    headers["Accept"] = "application/vnd.github.v3+json"

                for dep_file in dep_files:
                    try:
                        resp = requests.get(
                            f"https://api.github.com/repos/{owner_repo}/contents/{dep_file}",
                            headers=headers,
                            timeout=10,
                        )
                        if resp.status_code != 200:
                            continue

                        file_data = resp.json()
                        content = base64.b64decode(file_data.get("content", "")).decode("utf-8")

                        scan = scanner.scan_dependency_file(content, dep_file, owner_repo)
                        cur.execute("SAVEPOINT dep_scan")
                        stored = _store_dependency_scan(cur, scan)
                        cur.execute("RELEASE SAVEPOINT dep_scan")

                        results_summary["scans_performed"] += 1
                        results_summary["entries_created"] += stored
                        results_summary["total_updates"] += scan.get("updates_available", 0)
                        results_summary["total_vulnerabilities"] += scan.get("vulnerabilities_found", 0)
                        results_summary["critical_count"] += scan.get("critical_count", 0)
                        results_summary["scan_details"].append(
                            {
                                "source": owner_repo,
                                "file": dep_file,
                                "packages": scan.get("packages_scanned", 0),
                                "updates": scan.get("updates_available", 0),
                                "vulnerabilities": scan.get("vulnerabilities_found", 0),
                            }
                        )
                    except Exception as e:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT dep_scan")
                        except Exception:
                            conn.rollback()
                        logger.warning(f"Failed to scan {owner_repo}/{dep_file}: {e}")

            # Scan local platform requirements.txt if requested
            if include_platform:
                try:
                    local_path = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        "requirements.txt",
                    )
                    with open(local_path, "r") as f:
                        content = f.read()

                    scan = scanner.scan_dependency_file(content, "requirements.txt", "local/platform_v2")
                    cur.execute("SAVEPOINT local_scan")
                    stored = _store_dependency_scan(cur, scan)
                    cur.execute("RELEASE SAVEPOINT local_scan")

                    results_summary["scans_performed"] += 1
                    results_summary["entries_created"] += stored
                    results_summary["total_updates"] += scan.get("updates_available", 0)
                    results_summary["total_vulnerabilities"] += scan.get("vulnerabilities_found", 0)
                    results_summary["critical_count"] += scan.get("critical_count", 0)
                    results_summary["scan_details"].append(
                        {
                            "source": "local/platform_v2",
                            "file": "requirements.txt",
                            "packages": scan.get("packages_scanned", 0),
                            "updates": scan.get("updates_available", 0),
                            "vulnerabilities": scan.get("vulnerabilities_found", 0),
                        }
                    )
                except Exception as e:
                    try:
                        cur.execute("ROLLBACK TO SAVEPOINT local_scan")
                    except Exception:
                        conn.rollback()
                    logger.warning(f"Failed to scan local requirements.txt: {e}")

            conn.commit()
            return jsonify({"success": True, **results_summary})

        except Exception as e:
            logger.error(f"Dependency scan failed: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # DEPENDENCY REPORTS & SUGGESTIONS
    # ==================================================================

    @bp.route("/github/dependency-report", methods=["GET"])
    @login_required
    @admin_required
    def github_dependency_report():
        """Get summary report of dependency scan results."""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    COUNT(*) as total_suggestions,
                    COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'critical') as critical_count,
                    COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'high') as high_count,
                    COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'medium') as medium_count,
                    COUNT(*) FILTER (WHERE memory_metadata->>'severity' = 'low') as low_count,
                    COUNT(*) FILTER (WHERE (memory_metadata->>'has_update')::boolean = true) as updates_available,
                    COUNT(*) FILTER (WHERE (memory_metadata->>'vulnerability_count')::int > 0) as with_vulnerabilities,
                    MAX(created_at) as last_scan
                FROM knowledge_base
                WHERE knowledge_type = 'upgrade_suggestion'
            """
            )
            summary = dict(cur.fetchone())

            # Group by ecosystem
            cur.execute(
                """
                SELECT
                    memory_metadata->>'ecosystem' as ecosystem,
                    COUNT(*) as count
                FROM knowledge_base
                WHERE knowledge_type = 'upgrade_suggestion'
                GROUP BY memory_metadata->>'ecosystem'
            """
            )
            by_ecosystem = [dict(r) for r in cur.fetchall()]

            # Group by source
            cur.execute(
                """
                SELECT
                    memory_metadata->>'scan_source' as source,
                    COUNT(*) as count,
                    COUNT(*) FILTER (WHERE memory_metadata->>'severity' IN ('critical', 'high')) as urgent
                FROM knowledge_base
                WHERE knowledge_type = 'upgrade_suggestion'
                GROUP BY memory_metadata->>'scan_source'
                ORDER BY urgent DESC
            """
            )
            by_source = [dict(r) for r in cur.fetchall()]
            return jsonify(
                {
                    "success": True,
                    "summary": summary,
                    "by_ecosystem": by_ecosystem,
                    "by_source": by_source,
                }
            )

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    @bp.route("/github/upgrade-suggestions", methods=["GET"])
    @login_required
    @admin_required
    def github_upgrade_suggestions():
        """List upgrade suggestions with optional filters."""
        severity = request.args.get("severity")
        ecosystem = request.args.get("ecosystem")
        source = request.args.get("source")
        limit = request.args.get("limit", 50, type=int)

        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            conditions = ["knowledge_type = 'upgrade_suggestion'"]
            params = []

            if severity:
                conditions.append("memory_metadata->>'severity' = %s")
                params.append(severity)
            if ecosystem:
                conditions.append("memory_metadata->>'ecosystem' = %s")
                params.append(ecosystem)
            if source:
                conditions.append("memory_metadata->>'scan_source' = %s")
                params.append(source)

            where = " AND ".join(conditions)
            params.append(limit)

            cur.execute(
                f"""SELECT id, title, content, importance_score, memory_metadata, created_at
                    FROM knowledge_base
                    WHERE {where}
                    ORDER BY importance_score DESC, created_at DESC
                    LIMIT %s""",
                params,
            )
            suggestions = []
            for row in cur.fetchall():
                r = dict(row)
                if isinstance(r.get("memory_metadata"), str):
                    r["memory_metadata"] = json.loads(r["memory_metadata"])
                suggestions.append(r)
            return jsonify({"success": True, "suggestions": suggestions, "count": len(suggestions)})

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:

            cur.close()

            conn.close()

    # ==================================================================
    # GITHUB-SPECIFIC STATS
    # ==================================================================

    @bp.route("/github/stats")
    @login_required
    @admin_required
    def github_stats():
        """GitHub-specific file counts and embedding coverage."""
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT
                    COUNT(*) as total_files,
                    SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END) as embedded_files
                FROM knowledge_base
                WHERE knowledge_type = 'github_file'
                """
            )
            row = cur.fetchone()
            total = row["total_files"] or 0
            embedded = row["embedded_files"] or 0
            pct = round((embedded / total) * 100) if total > 0 else 0

            # Per-repo breakdown for verification
            cur.execute(
                """
                SELECT r.id, r.repo_name, r.indexed_files as expected,
                       COUNT(kb.id) as actual,
                       SUM(CASE WHEN kb.embedding IS NOT NULL THEN 1 ELSE 0 END) as embedded
                FROM github_repositories r
                LEFT JOIN knowledge_base kb ON kb.knowledge_type = 'github_file'
                    AND kb.memory_metadata->>'repo' = r.repo_name
                GROUP BY r.id, r.repo_name, r.indexed_files
                ORDER BY r.repo_name
                """
            )
            repos = [dict(r) for r in cur.fetchall()]
            mismatches = [r for r in repos if (r["expected"] or 0) != (r["actual"] or 0)]

            # Freshness: oldest and newest indexed_at
            cur.execute(
                """SELECT min(indexed_at) as oldest, max(indexed_at) as newest,
                          count(*) FILTER (WHERE indexed_at IS NULL
                              OR indexed_at < NOW() - INTERVAL '7 days') as stale_count,
                          count(*) as total_repos
                   FROM github_repositories"""
            )
            freshness = cur.fetchone()

            return jsonify(
                success=True,
                total_files=total,
                embedded_files=embedded,
                embed_pct=pct,
                repos=repos,
                mismatches=mismatches,
                freshness={
                    "oldest_indexed": freshness["oldest"].isoformat() if freshness["oldest"] else None,
                    "newest_indexed": freshness["newest"].isoformat() if freshness["newest"] else None,
                    "stale_repos": freshness["stale_count"],
                    "total_repos": freshness["total_repos"],
                },
            )
        except Exception as e:
            logger.error(f"GitHub stats error: {e}")
            return jsonify(success=False, error=str(e)), 500
        finally:

            cur.close()

            conn.close()
