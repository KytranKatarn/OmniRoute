"""Proposal Service — Improvement proposal lifecycle management.

Migrated from tools/improvements/routes.py (Project #103, Phase 2).
Core CRUD, approval, execution, deployment, and stats.
"""

import json
import logging
import os
from database import _get_db_password
import sys
import threading
import traceback
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Ensure ai_bridge is importable
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def _get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


# ===================================================================
# QUERY OPERATIONS
# ===================================================================


def list_proposals(status=None):
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        base_sql = """SELECT ip.id, ip.title, ip.description, ip.category,
                       ip.priority, ip.status, ip.proposed_at, ip.proposed_by,
                       ip.plan_steps, ip.metadata, ip.assigned_agent_id,
                       ip.code_diff, ip.retry_count,
                       ip.backup_clearance_approved, ip.backup_clearance_reason,
                       ip.backup_clearance_at,
                       a.display_name AS agent_display_name,
                       a.name AS agent_code_name,
                       a.model AS agent_model
                FROM improvement_proposals ip
                LEFT JOIN agents a ON a.id = ip.assigned_agent_id"""
        if status:
            cur.execute(
                base_sql + " WHERE ip.status = %s ORDER BY ip.proposed_at DESC",
                (status,),
            )
        else:
            cur.execute(base_sql + " ORDER BY ip.proposed_at DESC")
        proposals = cur.fetchall()
        out = []
        for p in proposals:
            d = dict(p)
            if d.get("proposed_at"):
                d["proposed_at"] = d["proposed_at"].isoformat()
            if d.get("backup_clearance_at"):
                d["backup_clearance_at"] = d["backup_clearance_at"].isoformat()
            out.append(d)
        return {"success": True, "proposals": out, "count": len(out)}
    except Exception as e:
        logger.error(f"list_proposals: {e}")
        return {"success": False, "error": str(e)}
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


