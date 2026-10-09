"""Serving-process evidence required to complete a merged Code Health repair."""

import hashlib
import json
import subprocess
from database import get_db_cursor


# PID 1 guards against a fresh worker inheriting stale preloaded modules. This
# receipt is captured in the serving process, never supplied by a browser.
import psutil

RUNTIME_STARTED_AT = min(psutil.Process().create_time(), psutil.Process(1).create_time())


def verify_completion(proposal_id):
    """Require fresh runtime, exact deployed artifact, module QA and finding proof."""
    from services.repair_submission import metadata

    from pathlib import Path

    from services.audit_pipeline import resolve_proposal_source
    from services.code_health_repairs import module_from_file_path
    from services.code_issue_reconciler import finding_still_reproduces, proposal_message
    from services.qa_service import MODULE_SUITE_MAP
    from services.time_utils import now_utc

    with get_db_cursor(commit=True) as (_, cur):
        cur.execute("SELECT * FROM improvement_proposals WHERE id=%s FOR UPDATE", (proposal_id,))
        row = cur.fetchone()
        meta = metadata(row and row.get("metadata"))
        if not row or meta.get("source") != "code_health_audit" or not meta.get("merged_pr"):
            return {"success": False, "error": "A merged Code Health repair is required"}
        if row["status"] == "deployed" and meta.get("repair_verification"):
            return {"success": True, "already_verified": True}
        if row["status"] != "pr_open":
            return {"success": False, "error": "Repair is not awaiting completion verification"}
        submission = meta.get("repair_submission") or {}
        if meta.get("apply_mode") == "planned_codex_pr" and not meta.get("repair_artifacts"):
            return {"success": False, "error": "Planned repair manifest is unavailable"}
        if meta.get("repair_artifacts"):
            from services.planned_repair_verification import verify_artifacts

            try:
                evidence, modules = verify_artifacts(meta, RUNTIME_STARTED_AT)
            except (ValueError, OSError, SyntaxError, subprocess.SubprocessError) as exc:
                return {"success": False, "error": str(exc)}
        else:
            path, display, status = resolve_proposal_source(meta.get("file_path", ""))
            if status != "ok" or not submission.get("target_sha256"):
                return {"success": False, "error": "Deployed patch fingerprint is unavailable"}
            file = Path(path)
            source = file.read_text()
            if hashlib.sha256(source.encode()).hexdigest() != submission["target_sha256"]:
                return {"success": False, "error": "Deployed file does not match the submitted patch"}
            if RUNTIME_STARTED_AT <= file.stat().st_mtime:
                return {"success": False, "error": "Restart the service after deploying the patch, then run module QA"}
            verdict = finding_still_reproduces(
                proposal_message(meta.get("issue_code", ""), meta.get("detail", "")), source
            )
            if verdict is not False:
                return {"success": False, "error": "Original finding remains present or unverified"}
            modules = {module_from_file_path(display)}
            evidence = {"artifact_sha256": submission["target_sha256"]}
        if any(not MODULE_SUITE_MAP.get(module) for module in modules):
            return {"success": False, "error": "Module QA coverage is unavailable"}
        suites = sorted({suite for module in modules for suite in MODULE_SUITE_MAP[module]})
        # Match run_suite_for_module: inactive suites cannot run and must not
        # block completion. Still require nonempty active coverage and every
        # active mapped suite to have fresh, fully passing results.
        cur.execute(
            "SELECT id FROM qa_test_suites WHERE id=ANY(%s) AND is_active=true ORDER BY id FOR SHARE",
            (suites,),
        )
        suites = [suite["id"] for suite in cur.fetchall()]
        if any(not set(MODULE_SUITE_MAP[module]).intersection(suites) for module in modules):
            return {"success": False, "error": "Active module QA coverage is unavailable"}
        cur.execute(
            """SELECT DISTINCT ON (suite_id) id,suite_id,status,total_tests AS total,passed,failed,errors
               FROM qa_test_runs WHERE suite_id=ANY(%s) AND started_at>=to_timestamp(%s)
               ORDER BY suite_id,started_at DESC,id DESC""",
            (suites, RUNTIME_STARTED_AT),
        )
        runs = cur.fetchall()
        if len(runs) != len(set(suites)) or any(
            r["status"] != "completed" or not r["total"] or r["passed"] != r["total"] or r["failed"] or r["errors"]
            for r in runs
        ):
            return {"success": False, "error": "Run all module QA suites successfully after deployment"}
        if meta.get("repair_artifacts"):
            try:
                final_evidence, final_modules = verify_artifacts(meta, RUNTIME_STARTED_AT)
                if final_evidence != evidence or final_modules != modules:
                    return {"success": False, "error": "Deployment changed during verification"}
            except (ValueError, OSError, SyntaxError, subprocess.SubprocessError) as exc:
                return {"success": False, "error": str(exc)}
        receipt = {
            "verified_at": now_utc().isoformat(),
            "runtime_started_at": RUNTIME_STARTED_AT,
            **evidence,
            "qa_run_ids": [r["id"] for r in runs],
        }
        submission = dict(submission, stage="verified_complete")
        cur.execute(
            """UPDATE improvement_proposals SET status='deployed',deployed_at=NOW(),
               metadata=COALESCE(metadata,'{}'::jsonb) || %s::jsonb WHERE id=%s AND status='pr_open'""",
            (
                json.dumps({"code_applied": True, "repair_verification": receipt, "repair_submission": submission}),
                proposal_id,
            ),
        )
        cur.execute(
            "UPDATE improvement_deployments SET status='deployed',completed_at=NOW() WHERE proposal_id=%s AND status='deploying'",
            (proposal_id,),
        )
    return {"success": True, "verified": True, "verification": receipt}
