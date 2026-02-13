"""Code Sentinel Routes - AI-Powered Code Health & Quality Analysis

This module provides local-first code scanning with AI/Ollama integration.
Focuses on Code Health, Issues tracking, and Multi-Agent team analysis.

NOTE: PR/Git functionality is in CodeRabbit module, not here.
"""

from flask import render_template, jsonify, request, session
from flask_login import login_required
from . import code_sentinel_bp
import os
import re
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json
import sys
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

logger = logging.getLogger(__name__)

# Add paths for imports
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

# Import Bridge routing functions for proper team member routing
try:
    from ai_bridge.archie_bridge import route_task_to_station, execute_agent_task, get_available_agent_for_station

    BRIDGE_ROUTING_AVAILABLE = True
except ImportError:
    BRIDGE_ROUTING_AVAILABLE = False
    logger.warning("Bridge routing not available, falling back to direct calls")

# Ollama configuration
OLLAMA_PRIMARY = os.getenv("OLLAMA_PRIMARY", "host.docker.internal:11434")
OLLAMA_SECONDARY = os.getenv("OLLAMA_SECONDARY", "")


def check_ollama_status():
    """Check if Ollama is available and return status"""
    for host in [OLLAMA_PRIMARY, OLLAMA_SECONDARY]:
        try:
            r = requests.get(f"http://{host}/api/tags", timeout=2)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                return {"available": True, "host": host, "models": models[:5], "model_count": len(models)}
        except Exception:
            continue
    return {"available": False, "host": None, "models": [], "model_count": 0}


def basic_static_analysis(code_content, file_path):
    """Perform basic static analysis without AI"""
    issues = []
    lines = code_content.split("\n")
    file_ext = os.path.splitext(file_path)[1].lower()

    # Python-specific checks
    if file_ext == ".py":
        for i, line in enumerate(lines, 1):
            # Security: Hardcoded passwords/secrets
            if re.search(r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']', line, re.I):
                if "getenv" not in line and "environ" not in line:
                    issues.append(
                        {
                            "line": i,
                            "type": "security",
                            "severity": "high",
                            "message": "Potential hardcoded secret detected",
                            "suggestion": "Use environment variables instead",
                        }
                    )

            # Security: SQL injection risk
            if re.search(r'execute\s*\(\s*["\'].*%s|execute\s*\(\s*f["\']', line):
                if "parameterized" not in line.lower():
                    issues.append(
                        {
                            "line": i,
                            "type": "security",
                            "severity": "high",
                            "message": "Potential SQL injection vulnerability",
                            "suggestion": "Use parameterized queries",
                        }
                    )

            # Quality: Bare except
            if re.search(r"except\s*:", line):
                issues.append(
                    {
                        "line": i,
                        "type": "quality",
                        "severity": "medium",
                        "message": "Bare except clause catches all exceptions",
                        "suggestion": "Specify exception type (e.g., except ValueError:)",
                    }
                )

            # Quality: TODO/FIXME comments
            if re.search(r"#\s*(TODO|FIXME|XXX|HACK)", line, re.I):
                issues.append(
                    {
                        "line": i,
                        "type": "quality",
                        "severity": "low",
                        "message": "TODO/FIXME comment found",
                        "suggestion": "Address or track this item",
                    }
                )

            # Style: Line too long
            if len(line) > 120:
                issues.append(
                    {
                        "line": i,
                        "type": "style",
                        "severity": "low",
                        "message": f"Line exceeds 120 characters ({len(line)})",
                        "suggestion": "Break into multiple lines",
                    }
                )

            # Performance: Print statements in production code
            if re.search(r"^\s*print\s*\(", line) and "debug" not in file_path.lower():
                issues.append(
                    {
                        "line": i,
                        "type": "performance",
                        "severity": "low",
                        "message": "Print statement found (use logging instead)",
                        "suggestion": "Replace with logger.info() or logger.debug()",
                    }
                )

    # JavaScript/HTML checks
    elif file_ext in [".js", ".html"]:
        for i, line in enumerate(lines, 1):
            # Security: innerHTML usage
            if "innerHTML" in line and "=" in line:
                issues.append(
                    {
                        "line": i,
                        "type": "security",
                        "severity": "medium",
                        "message": "innerHTML usage may be XSS vulnerable",
                        "suggestion": "Use textContent or sanitize input",
                    }
                )

            # Security: eval usage
            if re.search(r"\beval\s*\(", line):
                issues.append(
                    {
                        "line": i,
                        "type": "security",
                        "severity": "critical",
                        "message": "eval() is dangerous and should be avoided",
                        "suggestion": "Use JSON.parse() or safer alternatives",
                    }
                )

            # Quality: console.log
            if "console.log" in line:
                issues.append(
                    {
                        "line": i,
                        "type": "quality",
                        "severity": "low",
                        "message": "console.log found",
                        "suggestion": "Remove or use proper logging",
                    }
                )

    # Calculate quality score based on issues
    critical_count = len([i for i in issues if i["severity"] == "critical"])
    high_count = len([i for i in issues if i["severity"] == "high"])
    medium_count = len([i for i in issues if i["severity"] == "medium"])
    low_count = len([i for i in issues if i["severity"] == "low"])

    # Scoring: start at 100, deduct based on severity
    score = 100 - (critical_count * 25) - (high_count * 15) - (medium_count * 5) - (low_count * 2)
    score = max(0, min(100, score))  # Clamp between 0-100

    return {
        "quality_score": score,
        "issues": issues,
        "summary": f"Static analysis found {len(issues)} issues" if issues else "No issues found",
        "analysis_type": "static",
    }


