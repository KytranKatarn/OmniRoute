"""
A.R.C.H.I.E. MCP Server - Claude Code Integration Tools
Phase 64: Claude Code Optimization

Specialized tools for Claude Code integration:
- get_git_context: Recent git activity and changes
- search_mistakes: Find learned mistakes to avoid
- get_roadmap_status: Current phase and tasks
- trigger_code_review: Run CodeRabbit analysis
- get_module_info: Module details and patterns
- check_platform_health: Quick health check
"""

import os
from database import _get_db_password
import logging
import re
import subprocess
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Any
import requests

from . import register_tool, cap_limit

logger = logging.getLogger("archie_mcp.tools.claude")

# Database configuration
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.1.200"),
    "database": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": _get_db_password(),
}

PLATFORM_URL = os.getenv("ARCHIE_PLATFORM_URL", "http://archie_platform:3000")
GIT_REPO_PATH = "/mnt/archie_brain"


def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn, conn.cursor(cursor_factory=RealDictCursor)
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None, None


def run_git_command(cmd: List[str], cwd: str = GIT_REPO_PATH) -> str:
    """Run a git command and return output"""
    try:
        result = subprocess.run(["git"] + cmd, cwd=cwd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Git command failed: {e}")
        return ""


# ============================================================================
# GET GIT CONTEXT TOOL
# ============================================================================


async def get_git_context_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get recent git activity for context-aware assistance.

    Returns:
    - Current branch
    - Recent commits (last N)
    - Modified files
    - Staged changes summary
    - Uncommitted files
    """
    limit = cap_limit(arguments, 10, 50)
    include_diff = arguments.get("include_diff", False)

    try:
        context = {
            "branch": run_git_command(["rev-parse", "--abbrev-ref", "HEAD"]),
            "last_commit": run_git_command(["log", "-1", "--format=%H %s"]),
            "recent_commits": [],
            "modified_files": [],
            "staged_files": [],
            "untracked_files": [],
        }

        # Recent commits
        commits_raw = run_git_command(["log", f"-{limit}", "--format=%H|%s|%an|%ar"])
        if commits_raw:
            for line in commits_raw.split("\n"):
                parts = line.split("|")
                if len(parts) >= 4:
                    context["recent_commits"].append(
                        {
                            "hash": parts[0][:8],
                            "message": parts[1],
                            "author": parts[2],
                            "time": parts[3],
                        }
                    )

        # Modified files (unstaged)
        modified = run_git_command(["diff", "--name-only"])
        if modified:
            context["modified_files"] = modified.split("\n")

        # Staged files
        staged = run_git_command(["diff", "--cached", "--name-only"])
        if staged:
            context["staged_files"] = staged.split("\n")

        # Untracked files
        untracked = run_git_command(["ls-files", "--others", "--exclude-standard"])
        if untracked:
            context["untracked_files"] = untracked.split("\n")[:20]  # Limit

        # Optional: include diff content
        if include_diff and context["staged_files"]:
            context["staged_diff"] = run_git_command(["diff", "--cached"])[:5000]

        context["summary"] = {
            "total_commits_shown": len(context["recent_commits"]),
            "modified_count": len(context["modified_files"]),
            "staged_count": len(context["staged_files"]),
            "untracked_count": len(context["untracked_files"]),
        }

        return {"success": True, "context": context}

    except Exception as e:
        logger.error(f"Git context error: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="get_git_context",
    category="claude",
    description="Get recent git activity including branch, commits, modified files, and staged changes. Use this to understand the current development context.",
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of recent commits to return (default: 10, max: 50)",
                "default": 10,
            },
            "include_diff": {
                "type": "boolean",
                "description": "Include staged diff content",
                "default": False,
            },
        },
    },
    handler=get_git_context_handler,
)


# ============================================================================
# SEARCH MISTAKES TOOL
# ============================================================================


async def search_mistakes_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Search learned mistakes to prevent repeating errors.

    Prioritizes recent mistakes and exact matches.
    """
    query = arguments.get("query", "")
    category = arguments.get("category")
    limit = cap_limit(arguments, 5, 20)

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "Database connection failed"}

    try:
        conditions = ["knowledge_type = 'mistake_learned'"]
        params = []

        if category:
            conditions.append("tags @> %s::text[]")
            params.append([category])

        # Whole-phrase ILIKE matched only verbatim text, so a natural multi-word
        # query ("git commit stuck") returned 0 rows even though every word
        # appeared in a mistake. Try every-token, then any-token, then the raw
        # phrase — first variant with hits wins.
        per_token = "(title ILIKE %s OR content ILIKE %s)"
        tokens = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) >= 2] if query else []
        variants = []
        if len(tokens) > 1:
            token_params = [f"%{t}%" for t in tokens for _ in range(2)]
            variants.append((" AND ".join([per_token] * len(tokens)), token_params))
            variants.append((" OR ".join([per_token] * len(tokens)), token_params))
        else:
            variants.append((per_token if query else None, [f"%{query}%", f"%{query}%"] if query else []))

        mistakes = []
        for text_cond, text_params in variants:
            where_clause = " AND ".join(conditions + ([text_cond] if text_cond else []))
            cur.execute(
                f"""
                SELECT
                    id,
                    title,
                    content,
                    tags,
                    importance_score,
                    created_at
                FROM knowledge_base
                WHERE {where_clause}
                ORDER BY importance_score DESC, created_at DESC
                LIMIT %s
            """,
                params + text_params + [limit],
            )
            mistakes = cur.fetchall()
            if mistakes:
                break

        # Format for easy reading
        formatted = []
        for m in mistakes:
            formatted.append(
                {
                    "title": m["title"],
                    "pattern": m["content"][:500] if m["content"] else "",
                    "tags": m["tags"] or [],
                    "importance": float(m["importance_score"]) if m["importance_score"] else 0.5,
                    "learned_at": (m["created_at"].isoformat() if m["created_at"] else None),
                }
            )

        return {
            "success": True,
            "mistakes": formatted,
            "count": len(formatted),
            "tip": "Check these patterns before similar operations to avoid known issues",
        }

    except Exception as e:
        logger.error(f"Mistake search error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


register_tool(
    name="search_mistakes",
    category="claude",
    description="Search learned mistakes and error patterns to avoid repeating them. Query by keyword or category (database, docker, python, etc.).",
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query for mistake patterns",
            },
            "category": {
                "type": "string",
                "description": "Filter by category tag (e.g., database, docker, python)",
                "enum": [
                    "database",
                    "docker",
                    "python",
                    "flask",
                    "filesystem",
                    "network",
                    "auth",
                    "api",
                    "git",
                ],
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results (default: 5)",
                "default": 5,
            },
        },
    },
    handler=search_mistakes_handler,
)


