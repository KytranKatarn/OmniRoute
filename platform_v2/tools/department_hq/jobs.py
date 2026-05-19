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

    # Job #60 — Daily Backup Retention Cleanup (7:00 AM — after 06:00 shell cron backup)
    def _run_backup_retention_cleanup():
        # Reference pattern for job governance: audit_log + Telegram notification
        from database import get_db_cursor
        from services.telegram_service import send_info

        job_name = "backup_retention_cleanup"

        def _audit(event_type: str, details: str):
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """INSERT INTO governance_audit_log
                           (event_category, event_type, action, details, timestamp)
                           VALUES ('job_governance', %s, 'scheduler', %s, NOW())""",
                        (event_type, details),
                    )
            except Exception as ae:
                logger.warning("[BackupRetention] audit_log write failed: %s", ae)

        _audit(f"{job_name}.started", "Daily backup retention cleanup initiated")
        try:
            from tools.backup_manager._shared import cleanup_old_backups

            result = cleanup_old_backups(dry_run=False)
            deleted = (result or {}).get("deleted_count", 0)
            detail = f"Auto-cleanup: {deleted} backup(s) pruned"
            logger.info("[BackupRetention] %s", detail)
            _audit(f"{job_name}.completed", detail)
            if deleted > 0:
                send_info(f"🗑️ Backup retention: {deleted} old backup(s) removed by GFS policy.")
        except Exception as e:
            logger.error("[BackupRetention] Auto-cleanup failed: %s", e)
            _audit(f"{job_name}.failed", str(e)[:500])

    scheduler.add_job(
        with_ctx(_run_backup_retention_cleanup),
        trigger=CronTrigger(hour=7, minute=0, timezone="America/Toronto"),
        id="agent_backup_retention_cleanup",
        name="Agent Loop: Daily Backup Retention Cleanup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Job #61 — F.O.R.G.E. PR Poll (every 4h) — sync open PRs from GitHub into pr_reviews
    def _run_forge_pr_poll():
        from database import get_db_cursor
        from tools.repair_bay.services.pr_review_service import (
            get_tracked_repos,
            poll_open_prs,
        )

        def _audit(event_type: str, details: str):
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """INSERT INTO governance_audit_log
                           (event_category, event_type, action, details, timestamp)
                           VALUES ('job_governance', %s, 'scheduler', %s, NOW())""",
                        (event_type, details),
                    )
            except Exception as ae:
                logger.warning("[ForgePRPoll] audit_log write failed: %s", ae)

        _audit("forge_pr_poll.started", "F.O.R.G.E. PR poll initiated")
        repos = get_tracked_repos()
        total_inserted = total_updated = total_errors = 0
        for repo in repos:
            result = poll_open_prs(repo=repo)
            total_inserted += result.get("inserted", 0)
            total_updated += result.get("updated", 0)
            total_errors += result.get("errors", 0)
        detail = f"repos={len(repos)} inserted={total_inserted} updated={total_updated} errors={total_errors}"
        logger.info("[ForgePRPoll] %s", detail)
        _audit("forge_pr_poll.completed", detail)

    scheduler.add_job(
        with_ctx(_run_forge_pr_poll),
        trigger=IntervalTrigger(hours=4),
        id="agent_forge_pr_poll",
        name="Agent Loop: F.O.R.G.E. PR Poll",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Job #62 — F.O.R.G.E. PR Analyze (every 4h at +20min offset) — AI review pending PRs
    def _run_forge_pr_analyze():
        from database import get_db_cursor
        from services.telegram_service import send_info
        from tools.repair_bay.services.pr_diff_analyzer import analyze_pending_prs

        def _audit(event_type: str, details: str):
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """INSERT INTO governance_audit_log
                           (event_category, event_type, action, details, timestamp)
                           VALUES ('job_governance', %s, 'scheduler', %s, NOW())""",
                        (event_type, details),
                    )
            except Exception as ae:
                logger.warning("[ForgePRAnalyze] audit_log write failed: %s", ae)

        _audit("forge_pr_analyze.started", "F.O.R.G.E. PR analysis cycle initiated")
        result = analyze_pending_prs(max_prs=5)
        processed = result.get("processed", 0)
        failed = result.get("failed", 0)
        skipped = result.get("skipped", 0)
        detail = f"processed={processed} failed={failed} skipped={skipped}"
        logger.info("[ForgePRAnalyze] %s", detail)
        _audit("forge_pr_analyze.completed", detail)
        if processed > 0:
            send_info(f"⚙️ F.O.R.G.E. reviewed {processed} PR(s). " f"Check Repair Bay → PR Review for summaries.")
        if failed > 0:
            logger.warning("[ForgePRAnalyze] %d PR(s) failed analysis", failed)

    scheduler.add_job(
        with_ctx(_run_forge_pr_analyze),
        trigger=CronTrigger(hour="1,5,9,13,17,21", minute=20, timezone="America/Toronto"),
        id="agent_forge_pr_analyze",
        name="Agent Loop: F.O.R.G.E. PR Analyze",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Job #63 — Civic Transparency GEDS daily refresh (3:31 AM)
    try:
        from services.civic_geds_refresh import run_geds_refresh_sync

        scheduler.add_job(
            run_geds_refresh_sync,
            trigger=CronTrigger(hour=3, minute=31, timezone="America/Toronto"),
            id="civic_transparency_geds_refresh",
            name="Civic Transparency — GEDS daily refresh",
            misfire_grace_time=3600,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        logger.info("[DeptHQ] Registered civic_transparency_geds_refresh job")
    except Exception as e:
        logger.error("[DeptHQ] Failed to register civic_transparency_geds_refresh: %s", e)

    # Job #64 — Model Queue Planner (every 5 min)
    # Rebalances dispatch_pending_queue priorities to minimise GPU model swaps.
    # Groups same-model tasks so the dispatcher drains one model completely
    # before loading the next. Also logs cluster node topology so DHQ shows
    # which nodes could unlock additional throughput.
    def _run_model_queue_planner():
        import json as _json
        import time as _time

        start = _time.time()
        job_name = "model_queue_planner"

        try:
            from database import get_db_cursor as _gdc

            # ── 1. Read pending queue grouped by model ────────────────────
            with _gdc() as (_c, _cur):
                _cur.execute(
                    """
                    SELECT model_needed,
                           STRING_AGG(DISTINCT agent_name, ', ') AS agents,
                           COUNT(*) AS task_count,
                           SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running
                    FROM dispatch_pending_queue
                    WHERE status IN ('queued','running')
                    GROUP BY model_needed
                    ORDER BY COUNT(*) DESC
                    """
                )
                model_groups = [dict(r) for r in _cur.fetchall()]

                # ── 2. Read cluster nodes ─────────────────────────────────
                _cur.execute(
                    """
                    SELECT node_id, node_name, hostname, gpu_vram_gb, ram_gb,
                           ollama_available, deployment_mode,
                           last_heartbeat,
                           (last_heartbeat > NOW() - INTERVAL '3 minutes') AS is_live
                    FROM remote_nodes
                    WHERE is_active = true
                    ORDER BY last_heartbeat DESC NULLS LAST
                    """
                )
                nodes = [dict(r) for r in _cur.fetchall()]

            if not model_groups:
                logger.debug("[ModelQueuePlanner] queue empty — nothing to plan")
                return

            # ── 3. Classify nodes ─────────────────────────────────────────
            # hub: archie-starbase (always the anchor)
            # gpu_fleet: live nodes with GPU and Ollama (e.g. Node .245 when online)
            # cpu_fleet: live nodes with Ollama but no GPU (VPS when Ollama installed)
            # potential: live nodes without Ollama — could be unlocked
            gpu_fleet = [
                n
                for n in nodes
                if n.get("is_live")
                and n.get("ollama_available")
                and n.get("gpu_vram_gb")
                and n["node_id"] != "archie-starbase"
            ]
            cpu_fleet = [
                n
                for n in nodes
                if n.get("is_live")
                and n.get("ollama_available")
                and not n.get("gpu_vram_gb")
                and n["node_id"] != "archie-starbase"
            ]
            potential = [
                n
                for n in nodes
                if n.get("is_live") and not n.get("ollama_available") and n["node_id"] != "archie-starbase"
            ]

            # ── 4. Build priority assignments ─────────────────────────────
            # Largest batch → highest priority (drain first for minimal swaps).
            # CPU-only models get a +1 bonus: they don't occupy the GPU lane
            # and can run while a GPU model is loading/running.
            CPU_SIGNATURES = {"-cpu", "embed", "arctic"}
            plan_actions = []
            updates = []

            for rank, group in enumerate(model_groups):
                model = group["model_needed"]
                count = group["task_count"]
                agents = group["agents"]
                is_cpu = any(sig in model.lower() for sig in CPU_SIGNATURES)

                # Priority: top batch = 9, each rank down -1, floor at 5
                new_priority = max(5, 9 - rank + (1 if is_cpu else 0))

                # Route hint: can any fleet node handle this model?
                if is_cpu and cpu_fleet:
                    route = f"→ CPU fleet ({cpu_fleet[0]['node_name']})"
                elif not is_cpu and gpu_fleet:
                    route = f"→ GPU fleet ({gpu_fleet[0]['node_name']})"
                else:
                    route = "→ hub"

                updates.append((new_priority, model))
                plan_actions.append(f"{agents} [{model}] ×{count} tasks → priority {new_priority} {route}")

            # ── 5. Apply priority updates ────────────────────────────────
            with _gdc(commit=True) as (_c2, _cur2):
                for new_priority, model in updates:
                    _cur2.execute(
                        "UPDATE dispatch_pending_queue SET priority=%s WHERE model_needed=%s AND status='queued'",
                        (new_priority, model),
                    )

            # ── 6. Potential unlock report ───────────────────────────────
            unlock_hints = []
            for n in potential:
                ram = n.get("ram_gb") or 0
                gpu = n.get("gpu_vram_gb") or 0
                if gpu >= 8:
                    unlock_hints.append(
                        f"{n['node_name']} ({n['hostname']}) — RTX/GPU {gpu}GB VRAM: install Ollama → unlock mid-tier GPU agents"
                    )
                elif ram >= 6:
                    unlock_hints.append(
                        f"{n['node_name']} ({n['hostname']}) — {ram:.0f}GB RAM, no GPU: install Ollama → unlock small CPU agents (qwen2.5:1.5b, llama3.2:3b)"
                    )

            # ── 7. Log to autonomy_loop_log ──────────────────────────────
            duration_ms = int((_time.time() - start) * 1000)
            details = {
                "plan": plan_actions,
                "hub_gpu_gb": 8,
                "gpu_fleet_nodes": [n["node_name"] for n in gpu_fleet],
                "cpu_fleet_nodes": [n["node_name"] for n in cpu_fleet],
                "potential_unlocks": unlock_hints,
            }
            with _gdc(commit=True) as (_c3, _cur3):
                _cur3.execute(
                    """INSERT INTO autonomy_loop_log
                       (job_name, status, items_processed, items_failed, duration_ms, details, department)
                       VALUES (%s,'success',%s,0,%s,%s,'Engineering & Technology')""",
                    (job_name, len(model_groups), duration_ms, _json.dumps(details)),
                )

            logger.info(
                "[ModelQueuePlanner] %d model groups rebalanced | gpu_fleet=%d cpu_fleet=%d potential=%d",
                len(model_groups),
                len(gpu_fleet),
                len(cpu_fleet),
                len(potential),
            )
            for line in plan_actions:
                logger.info("[ModelQueuePlanner]   %s", line)
            if unlock_hints:
                logger.info("[ModelQueuePlanner] Potential unlocks: %s", unlock_hints)

        except Exception as exc:
            logger.error("[ModelQueuePlanner] failed: %s", exc)

    scheduler.add_job(
        with_ctx(_run_model_queue_planner),
        trigger=IntervalTrigger(minutes=5),
        id="model_queue_planner",
        name="Agent Loop: Model Queue Planner",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("[DeptHQ] Registered model_queue_planner job (5-min interval)")

    # ── S.C.O.U.T. Jobs ─────────────────────────────────────────────────────

    def _run_scout_procurement_sync():
        """Nightly CanadaBuys tender sync via S.C.O.U.T. browser fleet."""
        import urllib.request as _ur
        import json as _json

        url = "http://archie_scraper:4243/jobs"
        payload = _json.dumps(
            {
                "job_type": "procurement_sync",
                "target_url": "https://canadabuys.canada.ca/en/tender-opportunities",
                "params": {"max_pages": 5},
                "requested_by": "agent_loop",
            }
        ).encode()
        try:
            req = _ur.Request(url, data=payload)
            req.add_header("Content-Type", "application/json")
            r = _ur.urlopen(req, timeout=10)
            d = _json.loads(r.read())
            logger.info("[scout] procurement sync job #%s submitted", d.get("job_id"))
        except Exception as exc:
            logger.warning("[scout] procurement sync dispatch failed: %s", exc)

    def _run_scout_platform_ux_check():
        """Weekly UX screenshot check of platform + watch product landing pages."""
        import urllib.request as _ur
        import json as _json

        targets = [
            "https://platform.kytranempowerment.com",
            "https://gov.kytranempowerment.com",
            "https://civic.kytranempowerment.com",
        ]
        for target_url in targets:
            try:
                payload = _json.dumps(
                    {
                        "job_type": "ux_audit",
                        "target_url": target_url,
                        "params": {"viewport": "1280x800"},
                        "requested_by": "agent_loop",
                    }
                ).encode()
                req = _ur.Request("http://archie_scraper:4243/jobs", data=payload)
                req.add_header("Content-Type", "application/json")
                r = _ur.urlopen(req, timeout=10)
                d = _json.loads(r.read())
                logger.info("[scout] UX check job #%s submitted for %s", d.get("job_id"), target_url)
            except Exception as exc:
                logger.warning("[scout] UX check failed for %s: %s", target_url, exc)

    scheduler.add_job(
        with_ctx(_run_scout_procurement_sync),
        trigger=CronTrigger(hour=2, minute=0, timezone="America/Toronto"),
        id="scout_procurement_sync",
        name="Scout: Nightly CanadaBuys tender sync",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered scout_procurement_sync job (daily 2:00 AM)")

    scheduler.add_job(
        with_ctx(_run_scout_platform_ux_check),
        trigger=CronTrigger(day_of_week="sun", hour=9, minute=0, timezone="America/Toronto"),
        id="scout_platform_ux_check",
        name="Scout: Weekly platform UX check",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered scout_platform_ux_check job (Sunday 9:00 AM)")

    # -------------------------------------------------------------------------
    # Job #120: Dispatch queue zombie reaper — expire stale running rows
    # -------------------------------------------------------------------------
    def _run_dispatch_zombie_reaper():
        """Expire dispatch_pending_queue rows stuck in 'running' for >30 min.

        Platform restarts orphan in-flight rows at 'running' status. Without
        this reaper they accumulate indefinitely, making the CLUSTER ACTIVITY
        panel show false counts and blocking queue health checks.
        """
        try:
            from database import get_db_cursor
            from services.telegram_service import send_system

            with get_db_cursor(commit=True) as (_, cur):
                cur.execute(
                    """
                    UPDATE dispatch_pending_queue
                       SET status = 'failed'
                     WHERE status = 'running'
                       AND queued_at < NOW() - INTERVAL '30 minutes'
                    RETURNING id, agent_name, capability
                    """
                )
                reaped = cur.fetchall() or []

            if reaped:
                summary = ", ".join(f"{r['agent_name']}/{r['capability']}" for r in reaped[:5])
                if len(reaped) > 5:
                    summary += f" +{len(reaped) - 5} more"
                logger.warning(
                    "[DeptHQ] Zombie reaper: expired %d stuck running tasks — %s",
                    len(reaped),
                    summary,
                )
                try:
                    send_system(
                        f"⚠️ Queue zombie reaper: expired {len(reaped)} tasks " f"stuck >30 min.\nAgents: {summary}"
                    )
                except Exception:
                    pass
            else:
                logger.debug("[DeptHQ] Zombie reaper: queue clean")
        except Exception as exc:
            logger.error("[DeptHQ] Zombie reaper failed: %s", exc)

    scheduler.add_job(
        with_ctx(_run_dispatch_zombie_reaper),
        trigger=CronTrigger(minute="*/15", timezone="America/Toronto"),
        id="dispatch_zombie_reaper",
        name="Queue: Expire zombie running tasks (>30 min)",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered dispatch_zombie_reaper job (every 15 min)")

    # Job #121: Media generation queue reaper — re-queue stuck generating jobs
    # -------------------------------------------------------------------------
    def _run_media_generation_reaper():
        """Reset media_generation_queue rows stuck in 'generating' >15 min.

        If a fleet node drops mid-generation, the queue entry stays at
        'generating' forever. This reaper resets it to 'pending' so the
        media_generation_worker re-dispatches to the next best available node.
        """
        try:
            from database import get_db_cursor
            from services.telegram_service import send_system

            with get_db_cursor(commit=True) as (_, cur):
                cur.execute(
                    """
                    UPDATE media_generation_queue
                       SET status = 'pending', started_at = NULL
                     WHERE status = 'generating'
                       AND started_at < NOW() - INTERVAL '15 minutes'
                    RETURNING id, media_type, params->>'model' AS model
                    """
                )
                reaped = cur.fetchall() or []

            if reaped:
                summary = ", ".join(f"#{r['id']} {r['media_type']}/{r.get('model', '?')}" for r in reaped[:5])
                logger.warning(
                    "[DeptHQ] Media reaper: reset %d stuck jobs → pending — %s",
                    len(reaped),
                    summary,
                )
                try:
                    send_system(
                        f"⚠️ Media generation reaper: {len(reaped)} stuck job(s) "
                        f"reset to pending (node may have dropped).\n{summary}"
                    )
                except Exception:
                    pass
            else:
                logger.debug("[DeptHQ] Media reaper: queue clean")
        except Exception as exc:
            logger.error("[DeptHQ] Media generation reaper failed: %s", exc)

    scheduler.add_job(
        with_ctx(_run_media_generation_reaper),
        trigger=CronTrigger(minute="*/10", timezone="America/Toronto"),
        id="media_generation_reaper",
        name="Queue: Reset stuck media generation jobs (>15 min)",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered media_generation_reaper job (every 10 min)")

    # =========================================================================
    # WTF Fleet Orchestration Jobs — Project #350
    # 4 independent jobs, staggered every 30 min across fleet nodes.
    # DHQ dispatches to News & Media agents (B.I.A.S., V.E.R.I.F.Y., L.O.C.A.L.,
    # S.C.O.U.T.) across Starship-246, Starship-245, outpost-us.
    # VPS backlog workers remain active at low cap as always-on fallback.
    # =========================================================================

    _WTF_BATCH = 25
    _WTF_MAX_PER_CYCLE = 200
    _WTF_FAILBACK_THRESHOLD = 3

    # Context manager: connects to the wtf database (separate from archie DB).
    # wtf tables live in the wtf schema of archie_database container, dbname=wtf.
    from contextlib import contextmanager as _cm

    @_cm
    def _wtf_cur(commit=False):
        import os
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(
            host="archie_database",
            port=5432,
            dbname="wtf",
            user="wtfuser",
            password=os.getenv("WTF_DB_PASSWORD", ""),
            options="-c search_path=wtf",
        )
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Job #122: WTF LLM Analysis — bias scoring via B.I.A.S. / V.E.R.I.F.Y.
    # Runs every 30 min at :00 and :30 (EDT).
    def _run_wtf_llm_analysis():
        try:
            import json as _json
            from tools.department_hq.services.department_dispatcher import dispatch

            processed = failed = consecutive_failures = 0

            while processed + failed < _WTF_MAX_PER_CYCLE:
                with _wtf_cur() as cur:
                    cur.execute(
                        """
                        SELECT a.id, a.title, a.body, s.slug AS source_slug
                        FROM wtf.articles a
                        JOIN wtf.sources s ON s.id = a.source_id
                        WHERE a.ai_analyzed = false
                          AND a.published_at > NOW() - INTERVAL '90 days'
                          AND NOT EXISTS (
                              SELECT 1 FROM wtf.llm_analyses la WHERE la.article_id = a.id
                          )
                        ORDER BY a.published_at DESC
                        LIMIT %s
                        """,
                        (_WTF_BATCH,),
                    )
                    batch = cur.fetchall() or []

                if not batch:
                    break

                for row in batch:
                    if processed + failed >= _WTF_MAX_PER_CYCLE:
                        break
                    aid = row["id"]
                    title = row["title"]
                    body = (row["body"] or "")[:2000]
                    source_slug = row["source_slug"] or ""
                    prompt = (
                        f"Analyze the bias of this Canadian news article.\n\n"
                        f"Source: {source_slug}\nTitle: {title}\nBody: {body}\n\n"
                        'Return ONLY valid JSON: {"score": float -1 to 1, "band": string, '
                        '"rationale": string, "trigger_phrases": list[str], "confidence": float}'
                    )
                    result = dispatch(
                        capability="bias_analysis",
                        prompt=prompt,
                        module_id="wtf_dhq_llm",
                        json_mode=True,
                    )
                    if result.success:
                        try:
                            parsed = (
                                _json.loads(result.response)
                                if isinstance(result.response, str)
                                else (result.response or {})
                            )
                        except Exception:
                            parsed = {}
                        band = (parsed.get("band") or "center").lower().strip()
                        if band not in ("left", "center-left", "center", "center-right", "right"):
                            band = "center"
                        score = float(parsed.get("score") or 0.0)
                        rationale = str(parsed.get("rationale") or "")[:2000]
                        trigger_phrases = _json.dumps(parsed.get("trigger_phrases") or [])
                        confidence = parsed.get("confidence")
                        try:
                            with _wtf_cur(commit=True) as cur:
                                cur.execute(
                                    """
                                    INSERT INTO wtf.llm_analyses (article_id, sections_json, model, completed_at)
                                    VALUES (%s, %s::jsonb, 'dhq_bias_v1', NOW())
                                    ON CONFLICT (article_id, model) DO UPDATE
                                      SET sections_json = EXCLUDED.sections_json, completed_at = NOW()
                                    """,
                                    (aid, _json.dumps(parsed)),
                                )
                                cur.execute(
                                    "UPDATE wtf.articles SET ai_analyzed = true, ai_analyzed_at = NOW() WHERE id = %s",
                                    (aid,),
                                )
                                cur.execute(
                                    """
                                    INSERT INTO wtf.bias_scores
                                        (article_id, band, score, heuristic_version, rationale,
                                         analyzed_by, trigger_phrases, confidence, computed_at)
                                    VALUES (%s, %s, %s, 'dhq_v1', %s, 'dhq_v1', %s::jsonb, %s, NOW())
                                    ON CONFLICT (article_id) DO UPDATE
                                      SET band = EXCLUDED.band, score = EXCLUDED.score,
                                          rationale = EXCLUDED.rationale, analyzed_by = EXCLUDED.analyzed_by,
                                          trigger_phrases = EXCLUDED.trigger_phrases,
                                          confidence = EXCLUDED.confidence, computed_at = NOW()
                                    """,
                                    (aid, band, score, rationale, trigger_phrases, confidence),
                                )
                            processed += 1
                            consecutive_failures = 0
                        except Exception as persist_exc:
                            logger.warning("[WTFLLMJob] persist failed article=%s: %s", aid, persist_exc)
                            failed += 1
                    else:
                        failed += 1
                        consecutive_failures += 1
                        if consecutive_failures >= _WTF_FAILBACK_THRESHOLD:
                            logger.warning(
                                "[WTFLLMJob] %d consecutive fleet failures — VPS fallback active this cycle",
                                consecutive_failures,
                            )
                            break

            logger.info("[WTFLLMJob] cycle done: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            logger.error("[WTFLLMJob] crashed: %s", exc)

    scheduler.add_job(
        with_ctx(_run_wtf_llm_analysis),
        trigger=CronTrigger(minute="0,30", timezone="America/Toronto"),
        id="wtf_llm_analysis",
        name="WTF: LLM Bias Analysis — B.I.A.S./V.E.R.I.F.Y. fleet (Project #350)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered wtf_llm_analysis job (every 30 min at :00/:30)")

    # Job #123: WTF Geo Extraction — location mapping via L.O.C.A.L.
    # Runs every 30 min at :05 and :35 (staggered from LLM).
    def _run_wtf_geo():
        try:
            import json as _json
            from tools.department_hq.services.department_dispatcher import dispatch

            processed = failed = consecutive_failures = 0

            while processed + failed < _WTF_MAX_PER_CYCLE:
                with _wtf_cur() as cur:
                    cur.execute(
                        """
                        SELECT a.id, a.title, a.body
                        FROM wtf.articles a
                        WHERE a.province_code IS NULL
                          AND a.city IS NULL
                          AND a.published_at > NOW() - INTERVAL '90 days'
                        ORDER BY a.published_at DESC
                        LIMIT %s
                        """,
                        (_WTF_BATCH,),
                    )
                    batch = cur.fetchall() or []

                if not batch:
                    break

                for row in batch:
                    if processed + failed >= _WTF_MAX_PER_CYCLE:
                        break
                    aid = row["id"]
                    title = row["title"]
                    body = (row["body"] or "")[:1000]
                    prompt = (
                        f"Extract the primary geographic location this news article is about.\n\n"
                        f"Title: {title}\nBody: {body}\n\n"
                        'Return ONLY valid JSON: {"province_code": "ON" or null, "country_code": "CA"|"US"|... or null, '
                        '"city": "Toronto" or null, "lat": float or null, "lng": float or null, '
                        '"geo_scope": "national|provincial|municipal|international", "geo_confidence": 0.0-1.0}'
                    )
                    result = dispatch(
                        capability="geo_extraction",
                        prompt=prompt,
                        module_id="wtf_dhq_geo",
                        json_mode=True,
                    )
                    if result.success:
                        try:
                            parsed = (
                                _json.loads(result.response)
                                if isinstance(result.response, str)
                                else (result.response or {})
                            )
                        except Exception:
                            parsed = {}
                        try:
                            with _wtf_cur(commit=True) as cur:
                                cur.execute(
                                    """
                                    UPDATE wtf.articles
                                    SET province_code = %s, city = %s, lat = %s, lng = %s,
                                        geo_scope = %s
                                    WHERE id = %s AND province_code IS NULL
                                    """,
                                    (
                                        parsed.get("province_code"),
                                        parsed.get("city"),
                                        parsed.get("lat"),
                                        parsed.get("lng"),
                                        parsed.get("geo_scope") or "national",
                                        aid,
                                    ),
                                )
                            processed += 1
                            consecutive_failures = 0
                        except Exception as persist_exc:
                            logger.warning("[WTFGeoJob] persist failed article=%s: %s", aid, persist_exc)
                            failed += 1
                    else:
                        failed += 1
                        consecutive_failures += 1
                        if consecutive_failures >= _WTF_FAILBACK_THRESHOLD:
                            logger.warning(
                                "[WTFGeoJob] %d consecutive fleet failures — VPS fallback active this cycle",
                                consecutive_failures,
                            )
                            break

            logger.info("[WTFGeoJob] cycle done: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            logger.error("[WTFGeoJob] crashed: %s", exc)

    scheduler.add_job(
        with_ctx(_run_wtf_geo),
        trigger=CronTrigger(minute="5,35", timezone="America/Toronto"),
        id="wtf_geo",
        name="WTF: Geo Extraction — L.O.C.A.L. fleet (Project #350)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered wtf_geo job (every 30 min at :05/:35)")

    # Job #124: WTF Factcheck — claim verification via V.E.R.I.F.Y.
    # Runs every 30 min at :10 and :40.
    def _run_wtf_factcheck():
        try:
            import json as _json
            from tools.department_hq.services.department_dispatcher import dispatch

            processed = failed = consecutive_failures = 0
            _VERDICT_MAP = {
                "verified": "true",
                "true": "true",
                "mostly_true": "mostly_true",
                "mixed": "mixed",
                "disputed": "false",
                "false": "false",
                "unverifiable": "unverified",
                "unverified": "unverified",
            }
            _OVERALL_MAP = {
                "verified": "verified",
                "true": "verified",
                "mostly_true": "mostly_true",
                "mixed": "mixed",
                "disputed": "disputed",
                "false": "disputed",
                "unverifiable": "unverifiable",
                "unverified": "unverifiable",
            }

            while processed + failed < _WTF_MAX_PER_CYCLE:
                with _wtf_cur() as cur:
                    cur.execute(
                        """
                        SELECT a.id, a.title, a.body
                        FROM wtf.articles a
                        WHERE a.published_at > NOW() - INTERVAL '90 days'
                          AND NOT EXISTS (
                              SELECT 1 FROM wtf.fact_checks fc
                              WHERE fc.article_id = a.id AND fc.analyzed_by = 'dhq_v1'
                          )
                        ORDER BY a.published_at DESC
                        LIMIT %s
                        """,
                        (_WTF_BATCH,),
                    )
                    batch = cur.fetchall() or []

                if not batch:
                    break

                for row in batch:
                    if processed + failed >= _WTF_MAX_PER_CYCLE:
                        break
                    aid = row["id"]
                    title = row["title"]
                    body = (row["body"] or "")[:2000]
                    prompt = (
                        f"Fact-check the claims in this Canadian news article.\n\n"
                        f"Title: {title}\nBody: {body}\n\n"
                        'Return ONLY valid JSON: {"claims": [{"text": str, "verdict": str, "reasoning": str}], '
                        '"overall_verdict": string, "confidence": float}. '
                        "Verdicts: verified | mixed | disputed | unverifiable"
                    )
                    result = dispatch(
                        capability="fact_check",
                        prompt=prompt,
                        module_id="wtf_dhq_factcheck",
                        json_mode=True,
                    )
                    if result.success:
                        try:
                            parsed = (
                                _json.loads(result.response)
                                if isinstance(result.response, str)
                                else (result.response or {})
                            )
                        except Exception:
                            parsed = {}
                        claims = parsed.get("claims") or []
                        overall_raw = (parsed.get("overall_verdict") or "unverifiable").lower()
                        overall = _OVERALL_MAP.get(overall_raw, "unverifiable")
                        claims_json = _json.dumps(claims)
                        try:
                            with _wtf_cur(commit=True) as cur:
                                cur.execute(
                                    "DELETE FROM wtf.fact_checks WHERE article_id = %s AND analyzed_by = 'dhq_v1'",
                                    (aid,),
                                )
                                if claims:
                                    for claim_item in claims:
                                        claim_text = str(claim_item.get("text") or "")[:2000]
                                        if not claim_text:
                                            continue
                                        verdict = _VERDICT_MAP.get(
                                            str(claim_item.get("verdict") or "unverified").lower().strip(),
                                            "unverified",
                                        )
                                        evidence = str(claim_item.get("reasoning") or claim_item.get("evidence") or "")[
                                            :4000
                                        ]
                                        cur.execute(
                                            """
                                            INSERT INTO wtf.fact_checks
                                                (article_id, claim, verdict, evidence, checker,
                                                 analyzed_by, claims, overall_verdict)
                                            VALUES (%s, %s, %s, %s, 'fact_v1', 'dhq_v1', %s::jsonb, %s)
                                            """,
                                            (aid, claim_text, verdict, evidence, claims_json, overall),
                                        )
                                else:
                                    cur.execute(
                                        """
                                        INSERT INTO wtf.fact_checks
                                            (article_id, claim, verdict, evidence, checker,
                                             analyzed_by, claims, overall_verdict)
                                        VALUES (%s, 'No verifiable claims detected.', 'unverified', '',
                                                'fact_v1', 'dhq_v1', '[]'::jsonb, 'unverifiable')
                                        """,
                                        (aid,),
                                    )
                            processed += 1
                            consecutive_failures = 0
                        except Exception as persist_exc:
                            logger.warning("[WTFFactcheckJob] persist failed article=%s: %s", aid, persist_exc)
                            failed += 1
                    else:
                        failed += 1
                        consecutive_failures += 1
                        if consecutive_failures >= _WTF_FAILBACK_THRESHOLD:
                            logger.warning(
                                "[WTFFactcheckJob] %d consecutive fleet failures — VPS fallback active this cycle",
                                consecutive_failures,
                            )
                            break

            logger.info("[WTFFactcheckJob] cycle done: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            logger.error("[WTFFactcheckJob] crashed: %s", exc)

    scheduler.add_job(
        with_ctx(_run_wtf_factcheck),
        trigger=CronTrigger(minute="10,40", timezone="America/Toronto"),
        id="wtf_factcheck",
        name="WTF: Factcheck — V.E.R.I.F.Y. fleet (Project #350)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered wtf_factcheck job (every 30 min at :10/:40)")

    # Job #126: WTF Factcheck Backlog — clears historical gap via V.E.R.I.F.Y.-B on hub.
    # Fires at :05/:35 — interleaved with production job (:10/:40), never overlapping.
    # Selects OLDEST articles first (production selects newest) so both ends drain together.
    # Auto-scalable: register any agent with fact_check_backlog skill on any node and
    # DHQ routes to the whole pool automatically — no changes needed here ever.
    def _run_wtf_factcheck_backlog():
        try:
            import json as _json
            from tools.department_hq.services.department_dispatcher import dispatch

            processed = failed = consecutive_failures = 0
            _VERDICT_MAP = {
                "verified": "true",
                "true": "true",
                "mostly_true": "mostly_true",
                "mixed": "mixed",
                "disputed": "false",
                "false": "false",
                "unverifiable": "unverified",
                "unverified": "unverified",
            }
            _OVERALL_MAP = {
                "verified": "verified",
                "true": "verified",
                "mostly_true": "mostly_true",
                "mixed": "mixed",
                "disputed": "disputed",
                "false": "disputed",
                "unverifiable": "unverifiable",
                "unverified": "unverifiable",
            }

            while processed + failed < _WTF_MAX_PER_CYCLE:
                with _wtf_cur() as cur:
                    cur.execute(
                        """
                        SELECT a.id, a.title, a.body
                        FROM wtf.articles a
                        WHERE a.published_at > NOW() - INTERVAL '90 days'
                          AND NOT EXISTS (
                              SELECT 1 FROM wtf.fact_checks fc WHERE fc.article_id = a.id
                          )
                        ORDER BY a.published_at ASC
                        LIMIT %s
                        """,
                        (_WTF_BATCH,),
                    )
                    batch = cur.fetchall() or []

                if not batch:
                    logger.info("[WTFFactcheckBacklog] backlog clear — nothing to process")
                    break

                for row in batch:
                    if processed + failed >= _WTF_MAX_PER_CYCLE:
                        break
                    aid = row["id"]
                    title = row["title"]
                    body = (row["body"] or "")[:2000]
                    prompt = (
                        f"Fact-check the claims in this Canadian news article.\n\n"
                        f"Title: {title}\nBody: {body}\n\n"
                        'Return ONLY valid JSON: {"claims": [{"text": str, "verdict": str, "reasoning": str}], '
                        '"overall_verdict": string, "confidence": float}. '
                        "Verdicts: verified | mixed | disputed | unverifiable"
                    )
                    result = dispatch(
                        capability="fact_check_backlog",
                        prompt=prompt,
                        module_id="wtf_dhq_factcheck_backlog",
                        json_mode=True,
                    )
                    if result.success:
                        try:
                            try:
                                parsed = (
                                    _json.loads(result.response)
                                    if isinstance(result.response, str)
                                    else result.response
                                )
                            except (_json.JSONDecodeError, TypeError, ValueError):
                                parsed = {}
                            claims = parsed.get("claims") or []
                            overall_raw = (parsed.get("overall_verdict") or "unverifiable").lower().strip()
                            overall = _OVERALL_MAP.get(overall_raw, "unverifiable")
                            claims_json = _json.dumps(claims)
                            with _wtf_cur(commit=True) as cur:
                                cur.execute(
                                    "DELETE FROM wtf.fact_checks WHERE article_id = %s AND analyzed_by = 'dhq_backlog_v1'",
                                    (aid,),
                                )
                                if claims:
                                    for claim_item in claims:
                                        claim_text = (claim_item.get("text") or "")[:500]
                                        verdict = _VERDICT_MAP.get(
                                            (claim_item.get("verdict") or "unverified").lower().strip(),
                                            "unverified",
                                        )
                                        evidence = (claim_item.get("reasoning") or "")[:4000]
                                        cur.execute(
                                            """
                                            INSERT INTO wtf.fact_checks
                                                (article_id, claim, verdict, evidence, checker,
                                                 analyzed_by, claims, overall_verdict)
                                            VALUES (%s, %s, %s, %s, 'fact_v1', 'dhq_backlog_v1', %s::jsonb, %s)
                                            """,
                                            (aid, claim_text, verdict, evidence, claims_json, overall),
                                        )
                                else:
                                    cur.execute(
                                        """
                                        INSERT INTO wtf.fact_checks
                                            (article_id, claim, verdict, evidence, checker,
                                             analyzed_by, claims, overall_verdict)
                                        VALUES (%s, 'No verifiable claims detected.', 'unverified', '',
                                                'fact_v1', 'dhq_backlog_v1', '[]'::jsonb, 'unverifiable')
                                        """,
                                        (aid,),
                                    )
                            processed += 1
                            consecutive_failures = 0
                        except Exception:
                            logger.exception("[WTFFactcheckBacklog] persist failed aid=%s", aid)
                            failed += 1
                            consecutive_failures += 1
                    else:
                        failed += 1
                        consecutive_failures += 1
                        logger.warning("[WTFFactcheckBacklog] dispatch failed aid=%s: %s", aid, result.error)

                    if consecutive_failures >= _WTF_FAILBACK_THRESHOLD:
                        logger.error("[WTFFactcheckBacklog] %d consecutive failures — aborting", consecutive_failures)
                        break

            logger.info("[WTFFactcheckBacklog] cycle done: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            logger.error("[WTFFactcheckBacklog] crashed: %s", exc)

    scheduler.add_job(
        with_ctx(_run_wtf_factcheck_backlog),
        trigger=CronTrigger(minute="5,35", timezone="America/Toronto"),
        id="wtf_factcheck_backlog",
        name="WTF: Factcheck Backlog — V.E.R.I.F.Y.-B hub pool (Job #126)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered wtf_factcheck_backlog job (every 30 min at :05/:35)")

    # Job #125: WTF Scout — full body fetch for short articles via S.C.O.U.T.
    # Runs every 30 min at :15 and :45. Only processes articles <7 days old.
    def _run_wtf_scout():
        try:
            from database import get_db_cursor
            from tools.department_hq.services.department_dispatcher import dispatch

            processed = failed = consecutive_failures = 0

            while processed + failed < _WTF_MAX_PER_CYCLE:
                with _wtf_cur() as cur:
                    cur.execute(
                        """
                        SELECT a.id, a.title, a.url
                        FROM wtf.articles a
                        WHERE LENGTH(a.body) < 300
                          AND a.url IS NOT NULL
                          AND a.published_at > NOW() - INTERVAL '7 days'
                        ORDER BY a.published_at DESC
                        LIMIT %s
                        """,
                        (_WTF_BATCH,),
                    )
                    batch = cur.fetchall() or []

                if not batch:
                    break

                for row in batch:
                    if processed + failed >= _WTF_MAX_PER_CYCLE:
                        break
                    aid = row["id"]
                    title = row["title"]
                    url = row["url"]
                    prompt = (
                        f"Scrape and return the full article text from this URL.\n\n"
                        f"URL: {url}\nTitle: {title}\n\n"
                        "Return ONLY the plain article body text. No HTML, no JSON, no metadata."
                    )
                    result = dispatch(
                        capability="web_scraping",
                        prompt=prompt,
                        module_id="wtf_dhq_scout",
                        json_mode=False,
                    )
                    if result.success and result.response and len(result.response.strip()) > 200:
                        try:
                            with _wtf_cur(commit=True) as cur:
                                cur.execute(
                                    "UPDATE wtf.articles SET body = %s WHERE id = %s AND LENGTH(body) < 300",
                                    (result.response.strip()[:8000], aid),
                                )
                            processed += 1
                            consecutive_failures = 0
                        except Exception as persist_exc:
                            logger.warning("[WTFScoutJob] persist failed article=%s: %s", aid, persist_exc)
                            failed += 1
                    else:
                        failed += 1
                        consecutive_failures += 1
                        if consecutive_failures >= _WTF_FAILBACK_THRESHOLD:
                            logger.warning(
                                "[WTFScoutJob] %d consecutive fleet failures — VPS fallback active this cycle",
                                consecutive_failures,
                            )
                            break

            logger.info("[WTFScoutJob] cycle done: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            logger.error("[WTFScoutJob] crashed: %s", exc)

    scheduler.add_job(
        with_ctx(_run_wtf_scout),
        trigger=CronTrigger(minute="15,45", timezone="America/Toronto"),
        id="wtf_scout",
        name="WTF: Scout Body Fetch — S.C.O.U.T. fleet (Project #350)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered wtf_scout job (every 30 min at :15/:45)")

    logger.info("[DeptHQ] Registered 4 WTF fleet orchestration jobs (Project #350)")

    # Cluster Orchestration Worker (Project #352) — every 60s.
    # Scores all active AI agents across all capabilities and fleet nodes.
    # Writes agent_overflow_state; refreshes the dispatcher's in-memory overflow cache.
    def _run_cluster_orchestration_worker():
        try:
            import json as _json
            import time as _time
            from database import get_db_cursor
            from services.cluster_orchestration_service import (
                compute_overflow_score,
                resolve_config,
                update_overflow_cache,
            )
            from services.fleet_resource_router import utilization_pct

            cycle_start = _time.monotonic()
            newly_activated = 0

            # Pass 1 — node utilization
            node_util: dict = {}
            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT id, current_load, max_concurrent, gpu_available,
                           gpu_vram_gb, ram_gb, last_heartbeat
                    FROM remote_nodes
                    WHERE last_heartbeat > NOW() - INTERVAL '2 minutes'
                """
                )
                for row in cur.fetchall() or []:
                    node_util[row["id"]] = utilization_pct(dict(row))

            # Pass 2 — agent idle minutes (time since last dispatch)
            agent_idle: dict = {}
            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT a.id,
                           COALESCE(
                               EXTRACT(EPOCH FROM NOW() - MAX(tel.created_at)) / 60,
                               999
                           ) AS idle_minutes
                    FROM agents a
                    LEFT JOIN task_execution_log tel
                        ON tel.agent_name = a.name
                       AND tel.created_at > NOW() - INTERVAL '60 minutes'
                    WHERE a.shift_state IN ('active', 'deployed')
                      AND a.worker_type = 'ai'
                    GROUP BY a.id
                """
                )
                for row in cur.fetchall() or []:
                    agent_idle[row["id"]] = float(row["idle_minutes"] if row["idle_minutes"] is not None else 999)

            # Pass 3 — queue depths per capability in dispatch_pending_queue
            queue_depths: dict = {}
            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT capability, COUNT(*) AS depth
                    FROM dispatch_pending_queue
                    WHERE status = 'pending'
                    GROUP BY capability
                """
                )
                for row in cur.fetchall() or []:
                    queue_depths[row["capability"]] = row["depth"]

            # Synthetic geo backlog — WTF articles awaiting geo live in the wtf DB,
            # not dispatch_pending_queue, so the orchestration score would always see
            # depth=0 for geo_extraction. Inject the real backlog count so L.O.C.A.L.
            # overflow activates correctly when there is a large pending queue.
            try:
                import os as _os
                import psycopg2
                import psycopg2.extras

                _wtf_conn = psycopg2.connect(
                    host="archie_database",
                    port=5432,
                    dbname="wtf",
                    user="wtfuser",
                    password=_os.getenv("WTF_DB_PASSWORD", ""),
                    options="-c search_path=wtf",
                )
                with _wtf_conn:
                    with _wtf_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as _wc:
                        _wc.execute(
                            """
                            SELECT COUNT(*) AS cnt FROM wtf.articles
                            WHERE province_code IS NULL AND city IS NULL
                              AND published_at > NOW() - INTERVAL '90 days'
                        """
                        )
                        _wtf_geo_row = _wc.fetchone()
                _wtf_conn.close()
                if _wtf_geo_row and _wtf_geo_row["cnt"]:
                    queue_depths["geo_extraction"] = queue_depths.get("geo_extraction", 0) + int(_wtf_geo_row["cnt"])
                    queue_depths["geo_quick"] = queue_depths.get("geo_quick", 0) + int(_wtf_geo_row["cnt"])
            except Exception as _wtf_geo_exc:
                logger.warning("[orchestration] geo backlog inject failed: %s", _wtf_geo_exc)

            # Pass 4 — load all config rows once
            with get_db_cursor() as (_, cur):
                cur.execute("SELECT * FROM cluster_orchestration_config")
                all_configs = [dict(r) for r in (cur.fetchall() or [])]

            # Pass 5 — score each (agent, node, capability) assignment
            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT na.hub_agent_id AS agent_id,
                           na.node_id,
                           sk.skill_name   AS capability,
                           a.name          AS agent_name
                    FROM node_agents na
                    JOIN agents a ON a.id = na.hub_agent_id
                    JOIN agent_skills sk ON sk.agent_id = na.hub_agent_id
                    WHERE a.shift_state IN ('active', 'deployed')
                      AND a.worker_type = 'ai'
                      AND na.node_id IN (
                          SELECT id FROM remote_nodes
                          WHERE last_heartbeat > NOW() - INTERVAL '2 minutes'
                      )
                """
                )
                assignments = cur.fetchall() or []

            upsert_rows = []
            for row in assignments:
                agent_id = row["agent_id"]
                node_id = row["node_id"]
                capability = row["capability"]

                cfg = resolve_config(all_configs, agent_id, capability, node_id)
                # Cast any Decimal DB values to float so arithmetic doesn't crash
                cfg = {
                    k: float(v) if hasattr(v, "__float__") and not isinstance(v, (bool, int)) else v
                    for k, v in cfg.items()
                }
                if not cfg.get("overflow_enabled", True):
                    continue

                score = compute_overflow_score(
                    idle_minutes=agent_idle.get(agent_id, 999),
                    util_pct=node_util.get(node_id, 100.0),
                    queue_depth=queue_depths.get(capability, 0),
                    config=cfg,
                )
                paused = cfg.get("overflow_paused", False)
                is_active = (score >= 0.5) and not paused

                upsert_rows.append(
                    {
                        "agent_id": agent_id,
                        "capability": capability,
                        "overflow_score": score,
                        "is_active": is_active,
                        "node_id": node_id,
                        "reason": {
                            "idle_mins": round(agent_idle.get(agent_id, 999), 1),
                            "util_pct": round(node_util.get(node_id, 100), 1),
                            "queue_depth": queue_depths.get(capability, 0),
                            "paused": paused,
                        },
                    }
                )

            if upsert_rows:
                with get_db_cursor(commit=True) as (_, cur):
                    for r in upsert_rows:
                        cur.execute(
                            "SELECT is_active FROM agent_overflow_state " "WHERE agent_id=%s AND capability=%s",
                            (r["agent_id"], r["capability"]),
                        )
                        prev = cur.fetchone()
                        was_active = prev["is_active"] if prev else False

                        cur.execute(
                            """
                            INSERT INTO agent_overflow_state
                                (agent_id, capability, overflow_score, is_active,
                                 activated_at, expires_at, node_id, reason, updated_at)
                            VALUES (%s, %s, %s, %s,
                                CASE WHEN %s THEN NOW() ELSE NULL END,
                                NOW() + INTERVAL '90 seconds',
                                %s, %s::jsonb, NOW())
                            ON CONFLICT (agent_id, capability) DO UPDATE SET
                                overflow_score = EXCLUDED.overflow_score,
                                is_active      = EXCLUDED.is_active,
                                activated_at   = CASE
                                    WHEN EXCLUDED.is_active
                                     AND NOT agent_overflow_state.is_active
                                    THEN NOW()
                                    ELSE agent_overflow_state.activated_at END,
                                expires_at     = EXCLUDED.expires_at,
                                node_id        = EXCLUDED.node_id,
                                reason         = EXCLUDED.reason,
                                updated_at     = NOW()
                        """,
                            (
                                r["agent_id"],
                                r["capability"],
                                r["overflow_score"],
                                r["is_active"],
                                r["is_active"],
                                r["node_id"],
                                _json.dumps(r["reason"]),
                            ),
                        )
                        if r["is_active"] and not was_active:
                            newly_activated += 1

            # Always clean up expired rows, even on empty cycles
            with get_db_cursor(commit=True) as (_, cur):
                cur.execute("DELETE FROM agent_overflow_state WHERE expires_at < NOW()")

            update_overflow_cache(upsert_rows)

            elapsed_ms = int((_time.monotonic() - cycle_start) * 1000)
            active_count = sum(1 for r in upsert_rows if r["is_active"])
            logger.info(
                "[ClusterOrchestration] scored=%d active=%d activated=%d elapsed=%dms",
                len(upsert_rows),
                active_count,
                newly_activated,
                elapsed_ms,
            )

            if newly_activated >= 5:
                try:
                    from services.telegram_service import send_info

                    caps = len({r["capability"] for r in upsert_rows if r["is_active"]})
                    send_info(f"Cluster overflow activated: {newly_activated} agents " f"across {caps} capabilities")
                except Exception:
                    pass

        except Exception as exc:
            logger.error("[ClusterOrchestration] crashed: %s", exc)

    # Expose for manual /trigger endpoint (used by fleet_orchestration_routes.py)
    _run_cluster_orchestration_worker_fn = _run_cluster_orchestration_worker

    scheduler.add_job(
        with_ctx(_run_cluster_orchestration_worker),
        trigger=CronTrigger(second="0", timezone="America/Toronto"),
        id="cluster_orchestration_worker",
        name="Cluster Orchestration — elastic agent dispatch (Project #352)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered cluster_orchestration_worker (every 60s)")

    logger.info("[DeptHQ] Registered 12 code health/audit jobs")