def get_proposal(proposal_id):
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT ip.*, a.display_name AS agent_display_name,
                      a.name AS agent_code_name, a.model AS agent_model
               FROM improvement_proposals ip
               LEFT JOIN agents a ON a.id = ip.assigned_agent_id
               WHERE ip.id = %s""",
            (proposal_id,),
        )
        proposal = cur.fetchone()
        if not proposal:
            return {"success": False, "error": "Proposal not found"}
        d = dict(proposal)
        for f in ["proposed_at", "reviewed_at", "implemented_at", "approved_at"]:
            if d.get(f):
                d[f] = d[f].isoformat()
        return {"success": True, "proposal": d}
    except Exception as e:
        logger.error(f"get_proposal: {e}")
        return {"success": False, "error": str(e)}
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


def delete_proposal(proposal_id):
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, status, title FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()
        if not proposal:
            return {"success": False, "error": "Proposal not found"}
        deletable = ["proposed", "failed", "archived", "rejected", "pending", "pending_approval"]
        if proposal[1] not in deletable:
            return {
                "success": False,
                "error": f'Cannot delete proposal with status "{proposal[1]}". '
                f"Only: {', '.join(deletable)} can be deleted.",
            }
        cur.execute("UPDATE code_issues SET proposal_id = NULL WHERE proposal_id = %s", (proposal_id,))
        cur.execute("DELETE FROM sandbox_instances WHERE proposal_id = %s", (proposal_id,))
        cur.execute("DELETE FROM improvement_proposals WHERE id = %s", (proposal_id,))
        conn.commit()
        return {"success": True, "message": f'Proposal #{proposal_id} "{proposal[2]}" deleted permanently'}
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"delete_proposal: {e}")
        return {"success": False, "error": str(e)}
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


# ===================================================================
# APPROVAL / REJECTION
# ===================================================================


def approve_proposal(proposal_id, user_id):
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """SELECT id, title, description, metadata, plan_steps, category
            FROM improvement_proposals
            WHERE id = %s AND status IN ('pending_approval', 'pending', 'proposed')""",
            (proposal_id,),
        )
        proposal = cur.fetchone()
        if not proposal:
            return {"success": False, "error": "Proposal not found or already processed"}
        prop_id, title, description, metadata, existing_plan, category = proposal

        plan_steps = existing_plan
        if not plan_steps:
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            fp = metadata.get("file_path") if metadata else None
            ln = metadata.get("line_number") if metadata else None
            it = metadata.get("issue_type", category) if metadata else category
            if fp:
                plan_steps = [
                    {
                        "step": 1,
                        "description": "Read and analyze the target file",
                        "action": "read_file",
                        "target": fp,
                        "details": f"Read file around line {ln or 'N/A'}",
                    },
                    {
                        "step": 2,
                        "description": f"Apply the fix: {title}",
                        "action": "edit_file",
                        "target": fp,
                        "details": f"{description}\n\nLine {ln or 'relevant section'}. Issue type: {it}",
                    },
                ]
            else:
                plan_steps = [
                    {
                        "step": 1,
                        "description": "Analyze and implement",
                        "action": "edit_file",
                        "target": "TBD",
                        "details": description or title,
                    }
                ]

        cur.execute(
            """UPDATE improvement_proposals
            SET status = 'approved', approved_by = %s, approved_at = NOW(), reviewed_at = NOW(), plan_steps = %s
            WHERE id = %s RETURNING id""",
            (user_id, json.dumps(plan_steps), proposal_id),
        )
        cur.fetchone()
        conn.commit()

        # Auto-sandbox
        sandbox_info = None
        try:
            from tools.repair_bay.services.sandbox_manager import SandboxManager

            fp = None
            if metadata:
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except Exception:
                        metadata = {}
                fp = metadata.get("file_path")
            mgr = SandboxManager()
            mid = "platform"
            if fp:
                mid = mgr.detect_module_from_filepath(fp)
            sr = mgr.create_module_sandbox(mid, proposal_id)
            if sr:
                sandbox_info = {
                    "module_id": mid,
                    "sandbox_created": True,
                    "schema_name": sr.get("schema_name"),
                    "message": f"Sandbox created for module: {mid}",
                }
                logger.info(f"Auto-created sandbox for proposal {proposal_id}: {mid}")
        except Exception as se:
            logger.warning(f"Could not auto-create sandbox for proposal {proposal_id}: {se}")
            sandbox_info = {"sandbox_created": False, "error": str(se)}

        # Auto-run in background
        threading.Thread(target=auto_run, args=(proposal_id,), daemon=True).start()
        logger.info(f"Auto-run thread started for proposal #{proposal_id}")

        return {
            "success": True,
            "message": "Proposal approved -- auto-execution started",
            "proposal_id": proposal_id,
            "plan_generated": existing_plan is None,
            "steps_count": len(plan_steps) if plan_steps else 0,
            "sandbox": sandbox_info,
            "auto_execution": True,
        }
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"approve_proposal: {e}")
        return {"success": False, "error": str(e)}
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


def reject_proposal(proposal_id, reason="Rejected by user"):
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """UPDATE improvement_proposals
            SET status = 'rejected', reviewed_at = NOW(),
                metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{rejection_reason}', to_jsonb(%s::text))
            WHERE id = %s AND status IN ('pending_approval', 'pending', 'proposed')
            RETURNING id""",
            (reason, proposal_id),
        )
        result = cur.fetchone()
        conn.commit()
        if not result:
            return {"success": False, "error": "Proposal not found or already processed"}
        return {"success": True, "message": "Proposal rejected", "proposal_id": proposal_id}
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"reject_proposal: {e}")
        return {"success": False, "error": str(e)}
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


# ===================================================================
# EXECUTION
# ===================================================================


_PERF_ACTION_PRIORITY = {"rollback": 3, "pause": 2, "flag": 1, "none": 0, None: 0}


def _evaluate_perf_gate(run_ids, proposal_id):
    """Run qa_baseline_service.evaluate_post_deploy for each run and apply the
    strongest action across them (rollback > pause > flag > none).

    Defensive: any failure inside the gate is logged + Telegram'd as
    "FAILED OPEN" — must never raise out of the daemon thread.
    """
    if not run_ids:
        return
    try:
        from services import qa_baseline_service
        from services import telegram_service
        from database import get_db_cursor

        actions = []
        for rid in run_ids:
            try:
                actions.append(qa_baseline_service.evaluate_post_deploy(run_id=rid, proposal_id=proposal_id))
            except Exception as _eval_exc:  # noqa: BLE001 — defensive
                logger.warning("[PerfGate] evaluate_post_deploy failed for run %s: %s", rid, _eval_exc)
                actions.append(None)

        strongest = max(actions, key=lambda a: _PERF_ACTION_PRIORITY.get(a, 0)) if actions else "none"
        logger.info(
            "[PerfGate] proposal #%s — runs=%s actions=%s strongest=%s",
            proposal_id,
            run_ids,
            actions,
            strongest,
        )

        if strongest == "rollback":
            backup_name = None
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT backup_name FROM improvement_proposals WHERE id = %s",
                    (proposal_id,),
                )
                row = cur.fetchone()
                backup_name = row.get("backup_name") if row else None

            if backup_name:
                try:
                    from tools.repair_bay.services.auto_rollback import AutoRollbackManager

                    rb = AutoRollbackManager()
                    rollback_result = rb.rollback_deployment(
                        deployment_id=None,
                        backup_name=backup_name,
                        reason=f"Perf regression on critical test (proposal #{proposal_id})",
                    )
                except Exception as _rb_exc:  # noqa: BLE001
                    rollback_result = {"success": False, "error": str(_rb_exc)}
            else:
                rollback_result = {"success": False, "error": "no backup_name on proposal"}

            if rollback_result.get("success"):
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE improvement_proposals SET status = 'regression' WHERE id = %s",
                        (proposal_id,),
                    )
                telegram_service.send_system(
                    title="AUTO-ROLLBACK — perf regression",
                    message=(
                        f"Critical perf regression on proposal #{proposal_id}. "
                        f"Auto-rollback succeeded (backup: {backup_name})."
                    ),
                    source_agent="P.R.O.B.E.",
                )
            else:
                telegram_service.send_system(
                    title="MANUAL ROLLBACK REQUIRED",
                    message=(
                        f"Critical perf regression on proposal #{proposal_id}. "
                        f"Auto-rollback FAILED: {rollback_result.get('error')}"
                    ),
                    source_agent="P.R.O.B.E.",
                )

        elif strongest == "pause":
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE improvement_proposals SET status = 'paused_for_perf_review' WHERE id = %s",
                    (proposal_id,),
                )
                cur.execute(
                    """
                    INSERT INTO system_config (key, value, updated_at)
                    VALUES ('deploy_paused_perf', 'true', NOW())
                    ON CONFLICT (key) DO UPDATE SET value = 'true', updated_at = NOW()
                    """
                )
            telegram_service.send_system(
                title="DEPLOYS PAUSED — perf regression",
                message=(
                    f"Non-critical perf regression (2-of-3) on proposal #{proposal_id}. "
                    f"Clear via /api/qa/regressions/<id>/clear."
                ),
                source_agent="P.R.O.B.E.",
            )

        elif strongest == "flag":
            telegram_service.send_info(
                title="PERF FLAG",
                message=(f"Perf regression on proposal #{proposal_id}. See dashboard for details."),
                source_agent="P.R.O.B.E.",
            )
        # 'none' / None → no action, no alert

    except Exception as _gate_exc:  # noqa: BLE001 — fail open
        logger.warning("[PerfGate] failed open on proposal #%s: %s", proposal_id, _gate_exc)
        try:
            from services import telegram_service

            telegram_service.send_system(
                title="PERF GATE FAILED OPEN",
                message=(f"Proposal #{proposal_id}: {_gate_exc}. Deploy proceeded without perf check."),
                source_agent="P.R.O.B.E.",
            )
        except Exception:
            pass  # Telegram failure must not propagate


def _trigger_module_qa(prop_meta, proposal_id):
    """Fire P.R.O.B.E. QA suite(s) for the module affected by this proposal.

    Runs in a daemon thread so it never blocks the deploy response.
    Uses the file_path or suite_id stored in proposal metadata.
    After QA completes, evaluates the perf gate and applies
    rollback / pause / flag / none per qa_baseline_service.evaluate_post_deploy.
    """
    import threading

    def _run():
        run_ids = []
        try:
            from services.qa_service import run_suite_for_module, run_suite

            suite_id = (prop_meta or {}).get("suite_id")
            if suite_id:
                logger.info("[QA] Post-deploy: re-running suite %s for proposal #%s", suite_id, proposal_id)
                result = run_suite(int(suite_id), triggered_by=f"repair_bay_deploy:{proposal_id}")
                rid = (result or {}).get("run_id")
                if rid:
                    run_ids.append(rid)
            else:
                file_path = (prop_meta or {}).get("file_path", "")
                if file_path:
                    logger.info("[QA] Post-deploy: scanning module for '%s' (proposal #%s)", file_path, proposal_id)
                    results = run_suite_for_module(file_path, triggered_by=f"repair_bay_deploy:{proposal_id}")
                    for r in results or []:
                        rid = r.get("run_id")
                        if rid:
                            run_ids.append(rid)
        except Exception as exc:
            logger.warning("[QA] Post-deploy QA trigger failed for proposal #%s: %s", proposal_id, exc)

        # Perf gate evaluation runs after QA regardless of which path fired,
        # using whatever run_ids we managed to capture.
        _evaluate_perf_gate(run_ids, proposal_id)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def run_proposal(proposal_id, user_id, skip_backup=False, use_orchestrator=True, steps=None):
    """Run an approved proposal using WorkflowOrchestrator with retry support."""
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT id, status, plan_steps, title FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()
        cur.close()
        conn.close()
        conn = None
        cur = None

        if not proposal:
            return {"success": False, "error": "Proposal not found"}
        if not proposal.get("plan_steps") or len(proposal.get("plan_steps", [])) == 0:
            return {
                "success": False,
                "error": 'No implementation plan found. Click "Regenerate Plan" first.',
                "legacy": True,
            }

        # ── W.A.R.D.E.N. pre-deploy governance check ─────────────────────────────
        if not skip_backup:
            try:
                from services.backup_governance_service import request_deploy_clearance

                # Use priority column (table has no severity column)
                _proposal_severity = "medium"
                try:
                    with get_db_cursor() as (_c2, _cur2):
                        _cur2.execute(
                            "SELECT priority FROM improvement_proposals WHERE id = %s",
                            (proposal_id,),
                        )
                        _row = _cur2.fetchone()
                        if (
                            _row
                            and _row.get("priority")
                            and _row["priority"].lower()
                            in (
                                "critical",
                                "high",
                                "medium",
                                "low",
                            )
                        ):
                            _proposal_severity = _row["priority"].lower()
                except Exception:
                    pass  # priority column fallback — use default

                clearance = request_deploy_clearance(
                    module=str(proposal_id),
                    severity=_proposal_severity,
                    triggered_by="probe",
                    proposal_id=proposal_id,
                )

                # Record clearance result on the proposal row
                try:
                    with get_db_cursor(commit=True) as (_c3, _cur3):
                        _cur3.execute(
                            """UPDATE improvement_proposals SET
                                   backup_clearance_approved = %s,
                                   backup_clearance_snapshot_id = %s,
                                   backup_clearance_reason = %s,
                                   backup_clearance_at = NOW()
                               WHERE id = %s""",
                            (
                                clearance["approved"],
                                clearance.get("snapshot_id"),
                                clearance["reason"],
                                proposal_id,
                            ),
                        )
                except Exception as _upd_err:
                    logger.warning("Could not record clearance on proposal: %s", _upd_err)

                if not clearance["approved"]:
                    return {
                        "success": False,
                        "error": f"W.A.R.D.E.N. clearance denied: {clearance['reason']}",
                        "clearance": clearance,
                    }
            except ImportError:
                pass  # governance service not available — fail open
            except Exception as _gov_err:
                logger.warning("Governance check failed (fail-open): %s", _gov_err)

        # ── F.O.R.G.E. PR compliance check (soft gate — never blocks) ─────────
        try:
            import subprocess as _forge_sp
            from services.forge_gate_service import request_pr_clearance

            _commit = None
            try:
                _commit = (
                    _forge_sp.run(
                        ["git", "-C", "/app", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
                    ).stdout.strip()
                    or None
                )
            except Exception:
                pass
            forge_clearance = request_pr_clearance(
                git_commit=_commit,
                severity=_proposal_severity if "_proposal_severity" in dir() else "medium",
                proposal_id=proposal_id,
            )
            logger.info("F.O.R.G.E. gate: %s", forge_clearance.get("reason"))
        except Exception as _forge_err:
            logger.warning("F.O.R.G.E. gate failed (fail-open): %s", _forge_err)
        # ─────────────────────────────────────────────────────────────────────

        # Step 1: Backup
        backup_result = None
        if not skip_backup:
            try:
                from tools.backup_manager import create_backup

                backup_result = create_backup(
                    description=f"pre_improvement_{proposal_id}", created_by_username="system", proposal_id=proposal_id
                )
                if backup_result and backup_result.get("success"):
                    c = _get_db()
                    cu = c.cursor()
                    cu.execute(
                        "UPDATE improvement_proposals SET backup_name = %s, backup_created_at = NOW() WHERE id = %s",
                        (backup_result["backup_name"], proposal_id),
                    )
                    c.commit()
                    cu.close()
                    c.close()
            except Exception as be:
                logger.warning(f"Backup error (non-fatal): {be}")

        # Step 2: Run
        if use_orchestrator:
            try:
                from workflow_orchestrator import run_workflow

                result = run_workflow(proposal_id)
                if result.get("success") and not result.get("test_passed", True):
                    from retry_handler import handle_test_failure

                    retry_result = handle_test_failure(proposal_id, result.get("test_results", {}))
                    result["retry_info"] = retry_result
                    result["message"] = f"Tests failed. {retry_result.get('message', 'Retry initiated.')}"
            except ImportError:
                from ai_bridge.archie_bridge import execute_proposal as _ep

                result = _ep(proposal_id=proposal_id, user_id=user_id, approved_steps=steps)
        else:
            from ai_bridge.archie_bridge import execute_proposal as _ep

            result = _ep(proposal_id=proposal_id, user_id=user_id, approved_steps=steps)

        if backup_result and backup_result.get("success"):
            result["backup_created"] = True
            result["backup_name"] = backup_result["backup_name"]
            result["backup_path"] = backup_result.get("backup_path")

        # Post-deploy: trigger P.R.O.B.E. QA re-run for the affected module
        # Runs in a daemon thread so it doesn't block the deploy response.
        if result.get("success"):
            _trigger_module_qa(prop_meta, proposal_id)

        return result

    except Exception as e:
        logger.error(f"run_proposal: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}
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


def regenerate_plan(proposal_id):
    conn = None
    cur = None
    try:
        from code_generation_engine import generate_code_for_proposal

        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, title, description, category, priority, metadata FROM improvement_proposals WHERE id = %s",
            (proposal_id,),
        )
        proposal = cur.fetchone()
        if not proposal:
            return {"success": False, "error": "Proposal not found"}

        title = proposal["title"]
        description = proposal["description"] or title
        category = proposal["category"] or "general"
        metadata = proposal["metadata"] or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}

        file_path = metadata.get("file_path")
        target_files = [file_path] if file_path else None
        line_number = metadata.get("line_number")
        issue_context = None
        if metadata.get("issue_type") or metadata.get("severity"):
            issue_context = {
                "issue_type": metadata.get("issue_type"),
                "severity": metadata.get("severity"),
                "line_number": line_number,
                "message": metadata.get("message", description),
                "suggestion": metadata.get("suggestion", metadata.get("fix_suggestion", "")),
            }

        code_result = generate_code_for_proposal(
            proposal_id=proposal_id,
            proposal_title=title,
            proposal_description=description,
            category=category,
            target_files=target_files,
            line_number=line_number,
            issue_context=issue_context,
        )
        if not code_result.get("success"):
            return {
                "success": False,
                "error": f"AI code generation failed: {code_result.get('error', 'Unknown error')}",
            }

        changes = code_result.get("changes", [])
        plan_steps = []
        for i, change in enumerate(changes, 1):
            plan_steps.append(
                {
                    "step": i,
                    "description": change.get("description", f"Change {i}"),
                    "action": change.get("action", "edit_file"),
                    "target": change.get("file_path", "unknown"),
                    "details": change.get("diff", change.get("new_content", "")),
                    "old_content": change.get("old_content", ""),
                    "new_content": change.get("new_content", ""),
                }
            )

        if not plan_steps:
            if file_path:
                plan_steps = [
                    {
                        "step": 1,
                        "description": "Read and analyze the target file",
                        "action": "read_file",
                        "target": file_path,
                        "details": f"Read file around line {line_number or 'N/A'}",
                    },
                    {
                        "step": 2,
                        "description": f"Apply the fix: {title}",
                        "action": "edit_file",
                        "target": file_path,
                        "details": description,
                    },
                ]
            else:
                search_term = title.split(":")[-1].strip() if ":" in title else title
                plan_steps = [
                    {
                        "step": 1,
                        "description": "Search for relevant code",
                        "action": "search_code",
                        "target": search_term[:50],
                        "details": f"Find files related to: {title}",
                    },
                    {
                        "step": 2,
                        "description": f"Implement: {title}",
                        "action": "edit_file",
                        "target": "TBD",
                        "details": description,
                    },
                ]

        cur.execute(
            """UPDATE improvement_proposals
            SET plan_steps = %s, metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb, test_retry_count = 0
            WHERE id = %s RETURNING id""",
            (
                json.dumps(plan_steps),
                json.dumps(
                    {
                        "ai_generated_plan": True,
                        "plan_generated_at": datetime.now().isoformat(),
                        "model_used": code_result.get("metadata", {}).get("model_used", "unknown"),
                        "changes_count": len(changes),
                    }
                ),
                proposal_id,
            ),
        )
        result = cur.fetchone()
        conn.commit()
        if not result:
            return {"success": False, "error": "Failed to update proposal"}

        return {
            "success": True,
            "message": f"AI-generated plan with {len(plan_steps)} executable steps",
            "steps_count": len(plan_steps),
            "proposal_id": proposal_id,
            "ai_generated": True,
            "has_file_target": bool(file_path),
            "model_used": code_result.get("metadata", {}).get("model_used", "unknown"),
        }
    except Exception as e:
        logger.error(f"regenerate_plan: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}
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


def retry_proposal(proposal_id, user_id):
    try:
        from improvement_conversation_engine import retry_proposal_with_escalation

        result = retry_proposal_with_escalation(proposal_id=proposal_id, user_id=user_id)
        if result["success"]:
            return {
                "success": True,
                "escalated": result.get("escalated", False),
                "attempt_number": result.get("attempt_number", 1),
                "assigned_agent": result.get("assigned_agent", "Internal Team"),
                "agent_type": result.get("agent_type", "internal"),
                "message": result.get("response", "Retry started successfully"),
                "proposal_id": proposal_id,
            }
        else:
            return {"success": False, "error": result.get("response", "Failed to retry proposal")}
    except Exception as e:
        logger.error(f"retry_proposal: {e}")
        return {"success": False, "error": str(e)}


# ===================================================================
# ESCALATION / ARCHIVE
# ===================================================================


def escalate_proposal(proposal_id):
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()
        if not proposal:
            return {"success": False, "error": "Proposal not found"}
        cur.execute(
            "UPDATE improvement_proposals SET status = 'escalated', escalated_at = NOW() WHERE id = %s", (proposal_id,)
        )
        cur.execute(
            "INSERT INTO notifications (user_id, type, title, message, is_read) VALUES (%s, %s, %s, %s, FALSE)",
            (
                2,
                "task_escalated",
                f"Failed Task Escalated: Proposal #{proposal_id}",
                f'Proposal "{proposal["title"]}" has failed and needs senior developer attention.',
            ),
        )
        conn.commit()
        return {"success": True, "message": "Proposal escalated to senior developers"}
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"escalate_proposal: {e}")
        return {"success": False, "error": str(e)}
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


def archive_proposal(proposal_id):
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE improvement_proposals SET status = 'archived', archived_at = NOW() WHERE id = %s", (proposal_id,)
        )
        if cur.rowcount == 0:
            return {"success": False, "error": "Proposal not found"}
        conn.commit()
        return {"success": True, "message": "Proposal archived"}
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"archive_proposal: {e}")
        return {"success": False, "error": str(e)}
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


# ===================================================================
# DEPLOY / RESTORE / BACKUPS
# ===================================================================


def _module_backup_ref(backup_result):
    """improvement_deployments.backup_name for a module-scoped snapshot: 'modules/<dir>'.

    Every consumer joins BACKUP_DIR + backup_name — the Deployment tab's
    snapshot_exists check and auto_rollback's backup_path resolution both — so the
    stored name must carry the modules/ subdirectory (#5279)."""
    return "modules/" + str((backup_result or {}).get("backup_name") or "")


def _predeploy_module_scope(proposal):
    """#5279 / ADR-009: the module name when this proposal's change is fully CONTAINED
    in platform_v2/tools/<module>/ — else None, meaning take a FULL snapshot.

    A backup only protects what it contains, so scoping is allowed ONLY when the
    touched file provably lives inside what backup_module() captures. Everything
    else stays on the full-snapshot safety net (task item 4):
      * services / ai_bridge — wide blast radius (the primitive now covers them,
        item 1, but policy keeps them full until the scoped rung is proven there)
      * database/migrations, templates, static, anything outside tools/<module>/
      * containment mismatch (module_name says X, file lives under Y)
      * missing/nonexistent runtime_file, traversal or odd characters
    """
    import json as _json
    import os as _os
    import re as _re

    meta = (proposal or {}).get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = _json.loads(meta)
        except Exception:
            return None
    if not isinstance(meta, dict):
        return None
    module_name = str(meta.get("module_name") or "")
    file_path = str(meta.get("file_path") or "")
    runtime_file = str(meta.get("runtime_file") or "")
    if not module_name or not file_path or not runtime_file:
        return None
    if not _re.fullmatch(r"[A-Za-z0-9_-]+", module_name):
        return None
    if module_name in ("services", "ai_bridge"):
        return None
    if ".." in file_path or ".." in runtime_file:
        return None
    if not file_path.lstrip("/").startswith(f"platform_v2/tools/{module_name}/"):
        return None
    if not _os.path.isabs(runtime_file) or not _os.path.isfile(runtime_file):
        return None
    return module_name


def deploy_to_production(proposal_id):
    """Deploy an approved proposal with backup.

    Inlined from ImprovementManager.deploy_proposal (Phase 5 cleanup).
    """
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Fetch proposal
        cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()
        if not proposal:
            return {"success": False, "error": "Proposal not found"}
        # Accept approved / tested / ready_for_review as deployable
        if proposal["status"] not in ("approved", "tested", "ready_for_review"):
            return {"success": False, "error": f"Proposal cannot be deployed (status: {proposal['status']})"}

        # ── W.A.R.D.E.N. pre-deploy governance clearance (#2706) ─────────────────
        # This is the AUTOMATED deploy path (Telegram deploy_approve, director-approval
        # callback), so it must acknowledge the backup-freshness gate exactly like
        # run_proposal() does — otherwise a whole class of deploys skipped governance.
        # Severity from the proposal's priority column (no severity column). medium/low
        # HARD-block on stale backups; critical/high are advisory. Fail-open so a
        # governance/import error never blocks a deploy.
        _severity = "medium"
        _pri = (proposal.get("priority") or "").lower()
        if _pri in ("critical", "high", "medium", "low"):
            _severity = _pri
        # #5279 / ADR-009: decide the pre-deploy backup scope ONCE, before clearance,
        # so the gate can judge the scope that matters (a fresh module copy vs the
        # stale full snapshot that was starving its own drain).
        scoped_module = _predeploy_module_scope(proposal)
        try:
            from services.backup_governance_service import request_deploy_clearance
            from database import get_db_cursor

            clearance = request_deploy_clearance(
                module=str(proposal_id),
                severity=_severity,
                triggered_by="deploy_to_production",
                proposal_id=proposal_id,
                deploy_scope="scoped" if scoped_module else "full",
            )
            try:
                with get_db_cursor(commit=True) as (_cc, _clr_cur):
                    _clr_cur.execute(
                        """UPDATE improvement_proposals SET
                               backup_clearance_approved = %s,
                               backup_clearance_snapshot_id = %s,
                               backup_clearance_reason = %s,
                               backup_clearance_at = NOW()
                           WHERE id = %s""",
                        (clearance["approved"], clearance.get("snapshot_id"), clearance["reason"], proposal_id),
                    )
            except Exception as _upd_err:
                logger.warning("Could not record clearance on proposal %s: %s", proposal_id, _upd_err)
            if not clearance["approved"]:
                return {
                    "success": False,
                    "error": f"W.A.R.D.E.N. clearance denied: {clearance['reason']}",
                    "clearance": clearance,
                }
        except ImportError:
            pass  # governance service unavailable — fail open
        except Exception as _gov_err:
            logger.warning("Governance check failed (fail-open): %s", _gov_err)

        # --- Create pre-deploy backup via Backup Manager (#5279 / ADR-009) ---
        # Scoped-by-default: a change contained in tools/<module>/ gets a FRESH module
        # backup (0-2 MB, instant, ships rollback.sh) instead of the 2.3 GB / 16-min
        # full snapshot — measured 77 runs = 179 GB + 20.5 h in one week, protecting
        # single-line lint fixes and starving the freshness gate. FULL remains the
        # safety net for migrations, services/, ai_bridge/, multi-module and anything
        # unresolvable — and a scoped-backup FAILURE falls UP to full, never down to
        # nothing.
        from tools.backup_manager._shared import backup_module as _backup_module
        from tools.backup_manager._shared import create_backup_programmatic
        from database import get_db_cursor as _get_db_cursor

        backup_result = None
        if scoped_module:
            backup_result = _backup_module(
                scoped_module,
                proposal_id=proposal_id,
                created_by_username="system",
                predeploy=True,
            )
            if backup_result.get("success"):
                backup_result = dict(backup_result)
                backup_result["backup_name"] = _module_backup_ref(backup_result)
            else:
                logger.warning(
                    "Scoped pre-deploy backup failed for proposal %s (%s) — falling back to FULL",
                    proposal_id,
                    backup_result.get("error"),
                )
                backup_result = None
        if backup_result is None:
            # #5812: a batch of N deploys took N FULL ~2.8 GB snapshots of a tree that never
            # changed (deploy_to_production applies no code — #5808): ~33 GB measured for one
            # batch of 12. Reuse a recent snapshot when the tree is PROVABLY identical.
            #
            # Decided by the ARTIFACT, never the clock — a matching fingerprint is required and
            # recency is only a secondary bound. FAIL CLOSED everywhere: no fingerprint, no
            # match, or any exception -> a fresh backup. Wasting 2.8 GB is cheap; deploying
            # against a restore point that does not match the tree is not.
            #
            # The fingerprint is stamped into backup_log.notes AFTER creation, never into the
            # description — create_backup_programmatic derives the backup DIRECTORY NAME from
            # the description, so putting it there would pollute the path.
            _reused, _fp = None, None
            try:
                from services.predeploy_backup_reuse import (
                    FINGERPRINT_PREFIX,
                    REUSE_MAX_AGE_MINUTES,
                    pick_reusable_backup,
                    tree_fingerprint,
                )

                _app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                _fp = tree_fingerprint([_app_root])
                if _fp:
                    with _get_db_cursor() as (_rc, _rcur):
                        # backup_log has NO backup_name column — the name is the BASENAME of
                        # file_path (verified: /backups/20260819_125159_Pre-deploy_...).
                        # Querying a column that does not exist would throw on every deploy and
                        # fall through to a fresh backup forever: a feature that can never fire.
                        _rcur.execute(
                            """SELECT regexp_replace(file_path, '^.*/', '') AS backup_name,
                                      notes,
                                      EXTRACT(EPOCH FROM (now() - created_at))/60.0 AS age_minutes
                                 FROM backup_log
                                WHERE status = 'success'
                                  AND file_path IS NOT NULL
                                  AND notes LIKE %s
                                  AND created_at > now() - make_interval(mins => %s)
                                ORDER BY created_at DESC LIMIT 10""",
                            (f"%{FINGERPRINT_PREFIX}%", REUSE_MAX_AGE_MINUTES),
                        )
                        _cands = [dict(r) for r in _rcur.fetchall()]
                    _reused = pick_reusable_backup(_cands, _fp)
            except Exception as _reuse_err:
                logger.warning("pre-deploy backup reuse check failed (taking a fresh backup): %s", _reuse_err)
                _reused = None

            if _reused:
                logger.info(
                    "proposal %s: REUSING pre-deploy backup %s (tree fingerprint %s unchanged)",
                    proposal_id,
                    _reused,
                    _fp,
                )
                backup_result = {"success": True, "backup_name": _reused, "reused": True, "tree_fingerprint": _fp}
            else:
                backup_result = create_backup_programmatic(
                    description=f"Pre-deploy snapshot for proposal #{proposal_id}: {proposal['title'][:60]}",
                    created_by_username="system",
                    proposal_id=proposal_id,
                )
                # Stamp the fingerprint so the NEXT deploy in this batch can match it.
                # Non-fatal: without the stamp we simply take another full backup.
                if _fp and backup_result and backup_result.get("success"):
                    try:
                        from services.predeploy_backup_reuse import FINGERPRINT_PREFIX as _FPP

                        with _get_db_cursor(commit=True) as (_sc, _scur):
                            _scur.execute(
                                "UPDATE backup_log SET notes = COALESCE(notes,'') || %s "
                                "WHERE id = (SELECT max(id) FROM backup_log WHERE status='success')",
                                (f" {_FPP}{_fp}",),
                            )
                    except Exception as _stamp_err:
                        logger.warning("could not stamp tree fingerprint on backup: %s", _stamp_err)
        backup_name = backup_result.get("backup_name", "") if backup_result.get("success") else ""

        # Record in improvement_deployments so Deployment Backups tab shows it
        if backup_name:
            try:
                with _get_db_cursor(commit=True) as (dconn, dcur):
                    dcur.execute(
                        """INSERT INTO improvement_deployments
                           (proposal_id, backup_name, deployment_type, status)
                           VALUES (%s, %s, 'manual', 'deploying')""",
                        (proposal_id, backup_name),
                    )
            except Exception as be:
                logger.warning("Failed to record pre-deploy backup in improvement_deployments: %s", be)

        # --- Deployment log ---
        code_changes = proposal.get("code_changes", "")
        backup_dir = backup_result.get("backup_path", "") if backup_result.get("success") else ""
        deployment_log = [
            f"Backup created: {backup_name}" if backup_name else "Backup skipped (backup manager unavailable)",
            f"Code changes ready to apply: {len(code_changes)} characters",
            "Manual deployment required - automatic code application disabled for safety",
        ]

        # --- Mark as deployed ---
        cur.execute(
            """UPDATE improvement_proposals
               SET status = 'deployed',
                   deployed_at = %s,
                   metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
               WHERE id = %s""",
            (
                datetime.now(),
                json.dumps(
                    {
                        "backup": {
                            "backup_name": backup_name,
                            "backup_dir": str(backup_dir),
                        },
                        "deployment_log": deployment_log,
                        "deployed_timestamp": datetime.now().isoformat(),
                        # #5808: status='deployed' means "backed up and cleared to apply",
                        # NOT "the code is live". This path never writes production files.
                        # Machine-readable so nothing downstream has to parse the prose in
                        # deployment_log to learn the truth.
                        "code_applied": False,
                        "apply_mode": "manual",
                    }
                ),
                proposal_id,
            ),
        )
        conn.commit()

        # ⚠️ DELIBERATELY NOT marking code_issues 'fixed' here (#5808, 2026-08-19).
        # This function does NOT apply code to production — see the deployment_log it
        # builds three lines up: "Manual deployment required - automatic code
        # application disabled for safety". It takes a backup and stops.
        #
        # Marking the linked issues 'fixed' therefore closed REAL, STILL-PRESENT defects:
        # the scanner stopped re-proposing them, so the debt became invisible rather than
        # resolved. Measured on proposal 8658 — the file it claimed to have fixed had not
        # been written in three weeks (mtime), in the repo, the container OR the sandbox.
        #
        # An issue is fixed when the CODE changes, never when a proposal is approved.
        # The issues stay open; `reverify_deployed_findings()` (audit_pipeline) re-audits
        # deployed proposals and is the correct place to close them, because it looks at
        # the artifact. Gate on the artifact, not the status field (ADR-014).
        logger.info(
            "proposal %s: code_issues left OPEN — this path applies no code (see deployment_log)",
            proposal_id,
        )

        # ── C.O.D.E.X. auto-documents the deploy (non-blocking, fire-and-forget) ─
        try:
            from services.codex_gate_service import document_deploy

            document_deploy(
                module=proposal.get("file_path", f"proposal_{proposal_id}"),
                git_commit=locals().get("_commit"),
                changes_summary=f"Repair Bay proposal #{proposal_id} deployed",
                proposal_id=proposal_id,
            )
        except Exception as _doc_err:
            logger.warning("C.O.D.E.X. doc gate suppressed: %s", _doc_err)
        # ─────────────────────────────────────────────────────────────────────────

        return {
            "success": True,
            "message": "Proposal deployed with backup",
            "backup": {"backup_name": backup_name, "backup_dir": str(backup_dir)},
            "deployment_log": deployment_log,
        }
    except Exception as e:
        logger.error(f"deploy_to_production: {e}")
        if conn:
            conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def restore_proposal(proposal_id):
    try:
        from ai_bridge.archie_bridge import restore_from_backups, get_proposal_backups

        backups_result = get_proposal_backups(proposal_id)
        if not backups_result["success"]:
            return backups_result
        if backups_result["count"] == 0:
            return {"success": False, "error": "No backups found for this proposal"}
        return restore_from_backups(proposal_id, backups_result["backups"])
    except Exception as e:
        logger.error(f"restore_proposal: {e}")
        return {"success": False, "error": str(e)}


def get_backups(proposal_id):
    try:
        from ai_bridge.archie_bridge import get_proposal_backups

        return get_proposal_backups(proposal_id)
    except Exception as e:
        logger.error(f"get_backups: {e}")
        return {"success": False, "error": str(e)}


# ===================================================================
# STATS
# ===================================================================


def get_stats():
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'pending' OR status = 'proposed') as pending,
                COUNT(*) FILTER (WHERE status = 'approved') as approved,
                COUNT(*) FILTER (WHERE status = 'deployed' OR status = 'implemented') as deployed,
                COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                COUNT(*) FILTER (WHERE status = 'testing') as testing,
                COUNT(*) FILTER (WHERE status = 'in_progress') as in_progress
            FROM improvement_proposals"""
        )
        stats = cur.fetchone()
        cur.execute(
            "SELECT id, title, status, proposed_at FROM improvement_proposals ORDER BY proposed_at DESC LIMIT 5"
        )
        recent = cur.fetchall()
        return {"success": True, "stats": dict(stats) if stats else {}, "recent": [dict(r) for r in recent]}
    except Exception as e:
        logger.error(f"get_stats: {e}")
        return {"success": False, "error": str(e)}
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


def get_stuck():
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT id, title, description, category, priority, status, proposed_at,
                EXTRACT(EPOCH FROM (NOW() - proposed_at))/3600 as hours_stuck
            FROM improvement_proposals
            WHERE status IN ('pending', 'pending_approval', 'proposed')
            AND proposed_at < NOW() - INTERVAL '48 hours'
            ORDER BY proposed_at ASC"""
        )
        stuck = cur.fetchall()
        return {"success": True, "stuck_proposals": stuck, "count": len(stuck)}
    except Exception as e:
        logger.error(f"get_stuck: {e}")
        return {"success": False, "error": str(e)}
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