# ============================================================================
# GET ROADMAP STATUS TOOL
# ============================================================================


async def get_roadmap_status_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get current development phase and task status from Blueprint.
    """
    include_tasks = arguments.get("include_tasks", True)
    active_only = arguments.get("active_only", False)

    conn, cur = get_db_connection()
    if not conn:
        # #7164 liveness-only fallback. There is no /api/health route — the
        # probe just 404s, and returning health JSON as "roadmap" would
        # mislabel the data. Report honest degraded state instead: is the
        # platform process alive, and was any roadmap data substituted (no).
        platform_status = "unknown"
        try:
            response = requests.get(f"{PLATFORM_URL}/health", timeout=5, allow_redirects=False)
            if response.status_code == 200 and response.json().get("status") == "healthy":
                platform_status = "healthy"
            else:
                platform_status = f"unhealthy (HTTP {response.status_code})"
        except (requests.RequestException, ValueError) as e:
            platform_status = f"offline ({e})"
        return {
            "success": False,
            "error": "Database connection failed; roadmap unavailable",
            "degraded": True,
            "platform_liveness": platform_status,
            "hint": "No roadmap data was substituted — retry once the DB is reachable.",
        }

    try:
        # Get phases
        status_filter = "WHERE status = 'active'" if active_only else ""

        cur.execute(
            f"""
            SELECT
                id,
                phase_number,
                name,
                section,
                status,
                description,
                completion_percent
            FROM blueprint_phases
            {status_filter}
            ORDER BY display_order, phase_number
        """
        )

        phases = cur.fetchall()

        result = {
            "phases": [],
            "summary": {
                "total_phases": len(phases),
                "completed": 0,
                "active": 0,
                "planned": 0,
            },
        }

        for phase in phases:
            phase_data = {
                "id": phase["id"],
                "number": phase["phase_number"],
                "name": phase["name"],
                "section": phase["section"],
                "status": phase["status"],
                "completion": phase["completion_percent"],
            }

            # Count by status
            if phase["status"] == "complete":
                result["summary"]["completed"] += 1
            elif phase["status"] == "active":
                result["summary"]["active"] += 1
            else:
                result["summary"]["planned"] += 1

            # Get tasks if requested
            if include_tasks and phase["status"] in ("active", "in_progress"):
                cur.execute(
                    """
                    SELECT id, task_description, done, notes
                    FROM blueprint_tasks
                    WHERE phase_id = %s
                    ORDER BY display_order
                """,
                    (phase["id"],),
                )

                tasks = cur.fetchall()
                phase_data["tasks"] = [
                    {
                        "description": t["task_description"],
                        "done": t["done"],
                        "notes": t["notes"],
                    }
                    for t in tasks
                ]
                phase_data["task_progress"] = f"{sum(1 for t in tasks if t['done'])}/{len(tasks)}"

            result["phases"].append(phase_data)

        return {"success": True, "roadmap": result}

    except Exception as e:
        logger.error(f"Roadmap fetch error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


register_tool(
    name="get_roadmap_status",
    category="claude",
    description="Get current development roadmap showing phases, their status, and tasks. Use to understand project progress and current focus.",
    input_schema={
        "type": "object",
        "properties": {
            "include_tasks": {
                "type": "boolean",
                "description": "Include task details for active phases",
                "default": True,
            },
            "active_only": {
                "type": "boolean",
                "description": "Only show active/in-progress phases",
                "default": False,
            },
        },
    },
    handler=get_roadmap_status_handler,
)


# ============================================================================
# TRIGGER CODE REVIEW TOOL
# ============================================================================


async def trigger_code_review_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Trigger CodeRabbit analysis on files or staged changes.
    """
    files = arguments.get("files", [])
    review_type = arguments.get("review_type", "full")  # full, security, quality

    try:
        # Get files to review
        if not files:
            # Default to staged files
            staged = run_git_command(["diff", "--cached", "--name-only"])
            if staged:
                files = [f for f in staged.split("\n") if f.endswith((".py", ".js", ".ts", ".html"))]

        if not files:
            return {"success": False, "error": "No files to review"}

        # Route through Department HQ dispatcher (ADR-013, Task #1298). The
        # legacy /tools/coderabbit/api/analyze route was removed; every prior
        # call 404'd and silently fell through to the regex static-analysis
        # fallback. Going through dispatch() gives proper agent selection
        # (P.R.O.B.E. / V.I.G.I.L. on Engineering & Technology) and tagged
        # task_execution_log rows.
        try:
            from tools.department_hq.services.department_dispatcher import dispatch

            try:
                from mcp_server.dispatch_context import claude_request
            except Exception:
                from contextlib import contextmanager

                @contextmanager
                def claude_request(mcp_tool: str, origin: str = "claude"):  # type: ignore[no-redef]
                    yield

            review_files = files[:10]
            file_blocks = []
            for file_path in review_files:
                full_path = os.path.join(GIT_REPO_PATH, file_path)
                if os.path.exists(full_path):
                    try:
                        with open(full_path, "r") as f:
                            content = f.read()
                        file_blocks.append(f"### {file_path}\n```\n{content[:6000]}\n```")
                    except Exception:
                        continue

            review_prompt = (
                f"Review these files for {review_type} issues — "
                "report security, code-quality, and best-practice problems. "
                "Output a JSON-like list of issues with file path, type "
                "(security/quality/style), and a one-line description.\n\n" + "\n\n".join(file_blocks)
            )

            with claude_request(mcp_tool="trigger_code_review", origin="claude"):
                dispatch_result = dispatch(
                    capability="code_review",
                    prompt=review_prompt,
                    module_id="mcp_trigger_code_review",
                )

            if dispatch_result.success and getattr(dispatch_result, "response", None):
                return {
                    "success": True,
                    "review": {
                        "files_analyzed": len(review_files),
                        "report": dispatch_result.response,
                        "agent": getattr(dispatch_result, "agent_name", None),
                        "model": getattr(dispatch_result, "model_used", None),
                    },
                }

            logger.warning(
                "code_review dispatch did not produce a response; falling back to static checks: %s",
                getattr(dispatch_result, "error", None),
            )
        except Exception as e:
            logger.warning(f"Bridge dispatch raised in trigger_code_review: {e}")

        # Fallback: basic static analysis
        issues = []
        for file_path in files[:5]:  # Limit fallback analysis
            full_path = os.path.join(GIT_REPO_PATH, file_path)
            if os.path.exists(full_path):
                with open(full_path, "r") as f:
                    content = f.read()

                # Basic checks
                if "password" in content.lower() and "=" in content:
                    issues.append(
                        {
                            "file": file_path,
                            "type": "security",
                            "message": "Potential hardcoded password",
                        }
                    )
                if "except:" in content:
                    issues.append(
                        {
                            "file": file_path,
                            "type": "quality",
                            "message": "Bare except clause detected",
                        }
                    )

        return {
            "success": True,
            "review": {
                "files_analyzed": len(files),
                "issues": issues,
                "fallback": True,
                "note": "Basic analysis - CodeRabbit API unavailable",
            },
        }

    except Exception as e:
        logger.error(f"Code review error: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="trigger_code_review",
    category="claude",
    description="Trigger AI-powered code review using CodeRabbit. Analyzes files for security issues, code quality, and best practices.",
    input_schema={
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file paths to review (defaults to staged files)",
            },
            "review_type": {
                "type": "string",
                "description": "Type of review",
                "enum": ["full", "security", "quality"],
                "default": "full",
            },
        },
    },
    handler=trigger_code_review_handler,
)


