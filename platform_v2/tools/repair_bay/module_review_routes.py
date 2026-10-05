"""Repair Bay — Module Review tab routes.

Single source of truth for module health: QA, chat overlay, KB docs, code health.
Aggregates data from qa_test_suites, code_metrics_snapshots, improvement_proposals,
and knowledge_base into per-module cards grouped by category.
"""

import logging

from flask import jsonify, request
from flask_login import login_required
from services.code_health_repairs import TERMINAL_STATUSES

logger = logging.getLogger(__name__)

# Canonical module → agent assignment map.
# Key = module_key matching module_registry + qa_service MODULE_SUITE_MAP.
# Update here when a new chat overlay is added to a module.
MODULE_AGENT_MAP = {
    # Admin Ops
    "backup_manager": {"agent_name": "W.A.R.D.E.N.", "agent_id": 363, "color": "#ef4444"},
    "security_network": {"agent_name": "V.I.G.I.L.", "agent_id": 3, "color": "#ef4444"},
    "account_center": {"agent_name": "R.E.S.O.L.V.E.", "agent_id": 142, "color": "#ef4444"},
    "saas_manager": {"agent_name": "R.E.S.O.L.V.E.", "agent_id": 142, "color": "#ef4444"},
    # AI Command
    "department_hq": {"agent_name": "K.I.N.", "agent_id": 145, "color": "#00e5ff"},
    "consciousness": {"agent_name": "C.O.D.E.X.", "agent_id": 146, "color": "#8b5cf6"},
    "agent_academy": {"agent_name": "F.O.R.G.E.", "agent_id": 136, "color": "#00e5ff"},
    "repair_bay": {"agent_name": "F.O.R.G.E.", "agent_id": 136, "color": "#00e5ff"},
    "wtf_hub": {"agent_name": "F.A.C.T.", "agent_id": 48, "color": "#00ffff"},
    # SaaS Services
    "email_manager": {"agent_name": "R.E.S.O.L.V.E.", "agent_id": 142, "color": "#ef4444"},
    "google_work_suite": {"agent_name": "R.E.S.O.L.V.E.", "agent_id": 142, "color": "#ef4444"},
    "user_profile": {"agent_name": "R.E.S.O.L.V.E.", "agent_id": 142, "color": "#ef4444"},
    # Creative Studios
    "media_studio": {"agent_name": "M.U.S.E.", "agent_id": 138, "color": "#f472b6"},
    "game_studio": {"agent_name": "M.U.S.E.", "agent_id": 138, "color": "#f472b6"},
    # Crypto — C.H.A.I.N. #365 owns mining pool analytics (approved 2026-05-12)
    "archie_pool": {"agent_name": "C.H.A.I.N.", "agent_id": 365, "color": "#f59e0b"},
    "pool_management": {"agent_name": "C.H.A.I.N.", "agent_id": 365, "color": "#f59e0b"},
    # Applications & Concepts
    "media_hub": {"agent_name": "M.A.V.E.N.", "agent_id": 27, "color": "#8b5cf6"},
    "family_tree": {"agent_name": "H.E.R.I.T.A.G.E.", "agent_id": 331, "color": "#f59e0b"},
    "fitness": {"agent_name": "V.I.T.A.L.", "agent_id": 148, "color": "#22d3ee"},
    "therapy": {"agent_name": "V.I.T.A.L.", "agent_id": 148, "color": "#60a5fa"},
    "faith": {"agent_name": "F.A.I.T.H.", "agent_id": 352, "color": "#a78bfa"},
    "doc": {"agent_name": "V.I.T.A.L.", "agent_id": 148, "color": "#3b82f6"},
}

# Module categories matching module_registry.py
MODULE_CATEGORIES = {
    "admin_operations": [
        "backup_manager",
        "security_network",
        "account_center",
        "saas_manager",
    ],
    "ai_command": [
        "department_hq",
        "consciousness",
        "archie_chat",
        "repair_bay",
        "agent_academy",
        # "automations" removed — enabled=False in module_registry (Decision #434)
        "wtf_hub",
    ],
    "saas_services": [
        "email_manager",
        "google_work_suite",
        "user_profile",
        "kytran_business_suite",
        # "scheduler" removed — enabled=False in module_registry
        # "social_media" removed — enabled=False in module_registry
        # "task_planner" removed — enabled=False in module_registry (Task #1984)
        "kytran_system_ops",
    ],
    "applications_concepts": [
        "media_hub",
        "family_tree",
        "fitness",
        "therapy",
        "faith",
        "doc",
    ],
    "creative_studios": [
        "media_studio",
        "game_studio",
    ],
    "crypto": [
        "archie_pool",
        "pool_management",
    ],
}

CATEGORY_LABELS = {
    "admin_operations": "Admin Ops",
    "ai_command": "AI Command",
    "saas_services": "SaaS Services",
    "applications_concepts": "Applications",
    "creative_studios": "Creative Studios",
    "crypto": "Crypto",
}