# ===================================================================
# DEPLOY HISTORY (absorbed from deploy_routes.py)
# ===================================================================


def get_deploy_history():
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT id, title, category, priority, risk_level, status, deployed_at, approved_at, backup_name, metadata
            FROM improvement_proposals WHERE status IN ('deployed', 'implemented')
            ORDER BY deployed_at DESC NULLS LAST LIMIT 50"""
        )
        deployments = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT
                COUNT(*) FILTER (WHERE status IN ('deployed', 'implemented')) as total_deployed,
                COUNT(*) FILTER (WHERE status = 'tested') as ready_to_deploy,
                COUNT(*) FILTER (WHERE status = 'fix_requested') as failed
            FROM improvement_proposals"""
        )
        deploy_stats = dict(cur.fetchone())
        return {"success": True, "deployments": deployments, "stats": deploy_stats}
    except Exception as e:
        logger.error(f"get_deploy_history: {e}")
        return {"success": False, "error": str(e)}
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


# ---------------------------------------------------------------------------
# Tiered Deployment Approval (org-chart routing)
# ---------------------------------------------------------------------------

# Maps proposal category → (department, director_agent, dispatch_capability)
_CATEGORY_APPROVER = {
    "code": ("Engineering & Technology", "F.O.R.G.E.", "code_review"),
    "refactoring": ("Engineering & Technology", "F.O.R.G.E.", "code_review"),
    "performance": ("Engineering & Technology", "F.O.R.G.E.", "code_review"),
    "bug": ("Engineering & Technology", "F.O.R.G.E.", "code_review"),
    "large_file": ("Engineering & Technology", "F.O.R.G.E.", "code_review"),
    "direct_ollama": ("Engineering & Technology", "F.O.R.G.E.", "code_review"),
    "security": ("Security & Compliance", "V.I.G.I.L.", "security"),
    "compliance": ("Security & Compliance", "V.I.G.I.L.", "compliance"),
    "documentation": ("Documentation & Knowledge", "C.O.D.E.X.", "documentation"),
    "infrastructure": ("Operations & Infrastructure", "B.A.S.E.", "general"),
    "research": ("Research & Development", "D.A.R.W.I.N.", "research"),
}
_DEFAULT_APPROVER = ("Engineering & Technology", "F.O.R.G.E.", "code_review")