# ============================================================================
# GET MODULE INFO TOOL
# ============================================================================


async def get_module_info_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get information about a specific A.R.C.H.I.E. module.
    """
    module_name = arguments.get("module_name", "")

    if not module_name:
        return {"success": False, "error": "Module name is required"}

    try:
        module_path = f"/mnt/archie_brain/platform_v2/tools/{module_name}"

        info = {
            "name": module_name,
            "exists": os.path.isdir(module_path),
            "files": [],
            "routes": [],
            "has_template": False,
        }

        if info["exists"]:
            # List files
            for f in os.listdir(module_path):
                if f.endswith(".py"):
                    info["files"].append(f)

            # Check for routes
            routes_file = os.path.join(module_path, "routes.py")
            if os.path.exists(routes_file):
                with open(routes_file, "r") as f:
                    content = f.read()

                # Extract route patterns
                import re

                routes = re.findall(r'@\w+\.route\([\'"]([^\'"]+)[\'"]', content)
                info["routes"] = routes[:20]  # Limit

                # Count lines
                info["lines_of_code"] = len(content.split("\n"))

            # Check template
            template_path = f"/mnt/archie_brain/platform_v2/templates/tools/{module_name}.html"
            info["has_template"] = os.path.exists(template_path)

        # Get from module registry if available
        try:
            response = requests.get(f"{PLATFORM_URL}/api/modules/health", timeout=5)
            if response.status_code == 200:
                modules = response.json().get("modules", [])
                for m in modules:
                    if m.get("module_id") == module_name:
                        info["registry"] = {
                            "name": m.get("name"),
                            "category": m.get("category"),
                            "status": m.get("status"),
                            "description": m.get("description"),
                        }
                        break
        except Exception:
            pass

        return {"success": True, "module": info}

    except Exception as e:
        logger.error(f"Module info error: {e}")
        return {"success": False, "error": str(e)}


register_tool(
    name="get_module_info",
    category="claude",
    description="Get detailed information about an A.R.C.H.I.E. module including files, routes, and registry status.",
    input_schema={
        "type": "object",
        "properties": {
            "module_name": {
                "type": "string",
                "description": "Module name (e.g., blueprint, consciousness, coderabbit)",
            }
        },
        "required": ["module_name"],
    },
    handler=get_module_info_handler,
)


# ============================================================================
# CHECK PLATFORM HEALTH TOOL
# ============================================================================


async def check_platform_health_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Quick health check of A.R.C.H.I.E. platform and services.
    """
    detailed = arguments.get("detailed", False)

    health = {
        "platform": {"status": "unknown"},
        "database": {"status": "unknown"},
        "services": {},
    }

    # Check platform. There is no /api/health route: the platform's liveness
    # endpoint is /health, and every /api/* path sits behind Flask-Login and
    # answers 302 with an HTML login page. Probing /api/health followed that
    # redirect and then died in response.json() with "Expecting value: line 1
    # column 1 (char 0)" -- a ValueError, which requests.RequestException does
    # NOT catch, so the failure escaped and a healthy hub read as degraded.
    try:
        response = requests.get(f"{PLATFORM_URL}/health", timeout=5, allow_redirects=False)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "healthy":
                health["platform"] = {
                    "status": "healthy",
                    "version": data.get("version", "unknown"),
                    "uptime": data.get("uptime"),
                }
            else:
                health["platform"] = {"status": "unhealthy", "detail": data}
        elif response.status_code in (301, 302, 307, 308):
            # A redirect means we hit an auth-gated path, not the platform.
            health["platform"] = {
                "status": "unhealthy",
                "code": response.status_code,
                "detail": "redirected to auth — wrong path for a liveness probe",
            }
        else:
            health["platform"] = {"status": "unhealthy", "code": response.status_code}
    except (requests.RequestException, ValueError) as e:
        health["platform"] = {"status": "offline", "error": str(e)}

    # Check database
    conn, cur = get_db_connection()
    if conn:
        try:
            cur.execute("SELECT 1")
            health["database"] = {"status": "healthy"}

            if detailed:
                cur.execute("SELECT count(*) FROM knowledge_base")
                health["database"]["knowledge_entries"] = cur.fetchone()["count"]
        except Exception as e:
            health["database"] = {"status": "error", "error": str(e)}
        finally:
            cur.close()
            conn.close()
    else:
        health["database"] = {"status": "offline"}

    # Check additional services if detailed
    if detailed:
        # Ollama
        for host in ["192.168.1.246:11434", "192.168.1.245:11434"]:
            try:
                r = requests.get(f"http://{host}/api/tags", timeout=2)
                if r.status_code == 200:
                    health["services"]["ollama"] = {
                        "status": "healthy",
                        "host": host,
                        "models": len(r.json().get("models", [])),
                    }
                    break
            except Exception:
                continue

        if "ollama" not in health["services"]:
            health["services"]["ollama"] = {"status": "offline"}

        # N8N
        try:
            r = requests.get("http://localhost:5678/healthz", timeout=2)
            health["services"]["n8n"] = {"status": "healthy" if r.status_code == 200 else "unhealthy"}
        except Exception:
            health["services"]["n8n"] = {"status": "offline"}

    # Overall status
    health["overall"] = (
        "healthy" if all(s.get("status") == "healthy" for s in [health["platform"], health["database"]]) else "degraded"
    )

    return {"success": True, "health": health}


