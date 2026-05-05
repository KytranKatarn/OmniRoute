"""department_hq/jobs.py — Central job registration hub (Decision #440).

register_department_hq_jobs() is the SINGLE entry point called from AgentLoop.
It registers Department HQ's own jobs and delegates to other module registrars:
  - tools.consciousness.jobs.register_consciousness_jobs
  - tools.security_network.jobs.register_security_jobs
  - services.agent_jobs.register_agent_welfare_jobs
  - services.fleet_jobs.register_fleet_jobs

Own jobs (moved from dev_hq — Decision #433):
  - daily_code_metrics_scan (Job #40)
  - pattern_compliance_check (Job #41)
  - automated_module_audit (Job #58)
  - daily_code_health_digest (Job #51)
  - daily_code_health_scan (Job #55)
  - competitor_landscape_scan (Job #52)
"""

import json
import logging
import time

logger = logging.getLogger("agent_loop")

# ---------------------------------------------------------------------------
# Shared helper: _log_cycle  (mirrors AgentLoop._log_cycle)
# ---------------------------------------------------------------------------

# Department mapping for dev_hq jobs
_DEVHQ_DEPARTMENT = "Engineering & Technology"


def _log_cycle(
    job_name: str,
    items_processed: int,
    items_failed: int,
    duration_ms: int,
    details: dict = None,
    error_message: str = None,
):
    """Log an agent loop execution cycle to autonomy_loop_log."""
    status = "error" if items_failed > 0 and items_processed == 0 else "partial" if items_failed > 0 else "success"
    try:
        from db import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO autonomy_loop_log
            (job_name, status, items_processed, items_failed, duration_ms, details, error_message, department)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job_name,
                status,
                items_processed,
                items_failed,
                duration_ms,
                json.dumps(details or {}),
                error_message,
                _DEVHQ_DEPARTMENT,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log agent cycle: {e}")


# ---------------------------------------------------------------------------
# Job implementations (faithful copies from agent_loop.py)
# ---------------------------------------------------------------------------


def daily_code_metrics_scan():
    """Job #40: Daily codebase metrics snapshot at 3:00 AM with stale audit detection."""
    start = time.time()
    try:
        from services.code_metrics_service import scan_and_detect_changes

        metrics, snapshot_id, changed_modules = scan_and_detect_changes()
        duration_ms = int((time.time() - start) * 1000)
        logger.info(
            "Daily code metrics: %d files, %d lines (snapshot #%s, %d modules changed)",
            metrics["total_files"],
            metrics["total_lines"],
            snapshot_id,
            len(changed_modules),
        )
        _log_cycle("code_metrics_scan", 1, 0, duration_ms)

        # Auto-audit changed modules via F.O.R.G.E.
        if changed_modules:
            from services.code_metrics_service import audit_single_module, log_audit

            audited_count = 0
            for key in changed_modules:
                mod_data = metrics.get("modules", {}).get(key, {})
                try:
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
                        trigger_reason="change_detected",
                        dispatched_via="F.O.R.G.E.",
                    )
                    audited_count += 1
                except Exception as audit_err:
                    logger.warning("Change-triggered audit failed for %s: %s", key, audit_err)
            if audited_count:
                logger.info("Change-triggered audits: %d/%d modules audited", audited_count, len(changed_modules))
    except Exception as e:
        _log_cycle("code_metrics_scan", 0, 1, int((time.time() - start) * 1000), error_message=str(e))
        logger.warning(f"Failed: {e}")