# Risk → tier:
#   low      = Tier 1 — F.O.R.G.E. auto-dispatch (no human needed)
#   medium   = Tier 1 — Dept director auto-dispatch (LLM review, no Telegram)
#   high     = Tier 2 — A.R.C.H.I.E. Telegram (Kytran approves as A.R.C.H.I.E.)
#   critical = Tier 2 — Kytran explicit Telegram (human sign-off mandatory)
_RISK_TIER = {"low": 1, "medium": 1, "high": 2, "critical": 2}


def _get_approver(proposal):
    """Return (dept, director, capability, tier, telegram_target) for a proposal."""
    risk = (proposal.get("risk_level") or "medium").lower()
    category = (proposal.get("category") or "code").lower()
    dept, director, cap = _CATEGORY_APPROVER.get(category, _DEFAULT_APPROVER)
    tier = _RISK_TIER.get(risk, 2)
    if risk == "critical":
        telegram_target = "Kytran"
    elif risk == "high":
        telegram_target = "A.R.C.H.I.E."
    else:
        telegram_target = director
    return {
        "dept": dept,
        "director": director,
        "capability": cap,
        "tier": tier,
        "telegram_target": telegram_target,
        "risk": risk,
    }


def _diff_target_contained(rel):
    """True iff ``rel`` is a traversal-free path inside a gateable root
    (``platform_v2/`` or ``ai_bridge/``).

    A naive ``rel.startswith("platform_v2/")`` accepts
    ``platform_v2/../../etc/cron.d/x``, which then escapes the worktree via the
    ``_basesync_touched`` ``shutil.copyfile`` that runs BEFORE ``git apply``'s own
    path protection. Rejects absolute paths and any ``..`` component. (#4979)
    """
    import os

    if not isinstance(rel, str) or not rel.strip():
        return False
    p = rel.strip().replace("\\", "/")
    if p.startswith("/") or ".." in p.split("/"):
        return False
    norm = os.path.normpath(p).replace("\\", "/")
    if norm.startswith("/") or norm == ".." or norm.startswith("../"):
        return False
    return norm.startswith("platform_v2/") or norm.startswith("ai_bridge/")