register_tool(
    name="check_platform_health",
    category="claude",
    description="Quick health check of A.R.C.H.I.E. platform, database, and services. Use before making changes to verify system is healthy.",
    input_schema={
        "type": "object",
        "properties": {
            "detailed": {
                "type": "boolean",
                "description": "Include detailed service checks (Ollama, N8N)",
                "default": False,
            }
        },
    },
    handler=check_platform_health_handler,
)


# ============================================================================
# TOKEN-EFFICIENT SUMMARY TOOLS (Added for optimization)
# ============================================================================


async def get_quick_summary_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ultra-compact platform summary - minimal tokens.
    Returns only essential status in ~100 tokens.
    """
    try:
        summary = []

        # Platform status (one line). /health is the liveness route — there is no
        # /api/health (404), and allow_redirects=False keeps an auth redirect
        # from being counted as OK. Same pattern as check_platform_health above.
        try:
            r = requests.get(f"{PLATFORM_URL}/health", timeout=2, allow_redirects=False)
            if r.status_code == 200:
                summary.append("Platform: OK")
            else:
                summary.append(f"Platform: ERROR ({r.status_code})")
        except Exception:
            summary.append("Platform: OFFLINE")

        # DB status (one line)
        conn, cur = get_db_connection()
        if conn:
            try:
                cur.execute("SELECT count(*) FROM knowledge_base")
                kb_count = cur.fetchone()["count"]
                summary.append(f"DB: OK ({kb_count} knowledge entries)")
            finally:
                cur.close()
                conn.close()
        else:
            summary.append("DB: OFFLINE")

        # Git status (one line). The gateway image has no repo mount, so git
        # silently fails there — report n/a instead of claiming "0 modified".
        branch = run_git_command(["rev-parse", "--abbrev-ref", "HEAD"])
        if branch:
            modified = run_git_command(["diff", "--name-only"])
            mod_count = len([f for f in modified.split("\n") if f]) if modified else 0
            summary.append(f"Git: {branch} ({mod_count} modified)")
        else:
            summary.append("Git: n/a (repo not visible)")

        return {
            "success": True,
            "summary": " | ".join(summary),
            "tokens_saved": "This response is ~50 tokens vs ~500 for detailed health check",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


register_tool(
    name="get_quick_summary",
    category="claude",
    description="Ultra-compact platform summary in ~50 tokens. Use this FIRST before detailed checks.",
    input_schema={"type": "object", "properties": {}},
    handler=get_quick_summary_handler,
)


async def list_modules_brief_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    List all modules with just name and status - no details.
    """
    category = arguments.get("category")

    try:
        response = requests.get(f"{PLATFORM_URL}/api/modules/health", timeout=5)
        if response.status_code != 200:
            return {"success": False, "error": "API unavailable"}

        modules = response.json().get("modules", [])

        # Filter by category if specified
        if category:
            modules = [m for m in modules if m.get("category", "").lower() == category.lower()]

        # Return just names and status
        brief = [f"{m['module_id']}:{m.get('status', '?')}" for m in modules]

        return {
            "success": True,
            "modules": brief,
            "count": len(brief),
            "format": "name:status",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


register_tool(
    name="list_modules_brief",
    category="claude",
    description='List modules as compact "name:status" pairs. Use get_module_info only if you need details.',
    input_schema={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Filter by category (ADMIN, CREATION, DEVELOPMENT, BUSINESS_TOOLS, STANDALONE_APPS)",
            }
        },
    },
    handler=list_modules_brief_handler,
)


