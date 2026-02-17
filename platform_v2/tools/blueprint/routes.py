"""A.R.C.H.I.E. Mission Control Routes - Admin Only"""

from flask import jsonify, request, redirect, url_for
from . import blueprint_bp
import json
from datetime import datetime
from psycopg2.extras import RealDictCursor

# Import module registry for module status
try:
    from module_registry import (
        get_all_modules,
        get_enabled_modules,
        ModuleCategory,
    )  # noqa: F401

    REGISTRY_AVAILABLE = True
except ImportError:
    REGISTRY_AVAILABLE = False

# Import Phase 29 managers
try:
    from .phase_manager import (
        get_all_phases,
        get_phase,
        create_phase,
        update_phase,
        delete_phase,
        reorder_phases,
        add_task,
        toggle_task,
        update_task,
        delete_task,
        get_roadmap_summary,
        get_sections,
    )
    from .inventory_scanner import (  # noqa: F401
        scan_platform,
        get_current_inventory,
        get_inventory_history,
        get_inventory_snapshot,
        delete_inventory_snapshot,
        scan_and_save,
    )
    from .cleanup_manager import (  # noqa: F401
        scan_for_candidates,
        add_candidates_to_db,
        get_candidates,
        approve_candidate,
        reject_candidate,
        bulk_approve,
        execute_cleanup,
        bulk_execute,
        get_cleanup_report,
        scan_and_save as cleanup_scan_and_save,
    )

    PHASE29_AVAILABLE = True
except ImportError as e:
    PHASE29_AVAILABLE = False
    import logging

    logging.getLogger(__name__).warning(f"Phase 29 managers not available: {e}")

# Import Blueprint Intelligence (Phase 29.5 - Full Integration, 29.6 - Cross-Module Sync)
try:
    from .blueprint_intelligence import (
        get_database_schema,
        get_api_endpoints,
        get_system_health,
        get_dependencies,
        get_backup_status,
        get_agent_directory,
        compare_inventory_snapshots,
        sync_blueprint_to_knowledge_base,
        execute_quick_action,
        get_consciousness_summary,
        sync_module_code_to_knowledge,  # Phase 29.6 - Module code sync
        auto_sync_if_stale,  # Phase: DB-Centric Consolidation
    )

    INTELLIGENCE_AVAILABLE = True
except ImportError as e:
    INTELLIGENCE_AVAILABLE = False
    import logging

    logging.getLogger(__name__).warning(f"Blueprint Intelligence not available: {e}")

# Docs are now served from the knowledge_base table (DB-Centric Consolidation)


@blueprint_bp.route("/")
def index():
    """Redirect to Dev HQ (Mission Control replaced by Dev HQ)."""
    return redirect(url_for("dev_hq.index"))


@blueprint_bp.route("/api/overview")
def get_overview():
    """Get A.R.C.H.I.E. system overview"""
    # Count docs from knowledge_base
    docs_count = 0
    try:
        from database import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM knowledge_base WHERE source_type = 'docs_migration'")
        docs_count = cur.fetchone()[0]
        cur.close()
        conn.close()
    except Exception:
        pass

    return jsonify(
        {
            "name": "A.R.C.H.I.E.",
            "full_name": "Autonomous Resource and Coordination Hub for Intelligent Execution",
            "version": "5.4.0",
            "description": """A.R.C.H.I.E. is an AI-powered platform that combines multiple intelligent systems
        into a unified dashboard. She provides tools for creation, development, business management,
        health & wellness, and system administration - all with AI assistance.""",
            "mission": """To empower users with AI-assisted tools that handle complex tasks autonomously
        while maintaining human oversight and control.""",
            "capabilities": [
                {
                    "name": "Local-First Intelligence",
                    "desc": "Checks local knowledge before external APIs",
                },
                {
                    "name": "Unified Knowledge Base",
                    "desc": "Single source of truth for all platform knowledge",
                },
                {
                    "name": "Automatic Learning",
                    "desc": "Learns from mistakes and improves over time",
                },
                {
                    "name": "Multi-Model AI Bridge",
                    "desc": "Routes to Ollama, Claude, OpenAI, Grok, Gemini",
                },
                {
                    "name": "Bridge Command Center",
                    "desc": "10-station architecture with IAAE compliance",
                },
                {
                    "name": "Conversation Triage",
                    "desc": "Auto-extracts knowledge from conversations",
                },
                {
                    "name": "NL Code Generation",
                    "desc": "Generate code from natural language descriptions",
                },
                {
                    "name": "Multi-Agent Code Review",
                    "desc": "4 specialized agents with consensus building",
                },
            ],
            "architecture": {
                "frontend": "Flask + Jinja2 Templates",
                "backend": "Python Flask with Blueprints",
                "database": "PostgreSQL with unified knowledge_base",
                "ai": "AI Bridge with multi-model routing",
                "deployment": "Docker Compose",
            },
            "docs_count": docs_count,
        }
    )


@blueprint_bp.route("/api/modules")
def get_modules():
    """Get all modules with their status"""
    if not REGISTRY_AVAILABLE:
        return jsonify({"error": "Module registry not available"}), 500

    modules = get_all_modules()

    # Categorize modules
    categories = {}
    for module in modules:
        cat_name = module.category.value
        if cat_name not in categories:
            categories[cat_name] = {
                "name": cat_name.replace("_", " ").title(),
                "modules": [],
            }

        # Determine status
        if module.coming_soon:
            status = "placeholder"
        elif module.beta:
            status = "beta"
        else:
            # Check if module has real implementation or just placeholder routes
            status = "live"

        # Check health
        health_status = "unknown"
        if module.health_check:
            try:
                health = module.health_check()
                health_status = "healthy" if health.get("healthy") else "unhealthy"
            except Exception:
                health_status = "error"

        categories[cat_name]["modules"].append(
            {
                "id": module.id,
                "name": module.name,
                "description": module.description.replace("<br>", " - "),
                "icon": module.icon,
                "route": module.route,
                "status": status,
                "health": health_status,
                "enabled": module.enabled,
                "minimum_role": module.minimum_role,
                "tags": module.tags,
            }
        )

    # Count stats
    total = len(modules)
    live = len([m for m in modules if not m.coming_soon and not m.beta])
    beta = len([m for m in modules if m.beta])
    placeholder = len([m for m in modules if m.coming_soon])

    return jsonify(
        {
            "categories": categories,
            "total": total,  # For header stats
            "stats": {
                "total": total,
                "live": live,
                "beta": beta,
                "placeholder": placeholder,
                "progress_percent": round((live / total) * 100) if total > 0 else 0,
            },
        }
    )