def _basesync_touched(worktree_root, touched):
    """Copy each touched file's CURRENT prod source into the staging worktree so
    `git apply --check` measures drift against what the fix was cut from. Reuses
    the audit resolver (single source of truth for in-container prod paths:
    platform_v2/* -> /app, ai_bridge/* -> real path). Raises on any miss (fail-closed).
    """
    import os
    import shutil

    from services.audit_pipeline import resolve_proposal_source

    root_real = os.path.realpath(worktree_root)
    for rel in touched:
        prod_abs, _display, status = resolve_proposal_source(rel)
        if status != "ok" or not prod_abs:
            raise RuntimeError(f"cannot resolve prod source for {rel} (status={status})")
        dest = os.path.join(worktree_root, rel)
        # Containment (#4979): a symlink in the worktree could still redirect the
        # write outside it — realpath the dest and refuse anything beyond root.
        if os.path.realpath(dest) != root_real and not os.path.realpath(dest).startswith(root_real + os.sep):
            raise RuntimeError(f"refusing to base-sync outside worktree: {rel}")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(prod_abs, dest)


def _apply_fix_to_sandbox(sandbox_path, code_changes):
    """Apply a proposal's unified-diff ``code_changes`` into the staging worktree.

    NEW CONTRACT (2026-07-18, HoloDeck-P0): ``code_changes`` is a unified DIFF
    string with repo-relative headers (``a/platform_v2/...``, ``b/ai_bridge/...``);
    ``sandbox_path`` is the worktree ROOT ``/mnt/archie_sandbox``. Base-syncs each
    touched file from live prod, then ``git apply --check`` (FAIL CLOSED on drift)
    then ``git apply``. Returns {"applied":[rel,...], "expected":int, "error":str|None}.
    The caller MUST revert ``applied`` afterward.
    """
    import os
    import subprocess
    import tempfile

    def _git(*args):
        # -c safe.directory=* : the sandbox worktree is root-owned but git in
        # this container runs as a different uid — without this flag EVERY
        # git invocation aborts with "detected dubious ownership" (rc=128).
        return ["git", "-c", "safe.directory=*", "-C", sandbox_path, *args]

    result = {"applied": [], "expected": 0, "error": None}

    if not os.path.isdir(sandbox_path):
        result["error"] = (
            f"sandbox worktree {sandbox_path} is not mounted/present in this "
            f"container — cannot apply fix; gate fails closed"
        )
        return result
    if not isinstance(code_changes, str) or not code_changes.strip():
        result["error"] = "code_changes is not a unified-diff string — nothing to validate"
        return result

    touched = [ln[len("+++ b/") :].strip() for ln in code_changes.splitlines() if ln.startswith("+++ b/")]
    if not touched:
        result["error"] = "diff has no target files (+++ b/...) — nothing to validate"
        return result
    result["expected"] = len(touched)

    for rel in touched:
        if not _diff_target_contained(rel):
            result["error"] = (
                f"{rel} is not a contained gateable path in the staging worktree "
                f"(platform_v2/ or ai_bridge/, no traversal) — cannot gate"
            )
            return result

    # Base-sync so --check measures drift against current prod.
    try:
        _basesync_touched(sandbox_path, touched)
    except Exception as sync_err:
        # A partial base-sync can leave earlier-copied files dirty in the
        # worktree. Revert the full touched set (no-op for files never
        # copied) so the worktree stays clean on failure.
        subprocess.run(_git("checkout", "--", *touched), capture_output=True, timeout=30)
        result["error"] = f"base-sync failed: {sync_err}"
        return result

    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as fh:
            fh.write(code_changes)
            tmp = fh.name
        check = subprocess.run(
            _git("apply", "--check", tmp),
            capture_output=True,
            timeout=30,
        )
        if check.returncode != 0:
            # Revert the base-synced files so the worktree is left clean.
            subprocess.run(_git("checkout", "--", *touched), capture_output=True, timeout=30)
            result["error"] = f"git apply --check failed (drift/unapplicable): {check.stderr.decode()[:300]}"
            return result
        applied = subprocess.run(
            _git("apply", tmp),
            capture_output=True,
            timeout=30,
        )
        if applied.returncode != 0:
            subprocess.run(_git("checkout", "--", *touched), capture_output=True, timeout=30)
            result["error"] = f"git apply failed: {applied.stderr.decode()[:300]}"
            return result
        result["applied"] = touched
        return result
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _sandbox_gate(proposal_id, proposal):
    """Apply fix to sandbox branch, restart archie_staging, run P.R.O.B.E. suite #79.

    Returns {"passed": bool, "passed_count": int, "total": int, "run_id": int, "error": str|None}

    FAIL-CLOSED: if the fix cannot be fully applied to the staging worktree
    (worktree not mounted, unparseable/empty changes, or any write error) the
    gate returns passed=False WITHOUT running the QA suite — validating stale
    staging code could false-pass a production deploy.
    """
    import subprocess

    sandbox_path = "/mnt/archie_sandbox"  # worktree root; .git resolves here
    code_changes = proposal.get("code_changes")

    # Apply code changes to the staging worktree. If we cannot FULLY apply the
    # fix, do NOT proceed to validate — QA against stale code could false-pass.
    applied_files = []
    if code_changes:
        apply_res = _apply_fix_to_sandbox(sandbox_path, code_changes)
        if apply_res["error"]:
            logger.warning("sandbox_gate: apply failed for #%s — %s", proposal_id, apply_res["error"])
            return {
                "passed": False,
                "passed_count": 0,
                "total": 0,
                "run_id": None,
                "applied_files": apply_res["applied"],
                "error": f"code apply failed: {apply_res['error']}",
            }
        applied_files = apply_res["applied"]

    def _revert_and_restart():
        import subprocess

        def _git(*args):
            # -c safe.directory=* : sandbox worktree is root-owned, git here
            # runs as a different uid — without this every git call aborts
            # with "detected dubious ownership" (rc=128). Previously ignored
            # because the return code was never checked (silent worktree-dirty bug).
            return ["git", "-c", "safe.directory=*", "-C", sandbox_path, *args]

        if applied_files:
            r = subprocess.run(_git("checkout", "--", *applied_files), capture_output=True, timeout=30)
            if r.returncode != 0:
                logger.warning(
                    "sandbox_gate: revert checkout rc=%s stderr=%s",
                    r.returncode,
                    r.stderr.decode()[:200],
                )
        subprocess.run(
            [
                "docker",
                "compose",
                "--file",
                "/mnt/archie_brain/docker-compose.staging.yml",
                "restart",
                "archie_staging",
            ],
            capture_output=True,
            timeout=30,
        )

    try:
        import subprocess
        import time

        # Restart archie_staging so the applied change takes effect.
        subprocess.run(
            [
                "docker",
                "compose",
                "--file",
                "/mnt/archie_brain/docker-compose.staging.yml",
                "restart",
                "archie_staging",
            ],
            timeout=30,
            capture_output=True,
        )
        time.sleep(5)

        from services.qa_service import run_suite

        result = run_suite(79, triggered_by=f"tiered_approval_gate_proposal_{proposal_id}")
        passed = result.get("passed", 0)
        total = result.get("total", 0)
        run_id = result.get("run_id")
        gate_passed = total > 0 and passed == total
        return {
            "passed": gate_passed,
            "passed_count": passed,
            "total": total,
            "run_id": run_id,
            "applied_files": applied_files,
            "error": None,
        }
    except Exception as qa_err:
        logger.error("sandbox_gate: QA run failed: %s", qa_err)
        return {
            "passed": False,
            "passed_count": 0,
            "total": 0,
            "run_id": None,
            "applied_files": applied_files,
            "error": str(qa_err),
        }
    finally:
        try:
            _revert_and_restart()
        except Exception as rev_err:
            logger.error("sandbox_gate: revert failed for #%s — staging may be dirty: %s", proposal_id, rev_err)