def pattern_compliance_check():
    """Job #41: Scan for pattern violations at 4:00 AM."""
    try:
        import os
        import re
        from services.code_metrics_service import log_audit

        tools_dir = "/app/tools" if os.path.isdir("/app/tools") else "/mnt/archie_brain/platform_v2/tools"
        violations = []

        for root, dirs, files in os.walk(tools_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                filepath = os.path.join(root, fname)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    # Check for direct Ollama calls (ADR-013 violation)
                    if "call_ollama(" in content and "bridge" not in filepath and "archie_bridge" not in filepath:
                        violations.append(f"DIRECT_OLLAMA: {filepath}")

                    # Check for call_claude_api / call_openai_api in modules
                    if (
                        "call_claude_api(" in content or "call_openai_api(" in content
                    ) and "archie_bridge" not in filepath:
                        violations.append(f"DIRECT_CLOUD: {filepath}")

                except Exception:
                    pass

        if violations:
            log_audit(
                module_name="PATTERN_COMPLIANCE",
                category="automated_scan",
                issues_found=len(violations),
                notes="; ".join(violations[:20]),
                status="violations_found",
            )
            logger.warning("Pattern compliance: %d violations found", len(violations))
        _log_cycle("pattern_compliance", len(violations), 0, 0)
    except Exception as e:
        _log_cycle("pattern_compliance", 0, 1, 0, error_message=str(e))
        logger.warning(f"Failed: {e}")


def automated_module_audit(flask_app):
    """Job #58: Automated module audit — weekly Sunday 3:30 AM."""
    try:
        from database import get_db_cursor
        from services.code_metrics_service import audit_single_module, log_audit
        from services.audit_pipeline import process_audit_findings

        # Load latest per_module data from most recent snapshot
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT per_module FROM code_metrics_snapshots
                   ORDER BY scanned_at DESC LIMIT 1"""
            )
            row = cur.fetchone()
            if not row or not row.get("per_module"):
                logger.warning("Automated module audit: no snapshot found, skipping")
                return

            per_module = row["per_module"]

            # Also check for open high/critical proposals per module
            cur.execute(
                """SELECT title, COUNT(*) as cnt
                   FROM improvement_proposals
                   WHERE status NOT IN ('deployed', 'rejected', 'archived')
                     AND priority IN ('high', 'critical')
                   GROUP BY title"""
            )
            proposal_files = {r["title"]: r["cnt"] for r in cur.fetchall()}

        audited = 0
        clean = 0
        violations = 0
        severity_totals = {"red": 0, "yellow": 0, "info": 0}
        total_proposals = 0

        for module_name, stats in per_module.items():
            issues_found, notes, status, issues_list, profile = audit_single_module(module_name, module_data=stats)

            # Tally severity breakdown
            for issue in issues_list:
                sev = issue.get("severity", "info")
                severity_totals[sev] = severity_totals.get(sev, 0) + 1

            # Auto-generate Repair Bay proposals for red/yellow findings
            if issues_list:
                try:
                    result = process_audit_findings(module_name, issues_list)
                    total_proposals += result.get("proposals_created", 0)
                except Exception as pipe_err:
                    logger.warning("Audit pipeline failed for %s: %s", module_name, pipe_err)

            # Check proposals affecting this module
            proposal_issues = 0
            module_clean = module_name.replace("_", " ").replace("-", " ").lower()
            for ptitle, cnt in proposal_files.items():
                if module_clean in (ptitle or "").lower() or module_name in (ptitle or "").lower():
                    proposal_issues += cnt
            if proposal_issues > 0:
                issues_found += proposal_issues
                notes += f"; {proposal_issues} open high/critical proposals"
                if status == "completed":
                    status = "violations_found"

            log_audit(
                module_name=module_name,
                category=profile.upper(),
                files_reviewed=stats.get("files", 0),
                lines_before=stats.get("lines", 0),
                lines_after=stats.get("lines", 0),
                issues_found=issues_found,
                notes=notes,
                status=status,
                audit_profile=profile,
                trigger_reason="scheduled",
                dispatched_via="F.O.R.G.E.",
            )

            audited += 1
            if status == "completed":
                clean += 1
            else:
                violations += 1

        # --- Phase 1.5: Pre-dispatch model cleanup ---
        # Unload non-essential models to free VRAM/RAM for repair agents
        try:
            import urllib.request as _urllib

            essential_models = {"arctic-embed-cpu:latest", "qwen2.5-coder:7b", "qwen2.5:1.5b"}
            ps_resp = _urllib.urlopen("http://192.168.1.200:11434/api/ps", timeout=10)
            loaded = json.loads(ps_resp.read()).get("models", [])
            unloaded = 0
            for m in loaded:
                if m["name"] not in essential_models:
                    try:
                        # Model unload is admin-plane, not inference —
                        # going directly to Ollama's /api/generate with
                        # keep_alive=0 is the documented way. The prior
                        # `dispatch(..., model=..., keep_alive=0)` path
                        # silently dropped those kwargs (not in canonical
                        # signature) so unloads never happened in prod.
                        payload = json.dumps({"model": m["name"], "prompt": "", "keep_alive": 0}).encode()
                        req = _urllib.Request(
                            "http://192.168.1.200:11434/api/generate",
                            data=payload,
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        _urllib.urlopen(req, timeout=30)
                        unloaded += 1
                    except Exception:
                        pass
            if unloaded:
                logger.info("Repair pipeline: unloaded %d non-essential models before dispatch", unloaded)
        except Exception as cleanup_err:
            logger.debug("Pre-dispatch cleanup skipped: %s", cleanup_err)

        # --- Phase 2: Dispatch approved proposals for AI fixes ---
        try:
            from services.audit_pipeline import dispatch_audit_proposals

            dispatch_result = dispatch_audit_proposals(limit=10)
            total_dispatched = dispatch_result.get("dispatched", 0)
            logger.info(
                "Repair pipeline phase 2: %d proposals dispatched for AI fixes",
                total_dispatched,
            )
        except Exception as dispatch_err:
            logger.warning("Repair pipeline dispatch phase failed: %s", dispatch_err)
            total_dispatched = 0

        logger.info(
            "Automated module audit: %d modules audited (%d clean, %d violations) — "
            "severity: %d red, %d yellow, %d info — %d proposals created, %d dispatched",
            audited,
            clean,
            violations,
            severity_totals["red"],
            severity_totals["yellow"],
            severity_totals["info"],
            total_proposals,
            total_dispatched,
        )

        # --- Phase 3: Route Telegram summary through A.R.C.H.I.E. inbox ---
        if violations > 0 or total_dispatched > 0:
            try:
                from services.telegram_service import send as _tg_send

                _tg_send(
                    category="system",
                    title="Weekly Repair Cycle Complete",
                    message=(
                        f"Modules audited: {audited} ({clean} clean, {violations} violations)\n"
                        f"Severity: {severity_totals['red']} red, {severity_totals['yellow']} yellow, {severity_totals['info']} info\n"
                        f"Proposals: {total_proposals} created, {total_dispatched} dispatched"
                    ),
                    source_agent="F.O.R.G.E.",
                    source_department="Engineering & Technology",
                    source_module="jobs",
                )
            except Exception as tg_err:
                logger.debug("Repair cycle Telegram summary failed: %s", tg_err)

        _log_cycle(
            "automated_module_audit",
            audited,
            0,  # items_failed = job errors, not audit violations
            0,
            details={
                "violations": violations,
                "clean": clean,
                "severity": severity_totals,
                "proposals_created": total_proposals,
                "proposals_dispatched": total_dispatched,
            },
        )
    except Exception as e:
        _log_cycle("automated_module_audit", 0, 1, 0, error_message=str(e))
        logger.warning(f"Automated module audit failed: {e}")


def daily_code_health_digest(flask_app, scheduler):
    """Job #51: Send a morning Telegram summary of code health status at 8:00 AM."""
    start = time.time()
    try:
        from datetime import datetime, timedelta
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            # Get latest code metrics snapshot
            cur.execute(
                """
                SELECT id, total_files, total_lines, scanned_at
                FROM code_metrics_snapshots
                ORDER BY scanned_at DESC LIMIT 1
            """
            )
            snapshot = cur.fetchone()

            # Get audit log summary — green (recent), stale (>30d), unaudited
            cur.execute(
                """
                SELECT module_name, status, audited_at
                FROM code_audit_log
                WHERE id IN (
                    SELECT MAX(id) FROM code_audit_log GROUP BY module_name
                )
            """
            )
            audits = cur.fetchall()

            green = 0
            stale = 0
            violations = 0
            stale_modules = []
            violation_modules = []

            for audit in audits:
                status = audit.get("status", "")
                module = audit.get("module_name", "unknown")
                audited_at = audit.get("audited_at")
                if status == "violations_found":
                    violations += 1
                    violation_modules.append(module)
                elif audited_at:
                    age = (
                        datetime.now() - audited_at.replace(tzinfo=None)
                        if audited_at.tzinfo
                        else datetime.now() - audited_at
                    )
                    if age > timedelta(days=30):
                        stale += 1
                        stale_modules.append(module)
                    else:
                        green += 1
                else:
                    stale += 1
                    stale_modules.append(module)

            # Get modules changed since last digest (commits in last 24h)
            cur.execute(
                """
                SELECT DISTINCT module_name FROM code_audit_log
                WHERE audited_at > NOW() - INTERVAL '24 hours'
                ORDER BY module_name
            """
            )
            changed = [r["module_name"] for r in cur.fetchall()]

            # Count total agent loop jobs
            job_count = len(scheduler.get_jobs()) if scheduler else 51

            # Build message
            total_files = snapshot["total_files"] if snapshot else 0
            total_lines = snapshot["total_lines"] if snapshot else 0

            lines = [
                "\U0001f4ca *Daily Code Health Digest*\n",
                f"\u2705 Green: {green}  \u23f3 Stale: {stale}  \u26a0\ufe0f Violations: {violations}",
                f"\U0001f4c1 {total_files} files, {total_lines:,} lines",
            ]

            if changed:
                lines.append(f"\n\U0001f504 Changed (24h): {', '.join(changed[:10])}")
            if violation_modules:
                lines.append(f"\n\u274c Violations in: {', '.join(violation_modules[:10])}")
            if stale_modules:
                lines.append(f"\n\u23f0 Stale: {', '.join(stale_modules[:5])}")

            lines.append(f"\n\U0001f916 Job count: {job_count}")

            text = "\n".join(lines)

            # Send to authorized admins via unified telegram service
            try:
                from services.telegram_service import send_info

                send_info("Code Health Digest", text, source_module="department_hq.jobs")
                logger.info(
                    "Code health digest sent: %d green, %d stale, %d violations",
                    green,
                    stale,
                    violations,
                )
            except Exception as tg_err:
                logger.warning(f"Code health digest telegram failed: {tg_err}")

        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("code_health_digest", 1, 0, duration_ms)

    except Exception as e:
        logger.warning(f"Code health digest failed: {e}")
        _log_cycle("code_health_digest", 0, 1, int((time.time() - start) * 1000), error_message=str(e))


def daily_code_health_scan():
    """Job #55: Run codebase scan daily at 2:00 AM. Saves snapshot for Code Health tab."""
    start = time.time()
    try:
        from services.code_metrics_service import scan_codebase, save_snapshot

        logger.info("[CodeHealthScan] Starting daily codebase scan")
        metrics = scan_codebase()
        snapshot_id = save_snapshot(metrics)
        logger.info(
            "[CodeHealthScan] Complete: %d files, %d lines, snapshot #%s",
            metrics.get("total_files", 0),
            metrics.get("total_lines", 0),
            snapshot_id,
        )
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("code_health_scan", 1, 0, duration_ms)

    except Exception as e:
        logger.warning(f"Code health scan failed: {e}")
        _log_cycle(
            "code_health_scan",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )


def daily_recompute_perf_baselines():
    """Job #59: Nightly recompute of P.R.O.B.E. perf baselines (03:45 EDT).

    Walks every (suite_id, test_name) pair with ≥10 successful samples and
    upserts qa_perf_baselines.baseline_p95_ms. Drift-correcting nightly batch
    so the post-deploy gate stays calibrated to recent production behaviour.

    Defensive: never raises. Loop log captures success count or error.
    """
    start = time.time()
    try:
        from services import qa_baseline_service

        updated = qa_baseline_service.recompute_all_baselines()
        duration_ms = int((time.time() - start) * 1000)
        logger.info("[PerfBaselines] Recomputed %d baselines", updated)
        _log_cycle("recompute_perf_baselines", updated, 0, duration_ms)
    except Exception as e:
        logger.warning(f"Perf baselines recompute failed: {e}")
        _log_cycle(
            "recompute_perf_baselines",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )


def competitor_landscape_scan(flask_app):
    """Job #52: Scan AI competitor landscape every 2 weeks, update knowledge_base, notify via Telegram."""
    start = time.time()
    try:
        from services.competitor_scan_service import run_competitor_scan

        result = run_competitor_scan()
        created = result["created"]
        updated = result["updated"]
        total = result["total"]

        if created == 0 and updated == 0:
            logger.info(f"[Competitors] All {total} competitors up to date, nothing to do")
            _log_cycle("competitor_scan", 1, 0, int((time.time() - start) * 1000))
            return

        # Build Telegram summary
        lines = [
            "\U0001f50d *AI Competitor Landscape Scan*\n",
            f"\U0001f4ca Tracked: {total} competitors across {len(result.get('summary_lines', []))} changes",
            f"\U0001f195 New: {created}  \U0001f504 Updated: {updated}",
        ]
        if result.get("summary_lines"):
            lines.append("\n*Changes:*")
            lines.extend(result["summary_lines"][:15])

        text = "\n".join(lines)

        # Send Telegram notification
        try:
            from services.telegram_service import send_sync

            send_sync("Competitor Landscape Scan", text, source_module="department_hq.jobs")
        except Exception as tg_err:
            logger.warning(f"Competitor scan telegram failed: {tg_err}")

        logger.info(
            "[Competitors] Scan complete: %d new, %d updated out of %d tracked",
            created,
            updated,
            total,
        )
        _log_cycle("competitor_scan", 1, 0, int((time.time() - start) * 1000))

    except Exception as e:
        logger.warning(f"[Competitors] Landscape scan failed: {e}")
        _log_cycle("competitor_scan", 0, 1, int((time.time() - start) * 1000), error_message=str(e))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_department_hq_jobs(scheduler, flask_app):
    """Central job registration — ALL department jobs go through here.

    This is the single entry point for job registration, called from AgentLoop.
    Individual modules still define their job functions, but registration
    is centralized here for visibility and monitoring (Decision #440).
    """
    # 1. Register Department HQ's own jobs
    _register_own_jobs(scheduler, flask_app)

    # 2. Register other module jobs — centralized here (was in agent_loop.py)
    try:
        from tools.consciousness.jobs import register_consciousness_jobs

        register_consciousness_jobs(scheduler, flask_app)
        logger.info("[DeptHQ] Consciousness jobs registered")
    except Exception as e:
        logger.error("[DeptHQ] Failed: consciousness jobs: %s", e)

    try:
        from tools.security_network.jobs import register_security_jobs

        register_security_jobs(scheduler, flask_app)
        logger.info("[DeptHQ] Security/network jobs registered")
    except Exception as e:
        logger.error("[DeptHQ] Failed: security jobs: %s", e)

    try:
        from services.agent_jobs import register_agent_welfare_jobs

        register_agent_welfare_jobs(scheduler, flask_app)
        logger.info("[DeptHQ] Agent welfare jobs registered")
    except Exception as e:
        logger.error("[DeptHQ] Failed: welfare jobs: %s", e)

    try:
        from services.fleet_jobs import register_fleet_jobs

        register_fleet_jobs(scheduler, flask_app)
        logger.info("[DeptHQ] Fleet jobs registered")
    except Exception as e:
        logger.error("[DeptHQ] Failed: fleet jobs: %s", e)


def _register_own_jobs(scheduler, flask_app):
    """Register Department HQ's own background jobs with the scheduler."""
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    def with_ctx(fn):
        """Wrap function to run inside Flask app context."""

        def wrapper():
            with flask_app.app_context():
                fn()

        wrapper.__name__ = fn.__name__
        return wrapper

    def with_ctx_app(fn):
        """Wrap function that needs flask_app to run inside Flask app context."""

        def wrapper():
            with flask_app.app_context():
                fn(flask_app)

        wrapper.__name__ = fn.__name__
        return wrapper

    def with_ctx_app_sched(fn):
        """Wrap function that needs flask_app + scheduler to run inside Flask app context."""

        def wrapper():
            with flask_app.app_context():
                fn(flask_app, scheduler)

        wrapper.__name__ = fn.__name__
        return wrapper

    # Job #40 — Daily Code Metrics Scan (3:00 AM)
    scheduler.add_job(
        with_ctx(daily_code_metrics_scan),
        trigger=CronTrigger(hour=3, minute=0, timezone="America/Toronto"),
        id="agent_code_metrics",
        name="Agent Loop: Daily Code Metrics Scan",
        replace_existing=True,
    )

    # Job #41 — Pattern Compliance Check (4:00 AM)
    scheduler.add_job(
        with_ctx(pattern_compliance_check),
        trigger=CronTrigger(hour=4, minute=0, timezone="America/Toronto"),
        id="agent_pattern_compliance",
        name="Agent Loop: Pattern Compliance Check",
        replace_existing=True,
    )

    # Job #58 — Automated Module Audit (daily 3:30 AM)
    scheduler.add_job(
        with_ctx_app(automated_module_audit),
        trigger=CronTrigger(hour=3, minute=30, timezone="America/Toronto"),
        id="agent_automated_module_audit",
        name="Agent Loop: Automated Module Audit",
        replace_existing=True,
    )

    # Job #51 — Daily Code Health Digest (8:00 AM)
    scheduler.add_job(
        with_ctx_app_sched(daily_code_health_digest),
        trigger=CronTrigger(hour=8, minute=0, timezone="America/Toronto"),
        id="agent_code_health_digest",
        name="Agent Loop: Daily Code Health Digest",
        replace_existing=True,
    )

    # Job #55 — Daily Code Health Scan (2:00 AM)
    scheduler.add_job(
        with_ctx(daily_code_health_scan),
        trigger=CronTrigger(hour=2, minute=0, timezone="America/Toronto"),
        id="agent_code_health_scan",
        name="Agent Loop: Daily Code Health Scan",
        replace_existing=True,
    )

    # Job #52 — Competitor Landscape Scan (every 2 weeks)
    scheduler.add_job(
        with_ctx_app(competitor_landscape_scan),
        trigger=IntervalTrigger(days=14),
        id="agent_competitor_scan",
        name="Agent Loop: Competitor Landscape Scan",
        replace_existing=True,
    )

    # Job #59 — Nightly Recompute Perf Baselines (3:45 AM)
    # 03:00 reserved by #40 (code_metrics), 03:15 by forge_dep_drift,
    # 03:30 by #58 (module_audit) — 03:45 is the next clean slot.
    scheduler.add_job(
        daily_recompute_perf_baselines,
        trigger=CronTrigger(hour=3, minute=45, timezone="America/Toronto"),
        id="agent_recompute_perf_baselines",
        name="Agent Loop: Nightly Recompute Perf Baselines",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    logger.info("[DeptHQ] Registered 7 code health/audit jobs")