@blueprint_bp.route("/api/docs")
def get_docs():
    """Get knowledge base entries with search, filter, and sort.

    Query params:
        q       - text search across title and content
        type    - filter by knowledge_type (vault_note, code_snippet, etc.)
        category - filter by category
        tag     - filter by tag
        sort    - importance|recent|title|accessed (default: importance)
    """
    from database import get_db

    q = request.args.get("q", "").strip()
    kb_type = request.args.get("type", "").strip()
    category = request.args.get("category", "").strip()
    tag = request.args.get("tag", "").strip()
    sort = request.args.get("sort", "importance").strip()

    sort_map = {
        "importance": "importance_score DESC, updated_at DESC",
        "recent": "updated_at DESC",
        "title": "title ASC",
        "accessed": "access_count DESC, last_accessed DESC NULLS LAST",
    }
    order_by = sort_map.get(sort, sort_map["importance"])

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Build query
        conditions = []
        params = []

        if q:
            conditions.append("(title ILIKE %s OR content ILIKE %s)")
            params.extend([f"%{q}%", f"%{q}%"])
        if kb_type:
            conditions.append("knowledge_type = %s")
            params.append(kb_type)
        if category:
            conditions.append("category = %s")
            params.append(category)
        if tag:
            conditions.append("%s = ANY(tags)")
            params.append(tag)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        # Main query
        cur.execute(
            f"""
            SELECT id, title, knowledge_type, category, tags,
                   importance_score, access_count,
                   LEFT(content, 300) as preview,
                   LENGTH(content) as content_length,
                   created_at, updated_at, last_accessed
            FROM knowledge_base
            {where}
            ORDER BY {order_by}
            LIMIT 200
        """,
            params,
        )
        docs = cur.fetchall()

        # Facets: type counts
        cur.execute(
            """
            SELECT knowledge_type, COUNT(*) as cnt
            FROM knowledge_base
            GROUP BY knowledge_type
            ORDER BY cnt DESC
        """
        )
        type_facets = cur.fetchall()

        # Facets: category counts
        cur.execute(
            """
            SELECT category, COUNT(*) as cnt
            FROM knowledge_base
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY cnt DESC
        """
        )
        category_facets = cur.fetchall()

        cur.close()
        conn.close()

        # Serialize
        for doc in docs:
            for key in ("created_at", "updated_at", "last_accessed"):
                if doc.get(key):
                    doc[key] = doc[key].isoformat()
            if doc.get("importance_score") is not None:
                doc["importance_score"] = float(doc["importance_score"])

        return jsonify(
            {
                "docs": docs,
                "total": len(docs),
                "facets": {
                    "types": [{"type": f["knowledge_type"], "count": f["cnt"]} for f in type_facets],
                    "categories": [{"category": f["category"], "count": f["cnt"]} for f in category_facets],
                },
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint_bp.route("/api/docs/<int:doc_id>")
def get_doc_content_by_id(doc_id):
    """Get full content of a knowledge base entry by ID. Increments access_count."""
    from database import get_db

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Increment access count
        cur.execute(
            """
            UPDATE knowledge_base
            SET access_count = COALESCE(access_count, 0) + 1,
                last_accessed = NOW()
            WHERE id = %s
            RETURNING *
        """,
            (doc_id,),
        )
        doc = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not doc:
            return jsonify({"error": "Document not found"}), 404

        # Serialize
        for key in ("created_at", "updated_at", "last_accessed", "indexed_at"):
            if doc.get(key):
                doc[key] = doc[key].isoformat()
        if doc.get("importance_score") is not None:
            doc["importance_score"] = float(doc["importance_score"])
        if doc.get("memory_metadata") and isinstance(doc["memory_metadata"], str):
            try:
                doc["memory_metadata"] = json.loads(doc["memory_metadata"])
            except (json.JSONDecodeError, TypeError):
                pass

        return jsonify(doc)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint_bp.route("/api/docs/file/<filename>")
def get_doc_by_filename(filename):
    """Legacy compatibility: look up a knowledge_base entry by original filename."""
    from database import get_db

    title = filename.replace(".md", "").replace("_", " ")

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            UPDATE knowledge_base
            SET access_count = COALESCE(access_count, 0) + 1,
                last_accessed = NOW()
            WHERE title ILIKE %s
            RETURNING *
        """,
            (title,),
        )
        doc = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not doc:
            return jsonify({"error": "Document not found"}), 404

        for key in ("created_at", "updated_at", "last_accessed", "indexed_at"):
            if doc.get(key):
                doc[key] = doc[key].isoformat()
        if doc.get("importance_score") is not None:
            doc["importance_score"] = float(doc["importance_score"])

        return jsonify(
            {
                "filename": filename,
                "content": doc.get("content", ""),
                "size": len(doc.get("content", "")),
                "doc": doc,
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@blueprint_bp.route("/api/roadmap")
def get_roadmap():
    """Get project roadmap and progress - Comprehensive view of all A.R.C.H.I.E. development"""

    # Comprehensive roadmap based on /docs/ audit - Jan 13, 2026
    roadmap = {
        "sections": [
            {
                "title": "PLATFORM FOUNDATION",
                "icon": "🏗️",
                "phases": [
                    {
                        "name": "Phase 1: Database Schema Unification",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Single knowledge_base table (2,490+ entries)",
                                "done": True,
                            },
                            {"task": "Migrate from fragmented systems", "done": True},
                            {"task": "Helper functions and views", "done": True},
                            {"task": "Type-based organization (6 types)", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 2: Unified Brain Interface",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Admin dashboard at /tools/admin/brain",
                                "done": True,
                            },
                            {"task": "unified_knowledge_search.py", "done": True},
                            {
                                "task": "6 API routes for knowledge management",
                                "done": True,
                            },
                            {"task": "Type-weighted ranking system", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 3: AI Bridge Local-First",
                        "status": "complete",
                        "items": [
                            {
                                "task": "knowledge_retrieval.py integration",
                                "done": True,
                            },
                            {
                                "task": "3-step retrieval: mistakes → knowledge → memory",
                                "done": True,
                            },
                            {
                                "task": "Local knowledge checked BEFORE external APIs",
                                "done": True,
                            },
                            {"task": "4-6x faster queries, cost savings", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 4: Mistake Learning & Prevention",
                        "status": "complete",
                        "items": [
                            {
                                "task": "mistake_detector.py with 14 error patterns",
                                "done": True,
                            },
                            {"task": "Flask error handler integration", "done": True},
                            {
                                "task": "Automatic learning from exceptions",
                                "done": True,
                            },
                            {
                                "task": "4 API routes for mistake management",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 4.5: Claude Code Integration",
                        "status": "complete",
                        "items": [
                            {"task": "PreCompact & SessionEnd hooks", "done": True},
                            {"task": "Conversation monitoring & saving", "done": True},
                            {"task": "Git worktrees structure", "done": True},
                            {"task": "CLAUDE.md project memory", "done": True},
                        ],
                    },
                ],
            },
            {
                "title": "IMPROVEMENT WORKFLOW (v4.0)",
                "icon": "🔧",
                "phases": [
                    {
                        "name": "Workflow Phase 1: Foundation",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Database migration (5 tables, 8 columns, 12 indexes)",
                                "done": True,
                            },
                            {
                                "task": "Stuck proposal detection & auto-escalation",
                                "done": True,
                            },
                            {"task": "Team assignment engine skeleton", "done": True},
                            {"task": "Notification system integration", "done": True},
                        ],
                    },
                    {
                        "name": "Workflow Phase 2: Enhanced Chat",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Natural language proposal creation",
                                "done": True,
                            },
                            {
                                "task": "Code diff engine with syntax highlighting",
                                "done": True,
                            },
                            {"task": "Step-by-step guidance generator", "done": True},
                            {"task": "4 new API endpoints", "done": True},
                        ],
                    },
                    {
                        "name": "Workflow Phase 3: Team Assignment",
                        "status": "complete",
                        "items": [
                            {"task": "team_assignment_engine.py (18K)", "done": True},
                            {
                                "task": "Internal-first routing (90% internal usage)",
                                "done": True,
                            },
                            {"task": "Skill-based matching", "done": True},
                            {"task": "6 team management API endpoints", "done": True},
                        ],
                    },
                    {
                        "name": "Workflow Phase 4: Sandbox System",
                        "status": "complete",
                        "items": [
                            {
                                "task": "sandbox_manager.py orchestrator (26K)",
                                "done": True,
                            },
                            {
                                "task": "Schema-based sandboxes (122 tables, <1s)",
                                "done": True,
                            },
                            {
                                "task": "Docker-based sandboxes for high-risk",
                                "done": True,
                            },
                            {
                                "task": "Test runner (syntax, security, health)",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Workflow Phase 5: Deployment Pipeline",
                        "status": "complete",
                        "items": [
                            {"task": "safe_deployment_protocol.py (20K)", "done": True},
                            {
                                "task": "deployment_decision.py risk assessment",
                                "done": True,
                            },
                            {"task": "Pre-deployment backup automation", "done": True},
                            {
                                "task": "deployment_monitor.py (24hr monitoring)",
                                "done": True,
                            },
                            {
                                "task": "Deploy-to-production with issue tracking",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Workflow Phase 6: Full Integration",
                        "status": "complete",
                        "items": [
                            {
                                "task": "CodeRabbit → Improvements Lab flow",
                                "done": True,
                            },
                            {
                                "task": "Send to Improvements button with duplicate prevention",
                                "done": True,
                            },
                            {
                                "task": "Per-module sandbox architecture (6 sandboxes)",
                                "done": True,
                            },
                            {
                                "task": "Sandbox Manager UI with visual access",
                                "done": True,
                            },
                            {
                                "task": "Full workflow: scan → proposal → test → deploy → fixed",
                                "done": True,
                            },
                            {
                                "task": "Issue status tracking (fixed_at, fixed_by)",
                                "done": True,
                            },
                            {"task": "code_fixes audit trail", "done": True},
                        ],
                    },
                    {
                        "name": "Workflow Phase 7: UI Polish",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Status filter dropdown (12 statuses)",
                                "done": True,
                            },
                            {
                                "task": "Delete proposal button with cascade",
                                "done": True,
                            },
                            {
                                "task": "Confirmation dialogs with proposal titles",
                                "done": True,
                            },
                            {"task": "Database cleanup tools", "done": True},
                        ],
                    },
                    {
                        "name": "Workflow Phase 8: Test Retry Loop + Contractor Escalation",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Database migration 025 (retry tracking, escalation, chat)",
                                "done": True,
                            },
                            {
                                "task": "test_retry_handler.py (automatic retry up to 3x)",
                                "done": True,
                            },
                            {
                                "task": "Contractor routing in archie_bridge.py",
                                "done": True,
                            },
                            {
                                "task": "chat_handler.py for fluid human-contractor chat",
                                "done": True,
                            },
                            {
                                "task": "Strict queue enforcement (one proposal at a time)",
                                "done": True,
                            },
                            {
                                "task": "10 new API endpoints for retry/escalation/chat",
                                "done": True,
                            },
                            {
                                "task": "Agent personality system (personality_prompt, communication_style)",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Workflow Phase 9: Improvements Lab UI Rebuild",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Refactor from 4,340 lines to modular architecture",
                                "done": True,
                            },
                            {
                                "task": "Create api.js - centralized API calls (304 lines)",
                                "done": True,
                            },
                            {
                                "task": "Create ui.js - notifications, modals, utilities (431 lines)",
                                "done": True,
                            },
                            {
                                "task": "Create app.js - state management, 25 async functions (965 lines)",
                                "done": True,
                            },
                            {"task": "Slim HTML template (291 lines)", "done": True},
                            {
                                "task": "Proposal list with filters and cards",
                                "done": True,
                            },
                            {"task": "Sandbox viewer with test controls", "done": True},
                            {
                                "task": "Contractor chat panel with escalation",
                                "done": True,
                            },
                            {"task": "Queue status display", "done": True},
                            {"task": "All button interactions wired up", "done": True},
                        ],
                    },
                    {
                        "name": "Workflow Phase 10: Team Management UI Updates",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Add personality prompt editor for agents",
                                "done": True,
                            },
                            {"task": "Add communication style selector", "done": True},
                            {
                                "task": "Show agent work history on proposals",
                                "done": True,
                            },
                            {
                                "task": "Display contractor API status and availability",
                                "done": True,
                            },
                            {
                                "task": "Integration with escalation workflow",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Workflow Phase 11: Backup Manager v2",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Consolidate duplicate backup_manager files",
                                "done": True,
                            },
                            {
                                "task": "Fix path constants for modular architecture",
                                "done": True,
                            },
                            {
                                "task": "Add programmatic create_backup() function",
                                "done": True,
                            },
                            {
                                "task": "Add backup_module() for module-level backups",
                                "done": True,
                            },
                            {
                                "task": "Add get_module_dependencies() helper",
                                "done": True,
                            },
                            {
                                "task": "Fix imports in improvements/routes.py",
                                "done": True,
                            },
                            {
                                "task": "Fix imports in safe_deployment_protocol.py",
                                "done": True,
                            },
                            {"task": "Delete old backup_manager.py", "done": True},
                            {
                                "task": "Create /docs/BACKUP_MANAGER_GUIDE.md",
                                "done": True,
                            },
                            {
                                "task": "Add API endpoints for module backups",
                                "done": True,
                            },
                            {
                                "task": "Fix build number tracking (read/write from .current_build)",
                                "done": True,
                            },
                            {
                                "task": "Implement backup types (full/critical/database/custom)",
                                "done": True,
                            },
                            {
                                "task": "Add Module Backups UI section (purple themed)",
                                "done": True,
                            },
                            {
                                "task": "Add all 11 components backup (was missing 6)",
                                "done": True,
                            },
                            {
                                "task": "Fix docker volume mounts for full backup access",
                                "done": True,
                            },
                            {
                                "task": "Verify disaster recovery (58MB, 264 tables)",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Workflow Phase 12: Improvements Lab Workflow Fixes",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Fix execute endpoint (400 error on empty body)",
                                "done": True,
                            },
                            {
                                "task": "Add Regenerate Plan button for legacy proposals",
                                "done": True,
                            },
                            {
                                "task": "Fix AI code parser for markdown format",
                                "done": True,
                            },
                            {
                                "task": "Fix Security Scan test (check recent files only)",
                                "done": True,
                            },
                            {
                                "task": "Fix test status logic (required vs non-required)",
                                "done": True,
                            },
                            {
                                "task": "Fix Logs endpoint to show test results",
                                "done": True,
                            },
                            {
                                "task": "Fix deploy test_status check (wrong column)",
                                "done": True,
                            },
                            {
                                "task": "Implement actual code deployment (was stub)",
                                "done": True,
                            },
                            {"task": "Fix container path mapping", "done": True},
                            {"task": "Test full deploy to production", "done": True},
                        ],
                    },
                    {
                        "name": "Workflow Phase 13: External Watchdog Auto-Rollback",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Create POSIX shell watchdog script",
                                "done": True,
                            },
                            {
                                "task": "Watchdog runs in docker:cli container",
                                "done": True,
                            },
                            {
                                "task": "Crash loop detection (restarting status)",
                                "done": True,
                            },
                            {
                                "task": "Sustained healthy check (20s requirement)",
                                "done": True,
                            },
                            {
                                "task": "Auto-restore from backup using modified_files",
                                "done": True,
                            },
                            {"task": "Database rollback status updates", "done": True},
                            {
                                "task": "Restart endpoint launches external watchdog",
                                "done": True,
                            },
                            {
                                "task": "Test with intentional crash - SUCCESS",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Workflow Phase 14: CodeRabbit Integration Fix",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Fix AI-generated fixes to match actual code",
                                "done": True,
                            },
                            {
                                "task": "Read actual file content before generating fix",
                                "done": True,
                            },
                            {
                                "task": "Validate paths (Docker + host) before generating",
                                "done": True,
                            },
                            {"task": "Strip line numbers from AI output", "done": True},
                            {
                                "task": "Feedback loop: deploy success → mark issue fixed",
                                "done": True,
                            },
                            {
                                "task": "End-to-end test: CodeRabbit → Deploy verified",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Workflow Phase 15: Team Management Personality System",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Add personality prompt editor textarea",
                                "done": True,
                            },
                            {
                                "task": "Add communication style selector dropdown",
                                "done": True,
                            },
                            {
                                "task": "Show agent work history (proposals, discussions)",
                                "done": True,
                            },
                            {
                                "task": "Display contractor API status for contract agents",
                                "done": True,
                            },
                            {
                                "task": "Add /api/agents/<id>/work-history endpoint",
                                "done": True,
                            },
                            {
                                "task": "Add /api/agents/<id>/contractor-status endpoint",
                                "done": True,
                            },
                            {
                                "task": "Integration with escalation workflow ready",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 16: V2 Code Generation Engine",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Implement Architect/Editor pattern for 85% accuracy",
                                "done": True,
                            },
                            {
                                "task": "Add syntax validation (ast.parse + py_compile)",
                                "done": True,
                            },
                            {"task": "Add content matching verification", "done": True},
                            {
                                "task": "Add smart snippet validation for except/else blocks",
                                "done": True,
                            },
                            {
                                "task": "Add retry logic with error feedback (max 3)",
                                "done": True,
                            },
                            {
                                "task": "Add Team Management integration (prefer_contractor)",
                                "done": True,
                            },
                            {
                                "task": "Fix code_application_system to fail on mismatch",
                                "done": True,
                            },
                            {
                                "task": "Create CODE_GENERATION_ENGINE_V2.md documentation",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 17: Team Skills & HR Dashboard",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Create migration to populate agent_skills table (959 records)",
                                "done": True,
                            },
                            {
                                "task": "Map models to skill strengths (18 model mappings)",
                                "done": True,
                            },
                            {
                                "task": "Add Skills API endpoints (8 new routes)",
                                "done": True,
                            },
                            {
                                "task": "Add Skills tab to Team Management UI",
                                "done": True,
                            },
                            {
                                "task": "Add HR Dashboard tab with model performance comparison",
                                "done": True,
                            },
                            {
                                "task": "Skills matrix view (agents x skills)",
                                "done": True,
                            },
                            {"task": "Skill gaps identification", "done": True},
                            {
                                "task": "Skill-based recommendations engine",
                                "done": True,
                            },
                            {
                                "task": "Integrate skills with V2 code generation model selection",
                                "done": True,
                            },
                            {
                                "task": "Update A.R.C.H.I.E. Blueprints with Phase 16/17",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 18: CodeRabbit v2.0.0 Optimization",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Add proposal_id column to code_issues table",
                                "done": True,
                            },
                            {
                                "task": "Fix git commit parameter mismatch (stage_all)",
                                "done": True,
                            },
                            {
                                "task": "Add modified file detection (mtime comparison)",
                                "done": True,
                            },
                            {
                                "task": 'Add "Rescan Modified" batch button',
                                "done": True,
                            },
                            {
                                "task": "Add bidirectional issue tracking with proposals",
                                "done": True,
                            },
                            {
                                "task": "Add status-aware proposal badges in Issues tab",
                                "done": True,
                            },
                            {
                                "task": "Add CodeRabbit review status on PRs",
                                "done": True,
                            },
                            {
                                "task": 'Add "Request Review" button for PRs',
                                "done": True,
                            },
                            {
                                "task": "Add sessionStorage scan cache persistence",
                                "done": True,
                            },
                            {"task": "Fix folder toggle quote escaping", "done": True},
                            {
                                "task": "Update CODERABBIT_MODULE.md to v2.0.0",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 19: PR Workflow & Git Hooks",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Create .coderabbit.yaml for auto-reviews on main/develop",
                                "done": True,
                            },
                            {
                                "task": "Create pre-push git hook for protected branches",
                                "done": True,
                            },
                            {
                                "task": "Create install-git-hooks.sh script",
                                "done": True,
                            },
                            {
                                "task": "Create PR_WORKFLOW_CODERABBIT.md documentation",
                                "done": True,
                            },
                            {
                                "task": "Test CodeRabbit auto-review on PR #3",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 20: CodeRabbit → Improvements Lab Integration",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Add /api/pr/<number>/review-comments endpoint",
                                "done": True,
                            },
                            {
                                "task": "Add /api/pr/suggestions-to-improvements endpoint",
                                "done": True,
                            },
                            {
                                "task": "Add /api/pr/<number>/merge endpoint",
                                "done": True,
                            },
                            {"task": "Add /api/git/create-pr endpoint", "done": True},
                            {
                                "task": "Add Create PR section in Local Git tab",
                                "done": True,
                            },
                            {
                                "task": "Add Suggestions button on reviewed PRs",
                                "done": True,
                            },
                            {
                                "task": "Add suggestions modal with checkboxes",
                                "done": True,
                            },
                            {"task": "Add Merge PR button on open PRs", "done": True},
                            {
                                "task": "Auto-categorize suggestions (security, performance, etc.)",
                                "done": True,
                            },
                            {
                                "task": "Track PR context in proposals (pr_number, pr_url)",
                                "done": True,
                            },
                            {
                                "task": "Test full workflow: PR → Review → Proposal",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 21: Git Manager Consolidation",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Disable GitHub Manager module (set enabled=False)",
                                "done": True,
                            },
                            {
                                "task": 'Rename "Local Git" tab to "Git Manager"',
                                "done": True,
                            },
                            {"task": "Add /api/git/branches endpoint", "done": True},
                            {
                                "task": "Add /api/git/create-branch endpoint",
                                "done": True,
                            },
                            {"task": "Add /api/git/checkout endpoint", "done": True},
                            {
                                "task": "Add /api/git/delete-branch endpoint",
                                "done": True,
                            },
                            {"task": "Add branch selector dropdown UI", "done": True},
                            {
                                "task": "Add branch list with delete buttons",
                                "done": True,
                            },
                            {"task": "Add Create Branch modal", "done": True},
                            {
                                "task": "Add GitHub Issues tab (list, create, close/reopen)",
                                "done": True,
                            },
                            {
                                "task": "Add GitHub Actions tab (runs, workflows, re-run)",
                                "done": True,
                            },
                            {
                                "task": "Add protected branch enforcement (main, master, develop)",
                                "done": True,
                            },
                            {
                                "task": "Update CODERABBIT_MODULE.md to v2.2.0",
                                "done": True,
                            },
                            {"task": "Update MODULE_REGISTRY_STATUS.md", "done": True},
                            {
                                "task": "Add CI workflow (.github/workflows/ci.yml)",
                                "done": True,
                            },
                            {"task": "CI: Lint & Syntax Check job", "done": True},
                            {"task": "CI: Security Scan job (Bandit)", "done": True},
                            {"task": "CI: Docker Build Test job", "done": True},
                            {
                                "task": "Test GitHub Actions tab with live workflow runs",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 22: Dashboard Layout Restructuring",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Move A.R.C.H.I.E. Chat to STANDALONE_APPS",
                                "done": True,
                            },
                            {
                                "task": "Disable Code Editor (replaced by Website Designer)",
                                "done": True,
                            },
                            {
                                "task": "Disable Business Directory (now tab in Website Designer)",
                                "done": True,
                            },
                            {
                                "task": "Move Improvements Lab to DEVELOPMENT (admin only)",
                                "done": True,
                            },
                            {
                                "task": "Move Sandbox Manager to DEVELOPMENT (admin only)",
                                "done": True,
                            },
                            {
                                "task": "Rename Website Studio → Website Designer",
                                "done": True,
                            },
                            {
                                "task": "DEVELOPMENT category RED styling (#FF6B6B)",
                                "done": True,
                            },
                            {
                                "task": "ADMIN category RED styling (#FF6B6B) - matching DEVELOPMENT",
                                "done": True,
                            },
                            {
                                "task": "ADMIN ONLY badge on DEVELOPMENT section",
                                "done": True,
                            },
                            {
                                "task": "Add Code View tab (Monaco-style editor)",
                                "done": True,
                            },
                            {
                                "task": "Add Preview tab (live HTML preview)",
                                "done": True,
                            },
                            {
                                "task": "Add Business Directory tab (admin: AI team, users: personal)",
                                "done": True,
                            },
                            {
                                "task": "Add Git tab (commit, push, pull, history)",
                                "done": True,
                            },
                            {
                                "task": "Add Domains tab (Hostinger DNS management)",
                                "done": True,
                            },
                            {
                                "task": "Create hostinger_integration.py API wrapper",
                                "done": True,
                            },
                            {
                                "task": "Add DNS presets (GitHub Pages, Vercel, Netlify)",
                                "done": True,
                            },
                            {
                                "task": "Per-user Business Directory for non-admin users",
                                "done": True,
                            },
                            {
                                "task": "Update MASTER_STATUS_AND_ROADMAP_2026.md",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 23: Sandbox System Completion",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Verify Migration 007 (sandbox_test_suites, sandbox_test_results)",
                                "done": True,
                            },
                            {
                                "task": "Verify Migration 020 (module_sandboxes, sandbox_config)",
                                "done": True,
                            },
                            {
                                "task": "Create Migration 021 (improvement_deployments enhancement)",
                                "done": True,
                            },
                            {
                                "task": "Sandbox Manager template verified (1169 lines)",
                                "done": True,
                            },
                            {
                                "task": "Auto-backup on deploy-to-production",
                                "done": True,
                            },
                            {
                                "task": "Deployment tracking in improvement_deployments",
                                "done": True,
                            },
                            {"task": "Post-deployment health checks", "done": True},
                            {
                                "task": "Auto-sandbox creation on proposal approval",
                                "done": True,
                            },
                            {"task": "Module detection from file paths", "done": True},
                            {
                                "task": "v_recent_improvement_deployments view",
                                "done": True,
                            },
                            {
                                "task": "v_improvement_deployment_stats view",
                                "done": True,
                            },
                            {
                                "task": "AI Bridge environment awareness (sandbox/production)",
                                "done": True,
                            },
                            {
                                "task": "Auto-restart container after Python deployments",
                                "done": True,
                            },
                            {
                                "task": "Deployment status tracking (success/failed)",
                                "done": True,
                            },
                            {
                                "task": "PR review feedback loop (unified with scan issues)",
                                "done": True,
                            },
                            {
                                "task": "CodeRabbit → Improvements → Deploy → Fixed workflow",
                                "done": True,
                            },
                            {
                                "task": "Sandbox Manager UI modernization (match CodeRabbit/Improvements Lab)",
                                "done": True,
                            },
                            {
                                "task": "Tab navigation: Environments, Test Results, Deployments, Config",
                                "done": True,
                            },
                            {
                                "task": "Schema/Docker type badges with visual distinction",
                                "done": True,
                            },
                            {
                                "task": "API endpoints: /api/test-results, /api/deployments",
                                "done": True,
                            },
                            {"task": "Update Blueprint with Phase 23", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 24: Backup Manager Integration",
                        "status": "complete",
                        "items": [
                            {
                                "task": "UI Modernization (match CodeRabbit/Improvements Lab style)",
                                "done": True,
                            },
                            {
                                "task": "Tab navigation: Backups, Deployment Backups, Modules, Retention",
                                "done": True,
                            },
                            {
                                "task": "Deployment Backups tab (show improvement_deployments backups)",
                                "done": True,
                            },
                            {
                                "task": "Cross-module navigation links (Sandbox, Improvements, CodeRabbit)",
                                "done": True,
                            },
                            {
                                "task": "API endpoint: /api/deployment-backups",
                                "done": True,
                            },
                            {"task": "Stats grid with deployment count", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 31: Business Tools UI Standardization",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Social Media module redesign (Neo-Command Center theme)",
                                "done": True,
                            },
                            {
                                "task": "Website Studio module redesign (matching theme)",
                                "done": True,
                            },
                            {
                                "task": "Business Tools navigation bar (pink theme #FF69B4)",
                                "done": True,
                            },
                            {
                                "task": "Call Center module redesign (~2,000 lines)",
                                "done": True,
                            },
                            {
                                "task": "CRM module redesign (~1,884 lines)",
                                "done": True,
                            },
                            {
                                "task": "Email Manager module redesign (~2,160 lines)",
                                "done": True,
                            },
                            {
                                "task": "Toast notifications replacing alert() calls",
                                "done": True,
                            },
                            {"task": "Light/dark mode toggle support", "done": True},
                            {
                                "task": "Responsive design for mobile devices",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 25: Website Designer Improvements",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Create chat_handler.py for chat-to-code pipeline",
                                "done": True,
                            },
                            {
                                "task": "POST /api/chat endpoint for A.R.C.H.I.E. conversations",
                                "done": True,
                            },
                            {
                                "task": "POST /api/apply-changes for AI-generated edits",
                                "done": True,
                            },
                            {
                                "task": "POST /api/deploy-to-github-pages one-click deploy",
                                "done": True,
                            },
                            {
                                "task": "GET /api/preview for live HTML preview",
                                "done": True,
                            },
                            {
                                "task": "GET/POST /api/chat/history for conversation persistence",
                                "done": True,
                            },
                            {
                                "task": "Dark cyberpunk theme matching platform style",
                                "done": True,
                            },
                            {
                                "task": "Tab navigation: Chat Designer, Projects, Git",
                                "done": True,
                            },
                            {
                                "task": "Create UI_STYLE_GUIDE.md documentation",
                                "done": True,
                            },
                            {
                                "task": "Create WEBSITE_DESIGNER_MODULE.md documentation",
                                "done": True,
                            },
                            {
                                "task": "Fix Preview panel display issues (min-height, loading state)",
                                "done": True,
                            },
                            {
                                "task": "Improve file/folder selection UI (tree view, icons)",
                                "done": True,
                            },
                            {
                                "task": "Git tab detail improvements (dynamic repo info, fetch, better UI)",
                                "done": True,
                            },
                            {
                                "task": "Monaco Editor integration for syntax highlighting",
                                "done": True,
                            },
                            {
                                "task": "Layout reorganization (stacked Preview + Code)",
                                "done": True,
                            },
                            {
                                "task": "File selection bar with tabs and actions",
                                "done": True,
                            },
                            {"task": "Language badge showing file type", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 25b: Bootstrap Compatibility Restoration",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Add Bootstrap 5.3.2 CSS to base.html",
                                "done": True,
                            },
                            {
                                "task": "Add Bootstrap Icons 1.11.1 to base.html",
                                "done": True,
                            },
                            {
                                "task": "Add Bootstrap JS bundle to base.html",
                                "done": True,
                            },
                            {
                                "task": "Add extra_head, extra_css, extra_js template blocks",
                                "done": True,
                            },
                            {"task": "Fix Invoicing module layout", "done": True},
                            {"task": "Fix Scheduler module layout", "done": True},
                            {"task": "Fix Automations module layout", "done": True},
                            {"task": "Fix Analytics module layout", "done": True},
                            {"task": "Fix Store Builder module layout", "done": True},
                        ],
                    },
                ],
            },
            {
                "title": "MODULE DEVELOPMENT",
                "icon": "📦",
                "phases": [
                    {
                        "name": "Phase 5: Module Consolidation",
                        "status": "complete",
                        "items": [
                            {"task": "Consolidate duplicate modules", "done": True},
                            {"task": "Add STANDALONE_APPS category", "done": True},
                            {"task": "Add BUSINESS_TOOLS category", "done": True},
                            {"task": "Module registry with 32 modules", "done": True},
                            {"task": "A.R.C.H.I.E. Blueprint module", "done": True},
                            {
                                "task": "CodeRabbit module with GitHub integration",
                                "done": True,
                            },
                            {
                                "task": "CodeRabbit dashboard with live PR stats",
                                "done": True,
                            },
                            {
                                "task": "GitHub repo connected (archie-platform)",
                                "done": True,
                            },
                            {
                                "task": "Code Health Scanner with AI + Static analysis",
                                "done": True,
                            },
                            {
                                "task": "File scanning with Ollama integration",
                                "done": True,
                            },
                            {
                                "task": "Collapsible folder UI with pass/scan stats",
                                "done": True,
                            },
                            {
                                "task": "Batch scanning (Scan All with progress)",
                                "done": True,
                            },
                            {
                                "task": "Scan results persistence in database",
                                "done": True,
                            },
                            {
                                "task": "Knowledge base integration for learning",
                                "done": True,
                            },
                            {
                                "task": "Auto-create improvement proposals for critical issues",
                                "done": True,
                            },
                            {"task": "Fix audit trail (who/when/what)", "done": True},
                            {
                                "task": "Documentation audit (60 files reviewed)",
                                "done": True,
                            },
                            {"task": "Archive obsolete docs (12 files)", "done": True},
                            {"task": "Update admin panel references", "done": True},
                            {
                                "task": "Fix Claude Code hooks configuration",
                                "done": True,
                            },
                            {"task": "Implement Project Builder UI", "done": True},
                            {"task": "Implement Media Studio UI", "done": True},
                            {
                                "task": "Creation Tools nav bar (orange theme)",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 6: Business Tools Integration",
                        "status": "complete",
                        "items": [
                            {
                                "task": "CRM Module - Customer database with subscription tracking",
                                "done": True,
                            },
                            {
                                "task": "Email Manager - Communications hub (templates, SMTP, logs)",
                                "done": True,
                            },
                            {
                                "task": "Invoicing Module - Subscription billing with Stripe/PDF",
                                "done": True,
                            },
                            {
                                "task": "Scheduler Module - Calendar & subscription renewals",
                                "done": True,
                            },
                            {
                                "task": "Analytics Module - Unified metrics dashboard",
                                "done": True,
                            },
                            {
                                "task": "Automations Module - N8N visual workflow builder",
                                "done": True,
                            },
                            {
                                "task": "Social Media Module - Command center (FB/IG/TikTok/LinkedIn/YouTube)",
                                "done": True,
                            },
                            {
                                "task": "Call Center - TELUS Biz Connect 1-800 setup",
                                "done": True,
                            },
                            {
                                "task": "Store + Website integration for embeddable widgets",
                                "done": True,
                            },
                            {
                                "task": "STORE.KytranEmpowerment.com deployment",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 7: Standalone Apps",
                        "status": "complete",
                        "items": [
                            {"task": "DOC - Medical AI assistant", "done": True},
                            {"task": "Therapy - Mental health AI", "done": True},
                            {"task": "Fitness - AI fitness coach", "done": True},
                            {"task": "StockBot - AI stock screener", "done": True},
                            {"task": "Archie Pool user dashboard", "done": True},
                            {"task": "Pool Management admin interface", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 8: Advanced Development Tools",
                        "status": "complete",
                        "items": [
                            {
                                "task": "IDE Integration module (Cursor AI, OpenCode, VS Code, MCP)",
                                "done": True,
                            },
                            {
                                "task": "MCP Protocol support for AI assistants",
                                "done": True,
                            },
                            {
                                "task": "Session management for IDE connections",
                                "done": True,
                            },
                            {
                                "task": "Testing Suite module with test discovery",
                                "done": True,
                            },
                            {
                                "task": "Automated regression testing runner",
                                "done": True,
                            },
                            {
                                "task": "Performance benchmarking (API, database, modules)",
                                "done": True,
                            },
                            {
                                "task": "Multi-Agent Code Review in CodeRabbit",
                                "done": True,
                            },
                            {
                                "task": "4 specialized review agents with consensus building",
                                "done": True,
                            },
                            {
                                "task": "Natural Language Code Generator (nl_code_generator.py)",
                                "done": True,
                            },
                            {
                                "task": "NL-to-code API endpoints in Code Editor",
                                "done": True,
                            },
                            {
                                "task": "Intent classification (create, modify, fix, explain, convert)",
                                "done": True,
                            },
                        ],
                    },
                ],
            },
            {
                "title": "FUTURE FEATURES",
                "icon": "🚀",
                "phases": [
                    {
                        "name": "Phase 26: A.R.C.H.I.E. Bridge - Core UI",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Create /tools/bridge/ route and blueprint",
                                "done": True,
                            },
                            {
                                "task": "Design Bridge template with station layout",
                                "done": True,
                            },
                            {
                                "task": "Real-time stats (LLM status, active requests, load)",
                                "done": True,
                            },
                            {"task": "Station cards with agent avatars", "done": True},
                            {"task": "Captain/First Officer status bar", "done": True},
                            {
                                "task": "Click station -> navigate to modules",
                                "done": True,
                            },
                            {"task": "Dark cyberpunk theme", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 27: A.R.C.H.I.E. Bridge - LLM Monitor",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Create llm_connections database table (migration 022)",
                                "done": True,
                            },
                            {
                                "task": "Health check background service (llm_monitor.py)",
                                "done": True,
                            },
                            {
                                "task": "Provider-specific checks (Ollama, Claude, OpenAI, Grok, Gemini)",
                                "done": True,
                            },
                            {"task": "Connection status API endpoints", "done": True},
                            {
                                "task": "LLM Connections Monitor panel (Providers/Models/Alerts tabs)",
                                "done": True,
                            },
                            {
                                "task": "Alert system for connection failures",
                                "done": True,
                            },
                            {
                                "task": "Bridge icon updated to 🎛️ (control panel)",
                                "done": True,
                            },
                            {
                                "task": "Admin Ops modules display with red styling on dashboard",
                                "done": True,
                            },
                            {
                                "task": "Naming standardized to Consciousness",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 28: A.R.C.H.I.E. Bridge - Station Assignment",
                        "status": "complete",
                        "items": [
                            {"task": "Create bridge_stations table", "done": True},
                            {"task": "Create station_assignments table", "done": True},
                            {"task": "Drag-and-drop agent assignment UI", "done": True},
                            {"task": "Station configuration modal", "done": True},
                            {"task": "Integration with Team Management", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 29: A.R.C.H.I.E. Bridge - VPN Remote Nodes",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Design remote node client architecture",
                                "done": True,
                            },
                            {"task": "VPN connection management", "done": True},
                            {
                                "task": "Node registration & authentication",
                                "done": True,
                            },
                            {"task": "Version enforcement system", "done": True},
                            {"task": "Load balancing across nodes", "done": True},
                            {"task": "Failover handling", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 30: Mining Pool Integration",
                        "status": "complete",
                        "items": [
                            {"task": "Review mining pool documentation", "done": True},
                            {
                                "task": "Design dual-purpose scheduler (AI + Mining)",
                                "done": True,
                            },
                            {
                                "task": "Integrate with Bridge for resource management",
                                "done": True,
                            },
                            {"task": "Contributor reward system", "done": True},
                            {
                                "task": "Blockchain authentication (optional)",
                                "done": True,
                            },
                        ],
                    },
                    # ==================== IAAE GOVERNANCE PHASES ====================
                    {
                        "name": "Phase 31: Bridge Station Restructure",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Expand Bridge from 5 to 10 stations",
                                "done": True,
                            },
                            {
                                "task": "Create bridge_stations table with seed data",
                                "done": True,
                            },
                            {
                                "task": "Update Bridge UI template for 3-row layout",
                                "done": True,
                            },
                            {"task": "Add station configuration APIs", "done": True},
                            {
                                "task": "Create BRIDGE_STATION_ARCHITECTURE.md",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 32: Per-Agent Memory Tables",
                        "status": "complete",
                        "items": [
                            {"task": "Create agent_memory table", "done": True},
                            {
                                "task": "Implement soft-delete with IAAE compliance",
                                "done": True,
                            },
                            {
                                "task": "Add memory CRUD endpoints (6 endpoints)",
                                "done": True,
                            },
                            {"task": "Soft-delete using DB function", "done": True},
                            {"task": "Memory restore endpoint", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 33: Agent Emotional State Tracking",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Create agent_emotional_state table",
                                "done": True,
                            },
                            {
                                "task": "Implement bounds checking (0.1-1.0 energy, 0-0.9 stress)",
                                "done": True,
                            },
                            {
                                "task": "Add automatic interventions (rest triggers)",
                                "done": True,
                            },
                            {
                                "task": "Create emotional dashboard widget in IAAE tab",
                                "done": True,
                            },
                            {
                                "task": "History endpoint with configurable days",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 34: IAAE Ethics Constraints",
                        "status": "complete",
                        "items": [
                            {"task": "Create ethics_constraints table", "done": True},
                            {"task": "Seed 13 default constraints", "done": True},
                            {"task": "Implement constraint checking API", "done": True},
                            {
                                "task": "Add ethics constraint management UI",
                                "done": True,
                            },
                            {
                                "task": "Create IAAE_GOVERNANCE_FRAMEWORK.md",
                                "done": True,
                            },
                            {"task": "CRUD endpoints for constraints", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 35: Governance Audit System",
                        "status": "complete",
                        "items": [
                            {"task": "Create governance_audit_log table", "done": True},
                            {
                                "task": "Implement logging for all IAAE events",
                                "done": True,
                            },
                            {"task": "Create audit log viewer UI", "done": True},
                            {"task": "Add compliance reporting via API", "done": True},
                            {
                                "task": "Filter by category, pagination support",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 36: Rest Cycle Implementation",
                        "status": "complete",
                        "items": [
                            {"task": "Create agent_rest_cycles table", "done": True},
                            {
                                "task": "Implement automatic rest triggers via DB function",
                                "done": True,
                            },
                            {
                                "task": "Add rest cycle management API (start/end)",
                                "done": True,
                            },
                            {"task": "Create monitoring in IAAE tab", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 37: Task Refusal System",
                        "status": "complete",
                        "items": [
                            {"task": "Create task_refusal_log table", "done": True},
                            {
                                "task": "Implement refusal conditions via constraints",
                                "done": True,
                            },
                            {
                                "task": "Add override workflow with justification",
                                "done": True,
                            },
                            {"task": "Create refusal analytics endpoint", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 38: Ethics Agent Deployment",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Create ATHENA Ethics Watchdog agent (ID: 83)",
                                "done": True,
                            },
                            {
                                "task": "Create ethics_monitor.py module (~450 lines)",
                                "done": True,
                            },
                            {
                                "task": "Implement monitoring routines with thresholds",
                                "done": True,
                            },
                            {"task": "Set up weekly compliance reports", "done": True},
                            {
                                "task": "Configure alert triggers (stress, energy, rest)",
                                "done": True,
                            },
                            {
                                "task": "Add 15 ethics monitoring API endpoints",
                                "done": True,
                            },
                            {
                                "task": "Create Ethics Monitor sub-tab in IAAE",
                                "done": True,
                            },
                            {
                                "task": "Database migration: ethics tables + functions",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 39: Station Assignment UI",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Create drag-and-drop assignment interface (HTML5)",
                                "done": True,
                            },
                            {
                                "task": "Command Station: ARCHIE + Kytran fixed, Assistant/Backup slots",
                                "done": True,
                            },
                            {
                                "task": "9-station grid (3x3) with drag-drop zones",
                                "done": True,
                            },
                            {
                                "task": "Training Room with skill picker modal (201 skills)",
                                "done": True,
                            },
                            {
                                "task": "Lounge Area integrated with IAAE rest cycles",
                                "done": True,
                            },
                            {"task": "Unassigned Pool table at bottom", "done": True},
                            {
                                "task": "IAAE compliance pre-check on all moves",
                                "done": True,
                            },
                            {
                                "task": "9 new API endpoints (drag-drop, training, lounge)",
                                "done": True,
                            },
                            {
                                "task": "Database: training_assignments table, views",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 40: IAAE Compliance Dashboard",
                        "status": "complete",
                        "items": [
                            {"task": "Add IAAE tab to Team Management", "done": True},
                            {
                                "task": "Create compliance status indicators",
                                "done": True,
                            },
                            {"task": "Implement agent welfare metrics", "done": True},
                            {
                                "task": "Create constraints management view",
                                "done": True,
                            },
                            {"task": "Add audit log viewer", "done": True},
                            {"task": "Add refusals analytics view", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 42: Smart LLM Routing System",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Create task_routing_rules table (15 seeded rules)",
                                "done": True,
                            },
                            {
                                "task": "Create task_executions table for tracking",
                                "done": True,
                            },
                            {
                                "task": "Create model_tier_configs table (4 tiers)",
                                "done": True,
                            },
                            {
                                "task": "Create SmartRouter class in ai_bridge",
                                "done": True,
                            },
                            {
                                "task": "Add routing API endpoints (7 endpoints)",
                                "done": True,
                            },
                            {"task": "Integrate with archie_bridge.py", "done": True},
                            {
                                "task": "Add LLM Routing tab to Team Management",
                                "done": True,
                            },
                            {
                                "task": "Create analytics pie chart and cost tracking",
                                "done": True,
                            },
                            {"task": "Per-agent Opus budget enforcement", "done": True},
                            {"task": "Auto-escalation after 3 failures", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 41: Admin Operations Hub",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Add ADMIN_OPS category to ModuleCategory enum",
                                "done": True,
                            },
                            {
                                "task": "Add admin_ops category to dashboard_generator.py",
                                "done": True,
                            },
                            {
                                "task": "Move Bridge, Team Management, Consciousness to ADMIN_OPS",
                                "done": True,
                            },
                            {
                                "task": "Update Bridge branding (BRIDGE COMMAND)",
                                "done": True,
                            },
                            {
                                "task": "Update Consciousness branding (A.R.C.H.I.E. MIND)",
                                "done": True,
                            },
                            {
                                "task": "Add cross-navigation buttons between modules",
                                "done": True,
                            },
                            {
                                "task": "Modernize Team Management UI (cyberpunk theme)",
                                "done": True,
                            },
                            {
                                "task": "Add Station Assignment tab to Team Management",
                                "done": True,
                            },
                            {
                                "task": "Create IAAE_TECHNICAL_ALIGNMENT.md documentation",
                                "done": True,
                            },
                        ],
                    },
                    {
                        "name": "Phase 42: Conversation Triage System",
                        "status": "complete",
                        "items": [
                            {"task": "Create conversation_triage module", "done": True},
                            {"task": "Implement conversation classifier", "done": True},
                            {"task": "Implement error/mistake extractor", "done": True},
                            {"task": "Implement code snippet extractor", "done": True},
                            {"task": "Implement insight extractor", "done": True},
                            {"task": "Create triage database tables", "done": True},
                            {
                                "task": "Update pre-compact hook for triage queue",
                                "done": True,
                            },
                            {"task": "Create triage API routes", "done": True},
                            {
                                "task": "Register triage blueprint in app.py",
                                "done": True,
                            },
                            {
                                "task": "Create Knowledge Management agents (4)",
                                "done": True,
                            },
                            {
                                "task": "Assign agents to Consciousness station",
                                "done": True,
                            },
                        ],
                    },
                    # ==================== FUTURE PHASES ====================
                    {
                        "name": "Phase 8: Figma Integration",
                        "status": "complete",
                        "items": [
                            {"task": "OAuth 2.0 authentication", "done": True},
                            {"task": "Design parser & analyzer", "done": True},
                            {"task": "AI component mapper", "done": True},
                            {"task": "React/Vue/HTML code generation", "done": True},
                            {"task": "Preview system & export", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 9: Long-Term Memory",
                        "status": "complete",
                        "items": [
                            {
                                "task": "Enhanced memory schema (Migration 028)",
                                "done": True,
                            },
                            {
                                "task": "Memory collection points (6 new tables)",
                                "done": True,
                            },
                            {
                                "task": "Semantic search (Ollama embeddings)",
                                "done": True,
                            },
                            {
                                "task": "Agent memory integration (memory_service.py)",
                                "done": True,
                            },
                            {"task": "Memory API (15+ endpoints)", "done": True},
                        ],
                    },
                    {
                        "name": "Phase 10: Production Launch",
                        "status": "planned",
                        "items": [
                            {
                                "task": "Domain setup (archie-platform.com)",
                                "done": False,
                            },
                            {"task": "SSL/Security audit", "done": False},
                            {"task": "Billing integration", "done": False},
                            {"task": "API documentation (OpenAPI)", "done": False},
                            {"task": "Mobile apps (Android/iOS)", "done": False},
                        ],
                    },
                ],
            },
        ],
        "summary": {},
    }

    # Calculate totals
    total_phases = 0
    completed_phases = 0
    in_progress_phases = 0
    planned_phases = 0
    total_tasks = 0
    done_tasks = 0

    for section in roadmap["sections"]:
        for phase in section["phases"]:
            total_phases += 1
            if phase["status"] == "complete":
                completed_phases += 1
            elif phase["status"] == "in_progress":
                in_progress_phases += 1
            else:
                planned_phases += 1

            for item in phase["items"]:
                total_tasks += 1
                if item["done"]:
                    done_tasks += 1

    roadmap["summary"] = {
        "total_phases": total_phases,
        "completed_phases": completed_phases,
        "in_progress": in_progress_phases,
        "planned": planned_phases,
        "total_tasks": total_tasks,
        "done_tasks": done_tasks,
        "progress_percent": (round((done_tasks / total_tasks) * 100) if total_tasks > 0 else 0),
    }

    return jsonify(roadmap)


@blueprint_bp.route("/api/code-reference")
def get_code_reference():
    """Get code structure reference for A.R.C.H.I.E."""

    reference = {
        "directories": [
            {"path": "/mnt/archie_brain/", "purpose": "Root project directory"},
            {
                "path": "/mnt/archie_brain/platform_v2/",
                "purpose": "Main Flask application",
            },
            {
                "path": "/mnt/archie_brain/platform_v2/tools/",
                "purpose": "Module blueprints",
            },
            {
                "path": "/mnt/archie_brain/platform_v2/templates/",
                "purpose": "Jinja2 templates",
            },
            {"path": "/mnt/archie_brain/ai_bridge/", "purpose": "AI model routing"},
            {"path": "/mnt/archie_brain/docs/", "purpose": "Project documentation"},
            {"path": "/mnt/archie_brain/backups/", "purpose": "System backups"},
        ],
        "key_files": [
            {"file": "app.py", "purpose": "Main Flask application entry point"},
            {
                "file": "module_registry.py",
                "purpose": "Module definitions and registry",
            },
            {"file": "rbac.py", "purpose": "Role-based access control"},
            {
                "file": "dashboard_generator.py",
                "purpose": "Dynamic dashboard generation",
            },
            {"file": "unified_knowledge_search.py", "purpose": "Knowledge base search"},
            {"file": "mistake_detector.py", "purpose": "Error pattern detection"},
            {"file": "docker-compose.yml", "purpose": "Docker service definitions"},
            {"file": ".env", "purpose": "Environment variables (SECRET)"},
        ],
        "database": {
            "name": "archie",
            "key_tables": [
                {"table": "knowledge_base", "purpose": "Unified knowledge storage"},
                {"table": "users", "purpose": "User authentication"},
                {"table": "agents", "purpose": "AI agent definitions"},
                {
                    "table": "improvement_proposals",
                    "purpose": "Code improvement tracking",
                },
                {"table": "token_usage_log", "purpose": "API cost tracking"},
            ],
        },
        "api_patterns": [
            {"pattern": "/tools/<module>/", "purpose": "Module main page"},
            {"pattern": "/tools/<module>/api/*", "purpose": "Module API endpoints"},
            {"pattern": "/api/modules", "purpose": "Module listing"},
            {"pattern": "/api/notifications", "purpose": "User notifications"},
        ],
    }

    return jsonify(reference)


@blueprint_bp.route("/api/status")
def status():
    """Health check for blueprint module"""
    return jsonify(
        {
            "module": "blueprint",
            "status": "live",
            "healthy": True,
            "message": "A.R.C.H.I.E. Blueprint module operational",
        }
    )


@blueprint_bp.route("/api/git-activity")
def get_git_activity():
    """Get recent git activity including commits, PRs, and deployments"""
    import subprocess

    try:
        # Get database connection
        from database import get_db
        from psycopg2.extras import RealDictCursor

        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Get git commits from database
        cur.execute(
            """
            SELECT gc.*, ip.title as proposal_title
            FROM git_commits gc
            LEFT JOIN improvement_proposals ip ON gc.proposal_id = ip.id
            ORDER BY gc.committed_at DESC
            LIMIT 20
        """
        )
        db_commits = cur.fetchall()

        # Get recent local git commits
        local_commits = []
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-20", "--format=%H|%s|%an|%ae|%ci"],
                cwd="/mnt/archie_brain",
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if "|" in line:
                        parts = line.split("|")
                        if len(parts) >= 5:
                            local_commits.append(
                                {
                                    "commit_hash": parts[0],
                                    "message": parts[1],
                                    "author_name": parts[2],
                                    "author_email": parts[3],
                                    "committed_at": parts[4],
                                    "source": "local",
                                }
                            )
        except Exception as e:
            print(f"Error getting local commits: {e}")

        # Get PRs from pull_requests table
        cur.execute(
            """
            SELECT repo, pr_number, title, state, author, url, created_at
            FROM pull_requests
            ORDER BY created_at DESC
            LIMIT 10
        """
        )
        prs = cur.fetchall()

        # Get recent deployments
        cur.execute(
            """
            SELECT id.*, ip.title as proposal_title
            FROM improvement_deployments id
            JOIN improvement_proposals ip ON id.proposal_id = ip.id
            ORDER BY id.deployed_at DESC
            LIMIT 10
        """
        )
        deployments = cur.fetchall()

        # Get git tracking status
        cur.execute("SELECT COUNT(*) as total FROM git_commits")
        git_commits_count = cur.fetchone()["total"]

        cur.close()
        conn.close()

        # Check if git poller is running
        poller_status = "unknown"
        try:
            from git_commit_poller import GitCommitPoller  # noqa: F401

            # Can't easily check if running without a reference
            poller_status = "available"
        except Exception:
            poller_status = "not_imported"

        return jsonify(
            {
                "success": True,
                "git_commits": {
                    "from_database": [
                        {
                            **dict(c),
                            "committed_at": (c["committed_at"].isoformat() if c.get("committed_at") else None),
                            "detected_at": (c["detected_at"].isoformat() if c.get("detected_at") else None),
                        }
                        for c in db_commits
                    ],
                    "from_local": local_commits,
                    "total_tracked": git_commits_count,
                },
                "pull_requests": [
                    {
                        **dict(pr),
                        "created_at": (pr["created_at"].isoformat() if pr.get("created_at") else None),
                    }
                    for pr in prs
                ],
                "deployments": [
                    {
                        **dict(d),
                        "deployed_at": (d["deployed_at"].isoformat() if d.get("deployed_at") else None),
                    }
                    for d in deployments
                ],
                "tracking_status": {
                    "git_commits_tracked": git_commits_count,
                    "prs_tracked": len(prs),
                    "deployments_tracked": len(deployments),
                    "poller_status": poller_status,
                },
            }
        )

    except Exception as e:
        import traceback

        return (
            jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}),
            500,
        )


@blueprint_bp.route("/api/git-tracking/initialize", methods=["POST"])
def initialize_git_tracking():
    """Initialize git tracking - install hooks and start poller"""
    results = {"hooks": None, "poller": None}

    try:
        # Install git hooks
        from git_hook_manager import GitHookManager

        hook_manager = GitHookManager()
        results["hooks"] = hook_manager.install_post_commit_hook()
    except Exception as e:
        results["hooks"] = {"success": False, "error": str(e)}

    try:
        # Note: Poller should be started by app.py on startup, not here
        # But we can check status
        from git_commit_poller import GitCommitPoller  # noqa: F401

        results["poller"] = {
            "success": True,
            "message": "GitCommitPoller class available. Start via app.py",
        }
    except Exception as e:
        results["poller"] = {"success": False, "error": str(e)}

    return jsonify(
        {
            "success": all(r.get("success", False) for r in results.values() if r),
            "results": results,
        }
    )


# ============================================
# Phase 29: Blueprint Optimization API Endpoints
# ============================================

# ---------------------
# Phase Management CRUD
# ---------------------


@blueprint_bp.route("/api/phases")
def api_get_phases():
    """Get all phases with tasks, optionally filtered by section or status."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Phase management not available"}), 500

    section = request.args.get("section")
    status = request.args.get("status")

    try:
        phases = get_all_phases(section=section, status=status)
        summary = get_roadmap_summary()
        sections = get_sections()

        return jsonify(
            {
                "success": True,
                "phases": phases,
                "summary": summary,
                "sections": sections,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/phases/<int:phase_id>")
def api_get_phase(phase_id):
    """Get a single phase with tasks."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Phase management not available"}), 500

    try:
        phase = get_phase(phase_id)
        if not phase:
            return jsonify({"success": False, "error": "Phase not found"}), 404
        return jsonify({"success": True, "phase": phase})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/phases", methods=["POST"])
def api_create_phase():
    """Create a new phase."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Phase management not available"}), 500

    try:
        data = request.get_json()
        if not data or "phase_number" not in data or "name" not in data:
            return (
                jsonify({"success": False, "error": "phase_number and name required"}),
                400,
            )

        phase = create_phase(data)
        return jsonify({"success": True, "phase": phase})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/phases/<int:phase_id>", methods=["PUT"])