def request_tiered_deploy_approval(proposal_id, force_tier=None):
    """Route deployment through org-chart approvers with mandatory sandbox gate.

    Flow per risk level (from _RISK_TIER):
      low    → F.O.R.G.E. code_review dispatch (auto) → sandbox gate → deploy
      medium → F.O.R.G.E. code_review dispatch (auto) → sandbox gate → deploy
      high   → A.R.C.H.I.E. Telegram to Kytran → sandbox gate → deploy
      critical → same as high + priority=critical

    ``force_tier=2`` overrides the risk→tier mapping and sends the proposal to
    Telegram approval regardless of risk. Callers use this when a class of change
    must have a human in the loop even though its computed risk is low/medium —
    e.g. the deterministic fixer's bulk mechanical fixes, where the volume (100+)
    is itself the risk and unattended auto-approve is not acceptable. Owner
    decision 2026-07-20: mechanical fixes go to Telegram, not F.O.R.G.E. auto.

    NOTE the docstring previously claimed medium → director Telegram; _RISK_TIER
    actually maps medium → 1 (auto). Corrected above rather than silently changing
    the mapping, which would re-route every medium-risk deploy on the platform.

    Returns:
      {success, deployed, pending, approver, tier, sandbox, message}
    """
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM improvement_proposals WHERE id = %s", (proposal_id,))
        proposal = cur.fetchone()
        if not proposal:
            return {"success": False, "error": "Proposal not found"}
        if proposal["status"] not in ("approved", "tested", "ready_for_review", "sandboxed"):
            return {"success": False, "error": f"Proposal not ready for deployment (status: {proposal['status']})"}
        cur.close()
        conn.close()
        conn = cur = None
    except Exception as e:
        logger.error("request_tiered_deploy_approval fetch: %s", e)
        return {"success": False, "error": str(e)}
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

    routing = _get_approver(proposal)
    tier = routing["tier"]
    if force_tier in (1, 2) and force_tier != tier:
        logger.info(
            "deploy_approval: proposal #%s tier %s -> %s (caller override; risk=%s)",
            proposal_id,
            tier,
            force_tier,
            routing["risk"],
        )
        tier = force_tier
    director = routing["director"]
    cap = routing["capability"]
    risk = routing["risk"]

    # ── Tier 1: Queue to DHQ dispatch_pending_queue (async, non-blocking) ────────
    # model_dispatch_worker (15s job) picks this up, runs the LLM review, then
    # fires the deploy_approve_gate callback which runs _sandbox_gate + deploy.
    # The HTTP caller gets an immediate response — no synchronous LLM wait.
    if tier == 1:
        import json as _json

        review_prompt = (
            f"Review deployment of proposal #{proposal_id}: {proposal['title']}.\n"
            f"Risk: {risk}. Category: {proposal.get('category', 'code')}.\n"
            f"Code changes summary: {str(proposal.get('code_changes', ''))[:600]}\n"
            f"Respond APPROVED or REJECTED and a one-line reason."
        )
        # Look up director agent model
        try:
            from database import get_db_cursor as _get_db_cursor

            with _get_db_cursor() as (_c, _cur):
                _cur.execute(
                    "SELECT id, model FROM agents WHERE name = %s AND shift_state != 'decommissioned' LIMIT 1",
                    (director,),
                )
                _a = _cur.fetchone()
            agent_db_id = _a["id"] if _a else None
            agent_model = _a["model"] if _a else "mistral:7b"
        except Exception:
            agent_db_id = None
            agent_model = "mistral:7b"

        try:
            from database import get_db_cursor as _gdc

            with _gdc(commit=True) as (_conn2, _cur2):
                _cur2.execute(
                    """
                    INSERT INTO dispatch_pending_queue
                        (capability, model_needed, model_type, prompt,
                         agent_name, agent_id, module_id, source_product,
                         requested_by, priority, callback_type, callback_data)
                    VALUES (%s,%s,'llama',%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        cap,
                        agent_model,
                        review_prompt,
                        director,
                        agent_db_id,
                        "repair_bay",
                        "archie_platform",
                        "repair_bay_deploy",
                        7,
                        "deploy_approve_gate",
                        _json.dumps({"proposal_id": proposal_id}),
                    ),
                )
                _row = _cur2.fetchone()
                queue_id = _row["id"] if _row else None

            logger.info(
                "deploy_approval: queued proposal #%s for %s review → queue_id=%s",
                proposal_id,
                director,
                queue_id,
            )
            return {
                "success": True,
                "deployed": False,
                "pending": True,
                "queued": True,
                "queue_id": queue_id,
                "approver": director,
                "tier": 1,
                "message": (
                    f"Queued for {director} review via DHQ (queue #{queue_id}). "
                    f"model_dispatch_worker will execute — sandbox gate + deploy run automatically on approval."
                ),
            }
        except Exception as queue_err:
            logger.error("Tier-1 DHQ queue failed: %s", queue_err)
            return {
                "success": False,
                "deployed": False,
                "pending": False,
                "approver": director,
                "tier": 1,
                "error": f"Failed to queue for {director} review: {queue_err}",
            }

    # ── Tier 2: Telegram approval (director or A.R.C.H.I.E.) ──────────────────
    else:
        from ai_bridge.agent_loop import request_approval

        telegram_target = routing["telegram_target"]
        priority = 10 if risk == "critical" else 7 if risk == "high" else 5
        approval_id = request_approval(
            action_type="deploy_approve",
            action_data={
                "proposal_id": proposal_id,
                "risk_level": risk,
                "director": director,
                "category": proposal.get("category", ""),
            },
            reason=(
                f"{risk.upper()} risk deployment: #{proposal_id} {proposal['title'][:60]} — "
                f"requires {telegram_target} approval before sandbox gate + production deploy"
            ),
            requested_by="system",
            tier=2,
            priority=priority,
        )
        return {
            "success": True,
            "deployed": False,
            "pending": True,
            "approver": telegram_target,
            "tier": 2,
            "approval_id": approval_id,
            "message": (
                f"Sent to {telegram_target} for approval via Telegram. "
                f"Once approved, sandbox gate (P.R.O.B.E. #79) runs automatically before production deploy."
            ),
        }


def get_deploy_ready():
    conn = None
    cur = None
    try:
        conn = _get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT id, title, category, priority, risk_level, status, approved_at, metadata
            FROM improvement_proposals
            WHERE status IN ('ready_for_review', 'tested', 'sandboxed')
            ORDER BY
              CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
              approved_at ASC"""
        )
        return {"success": True, "proposals": [dict(r) for r in cur.fetchall()]}
    except Exception as e:
        logger.error(f"get_deploy_ready: {e}")
        return {"success": False, "error": str(e)}
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


