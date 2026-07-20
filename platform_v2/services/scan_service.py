"""Scan Service — Code scanning, analysis, and multi-agent review.

Migrated from tools/code_sentinel/routes.py (Project #103, Phase 1).
All business logic lives here; route files are thin HTTP wrappers.
"""

import json
import logging
import os
from database import _get_db_password
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import psycopg2
import requests
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bridge dispatcher (all AI work routes through here)
# ---------------------------------------------------------------------------
try:
    from tools.department_hq.services.department_dispatcher import get_dispatcher

    _dispatcher = get_dispatcher()
    BRIDGE_ROUTING_AVAILABLE = True
except Exception:
    _dispatcher = None
    BRIDGE_ROUTING_AVAILABLE = False

# ---------------------------------------------------------------------------
# Node router (optional — for multi-agent distributed review)
# ---------------------------------------------------------------------------
try:
    from ai_bridge.node_router import get_nodes_with_model

    NODE_ROUTING_AVAILABLE = True
except ImportError:
    NODE_ROUTING_AVAILABLE = False

    def get_nodes_with_model(_model):
        return []


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OLLAMA_PRIMARY = os.getenv("OLLAMA_PRIMARY", "host.docker.internal:11434")
OLLAMA_SECONDARY = os.getenv("OLLAMA_SECONDARY", "")

# In-memory store for multi-agent reviews (ephemeral, cleared on restart)
_multi_agent_reviews: dict = {}

# Skill -> specialty mapping for multi-agent reviews
REVIEW_SKILL_MAPPING = {
    "security": {
        "skills": ["security", "cybersecurity", "penetration_testing"],
        "focus": [
            "SQL injection",
            "XSS",
            "auth bypass",
            "secrets exposure",
            "OWASP top 10",
        ],
        "prompt_prefix": "You are a security expert reviewing code for vulnerabilities. Focus on: ",
    },
    "code_review": {
        "skills": ["code_review", "code_quality", "best_practices"],
        "focus": [
            "SOLID principles",
            "DRY violations",
            "code smells",
            "naming conventions",
            "documentation",
        ],
        "prompt_prefix": "You are a senior developer reviewing code quality. Focus on: ",
    },
    "architecture": {
        "skills": ["architecture", "system_design", "api_design"],
        "focus": [
            "design patterns",
            "separation of concerns",
            "modularity",
            "dependencies",
            "scalability",
        ],
        "prompt_prefix": "You are a software architect reviewing code structure. Focus on: ",
    },
    "bug_fixing": {
        "skills": ["bug_fixing", "debugging", "testing"],
        "focus": [
            "edge cases",
            "error handling",
            "null checks",
            "race conditions",
            "memory leaks",
        ],
        "prompt_prefix": "You are a QA engineer reviewing code for potential bugs. Focus on: ",
    },
}

# Fallback review agents (used when team management agents unavailable)
FALLBACK_REVIEW_AGENTS = {
    "security_expert": {
        "name": "Security Expert",
        "specialty": "security",
        "focus": ["SQL injection", "XSS", "auth bypass", "secrets exposure"],
        "prompt_prefix": "You are a security expert. Analyze this code for security vulnerabilities. Focus on: ",
    },
    "code_quality": {
        "name": "Code Quality Reviewer",
        "specialty": "code_review",
        "focus": [
            "SOLID principles",
            "DRY violations",
            "code smells",
            "maintainability",
        ],
        "prompt_prefix": "You are a senior developer reviewing code quality. Focus on: ",
    },
}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def _get_db():
    """Get database connection."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", 5432),
        dbname=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def init_tables():
    """Create code health tables if they don't exist."""
    conn = _get_db()
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


# Ensure tables exist on import
init_tables()


# ===================================================================
# CORE ANALYSIS
# ===================================================================


def check_ai_status():
    """Check Ollama/Bridge availability and return status dict."""
    for host in [OLLAMA_PRIMARY, OLLAMA_SECONDARY]:
        if not host:
            continue
        try:
            r = requests.get(f"http://{host}/api/tags", timeout=2)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                return {
                    "available": True,
                    "host": host,
                    "models": models[:5],
                    "model_count": len(models),
                }
        except Exception:
            continue
    return {"available": False, "host": None, "models": [], "model_count": 0}


def static_analysis(code_content, file_path):
    """Regex-based static analysis (Python, JS, HTML). No AI required.

    Returns dict with quality_score (0-100), issues list, summary, analysis_type.
    """
    issues = []
    lines = code_content.split("\n")
    file_ext = os.path.splitext(file_path)[1].lower()

    if file_ext == ".py":
        for i, line in enumerate(lines, 1):
            # Security: Hardcoded passwords/secrets
            if re.search(
                r'(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']',
                line,
                re.I,
            ):
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

    elif file_ext in [".js", ".html"]:
        for i, line in enumerate(lines, 1):
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
            # Security: dangerous code execution patterns
            if re.search(r"\beval\s*\(", line):
                issues.append(
                    {
                        "line": i,
                        "type": "security",
                        "severity": "critical",
                        "message": "Dangerous code execution pattern detected",
                        "suggestion": "Use JSON.parse() or safer alternatives",
                    }
                )
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

    # Scoring
    critical = len([i for i in issues if i["severity"] == "critical"])
    high = len([i for i in issues if i["severity"] == "high"])
    medium = len([i for i in issues if i["severity"] == "medium"])
    low = len([i for i in issues if i["severity"] == "low"])
    score = max(0, min(100, 100 - (critical * 25) - (high * 15) - (medium * 5) - (low * 2)))

    return {
        "quality_score": score,
        "issues": issues,
        "summary": (f"Static analysis found {len(issues)} issues" if issues else "No issues found"),
        "analysis_type": "static",
    }