def api_update_phase(phase_id):
    """Update a phase."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Phase management not available"}), 500

    try:
        data = request.get_json()
        phase = update_phase(phase_id, data)
        if not phase:
            return jsonify({"success": False, "error": "Phase not found"}), 404
        return jsonify({"success": True, "phase": phase})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/phases/<int:phase_id>", methods=["DELETE"])
def api_delete_phase(phase_id):
    """Delete a phase."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Phase management not available"}), 500

    try:
        deleted = delete_phase(phase_id)
        if not deleted:
            return jsonify({"success": False, "error": "Phase not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/phases/reorder", methods=["POST"])
def api_reorder_phases():
    """Reorder phases."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Phase management not available"}), 500

    try:
        data = request.get_json()
        if not data or "order" not in data:
            return jsonify({"success": False, "error": "order list required"}), 400

        reorder_phases(data["order"])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/phases/<int:phase_id>/tasks", methods=["POST"])
def api_add_task(phase_id):
    """Add a task to a phase."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Phase management not available"}), 500

    try:
        data = request.get_json()
        if not data or "task_description" not in data:
            return (
                jsonify({"success": False, "error": "task_description required"}),
                400,
            )

        task = add_task(
            phase_id,
            data["task_description"],
            done=data.get("done", False),
            notes=data.get("notes"),
        )
        return jsonify({"success": True, "task": task})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/tasks/<int:task_id>/toggle", methods=["PUT"])
