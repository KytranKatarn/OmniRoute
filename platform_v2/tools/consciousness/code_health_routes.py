"""
Code Health Routes — Consciousness Module
==========================================
API endpoints for codebase metrics, audit progress, and snapshots.
"""

import logging
import threading
import time

from flask import current_app, jsonify, request
from flask_login import login_required

from database import get_db_cursor
from services.token_provenance import ESTIMATED_SQL, cloud_classifier_sql

logger = logging.getLogger(__name__)


def _module_from_proposal_fp(fp):
    """Attribute a proposal file_path to the Code Health module that owns it.

    The scanner files tools/* findings under BOTH spellings: the placeholder
    alias (``[APP_CORE]/tools/faith/...``) and the on-disk path
    (``platform_v2/tools/faith/...``). A naive first-segment split mis-attributes
    the aliased spelling to ``[APP_CORE]``, so Faith looked like it had 1 issue
    and 2 repairs while Repair Bay counted 3 — the Repairs tab and the
    Consciousness code-health page disagreed.

    Resolution order (mirrors audit_pipeline's placeholder map):
    - ``platform_v2/tools/<mod>/...`` -> ``<mod>``
    - ``[APP_CORE]/tools/<mod>/...`` -> ``<mod>`` (bracket alias -> real module)
    - non-tools platform_v2 / ai_bridge / migrations -> the bracket token
    - standalone_*/website_* and everything else -> first path segment
    """
    if not fp:
        return None
    if "platform_v2/tools/" in fp or "[APP_CORE]/tools/" in fp:
        marker = "platform_v2/tools/" if "platform_v2/tools/" in fp else "[APP_CORE]/tools/"
        return fp.split(marker)[1].split("/")[0]
    if fp.startswith("platform_v2/") or fp.startswith("[APP_CORE]/"):
        return "[APP_CORE]"
    if fp.startswith("ai_bridge/") or fp.startswith("[AI_BRIDGE]/"):
        return "[AI_BRIDGE]"
    if fp.startswith("database/migrations/") or fp.startswith("[MIGRATIONS]/"):
        return "[MIGRATIONS]"
    return fp.split("/")[0]