# Database connection
def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def init_code_health_tables():
    """Initialize code health tracking tables"""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS code_scans (
                id SERIAL PRIMARY KEY,
                file_path VARCHAR(500) NOT NULL,
                scan_type VARCHAR(50) DEFAULT 'manual',
                issues_found INTEGER DEFAULT 0,
                security_issues INTEGER DEFAULT 0,
                quality_score DECIMAL(5,2),
                scan_result JSONB,
                scanned_by VARCHAR(100),
                scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS code_issues (
                id SERIAL PRIMARY KEY,
                scan_id INTEGER REFERENCES code_scans(id),
                file_path VARCHAR(500) NOT NULL,
                line_number INTEGER,
                issue_type VARCHAR(50),
                severity VARCHAR(20),
                message TEXT,
                suggestion TEXT,
                status VARCHAR(20) DEFAULT 'open',
                proposal_id INTEGER,
                fixed_by VARCHAR(100),
                fixed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS code_fixes (
                id SERIAL PRIMARY KEY,
                issue_id INTEGER REFERENCES code_issues(id),
                file_path VARCHAR(500) NOT NULL,
                fixed_by VARCHAR(100) NOT NULL,
                fix_description TEXT,
                pr_number INTEGER,
                pr_url VARCHAR(500),
                commit_sha VARCHAR(100),
                fixed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_code_scans_file ON code_scans(file_path);
            CREATE INDEX IF NOT EXISTS idx_code_issues_status ON code_issues(status);
            CREATE INDEX IF NOT EXISTS idx_code_fixes_file ON code_fixes(file_path);
        """
        )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error initializing tables: {e}")
        return False
    finally:
        cur.close()
        conn.close()


# Initialize tables on module load
init_code_health_tables()


# ============================================================================
# MAIN ROUTES
# ============================================================================


@code_sentinel_bp.route("/")
def index():
    """Main Code Sentinel dashboard"""
    return render_template("tools/code_sentinel.html")


@code_sentinel_bp.route("/api/status")
def status():
    """Health check for Code Sentinel module"""
    ai_status = check_ollama_status()
    return jsonify(
        {
            "module": "code_sentinel",
            "status": "active",
            "healthy": True,
            "message": "Code Sentinel active - local code scanning with AI",
            "features": {
                "code_health": True,
                "multi_agent_review": True,
                "issue_tracking": True,
                "bridge_routing": BRIDGE_ROUTING_AVAILABLE,
            },
            "ai_status": ai_status,
        }
    )


@code_sentinel_bp.route("/api/ai-status")
def ai_status():
    """Check AI/Ollama availability for code scanning"""
    ollama = check_ollama_status()
    return jsonify(
        {
            "ollama": ollama,
            "archie_bridge": {"available": True, "path": "/mnt/archie_brain/ai_bridge"},
            "analysis_modes": {"ai_powered": ollama["available"], "static_analysis": True},
            "recommended_mode": "ai_powered" if ollama["available"] else "static",
        }
    )


# ============================================================================
# CODE HEALTH ENDPOINTS
# ============================================================================


@code_sentinel_bp.route("/api/health/stats")
def get_health_stats():
    """Get code health statistics"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get scan stats
        cur.execute(
            """
            SELECT
                COUNT(*) as total_scans,
                COUNT(DISTINCT file_path) as files_scanned,
                SUM(issues_found) as total_issues,
                SUM(security_issues) as security_issues,
                AVG(quality_score) as avg_quality_score
            FROM code_scans
        """
        )
        scan_stats = cur.fetchone()

        # Get issue stats
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'open') as open_issues,
                COUNT(*) FILTER (WHERE status = 'fixed') as fixed_issues,
                COUNT(*) FILTER (WHERE severity = 'critical') as critical_issues,
                COUNT(*) FILTER (WHERE severity = 'high') as high_issues,
                COUNT(*) FILTER (WHERE severity = 'medium') as medium_issues,
                COUNT(*) FILTER (WHERE severity = 'low') as low_issues
            FROM code_issues
        """
        )
        issue_stats = cur.fetchone()

        # Get recent fixes
        cur.execute(
            """
            SELECT fixed_by, COUNT(*) as fix_count
            FROM code_fixes
            WHERE fixed_at > NOW() - INTERVAL '30 days'
            GROUP BY fixed_by
            ORDER BY fix_count DESC
            LIMIT 5
        """
        )
        top_fixers = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "scan_stats": {
                    "total_scans": scan_stats["total_scans"] or 0,
                    "files_scanned": scan_stats["files_scanned"] or 0,
                    "total_issues": scan_stats["total_issues"] or 0,
                    "security_issues": scan_stats["security_issues"] or 0,
                    "avg_quality_score": float(scan_stats["avg_quality_score"] or 0),
                },
                "issue_stats": {
                    "open": issue_stats["open_issues"] or 0,
                    "fixed": issue_stats["fixed_issues"] or 0,
                    "critical": issue_stats["critical_issues"] or 0,
                    "high": issue_stats["high_issues"] or 0,
                    "medium": issue_stats["medium_issues"] or 0,
                    "low": issue_stats["low_issues"] or 0,
                },
                "top_fixers": [dict(f) for f in top_fixers],
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@code_sentinel_bp.route("/api/health/scan", methods=["POST"])
def scan_file():
    """Scan a file for code quality and security issues using AI Bridge"""
    data = request.get_json() or {}
    file_path = data.get("file_path")
    full_path_provided = data.get("full_path")

    if not file_path and not full_path_provided:
        return jsonify({"error": "file_path is required"}), 400

    scanned_by = session.get("username", "system")
    user_id = session.get("user_id", 4)
    if not isinstance(user_id, int):
        user_id = 4

    try:
        # Resolve the full path
        if full_path_provided and os.path.exists(full_path_provided):
            full_path = full_path_provided
        elif file_path:
            if file_path.startswith("platform_v2/"):
                full_path = f"/app/{file_path[len('platform_v2/'):]}"
            elif file_path.startswith("ai_bridge/"):
                full_path = f"/mnt/archie_brain/{file_path}"
            else:
                full_path = f"/mnt/archie_brain/{file_path}"
        else:
            return jsonify({"error": "file_path is required"}), 400

        if not os.path.exists(full_path):
            return jsonify({"error": f"File not found: {file_path}"}), 404

        with open(full_path, "r") as f:
            code_content = f.read()

        # STEP 1: Always run static analysis (fast baseline)
        static_result = basic_static_analysis(code_content, file_path)
        analysis_type = "static"

        # STEP 2: Try AI analysis via Bridge routing
        ai_result = None
        agent_used = None
        ollama_status = check_ollama_status()

        if BRIDGE_ROUTING_AVAILABLE:
            try:
                routing = route_task_to_station("code_review", f"Review code in {file_path}")
                agent = routing.get("agent")

                if agent:
                    agent_used = {
                        "id": agent.get("id"),
                        "name": agent.get("name"),
                        "station": routing.get("station"),
                        "model": agent.get("model"),
                    }
                    logger.info(f"Code Sentinel scan routed to {agent.get('name')} at {routing.get('station')} station")

                    ai_content = (
                        code_content[:10000] + "\n... (truncated)" if len(code_content) > 10000 else code_content
                    )

                    task = f"""Analyze this code for issues. Return a JSON object with:
{{
    "quality_score": 0-100,
    "issues": [
        {{
            "line": line_number or null,
            "type": "security|quality|style|performance",
            "severity": "critical|high|medium|low",
            "message": "description of issue",
            "suggestion": "how to fix it"
        }}
    ],
    "summary": "brief summary"
}}

File: {file_path}
```
{ai_content}
```

Only return valid JSON, no other text."""

                    result = execute_agent_task(agent_id=agent["id"], task=task, user_id=user_id, stream=False)

                    if result.get("success"):
                        response_text = result.get("response", "{}")
                        if "```json" in response_text:
                            response_text = response_text.split("```json")[1].split("```")[0]
                        elif "```" in response_text:
                            response_text = response_text.split("```")[1].split("```")[0]

                        ai_result = json.loads(response_text.strip())
                        analysis_type = "ai_powered"
                        logger.info(f"AI analysis completed for {file_path} via {agent.get('name')}")

            except Exception as e:
                logger.warning(f"Bridge routing failed, trying direct: {e}")

        # Fallback: Direct archie_bridge call
        if not ai_result and ollama_status["available"]:
            try:
                from ai_bridge.archie_bridge import archie_bridge

                ai_content = code_content[:10000] + "\n... (truncated)" if len(code_content) > 10000 else code_content

                prompt = f"""Analyze this code for issues. Return a JSON object with:
{{
    "quality_score": 0-100,
    "issues": [
        {{
            "line": line_number or null,
            "type": "security|quality|style|performance",
            "severity": "critical|high|medium|low",
            "message": "description of issue",
            "suggestion": "how to fix it"
        }}
    ],
    "summary": "brief summary"
}}

File: {file_path}
```
{ai_content}
```

Only return valid JSON, no other text."""

                ai_response = archie_bridge(prompt, try_local_first=True)

                response_text = ai_response.get("response", "{}")
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0]
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0]

                ai_result = json.loads(response_text.strip())
                analysis_type = "ai_powered"
                agent_used = {"name": "Direct Ollama", "station": "Fallback"}

            except Exception as e:
                logger.warning(f"AI analysis failed, using static: {e}")

        # STEP 3: Combine results
        if ai_result and ai_result.get("issues"):
            analysis = {
                "quality_score": ai_result.get("quality_score", static_result["quality_score"]),
                "issues": ai_result.get("issues", []),
                "summary": ai_result.get("summary", ""),
                "analysis_type": "ai_powered",
            }
            ai_lines = {i.get("line") for i in analysis["issues"] if i.get("line")}
            for static_issue in static_result.get("issues", []):
                if static_issue.get("line") not in ai_lines:
                    analysis["issues"].append({**static_issue, "source": "static"})
        else:
            analysis = static_result
            analysis["analysis_type"] = "static"
            if ollama_status["available"]:
                analysis["summary"] = "AI parsing failed - showing static analysis"
            else:
                analysis["summary"] = f"Static analysis ({len(static_result['issues'])} issues found)"

        # Store scan results in database
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        issues = analysis.get("issues", [])
        security_issues = len([i for i in issues if i.get("type") == "security"])

        cur.execute(
            """
            INSERT INTO code_scans (file_path, scan_type, issues_found, security_issues,
                                   quality_score, scan_result, scanned_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                file_path,
                "ai_scan",
                len(issues),
                security_issues,
                analysis.get("quality_score", 0),
                json.dumps(analysis),
                scanned_by,
            ),
        )
        scan_id = cur.fetchone()["id"]

        # Store individual issues
        for issue in issues:
            cur.execute(
                """
                INSERT INTO code_issues (scan_id, file_path, line_number, issue_type,
                                        severity, message, suggestion)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    scan_id,
                    file_path,
                    issue.get("line"),
                    issue.get("type", "quality"),
                    issue.get("severity", "medium"),
                    issue.get("message", ""),
                    issue.get("suggestion", ""),
                ),
            )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "scan_id": scan_id,
                "file_path": file_path,
                "quality_score": analysis.get("quality_score", 0),
                "issues_found": len(issues),
                "security_issues": security_issues,
                "issues": issues,
                "summary": analysis.get("summary", ""),
                "analysis_type": analysis.get("analysis_type", "unknown"),
                "ollama_available": ollama_status["available"],
                "bridge_routing": BRIDGE_ROUTING_AVAILABLE,
                "agent_used": agent_used,
                "scanned_by": scanned_by,
                "scanned_at": datetime.now().isoformat(),
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@code_sentinel_bp.route("/api/health/batch-scan", methods=["POST"])
@login_required
def batch_scan_files():
    """Scan multiple files in parallel"""
    data = request.get_json() or {}
    file_paths = data.get("files", [])
    max_workers = min(data.get("max_workers", 4), 8)

    if not file_paths:
        return jsonify({"error": "No files provided"}), 400

    if len(file_paths) > 50:
        return jsonify({"error": "Maximum 50 files per batch"}), 400

    scanned_by = session.get("username", "system")
    results = []
    errors = []

    def scan_single_file(file_path):
        """Scan a single file - worker function"""
        try:
            if file_path.startswith("platform_v2/"):
                full_path = f"/app/{file_path[len('platform_v2/'):]}"
            elif file_path.startswith("ai_bridge/"):
                full_path = f"/mnt/archie_brain/{file_path}"
            else:
                full_path = f"/mnt/archie_brain/{file_path}"

            if not os.path.exists(full_path):
                return {"file_path": file_path, "error": "File not found", "success": False}

            with open(full_path, "r") as f:
                code_content = f.read()

            static_result = basic_static_analysis(code_content, file_path)
            analysis = static_result
            analysis["analysis_type"] = "static"

            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            issues = analysis.get("issues", [])
            security_issues = len([i for i in issues if i.get("type") == "security"])

            cur.execute(
                """
                INSERT INTO code_scans (file_path, scan_type, issues_found, security_issues,
                                       quality_score, scan_result, scanned_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    file_path,
                    "batch_scan",
                    len(issues),
                    security_issues,
                    analysis.get("quality_score", 0),
                    json.dumps(analysis),
                    scanned_by,
                ),
            )
            scan_id = cur.fetchone()["id"]
            conn.commit()
            cur.close()
            conn.close()

            return {
                "file_path": file_path,
                "success": True,
                "scan_id": scan_id,
                "quality_score": analysis.get("quality_score", 0),
                "issues_found": len(issues),
                "security_issues": security_issues,
                "analysis_type": analysis.get("analysis_type"),
            }

        except Exception as e:
            return {"file_path": file_path, "error": str(e), "success": False}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(scan_single_file, fp): fp for fp in file_paths}

        for future in as_completed(future_to_file):
            result = future.result()
            if result.get("success"):
                results.append(result)
            else:
                errors.append(result)

    return jsonify(
        {
            "success": True,
            "total_files": len(file_paths),
            "scanned": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
            "summary": {
                "avg_quality": sum(r.get("quality_score", 0) for r in results) / max(len(results), 1),
                "total_issues": sum(r.get("issues_found", 0) for r in results),
                "security_issues": sum(r.get("security_issues", 0) for r in results),
            },
        }
    )