def api_toggle_task(task_id):
    """Toggle a task's done status."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Phase management not available"}), 500

    try:
        task = toggle_task(task_id)
        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404
        return jsonify({"success": True, "task": task})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/tasks/<int:task_id>", methods=["PUT"])
def api_update_task(task_id):
    """Update a task."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Phase management not available"}), 500

    try:
        data = request.get_json()
        task = update_task(task_id, data)
        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404
        return jsonify({"success": True, "task": task})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def api_delete_task(task_id):
    """Delete a task."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Phase management not available"}), 500

    try:
        deleted = delete_task(task_id)
        if not deleted:
            return jsonify({"success": False, "error": "Task not found"}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# Platform Inventory
# ---------------------


@blueprint_bp.route("/api/inventory")
def api_get_inventory():
    """Get current platform inventory."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Inventory scanner not available"}), 500

    try:
        inventory = get_current_inventory()
        if not inventory:
            return jsonify(
                {
                    "success": True,
                    "inventory": None,
                    "message": "No inventory snapshot exists. Run a scan first.",
                }
            )
        return jsonify({"success": True, "inventory": inventory})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/inventory/history")
def api_get_inventory_history():
    """Get inventory snapshot history."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Inventory scanner not available"}), 500

    try:
        limit = request.args.get("limit", 20, type=int)
        history = get_inventory_history(limit=limit)
        return jsonify({"success": True, "history": history})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/inventory/scan", methods=["POST"])
def api_scan_inventory():
    """Trigger a new inventory scan."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Inventory scanner not available"}), 500

    try:
        data = request.get_json() or {}
        notes = data.get("notes")

        result = scan_and_save(notes=notes)
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/inventory/<int:snapshot_id>")
def api_get_inventory_snapshot(snapshot_id):
    """Get a specific inventory snapshot."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Inventory scanner not available"}), 500

    try:
        snapshot = get_inventory_snapshot(snapshot_id)
        if not snapshot:
            return jsonify({"success": False, "error": "Snapshot not found"}), 404
        return jsonify({"success": True, "snapshot": snapshot})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/inventory/<int:snapshot_id>", methods=["DELETE"])
def api_delete_inventory_snapshot(snapshot_id):
    """Delete an inventory snapshot."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Inventory scanner not available"}), 500

    try:
        deleted = delete_inventory_snapshot(snapshot_id)
        if not deleted:
            return (
                jsonify({"success": False, "error": "Snapshot not found or is current"}),
                404,
            )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# Cleanup Management