def _ch_async_job(job_type, description, total_steps, work_fn):
    """Run a heavy Code-Health op in a background thread, tracked in bridge_jobs.

    Returns (job_id, None) on start, or (None, msg) if a same-type job is already
    running (dispatch_service.create_job dedups via an advisory lock + running-row
    check, so two scans can never collide). The worker gets its own app context so
    DB access works off the request thread; it must not block the web worker.
    """
    from services.dispatch_service import get_dispatch_service

    svc = get_dispatch_service()
    job_id = svc.create_job(
        job_type=job_type,
        module_source="code_health",
        description=description,
        total_steps=max(1, int(total_steps or 1)),
    )
    if not job_id:
        # Dedup hit — return the live job's id so the caller can still poll it.
        existing_id = None
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT id FROM bridge_jobs
                       WHERE job_type = %s AND module_source = 'code_health' AND status = 'running'
                       ORDER BY created_at DESC LIMIT 1""",
                    (job_type,),
                )
                r = cur.fetchone()
                existing_id = r["id"] if r else None
        except Exception:
            existing_id = None
        return existing_id, "a %s job is already running" % job_type
    app_obj = current_app._get_current_object()

    def _runner():
        with app_obj.app_context():
            try:
                work_fn(job_id, svc)
                svc.complete_job(job_id, "completed")
            except Exception:
                logger.exception("code_health async job %s (%s) failed", job_id, job_type)
                svc.complete_job(job_id, "failed")

    threading.Thread(target=_runner, daemon=True, name="ch-%s-%s" % (job_type, job_id)).start()
    return job_id, None


# In-memory TTL cache for the token-usage endpoint. The underlying data changes
# slowly (daily ingest cron + a slow live dispatch trickle), so a short TTL makes
# repeat tab loads instant without going stale in any way that matters. Keyed by
# the `days` window. Per-gunicorn-worker (not shared) — that's fine for an admin view.
_TOKEN_USAGE_CACHE = {}
_TOKEN_USAGE_TTL = 600  # seconds

# Same short TTL for the token-buckets endpoint (accounting-integrity view: every
# token → agent-local / cloud-CLI / infrastructure keep-alive / 0-token marker).
_TOKEN_BUCKETS_CACHE = {}
_TOKEN_BUCKETS_TTL = 600  # seconds


# ── Engine-facing helpers ─────────────────────────────────────────────────────
# Shared by the @login_required+@admin_required session routes below AND the
# @_require_internal_key /api/internal/code-health/* aliases the A.R.C.H.I.E.
# build engine calls (#4262 — the loop-closer). Extracting the logic to module
# level keeps ONE implementation so the cockpit/UI and the engine never drift.


def _audit_one(key, mod_data):
    """Audit one module: static analysis -> log_audit -> auto-submit to Repair Bay
    (deduped). Returns a result dict. Shared by the sync single-module path and
    the async audit-all job so both behave identically."""
    from services.code_metrics_service import audit_single_module, log_audit

    issues_found, notes, status, issues_list, profile = audit_single_module(key, module_data=mod_data)
    log_audit(
        module_name=key,
        category=profile.upper(),
        files_reviewed=mod_data.get("files", 0),
        lines_before=mod_data.get("lines", 0),
        lines_after=mod_data.get("lines", 0),
        issues_found=issues_found,
        notes=notes,
        status=status,
        audit_profile=profile,
        trigger_reason="manual",
        dispatched_via="local_static_analysis",
    )
    proposals_created = 0
    proposals_skipped = 0
    if issues_list:
        try:
            from services.audit_pipeline import process_audit_findings

            repair_result = process_audit_findings(key, issues_list)
            proposals_created = repair_result.get("proposals_created", 0)
            proposals_skipped = repair_result.get("skipped_duplicates", 0)
        except Exception as repair_err:
            logger.warning("Auto-submit to Repair Bay failed for %s: %s", key, repair_err)
    from services.code_issue_reconciler import reconcile_open_proposals
    from services.code_health_repairs import open_proposal_counts, reconcile_duplicate_proposals

    reconciliation = None
    pending_repairs = None
    duplicates = None
    try:
        duplicates = reconcile_duplicate_proposals(key, dry_run=False)
        reconciliation = reconcile_open_proposals(
            dry_run=False, statuses=("approved", "ready_for_review", "fix_requested"), module_name=key
        )
        pending_repairs = open_proposal_counts().get(key, 0)
    except Exception:
        logger.warning("Repair reconciliation failed for %s", key, exc_info=True)
    return {
        "module": key,
        "profile": profile,
        # #5926: report the TOTAL, matching what every UI surface counts
        # (badge / audit-log table / details drilldown all derive from
        # `_parse_audit_findings(notes)`). `issues_found` is the RED-severity
        # SUBSET -- returning it here is why a re-audit said "12" while the tab
        # said "30" for the same module (true total: 33 = 12 red + 19 yellow +
        # 2 info). Both numbers are now reported, neither is inferred.
        "issues": len(issues_list),
        "issues_red": issues_found,
        "issues_actionable": sum(issue.get("severity") in ("red", "yellow") for issue in issues_list),
        "issues_informational": sum(issue.get("severity") not in ("red", "yellow") for issue in issues_list),
        "status": status,
        "proposals_created": proposals_created,
        "proposals_skipped": proposals_skipped,
        "pending_repairs": pending_repairs,
        "repair_reconciliation": reconciliation,
        "duplicate_reconciliation": duplicates,
    }


# Severity classification shared by the audit-details drilldown AND the
# severity-summary badge coloring — ONE set, used by both, so they cannot
# silently diverge (severity_summary used to carry its own narrower 4-red/
# 3-yellow copy of this same list; see #5881).
_FINDING_RED_CODES = {
    "SQL_INJECTION_RISK",
    "HARDCODED_SECRET",
    "DIRECT_OLLAMA",
    "DIRECT_CLOUD",
    "INSECURE_DEFAULT",
}
_FINDING_YELLOW_CODES = {
    "BARE_EXCEPT",
    "LARGE_FILE",
    "MISSING_INIT",
    "INLINE_SCRIPT",
    "CONSOLE_LOG",
    "LATEST_TAG",
    "MISSING_RESOURCE_LIMIT",
}


def _parse_audit_findings(notes):
    """Parse a code_audit_log.notes string into structured findings.

    THE single source of truth for "how many findings does this audit hold" —
    used by both the audit-details drilldown and the severity-summary count, so
    the number an operator is asked to act on and the list they'd act from can
    never drift again (#5881, defect 3: the headline count was NOT derived from
    the findings list — e.g. [AI_BRIDGE]'s persisted issues_found=6 while notes
    held 30 parseable findings, because issues_found only counts 'red'-severity
    issues while every finding, of any severity, belongs in the count shown).
    """
    findings = []
    notes = notes or ""
    if not notes or notes in ("clean — all checks passed", "clean"):
        return findings
    for part in notes.split("; "):
        part = part.strip()
        if not part:
            continue
        code = part.split(":")[0].strip() if ":" in part else part
        detail = part.split(":", 1)[1].strip() if ":" in part else ""
        if code in _FINDING_RED_CODES:
            severity = "red"
        elif code in _FINDING_YELLOW_CODES:
            severity = "yellow"
        else:
            severity = "info"
        findings.append({"code": code, "detail": detail, "severity": severity})
    return findings


def start_code_health_scan():
    """Kick the async full-codebase scan job. Returns (payload, http_status)."""

    def work(job_id, svc):
        from services.code_metrics_service import save_snapshot, scan_codebase

        metrics = scan_codebase(force=True)
        save_snapshot(metrics)
        svc.update_job_progress(job_id, completed_delta=1)

    job_id, err = _ch_async_job("code_health_scan", "Full codebase scan", 1, work)
    if err:
        return {"success": False, "already_running": True, "job_id": job_id, "error": err}, 409
    return {"success": True, "job_id": job_id, "status": "running"}, 200


def run_code_health_audit(module_key=None):
    """Audit ONE module (sync — powers the per-module modal) or ALL modules
    (async job). Returns (payload, http_status). Shared by the session route and
    the internal engine alias. The audit-all worker scans the tree ONCE then
    audits every module, and closes the self-healing loop with a reverify pass."""
    from services.code_metrics_service import scan_codebase

    if module_key:
        metrics = scan_codebase()
        all_modules = metrics.get("modules", {})
        if module_key not in all_modules:
            return {"success": False, "error": f"Module not found: {module_key}"}, 404
        try:
            result = _audit_one(module_key, all_modules.get(module_key, {}))
        except Exception as e:
            result = {"module": module_key, "profile": "unknown", "issues": -1, "status": f"error: {str(e)[:100]}"}
        return {"success": True, "audited": 1, "results": [result], "trigger": "manual"}, 200

    total_hint = 0
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT per_module FROM code_metrics_snapshots ORDER BY scanned_at DESC LIMIT 1")
            row = cur.fetchone()
            if row and row.get("per_module"):
                import json as _json

                pm = _json.loads(row["per_module"]) if isinstance(row["per_module"], str) else row["per_module"]
                total_hint = len(pm)
    except Exception:
        total_hint = 0

    def work(job_id, svc):
        metrics = scan_codebase()
        all_modules = metrics.get("modules", {})
        for key, mod_data in all_modules.items():
            try:
                _audit_one(key, mod_data)
                svc.update_job_progress(job_id, completed_delta=1)
            except Exception:
                logger.warning("audit-all: module %s failed", key, exc_info=True)
                svc.update_job_progress(job_id, failed_delta=1)
        try:
            from services.audit_pipeline import reverify_deployed_findings

            reverify_deployed_findings()
        except Exception:
            logger.warning("audit-all: reverify pass failed", exc_info=True)

    job_id, err = _ch_async_job("code_health_audit", "Audit all modules", total_hint or 40, work)
    if err:
        return {"success": False, "already_running": True, "job_id": job_id, "error": err}, 409
    return {"success": True, "job_id": job_id, "status": "running", "total": total_hint}, 200


def code_health_job_status_payload(job_id):
    """bridge_jobs poll payload for the async scan/audit/backfill jobs.
    Returns (payload, http_status)."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT job_type, status, completed_steps, failed_steps, total_steps
               FROM bridge_jobs WHERE id = %s""",
            (job_id,),
        )
        r = cur.fetchone()
    if not r:
        return {"success": False, "error": "job not found"}, 404
    return {
        "success": True,
        "job_id": job_id,
        "job_type": r.get("job_type"),
        "status": r.get("status"),
        "completed": r.get("completed_steps") or 0,
        "failed": r.get("failed_steps") or 0,
        "total": r.get("total_steps") or 0,
    }, 200


# ── Static-analysis Deep Scan (scanner tier, Slice 1 — spec 2026-07-11) ──────
# Seams are module-level + lazily imported so the worker is unit-testable
# without DB/dispatch and the heavy services only load when a scan runs.


def _static_run(target):
    from services.code_static_analyzer import run as _static_analyzer_run

    return _static_analyzer_run(target)


def _gate_findings(findings):
    from services.finding_gate import gate as _gate

    return _gate(findings)


def _submit_confirmed(module_name, issues):
    from services.audit_pipeline import process_audit_findings

    return process_audit_findings(module_name, issues)


def _deep_scan_worker(target="platform", progress_cb=None):
    """Deep static-analysis scan: faithful-runtime toolchain -> auto-verify gate
    -> Repair Bay proposals (grouped per module, deduped by the pipeline).
    Advisory findings are logged + counted, never proposed. Returns the summary
    dict consumed by code_health_autoheal."""

    def _tick():
        if progress_cb:
            try:
                progress_cb()
            except Exception:
                pass

    scan = _static_run(target)
    _tick()
    gated = _gate_findings(scan["findings"])
    _tick()

    confirmed = []
    advisory = list(gated["advisory"])
    for finding in gated["confirmed"]:
        if finding.get("module"):
            confirmed.append(finding)
        else:  # unknown runtime root — never mint a broken pipeline file_path
            advisory.append({**finding, "advisory": True, "gate_reason": "unmapped_path"})

    by_module = {}
    for finding in confirmed:
        issue = {
            "code": finding["code"],
            "severity": finding.get("severity", "yellow"),
            "file": finding.get("rel_file") or finding.get("file", ""),
            "detail": finding.get("message") or finding.get("detail", ""),
            "meta_extra": {
                "scan_tier": "static",
                "tool": finding.get("tool"),
                "verified_by": finding.get("verified_by"),
                "line": finding.get("line"),
                "runtime_file": finding.get("file"),
            },
        }
        by_module.setdefault(finding["module"], []).append(issue)

    proposals_created = 0
    skipped_duplicates = 0
    for module_name, issues in by_module.items():
        try:
            res = _submit_confirmed(module_name, issues) or {}
            proposals_created += res.get("proposals_created", 0)
            skipped_duplicates += res.get("skipped_duplicates", 0)
        except Exception:
            logger.warning("deep-scan: Repair Bay submit failed for %s", module_name, exc_info=True)
    _tick()

    summary = {
        "target": target,
        "confirmed": len(confirmed),
        "advisory": len(advisory),
        "proposals_created": proposals_created,
        "skipped_duplicates": skipped_duplicates,
        "coverage": scan.get("coverage", {}),
        # (module, rel_file, code) triples of every confirmed finding — the
        # static reverify in code_health_autoheal compares deployed proposals
        # against these to stamp fixed/still_open.
        "fingerprints": [[f["module"], f.get("rel_file") or f.get("file", ""), f["code"]] for f in confirmed],
    }
    logger.info("deep-scan summary: %s", summary)
    if advisory:
        logger.info(
            "deep-scan advisories (surfaced, not proposed): %s",
            [(a.get("tool"), a.get("code"), a.get("file"), a.get("line")) for a in advisory][:50],
        )
    return summary


def compute_orchestration():
    """Department-ownership + lifecycle aggregation of Code-Health findings.

    Resolution chain mirrors live dispatch: issue_code -> _ISSUE_CAPABILITY_MAP ->
    capability -> CAPABILITY_DEPARTMENT_MAP -> department -> director. Returns the
    JSON-able payload {"success", "departments"[]} so both the session route and
    the internal engine alias share one implementation."""
    from services.audit_pipeline import _ISSUE_CAPABILITY_MAP

    try:
        from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP
    except Exception:
        CAPABILITY_DEPARTMENT_MAP = {}
    # Code-Health audit capabilities aren't all in CAPABILITY_DEPARTMENT_MAP
    # (e.g. 'vulnerability_scan'); this override keeps ownership faithful so
    # security findings route to V.I.G.I.L., not the Engineering default.
    _CH_CAP_DEPT = {
        "vulnerability_scan": "Security & Compliance",
        "security": "Security & Compliance",
        "compliance": "Security & Compliance",
        "code_review": "Engineering & Technology",
        "code": "Engineering & Technology",
        "debug": "Engineering & Technology",
        "module_audit": "Documentation & Knowledge",
        "documentation": "Documentation & Knowledge",
    }
    director = {
        "Security & Compliance": "V.I.G.I.L.",
        "Engineering & Technology": "F.O.R.G.E.",
        "Documentation & Knowledge": "C.O.D.E.X.",
        "Analytics & Intelligence": "S.P.E.C.T.R.A.",
        "Research & Development": "D.A.R.W.I.N.",
    }
    # SQL aggregation over the FULL proposal set (previously ORDER BY id DESC
    # LIMIT 2000, a window that was ~95% archived rows — it hid ~92% of open
    # findings and rendered total==2000, the LIMIT). Archived/rejected rows are
    # excluded BEFORE any aggregation; 'total' is a real COUNT(*) of the
    # remaining rows. Grouping by (issue_code, lifecycle bucket) keeps the
    # result set tiny so the issue_code -> capability -> department mapping can
    # stay in Python.
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT COALESCE(metadata->>'issue_code', '?') AS code,
                      CASE
                          WHEN LOWER(COALESCE(metadata->>'reverified', '')) = 'fixed' THEN 'fixed'
                          WHEN LOWER(COALESCE(metadata->>'reverified', '')) = 'still_open' THEN 'still_open'
                          WHEN LOWER(COALESCE(status, '')) IN ('deployed', 'implemented') THEN 'deployed'
                          WHEN LOWER(COALESCE(status, '')) = 'failed' THEN 'other'
                          ELSE 'open'
                      END AS bucket,
                      COUNT(*) AS cnt
               FROM improvement_proposals
               WHERE metadata->>'source' = 'code_health_audit'
                 AND LOWER(COALESCE(status, '')) NOT IN ('rejected', 'archived', 'superseded')
               GROUP BY 1, 2"""
        )
        rows = cur.fetchall()

    agg = {}
    for r in rows:
        code = r["code"]
        cap = _ISSUE_CAPABILITY_MAP.get(code, "code_review")
        dept = _CH_CAP_DEPT.get(cap) or CAPABILITY_DEPARTMENT_MAP.get(cap, "Engineering & Technology")
        a = agg.setdefault(
            dept,
            {
                "department": dept,
                "director": director.get(dept),
                "capabilities": set(),
                "open": 0,
                "deployed": 0,
                "fixed": 0,
                "still_open": 0,
                "total": 0,
            },
        )
        a["capabilities"].add(cap)
        cnt = int(r["cnt"] or 0)
        a["total"] += cnt
        bucket = r["bucket"]
        if bucket in ("open", "deployed", "fixed", "still_open"):
            a[bucket] += cnt
        # 'other' (failed, un-reverified) counts toward total only — mirrors the
        # old per-row logic, which never bucketed failed rows as open.

    out = []
    for a in agg.values():
        a["capabilities"] = sorted(a["capabilities"])
        out.append(a)
    out.sort(key=lambda x: -x["total"])
    return {"success": True, "departments": out}