@code_sentinel_bp.route("/api/health/scans")
def get_scan_history():
    """Get scan history with full results"""
    limit = request.args.get("limit", 20, type=int)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT id, file_path, scan_type, issues_found, security_issues,
                   quality_score, scanned_by, scanned_at, scan_result
            FROM code_scans
            ORDER BY scanned_at DESC
            LIMIT %s
        """,
            (limit,),
        )
        scans = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "scans": [
                    {
                        **dict(s),
                        "scanned_at": s["scanned_at"].isoformat() if s["scanned_at"] else None,
                        "quality_score": float(s["quality_score"]) if s["quality_score"] else None,
                        "scan_result": s["scan_result"] if s["scan_result"] else {},
                    }
                    for s in scans
                ],
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@code_sentinel_bp.route("/api/health/issues")
def get_issues():
    """Get code issues"""
    status = request.args.get("status", "all")
    limit = request.args.get("limit", 50, type=int)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        base_query = """
            SELECT i.*, s.scanned_by, s.scanned_at
            FROM code_issues i
            JOIN code_scans s ON i.scan_id = s.id
        """

        if status == "all":
            cur.execute(
                base_query
                + """
                ORDER BY
                    CASE i.severity
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END,
                    i.created_at DESC
                LIMIT %s
            """,
                (limit,),
            )
        else:
            cur.execute(
                base_query
                + """
                WHERE i.status = %s
                ORDER BY
                    CASE i.severity
                        WHEN 'critical' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'medium' THEN 3
                        ELSE 4
                    END,
                    i.created_at DESC
                LIMIT %s
            """,
                (status, limit),
            )

        issues = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "issues": [
                    {
                        **dict(i),
                        "created_at": i["created_at"].isoformat() if i["created_at"] else None,
                        "fixed_at": i["fixed_at"].isoformat() if i["fixed_at"] else None,
                        "scanned_at": i["scanned_at"].isoformat() if i["scanned_at"] else None,
                    }
                    for i in issues
                ],
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@code_sentinel_bp.route("/api/health/issues/<int:issue_id>/fix", methods=["POST"])
def mark_issue_fixed(issue_id):
    """Mark an issue as fixed"""
    data = request.get_json() or {}
    fixed_by = data.get("fixed_by", session.get("username", "unknown"))
    fix_description = data.get("description", "")

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT file_path FROM code_issues WHERE id = %s", (issue_id,))
        issue = cur.fetchone()
        if not issue:
            return jsonify({"error": "Issue not found"}), 404

        cur.execute(
            """
            UPDATE code_issues
            SET status = 'fixed', fixed_by = %s, fixed_at = NOW()
            WHERE id = %s
        """,
            (fixed_by, issue_id),
        )

        cur.execute(
            """
            INSERT INTO code_fixes (issue_id, file_path, fixed_by, fix_description)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """,
            (issue_id, issue["file_path"], fixed_by, fix_description),
        )

        fix_id = cur.fetchone()["id"]
        conn.commit()

        return jsonify(
            {
                "success": True,
                "fix_id": fix_id,
                "issue_id": issue_id,
                "fixed_by": fixed_by,
                "message": "Issue marked as fixed",
            }
        )

    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@code_sentinel_bp.route("/api/health/fixes")
def get_fixes():
    """Get fix history"""
    limit = request.args.get("limit", 30, type=int)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT f.*, i.issue_type, i.severity, i.message as issue_message
            FROM code_fixes f
            JOIN code_issues i ON f.issue_id = i.id
            ORDER BY f.fixed_at DESC
            LIMIT %s
        """,
            (limit,),
        )
        fixes = cur.fetchall()

        return jsonify(
            {
                "success": True,
                "fixes": [{**dict(f), "fixed_at": f["fixed_at"].isoformat() if f["fixed_at"] else None} for f in fixes],
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@code_sentinel_bp.route("/api/health/files")
def get_file_health():
    """Get health status of files in the codebase"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT DISTINCT ON (file_path)
                file_path, quality_score, issues_found, security_issues,
                scanned_by, scanned_at
            FROM code_scans
            ORDER BY file_path, scanned_at DESC
        """
        )
        files = cur.fetchall()

        cur.execute(
            """
            SELECT file_path, COUNT(*) as open_issues
            FROM code_issues
            WHERE status = 'open'
            GROUP BY file_path
        """
        )
        open_issues = {r["file_path"]: r["open_issues"] for r in cur.fetchall()}

        return jsonify(
            {
                "success": True,
                "files": [
                    {
                        **dict(f),
                        "open_issues": open_issues.get(f["file_path"], 0),
                        "quality_score": float(f["quality_score"]) if f["quality_score"] else None,
                        "scanned_at": f["scanned_at"].isoformat() if f["scanned_at"] else None,
                    }
                    for f in files
                ],
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@code_sentinel_bp.route("/api/health/directory")
def get_directory_files():
    """Get list of files in a directory for scanning"""
    directory = request.args.get("path", "platform_v2")
    extensions = request.args.get("ext", ".py,.js,.html").split(",")

    try:
        path_mapping = {
            "platform_v2": "/app",
            "ai_bridge": "/mnt/archie_brain/ai_bridge",
            "docs": "/mnt/archie_brain/docs",
        }

        base_path = path_mapping.get(directory, f"/mnt/archie_brain/{directory}")

        if not os.path.exists(base_path):
            return jsonify({"error": f"Directory not found: {directory}"}), 404

        files = []
        for root, dirs, filenames in os.walk(base_path):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d != "__pycache__"
                and d != "node_modules"
                and d != "_deprecated"
                and "deprecated" not in d.lower()
            ]

            for filename in filenames:
                if filename == "__init__.py":
                    continue
                if any(filename.endswith(ext) for ext in extensions):
                    full_path = os.path.join(root, filename)
                    if base_path == "/app":
                        rel_path = f"platform_v2/{os.path.relpath(full_path, '/app')}"
                        folder = os.path.dirname(os.path.relpath(full_path, "/app"))
                    else:
                        rel_path = os.path.relpath(full_path, "/mnt/archie_brain")
                        folder = os.path.dirname(rel_path)
                    stat = os.stat(full_path)
                    size = stat.st_size
                    mtime = datetime.fromtimestamp(stat.st_mtime)
                    files.append(
                        {
                            "path": rel_path,
                            "name": filename,
                            "size": size,
                            "full_path": full_path,
                            "extension": os.path.splitext(filename)[1],
                            "folder": folder or "root",
                            "mtime": mtime.isoformat(),
                        }
                    )

        return jsonify(
            {
                "success": True,
                "directory": directory,
                "file_count": len(files),
                "files": sorted(files, key=lambda x: x["path"]),
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# MULTI-AGENT REVIEW SYSTEM
# ============================================================================

# Import node router for dynamic model routing
try:
    sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
    from node_router import get_ollama_url, log_model_request, get_nodes_with_model

    NODE_ROUTING_AVAILABLE = True
    logger.info("Node router loaded for multi-agent reviews")
except ImportError as e:
    NODE_ROUTING_AVAILABLE = False
    logger.warning(f"Node router not available: {e}")

# In-memory store for multi-agent reviews
multi_agent_reviews = {}

# Skill to specialty mapping
REVIEW_SKILL_MAPPING = {
    "security": {
        "skills": ["security", "cybersecurity", "penetration_testing"],
        "focus": ["SQL injection", "XSS", "auth bypass", "secrets exposure", "OWASP top 10"],
        "prompt_prefix": "You are a security expert reviewing code for vulnerabilities. Focus on: ",
    },
    "code_review": {
        "skills": ["code_review", "code_quality", "best_practices"],
        "focus": ["SOLID principles", "DRY violations", "code smells", "naming conventions", "documentation"],
        "prompt_prefix": "You are a senior developer reviewing code quality. Focus on: ",
    },
    "architecture": {
        "skills": ["architecture", "system_design", "api_design"],
        "focus": ["design patterns", "separation of concerns", "modularity", "dependencies", "scalability"],
        "prompt_prefix": "You are a software architect reviewing code structure. Focus on: ",
    },
    "bug_fixing": {
        "skills": ["bug_fixing", "debugging", "testing"],
        "focus": ["edge cases", "error handling", "null checks", "race conditions", "memory leaks"],
        "prompt_prefix": "You are a QA engineer reviewing code for potential bugs. Focus on: ",
    },
}

# Default review agents
REVIEW_AGENTS = {
    "security_expert": {
        "name": "Security Expert",
        "model": "deepseek-coder-v2:16b",
        "specialty": "security",
        "focus": ["SQL injection", "XSS", "auth bypass", "secrets exposure"],
        "prompt_prefix": "You are a security expert. Analyze this code for security vulnerabilities. Focus on: ",
    },
    "code_quality": {
        "name": "Code Quality Reviewer",
        "model": "deepseek-coder-v2:16b",
        "specialty": "code_review",
        "focus": ["SOLID principles", "DRY violations", "code smells", "maintainability"],
        "prompt_prefix": "You are a senior developer reviewing code quality. Focus on: ",
    },
}


def get_review_agents_from_team_management(specialty: str = None, limit: int = 4):
    """Get code review capable agents from Team Management"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if specialty and specialty in REVIEW_SKILL_MAPPING:
            skills = REVIEW_SKILL_MAPPING[specialty]["skills"]
            skill_filter = "AND s.skill_name = ANY(%s)"
            params = [skills, limit]
        else:
            all_skills = []
            for spec in REVIEW_SKILL_MAPPING.values():
                all_skills.extend(spec["skills"])
            skill_filter = "AND s.skill_name = ANY(%s)"
            params = [list(set(all_skills)), limit]

        cur.execute(
            f"""
            SELECT DISTINCT
                a.id,
                a.name,
                a.first_name,
                a.last_name,
                a.model,
                a.system_prompt,
                a.title,
                s.skill_name,
                s.proficiency_level,
                s.skill_category
            FROM agents a
            JOIN agent_skills s ON a.id = s.agent_id
            WHERE a.status = 'active'
              AND a.model IS NOT NULL
              {skill_filter}
            ORDER BY s.proficiency_level DESC, a.name
            LIMIT %s
        """,
            params,
        )

        agents = cur.fetchall()
        cur.close()
        conn.close()

        review_agents = {}
        for agent in agents:
            agent_key = f"agent_{agent['id']}"
            skill = agent["skill_name"]

            specialty_config = None
            for spec_name, spec_data in REVIEW_SKILL_MAPPING.items():
                if skill in spec_data["skills"]:
                    specialty_config = spec_data
                    break

            if not specialty_config:
                specialty_config = REVIEW_SKILL_MAPPING.get("code_review", {})

            review_agents[agent_key] = {
                "id": agent["id"],
                "name": agent["name"] or f"{agent['first_name']} {agent['last_name']}",
                "model": agent["model"],
                "specialty": agent["skill_category"] or "general",
                "skill": skill,
                "proficiency": agent["proficiency_level"],
                "focus": specialty_config.get("focus", []),
                "prompt_prefix": specialty_config.get("prompt_prefix", "You are reviewing code. Focus on: "),
                "system_prompt": agent["system_prompt"],
            }

        return review_agents

    except Exception as e:
        logger.error(f"Error getting review agents from Team Management: {e}")
        return {}


def get_available_nodes_for_review():
    """Get all nodes with their available models for code review"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT
                n.node_id,
                n.node_name,
                n.vpn_ip,
                n.status,
                n.current_load,
                n.bridge_priority,
                n.gpu_available,
                n.gpu_model,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'model_name', m.model_name,
                            'is_available', m.is_available,
                            'avg_response_ms', m.avg_response_ms
                        )
                    ) FILTER (WHERE m.model_name IS NOT NULL),
                    '[]'
                ) as models
            FROM remote_nodes n
            LEFT JOIN node_ollama_models m ON n.node_id = m.node_id AND m.is_available = true
            WHERE n.bridge_enabled = true
              AND n.status = 'online'
              AND n.approval_status = 'approved'
            GROUP BY n.node_id, n.node_name, n.vpn_ip, n.status, n.current_load,
                     n.bridge_priority, n.gpu_available, n.gpu_model
            ORDER BY n.current_load ASC, n.bridge_priority DESC
        """
        )

        nodes = cur.fetchall()
        cur.close()
        conn.close()

        return nodes

    except Exception as e:
        logger.error(f"Error getting available nodes: {e}")
        return []


@code_sentinel_bp.route("/api/multi-agent/nodes")
@login_required
def get_review_nodes():
    """Get available nodes and their models for code review"""
    nodes = get_available_nodes_for_review()

    total_models = set()
    for node in nodes:
        for model in node.get("models", []):
            if model.get("is_available"):
                total_models.add(model["model_name"])

    return jsonify(
        {
            "success": True,
            "nodes": [dict(n) for n in nodes],
            "node_count": len(nodes),
            "total_models": len(total_models),
            "model_list": sorted(list(total_models)),
            "node_routing_available": NODE_ROUTING_AVAILABLE,
        }
    )


@code_sentinel_bp.route("/api/multi-agent/agents")
@login_required
def list_review_agents():
    """Get available review agents from Team Management"""
    specialty = request.args.get("specialty")
    limit = request.args.get("limit", 8, type=int)

    team_agents = get_review_agents_from_team_management(specialty=specialty, limit=limit)

    agents = []
    for agent_key, config in team_agents.items():
        model_available = False
        if NODE_ROUTING_AVAILABLE:
            try:
                nodes = get_nodes_with_model(config["model"])
                model_available = len(nodes) > 0
            except Exception:
                model_available = False

        agents.append(
            {
                "id": agent_key,
                "agent_id": config.get("id"),
                "name": config["name"],
                "model": config["model"],
                "specialty": config["specialty"],
                "skill": config.get("skill"),
                "proficiency": config.get("proficiency", 0),
                "focus_areas": config["focus"],
                "model_available": model_available,
            }
        )

    specialties = list(REVIEW_SKILL_MAPPING.keys())

    return jsonify(
        {
            "success": True,
            "agents": agents,
            "agent_count": len(agents),
            "specialties": specialties,
            "source": "team_management",
            "node_routing": NODE_ROUTING_AVAILABLE,
        }
    )


@code_sentinel_bp.route("/api/multi-agent/review", methods=["POST"])
@login_required
def start_multi_agent_review():
    """Start a multi-agent code review"""
    try:
        data = request.get_json() or {}
        code = data.get("code", "")
        file_path = data.get("file_path", "unknown")
        selected_agents = data.get("agents", list(REVIEW_AGENTS.keys()))
        context = data.get("context", "")

        if not code:
            return jsonify({"success": False, "error": "No code provided"}), 400

        review_id = f"mar_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.urandom(4).hex()}"

        review = {
            "id": review_id,
            "file_path": file_path,
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "agents_selected": selected_agents,
            "agent_reviews": {},
            "consensus": None,
            "final_issues": [],
        }
        multi_agent_reviews[review_id] = review

        # Start async review
        thread = threading.Thread(
            target=_run_multi_agent_review, args=(review_id, code, file_path, selected_agents, context)
        )
        thread.daemon = True
        thread.start()

        return jsonify(
            {
                "success": True,
                "review_id": review_id,
                "message": f"Multi-agent review started with {len(selected_agents)} agents",
            }
        )

    except Exception as e:
        logger.error(f"Multi-agent review error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@code_sentinel_bp.route("/api/multi-agent/review/<review_id>")
@login_required
def get_multi_agent_review(review_id):
    """Get status and results of a multi-agent review"""
    if review_id in multi_agent_reviews:
        return jsonify({"success": True, "review": multi_agent_reviews[review_id]})
    return jsonify({"success": False, "error": "Review not found"}), 404


def _run_multi_agent_review(review_id: str, code: str, file_path: str, agents: list, context: str):
    """Execute multi-agent review with parallel agent execution"""
    review = multi_agent_reviews[review_id]

    try:
        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from archie_bridge import archie_bridge

        team_agents = get_review_agents_from_team_management(limit=10)
        all_issues = []
        review_lock = threading.Lock()

        def run_single_agent(agent_key):
            """Run a single agent's review"""
            if agent_key in team_agents:
                agent_config = team_agents[agent_key]
            elif agent_key in REVIEW_AGENTS:
                agent_config = REVIEW_AGENTS[agent_key]
            else:
                matching = [a for a in team_agents.values() if str(a.get("id")) == agent_key.replace("agent_", "")]
                if matching:
                    agent_config = matching[0]
                else:
                    return None

            model = agent_config.get("model", "deepseek-coder-v2:16b")
            agent_name = agent_config.get("name", "Unknown Agent")

            prompt_prefix = agent_config.get("prompt_prefix", "You are reviewing code. Focus on: ")
            focus_areas = agent_config.get("focus", [])

            prompt = f"""{prompt_prefix}
{', '.join(focus_areas)}

Analyze this code and return a JSON object with:
{{
    "issues": [
        {{
            "line": line_number or null,
            "type": "security|quality|style|performance",
            "severity": "critical|high|medium|low",
            "message": "description",
            "suggestion": "fix recommendation"
        }}
    ],
    "summary": "brief summary",
    "quality_score": 0-100
}}

{context}

File: {file_path}
```
{code[:8000]}
```

Return only valid JSON."""

            try:
                response = archie_bridge(prompt, try_local_first=True, model=model)
                response_text = response.get("response", "{}")

                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0]
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0]

                result = json.loads(response_text.strip())

                with review_lock:
                    review["agent_reviews"][agent_key] = {
                        "agent_name": agent_name,
                        "model": model,
                        "issues": result.get("issues", []),
                        "summary": result.get("summary", ""),
                        "quality_score": result.get("quality_score", 0),
                        "completed_at": datetime.now().isoformat(),
                    }
                    for issue in result.get("issues", []):
                        all_issues.append({**issue, "found_by": agent_name})

                return result

            except Exception as e:
                logger.error(f"Agent {agent_name} review failed: {e}")
                with review_lock:
                    review["agent_reviews"][agent_key] = {
                        "agent_name": agent_name,
                        "error": str(e),
                        "completed_at": datetime.now().isoformat(),
                    }
                return None

        # Run agents in parallel
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(run_single_agent, a): a for a in agents}
            for future in as_completed(futures):
                future.result()

        # Build consensus
        review["final_issues"] = all_issues
        review["consensus"] = {
            "total_issues": len(all_issues),
            "by_severity": {
                "critical": len([i for i in all_issues if i.get("severity") == "critical"]),
                "high": len([i for i in all_issues if i.get("severity") == "high"]),
                "medium": len([i for i in all_issues if i.get("severity") == "medium"]),
                "low": len([i for i in all_issues if i.get("severity") == "low"]),
            },
            "agents_completed": len([r for r in review["agent_reviews"].values() if "error" not in r]),
        }
        review["status"] = "completed"
        review["completed_at"] = datetime.now().isoformat()

    except Exception as e:
        logger.error(f"Multi-agent review failed: {e}")
        review["status"] = "failed"
        review["error"] = str(e)
