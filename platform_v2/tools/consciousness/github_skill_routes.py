"""GitHub Skill Pipeline Routes -- Discovery, adaptation, stats

Split from github_routes.py. Handles:
- Skill listing with filtering
- Skill adaptation (fork + optional AI rewrite)
- Pipeline statistics dashboard
"""

import json
import logging
import os

from psycopg2.extras import RealDictCursor
from flask import jsonify, request
from flask_login import current_user, login_required

from .github_routes import _get_db

logger = logging.getLogger(__name__)


def register_github_skill_routes(bp, admin_required):
    """Register skill pipeline routes on the consciousness blueprint."""

    # Helper: accept either Flask-Login session (admin) or Bearer API key
    def login_or_api_key(f):
        """Allow access via Flask-Login session OR Bearer API key."""
        from functools import wraps

        @wraps(f)
        def decorated(*args, **kwargs):
            api_key = request.headers.get("Authorization", "")
            if api_key.startswith("Bearer "):
                valid_key = os.getenv("ARCHIE_API_KEY", "dev-api-key-change-in-production")
                if api_key[7:] == valid_key:
                    return f(*args, **kwargs)
                return jsonify({"error": "Invalid API key"}), 401
            # Fall back to Flask-Login session
            if not current_user.is_authenticated:
                return jsonify({"error": "Authentication required"}), 401
            if not getattr(current_user, "is_admin", False):
                return jsonify({"error": "Admin access required"}), 403
            return f(*args, **kwargs)

        return decorated

    # ==================================================================
    # SKILL PIPELINE ROUTES
    # ==================================================================

    @bp.route("/github/skills", methods=["GET"])
    @login_required
    @admin_required
    def github_skills_list():
        """List all skills from the pipeline with filtering."""
        status = request.args.get("status")
        min_quality = request.args.get("min_quality", type=int)
        repo = request.args.get("repo")
        limit = min(request.args.get("limit", 50, type=int), 200)

        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            where_clauses = []
            params = []
            if status:
                where_clauses.append("gs.status = %s")
                params.append(status)
            if min_quality:
                where_clauses.append("gs.quality_score >= %s")
                params.append(min_quality)
            if repo:
                where_clauses.append("gs.repo_name ILIKE %s")
                params.append(f"%{repo}%")

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            params.append(limit)

            cur.execute(
                f"""SELECT gs.id, gs.repo_name, gs.skill_name, gs.description,
                           gs.capabilities, gs.quality_score, gs.status,
                           gs.agent_ids, gs.analysis, gs.adapted_from_id,
                           gs.file_path, gs.created_at, gs.updated_at
                    FROM github_skills gs
                    WHERE {where_sql}
                    ORDER BY gs.quality_score DESC NULLS LAST, gs.created_at DESC
                    LIMIT %s""",
                params,
            )
            skills = [dict(r) for r in cur.fetchall()]

            # Stats summary
            cur.execute(
                """SELECT status, COUNT(*) as count,
                          AVG(quality_score) FILTER (WHERE quality_score IS NOT NULL) as avg_quality
                   FROM github_skills
                   GROUP BY status
                   ORDER BY status"""
            )
            stats = [dict(r) for r in cur.fetchall()]

            return jsonify(
                {
                    "success": True,
                    "skills": skills,
                    "count": len(skills),
                    "pipeline_stats": stats,
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/github/skills/<int:skill_id>/adapt", methods=["POST"])
    @login_or_api_key
    def github_skill_adapt(skill_id):
        """Fork a skill for ARCHIE adaptation.

        Creates a new github_skills entry with adapted_from_id pointing
        to the original. Optionally triggers Bridge to rewrite the skill
        for ARCHIE conventions.
        """
        data = request.get_json() or {}
        auto_rewrite = data.get("auto_rewrite", False)

        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Fetch original skill
            cur.execute("SELECT * FROM github_skills WHERE id = %s", (skill_id,))
            original = cur.fetchone()
            if not original:
                return jsonify({"success": False, "error": "Skill not found"}), 404

            # Check not already adapted
            cur.execute(
                "SELECT id FROM github_skills WHERE adapted_from_id = %s",
                (skill_id,),
            )
            existing = cur.fetchone()
            if existing:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "Already adapted",
                            "adapted_id": existing["id"],
                        }
                    ),
                    409,
                )

            # Create adapted copy
            adapted_name = f"archie/{original['skill_name']}"
            cur.execute(
                """INSERT INTO github_skills
                       (repo_name, skill_name, description, capabilities,
                        quality_score, status, original_repo, adapted_from_id,
                        agent_ids, analysis, file_path)
                   VALUES ('ARCHIE/adapted-skills', %s, %s, %s,
                           %s, 'adapted', %s, %s,
                           %s, %s, %s)
                   RETURNING id""",
                (
                    adapted_name,
                    original["description"],
                    json.dumps(original.get("capabilities") or []),
                    original["quality_score"],
                    original["repo_name"],
                    skill_id,
                    json.dumps(original.get("agent_ids") or []),
                    json.dumps(original.get("analysis") or {}),
                    f"ARCHIE/adapted-skills/{original['skill_name']}",
                ),
            )
            adapted_row = cur.fetchone()
            adapted_id = adapted_row["id"]
            conn.commit()

            # Optionally trigger AI rewrite
            rewrite_result = None
            if auto_rewrite:
                try:
                    from tools.department_hq.services.department_dispatcher import dispatch_json

                    kb_content = ""
                    if original.get("kb_entry_id"):
                        cur.execute(
                            "SELECT content FROM knowledge_base WHERE id = %s",
                            (original["kb_entry_id"],),
                        )
                        kb_row = cur.fetchone()
                        if kb_row:
                            kb_content = kb_row["content"][:3000]

                    prompt = f"""Adapt this external skill for the A.R.C.H.I.E. platform.

Original skill from {original['repo_name']}:
---
{kb_content or original.get('description', '')}
---

Rewrite it to:
1. Follow ARCHIE conventions (stations, Bridge dispatch, LCARS UI patterns)
2. Reference ARCHIE agent capabilities instead of generic ones
3. Add platform-specific context (192.168.1.200, Docker deployment, 10 stations)
4. Keep the core functionality intact

Return ONLY the rewritten skill content as markdown."""

                    rewrite_result = dispatch_json(
                        capability="code_analysis",
                        prompt=prompt,
                        module_id="skill_adapter",
                        system_prompt="You are a skill adapter for A.R.C.H.I.E. Rewrite external skills to fit the platform.",
                    )
                    if rewrite_result and isinstance(rewrite_result, dict):
                        adapted_content = rewrite_result.get("response", "")
                        if adapted_content:
                            cur.execute(
                                """UPDATE github_skills
                                   SET description = %s, updated_at = NOW()
                                   WHERE id = %s""",
                                (adapted_content[:2000], adapted_id),
                            )
                            conn.commit()
                except Exception as rewrite_err:
                    logger.warning(f"[SkillAdapt] Auto-rewrite failed: {rewrite_err}")

            return jsonify(
                {
                    "success": True,
                    "adapted_id": adapted_id,
                    "original_id": skill_id,
                    "skill_name": adapted_name,
                    "auto_rewrite": bool(rewrite_result),
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    @bp.route("/github/skills/stats", methods=["GET"])
    @login_required
    @admin_required
    def github_skills_stats():
        """Pipeline statistics for the skill dashboard."""
        conn = None
        cur = None
        try:
            conn = _get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """SELECT status, COUNT(*) as count
                   FROM github_skills GROUP BY status ORDER BY status"""
            )
            by_status = {r["status"]: r["count"] for r in cur.fetchall()}

            cur.execute(
                """SELECT repo_name, COUNT(*) as skills,
                          AVG(quality_score) FILTER (WHERE quality_score IS NOT NULL) as avg_quality
                   FROM github_skills
                   GROUP BY repo_name
                   ORDER BY skills DESC LIMIT 10"""
            )
            top_repos = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """SELECT quality_score, COUNT(*) as count
                   FROM github_skills
                   WHERE quality_score IS NOT NULL
                   GROUP BY quality_score ORDER BY quality_score"""
            )
            quality_dist = {r["quality_score"]: r["count"] for r in cur.fetchall()}

            cur.execute(
                """SELECT id, repo_name, skill_name, quality_score, status,
                          capabilities, updated_at
                   FROM github_skills
                   WHERE status IN ('analyzed', 'registered')
                   ORDER BY updated_at DESC LIMIT 10"""
            )
            recent = [dict(r) for r in cur.fetchall()]

            cur.execute(
                """SELECT COUNT(DISTINCT agent_id) as agents,
                          COUNT(*) as total_assignments
                   FROM agent_skills
                   WHERE skill_name LIKE 'gh:%%'"""
            )
            agent_row = cur.fetchone()

            return jsonify(
                {
                    "success": True,
                    "pipeline": by_status,
                    "total_skills": sum(by_status.values()),
                    "top_repos": top_repos,
                    "quality_distribution": quality_dist,
                    "recent_analyzed": recent,
                    "agent_coverage": dict(agent_row) if agent_row else {},
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