def register_module_review_routes(bp, admin_required):
    """Register Module Review routes on the repair_bay blueprint."""

    @bp.route("/api/module-review/data")
    @login_required
    @admin_required
    def module_review_data():
        """Return aggregated module health data grouped by category."""
        from database import get_db_cursor
        from services.qa_service import MODULE_SUITE_MAP

        category_filter = request.args.get("category")

        # Invert MODULE_SUITE_MAP: suite_id → module_key
        suite_to_module: dict = {}
        for mod_key, suite_ids in MODULE_SUITE_MAP.items():
            for sid in suite_ids:
                suite_to_module[sid] = mod_key

        all_suite_ids = list(suite_to_module.keys())

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                # Latest run per suite using correct column names
                qa_rows = []
                if all_suite_ids:
                    cur.execute(
                        """
                        SELECT
                            ts.id AS suite_id,
                            ts.name AS suite_name,
                            tr.passed,
                            tr.failed,
                            tr.total_tests AS total,
                            tr.started_at AS run_at
                        FROM qa_test_suites ts
                        LEFT JOIN LATERAL (
                            SELECT passed, failed, total_tests, started_at
                            FROM qa_test_runs
                            WHERE suite_id = ts.id
                            ORDER BY started_at DESC
                            LIMIT 1
                        ) tr ON TRUE
                        WHERE ts.id = ANY(%s::int[]) AND ts.is_active = TRUE
                        ORDER BY ts.id
                        """,
                        (all_suite_ids,),
                    )
                    qa_rows = cur.fetchall() or []

                # Latest code metrics snapshot per module — per_module is a JSONB
                # column keyed by module name; there is no module_name scalar column.
                cur.execute(
                    """
                    SELECT
                        kv.key   AS module_name,
                        (kv.value->>'files')::int  AS total_files,
                        (kv.value->>'lines')::int  AS total_lines,
                        s.scanned_at
                    FROM (
                        SELECT id, per_module, scanned_at
                        FROM code_metrics_snapshots
                        ORDER BY scanned_at DESC
                        LIMIT 1
                    ) s,
                    jsonb_each(s.per_module) AS kv
                    """
                )
                metrics_rows = cur.fetchall() or []

                from services.code_health_repairs import open_proposal_counts

                proposals_by_module = open_proposal_counts(code_health_only=False)

                # KB vault notes per module (tags match module key)
                cur.execute(
                    """
                    SELECT
                        tags,
                        COUNT(*) AS note_count,
                        MAX(created_at) AS latest_at
                    FROM knowledge_base
                    WHERE knowledge_type = 'vault_note'
                      AND tags IS NOT NULL
                      AND array_length(tags, 1) > 0
                    GROUP BY tags
                    """
                )
                kb_rows = cur.fetchall() or []

        except Exception as exc:
            logger.exception("module_review_data query failed")
            return jsonify({"success": False, "error": str(exc)}), 500

        # Index data by module key (resolved via suite_to_module map)
        qa_by_module: dict = {}
        for row in qa_rows:
            mk = suite_to_module.get(row["suite_id"])
            if not mk:
                continue
            if mk not in qa_by_module:
                qa_by_module[mk] = {"suites": [], "total_passed": 0, "total_tests": 0, "last_run": None}
            suite = {
                "id": row["suite_id"],
                "name": row["suite_name"],
                "passed": row["passed"] or 0,
                "failed": row["failed"] or 0,
                "total": row["total"] or 0,
                "run_at": row["run_at"].isoformat() if row["run_at"] else None,
            }
            qa_by_module[mk]["suites"].append(suite)
            qa_by_module[mk]["total_passed"] += suite["passed"]
            qa_by_module[mk]["total_tests"] += suite["total"]
            if row["run_at"] and (
                not qa_by_module[mk]["last_run"] or row["run_at"].isoformat() > qa_by_module[mk]["last_run"]
            ):
                qa_by_module[mk]["last_run"] = row["run_at"].isoformat()

        metrics_by_module = {
            row["module_name"]: {
                "files": row["total_files"],
                "lines": row["total_lines"],
                "scanned_at": row["scanned_at"].isoformat() if row["scanned_at"] else None,
            }
            for row in metrics_rows
        }

        # Build KB lookup: tag → {note_count, latest_at}
        kb_by_tag: dict = {}
        for row in kb_rows:
            tags = row["tags"] or []
            for tag in tags:
                if tag not in kb_by_tag:
                    kb_by_tag[tag] = {"note_count": 0, "latest_at": None}
                kb_by_tag[tag]["note_count"] += row["note_count"]
                lat = row["latest_at"].isoformat() if row["latest_at"] else None
                if lat and (not kb_by_tag[tag]["latest_at"] or lat > kb_by_tag[tag]["latest_at"]):
                    kb_by_tag[tag]["latest_at"] = lat

        categories = []
        for cat_key, module_keys in MODULE_CATEGORIES.items():
            if category_filter and cat_key != category_filter:
                continue

            modules = []
            for mk in module_keys:
                qa = qa_by_module.get(mk, {})
                total = qa.get("total_tests", 0)
                passed = qa.get("total_passed", 0)
                pass_pct = round(passed / total * 100) if total > 0 else None

                agent_info = MODULE_AGENT_MAP.get(mk)
                kb_info = kb_by_tag.get(mk, {})
                metrics = metrics_by_module.get(mk, {})
                open_proposals = proposals_by_module.get(mk, 0)

                modules.append(
                    {
                        "key": mk,
                        "qa": {
                            "pass_pct": pass_pct,
                            "passed": passed,
                            "total": total,
                            "suites": qa.get("suites", []),
                            "last_run": qa.get("last_run"),
                        },
                        "overlay": {
                            "assigned": agent_info is not None,
                            "agent_name": agent_info["agent_name"] if agent_info else None,
                            "agent_id": agent_info["agent_id"] if agent_info else None,
                            "color": agent_info["color"] if agent_info else None,
                        },
                        "kb": {
                            "note_count": kb_info.get("note_count", 0),
                            "latest_at": kb_info.get("latest_at"),
                        },
                        "code_health": {
                            "files": metrics.get("files"),
                            "lines": metrics.get("lines"),
                            "open_proposals": open_proposals,
                            "scanned_at": metrics.get("scanned_at"),
                        },
                    }
                )

            categories.append(
                {
                    "key": cat_key,
                    "label": CATEGORY_LABELS[cat_key],
                    "modules": modules,
                }
            )

        return jsonify({"success": True, "categories": categories})

    @bp.route("/api/module-review/bundle", methods=["POST"])
    @login_required
    @admin_required
    def module_review_bundle():
        """Bundle all open improvement_proposals for a module into one consolidated proposal."""
        from database import get_db_cursor

        data = request.get_json(silent=True) or {}
        module_key = (data.get("module_key") or "").strip()
        if not module_key:
            return jsonify({"success": False, "error": "module_key required"}), 400
        escaped = module_key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """SELECT id, title, description, priority
                       FROM improvement_proposals
                       WHERE (COALESCE(NULLIF(module_name, ''), metadata->>'module_name') = %s
                              OR metadata->>'file_path' LIKE %s
                              OR metadata->>'file_path' LIKE %s)
                         AND status NOT IN %s
                       ORDER BY proposed_at DESC""",
                    (module_key, f"platform_v2/tools/{escaped}/%", f"[APP_CORE]/tools/{escaped}/%", TERMINAL_STATUSES),
                )
                open_proposals = cur.fetchall() or []

                if len(open_proposals) < 2:
                    return jsonify({"success": False, "error": "Need at least 2 open proposals to bundle"}), 400

                # Dedup: don't create a new bundle if one is already open for this module
                cur.execute(
                    """SELECT 1 FROM improvement_proposals
                       WHERE module_name = %s
                         AND proposal_source = 'bundled'
                         AND status NOT IN %s
                       LIMIT 1""",
                    (module_key, TERMINAL_STATUSES),
                )
                if cur.fetchone():
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"An open bundle already exists for {module_key}. Implement or reject it first.",
                            }
                        ),
                        409,
                    )

                titles = [r["title"] for r in open_proposals]
                descriptions = "\n\n".join(f"— {r['title']}: {r['description'] or ''}" for r in open_proposals)
                priorities = [r["priority"] for r in open_proposals]
                top_priority = "high" if "high" in priorities else "medium"
                source_ids = [r["id"] for r in open_proposals]

                cur.execute(
                    """INSERT INTO improvement_proposals
                           (title, description, category, priority, status,
                            module_name, proposal_source, metadata)
                       VALUES (%s, %s, 'code_quality', %s, 'proposed',
                               %s, 'bundled', %s::jsonb)
                       RETURNING id""",
                    (
                        f"[Bundled] {len(open_proposals)} fixes for {module_key}",
                        f"Consolidated from {len(open_proposals)} open proposals:\n\n{descriptions}",
                        top_priority,
                        module_key,
                        __import__("json").dumps({"bundled_from": source_ids}),
                    ),
                )
                bundle_id = cur.fetchone()["id"]

                cur.execute(
                    """UPDATE improvement_proposals
                       SET status = 'superseded', notes = %s
                       WHERE id = ANY(%s::int[])""",
                    (f"Superseded by bundled proposal #{bundle_id}", source_ids),
                )

            return jsonify({"success": True, "proposal_id": bundle_id, "bundled_count": len(open_proposals)})

        except Exception as exc:
            logger.exception("module_review_bundle failed")
            return jsonify({"success": False, "error": str(exc)}), 500