# ===================================================================
# BACKGROUND AUTO-RUN (used by agent_loop.py + approve_proposal)
# ===================================================================


def auto_run(proposal_id):
    """Background thread: auto-run approved proposal through code gen, sandbox, test.

    Status transitions: approved -> code_generating -> testing -> tested / fix_requested
    """
    logger.info(f"[AutoRun] Starting for proposal #{proposal_id}")
    try:
        _update_status(proposal_id, "code_generating")
        try:
            gen_result = regenerate_plan(proposal_id)
        except Exception as e:
            logger.error(f"[AutoRun] Code generation failed for #{proposal_id}: {e}")
            _update_status(proposal_id, "fix_requested", error=str(e))
            _notify_admin(proposal_id, "error", f"Code generation failed: {e}")
            return

        if not gen_result or not gen_result.get("success", True):
            error_msg = gen_result.get("error", "Code generation returned no results") if gen_result else "No result"
            _update_status(proposal_id, "fix_requested", error=error_msg)
            _notify_admin(proposal_id, "warning", f"Code generation issue: {error_msg}")
            return

        _update_status(proposal_id, "testing")
        try:
            from tools.repair_bay.services.sandbox_manager import SandboxManager

            mgr = SandboxManager()
            test_result = mgr.run_tests_for_proposal(proposal_id)
        except Exception as e:
            logger.warning(f"[AutoRun] Sandbox testing failed for #{proposal_id}: {e}")
            _update_status(proposal_id, "tested", error=f"Tests unavailable: {e}")
            _notify_admin(
                proposal_id,
                "info",
                f"Proposal #{proposal_id} approved -- sandbox tests unavailable, ready for manual review",
            )
            return

        if test_result and test_result.get("overall_status") == "passed":
            _update_status(proposal_id, "tested")
            _notify_admin(proposal_id, "success", f"Proposal #{proposal_id} passed all tests -- ready for deployment")
        else:
            error_detail = test_result.get("summary", "Tests failed") if test_result else "No test results"
            _update_status(proposal_id, "fix_requested", error=str(error_detail))
            _notify_admin(proposal_id, "warning", f"Proposal #{proposal_id} failed tests: {error_detail}")

    except Exception as e:
        logger.error(f"[AutoRun] Unexpected error for #{proposal_id}: {e}")
        _update_status(proposal_id, "fix_requested", error=str(e))
        _notify_admin(proposal_id, "error", f"Auto-run failed: {e}")


# ===================================================================
# PRIVATE HELPERS
# ===================================================================


def _update_status(proposal_id, status, error=None):
    try:
        conn = _get_db()
        cur = conn.cursor()
        if error:
            cur.execute(
                "UPDATE improvement_proposals SET status = %s, metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb WHERE id = %s",
                (status, json.dumps({"execution_log": error, "last_status_change": status}), proposal_id),
            )
        else:
            cur.execute("UPDATE improvement_proposals SET status = %s WHERE id = %s", (status, proposal_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update proposal #{proposal_id} status to {status}: {e}")


def _notify_admin(proposal_id, notif_type, message):
    type_map = {"success": "success", "warning": "warning", "error": "error", "info": "info"}
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO system_notifications (type, title, message, source, visibility) VALUES (%s, %s, %s, 'improvement_pipeline', 'admin')",
            (type_map.get(notif_type, "info"), f"Improvement #{proposal_id}", message),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to create notification for proposal #{proposal_id}: {e}")