# ===================================================================
# FILE PATH HELPERS
# ===================================================================

_PATH_MAP = {
    "platform_v2": "/app",
    "ai_bridge": "/mnt/archie_brain/ai_bridge",
    "docs": "/mnt/archie_brain/docs",
}


def _resolve_path(file_path=None, full_path=None):
    """Resolve relative file_path or absolute full_path to an actual filesystem path."""
    if full_path and os.path.exists(full_path):
        return full_path
    if not file_path:
        return None
    if file_path.startswith("platform_v2/"):
        return f"/app/{file_path[len('platform_v2/'):]}"
    elif file_path.startswith("ai_bridge/"):
        return f"/mnt/archie_brain/{file_path}"
    return f"/mnt/archie_brain/{file_path}"


# ===================================================================
# SCAN OPERATIONS
# ===================================================================


def scan_file(file_path, full_path=None, scanned_by="system", user_id=4, job_id=None, prefer_agent=None):
    """Scan a single file with AI + static analysis.

    Returns dict with scan_id, quality_score, issues, analysis_type, agent_used.
    """
    resolved = _resolve_path(file_path, full_path)
    if not resolved or not os.path.exists(resolved):
        return {"success": False, "error": f"File not found: {file_path}"}

    with open(resolved, "r") as f:
        code_content = f.read()

    # Step 1: Static analysis (always runs)
    static_result = static_analysis(code_content, file_path)
    ai_result = None
    agent_used = None

    # Step 2: AI analysis via Bridge dispatcher
    if BRIDGE_ROUTING_AVAILABLE and _dispatcher:
        try:
            ai_content = code_content[:10000]
            if len(code_content) > 10000:
                ai_content += "\n... (truncated, " + str(len(code_content)) + " chars total)"

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

            result = _dispatcher.request_work(
                capability="code_review",
                prompt=prompt,
                module_id="repair_bay",
                json_mode=True,
                user_id=user_id,
                timeout=120,
                job_id=job_id,
                prefer_agent=prefer_agent,
            )

            # Always capture agent info from Bridge, even if AI fails
            # Resolve display name from DB (agents use code names internally)
            agent_display = result.agent_name
            agent_title = None
            try:
                _conn = _get_db()
                _cur = _conn.cursor(cursor_factory=RealDictCursor)
                _cur.execute(
                    "SELECT display_name, first_name, last_name, title FROM agents WHERE name = %s",
                    (result.agent_name,),
                )
                _row = _cur.fetchone()
                if _row:
                    if _row["first_name"] and _row["last_name"]:
                        agent_display = f"{_row['first_name']} {_row['last_name']}"
                    elif _row["display_name"]:
                        agent_display = _row["display_name"]
                    agent_title = _row.get("title")
                _cur.close()
                _conn.close()
            except Exception:
                pass

            agent_used = {
                "name": agent_display,
                "code_name": result.agent_name,
                "station": result.station_code,
                "model": result.model_used,
                "title": agent_title,
            }

            if result.success:
                response_text = result.response
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0]
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0]

                ai_result = json.loads(response_text.strip())
                logger.info(f"AI analysis completed for {file_path} via {result.agent_name} ({result.model_used})")
            else:
                logger.warning(f"Dispatcher returned failure for {file_path}: {result.error}")

        except json.JSONDecodeError as e:
            logger.warning(f"AI returned invalid JSON for {file_path}: {e}")
        except Exception as e:
            logger.warning(f"AI analysis failed for {file_path}: {e}")

    # Step 3: Merge results
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
        analysis["summary"] = f"Static analysis — {len(static_result['issues'])} issues found"

    # Step 4: Store in database
    # Include agent info in the stored result so reports can show it later
    if agent_used:
        analysis["agent_used"] = agent_used

    conn = None
    cur = None
    try:
        conn = _get_db()
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

        # Pipeline hook: auto-create proposals for critical/high issues
        try:
            from services.scan_pipeline import process_scan_results

            process_scan_results(scan_id, issues, file_path)
        except Exception as pipeline_err:
            logger.warning(f"Scan pipeline hook failed: {pipeline_err}")

        return {
            "success": True,
            "scan_id": scan_id,
            "file_path": file_path,
            "quality_score": analysis.get("quality_score", 0),
            "issues_found": len(issues),
            "security_issues": security_issues,
            "issues": issues,
            "summary": analysis.get("summary", ""),
            "analysis_type": analysis.get("analysis_type", "unknown"),
            "bridge_routing": BRIDGE_ROUTING_AVAILABLE,
            "agent_used": agent_used,
            "scanned_by": scanned_by,
            "scanned_at": datetime.now().isoformat(),
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def batch_scan(file_paths, scanned_by="system", user_id=4):
    """Start a batch scan as a tracked Bridge job (background thread).

    Creates a real Bridge job so it shows at the ENGINEERING station with
    agent assignment, progress bar, and working badges. Returns the job_id
    immediately; frontend polls Bridge for progress.

    Returns dict with job_id on success.
    """
    if not file_paths:
        return {"success": False, "error": "No files provided"}
    if len(file_paths) > 50:
        return {"success": False, "error": "Maximum 50 files per batch"}

    # Auto-recover: mark stuck code_scan jobs as failed (platform restarts leave them 'running')
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (_, cur):
            cur.execute(
                """UPDATE bridge_jobs SET status='failed', error_message='Abandoned — platform restarted'
                   WHERE job_type='code_scan' AND module_source='repair_bay'
                   AND status='running' AND created_at < NOW() - INTERVAL '10 minutes'"""
            )
    except Exception:
        pass

    # Create a Bridge job for tracking
    if not BRIDGE_ROUTING_AVAILABLE or not _dispatcher:
        return {"success": False, "error": "Bridge dispatcher not available"}

    job_id = _dispatcher.create_job(
        job_type="code_scan",
        module_source="repair_bay",
        description=f"Code scan: {len(file_paths)} files",
        total_steps=len(file_paths),
        capability="code_review",
        metadata={"scanned_by": scanned_by, "file_count": len(file_paths)},
    )

    if job_id is None:
        # Duplicate guard triggered — a scan is already running
        return {
            "success": False,
            "duplicate": True,
            "error": "A scan job is already running — please wait for it to complete",
        }

    # Run scan in background thread
    thread = threading.Thread(
        target=_run_batch_scan_job,
        args=(job_id, file_paths, scanned_by, user_id),
        daemon=True,
    )
    thread.start()

    return {
        "success": True,
        "job_id": job_id,
        "message": f"Scan job #{job_id} started for {len(file_paths)} files",
    }


def _run_batch_scan_job(job_id, file_paths, scanned_by, user_id):
    """Background thread: scan files sequentially, updating Bridge job progress."""
    completed = 0
    failed = 0

    # Look up assigned agent for batch consistency — every file in the
    # batch should be dispatched to the same agent.
    prefer_agent = None
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT agent_name FROM bridge_jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
        if row:
            prefer_agent = row[0]
        cur.close()
        conn.close()
    except Exception:
        pass

    for fp in file_paths:
        try:
            result = scan_file(
                file_path=fp,
                scanned_by=scanned_by,
                user_id=user_id,
                job_id=job_id,
                prefer_agent=prefer_agent,
            )
            if result.get("success"):
                completed += 1
            else:
                failed += 1
                logger.warning(f"Batch scan file failed: {fp}: {result.get('error')}")
        except Exception as e:
            failed += 1
            logger.warning(f"Batch scan file exception: {fp}: {e}")

        # Update Bridge job progress after each file
        try:
            _dispatcher.update_job_progress(
                job_id=job_id,
                completed_steps=completed,
                failed_steps=failed,
            )
        except Exception as ue:
            logger.warning(f"Failed to update job progress: {ue}")

    # Mark job complete
    try:
        _dispatcher.complete_job(job_id)
    except Exception as ce:
        logger.warning(f"Failed to complete job: {ce}")

    logger.info(f"Batch scan job #{job_id} complete: {completed}/{len(file_paths)} " f"scanned, {failed} failed")


# ===================================================================
# QUERY OPERATIONS
# ===================================================================


def get_stats():
    """Get scan/issue/fixer statistics."""
    conn = _get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT COUNT(*) as total_scans,
                   COUNT(DISTINCT file_path) as files_scanned,
                   SUM(issues_found) as total_issues,
                   SUM(security_issues) as security_issues,
                   AVG(quality_score) as avg_quality_score
            FROM code_scans
        """
        )
        scan_stats = cur.fetchone()

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

        return {
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
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


def get_history(limit=20):
    """Get recent scan history."""
    conn = _get_db()
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
        return {
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
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


def get_file_report(file_path):
    """Get the latest scan report for a specific file, including full issues list."""
    conn = _get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT id, file_path, quality_score, scan_result, scanned_by, scanned_at
            FROM code_scans
            WHERE file_path = %s
            ORDER BY scanned_at DESC
            LIMIT 1
        """,
            (file_path,),
        )
        scan = cur.fetchone()
        if not scan:
            return {"success": False, "error": "No scan found for this file"}

        result = scan["scan_result"] or {}
        return {
            "success": True,
            "file_path": scan["file_path"],
            "quality_score": float(scan["quality_score"]) if scan["quality_score"] else 0,
            "issues": result.get("issues", []),
            "summary": result.get("summary", ""),
            "analysis_type": result.get("analysis_type", "static"),
            "agent_used": result.get("agent_used"),
            "scanned_by": scan["scanned_by"],
            "scanned_at": scan["scanned_at"].isoformat() if scan["scanned_at"] else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Auto-fix scope for `code_issues` (#5000)
# ---------------------------------------------------------------------------
# The platform owns the definition of "safe to hand to an automated fixer" —
# this is the `code_issues` counterpart to audit_pipeline's
# _AUTO_FIX_EXCLUDED_ISSUE_CODES (which covers audit PROPOSALS; the two tables
# use different taxonomies, so the lists cannot be shared literally).
#
# Why each entry is here (measured 2026-07-19 against 2,230 open issues):
#
#  * SQL injection — 275 of the 286 open `security/high` findings (96%). The
#    A.R.C.H.I.E. Engine selects the HIGHEST-SEVERITY in-scope issue, so without
#    this filter ~96% of its 6-hourly build cycles draw this one class. It is
#    the same class audit_pipeline already refuses to auto-fix: generated fixes
#    were 100% garbage (KB mistake #282665). Detector also over-flags.
#  * Hardcoded secret in a TEST file — verified false-positive class. Issue
#    #7257 flagged `gw.bot_token = "$TELEGRAM_BOT_TOKEN"`, a literal placeholder
#    in a fixture. There is nothing to fix, and the "suggested" fix (use env
#    vars) would BREAK the test. Confirmed live: the engine burned a build slot
#    and returned "nothing to commit, working tree clean".
#
# These stay visible in the Repair Bay UI and every existing caller — the filter
# is OPT-IN (auto_fixable=True) and only automated fixers should pass it.
# Excluding here does NOT mean "ignore": it means "a human reads this one".
_AUTO_FIX_EXCLUDED_MESSAGE_LIKE = ("%SQL injection%",)  # over-flagging + fix-gen produces garbage (KB #282665)
# (message LIKE, file_path LIKE) — excluded only in that file context.
_AUTO_FIX_EXCLUDED_IN_PATH = (("%hardcoded secret%", "%test%"),)


def _like_prefix(prefix: str) -> str:
    """Turn a path prefix into a LIKE pattern, escaping LIKE metacharacters.

    Critical: platform paths contain UNDERSCORES ("platform_v2", "media_studio")
    and `_` is a single-character LIKE wildcard. Unescaped, "platform_v2/" would
    also match "platformXv2/". Escape \\, % and _ and pair with ESCAPE '\\'.
    """
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def get_issues(status="all", limit=50, auto_fixable=False, path_prefixes=None):
    """Get code issues with optional status filter.

    auto_fixable=True additionally drops classes that are unsafe or pointless to
    hand to an automated fixer (see _AUTO_FIX_EXCLUDED_* above). Default False —
    every existing caller is unaffected.

    path_prefixes: optional iterable of path prefixes; only issues whose
    file_path starts with one of them are returned (#5002). This is a SERVER-SIDE
    scope filter for automated consumers that can only act on part of the tree.

    Why it exists: the A.R.C.H.I.E. Engine may only touch the Applications/Concepts
    modules (archie_engine/scope_guard.py PLATFORM_SCOPE). It previously fetched a
    severity-ordered window and filtered by path client-side — but measured
    2026-07-19, its first in-scope issue ranked **744** while the fetch limit was
    200, so it could never reach its own work and every cycle no-opped. Filtering
    here means the caller gets in-scope rows directly instead of paging the whole
    queue to find a dozen.

    SECURITY NOTE: this only ever NARROWS the result set — it cannot grant access.
    Write access remains gated by scope_guard on the engine side. The caller passes
    its own allowlist so there is ONE source of truth (duplicating the list here
    would drift, exactly as .claude/rules/codex-agent.md drifted from
    config/agents/codex.yaml).
    """
    conn = _get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        base = """
            SELECT i.*, s.scanned_by, s.scanned_at
            FROM code_issues i
            JOIN code_scans s ON i.scan_id = s.id
        """
        order = """
            ORDER BY
                CASE i.severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END,
                i.created_at DESC
            LIMIT %s
        """
        where = []
        params = []
        if status != "all":
            where.append("i.status = %s")
            params.append(status)
        if auto_fixable:
            for pat in _AUTO_FIX_EXCLUDED_MESSAGE_LIKE:
                where.append("COALESCE(i.message, '') NOT LIKE %s")
                params.append(pat)
            for msg_pat, path_pat in _AUTO_FIX_EXCLUDED_IN_PATH:
                where.append("NOT (COALESCE(i.message, '') LIKE %s AND COALESCE(i.file_path, '') LIKE %s)")
                params.extend([msg_pat, path_pat])
        if path_prefixes:
            # Cap the list so a caller cannot build an unbounded OR-chain.
            prefixes = [p for p in list(path_prefixes)[:100] if p and str(p).strip()]
            if prefixes:
                ors = []
                for p in prefixes:
                    ors.append("COALESCE(i.file_path, '') LIKE %s ESCAPE '\\'")
                    params.append(_like_prefix(str(p).strip()))
                where.append("(" + " OR ".join(ors) + ")")

        clause = (" WHERE " + " AND ".join(where) + " ") if where else " "
        cur.execute(base + clause + order, tuple(params) + (limit,))

        issues = cur.fetchall()
        return {
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
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


def mark_fixed(issue_id, fixed_by="unknown", description=""):
    """Mark an issue as fixed and create a code_fixes record."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT file_path FROM code_issues WHERE id = %s", (issue_id,))
        issue = cur.fetchone()
        if not issue:
            return {"success": False, "error": "Issue not found"}

        cur.execute(
            "UPDATE code_issues SET status = 'fixed', fixed_by = %s, fixed_at = NOW() WHERE id = %s",
            (fixed_by, issue_id),
        )
        cur.execute(
            """
            INSERT INTO code_fixes (issue_id, file_path, fixed_by, fix_description)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """,
            (issue_id, issue["file_path"], fixed_by, description),
        )
        fix_id = cur.fetchone()["id"]
        conn.commit()

        return {
            "success": True,
            "fix_id": fix_id,
            "issue_id": issue_id,
            "fixed_by": fixed_by,
            "message": "Issue marked as fixed",
        }
    except Exception as e:
        if conn:
            conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def get_fixes(limit=30):
    """Get fix history."""
    conn = _get_db()
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
        return {
            "success": True,
            "fixes": [{**dict(f), "fixed_at": f["fixed_at"].isoformat() if f["fixed_at"] else None} for f in fixes],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


def get_file_health():
    """Get per-file health status (latest scan + open issue count)."""
    conn = _get_db()
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
            FROM code_issues WHERE status = 'open'
            GROUP BY file_path
        """
        )
        open_map = {r["file_path"]: r["open_issues"] for r in cur.fetchall()}

        return {
            "success": True,
            "files": [
                {
                    **dict(f),
                    "open_issues": open_map.get(f["file_path"], 0),
                    "quality_score": float(f["quality_score"]) if f["quality_score"] else None,
                    "scanned_at": f["scanned_at"].isoformat() if f["scanned_at"] else None,
                }
                for f in files
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


def get_directory_files(path="platform_v2", extensions=None):
    """List files in a directory for the scan browser UI."""
    if extensions is None:
        extensions = [".py", ".js", ".html"]

    # Resolve sub-paths through _PATH_MAP (e.g. "platform_v2/tools" -> "/app/tools")
    base_path = _PATH_MAP.get(path)
    if not base_path:
        for prefix, mapped in _PATH_MAP.items():
            if path.startswith(prefix + "/"):
                base_path = mapped + path[len(prefix) :]
                break
        if not base_path:
            base_path = f"/mnt/archie_brain/{path}"

    if not os.path.exists(base_path):
        return {"success": False, "error": f"Directory not found: {path}"}

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
                full = os.path.join(root, filename)
                if base_path == "/app":
                    rel_path = f"platform_v2/{os.path.relpath(full, '/app')}"
                    folder = os.path.dirname(os.path.relpath(full, "/app"))
                else:
                    rel_path = os.path.relpath(full, "/mnt/archie_brain")
                    folder = os.path.dirname(rel_path)
                stat = os.stat(full)
                files.append(
                    {
                        "path": rel_path,
                        "name": filename,
                        "size": stat.st_size,
                        "full_path": full,
                        "extension": os.path.splitext(filename)[1],
                        "folder": folder or "root",
                        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )

    return {
        "success": True,
        "directory": path,
        "file_count": len(files),
        "files": sorted(files, key=lambda x: x["path"]),
    }


# ===================================================================
# SMART SCAN MODES
# ===================================================================


def get_changed_files(extensions=None):
    """Find files that have been modified since their last scan.

    Compares filesystem mtime to the latest scanned_at per file in code_scans.
    Returns files where mtime > last scan time, plus files never scanned.
    """
    if extensions is None:
        extensions = [".py", ".js", ".html"]

    conn = _get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Get the latest scan time per file
        cur.execute(
            """
            SELECT file_path, MAX(scanned_at) as last_scanned
            FROM code_scans
            GROUP BY file_path
        """
        )
        scan_map = {r["file_path"]: r["last_scanned"] for r in cur.fetchall()}

        if not scan_map:
            return {
                "success": True,
                "changed": [],
                "total": 0,
                "message": "No previous scans found — use Browse to scan files first",
            }

        changed = []
        for file_path, last_scanned in scan_map.items():
            resolved = _resolve_path(file_path)
            if not resolved or not os.path.exists(resolved):
                continue
            if not any(file_path.endswith(ext) for ext in extensions):
                continue
            stat = os.stat(resolved)
            file_mtime = datetime.fromtimestamp(stat.st_mtime)
            if file_mtime > last_scanned:
                folder = os.path.dirname(file_path)
                changed.append(
                    {
                        "path": file_path,
                        "name": os.path.basename(file_path),
                        "size": stat.st_size,
                        "full_path": resolved,
                        "extension": os.path.splitext(file_path)[1],
                        "folder": folder or "root",
                        "mtime": file_mtime.isoformat(),
                        "last_scanned": last_scanned.isoformat(),
                    }
                )

        return {
            "success": True,
            "changed": sorted(changed, key=lambda x: x["path"]),
            "total": len(changed),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


def get_module_list():
    """List scannable platform modules with file counts.

    Reads from module_registry MODULES list and counts .py files per module dir.
    """
    try:
        from module_registry import MODULES
    except ImportError:
        return {"success": False, "error": "module_registry not available"}

    modules = []
    for mod in MODULES:
        if not mod.enabled:
            continue
        # Derive filesystem path from module id
        mod_dir = f"/app/tools/{mod.id}"
        if not os.path.isdir(mod_dir):
            continue
        # Count scannable files
        file_count = 0
        for root, dirs, filenames in os.walk(mod_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            for fn in filenames:
                if fn.endswith((".py", ".js", ".html")) and fn != "__init__.py":
                    file_count += 1

        modules.append(
            {
                "id": mod.id,
                "name": mod.name,
                "category": mod.category.value if hasattr(mod.category, "value") else str(mod.category),
                "file_count": file_count,
                "icon": mod.icon,
            }
        )

    # Sort by category then name
    modules.sort(key=lambda m: (m["category"], m["name"]))
    return {"success": True, "modules": modules, "total": len(modules)}


def get_module_files(module_id, extensions=None):
    """Get scannable files for a specific module."""
    if extensions is None:
        extensions = [".py", ".js", ".html"]

    mod_dir = f"/app/tools/{module_id}"
    if not os.path.isdir(mod_dir):
        return {"success": False, "error": f"Module directory not found: {module_id}"}

    files = []
    for root, dirs, filenames in os.walk(mod_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__" and d != "node_modules"]
        for filename in filenames:
            if filename == "__init__.py":
                continue
            if any(filename.endswith(ext) for ext in extensions):
                full = os.path.join(root, filename)
                rel_path = f"platform_v2/tools/{module_id}/{os.path.relpath(full, mod_dir)}"
                folder = os.path.dirname(os.path.relpath(full, mod_dir))
                stat = os.stat(full)
                files.append(
                    {
                        "path": rel_path,
                        "name": filename,
                        "size": stat.st_size,
                        "full_path": full,
                        "extension": os.path.splitext(filename)[1],
                        "folder": f"tools/{module_id}/{folder}" if folder else f"tools/{module_id}",
                        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )

    return {
        "success": True,
        "module_id": module_id,
        "file_count": len(files),
        "files": sorted(files, key=lambda x: x["path"]),
    }


def get_previously_scanned(extensions=None):
    """Get all previously scanned files for rescan mode.

    Returns distinct file_path entries from code_scans that still exist on disk.
    """
    if extensions is None:
        extensions = [".py", ".js", ".html"]

    conn = _get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT DISTINCT ON (file_path)
                file_path, quality_score, scanned_at
            FROM code_scans
            ORDER BY file_path, scanned_at DESC
        """
        )
        rows = cur.fetchall()

        files = []
        for r in rows:
            fp = r["file_path"]
            if not any(fp.endswith(ext) for ext in extensions):
                continue
            resolved = _resolve_path(fp)
            if not resolved or not os.path.exists(resolved):
                continue
            stat = os.stat(resolved)
            folder = os.path.dirname(fp)
            files.append(
                {
                    "path": fp,
                    "name": os.path.basename(fp),
                    "size": stat.st_size,
                    "full_path": resolved,
                    "extension": os.path.splitext(fp)[1],
                    "folder": folder or "root",
                    "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "last_score": float(r["quality_score"]) if r["quality_score"] else None,
                    "last_scanned": r["scanned_at"].isoformat() if r["scanned_at"] else None,
                }
            )

        return {
            "success": True,
            "file_count": len(files),
            "files": sorted(files, key=lambda x: x["path"]),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        cur.close()
        conn.close()


# ===================================================================
# MULTI-AGENT REVIEW
# ===================================================================


def get_review_agents(specialty=None, limit=8):
    """Get code review agents from Team Management + check model availability."""
    team_agents = _get_team_review_agents(specialty=specialty, limit=limit)

    agents = []
    for agent_key, config in team_agents.items():
        model_available = False
        if NODE_ROUTING_AVAILABLE:
            try:
                nodes = get_nodes_with_model(config["model"])
                model_available = len(nodes) > 0
            except Exception:
                pass

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

    return {
        "success": True,
        "agents": agents,
        "agent_count": len(agents),
        "specialties": list(REVIEW_SKILL_MAPPING.keys()),
        "source": "team_management",
        "node_routing": NODE_ROUTING_AVAILABLE,
    }


def get_review_nodes():
    """Get available remote nodes and their models for code review."""
    nodes = _get_available_nodes()

    total_models = set()
    for node in nodes:
        for model in node.get("models", []):
            if model.get("is_available"):
                total_models.add(model["model_name"])

    return {
        "success": True,
        "nodes": [dict(n) for n in nodes],
        "node_count": len(nodes),
        "total_models": len(total_models),
        "model_list": sorted(list(total_models)),
        "node_routing_available": NODE_ROUTING_AVAILABLE,
    }


def start_multi_agent_review(code, file_path="unknown", agents=None, context=""):
    """Start an async multi-agent code review. Returns review_id immediately."""
    if not code:
        return {"success": False, "error": "No code provided"}

    if agents is None:
        agents = list(FALLBACK_REVIEW_AGENTS.keys())

    review_id = f"mar_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.urandom(4).hex()}"

    review = {
        "id": review_id,
        "file_path": file_path,
        "status": "running",
        "started_at": datetime.now().isoformat(),
        "agents_selected": agents,
        "agent_reviews": {},
        "consensus": None,
        "final_issues": [],
    }
    _multi_agent_reviews[review_id] = review

    thread = threading.Thread(
        target=_run_multi_agent_review,
        args=(review_id, code, file_path, agents, context),
        daemon=True,
    )
    thread.start()

    return {
        "success": True,
        "review_id": review_id,
        "message": f"Multi-agent review started with {len(agents)} agents",
    }


def get_review_status(review_id):
    """Get status/results of a multi-agent review."""
    if review_id in _multi_agent_reviews:
        return {"success": True, "review": _multi_agent_reviews[review_id]}
    return {"success": False, "error": "Review not found"}


# ===================================================================
# PRIVATE HELPERS
# ===================================================================


def _get_team_review_agents(specialty=None, limit=4):
    """Query agents table for review-capable agents."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if specialty and specialty in REVIEW_SKILL_MAPPING:
            skills = REVIEW_SKILL_MAPPING[specialty]["skills"]
        else:
            skills = []
            for spec in REVIEW_SKILL_MAPPING.values():
                skills.extend(spec["skills"])
            skills = list(set(skills))

        cur.execute(
            """
            SELECT DISTINCT
                a.id, a.name, a.first_name, a.last_name, a.model,
                a.system_prompt, a.title,
                s.skill_name, s.proficiency_level, s.skill_category
            FROM agents a
            JOIN agent_skills s ON a.id = s.agent_id
            WHERE a.status = 'active'
              AND a.model IS NOT NULL
              AND s.skill_name = ANY(%s)
            ORDER BY s.proficiency_level DESC, a.name
            LIMIT %s
        """,
            [skills, limit],
        )

        agents = cur.fetchall()
        review_agents = {}
        for agent in agents:
            agent_key = f"agent_{agent['id']}"
            skill = agent["skill_name"]

            spec_config = None
            for spec_data in REVIEW_SKILL_MAPPING.values():
                if skill in spec_data["skills"]:
                    spec_config = spec_data
                    break
            if not spec_config:
                spec_config = REVIEW_SKILL_MAPPING.get("code_review", {})

            review_agents[agent_key] = {
                "id": agent["id"],
                "name": agent["name"] or f"{agent['first_name']} {agent['last_name']}",
                "model": agent["model"],
                "specialty": agent["skill_category"] or "general",
                "skill": skill,
                "proficiency": agent["proficiency_level"],
                "focus": spec_config.get("focus", []),
                "prompt_prefix": spec_config.get("prompt_prefix", "You are reviewing code. Focus on: "),
                "system_prompt": agent["system_prompt"],
            }

        return review_agents
    except Exception as e:
        logger.error(f"Error getting review agents: {e}")
        return {}
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _get_available_nodes():
    """Query remote_nodes for online, approved, bridge-enabled nodes."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT
                n.node_id, n.node_name, n.vpn_ip, n.status,
                n.current_load, n.bridge_priority, n.gpu_available, n.gpu_model,
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
        return cur.fetchall()
    except Exception as e:
        logger.error(f"Error getting available nodes: {e}")
        return []
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _run_multi_agent_review(review_id, code, file_path, agents, context):
    """Background thread: execute parallel agent reviews, build consensus."""
    review = _multi_agent_reviews[review_id]

    try:
        team_agents = _get_team_review_agents(limit=10)
        all_issues = []
        review_lock = threading.Lock()

        def run_single(agent_key):
            if agent_key in team_agents:
                config = team_agents[agent_key]
            elif agent_key in FALLBACK_REVIEW_AGENTS:
                config = FALLBACK_REVIEW_AGENTS[agent_key]
            else:
                matching = [a for a in team_agents.values() if str(a.get("id")) == agent_key.replace("agent_", "")]
                config = matching[0] if matching else None

            if not config:
                return None

            agent_name = config.get("name", "Unknown Agent")
            prompt_prefix = config.get("prompt_prefix", "You are reviewing code. Focus on: ")
            focus_areas = config.get("focus", [])

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
                dispatch_result = _dispatcher.request_work(
                    capability="code_review",
                    prompt=prompt,
                    module_id="repair_bay",
                    system_prompt=prompt_prefix,
                    json_mode=True,
                )

                if not dispatch_result.success:
                    raise RuntimeError(f"Dispatch failed: {dispatch_result.error}")

                response_text = dispatch_result.response
                if "```json" in response_text:
                    response_text = response_text.split("```json")[1].split("```")[0]
                elif "```" in response_text:
                    response_text = response_text.split("```")[1].split("```")[0]

                parsed = json.loads(response_text.strip())

                with review_lock:
                    review["agent_reviews"][agent_key] = {
                        "agent_name": agent_name,
                        "model": dispatch_result.model_used,
                        "issues": parsed.get("issues", []),
                        "summary": parsed.get("summary", ""),
                        "quality_score": parsed.get("quality_score", 0),
                        "completed_at": datetime.now().isoformat(),
                    }
                    for issue in parsed.get("issues", []):
                        all_issues.append({**issue, "found_by": agent_name})

                return parsed

            except Exception as e:
                logger.error(f"Agent {agent_name} review failed: {e}")
                with review_lock:
                    review["agent_reviews"][agent_key] = {
                        "agent_name": agent_name,
                        "error": str(e),
                        "completed_at": datetime.now().isoformat(),
                    }
                return None

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(run_single, a): a for a in agents}
            for future in as_completed(futures):
                future.result()

        # Build consensus
        review["final_issues"] = all_issues
        review["consensus"] = {
            "total_issues": len(all_issues),
            "by_severity": {
                sev: len([i for i in all_issues if i.get("severity") == sev])
                for sev in ["critical", "high", "medium", "low"]
            },
            "agents_completed": len([r for r in review["agent_reviews"].values() if "error" not in r]),
        }
        review["status"] = "completed"
        review["completed_at"] = datetime.now().isoformat()

    except Exception as e:
        logger.error(f"Multi-agent review failed: {e}")
        review["status"] = "failed"
        review["error"] = str(e)


def audit_dependencies():
    """Run pip audit and return structured findings.

    Returns list of dicts: [{package, version, vuln_id, severity, description, fix_version}]
    """
    import subprocess

    findings = []

    # Method 1: pip audit (if installed)
    try:
        result = subprocess.run(
            ["pip-audit", "--format", "json", "--desc"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.stdout:
            import json as _json

            data = _json.loads(result.stdout)
            for vuln in data.get("vulnerabilities", []):
                findings.append(
                    {
                        "package": vuln.get("name", "unknown"),
                        "version": vuln.get("version", "unknown"),
                        "vuln_id": vuln.get("vulnerability_id", vuln.get("id", "")),
                        "severity": _map_pip_severity(vuln),
                        "description": vuln.get("description", "")[:200],
                        "fix_version": (
                            vuln.get("fix_versions", ["unknown"])[0] if vuln.get("fix_versions") else "unknown"
                        ),
                    }
                )
    except FileNotFoundError:
        logger.debug("pip-audit not installed, falling back to requirements parse")
    except Exception as e:
        logger.warning("pip audit failed: %s", e)

    # Method 2: Parse requirements.txt for known pinned-but-outdated packages
    # (This catches packages even when pip-audit isn't installed)
    try:
        req_path = os.environ.get("REQUIREMENTS_PATH", "/app/requirements.txt")
        if os.path.exists(req_path):
            with open(req_path) as f:
                for line in f:
                    if "SECURITY:" in line:
                        # Extract security comments we've documented
                        findings.append(
                            {
                                "package": "requirements.txt",
                                "version": "n/a",
                                "vuln_id": "PIN_BLOCKED",
                                "severity": "high",
                                "description": line.strip().lstrip("# "),
                                "fix_version": "blocked by compatibility pin",
                            }
                        )
    except Exception as e:
        logger.warning("Requirements parse failed: %s", e)

    return findings


def _map_pip_severity(vuln):
    """Map pip-audit severity aliases to standard levels."""
    aliases = vuln.get("aliases", [])
    desc = vuln.get("description", "").lower()
    if any("critical" in a.lower() for a in aliases):
        return "critical"
    if "remote code execution" in desc or "rce" in desc:
        return "critical"
    if "denial of service" in desc or "dos" in desc:
        return "medium"
    if "bypass" in desc or "injection" in desc:
        return "high"
    return "medium"


def store_dependency_findings(findings):
    """Store dependency audit findings as code_scans + code_issues.

    Returns scan_id or None.
    """
    if not findings:
        return None

    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)

        security_count = len([f for f in findings if f["severity"] in ("critical", "high")])

        cur.execute(
            """INSERT INTO code_scans
               (file_path, scan_type, issues_found, security_issues,
                quality_score, scan_result, scanned_by)
               VALUES ('requirements.txt', 'dependency_audit', %s, %s,
                       %s, %s, 'agent_loop')
               RETURNING id""",
            (
                len(findings),
                security_count,
                max(0, 100 - len(findings) * 5),
                json.dumps({"findings": findings}),
            ),
        )
        scan_id = cur.fetchone()["id"]

        for finding in findings:
            cur.execute(
                """INSERT INTO code_issues
                   (scan_id, file_path, line_number, issue_type,
                    severity, message, suggestion)
                   VALUES (%s, 'requirements.txt', 0, 'cve', %s, %s, %s)""",
                (
                    scan_id,
                    finding["severity"],
                    f"{finding['package']}=={finding['version']}: " f"{finding['vuln_id']} — {finding['description']}",
                    (
                        f"Upgrade to {finding['fix_version']}"
                        if finding["fix_version"] != "unknown"
                        else "Check PyPI for patched version"
                    ),
                ),
            )

        conn.commit()
        cur.close()
        conn.close()
        logger.info(
            "Dependency audit: %d findings stored (scan #%d)",
            len(findings),
            scan_id,
        )
        return scan_id
    except Exception as e:
        logger.error("Failed to store dependency findings: %s", e)
        return None