def register_code_health_routes(bp, admin_required):
    @bp.route("/api/code-health/scan", methods=["POST"])
    @login_required
    @admin_required
    def code_health_scan():
        """Full codebase scan — async (was a multi-second blocking filesystem walk).
        Returns a job_id immediately; poll /api/code-health/job-status/<id>."""
        payload, code = start_code_health_scan()
        return jsonify(payload), code

    @bp.route("/api/code-health/deep-scan", methods=["POST"])
    @login_required
    @admin_required
    def code_health_deep_scan():
        """Static-analysis deep scan (AST sweeps + linters in the faithful
        runtime) -> auto-verify gate -> Repair Bay proposals. Async; poll
        /api/code-health/job-status/<id>."""
        target = (request.get_json(silent=True) or {}).get("target", "platform")

        def work(job_id, svc):
            _deep_scan_worker(target, progress_cb=lambda: svc.update_job_progress(job_id, completed_delta=1))

        job_id, err = _ch_async_job("code_health_deep_scan", f"Deep static-analysis scan: {target}", 3, work)
        if err:
            return jsonify({"success": False, "already_running": True, "job_id": job_id, "error": err}), 409
        return jsonify({"success": True, "job_id": job_id, "status": "running"}), 202

    @bp.route("/api/code-health/job-status/<int:job_id>")
    @login_required
    @admin_required
    def code_health_job_status(job_id):
        """Poll target for the async scan/audit/backfill jobs (reads bridge_jobs)."""
        payload, code = code_health_job_status_payload(job_id)
        return jsonify(payload), code

    @bp.route("/api/code-health/current")
    @login_required
    @admin_required
    def code_health_current():
        from flask import request as req

        # Use latest DB snapshot by default (instant), live scan only if ?live=1
        if req.args.get("live") == "1":
            from services.code_metrics_service import scan_codebase

            metrics = scan_codebase()
            return jsonify(metrics)

        # Try loading from latest snapshot first (instant — no filesystem walk)
        row = None
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT total_files, total_lines, total_folders,
                          python_files, python_lines, js_files, js_lines,
                          css_files, css_lines, html_files, html_lines,
                          sql_files, sql_lines, per_module, modules_changed, scanned_at
                   FROM code_metrics_snapshots
                   ORDER BY scanned_at DESC LIMIT 1"""
            )
            row = cur.fetchone()

        if row and row.get("per_module"):
            import json as _json

            per_module = _json.loads(row["per_module"]) if isinstance(row["per_module"], str) else row["per_module"]

            modules_changed = row.get("modules_changed") or []
            if isinstance(modules_changed, str):
                try:
                    modules_changed = _json.loads(modules_changed)
                except Exception:
                    modules_changed = []

            # Reconstruct per-language totals from per_module by_type data
            lang_totals = {}
            for mod_data in per_module.values():
                for lang, counts in (mod_data.get("by_type") or {}).items():
                    if lang not in lang_totals:
                        lang_totals[lang] = {"files": 0, "lines": 0}
                    lang_totals[lang]["files"] += counts.get("files", 0)
                    lang_totals[lang]["lines"] += counts.get("lines", 0)

            metrics = {
                "total_files": row["total_files"],
                "total_lines": row["total_lines"],
                "total_folders": row.get("total_folders", 0),
                "modules": per_module,
                "python": lang_totals.get(
                    "python", {"files": row.get("python_files", 0), "lines": row.get("python_lines", 0)}
                ),
                "js": lang_totals.get("js", {"files": row.get("js_files", 0), "lines": row.get("js_lines", 0)}),
                "css": lang_totals.get("css", {"files": row.get("css_files", 0), "lines": row.get("css_lines", 0)}),
                "html": lang_totals.get("html", {"files": row.get("html_files", 0), "lines": row.get("html_lines", 0)}),
                "sql": lang_totals.get("sql", {"files": row.get("sql_files", 0), "lines": row.get("sql_lines", 0)}),
                "shell": lang_totals.get("shell", {"files": 0, "lines": 0}),
                "json": lang_totals.get("json", {"files": 0, "lines": 0}),
                "yaml": lang_totals.get("yaml", {"files": 0, "lines": 0}),
                "markdown": lang_totals.get("markdown", {"files": 0, "lines": 0}),
                "go": lang_totals.get("go", {"files": 0, "lines": 0}),
                "svg": lang_totals.get("svg", {"files": 0, "lines": 0}),
                "config": lang_totals.get("config", {"files": 0, "lines": 0}),
                "text": lang_totals.get("text", {"files": 0, "lines": 0}),
                "orphans": {},
                "modules_changed": modules_changed,
                "snapshot_age": row["scanned_at"].isoformat() if row["scanned_at"] else None,
            }

            # Add structural audits (lightweight, no filesystem walk)
            try:
                from services.code_metrics_service import (
                    _audit_kbs_plugins,
                    _audit_standalone_products,
                    _calculate_health_score,
                    _detect_retired_modules,
                    _find_orphan_files,
                )

                orphans = _find_orphan_files(set(per_module.keys()))
                metrics["orphans"] = orphans
                metrics["kbs_audit"] = _audit_kbs_plugins()
                metrics["standalone_audit"] = _audit_standalone_products()
                metrics["retired_modules"] = _detect_retired_modules()
                metrics["health_score"] = _calculate_health_score(metrics)
            except Exception:
                pass

            return jsonify(metrics)

        # Fallback: live scan if no snapshot exists
        from services.code_metrics_service import scan_codebase

        metrics = scan_codebase()
        return jsonify(metrics)

    @bp.route("/api/code-health/snapshots")
    @login_required
    @admin_required
    def code_health_snapshots():
        from services.code_metrics_service import get_snapshots

        snapshots = get_snapshots(limit=365)
        return jsonify({"snapshots": snapshots})

    @bp.route("/api/code-health/token-buckets")
    @login_required
    @admin_required
    def code_health_token_buckets():
        """Accounting-integrity view for the Token Economy tab: WHERE every token goes.

        Buckets every task_execution_log row in the window into exactly one of:
          agent   — real local inference attributed to a budgeted AI agent
          cloud   — provider left the cluster (services.token_provenance; NOT worker_type)
          infra   — warm-up keep-alive (fleet_warmup/kin_warmth) — no agent
          markers — 0-token orchestration/bookkeeping rows
          other   — real-local rows still lacking an agent_id (should trend to 0)
        Plus local-vs-cloud totals. Sourced from task_execution_log; short TTL cache.
        """
        # Range -> interval + time-bucket expression (5min/hour/day) + Toronto-local axis
        # label -- mirrors the token-usage endpoint so the buckets-over-time chart lines up
        # with the Local-vs-External one. bucket/label are a fixed whitelist (never user
        # input) so they are safe to embed; the window is a bound ::interval param.
        _b5 = "to_timestamp(floor(extract(epoch from created_at)/300)*300)"
        _bh = "to_timestamp(floor(extract(epoch from created_at)/3600)*3600)"
        _bd = "(created_at AT TIME ZONE 'America/Toronto')::date"
        _RANGE = {
            "1h": {
                "interval": "1 hour",
                "bucket": _b5,
                "label": f"to_char({_b5} AT TIME ZONE 'America/Toronto', 'HH24:MI')",
            },
            "24h": {
                "interval": "24 hours",
                "bucket": _bh,
                "label": f"to_char({_bh} AT TIME ZONE 'America/Toronto', 'HH24:MI')",
            },
            "7": {"interval": "7 days", "bucket": _bd, "label": "NULL"},
            "30": {"interval": "30 days", "bucket": _bd, "label": "NULL"},
            "90": {"interval": "90 days", "bucket": _bd, "label": "NULL"},
            "365": {"interval": "365 days", "bucket": _bd, "label": "NULL"},
        }
        rng = (request.args.get("range") or "").lower()
        if rng not in _RANGE:
            try:
                _d = int(request.args.get("days", 30))
            except (TypeError, ValueError):
                _d = 30
            rng = str(_d) if str(_d) in _RANGE else "30"
        spec = _RANGE[rng]

        if request.args.get("refresh") != "1":
            _hit = _TOKEN_BUCKETS_CACHE.get(rng)
            if _hit and (time.time() - _hit[0]) < _TOKEN_BUCKETS_TTL:
                payload = dict(_hit[1])
                payload["_cached"] = True
                return jsonify(payload)

        # Fixed CASE order = the accounting buckets. Order mirrors the exclusion the
        # accounting uses: estimated backfill first (a separate PROVENANCE axis — the
        # totals panel excludes it from the live cloud/local split, so this panel must
        # too or the ALL range diverges: measured 10,102,978 tokens apart before the
        # two shared ESTIMATED_SQL), then cloud (by PROVIDER, see token_provenance),
        # then warm-up infra, then 0-token markers, then a real attributed agent row,
        # else a stray real-local row (target: 0). No user input in the SQL.
        #
        # ONE cloud classifier, shared with the totals/series endpoint below. This
        # panel used to key "cloud" on worker_type='contract' while the Cloud Impact
        # totals keyed on provider — and the two DISAGREED on the same rows:
        # ollama_cloud/internal (665 runs, 637,900 tokens that left the cluster)
        # landed in the AGENT bucket here and in EXTERNAL there.
        # Owner requirement 2026-09-09: ALL cloud tokens count as cloud on this tab.
        #
        # Both flags are computed ONCE per row in a CTE. It did NOT make the query
        # cheap — measured on prod, EXPLAIN ANALYZE, best of 2, read-only session:
        #   series query, range=90:  old worker_type rule 5.4s · this CTE 19.6s
        #   plain wall-clock:        range=90 3.2s → 13.5s · range=365 (ALL) 2.2s → 14.4s
        #   bucket-totals CTE query, range=90: 3.8s — and a cache miss runs BOTH.
        # The cost is intrinsic to a provider-based classifier (lower()/position()/
        # left()/right() + a JSONB extract per row) vs a single text equality.
        # _TOKEN_BUCKETS_CACHE is a module dict, i.e. PER gunicorn worker (4), so a
        # miss can happen up to 4x per 10 min, each tying one of 32 threads ~15-20s.
        # Bounded by --timeout 600 (no worker kill). The real fix is precomputed
        # provenance flags on the row (#6658); until then this is the honest price
        # of "all cloud tokens count as cloud".
        row_cte = (
            "WITH r AS ("
            " SELECT tokens_used, agent_id, module_source, created_at,"
            f" ({cloud_classifier_sql()})='external' AS is_cloud,"
            f" {ESTIMATED_SQL} AS is_est"
            " FROM task_execution_log"
            " WHERE created_at > now() - %s::interval)"
        )
        bucket_case = (
            "CASE WHEN is_est THEN 'estimated' "
            "WHEN is_cloud THEN 'cloud' "
            "WHEN module_source IN ('fleet_warmup','kin_warmth') THEN 'infra' "
            "WHEN COALESCE(tokens_used,0)=0 THEN 'markers' "
            "WHEN agent_id IS NOT NULL THEN 'agent' "
            "ELSE 'other' END"
        )
        # Per-bucket token sum for the over-time series (markers omitted -- always 0
        # tokens). Every live bucket excludes is_est so that cloud here == the totals
        # panel's external_tokens for the same window, by construction.
        _live = "NOT is_est"
        _nowarm = "COALESCE(module_source,'') NOT IN ('fleet_warmup','kin_warmth')"
        series_sql = (
            "COALESCE(SUM(CASE WHEN is_est THEN tokens_used END),0) estimated,"
            f"COALESCE(SUM(CASE WHEN {_live} AND is_cloud THEN tokens_used END),0) cloud,"
            f"COALESCE(SUM(CASE WHEN {_live} AND NOT is_cloud"
            " AND module_source IN ('fleet_warmup','kin_warmth') THEN tokens_used END),0) infra,"
            f"COALESCE(SUM(CASE WHEN {_live} AND NOT is_cloud AND {_nowarm}"
            " AND agent_id IS NOT NULL THEN tokens_used END),0) agent,"
            f"COALESCE(SUM(CASE WHEN {_live} AND NOT is_cloud AND {_nowarm}"
            " AND agent_id IS NULL AND COALESCE(tokens_used,0)>0 THEN tokens_used END),0) other"
        )
        rows_by_key = {}
        series = []
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""{row_cte}
                    SELECT {bucket_case} AS bucket,
                        COUNT(*) AS rows,
                        COALESCE(SUM(tokens_used),0) AS tok
                    FROM r
                    GROUP BY 1""",
                (spec["interval"],),
            )
            for r in cur.fetchall():
                rows_by_key[r["bucket"]] = (int(r["rows"] or 0), int(r["tok"] or 0))

            cur.execute(
                f"""{row_cte}
                    SELECT {spec['bucket']} d, {spec['label']} lbl, {series_sql}
                    FROM r
                    GROUP BY d, lbl ORDER BY d""",
                (spec["interval"],),
            )
            for r in cur.fetchall():
                _d = r.get("d")
                series.append(
                    {
                        "day": _d.isoformat() if _d is not None and hasattr(_d, "isoformat") else _d,
                        "label": r.get("lbl"),
                        "agent": int(r.get("agent") or 0),
                        "cloud": int(r.get("cloud") or 0),
                        "infra": int(r.get("infra") or 0),
                        "other": int(r.get("other") or 0),
                        "estimated": int(r.get("estimated") or 0),
                    }
                )

        _META = [
            ("agent", "Agent · local inference", "attributed to a budgeted AI agent"),
            ("cloud", "Cloud / CLI", "provider left the cluster (token_provenance) — CLI + hosted models"),
            ("infra", "Infrastructure · keep-alive", "warm-up — charged to no agent"),
            ("markers", "Orchestration markers", "0-token bookkeeping rows"),
            ("other", "Unattributed (stray)", "real-local rows lacking an agent — trends to 0"),
            (
                "estimated",
                "Estimated · historical backfill",
                "token_source=estimated — excluded from the live cloud/local split",
            ),
        ]
        buckets = []
        for key, label, desc in _META:
            rows, tok = rows_by_key.get(key, (0, 0))
            buckets.append({"key": key, "label": label, "desc": desc, "rows": rows, "tokens": tok})
        total = sum(b["tokens"] for b in buckets)
        cloud = rows_by_key.get("cloud", (0, 0))[1]
        estimated = rows_by_key.get("estimated", (0, 0))[1]
        # local/pct_local describe the LIVE split only — estimated backfill is its own
        # axis (it holds 10.1M anthropic/contract rows over 365d that are neither
        # "local" nor a measured cloud call). Same definition as the token-usage
        # endpoint's totals, so the two payloads agree on every one of these keys.
        live_local = total - cloud - estimated
        payload = {
            "range": rng,
            "total_tokens": total,
            "cloud_tokens": cloud,
            "local_tokens": live_local,
            "estimated_tokens": estimated,
            "pct_local": round(100.0 * live_local / (live_local + cloud), 1) if (live_local + cloud) else 100.0,
            "buckets": buckets,
            "series": series,
        }
        _TOKEN_BUCKETS_CACHE[rng] = (time.time(), payload)
        return jsonify(dict(payload))

    @bp.route("/api/code-health/token-usage")
    @login_required
    @admin_required
    def code_health_token_usage():
        """Token economy for the Code Health tab.

        Sourced from task_execution_log (real Ollama eval_count tokens). Returns:
          - totals: local vs external token + dispatch split (+ pct_local)
          - agents: per-agent LLM usage (models, dispatches, tokens, local split)
          - series: tokens-over-time per day (local, external, estimated)

        Local = our own compute (services.token_provenance.LOCAL_PROVIDERS + LOCAL_PREFIXES; NULL = local by policy).
        External = cloud (provider names a cloud proxy, or model is a :cloud variant).
        Estimated-backfill rows (request_metadata.token_source='estimated') are reported
        as a SEPARATE series — never mixed into the 'real' local/external numbers.
        """
        # Range windows. Sub-day ranges (1h/24h) bucket finer than a day so recent
        # dispatch activity is visible (matches the 1H/24H buttons on other charts):
        #   1h → 5-minute buckets · 24h → hourly · 7/30/90/365 → daily.
        # `bucket`/`gran` come from this fixed whitelist (never user input) so they are
        # safe to embed in SQL; the time window is passed as a bound ::interval param.
        # Epoch-floor buckets are timezone-type-agnostic: extract(epoch …) yields the
        # correct absolute instant whether created_at is naive-UTC or timestamptz, so
        # `… AT TIME ZONE 'America/Toronto'` then renders the right local wall time.
        # (date_trunc on a NAIVE column would mis-convert by the UTC offset — bug avoided.)
        _b5 = "to_timestamp(floor(extract(epoch from created_at)/300)*300)"  # 5-min boundary
        _bh = "to_timestamp(floor(extract(epoch from created_at)/3600)*3600)"  # hour boundary
        _bd = "(created_at AT TIME ZONE 'America/Toronto')::date"
        # `label` is a server-rendered Toronto-local axis label so the frontend never
        # has to parse a UTC timestamp (which would drift by the browser's tz). day
        # ranges keep label NULL → frontend falls back to the ISO date in `day`.
        _RANGE = {
            "1h": {
                "interval": "1 hour",
                "bucket": _b5,
                "label": f"to_char({_b5} AT TIME ZONE 'America/Toronto', 'HH24:MI')",
                "gran": "5min",
            },
            "24h": {
                "interval": "24 hours",
                "bucket": _bh,
                "label": f"to_char({_bh} AT TIME ZONE 'America/Toronto', 'HH24:MI')",
                "gran": "hour",
            },
            "7": {"interval": "7 days", "bucket": _bd, "label": "NULL", "gran": "day"},
            "30": {"interval": "30 days", "bucket": _bd, "label": "NULL", "gran": "day"},
            "90": {"interval": "90 days", "bucket": _bd, "label": "NULL", "gran": "day"},
            "365": {"interval": "365 days", "bucket": _bd, "label": "NULL", "gran": "day"},
        }
        rng = (request.args.get("range") or "").lower()
        if rng not in _RANGE:
            # Back-compat: derive the range token from the legacy ?days= param.
            try:
                _d = int(request.args.get("days", 30))
            except (TypeError, ValueError):
                _d = 30
            rng = str(_d) if str(_d) in _RANGE else "30"
        spec = _RANGE[rng]

        # Serve from TTL cache when fresh (skips ~2-3s of aggregation over 259k+ rows).
        # ?refresh=1 forces a recompute. Keyed by the range token.
        if request.args.get("refresh") != "1":
            _hit = _TOKEN_USAGE_CACHE.get(rng)
            if _hit and (time.time() - _hit[0]) < _TOKEN_USAGE_TTL:
                payload = dict(_hit[1])
                payload["_cached"] = True
                payload["_cache_age_s"] = int(time.time() - _hit[0])
                return jsonify(payload)

        # Cloud/external detector — the SAME classifier the Token Buckets panel uses,
        # so the two panels can never disagree again. It is an allowlist of LOCAL
        # providers with everything else counted as cloud: a provider added later
        # (omniroute, ...) is cloud by default rather than "local until someone edits
        # a tuple". No LIKE/% inside, so it is safe with or without psycopg2 params.
        cls = cloud_classifier_sql()
        est = ESTIMATED_SQL
        # `cls` is %-free by construction (token_provenance). The per-agent query below
        # still uses NOT ILIKE '%%embed%%', so every query in this block keeps passing
        # (spec["interval"],) so psycopg2 unescapes it.
        where = "created_at > now() - %s::interval AND tokens_used IS NOT NULL"

        out = {
            "range": rng,
            "granularity": spec["gran"],
            "days": rng if rng in ("1h", "24h") else int(rng),
            "totals": {},
            "agents": [],
            "series": [],
        }
        with get_db_cursor() as (conn, cur):
            cur.execute(
                f"""SELECT
                        COALESCE(SUM(CASE WHEN {cls}='local'    AND NOT {est} THEN tokens_used END),0) local_tokens,
                        COALESCE(SUM(CASE WHEN {cls}='external' AND NOT {est} THEN tokens_used END),0) external_tokens,
                        COALESCE(SUM(CASE WHEN {est} THEN tokens_used END),0) estimated_tokens,
                        COUNT(*) FILTER (WHERE {cls}='local'    AND NOT {est}) local_disp,
                        COUNT(*) FILTER (WHERE {cls}='external' AND NOT {est}) external_disp
                    FROM task_execution_log
                    WHERE {where}""",
                (spec["interval"],),
            )
            t = cur.fetchone() or {}
            lt = int(t.get("local_tokens") or 0)
            xt = int(t.get("external_tokens") or 0)
            out["totals"] = {
                "local_tokens": lt,
                "external_tokens": xt,
                "estimated_tokens": int(t.get("estimated_tokens") or 0),
                "local_disp": int(t.get("local_disp") or 0),
                "external_disp": int(t.get("external_disp") or 0),
                "pct_local": round(100.0 * lt / (lt + xt), 1) if (lt + xt) else 100.0,
            }

            # Per-agent, with a per-MODEL token breakdown (jsonb array, biggest first)
            # so the UI can show the token count next to each model.
            cur.execute(
                f"""SELECT agent_name,
                        jsonb_agg(jsonb_build_object('model', model_used, 'tokens', mt, 'cloud', ext_t > 0)
                                  ORDER BY mt DESC) models,
                        SUM(md) disp,
                        SUM(mt) tokens,
                        SUM(local_t) local_tokens,
                        SUM(ext_t) external_tokens
                    FROM (
                        SELECT agent_name, COALESCE(model_used, '?') model_used,
                            COALESCE(SUM(tokens_used),0) mt,
                            COUNT(*) md,
                            COALESCE(SUM(CASE WHEN {cls}='local'    THEN tokens_used END),0) local_t,
                            COALESCE(SUM(CASE WHEN {cls}='external' THEN tokens_used END),0) ext_t
                        FROM task_execution_log
                        WHERE {where} AND NOT {est} AND agent_name IS NOT NULL
                          -- #4344: per-model token breakdown = real LLM rows only. Drop
                          -- orchestration markers (direct-INSERT job rows omit worker_type)
                          -- + non-LLM compute (browser/scraper, embeddings) so the per-agent
                          -- model list reflects actual token-generating inference.
                          AND worker_type IS NOT NULL
                          AND model_used NOT IN ('internal','batch','bridge-managed','browser')
                          AND model_used NOT ILIKE '%%embed%%'
                        GROUP BY agent_name, COALESCE(model_used, '?')
                    ) sub
                    GROUP BY agent_name
                    ORDER BY tokens DESC LIMIT 25""",
                (spec["interval"],),
            )
            for r in cur.fetchall():
                tok = int(r.get("tokens") or 0)
                loc = int(r.get("local_tokens") or 0)
                out["agents"].append(
                    {
                        "agent": r.get("agent_name"),
                        "models": [
                            {
                                "model": m.get("model"),
                                "tokens": int(m.get("tokens") or 0),
                                "cloud": bool(m.get("cloud")),
                            }
                            for m in (r.get("models") or [])
                        ],
                        "dispatches": int(r.get("disp") or 0),
                        "tokens": tok,
                        "local_tokens": loc,
                        "external_tokens": int(r.get("external_tokens") or 0),
                        "local_pct": round(100.0 * loc / tok) if tok else 100,
                    }
                )

            cur.execute(
                f"""SELECT {spec['bucket']} d, {spec['label']} lbl,
                        COALESCE(SUM(CASE WHEN {cls}='local'    AND NOT {est} THEN tokens_used END),0) local,
                        COALESCE(SUM(CASE WHEN {cls}='external' AND NOT {est} THEN tokens_used END),0) external,
                        COALESCE(SUM(CASE WHEN {est} THEN tokens_used END),0) estimated
                    FROM task_execution_log
                    WHERE {where}
                    GROUP BY d, lbl ORDER BY d""",
                (spec["interval"],),
            )
            for r in cur.fetchall():
                _d = r.get("d")
                out["series"].append(
                    {
                        "day": _d.isoformat() if _d is not None and hasattr(_d, "isoformat") else _d,
                        "label": r.get("lbl"),
                        "local": int(r.get("local") or 0),
                        "external": int(r.get("external") or 0),
                        "estimated": int(r.get("estimated") or 0),
                    }
                )

            # Cloud impact — the "how cloud helped build this" story. Pre-measurement
            # build-out (Jan–Apr 2026) is estimated (token_source='estimated_historical',
            # see scripts/estimate_historical_claude_tokens.py); agent-growth is real.
            cur.execute(
                """SELECT
                       COALESCE(SUM(tokens_used),0) est_tokens,
                       COALESCE(SUM((request_metadata->>'lines_inserted')::bigint),0) lines_built
                   FROM task_execution_log
                   WHERE COALESCE(request_metadata->>'token_source','') = 'estimated_historical'"""
            )
            imp = cur.fetchone() or {}
            cur.execute(
                """SELECT to_char(date_trunc('month', created_at), 'YYYY-MM') m, COUNT(*) n
                   FROM agents WHERE created_at IS NOT NULL
                   GROUP BY 1 ORDER BY 1"""
            )
            agents_by_month, running = [], 0
            for r in cur.fetchall():
                running += int(r.get("n") or 0)
                agents_by_month.append({"month": r.get("m"), "created": int(r.get("n") or 0), "cumulative": running})
            out["impact"] = {
                "origin": "2025-12-17",
                "measured_since": "2026-05-03",
                "est_historical_tokens": int(imp.get("est_tokens") or 0),
                "lines_built_est_period": int(imp.get("lines_built") or 0),
                "agents_by_month": agents_by_month,
                # Honest capacity/authorship timeline (owner-reported): the early build
                # was AI-ASSISTED (owner + DeepSeek + a capacity-limited Claude), not pure
                # Claude — and Claude capacity was capped before the Max 20x era.
                "capacity_phases": [
                    {
                        "period": "Dec 2025",
                        "detail": "1× Claude Pro (paid) + DeepSeek (web) + hand-written — capacity-capped",
                    },
                    {
                        "period": "Jan–Feb 2026",
                        "detail": "2× Claude accounts in parallel + DeepSeek (web) — token limits hit",
                    },
                    {"period": "Mar–Apr 2026", "detail": "scaling up"},
                    {"period": "May 2026 →", "detail": "Max 20× — measured (real tokens)"},
                ],
                "note": "Jan–Apr is an ESTIMATE of AI-assisted build effort (owner hand-written + DeepSeek web + a capacity-limited Claude) from lines×tok/line + commits×tok/commit — not pure-Claude tokens, and none of it ran on local fleet. Agent growth is real. Measured tokens begin 2026-05-03.",
            }
        _TOKEN_USAGE_CACHE[rng] = (time.time(), out)
        return jsonify(out)

    @bp.route("/api/code-health/audit-log")
    @login_required
    @admin_required
    def code_health_audit_log():
        # The JS consumer (consciousness.js) only builds latest-per-module maps
        # from this payload, but the old implementation returned EVERY
        # code_audit_log row (~7,800) per tab load. Return just the latest
        # entry per module (DISTINCT ON), newest first — same response shape.
        #
        # Pinned to dispatched_via='local_static_analysis' (#5881) — before this,
        # DISTINCT ON picked whichever engine wrote LAST (this scan or the
        # separately-labelled F.O.R.G.E. scheduled jobs), so the same tab painted
        # red or green depending purely on run order, not on the code. F.O.R.G.E.
        # keeps running and writing; it surfaces via /api/code-health/second-opinion.
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT DISTINCT ON (module_name)
                          id, module_name, category, files_reviewed,
                          lines_before, lines_after, issues_found, issues_fixed,
                          notes, status, audited_at
                   FROM code_audit_log
                   WHERE dispatched_via = 'local_static_analysis'
                   ORDER BY module_name, audited_at DESC"""
            )
            rows = cur.fetchall()
        entries = []
        for row in rows:
            r = dict(row)
            if hasattr(r.get("audited_at"), "isoformat"):
                r["audited_at"] = r["audited_at"].isoformat()
            # Defect 3 (#5881): the "Issues" number this feeds (consciousness.js
            # _renderModuleTable / _renderAuditTable) must be DERIVED FROM the
            # findings list, never from the separately-tracked issues_found
            # column — that column counts only 'red'-severity findings and used
            # to disagree with the findings list by 2x-6x in EITHER direction
            # (measured: [AI_BRIDGE] persisted issues_found=6 while notes held
            # 30 parseable findings). Raw persisted value kept as issues_found_raw
            # for anyone auditing the audit; issues_found is what the UI shows.
            r["issues_found_raw"] = r.get("issues_found")
            r["issues_found"] = len(_parse_audit_findings(r.get("notes")))
            entries.append(r)
        entries.sort(key=lambda r: r.get("audited_at") or "", reverse=True)
        return jsonify({"entries": entries})

    @bp.route("/api/code-health/module-status")
    @login_required
    @admin_required
    def code_health_module_status():
        modules = []
        summary = {"green": 0, "purple": 0, "yellow": 0, "orange": 0, "red": 0, "total": 0}

        # Map folder names to proper display names
        from module_registry import MODULES

        display_names = {m.id: m.name for m in MODULES}
        display_names.update(
            {
                "[AI_BRIDGE]": "AI Bridge",
                "[APP_CORE]": "App Core",
                "[MIGRATIONS]": "Migrations",
                "[SHARED]": "Shared Assets",
            }
        )

        # Add standalone product display names
        from services.code_metrics_service import STANDALONE_PRODUCTS, WEBSITE_PRODUCTS

        for product in STANDALONE_PRODUCTS:
            display_names[product["module_key"]] = product["name"]

        # Add website product display names
        for site in WEBSITE_PRODUCTS:
            display_names[site["module_key"]] = site["name"]

        with get_db_cursor() as (conn, cur):
            # Get module list from latest code_metrics_snapshot per_module JSONB
            cur.execute(
                """SELECT per_module FROM code_metrics_snapshots
                   ORDER BY scanned_at DESC LIMIT 1"""
            )
            row = cur.fetchone()
            per_module = row["per_module"] if row and row.get("per_module") else {}
            module_names = list(per_module.keys())

            # Get latest audit per module — pinned to local_static_analysis (#5881),
            # same reasoning as code_health_audit_log above.
            cur.execute(
                """SELECT DISTINCT ON (module_name)
                      module_name, audited_at, status, stale
                   FROM code_audit_log
                   WHERE dispatched_via = 'local_static_analysis'
                   ORDER BY module_name, audited_at DESC"""
            )
            audits = {
                r["module_name"]: {"audited_at": r["audited_at"], "status": r["status"], "stale": r["stale"]}
                for r in cur.fetchall()
            }

            # Get latest scan date
            cur.execute("SELECT scanned_at FROM code_metrics_snapshots ORDER BY scanned_at DESC LIMIT 1")
            scan_row = cur.fetchone()
            last_scan_date = scan_row["scanned_at"].isoformat() if scan_row else None

            # Get pending proposal counts per module (active proposals in pipeline)
            from services.code_health_repairs import open_proposal_counts

            proposal_counts = open_proposal_counts()

            for name in sorted(module_names):
                audit = audits.get(name)
                has_proposals = proposal_counts.get(name, 0) > 0
                if not audit:
                    status = "red"  # never audited
                elif has_proposals:
                    status = "purple"  # a clean audit does not close another scanner's findings
                elif audit["status"] == "violations_found":
                    status = "orange"  # audited but issues not submitted yet
                elif audit["status"] == "findings_open":
                    # #5942 — findings present, none red. Shares the yellow bucket with
                    # stale (both are "attention, not urgent"); it must be handled
                    # EXPLICITLY because this chain ends `else: green`, so an unhandled
                    # status would silently keep rendering these 26 modules as clean.
                    status = "yellow"
                elif audit.get("stale"):
                    status = "yellow"  # audit expired (>30 days)
                else:
                    status = "green"  # clean

                summary[status] += 1
                summary["total"] += 1

                modules.append(
                    {
                        "module_name": name,
                        "display_name": display_names.get(name, name.replace("_", " ").title()),
                        "status": status,
                        "last_audit_date": audit["audited_at"].isoformat() if audit else None,
                        "last_audit_status": audit["status"] if audit else None,
                        "stale": audit.get("stale", False) if audit else False,
                        "files_changed_since_audit": 0,
                        "last_scan_date": last_scan_date,
                        "pending_proposals": proposal_counts.get(name, 0),
                    }
                )

        return jsonify({"success": True, "modules": modules, "summary": summary})

    @bp.route("/api/code-health/severity-summary")
    @login_required
    @admin_required
    def code_health_severity_summary():
        """Return per-module severity breakdown for badge coloring.

        For each module, parses the latest local_static_analysis code_audit_log
        notes into findings (shared _parse_audit_findings, #5881) to determine
        the highest severity — red (security), yellow (quality), green (clean).
        total_issues = len(findings): the headline count is DERIVED FROM the
        findings list, never from the separately-tracked issues_found column
        (which counts only 'red'-severity issues and used to disagree with the
        findings list by 2x-6x in either direction — defect 3, #5881).
        """
        modules = {}
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT DISTINCT ON (module_name)
                      module_name, notes, audited_at
                   FROM code_audit_log
                   WHERE dispatched_via = 'local_static_analysis'
                   ORDER BY module_name, audited_at DESC"""
            )
            for row in cur.fetchall():
                name = row["module_name"]
                findings = _parse_audit_findings(row["notes"])

                red_count = sum(1 for f in findings if f["severity"] == "red")
                yellow_count = sum(1 for f in findings if f["severity"] == "yellow")
                info_count = sum(1 for f in findings if f["severity"] == "info")

                if red_count > 0:
                    highest = "red"
                elif yellow_count > 0:
                    highest = "yellow"
                else:
                    highest = "green"

                modules[name] = {
                    "highest_severity": highest,
                    "red": red_count,
                    "yellow": yellow_count,
                    "info": info_count,
                    "total_issues": len(findings),
                    "last_audit": row["audited_at"].isoformat() if row["audited_at"] else None,
                }

        return jsonify({"success": True, "modules": modules})

    @bp.route("/api/code-health/second-opinion")
    @login_required
    @admin_required
    def code_health_second_opinion():
        """F.O.R.G.E.'s scheduled audit pass, surfaced SEPARATELY (#5881).

        Owner decision 2026-08-21: "keep F.O.R.G.E., but separate + labelled" —
        it keeps running (Job #40 change-triggered + Job #58 weekly) and keeps
        writing dispatched_via='F.O.R.G.E.' rows. This endpoint is the ONLY place
        those rows are surfaced; the headline count/colour is owned entirely by
        local_static_analysis (code_health_severity_summary /
        code_health_module_status). Same shape as the other views, mirrored onto
        the F.O.R.G.E. label instead — an "AI second opinion", never authoritative.
        """
        modules = {}
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT DISTINCT ON (module_name)
                      module_name, issues_found, notes, status, audited_at, trigger_reason
                   FROM code_audit_log
                   WHERE dispatched_via = 'F.O.R.G.E.'
                   ORDER BY module_name, audited_at DESC"""
            )
            for row in cur.fetchall():
                findings = _parse_audit_findings(row["notes"])
                modules[row["module_name"]] = {
                    "status": row["status"],
                    # TWO counts, deliberately, and the NAMES have to say which is which
                    # (#5914). `total_issues` is DERIVED from the parsed findings and is the
                    # authoritative number — same meaning as in code_health_severity_summary,
                    # so the two endpoints agree. `forge_claimed_issues` is the raw
                    # code_audit_log column, i.e. what F.O.R.G.E. SAID it found.
                    #
                    # Keeping both is the point of a second-opinion view: when they DISAGREE,
                    # F.O.R.G.E.'s own count does not match its own notes, and that is a
                    # finding about F.O.R.G.E. worth seeing. But shipping them as
                    # `issues_found` + `total_issues` — as this endpoint did until 2026-08-22
                    # — is exactly the two-counts-of-one-thing drift #5881 removed everywhere
                    # else: a consumer reading the raw field silently gets the underived
                    # number. Never emit a raw count next to a derived one without saying so.
                    "total_issues": len(findings),
                    "forge_claimed_issues": row["issues_found"],
                    "trigger_reason": row["trigger_reason"],
                    "last_audit": row["audited_at"].isoformat() if row["audited_at"] else None,
                }

        return jsonify({"success": True, "source": "F.O.R.G.E. (AI second opinion)", "modules": modules})

    @bp.route("/api/code-health/backfill-git", methods=["POST"])
    @login_required
    @admin_required
    def code_health_backfill_git():
        """Backfill git history — async (the git walk is slow). Poll job-status."""

        def work(job_id, svc):
            from services.code_metrics_service import backfill_git_history

            backfill_git_history()
            svc.update_job_progress(job_id, completed_delta=1)

        job_id, err = _ch_async_job("code_health_backfill", "Backfill git history", 1, work)
        if err:
            return jsonify({"success": False, "already_running": True, "job_id": job_id, "error": err}), 409
        return jsonify({"success": True, "job_id": job_id, "status": "running"})

    @bp.route("/api/code-health/governance-log")
    @login_required
    @admin_required
    def code_health_governance_log():
        """Return F.O.R.G.E. self-healing actions from governance audit log."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT event_type, action, outcome, details, timestamp
                   FROM governance_audit_log
                   WHERE event_category = 'self_healing'
                   ORDER BY timestamp DESC LIMIT 50"""
            )
            entries = []
            for r in cur.fetchall():
                e = dict(r)
                if hasattr(e.get("timestamp"), "isoformat"):
                    e["timestamp"] = e["timestamp"].isoformat()
                entries.append(e)
        return jsonify({"success": True, "entries": entries})

    @bp.route("/api/code-health/standalone-status")
    @login_required
    @admin_required
    def code_health_standalone_status():
        """Return standalone product metrics with compliance tier info.
        Uses latest snapshot for stats (fast), DB for compliance scores."""
        from services.code_metrics_service import STANDALONE_PRODUCTS
        import json as _json

        # Get stats from latest snapshot (no filesystem walk)
        standalone_stats = {}
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT per_module FROM code_metrics_snapshots
                   ORDER BY scanned_at DESC LIMIT 1"""
            )
            row = cur.fetchone()
            if row and row.get("per_module"):
                pm = _json.loads(row["per_module"]) if isinstance(row["per_module"], str) else row["per_module"]
                for k, v in pm.items():
                    if k.startswith("standalone_"):
                        standalone_stats[k] = v

        # Get all compliance scores in one query
        compliance_map = {}
        try:
            product_names = [p["name"] for p in STANDALONE_PRODUCTS]
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT DISTINCT ON (scan_target) scan_target, overall_score, scanned_at
                       FROM compliance_scans
                       WHERE scan_target = ANY(%s)
                       ORDER BY scan_target, scanned_at DESC""",
                    (product_names,),
                )
                for r in cur.fetchall():
                    compliance_map[r["scan_target"]] = {
                        "score": float(r["overall_score"]) if r.get("overall_score") else None,
                        "scanned_at": r["scanned_at"].isoformat() if r.get("scanned_at") else None,
                    }
        except Exception:
            pass

        results = []
        for product in STANDALONE_PRODUCTS:
            key = product["module_key"]
            stats = standalone_stats.get(key, {})
            comp = compliance_map.get(product["name"], {})

            results.append(
                {
                    "name": product["name"],
                    "module_key": key,
                    "tier": product["tier"],
                    "path": product["path"],
                    "files": stats.get("files", 0),
                    "lines": stats.get("lines", 0),
                    "by_type": stats.get("by_type", {}),
                    "compliance_score": comp.get("score"),
                    "last_compliance_scan": comp.get("scanned_at"),
                    "compliance_packs": product.get("compliance_packs", []),
                }
            )

        return jsonify({"success": True, "standalones": results})

    @bp.route("/api/code-health/website-status")
    @login_required
    @admin_required
    def code_health_website_status():
        """Return website product metrics."""
        from services.code_metrics_service import WEBSITE_PRODUCTS, _get_website_stats

        website_stats = _get_website_stats()
        results = []
        for site in WEBSITE_PRODUCTS:
            key = site["module_key"]
            stats = website_stats.get(key, {})
            results.append(
                {
                    "name": site["name"],
                    "module_key": key,
                    "path": site["path"],
                    "files": stats.get("files", 0),
                    "lines": stats.get("lines", 0),
                    "folders": stats.get("folders", 0),
                    "by_type": stats.get("by_type", {}),
                }
            )

        return jsonify({"success": True, "websites": results})

    # _audit_one lifted to module scope (shared with the internal engine alias).

    @bp.route("/api/code-health/audit", methods=["POST"])
    @login_required
    @admin_required
    def code_health_audit():
        """Audit ONE module (sync — powers the per-module modal) or ALL modules
        (async job). Findings auto-submit to Repair Bay (deduped)."""
        from flask import request as req

        data = req.get_json(silent=True) or {}
        payload, code = run_code_health_audit(data.get("module"))
        return jsonify(payload), code

    @bp.route("/api/code-health/reverify", methods=["POST"])
    @login_required
    @admin_required
    def code_health_reverify():
        """Re-verify deployed Code-Health fixes — closes the self-healing loop by
        re-auditing and confirming each finding is actually gone. Optional {"module"}
        scopes to one module. Async; poll /job-status/<id> — the job encodes the
        result as completed=fixed, failed=still_open (regressions)."""
        from flask import request as req

        module_key = (req.get_json(silent=True) or {}).get("module")

        def work(job_id, svc):
            from services.audit_pipeline import reverify_deployed_findings

            res = reverify_deployed_findings(module_key)
            svc.update_job_progress(
                job_id,
                completed_delta=int(res.get("fixed", 0)),
                failed_delta=int(res.get("still_open", 0)),
            )

        job_id, err = _ch_async_job("code_health_reverify", "Re-verify deployed fixes", 1, work)
        if err:
            return jsonify({"success": False, "already_running": True, "job_id": job_id, "error": err}), 409
        return jsonify({"success": True, "job_id": job_id, "status": "running"})

    @bp.route("/api/code-health/orchestration")
    @login_required
    @admin_required
    def code_health_orchestration():
        """Which department LLM owns each Code-Health finding + the loop status.
        Delegates to the module-level compute_orchestration() (shared with the
        internal engine alias)."""
        return jsonify(compute_orchestration())

    @bp.route("/api/code-health/audit/<int:audit_id>/details")
    @login_required
    @admin_required
    def code_health_audit_details(audit_id):
        """Get full audit details including findings for a specific audit entry."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, module_name, category, files_reviewed, lines_before,
                          lines_after, issues_found, issues_fixed, notes, status,
                          audited_at, audit_profile, trigger_reason, dispatched_via
                   FROM code_audit_log WHERE id = %s""",
                (audit_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Audit entry not found"}), 404

            # Parse notes into structured findings — shared parser (#5881), so this
            # drilldown and the severity-summary count can never diverge again.
            notes = row["notes"] or ""
            findings = _parse_audit_findings(notes)

            # Check if proposals already exist for this module (use metadata for accuracy)
            proposal_status = {"total": 0, "by_status": {}, "items": []}
            try:
                module_name = row["module_name"]
                if (
                    module_name.startswith("standalone_")
                    or module_name.startswith("website_")
                    or module_name.startswith("[")
                ):
                    module_path_pattern = f"{module_name}/%"
                else:
                    module_path_pattern = f"platform_v2/tools/{module_name}/%"
                cur.execute(
                    """SELECT id, title, status, priority
                       FROM improvement_proposals
                       WHERE metadata->>'source' = 'code_health_audit'
                         AND metadata->>'file_path' LIKE %s
                         AND status NOT IN ('archived', 'rejected', 'deployed')
                       ORDER BY id DESC
                       LIMIT 20""",
                    (module_path_pattern,),
                )
                for pr in cur.fetchall():
                    s = pr["status"]
                    proposal_status["by_status"][s] = proposal_status["by_status"].get(s, 0) + 1
                    proposal_status["total"] += 1
                    proposal_status["items"].append(
                        {
                            "id": pr["id"],
                            "title": pr["title"],
                            "status": pr["status"],
                            "priority": pr["priority"],
                        }
                    )
            except Exception:
                pass

            result = {
                "success": True,
                "audit": {
                    "id": row["id"],
                    "module_name": row["module_name"],
                    "category": row["category"],
                    "files_reviewed": row["files_reviewed"],
                    "lines_before": row["lines_before"],
                    # Defect 3 (#5881): derive the displayed count FROM findings,
                    # same as code_health_audit_log. Raw persisted value kept as
                    # issues_found_raw for anyone auditing the audit.
                    "issues_found": len(findings),
                    "issues_found_raw": row["issues_found"],
                    "issues_fixed": row["issues_fixed"],
                    "status": row["status"],
                    "audited_at": row["audited_at"].isoformat() if row["audited_at"] else None,
                    "audit_profile": row.get("audit_profile", "python"),
                    "trigger_reason": row.get("trigger_reason", "unknown"),
                    "dispatched_via": row.get("dispatched_via"),
                },
                "findings": findings,
                "notes_raw": notes,
                "proposals": proposal_status,
            }
            return jsonify(result)

    @bp.route("/api/code-health/audit/<int:audit_id>/submit-repair", methods=["POST"])
    @login_required
    @admin_required
    def code_health_submit_repair(audit_id):
        """Submit audit findings to Repair Bay as improvement proposals."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT module_name, notes, issues_found, status FROM code_audit_log WHERE id = %s",
                (audit_id,),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Audit entry not found"}), 404
            if row["status"] == "completed" and row["issues_found"] == 0:
                return jsonify(
                    {
                        "success": False,
                        "error": "No issues to submit — module is clean",
                    }
                )

        # Parse notes into issues_list format for process_audit_findings
        issues_list = []
        notes = row["notes"] or ""
        for part in notes.split("; "):
            part = part.strip()
            if not part:
                continue
            code = part.split(":")[0].strip() if ":" in part else part
            detail = part.split(":", 1)[1].strip() if ":" in part else ""
            red_codes = {
                "SQL_INJECTION_RISK",
                "HARDCODED_SECRET",
                "DIRECT_OLLAMA",
                "DIRECT_CLOUD",
                "INSECURE_DEFAULT",
            }
            yellow_codes = {
                "BARE_EXCEPT",
                "LARGE_FILE",
                "MISSING_INIT",
                "INLINE_SCRIPT",
                "CONSOLE_LOG",
                "LATEST_TAG",
                "MISSING_RESOURCE_LIMIT",
            }
            if code in red_codes:
                severity = "red"
            elif code in yellow_codes:
                severity = "yellow"
            else:
                severity = "info"
            issues_list.append(
                {
                    "code": code,
                    "severity": severity,
                    "file": row["module_name"],
                    "detail": detail,
                }
            )

        try:
            from services.audit_pipeline import process_audit_findings

            result = process_audit_findings(row["module_name"], issues_list)
            return jsonify(
                {
                    "success": True,
                    "proposals_created": result.get("proposals_created", 0),
                    "skipped_duplicates": result.get("skipped_duplicates", 0),
                    "module": row["module_name"],
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/code-health/submit-attention", methods=["POST"])
    @login_required
    @admin_required
    def code_health_submit_attention():
        """Submit a Needs Attention item to Repair Bay for investigation."""
        data = request.get_json() or {}
        item_type = data.get("type", "")
        label = data.get("label", "")

        if not item_type:
            return jsonify({"success": False, "error": "type is required"}), 400

        try:
            from services.audit_pipeline import process_audit_findings

            issues_list = []

            if item_type == "orphan_files":
                # Submit orphan files for investigation
                from services.code_metrics_service import _find_orphan_files

                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """SELECT per_module FROM code_metrics_snapshots
                           ORDER BY scanned_at DESC LIMIT 1"""
                    )
                    row = cur.fetchone()
                if row and row.get("per_module"):
                    import json as _json

                    per_module = (
                        _json.loads(row["per_module"]) if isinstance(row["per_module"], str) else row["per_module"]
                    )
                    orphans = _find_orphan_files(set(per_module.keys()))
                    for category, files in orphans.items():
                        for f in files:
                            fname = f if isinstance(f, str) else f.get("file", str(f))
                            issues_list.append(
                                {
                                    "code": "ORPHAN_FILE",
                                    "severity": "yellow",
                                    "file": fname,
                                    "detail": f"Unmapped {category} file — not claimed by any module",
                                }
                            )
                module_name = "APP_CORE"

            elif item_type == "modules_with_issues":
                # Submit modules that have audit issues
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """SELECT DISTINCT module_name, notes, issues_found
                           FROM code_audit_log
                           WHERE status = 'completed' AND issues_found > 0
                           AND id IN (
                               SELECT MAX(id) FROM code_audit_log
                               GROUP BY module_name
                           )"""
                    )
                    rows = cur.fetchall()
                for row in rows:
                    notes = row["notes"] or ""
                    for part in notes.split("; "):
                        part = part.strip()
                        if not part:
                            continue
                        code = part.split(":")[0].strip() if ":" in part else part
                        detail = part.split(":", 1)[1].strip() if ":" in part else ""
                        issues_list.append(
                            {
                                "code": code,
                                "severity": "yellow",
                                "file": row["module_name"],
                                "detail": detail,
                            }
                        )
                module_name = "PLATFORM"

            elif item_type == "standalone_issues":
                from services.code_metrics_service import _audit_standalone_products

                sa = _audit_standalone_products()
                for issue in sa.get("issues", []):
                    issues_list.append(
                        {
                            "code": "STANDALONE_TIER1",
                            "severity": "yellow",
                            "file": issue.split("]")[0].replace("[", "").strip() if "]" in issue else "standalone",
                            "detail": issue,
                        }
                    )
                module_name = "STANDALONE"

            else:
                return jsonify({"success": False, "error": f"Unknown type: {item_type}"}), 400

            if not issues_list:
                return jsonify({"success": True, "proposals_created": 0, "message": "No issues to submit"})

            result = process_audit_findings(module_name, issues_list)
            return jsonify(
                {
                    "success": True,
                    "proposals_created": result.get("proposals_created", 0),
                    "skipped_duplicates": result.get("skipped_duplicates", 0),
                    "type": item_type,
                    "label": label,
                }
            )
        except Exception as e:
            logger.exception("Failed to submit attention item to Repair Bay")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/code-health/structural-audit")
    @login_required
    @admin_required
    def code_health_structural_audit():
        """Full structural audit — KBS plugins, standalone tiers, retired modules, health score."""
        from services.code_metrics_service import (
            _audit_kbs_plugins,
            _audit_standalone_products,
            _calculate_health_score,
            _detect_retired_modules,
            _find_orphan_files,
        )

        # Gather orphan data (need module names from scan)
        from services.code_metrics_service import _get_module_stats

        module_stats = _get_module_stats()
        orphans = _find_orphan_files(set(module_stats.keys()))

        kbs_audit = _audit_kbs_plugins()
        standalone_audit = _audit_standalone_products()
        retired_modules = _detect_retired_modules()

        # Build partial report for health score calculation
        partial = {
            "orphans": orphans,
            "kbs_audit": kbs_audit,
            "standalone_audit": standalone_audit,
            "retired_modules": retired_modules,
        }
        health_score = _calculate_health_score(partial)

        return jsonify(
            {
                "success": True,
                "health_score": health_score,
                "orphans": {k: len(v) for k, v in orphans.items()},
                "kbs_audit": {
                    "total": kbs_audit["total"],
                    "healthy": kbs_audit["healthy"],
                    "issues": kbs_audit["issues"],
                },
                "standalone_audit": {
                    "total": standalone_audit["total"],
                    "healthy": standalone_audit["healthy"],
                    "issues": standalone_audit["issues"],
                    "products": [
                        {
                            "name": p["name"],
                            "type": p["type"],
                            "exists": p["exists"],
                            "tier1": p["tier1"],
                            "issues": p["issues"],
                        }
                        for p in standalone_audit["products"]
                    ],
                },
                "retired_modules": retired_modules,
            }
        )

    @bp.route("/api/code-health/repair-pipeline")
    @login_required
    @admin_required
    def code_health_repair_pipeline():
        """Aggregate Repair Bay data for Code Health integration."""
        try:
            with get_db_cursor() as (conn, cur):
                # Repair queue stats by status
                cur.execute(
                    """
                    SELECT status, COUNT(*) as count
                    FROM repair_queue
                    GROUP BY status
                """
                )
                queue_by_status = {r["status"]: r["count"] for r in cur.fetchall()}

                # Repair queue by severity (pending/triaged only)
                cur.execute(
                    """
                    SELECT severity, COUNT(*) as count
                    FROM repair_queue
                    WHERE status IN ('pending', 'triaged', 'in_progress')
                    GROUP BY severity
                """
                )
                queue_by_severity = {r["severity"]: r["count"] for r in cur.fetchall()}

                # Proposal stats by status
                cur.execute(
                    """
                    SELECT status, COUNT(*) as count
                    FROM improvement_proposals
                    GROUP BY status
                """
                )
                proposals_by_status = {r["status"]: r["count"] for r in cur.fetchall()}

                # This panel also includes incident repairs and non-audit
                # proposals. Expose the audit subset separately, including why
                # approved work is deliberately excluded from automatic fixing.
                from services.audit_pipeline import _AUTO_FIX_EXCLUDED_ISSUE_CODES
                from services.code_health_repairs import TERMINAL_STATUSES

                cur.execute(
                    """SELECT COUNT(*) AS active,
                              COUNT(*) FILTER (WHERE status = 'approved' AND
                                  metadata->>'issue_code' = ANY(%s)) AS manual_review,
                              COUNT(*) FILTER (WHERE status = 'ready_for_review') AS ready_for_review,
                              COUNT(*) FILTER (WHERE status IN ('pending', 'pending_approval')) AS pending_approval,
                              COUNT(*) FILTER (WHERE status IN ('approved', 'fix_requested') AND
                                  metadata->>'dispatch_attempted' IS NOT NULL) AS dispatch_attempted
                       FROM improvement_proposals
                       WHERE metadata->>'source' = 'code_health_audit'
                         AND status NOT IN %s""",
                    (list(_AUTO_FIX_EXCLUDED_ISSUE_CODES), TERMINAL_STATUSES),
                )
                code_health = dict(cur.fetchone())

                # Recent governance actions (self-healing)
                cur.execute(
                    """
                    SELECT event_category, action, details, timestamp,
                           agent_id, reason
                    FROM governance_audit_log
                    WHERE event_category = 'forge_self_heal'
                    ORDER BY timestamp DESC
                    LIMIT 10
                """
                )
                governance = [
                    {
                        "event": r["event_category"],
                        "action": r["action"],
                        "details": r["details"],
                        "reason": r["reason"],
                        "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
                    }
                    for r in cur.fetchall()
                ]

            return jsonify(
                {
                    "success": True,
                    "queue": {
                        "by_status": queue_by_status,
                        "by_severity": queue_by_severity,
                        "total": sum(queue_by_status.values()),
                    },
                    "proposals": {
                        "by_status": proposals_by_status,
                        "total": sum(proposals_by_status.values()),
                    },
                    "governance": governance,
                    "code_health": code_health,
                    "repair_bay_url": "/tools/repair-bay",
                }
            )
        except Exception as e:
            return jsonify({"success": False, "error": str(e), "queue": {}, "proposals": {}, "governance": []})