# ---------------------


@blueprint_bp.route("/api/cleanup/candidates")
def api_get_cleanup_candidates():
    """Get cleanup candidates."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Cleanup manager not available"}), 500

    try:
        status = request.args.get("status")
        category = request.args.get("category")
        candidates = get_candidates(status=status, category=category)
        return jsonify({"success": True, "candidates": candidates})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/cleanup/scan", methods=["POST"])
def api_scan_cleanup():
    """Scan for cleanup candidates."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Cleanup manager not available"}), 500

    try:
        result = cleanup_scan_and_save()
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/cleanup/approve/<int:candidate_id>", methods=["POST"])
def api_approve_cleanup(candidate_id):
    """Approve a cleanup candidate."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Cleanup manager not available"}), 500

    try:
        data = request.get_json() or {}
        approved_by = data.get("approved_by", "admin")

        success = approve_candidate(candidate_id, approved_by)
        if not success:
            return (
                jsonify({"success": False, "error": "Candidate not found or not pending"}),
                404,
            )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/cleanup/reject/<int:candidate_id>", methods=["POST"])
def api_reject_cleanup(candidate_id):
    """Reject a cleanup candidate."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Cleanup manager not available"}), 500

    try:
        success = reject_candidate(candidate_id)
        if not success:
            return (
                jsonify({"success": False, "error": "Candidate not found or not pending"}),
                404,
            )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/cleanup/approve-bulk", methods=["POST"])