async def search_knowledge_brief_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Search knowledge base returning only titles and types - not full content.
    """
    query = arguments.get("query", "")
    limit = cap_limit(arguments, 10, 20)

    if not query:
        return {"success": False, "error": "Query required"}

    conn, cur = get_db_connection()
    if not conn:
        return {"success": False, "error": "DB connection failed"}

    try:
        cur.execute(
            """
            SELECT id, title, knowledge_type, importance_score
            FROM knowledge_base
            WHERE title ILIKE %s OR content ILIKE %s
            ORDER BY importance_score DESC
            LIMIT %s
        """,
            (f"%{query}%", f"%{query}%", limit),
        )

        results = cur.fetchall()

        # Compact format: "id:type:title"
        brief = [f"{r['id']}:{r['knowledge_type']}:{r['title'][:50]}" for r in results]

        return {
            "success": True,
            "results": brief,
            "count": len(brief),
            "tip": "Use knowledge ID to fetch full content if needed",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


register_tool(
    name="search_knowledge_brief",
    category="claude",
    description="Search knowledge base returning only titles (not content). Get full content only if needed.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    },
    handler=search_knowledge_brief_handler,
)


async def get_recent_activity_handler(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compact summary of recent platform activity.
    """
    try:
        activity = []

        # Recent commits (last 3)
        commits = run_git_command(["log", "-3", "--format=%h %s"])
        if commits:
            activity.append(f"Commits: {commits.replace(chr(10), ' | ')}")

        # Modified files count
        modified = run_git_command(["diff", "--name-only"])
        if modified:
            files = [f for f in modified.split("\n") if f]
            activity.append(f"Modified: {len(files)} files")

        # DB check
        conn, cur = get_db_connection()
        if conn:
            try:
                cur.execute(
                    """
                    SELECT count(*) FROM knowledge_base
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """
                )
                recent_knowledge = cur.fetchone()["count"]
                activity.append(f"New knowledge (24h): {recent_knowledge}")
            finally:
                cur.close()
                conn.close()

        return {"success": True, "activity": activity, "summary": " | ".join(activity)}
    except Exception as e:
        return {"success": False, "error": str(e)}


register_tool(
    name="get_recent_activity",
    category="claude",
    description="Compact summary of recent commits, changes, and knowledge additions.",
    input_schema={"type": "object", "properties": {}},
    handler=get_recent_activity_handler,
)


# Log registration
logger.info(
    "Claude integration tools registered: get_git_context, search_mistakes, get_roadmap_status, trigger_code_review, get_module_info, check_platform_health, get_quick_summary, list_modules_brief, search_knowledge_brief, get_recent_activity"
)