def api_bulk_approve_cleanup():
    """Approve multiple cleanup candidates."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Cleanup manager not available"}), 500

    try:
        data = request.get_json()
        if not data or "ids" not in data:
            return jsonify({"success": False, "error": "ids list required"}), 400

        approved_by = data.get("approved_by", "admin")
        count = bulk_approve(data["ids"], approved_by)
        return jsonify({"success": True, "approved_count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/cleanup/execute/<int:candidate_id>", methods=["POST"])
def api_execute_cleanup(candidate_id):
    """Execute cleanup for an approved candidate."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Cleanup manager not available"}), 500

    try:
        result = execute_cleanup(candidate_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/cleanup/execute-bulk", methods=["POST"])
def api_bulk_execute_cleanup():
    """Execute cleanup for multiple approved candidates."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Cleanup manager not available"}), 500

    try:
        data = request.get_json()
        if not data or "ids" not in data:
            return jsonify({"success": False, "error": "ids list required"}), 400

        result = bulk_execute(data["ids"])
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/cleanup/report")
def api_cleanup_report():
    """Get cleanup summary report."""
    if not PHASE29_AVAILABLE:
        return jsonify({"error": "Cleanup manager not available"}), 500

    try:
        report = get_cleanup_report()
        return jsonify({"success": True, **report})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================
# Phase 29.5: Blueprint Intelligence Hub API
# ============================================

# ---------------------
# Database Schema
# ---------------------


@blueprint_bp.route("/api/schema")
def api_get_schema():
    """Get comprehensive database schema information."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        schema = get_database_schema()
        return jsonify(schema)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# API Documentation
# ---------------------


@blueprint_bp.route("/api/endpoints")
def api_get_endpoints():
    """Get all registered API endpoints."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        endpoints = get_api_endpoints()
        return jsonify(endpoints)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# System Health
# ---------------------


@blueprint_bp.route("/api/health/full")
def api_get_full_health():
    """Get comprehensive system health information."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        health = get_system_health()
        return jsonify(health)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# Dependencies
# ---------------------


@blueprint_bp.route("/api/dependencies")
def api_get_dependencies():
    """Get Python package dependencies and versions."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        deps = get_dependencies()
        return jsonify(deps)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# Backup Status
# ---------------------


@blueprint_bp.route("/api/backups")
def api_get_backups():
    """Get backup status and history."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        backups = get_backup_status()
        return jsonify(backups)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# Agent Directory
# ---------------------


@blueprint_bp.route("/api/agents")
def api_get_agents():
    """Get comprehensive agent directory."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        agents = get_agent_directory()
        return jsonify(agents)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# Snapshot Comparison
# ---------------------


@blueprint_bp.route("/api/inventory/compare")
def api_compare_snapshots():
    """Compare two inventory snapshots."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        old_id = request.args.get("old_id", type=int)
        new_id = request.args.get("new_id", type=int)

        if not old_id or not new_id:
            return (
                jsonify({"success": False, "error": "old_id and new_id required"}),
                400,
            )

        comparison = compare_inventory_snapshots(old_id, new_id)
        return jsonify(comparison)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# Knowledge Base Sync
# ---------------------


@blueprint_bp.route("/api/sync-knowledge", methods=["POST"])
def api_sync_knowledge():
    """Sync Blueprint intelligence data to knowledge base."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        result = sync_blueprint_to_knowledge_base()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@blueprint_bp.route("/api/sync-module-code", methods=["POST"])
def api_sync_module_code():
    """Sync module routes.py code to knowledge base for A.R.C.H.I.E. retrieval.

    Phase 29.6: Store each module's routes.py as code_snippet in knowledge_base.
    """
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        result = sync_module_code_to_knowledge()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# Auto-Sync (fire-and-forget on page load)
# ---------------------


@blueprint_bp.route("/api/auto-sync", methods=["POST"])
def api_auto_sync():
    """Auto-sync blueprint data if stale (>5 min). Called on page load."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"synced": False, "reason": "intelligence_unavailable"})

    try:
        result = auto_sync_if_stale()
        return jsonify(result)
    except Exception as e:
        return jsonify({"synced": False, "error": str(e)})


# ---------------------
# Quick Actions
# ---------------------


@blueprint_bp.route("/api/quick-action", methods=["POST"])
def api_quick_action():
    """Execute a quick action."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        data = request.get_json()
        if not data or "action" not in data:
            return jsonify({"success": False, "error": "action required"}), 400

        result = execute_quick_action(data["action"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# Consciousness Integration
# ---------------------


@blueprint_bp.route("/api/consciousness")
def api_get_consciousness():
    """Get Consciousness module summary for Blueprint integration."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        summary = get_consciousness_summary()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------
# Combined Intelligence Report
# ---------------------


@blueprint_bp.route("/api/intelligence-report")
def api_intelligence_report():
    """Get a combined intelligence report for A.R.C.H.I.E."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"error": "Blueprint Intelligence not available"}), 500

    try:
        report = {
            "success": True,
            "generated_at": datetime.now().isoformat(),
            "schema_summary": {},
            "health_summary": {},
            "agent_summary": {},
            "consciousness_summary": {},
        }

        # Get schema summary
        schema = get_database_schema()
        if schema.get("success"):
            report["schema_summary"] = schema.get("summary", {})

        # Get health summary
        health = get_system_health()
        if health.get("success"):
            report["health_summary"] = {
                "cpu": health.get("system", {}).get("cpu_percent"),
                "memory_percent": health.get("system", {}).get("memory", {}).get("percent"),
                "disk_percent": health.get("system", {}).get("disk", {}).get("percent"),
                "docker_healthy": health.get("docker", {}).get("healthy", 0),
                "db_connected": health.get("database", {}).get("connected", False),
            }

        # Get agent summary
        agents = get_agent_directory()
        if agents.get("success"):
            report["agent_summary"] = agents.get("summary", {})

        # Get consciousness summary
        consciousness = get_consciousness_summary()
        if consciousness.get("success"):
            report["consciousness_summary"] = {
                "total_memories": consciousness.get("memory", {}).get("total_memories", 0),
                "avg_energy": consciousness.get("emotional", {}).get("avg_energy", 0),
                "knowledge_types": len(consciousness.get("knowledge", [])),
            }

        return jsonify(report)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
