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
  - daily_code_health_static_audit — THE persistent local_static_analysis scan (#5881)
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
    # #5339: 107 of 107 failing rows recorded NO reason. Resolve it here rather
    # than at 186 call sites — most are inside an `except`, so the exception is
    # still live in sys.exc_info(). An explicit caller message always wins.
    #
    # GUARDED because this runs on the LOGGING path of every job. Not every caller
    # reaches _log_cycle with platform_v2 on sys.path — fleet_jobs inserts it
    # explicitly before its own service imports — and an ImportError here would
    # turn a LOGGED failure into an UNLOGGED crash, strictly worse than the bug
    # being fixed. F.O.R.G.E. flagged exactly this on PR #2546 and was right.
    try:
        from services.loop_log import explain_failure

        error_message = explain_failure(status, items_failed, error_message, details)
    except Exception:  # noqa: BLE001 — the resolver must never break logging
        pass
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
                from services.director_report_service import submit_via_inbox as _forge_inbox

                _forge_inbox(
                    category="system",
                    title="Weekly Repair Cycle Complete",
                    message=(
                        f"Modules audited: {audited} ({clean} clean, {violations} violations)\n"
                        f"Severity: {severity_totals['red']} red, {severity_totals['yellow']} yellow, {severity_totals['info']} info\n"
                        f"Proposals: {total_proposals} created, {total_dispatched} dispatched"
                    ),
                    source_agent="F.O.R.G.E.",
                    severity="info",
                    department="Engineering & Technology",
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


def daily_code_health_static_audit():
    """THE persistent local_static_analysis audit for the Code Health tab (#5881).

    Calls `_audit_one()` per module — the SAME write path
    (`services.code_metrics_service.audit_single_module` -> `log_audit(...,
    dispatched_via="local_static_analysis")`) that the manual "Audit All" button
    uses in tools.consciousness.code_health_routes. Byte-identical code path means
    pressing that button between runs of this job can never move the numbers the
    tab shows — scheduled and manual are the same computation against the same
    (unchanged) code.

    Deliberately separate from `daily_code_metrics_scan` (Job #40) and
    `automated_module_audit` (Job #58), which keep running and keep writing
    dispatched_via="F.O.R.G.E." — the owner's decision (2026-08-21) was to keep
    that stream, but separate + labelled, never blended into the headline count.
    """
    start = time.time()
    try:
        from services.code_metrics_service import scan_codebase
        from tools.consciousness.code_health_routes import _audit_one

        metrics = scan_codebase()
        all_modules = metrics.get("modules", {})
        audited = 0
        failed = 0
        for key, mod_data in all_modules.items():
            try:
                _audit_one(key, mod_data)
                audited += 1
            except Exception as audit_err:
                failed += 1
                logger.warning("Static audit failed for %s: %s", key, audit_err)
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("code_health_static_audit", audited, failed, duration_ms)
    except Exception as e:
        _log_cycle(
            "code_health_static_audit",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )
        logger.warning(f"Code health static audit failed: {e}")


def _autoheal_enabled():
    from services.work_control_service import is_enabled

    return is_enabled("agent_code_health_autoheal", default=False)


def _run_autoheal():
    from services.code_health_autoheal import run_autoheal_cycle

    return run_autoheal_cycle(target="platform", max_fixes=10)


def code_health_autoheal_job():
    """Autonomous Code Health heal cycle: static deep scan -> auto-verify gate
    -> Repair Bay proposals -> DHQ fix dispatch (F.O.R.G.E./V.I.G.I.L.) ->
    static reverify. Deploy stays HUMAN-GATED. DEFAULT OFF — toggle the
    work-control key 'agent_code_health_autoheal' in the Autonomy tab."""
    if not _autoheal_enabled():
        return
    start = time.time()
    try:
        summary = _run_autoheal() or {}
        logger.info("[CodeHealthAutoheal] cycle summary: %s", summary)
        _log_cycle("code_health_autoheal", 1, 0, int((time.time() - start) * 1000))
    except Exception as e:
        logger.warning(f"Code health autoheal failed: {e}")
        _log_cycle(
            "code_health_autoheal",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )


def _drain_int_setting(key, default):
    """Read an int tunable from platform_settings (no-deploy retunable). Floors at 1."""
    from database import get_db_cursor

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if row and row["value"] not in (None, ""):
            return max(1, int(row["value"]))
    except Exception:
        logger.warning("code_health drain: bad/missing setting %s, using default %s", key, default)
    return default


def code_health_reconcile_job():
    """Close Code-Health findings whose problem provably no longer exists (#5004).

    Runs BOTH reconcilers, because the two tables feed different consumers and BOTH were
    drifting:
      * code_issues            — what the engine pulls work from
      * improvement_proposals  — what the Consciousness > Code Health "Department
                                 Orchestration" panel and the Repair Bay drain read

    Without this, a finding fixed by ANY route (engine PR, human PR, unrelated refactor)
    stays open forever: nothing writes back. code_issues had not been reconciled in over two
    months, and 331 of 1307 approved proposals described problems that no longer existed —
    so the drain kept generating fixes for dead findings and the panel kept showing them.

    SAFE BY CONSTRUCTION — it only closes what it can DISPROVE against the file on disk.
    Unreadable, unparseable, or no-deterministic-checker all leave the row untouched, and a
    second run finds nothing (idempotent). Archived proposals drop out of the drain's
    WHERE status IN ('pending','approved','fix_requested') automatically, so this REDUCES
    wasted fix-generation rather than interfering with it.

    Work-control key 'code_health_reconcile' (default ON — it is read-mostly and reversible:
    every row it touches is stamped archived_by='reconciler_5004' / fixed_by='reconciler').
    """
    from services.work_control_service import is_enabled

    if not is_enabled("code_health_reconcile", default=True):
        logger.info("code_health_reconcile: disabled via work-control — skipping")
        return {"skipped": True}

    from services.code_issue_reconciler import reconcile_open_issues, reconcile_open_proposals

    out = {}
    try:
        out["issues"] = reconcile_open_issues(limit=3000, dry_run=False)
    except Exception as exc:
        logger.warning("code_health_reconcile: issue pass failed: %s", exc)
        out["issues"] = {"error": str(exc)}
    try:
        # ready_for_review included since 2026-08-28: a built-but-undeployed fix whose
        # finding another PR already resolved (the #2896 twin shape) was invisible to
        # the approved-only default — it kept a live deploy_approve card that could
        # only ever fail the sandbox gate with "patch does not apply".
        out["proposals"] = reconcile_open_proposals(
            limit=3000, dry_run=False, statuses=("approved", "ready_for_review")
        )
    except Exception as exc:
        logger.warning("code_health_reconcile: proposal pass failed: %s", exc)
        out["proposals"] = {"error": str(exc)}

    logger.info(
        "code_health_reconcile: closed %s issue(s), archived %s proposal(s)",
        (out.get("issues") or {}).get("closed", "?"),
        (out.get("proposals") or {}).get("archived", "?"),
    )
    return out


def hub_deploy_state_monitor_job():
    """'Advise when to deploy' (spec 2026-08-26 §6.5): watch the volume-mounted hub tree.

    deploy_drift_monitor covers the 9 image-baked products; NOTHING watched the hub
    half — a merged fix that never got checkout+restart is the #2718 trap, and with
    ship_as_pr every repair now ends in a merge that needs exactly that. ADVISORY
    ONLY: nothing restarts automatically. Dedup'd on a state fingerprint so a
    standing condition pages once, not every 30 minutes.
    Toggle: work-control key 'hub_deploy_advisor' (default ON)."""
    from services.work_control_service import is_enabled

    if not is_enabled("hub_deploy_advisor", default=True):
        return
    try:
        from services.hub_deploy_state import hub_deploy_state

        state = hub_deploy_state()
    except Exception as e:
        logger.warning("hub_deploy_state_monitor: state read failed: %s", e)
        return
    status = state.get("status")
    if status not in ("needs_pull", "needs_restart"):
        return
    fingerprint = f"{status}:{str(state.get('head_sha', ''))[:9]}:{state.get('behind_main', '')}"
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = 'deploy:advisory:last'")
            row = cur.fetchone()
            if row and row["value"] == fingerprint:
                return  # standing condition already advised — page once, not every 30 min
            cur.execute(
                """INSERT INTO platform_settings (key, value, description)
                   VALUES ('deploy:advisory:last', %s, 'hub deploy-advisory dedup fingerprint')
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
                (fingerprint,),
            )
    except Exception as e:
        logger.warning("hub_deploy_state_monitor dedup failed (alerting anyway): %s", e)
    try:
        from services.telegram_service import send_system

        send_system(
            f"Hub deploy advised: {status}",
            "The hub working tree has merged changes not yet running "
            f"(behind_main={state.get('behind_main')}; warnings={'; '.join(state.get('warnings') or []) or 'none'}). "
            "Apply: git checkout main && git pull --ff-only, then restart archie_platform/archie_scheduler "
            "outside review windows.",
        )
    except Exception as e:
        logger.warning("hub_deploy_state_monitor alert failed: %s", e)


def gpu_state_monitor_job():
    """GPU/Xid watchdog (#5273 / #6106): an Xid 79 'fallen off the bus' hid as
    'the hub is slow' for 8 days once (#5595) and again on 2026-08-28. Reads the
    per-card telemetry file the host exporter writes (the SAME file
    model_service.get_gpu_fit_budget places against) and pages on:

      * STALE/MISSING file — the exporter died; placement silently fell back to
        the worst-case budget. Unmonitored-while-appearing-monitored guard.
      * recent NVRM Xid lines — a card is failing, not slow. Deliberately NOT
        alarming on an idle/empty card: empty GPUs are a resting state.
      * fewer cards than expected (a card fell off the bus entirely).

    Advisory only; dedup'd on a condition fingerprint so a standing condition
    pages once. Toggle: work-control key 'gpu_state_monitor' (default ON)."""
    from services.work_control_service import is_enabled

    if not is_enabled("gpu_state_monitor", default=True):
        return
    import json as _json
    import os as _os
    import time as _time

    expected_cards = int(_os.getenv("ARCHIE_GPU_EXPECTED_CARDS", "2"))
    path = _os.getenv("ARCHIE_GPU_STATE_PATH", "/app/.runtime/gpu_state.json")
    condition = None
    detail = ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = _json.load(fh)
        age_s = _time.time() - float(state.get("ts") or 0)
        cards = state.get("cards") or []
        xid = int(state.get("xid_recent") or 0)
        if age_s > 600:
            condition = "stale"
            detail = f"telemetry {age_s/60:.0f} min old — exporter dead; placement is on the worst-case fallback"
        elif xid > 0:
            condition = "xid"
            detail = f"{xid} NVRM Xid line(s) in the kernel journal (10-min window) — a GPU is FAILING, not slow"
        elif len(cards) < expected_cards:
            condition = "cards"
            detail = f"only {len(cards)}/{expected_cards} GPUs visible to nvidia-smi"
    except (OSError, ValueError, TypeError):
        condition = "missing"
        detail = f"{path} unreadable — exporter not installed or dead; placement is on the worst-case fallback"
    if not condition:
        return
    fingerprint = f"{condition}:{detail[:60]}"
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = 'gpu_state:advisory:last'")
            row = cur.fetchone()
            if row and row["value"] == fingerprint:
                return
            cur.execute(
                """INSERT INTO platform_settings (key, value, description)
                   VALUES ('gpu_state:advisory:last', %s, 'gpu_state_monitor dedup fingerprint')
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
                (fingerprint,),
            )
    except Exception as e:
        logger.warning("gpu_state_monitor dedup failed (alerting anyway): %s", e)
    try:
        from services.telegram_service import send_system

        send_system(f"GPU watchdog: {condition}", detail)
    except Exception as e:
        logger.warning("gpu_state_monitor alert failed: %s", e)


def code_health_reverify_job():
    """Daily loop closure: re-audit deployed proposals INDEPENDENTLY of audit-all.

    Before this job, reverified stamps rode only on the audit-all tail — if that
    stalled, verdicts silently froze (last 'fixed' was 2026-06-02 while deploys
    continued into August; KB #296234). Also the FIRST consumer of still_open:
    growth means shipped fixes are not removing their findings — alert, dedup'd
    on the count so a standing backlog pages once, not daily.
    Toggle: work-control key 'code_health_reverify' (default ON)."""
    from services.work_control_service import is_enabled

    if not is_enabled("code_health_reverify", default=True):
        return
    try:
        from services.audit_pipeline import reverify_deployed_findings

        reverify_deployed_findings()
    except Exception as e:
        logger.warning("code_health_reverify: reverify pass failed: %s", e)
        return
    try:
        from database import get_db_cursor
        from services.telegram_service import send_system

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "SELECT count(*) AS n FROM improvement_proposals "
                "WHERE status = 'deployed' AND metadata->>'reverified' = 'still_open'"
            )
            n = int(cur.fetchone()["n"])
            cur.execute("SELECT value FROM platform_settings WHERE key = 'code_health:reverify:last_still_open'")
            row = cur.fetchone()
            prev = int(row["value"]) if row and str(row["value"]).isdigit() else n
            cur.execute(
                """INSERT INTO platform_settings (key, value, description)
                   VALUES ('code_health:reverify:last_still_open', %s,
                           'still_open count at last reverify run (growth-alert dedup)')
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
                (str(n),),
            )
        if n > prev:
            send_system(
                f"Code Health re-verify: still_open grew to {n}",
                f"{n - prev} deployed fix(es) did not remove their finding (was {prev}). "
                "Repair Bay → Repairs lists the affected proposals.",
            )
    except Exception as e:
        logger.warning("code_health_reverify still_open alert failed: %s", e)


def code_health_backlog_drain_job():
    """Frequent, welfare-gated drain of the STANDING Code Health fix backlog.

    Complements the daily autoheal (which scans + dispatches fixes ONLY when its
    scan finds NEW issues): this works down the standing undispatched
    code_health proposal backlog every few hours, regardless of new-issue
    discovery. Fix GENERATION only — deploy stays HUMAN-GATED (results land in
    ready_for_review); every dispatch is welfare-gated (resting agents defer).
    DEFAULT OFF — work-control key 'code_health_backlog_drain'. Batch size
    tunable via platform_settings 'work:code_health_backlog_drain:max_fixes'
    (default 15)."""
    from services.work_control_service import is_enabled

    if not is_enabled("code_health_backlog_drain", default=False):
        return
    start = time.time()
    try:
        from services.audit_pipeline import dispatch_audit_proposals, archive_unfixable_audit_proposals

        # Autonomy: self-prune unfixable-path proposals BEFORE draining so the batch
        # never spends a slot on a target whose file no longer resolves. This is the
        # ONLY scheduled caller of the #4940 sweep (it previously ran only by hand).
        # Idempotent + reversible (archived_by='scope_filter_4940'); non-blocking.
        try:
            pruned = archive_unfixable_audit_proposals() or {}
            if pruned.get("archived"):
                logger.info("[CodeHealthBacklogDrain] pre-drain scope prune: %s", pruned)
        except Exception as _pe:
            logger.warning("pre-drain scope prune failed (non-blocking): %s", _pe)

        # DETERMINISTIC PASS FIRST (#4989 yield). Mechanical findings — an unused import on a
        # single-name line, an f-string with no placeholders — are single-line edits with
        # nothing for a model to decide. Sending them to the 7B is what produced a 0% drain:
        # every 2026-07-20 attempt died on find_not_located / find_ambiguous, i.e. the model's
        # FIND text not matching the file. Doing the edit directly and verifying with pyflakes
        # turned the same pool into 109 verified fixes.
        #
        # Runs BEFORE dispatch_audit_proposals so those proposals are already ready_for_review
        # and the LLM batch spends its slots on findings that actually need judgement.
        # Non-blocking: a failure here must not stop the existing drain.
        try:
            from services.deterministic_fixer import run_deterministic_fixes

            det_limit = _drain_int_setting("work:code_health_backlog_drain:deterministic_max", 100)
            # Queue a BOUNDED number of the verified fixes into the tiered approval pipeline so
            # they reach the Approvals tab + Telegram like every other human request, instead of
            # waiting on a manual Ship-tab click. Bounded because the backlog is ~109 deep and a
            # wall of prompts is worse than none. Tunable without a deploy.
            # Fixes are forced to TIER 2 (Telegram approval), never F.O.R.G.E. auto-approve —
            # owner decision 2026-07-20. Nothing deploys without a human tap, so a low positive
            # default is safe. Kept small because each one is a Telegram prompt: the 100+ backlog
            # drains at a reviewable rate instead of arriving as a wall. Tune without a deploy.
            det_approve = _drain_int_setting("work:code_health_backlog_drain:approval_max", 3)
            det = run_deterministic_fixes(limit=det_limit, dry_run=False, approval_max=det_approve) or {}
            if det.get("offered"):
                logger.info(
                    "[CodeHealthBacklogDrain] deterministic pass: %s offered, %s rejected by verification",
                    det.get("offered"),
                    det.get("rejected"),
                )
        except Exception as _de:
            logger.warning("deterministic fix pass failed (non-blocking): %s", _de)

        max_fixes = _drain_int_setting("work:code_health_backlog_drain:max_fixes", 15)
        # #6099 AUX POWER: while the operator has PLATFORM focus armed on repair_bay,
        # widen the drain batch — "full power to Repair Bay" should move fix THROUGHPUT,
        # not just queue order. Own key so the boost is tunable without touching the
        # everyday cap; focus_active is fail-safe False, so a config/DB hiccup can never
        # leave the boost stuck on. Deploy stays human-gated regardless of batch size.
        try:
            from services.fleet_dispatch_profile import focus_active

            if focus_active("repair_bay"):
                max_fixes = _drain_int_setting("work:code_health_backlog_drain:focus_max_fixes", max_fixes * 2)
        except Exception as _fe:
            logger.warning("focus boost check failed (non-blocking): %s", _fe)
        result = dispatch_audit_proposals(limit=max_fixes) or {}
        logger.info("[CodeHealthBacklogDrain] %s (max_fixes=%s)", result, max_fixes)
        _log_cycle(
            "code_health_backlog_drain",
            int(result.get("dispatched", 0)),
            int(result.get("failed", 0)),
            int((time.time() - start) * 1000),
            details=result,
        )
    except Exception as e:
        logger.warning("Code health backlog drain failed: %s", e)
        _log_cycle(
            "code_health_backlog_drain",
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


def job_recovery_reaper():
    """#1716 — mark stale 'running' bridge_jobs 'interrupted' (worker-crash recovery)."""
    try:
        from database import get_db_cursor
        from services.job_recovery_service import reap_stale_running

        with get_db_cursor(commit=True) as (_, cur):
            n = reap_stale_running(cur, max_age_min=20)
        if n:
            logger.info("job_recovery_reaper: marked %d stale running job(s) interrupted", n)
    except Exception:
        logger.exception("job_recovery_reaper failed")


def dispatch_retention_prune():
    """#4542 — nightly prune of OLD TERMINAL bridge_jobs + dispatch_pending_queue rows.

    Pure DB maintenance (no LLM/dispatch). Opens its own cursor; the service is
    fail-safe (allowlist statuses, batched commits, tunable via platform_settings)."""
    try:
        from services.dispatch_retention_service import run_retention

        res = run_retention(dry_run=False)
        deleted = res.get("deleted") or {}
        if res.get("enabled") and any(deleted.values()):
            logger.info(
                "dispatch_retention_prune: deleted %s",
                ", ".join(f"{t}={n}" for t, n in deleted.items()),
            )
    except Exception:
        logger.exception("dispatch_retention_prune failed")


def family_research_worker(flask_app=None):
    """#5343 (#5211): scheduled drain for family_research_queue.

    Users queue research per person (Family Tree → Start Research), but the only
    thing that ever ran a search was nothing — the queue had a compliant dispatch
    path and NO scheduled consumer. Claims a couple of 'queued' rows per cycle,
    runs the existing non-LLM search_all_sources() (8 external genealogy/archive
    APIs), stores the combined matches, and moves the row to 'found_matches' /
    'no_results' per the table's CHECK vocabulary. The LLM analyze step stays
    user-triggered (S.C.R.O.L.L. via the /analyze route). Toggle: work_control
    'family_research'.
    """
    from services.work_control_service import is_enabled

    if not is_enabled("family_research", default=True):
        return
    from database import get_db_cursor
    from psycopg2.extras import Json

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """
            UPDATE family_research_queue
            SET status = 'searching'
            WHERE id IN (
                SELECT id FROM family_research_queue
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 2
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, person_id
            """
        )
        claimed = [dict(r) for r in cur.fetchall()]
    if not claimed:
        return

    from tools.family_tree.services.research_service import search_all_sources

    done = 0
    for row in claimed:
        try:
            with get_db_cursor() as (_c, cur):
                cur.execute(
                    "SELECT first_name, last_name, birth_place FROM family_persons WHERE id = %s",
                    (row["person_id"],),
                )
                p = cur.fetchone()
            if not p:
                raise ValueError(f"person {row['person_id']} not found")
            p = dict(p)
            matches = search_all_sources(
                p.get("first_name") or "",
                p.get("last_name") or "",
                birth_place=p.get("birth_place") or "",
            )
            status = "found_matches" if matches else "no_results"
            top_score = max((m.get("score") or 0 for m in matches), default=None)
            with get_db_cursor(commit=True) as (_c, cur):
                cur.execute(
                    """
                    UPDATE family_research_queue
                    SET status = %s,
                        results = %s,
                        confidence_score = %s,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (status, Json({"matches": matches, "count": len(matches)}), top_score, row["id"]),
                )
            done += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("family_research_worker: entry %s failed: %s", row["id"], exc)
            # 'no_results' with the error recorded — the CHECK vocabulary has no
            # 'failed'; an honest empty result beats a row stuck in 'searching'.
            with get_db_cursor(commit=True) as (_c, cur):
                cur.execute(
                    """
                    UPDATE family_research_queue
                    SET status = 'no_results',
                        results = COALESCE(results, '{}'::jsonb) || %s::jsonb,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (Json({"error": str(exc)[:300]}), row["id"]),
                )
    logger.info("[DeptHQ] family_research_worker: processed %d/%d claimed entr(ies)", done, len(claimed))


def platform_registry_collect(flask_app=None, scheduler=None):
    """Nightly Living Platform Registry collection (#5230).

    Deliberately thin: all logic lives in platform_registry_service so it is
    testable without a scheduler. Never raises — an unattended job that dies
    takes the whole scheduler tick with it.
    """
    try:
        from services.platform_registry_service import run_registry_collection

        res = run_registry_collection(with_provenance=True)
        logger.info(
            "[registry] collection done ok=%s vanished=%s errors=%s",
            res.get("ok"),
            res.get("vanished"),
            list(res.get("errors") or {}),
        )
        return res
    except Exception as exc:  # noqa: BLE001
        logger.exception("[registry] collection job failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def maintenance_window_driver(flask_app=None, scheduler=None):
    """Drive scheduled maintenance windows: announce -> open -> close (#5217/#5235).

    The services existed and were tested but NOTHING CALLED THEM — the same
    "built but not wired" gap that #5226 closed for the maintenance splash. A
    window that no job advances is a window that never happens.

    ORDER IS DELIBERATE AND SAFETY-DRIVEN.

    CLOSE RUNS FIRST. An OPEN window suppresses the DR watchdog. A window that
    never closes leaves DR disarmed indefinitely — strictly worse than never
    having opened one, because the operator believes DR is armed. So expiry is
    swept before anything else, and a failure in the announce/open steps below
    can never prevent it.

    NEVER AUTO-OPENS AN UNANNOUNCED WINDOW. The owner's directive was to
    "advise and coordinate before, and let me know before the maintenance the fix
    list". open_scheduled() enforces that via force_unannounced, and this job
    NEVER passes it. A window that reaches its start time still un-announced is
    announced and left for the next tick rather than opened silently — one tick
    late beats an unannounced production change.

    Every step is independently guarded: one bad window must not stop the others,
    and the job never raises into the scheduler.
    """
    import os
    from datetime import timedelta

    from services.time_utils import now_utc

    result = {"closed": [], "announced": [], "opened": [], "errors": []}
    try:
        from services import maintenance_schedule_service as mss
    except Exception as exc:  # noqa: BLE001
        logger.warning("[maintenance] schedule service unavailable: %s", exc)
        return {"ok": False, "error": str(exc)}

    now = now_utc()
    lead_min = int(os.environ.get("MAINTENANCE_ANNOUNCE_LEAD_MIN", "60"))

    # ---- 1. CLOSE expired windows FIRST (releases DR suppression) ----
    try:
        for w in mss.list_windows(status="open", limit=50):
            start = w.get("scheduled_start")
            dur = int(w.get("duration_minutes") or 0)
            if not start or not dur:
                continue
            if now >= start + timedelta(minutes=dur):
                try:
                    mss.close_scheduled(w["id"])
                    result["closed"].append(w["id"])
                    logger.info("[maintenance] window %s expired -> closed (DR suppression released)", w["id"])
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append(f"close {w['id']}: {exc}")
                    logger.exception(
                        "[maintenance] FAILED to close expired window %s — DR may stay suppressed", w["id"]
                    )
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"close sweep: {exc}")

    # ---- 2. ANNOUNCE windows starting soon (planned -> announced) ----
    try:
        for w in mss.list_windows(status="planned", limit=50):
            start = w.get("scheduled_start")
            if start and now >= start - timedelta(minutes=lead_min):
                try:
                    r = mss.announce_plan(w["id"])
                    if r.get("ok"):
                        result["announced"].append(w["id"])
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append(f"announce {w['id']}: {exc}")
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"announce sweep: {exc}")

    # ---- 3. OPEN announced windows whose start has arrived ----
    try:
        for w in mss.list_windows(status="announced", limit=50):
            start = w.get("scheduled_start")
            if start and now >= start:
                try:
                    # force_unannounced is NEVER passed — see docstring.
                    r = mss.open_scheduled(w["id"])
                    if r.get("ok"):
                        result["opened"].append(w["id"])
                    else:
                        result["errors"].append(f"open {w['id']}: {r.get('error')}")
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append(f"open {w['id']}: {exc}")
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"open sweep: {exc}")

    if any(result[k] for k in ("closed", "announced", "opened")) or result["errors"]:
        logger.info("[maintenance] driver: %s", result)
    return result


def proposer_draft():
    """Draft a proposed manifest for the owner (#380 Task 5). Never opens a window.

    dry_run=True deliberately: until the Plan 3 cockpit review screen exists there is
    nowhere to review a real window, and creating unreviewable windows is how
    maintenance_windows fills with noise. Flip to dry_run=False in Plan 3, in the
    same PR that adds the review screen.
    """
    from services.proposer_service import propose_manifest

    lane_prefixes = {
        "codex": (
            "platform_v2/tools/fitness/",
            "platform_v2/tools/therapy/",
            "platform_v2/tools/faith/",
            "platform_v2/tools/brainstorm/",
            "platform_v2/tools/doc/",
            "platform_v2/tools/family_tree/",
        ),
        "engine": ("platform_v2/", "ai_bridge/", "scripts/", "docs/"),
    }
    return propose_manifest(lane_prefixes, repo="KytranKatarn/archie-platform", dry_run=True)


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


def signal_group_image_retry():
    """#4649 — weekly headed retry of the WTF group cover/logo replace.

    ROOT CAUSE (KB #277261): LinkedIn's group-update PATCH silently 422s image
    REPLACEMENT whenever the group already has images (fresh-set works, the UI
    swallows the error). Their flow may get fixed any week, so this calls the
    login sidecar's headed-task endpoint weekly, Telegram-notifies the owner
    on success, and self-disables. Silent on the expected 422 (log only).
    Toggle: Autonomy tab (work:signal_group_image_retry:enabled). State keys:
    signal:group_images:fixed ('true'|'gave_up'), signal:group_images:retry_count.
    """
    import os

    import requests

    from database import get_db_cursor
    from services.work_control_service import is_enabled

    if not is_enabled("signal_group_image_retry", default=True):
        return

    def _get(key, default=""):
        with get_db_cursor() as (_conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if not row:
            return default
        return row["value"] if isinstance(row, dict) else row[0]

    def _set(key, value, desc):
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                   VALUES (%s, %s, 'string', %s, NOW())
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
                (key, value, desc),
            )

    state = _get("signal:group_images:fixed")
    if state in ("true", "gave_up"):
        return
    count = int(_get("signal:group_images:retry_count", "0") or 0)

    try:
        resp = requests.post(
            "http://archie_browser_login:4281/group-image-retry",
            json={},  # sidecar defaults: WTF group + staged /profiles assets
            headers={"Authorization": f"Bearer {os.getenv('INTERNAL_API_KEY', '')}"},
            timeout=300,
        )
        result = resp.json() if resp.ok else {"error": f"http {resp.status_code}"}
    except Exception as e:
        logger.warning("[GroupImageRetry] sidecar call failed: %s", e)
        return

    _set("signal:group_images:retry_count", str(count + 1), "weekly WTF group image retry attempts (#4649)")
    if result.get("fixed"):
        _set("signal:group_images:fixed", "true", "WTF group cover+logo committed (#4649)")
        try:
            from services.telegram_service import send_info

            send_info(
                "🖼️ WTF group images fixed",
                "LinkedIn accepted the cover+logo replace "
                f"on weekly retry #{count + 1}. Check linkedin.com/groups/37040054/. "
                "The weekly retry job has self-disabled.",
            )
        except Exception:
            pass
        logger.info("[GroupImageRetry] SUCCESS on attempt %d — self-disabled", count + 1)
    else:
        logger.info(
            "[GroupImageRetry] attempt %d: cover=%s logo=%s (422 = LinkedIn still rejects replace)",
            count + 1,
            result.get("cover_status"),
            result.get("logo_status"),
        )
        if count + 1 >= 12:
            _set("signal:group_images:fixed", "gave_up", "12 weekly retries exhausted (#4649)")
            try:
                from services.telegram_service import send_info

                send_info(
                    "🖼️ WTF group image retry gave up",
                    "Weekly retry giving up after 12 attempts — "
                    "LinkedIn still 422s the replace. Fix via mobile app or re-enable "
                    "by clearing platform_settings signal:group_images:fixed.",
                )
            except Exception:
                pass


def _planner_node_fits(node: dict, model: str) -> bool:
    """Can *node* actually hold *model*? Diagnostic-grade wrapper for the planner.

    Delegates to the SAME predicate BridgeDispatcher routes on
    (fleet_resource_router.can_node_run_model), so the planner's hint and the
    dispatcher's decision cannot drift apart.

    FAIL-OPEN on purpose. This only decorates a log line — the planner writes
    priorities, never node assignments. A capacity lookup that raises must never
    take the queue planner down; a slightly optimistic hint is the cheaper failure.

    Context: an UNFILTERED hint printed gpu_fleet[0] for every model, so it claimed
    "gemma3:12b -> GPU fleet (USS-245)" for a 4GB node. On 2026-08-19 that misled an
    operator into capping a node that was serving qwen2.5:7b at 50/50 and 32.4s
    (KB #291799). A diagnostic naming an impossible node is worse than no diagnostic.
    """
    try:
        from services.fleet_resource_router import can_node_run_model

        return bool(can_node_run_model(node, model))
    except Exception:  # pragma: no cover - defensive
        return True


def review_fix_worker():
    """#5934 Phase 3 — close the Review-to-Coder loop (every 15 min).

    Drains the human-created pr_review_finding fix requests (Phase 1's send-back
    button is the ONLY producer, so every row here was explicitly authorised by a
    human click): one PR per cycle, fixes committed to the PR's OWN branch, then a
    diff-grounded re-review. 2 failed attempts per finding -> Telegram escalation.
    Never merges anything — the governance gate stays exactly as-is.
    Toggle: work-control key 'review_fix_loop' (default ON — human-initiated rows only)."""
    from services.work_control_service import is_enabled

    if not is_enabled("review_fix_loop", default=True):
        return
    try:
        from tools.repair_bay.services.review_fix_service import run_review_fix_cycle

        result = run_review_fix_cycle()
    except Exception as e:
        logger.warning("review_fix_worker failed: %s", e)
        return
    if result.get("prs_processed") or result.get("escalated"):
        logger.info("[review_fix_worker] %s", result)


def _register_own_jobs(scheduler, flask_app):
    """Register Department HQ's own background jobs with the scheduler."""
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    from services.job_governance import governed_job

    def with_ctx(fn):
        """Wrap a DHQ job so it runs inside the Flask app context AND under DHQ
        governance (project #332, #2743): every run writes a governance_audit_log
        trail (start/complete/fail) and a failure raises a quiet-hours-gated
        A.R.C.H.I.E. alert. Additive + fail-safe — never changes a job's logic and
        never crashes the shared scheduler. NOTE: with_ctx_app / with_ctx_app_sched
        pass args to fn and are intentionally left un-governed here (they need an
        arg-passing governed_job variant — tracked follow-up)."""
        return governed_job(fn, department="Department HQ", flask_app=flask_app)

    def with_ctx_app(fn):
        """Governed variant of with_ctx for a job registered as fn(flask_app)
        (project #332, #4791): app context + governance_audit_log trail +
        quiet-hours-gated failure alert. Additive + fail-safe."""
        return governed_job(fn, department="Department HQ", flask_app=flask_app, fn_args=(flask_app,))

    def with_ctx_app_sched(fn):
        """Governed variant of with_ctx for a job registered as fn(flask_app, scheduler)
        (project #332, #4791): app context + governance_audit_log trail +
        quiet-hours-gated failure alert. Additive + fail-safe."""
        return governed_job(fn, department="Department HQ", flask_app=flask_app, fn_args=(flask_app, scheduler))

    # Job #40 — Daily Code Metrics Scan (3:00 AM)
    scheduler.add_job(
        with_ctx(daily_code_metrics_scan),
        trigger=CronTrigger(hour=3, minute=0, timezone="America/Toronto"),
        id="agent_code_metrics",
        name="Agent Loop: Daily Code Metrics Scan",
        replace_existing=True,
    )

    # #5934 — Review-to-Coder loop closer: drains human-created pr_review_finding
    # fix requests (one PR / cycle), commits to the SAME PR branch, re-reviews,
    # escalates after 2 failed attempts. Never merges. Toggle: work:review_fix_loop.
    scheduler.add_job(
        with_ctx(review_fix_worker),
        trigger=CronTrigger(minute="*/15", timezone="America/Toronto"),
        id="review_fix_worker",
        name="Repair Bay: Review-Fix Loop (#5934)",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # #4649 — Weekly WTF group image retry (Mon 07:30 ET; self-disables on
    # success or after 12 attempts — LinkedIn 422s image REPLACE, KB #277261)
    scheduler.add_job(
        with_ctx(signal_group_image_retry),
        trigger=CronTrigger(day_of_week="mon", hour=7, minute=30, timezone="America/Toronto"),
        id="signal_group_image_retry",
        name="S.I.G.N.A.L.: Weekly WTF group image retry",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # #5230 — Living Platform Registry collection (nightly 03:40 ET).
    # Derives modules / services / skills from LIVE sources and appends a change
    # feed, so the docs an agent reads at boot cannot quietly rot. Alarms only on
    # a DISAPPEARANCE — appearances and field edits are normal churn; a vanished
    # entry is the thing nobody notices (the `backups` phantom-table class).
    # Provenance is measured on this nightly pass only (a GitHub call + HTTP fetch
    # per product), never on an ad-hoc run. Toggle: work_control 'platform_registry'.
    scheduler.add_job(
        with_ctx(platform_registry_collect),
        trigger=CronTrigger(hour=3, minute=40, timezone="America/Toronto"),
        id="platform_registry_collect",
        name="Registry: collect modules/services/skills + change feed",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # #5343 (#5211) — family research queue drain (every 15 min). Non-LLM
    # external-archive searches; the LLM analyze step stays user-triggered.
    scheduler.add_job(
        with_ctx(family_research_worker),
        trigger=IntervalTrigger(minutes=15),
        id="family_research_worker",
        name="Family Tree: drain queued research (8-source search)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # #5217/#5235 — drive scheduled maintenance windows every 5 min.
    # CLOSE runs first inside the job: an open window suppresses the DR watchdog,
    # so a window that never closes leaves DR disarmed while the operator believes
    # it is armed. Never auto-opens an UNANNOUNCED window — the owner asked to be
    # told the fix list beforehand, and one tick late beats a silent prod change.
    scheduler.add_job(
        with_ctx(maintenance_window_driver),
        trigger=IntervalTrigger(minutes=5),
        id="maintenance_window_driver",
        name="Maintenance: announce/open/close scheduled windows",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # #380 Task 5 — daily proposed-manifest draft (07:00 ET). dry_run=True: never
    # opens a window, just keeps the draft warm so the cockpit is never dormant.
    scheduler.add_job(
        with_ctx(proposer_draft),
        trigger=CronTrigger(hour=7, minute=0, timezone="America/Toronto"),
        id="proposer_draft",
        name="Proposer: draft proposed manifest for owner review",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
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

    # #5881 — THE persistent local_static_analysis scan (2:10 AM, after the 2:00
    # metrics snapshot). Calls the exact same _audit_one() write path as the manual
    # "Audit All" button, so scheduled and manual are byte-comparable and pressing
    # the button can never move the Code Health tab's numbers. Kept separate from
    # the 3:00/3:30 F.O.R.G.E.-labelled jobs below (owner decision 2026-08-21: keep
    # F.O.R.G.E., but separate + labelled — it never sets the headline colour).
    scheduler.add_job(
        with_ctx(daily_code_health_static_audit),
        trigger=CronTrigger(hour=2, minute=10, timezone="America/Toronto"),
        id="code_health_static_audit",
        name="Code Health: persistent local_static_analysis scan (#5881)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Autonomous Code Health heal cycle (02:45 AM — after the 2:00 scan;
    # 03:00/03:15/03:30/03:45 slots are taken). DEFAULT OFF via work-control
    # key 'agent_code_health_autoheal'. Deploy stays human-gated.
    scheduler.add_job(
        with_ctx(code_health_autoheal_job),
        trigger=CronTrigger(hour=2, minute=45, timezone="America/Toronto"),
        id="agent_code_health_autoheal",
        name="Code Health: Autonomous Heal Cycle (static tier)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Code Health BACKLOG DRAIN — frequent, welfare-gated drain of the STANDING
    # fix backlog (decoupled from new-issue discovery — the daily autoheal above
    # only drains when its scan finds NEW issues, so a large existing backlog
    # otherwise barely moves). Fix generation only; deploy stays HUMAN-GATED.
    # DEFAULT OFF via work-control 'code_health_backlog_drain'. Interval tunable
    # via platform_settings 'work:code_health_backlog_drain:interval_hours'
    # (default 3h; read at registration — a change needs a platform restart).
    _ch_drain_interval = _drain_int_setting("work:code_health_backlog_drain:interval_hours", 3)
    scheduler.add_job(
        with_ctx(code_health_backlog_drain_job),
        trigger=IntervalTrigger(hours=_ch_drain_interval),
        id="code_health_backlog_drain",
        name="Code Health: Backlog Drain (fix-gen, welfare-gated)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Code Health RE-VERIFY — daily loop closure (spec 2026-08-26 Phase 1). Before
    # this job the reverify pass rode ONLY on the audit-all tail, so a stalled
    # audit-all silently froze every fixed/still_open verdict while deploys
    # continued (measured: last 'fixed' 2026-06-02, KB #296234). Runs at 04:40 ET,
    # after the 02:00–03:30 scan/audit train. Toggle: 'code_health_reverify'.
    scheduler.add_job(
        with_ctx(code_health_reverify_job),
        trigger=CronTrigger(hour=4, minute=40, timezone="America/Toronto"),
        id="code_health_reverify",
        name="Code Health: Re-verify deployed fixes (loop closure)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Hub deploy advisory — 'advise when to deploy' (spec 2026-08-26 §6.5).
    # Complements deploy_drift_monitor (image-baked products) with the hub's
    # volume-mounted half. Advisory only; dedup'd; toggle 'hub_deploy_advisor'.
    scheduler.add_job(
        with_ctx(hub_deploy_state_monitor_job),
        trigger=IntervalTrigger(minutes=30),
        id="hub_deploy_state_monitor",
        name="Ship: Hub deploy advisory (volume-mounted tree)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # GPU/Xid watchdog (#5273/#6106): pages when a card is FAILING (Xid), lost,
    # or when the per-card telemetry feeding placement goes stale. Never again
    # should a dead GPU read as "the hub is slow" for a week (#5595).
    scheduler.add_job(
        with_ctx(gpu_state_monitor_job),
        trigger=IntervalTrigger(minutes=5),
        id="gpu_state_monitor",
        name="Fleet: GPU per-card/Xid watchdog",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Code Health: stale-finding reconciler (#5004). Re-validates OPEN code_issues against
    # the source on disk and closes the ones that provably no longer reproduce.
    #
    # Why scheduled: without it, a finding fixed by ANY route — an engine PR, a human PR,
    # unrelated refactoring — stays 'open' forever, because nothing writes back. code_issues
    # had not been reconciled in over two months (newest 'resolved' row: 2026-04-21). Run by
    # hand on 2026-07-20 it closed 633 of 2230. Hourly keeps that current instead of
    # depending on someone remembering.
    #
    # Safe to run often: it only CLOSES a finding it can disprove against the file (see
    # code_issue_reconciler — unreadable/unparseable/no-checker all leave the row alone),
    # it is idempotent (a second run finds 0), and it is read-mostly — the UPDATE only fires
    # when something is provably gone. Work-control key 'code_health_reconcile'.
    scheduler.add_job(
        with_ctx(code_health_reconcile_job),
        trigger=IntervalTrigger(hours=1),
        id="code_health_reconcile",
        name="Code Health: Stale-Finding Reconciler",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
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
        with_ctx(daily_recompute_perf_baselines),
        trigger=CronTrigger(hour=3, minute=45, timezone="America/Toronto"),
        id="agent_recompute_perf_baselines",
        name="Agent Loop: Nightly Recompute Perf Baselines",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Job — Interrupted-Job Recovery Reaper (#1716, every 10 min)
    scheduler.add_job(
        with_ctx(job_recovery_reaper),
        trigger=IntervalTrigger(minutes=10),
        id="job_recovery_reaper",
        name="Agent Loop: Interrupted-Job Recovery Reaper",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Job #4542 — Dispatch Retention Prune (4:15 AM — after the nightly job cluster;
    # 03:00/03:15/03:30/03:45/04:00 are taken). Deletes old terminal bridge_jobs +
    # dispatch_pending_queue rows. Tunable / disable-able via platform_settings.
    scheduler.add_job(
        with_ctx(dispatch_retention_prune),
        trigger=CronTrigger(hour=4, minute=15, timezone="America/Toronto"),
        id="dispatch_retention_prune",
        name="Agent Loop: Dispatch Retention Prune",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Job #60 — Daily Backup Retention Cleanup (7:00 AM — after 06:00 shell cron backup)
    def _run_backup_retention_cleanup():
        # Reference pattern for job governance: audit_log + Telegram notification
        import time as _brc_t
        from database import get_db_cursor

        _brc_start = _brc_t.time()
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
            # RETIRED (2026-07-23, #5141). This called cleanup_old_backups(dry_run=False):
            # a SECOND pruner applying a single global 7/4/6 GFS triple to /backups (a symlink
            # to /mnt/data2/backups) — the exact directory the canonical per-(component, tier)
            # engine scripts/backup/retention_prune.py already prunes nightly via
            # backup_triage.sh. Two pruners, different policies, one directory = the
            # competing-pruner anti-pattern the platform retired (#4051). It also read
            # result['deleted_count'] — but the function returns 'deleted' (a list) — so it
            # always reported 0 while silently deleting real restore points. Neutralised to a
            # no-op; retention is handled solely by the nightly canonical engine.
            detail = (
                "Retired — retention handled solely by the nightly canonical engine "
                "(scripts/backup/retention_prune.py). No action taken."
            )
            logger.info("[BackupRetention] %s", detail)
            _audit(f"{job_name}.skipped", detail)
        except Exception as e:
            logger.error("[BackupRetention] Auto-cleanup failed: %s", e)
            _audit(f"{job_name}.failed", str(e)[:500])
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="W.A.R.D.E.N.",
                capability="backup_governance",
                duration_ms=int((_brc_t.time() - _brc_start) * 1000),
            )
        except Exception as _tel:
            logger.debug("[BackupRetention] task_execution_log write failed: %s", _tel)

    scheduler.add_job(
        with_ctx(_run_backup_retention_cleanup),
        trigger=CronTrigger(hour=7, minute=0, timezone="America/Toronto"),
        id="agent_backup_retention_cleanup",
        name="Agent Loop: Daily Backup Retention Cleanup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Daily module backup (#5143) — back up EVERY module once a day so a focused,
    # module-scoped restore is always available without a full-platform snapshot (owner
    # ask 2026-07-23). Per-deploy backup_module() only covers modules that were deployed
    # that day (measured 4/7 days); this guarantees a fresh daily backup for all of them.
    # Runs 03:30 — after the 02:00 triage/run_backup and the 03:00 code-metrics scan.
    # Retention: retention_prune.prune_modules keeps the newest 7 per module (nightly).
    def _run_daily_module_backup():
        import os as _os

        from tools.backup_manager._shared import PLATFORM_DIR, backup_module

        tools_dir = _os.path.join(PLATFORM_DIR, "tools")
        exclude = {"__pycache__", "admin", "_deprecated"}
        try:
            names = sorted(
                d
                for d in _os.listdir(tools_dir)
                if d not in exclude
                and not d.startswith(".")
                and not d.startswith("_")
                and _os.path.isdir(_os.path.join(tools_dir, d))
                and (
                    _os.path.exists(_os.path.join(tools_dir, d, "routes.py"))
                    or _os.path.exists(_os.path.join(tools_dir, d, "__init__.py"))
                )
            )
        except OSError as e:
            logger.error("[DailyModuleBackup] cannot list modules: %s", e)
            return
        ok = fail = 0
        for name in names:
            try:
                res = backup_module(name)
                if res and res.get("success"):
                    ok += 1
                else:
                    fail += 1
                    logger.warning("[DailyModuleBackup] %s failed: %s", name, (res or {}).get("error"))
            except Exception as e:
                fail += 1
                logger.warning("[DailyModuleBackup] %s raised: %s", name, e)
        logger.info("[DailyModuleBackup] done — %d ok, %d failed of %d modules", ok, fail, len(names))

    scheduler.add_job(
        with_ctx(_run_daily_module_backup),
        trigger=CronTrigger(hour=3, minute=30, timezone="America/Toronto"),
        id="daily_module_backup",
        name="Agent Loop: Daily Module Backup (all modules)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Job #61 — F.O.R.G.E. PR Poll (every 4h) — sync open PRs from GitHub into pr_reviews
    def _run_forge_pr_poll():
        import time as _fpp_t

        _fpp_start = _fpp_t.time()
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
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="F.O.R.G.E.",
                capability="code_review",
                duration_ms=int((_fpp_t.time() - _fpp_start) * 1000),
            )
        except Exception as _tel:
            logger.debug("[ForgePRPoll] task_execution_log write failed: %s", _tel)

    scheduler.add_job(
        with_ctx(_run_forge_pr_poll),
        trigger=IntervalTrigger(hours=4),
        id="agent_forge_pr_poll",
        name="Agent Loop: F.O.R.G.E. PR Poll",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Job — Deploy-provenance drift monitor (#4749, KB #279350). Daily: for each image-baked
    # product, compare its running /version baked SHA against origin/main HEAD; --notify alerts
    # A.R.C.H.I.E./Telegram on CONCRETE drift only. Fail-open (unreachable/unstamped ≠ drift). Runs
    # the repo script in-container — git + ./.git + ./scripts are mounted; safe.directory is set for
    # the root-owned bind mount (mirrors the agent_loop git-in-container pattern).
    def _run_deploy_drift_monitor():
        import os as _dd_os
        import subprocess as _dd_sp
        import time as _dd_t

        _dd_start = _dd_t.time()
        script = "/mnt/archie_brain/scripts/deploy_drift_check.py"
        if not _dd_os.path.exists(script):
            logger.warning("[DeployDrift] %s not found — skipping", script)
            return
        env = dict(_dd_os.environ)
        env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "safe.directory",
                "GIT_CONFIG_VALUE_0": "/mnt/archie_brain",
            }
        )
        try:
            r = _dd_sp.run(
                ["python3", script, "--notify"],
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
            # deploy_drift_check.py exits 1 on concrete drift, 0 otherwise.
            tag = "DRIFT" if r.returncode == 1 else "in-sync"
            logger.info("[DeployDrift] %s (rc=%s)\n%s", tag, r.returncode, (r.stdout or "").strip()[-1500:])
            if (r.stderr or "").strip():
                logger.debug("[DeployDrift] stderr: %s", r.stderr.strip()[-500:])
        except Exception as exc:  # noqa: BLE001 — a monitor must never crash the scheduler
            logger.warning("[DeployDrift] check failed (fail-open): %s", exc)
            return
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="F.O.R.G.E.",
                capability="code_review",
                duration_ms=int((_dd_t.time() - _dd_start) * 1000),
            )
        except Exception as _tel:
            logger.debug("[DeployDrift] task_execution_log write failed: %s", _tel)

    scheduler.add_job(
        with_ctx(_run_deploy_drift_monitor),
        trigger=CronTrigger(hour=6, minute=20, timezone="America/Toronto"),
        id="deploy_drift_monitor",
        name="Repair Bay: Deploy-provenance drift monitor",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Job #62 — F.O.R.G.E. PR Analyze (every 4h at +20min offset) — AI review pending PRs
    def _run_forge_pr_analyze():
        import time as _fpa_t

        _fpa_start = _fpa_t.time()
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
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="F.O.R.G.E.",
                capability="code_review",
                duration_ms=int((_fpa_t.time() - _fpa_start) * 1000),
            )
        except Exception as _tel:
            logger.debug("[ForgePRAnalyze] task_execution_log write failed: %s", _tel)

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
            with_ctx(run_geds_refresh_sync),
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
                           gpu_available, extra_capabilities,
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

                # Route hint: name a node that can ACTUALLY hold this model.
                # This string is diagnostic only — the planner writes priority, never a
                # node assignment (node choice belongs to BridgeDispatcher/model_dispatch,
                # which enforce capacity themselves). But an unfiltered hint printed
                # gpu_fleet[0] regardless of the model, so it happily claimed
                # "gemma3:12b -> GPU fleet (USS-245)" for a 4GB node. On 2026-08-19 that
                # misled an operator into capping a 100%-healthy node (KB #291799).
                # A diagnostic that names an impossible node is worse than no hint.
                candidates = cpu_fleet if is_cpu else gpu_fleet
                eligible = [n for n in candidates if _planner_node_fits(n, model)]
                if eligible:
                    lane = "CPU" if is_cpu else "GPU"
                    route = f"→ {lane} fleet ({eligible[0]['node_name']})"
                elif candidates:
                    route = "→ hub (no fleet node can hold this model)"
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

            try:
                from services.telemetry_writer import log_marker

                log_marker(
                    agent_name="K.I.N.",
                    capability="workforce_planning",
                    duration_ms=duration_ms,
                    node_used_id=68,
                )
            except Exception as _tel:
                logger.debug("[ModelQueuePlanner] task_execution_log write failed: %s", _tel)

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
        import time as _dzr_t

        _dzr_start = _dzr_t.time()
        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (_, cur):
                # Expire stuck 'running' items (platform restart orphans, >30 min).
                #
                # ⚠️ THE CLOCK STARTS AT CLAIM, NOT AT ENQUEUE (#5188). This used
                # `queued_at < NOW() - 30 min`, which measures QUEUE WAIT, not
                # RUN TIME — so a job that waited out the deadline before a worker
                # ever picked it up was eligible for reaping the INSTANT it started
                # running. Measured 2026-07-28 across 2,183 reaped rows:
                #   avg wait to be claimed .......... 59.0 min   (already past 30)
                #   avg actually held (claim->reap) .. 6.2 min
                #   claimed AFTER the deadline ....... 1,962 / 2,183 = 89.9%
                # So ~90% were healthy, actively-running jobs killed mid-flight and
                # labelled "stuck running >30 min" — which they never were. That one
                # bucket is 2,022 rows, 57% of ALL dispatch failures, and it is why
                # the queue looked like it was hanging when it was actually being
                # shot. The label made the misdiagnosis worse than the loss.
                #
                # COALESCE keeps the original safety net: a 'running' row with NO
                # claimed_at is a genuine orphan (platform restart between claim and
                # write), so it still falls back to queued_at and is reaped.
                cur.execute(
                    """
                    UPDATE dispatch_pending_queue
                       SET status = 'failed',
                           error = 'zombie: held >30 min after claim (no result returned)'
                     WHERE status = 'running'
                       AND COALESCE(claimed_at, queued_at) < NOW() - INTERVAL '30 minutes'
                    RETURNING id, agent_name, capability
                    """
                )
                reaped = cur.fetchall() or []

                # Warmup rows first (#5699 item 3): capability='warmup' is a K.I.N.
                # infrastructure ping with a minutes-scale TTL of its own (12-min
                # expires_at at enqueue + the worker's fallback TTL). It must NEVER
                # land in the 'no drain worker' failure bucket below — 1,589 rows of
                # REAL expired work were invisible under 1,791 rows of warmup noise.
                # Terminal state is 'expired' (infrastructure), not 'failed'.
                cur.execute(
                    """
                    UPDATE dispatch_pending_queue
                       SET status = 'expired',
                           error = COALESCE(error, 'expired: warmup TTL — infrastructure ping, not real work')
                     WHERE status = 'queued'
                       AND capability = 'warmup'
                       AND queued_at < NOW() - INTERVAL '15 minutes'
                    RETURNING id
                    """
                )
                warmup_expired = cur.fetchall() or []

                # Expire stuck 'queued' items (no drain worker available, >2 hours)
                # These are CPU-model pre-queue entries that accumulate when model_dispatch_worker
                # is behind or offline. Expire them so the cluster activity display stays accurate.
                # COALESCE: a NULL capability is real work, not warmup — NULL <> 'warmup' is
                # NULL in SQL and would silently exempt those rows from the reaper.
                cur.execute(
                    """
                    UPDATE dispatch_pending_queue
                       SET status = 'failed', error = 'expired: no drain worker, stuck queued >2h'
                     WHERE status = 'queued'
                       AND COALESCE(capability, '') <> 'warmup'
                       AND queued_at < NOW() - INTERVAL '2 hours'
                    RETURNING id, agent_name, capability
                    """
                )
                stale_queued = cur.fetchall() or []
                if stale_queued or warmup_expired:
                    logger.warning(
                        "[DeptHQ] Queue reaper: expired %d stale queued tasks (no drain worker >2h) "
                        "+ %d warmup rows past TTL",
                        len(stale_queued),
                        len(warmup_expired),
                    )

                # Close rest cycles past THEIR break-type duration (#379 Phase 2): micro_rest
                # 15min / action_rest 30 / token_rest 45 / shift_rest 60 (from
                # workload_before.duration_min; legacy/typeless cycles fall back to 60min).
                # Recovery (stress/energy) is computed PER AGENT, scaled to depletion + rest
                # length via welfare_load.recovery_after_break — NOT a flat 0.20/0.80 reset.
                from services.welfare_load import recovery_after_break as _recovery

                cur.execute(
                    """
                    SELECT id, agent_id, stress_at_start, energy_at_start,
                           COALESCE((workload_before->>'duration_min')::numeric, 60) AS dur_min
                    FROM agent_rest_cycles
                    WHERE ended_at IS NULL
                      AND started_at < NOW() - (COALESCE((workload_before->>'duration_min')::numeric, 60)
                                                || ' minutes')::interval
                    """
                )
                due_cycles = cur.fetchall() or []
                if due_cycles:
                    recovered_ids = []
                    for _c in due_cycles:
                        _rs, _re = _recovery(_c["stress_at_start"], _c["energy_at_start"], _c["dur_min"])
                        cur.execute(
                            """
                            UPDATE agent_rest_cycles
                               SET ended_at = started_at + (((%s)::numeric) || ' minutes')::interval,
                                   stress_at_end = %s, energy_at_end = %s,
                                   notes = COALESCE(notes,'') || %s
                             WHERE id = %s
                            """,
                            (
                                _c["dur_min"],
                                _rs,
                                _re,
                                f" [auto-closed: {int(_c['dur_min'])}min rest; recovered stress->{_rs} energy->{_re}]",
                                _c["id"],
                            ),
                        )
                        cur.execute(
                            """
                            UPDATE agent_emotional_state
                               SET stress_level = %s, energy_level = %s,
                                   current_mood = 'focused', timestamp = NOW()
                             WHERE agent_id = %s
                            """,
                            (_rs, _re, _c["agent_id"]),
                        )
                        recovered_ids.append(_c["agent_id"])
                    logger.info(
                        "[DeptHQ] Rest reaper: closed %d rest cycle(s) at their break-type duration",
                        len(due_cycles),
                    )
                    # Restore agents from winding_down/cooldown → active after rest completes
                    cur.execute(
                        """
                        UPDATE agents
                           SET shift_state = 'active', updated_at = NOW()
                         WHERE id = ANY(%s)
                           AND shift_state IN ('winding_down', 'cooldown')
                        """,
                        (recovered_ids,),
                    )
                    if cur.rowcount:
                        logger.info(
                            "[DeptHQ] Rest reaper: restored %d agent(s) to active after rest",
                            cur.rowcount,
                        )
                        # Telegram — notify when agent(s) return to active duty after rest
                        try:
                            cur.execute(
                                "SELECT name FROM agents WHERE id = ANY(%s)",
                                (recovered_ids,),
                            )
                            recovered_names = [r["name"] for r in cur.fetchall() or []]
                            label = " & ".join(recovered_names) or f"{len(recovered_ids)} agent(s)"
                            verb = "has" if len(recovered_names) == 1 else "have"
                            # K.I.N. routes welfare news via A.R.C.H.I.E.'s inbox
                            # (A.R.C.H.I.E. is the sole Telegram voice — ADR unified-voice)
                            from services.director_report_service import submit_via_inbox as _kin_inbox

                            _kin_inbox(
                                category="welfare",
                                title=f"✅ {label} returned to active duty",
                                message=(
                                    f"{label} {verb} returned to active duty after mandatory rest — "
                                    f"back to full capacity and accepting dispatches."
                                ),
                                source_agent="K.I.N.",
                                severity="low",
                                department="Human Resources & Culture",
                                cooldown_hours=0.5,
                            )
                        except Exception as _tg_err:
                            logger.warning("[DeptHQ] Rest recovery Telegram notify failed: %s", _tg_err)

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
                    # Interactive alert: 📊 Details + 🔕 Snooze 24h (#alert-buttons).
                    from services.alert_actions_service import send_alert

                    send_alert(
                        alert_key="zombie_reaper",
                        title="⚠️ Queue zombie reaper",
                        message=f"Expired {len(reaped)} tasks stuck >30 min.\nAgents: {summary}",
                        actions=["details", "snooze"],
                    )
                except Exception:
                    pass
            else:
                logger.debug("[DeptHQ] Zombie reaper: queue clean")
        except Exception as exc:
            logger.error("[DeptHQ] Zombie reaper failed: %s", exc)
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="K.I.N.",
                capability="welfare_monitoring",
                duration_ms=int((_dzr_t.time() - _dzr_start) * 1000),
                node_used_id=68,
            )
        except Exception as _tel:
            logger.debug("[ZombieReaper] task_execution_log write failed: %s", _tel)

    scheduler.add_job(
        with_ctx(_run_dispatch_zombie_reaper),
        trigger=CronTrigger(minute="*/15", timezone="America/Toronto"),
        id="dispatch_zombie_reaper",
        name="Queue: Expire zombie running tasks (>30 min)",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered dispatch_zombie_reaper job (every 15 min)")

    def _run_creed_welfare_governance():
        """E.T.H.O.S./C.R.E.E.D. welfare governance (#379 Phase 4).

        Grades the ORGANISATION (0-100) on how it treats its AI workforce: the share of
        active agents within healthy bounds + the share of over-limit agents that were
        actually given a break. Persists the snapshot to agent_welfare_scores, emits a
        C.R.E.E.D. governance event per welfare violation, and produces improvement
        recommendations. Pure SQL + math + emit (no LLM) — safe on the scheduler thread.
        """
        try:
            from database import get_db_cursor
            from services.welfare_governance_service import run_welfare_governance

            with get_db_cursor(commit=True) as (_, cur):
                result = run_welfare_governance(cur, emit=True)
            logger.info(
                "[DeptHQ] Welfare governance: %s/%s (%d violations, %d recommendations)",
                result.get("score"),
                result.get("grade"),
                len(result.get("violations") or []),
                len(result.get("recommendations") or []),
            )
        except Exception as _wg:
            logger.warning("[DeptHQ] welfare governance job failed: %s", _wg, exc_info=True)

    scheduler.add_job(
        with_ctx(_run_creed_welfare_governance),
        trigger=CronTrigger(hour=6, minute=0, timezone="America/Toronto"),
        id="creed_welfare_governance",
        name="C.R.E.E.D.: AI-workforce welfare governance (daily 06:00 ET)",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered creed_welfare_governance job (daily 06:00 ET)")

    def _run_welfare_emit_intraday():
        """C.R.E.E.D. welfare emitter — intraday cadence (#379 Phase 3, FIX-1).

        The 06:00 daily job samples the token-window LOW (overnight idle drains the
        24h-rolling token sum), so in production it emitted ~0 welfare events and the
        public welfare grade never moved. This HOURLY job gathers a FRESH snapshot
        and pushes de-duped per-dimension category='welfare' events to the standalone
        (welfare_emit). De-dupe (state-change + 6h heartbeat) keeps 54 agents × 4
        dims from flooding the public store. Does NOT persist a headline row (the
        daily job owns agent_welfare_scores). Pure SQL + emit — safe on the
        scheduler thread.

        HOURLY (not */5): the public welfare grade is a 30-day rolling window, so it
        needs mid-day coverage, not sub-hourly resolution; an over-budget agent
        persists for hours. Hourly + de-dupe = real signal, minimal traffic.
        """
        try:
            from database import get_db_cursor
            from services.welfare_governance_service import welfare_emit_intraday

            with get_db_cursor(commit=True) as (_, cur):
                summary = welfare_emit_intraday(cur)
            logger.info(
                "[DeptHQ] Welfare emit (intraday): built=%s emitted=%s skipped=%s failed=%s",
                summary.get("built"),
                summary.get("emitted"),
                summary.get("skipped"),
                summary.get("failed"),
            )
        except Exception as _we:
            logger.warning("[DeptHQ] welfare emit intraday job failed: %s", _we, exc_info=True)

    scheduler.add_job(
        with_ctx(_run_welfare_emit_intraday),
        trigger=CronTrigger(minute=0, timezone="America/Toronto"),
        id="welfare_emit_intraday",
        name="C.R.E.E.D.: welfare event emitter (hourly, intraday)",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered welfare_emit_intraday job (hourly)")

    # K.I.N. stuck-agent reaper (FIX-6 + FIX-8, review KB #270619). Two leaks left
    # agents permanently idle: (RC2) 'deployed' is a terminal black-hole — an agent
    # placed on a node that stays steadily ONLINE never returns, because the only exit
    # fires on a node OFFLINE→ONLINE flip; and select_agent scores any non-active agent
    # 0.0, so it is unselectable. (RC3) an agent the dispatcher/welfare gate drops to
    # 'winding_down' gets NO rest cycle, so the rest-reaper (which only restores agents
    # whose cycle it closed) never sees it. This job closes both: it returns to active
    # any agent that is safe to wake — node placement in node_agents is PRESERVED, only
    # shift_state flips so the agent is dispatchable again.
    def _run_kin_stuck_agent_reaper():
        from database import get_db_cursor as _ksr_db

        try:
            with _ksr_db(commit=True) as (_, _ksr_cur):
                # FIX-6: 'deployed' agents idle for 20 min (no recent dispatch) → active.
                _ksr_cur.execute(
                    """
                    UPDATE agents a SET shift_state='active', updated_at=NOW()
                     WHERE a.worker_type='ai' AND a.shift_state='deployed' AND a.status='active'
                       AND NOT EXISTS (SELECT 1 FROM task_execution_log tel
                                        WHERE tel.agent_name=a.name
                                          AND tel.created_at > NOW() - INTERVAL '20 minutes')
                    RETURNING name
                    """
                )
                freed_deployed = [r["name"] for r in _ksr_cur.fetchall() or []]
                # FIX-8: 'winding_down'/'cooldown' with cleared welfare (latest stress < 0.70)
                # and NO ACTIVE rest cycle → active. Catches dispatcher-downed agents that the
                # rest-reaper can't see because they never got a rest cycle.
                #
                # BUGFIX (welfare-rest-enforcement): a rest cycle is "active" when it is
                # open-ended (ended_at IS NULL) OR still inside its window (ended_at > NOW()).
                # The COO 12h mandatory-rest writes a BOUNDED cycle (ended_at = NOW()+8h, a
                # FUTURE timestamp, NOT NULL — agent_jobs.py). The old guard only checked
                # ended_at IS NULL, so it did not see the COO cycle, and this reaper restored
                # the just-rested agent within 5 min whenever its token-stress was < 0.70 —
                # the cumulative-HOURS rest fought the instantaneous token-STRESS restore in a
                # 30-min ping-pong (V.E.R.I.F.Y.). An explicit mandatory-rest window must
                # outrank a low stress reading until it expires.
                _ksr_cur.execute(
                    """
                    UPDATE agents a SET shift_state='active', updated_at=NOW()
                     WHERE a.worker_type='ai' AND a.shift_state IN ('winding_down','cooldown')
                       AND a.status='active'
                       AND COALESCE((SELECT stress_level FROM agent_emotional_state
                                       WHERE agent_id=a.id ORDER BY timestamp DESC LIMIT 1),0) < 0.70
                       AND NOT EXISTS (SELECT 1 FROM agent_rest_cycles rc
                                        WHERE rc.agent_id=a.id
                                          AND (rc.ended_at IS NULL OR rc.ended_at > NOW()))
                    RETURNING name
                    """
                )
                freed_wind = [r["name"] for r in _ksr_cur.fetchall() or []]
                # BARRACKED-RESCUE (bug #5155): 'barracked' is the failure-standby
                # bench and does NOT auto-recover — but agents also land there for
                # NON-failure reasons (a fresh hire benched seconds after creation;
                # a fleet-health/node-offline flap), then strand FOREVER. Hired
                # capacity never reaches the dispatchable pool, so the staffing
                # recommender re-proposes the same skill every cycle (News fact_check/
                # bias_analysis re-proposed daily despite approvals). Recover a
                # barracked agent ONLY when it is genuinely stuck (>10 min), carries
                # NO recent failure-standby marker (agent_learning_records within 6h —
                # the ONE thing that means it was benched for real failures, not
                # stranded), has low stress, and has no active rest cycle. A truly-
                # failing agent keeps its Academy/verification window and re-benches
                # itself if it fails again after recovery — so this can't defeat the
                # failure-standby, only the accidental strandings.
                _ksr_cur.execute(
                    """
                    UPDATE agents a SET shift_state='active', updated_at=NOW()
                     WHERE a.worker_type='ai' AND a.shift_state='barracked'
                       AND a.status='active'
                       AND a.updated_at < NOW() - INTERVAL '10 minutes'
                       AND COALESCE((SELECT stress_level FROM agent_emotional_state
                                       WHERE agent_id=a.id ORDER BY timestamp DESC LIMIT 1),0) < 0.70
                       AND NOT EXISTS (SELECT 1 FROM agent_rest_cycles rc
                                        WHERE rc.agent_id=a.id
                                          AND (rc.ended_at IS NULL OR rc.ended_at > NOW()))
                       AND NOT EXISTS (SELECT 1 FROM agent_learning_records lr
                                        WHERE lr.agent_id=a.id
                                          AND lr.learning_type='failure_standby'
                                          AND lr.learned_at > NOW() - INTERVAL '6 hours')
                    RETURNING name
                    """
                )
                freed_barracked = [r["name"] for r in _ksr_cur.fetchall() or []]
                total = len(freed_deployed) + len(freed_wind) + len(freed_barracked)
                if total:
                    logger.info(
                        "[DeptHQ] K.I.N. stuck-agent reaper: restored %d → active "
                        "(deployed=%s, winding_down=%s, barracked=%s)",
                        total,
                        freed_deployed,
                        freed_wind,
                        freed_barracked,
                    )
        except Exception as exc:
            logger.error("[DeptHQ] K.I.N. stuck-agent reaper failed: %s", exc)

    scheduler.add_job(
        with_ctx(_run_kin_stuck_agent_reaper),
        trigger=CronTrigger(minute="*/5", timezone="America/Toronto"),
        id="kin_stuck_agent_reaper",
        name="K.I.N.: Reap stuck deployed/winding_down/barracked agents → active",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered kin_stuck_agent_reaper job (every 5 min)")

    # Job: K.I.N. failure-standby — pull a repeatedly-FAILING agent OFF the floor for
    # Academy/verification instead of pushing it more work (owner directive; welfare
    # accounted only for SUCCESS until now — this is the failure half). An active AI
    # agent with >=5 real-LLM dispatches AND >=50% failures in the last hour is benched
    # to 'barracked' (standby that does NOT auto-recover like cooldown — it returns only
    # when verified/woken), gets an agent_learning_records Academy entry, and a NEGATIVE
    # C.R.E.E.D. governance event. Once benched it is no longer shift_state='active', so
    # it won't re-match next cycle (natural dedup). Runs every 15 min.
    def _run_kin_failure_standby():
        import json as _fj

        from database import get_db_cursor as _fdb
        from services.kin_failure_standby import failing_agents as _failing_agents

        try:
            standby = []
            with _fdb(commit=True) as (_c, cur):
                # Candidate selection lives in services/kin_failure_standby.py so it can
                # be tested (tests/test_kin_failure_standby_backpressure.py). It excludes
                # hub admission-control sheds from BOTH the failure count and the
                # dispatch count — those rows are capacity control, not agent defects
                # (#5165). See services/infra_failure_filter.py for why.
                for o in _failing_agents(cur):
                    aid, aname = o["id"], o["name"]
                    total, fails = int(o["total"]), int(o["fails"])
                    pct = round(100.0 * fails / total)
                    cur.execute(
                        """INSERT INTO agent_learning_records
                               (agent_id, learning_type, subject, lesson_learned, source_type)
                           VALUES (%s,'failure_standby','reliability',%s,'kin_failure_monitor')""",
                        (
                            aid,
                            f"{aname} pulled to standby: {pct}% failure rate ({fails}/{total} real-LLM "
                            f"dispatches in 1h). Verify model/health (Academy) before returning to the floor.",
                        ),
                    )
                    cur.execute(
                        """INSERT INTO governance_audit_log
                               (agent_id, event_category, event_type, action, reason, details, timestamp)
                           VALUES (%s,'creed_compliance','failure_standby','kin_failure_monitor',%s,%s::jsonb,NOW())""",
                        (
                            aid,
                            f"K.I.N. pulled {aname} to standby — {pct}% failure rate ({fails}/{total} in 1h). "
                            f"Routed to Academy/verification, NOT more work.",
                            _fj.dumps({"fail_pct": pct, "fails": fails, "total": total, "failure_driven": True}),
                        ),
                    )
                    standby.append((aid, aname, pct))
            # Bench via the single-writer (agents-table guardrail). 'barracked' = standby
            # that does not auto-recover; the dispatcher routes around it.
            if standby:
                from services.agent_service import transition_shift_state as _ts

                for aid, aname, pct in standby:
                    try:
                        _ts(aid, "barracked", f"K.I.N. failure standby — {pct}% fail/1h → Academy/verification")
                    except Exception as _tse:
                        logger.warning("[DeptHQ] failure-standby transition failed for %s: %s", aname, _tse)
                logger.info(
                    "[DeptHQ] K.I.N. failure-standby: benched %d failing agent(s): %s",
                    len(standby),
                    ", ".join(f"{n}({p}%)" for _, n, p in standby),
                )
        except Exception as exc:
            logger.error("[DeptHQ] K.I.N. failure-standby failed: %s", exc)

    scheduler.add_job(
        with_ctx(_run_kin_failure_standby),
        trigger=CronTrigger(minute="*/15", timezone="America/Toronto"),
        id="kin_failure_standby",
        name="K.I.N.: Pull failing agents to standby for Academy/verification",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered kin_failure_standby job (every 15 min)")

    # Job #124: Dispatch Backfill Worker — re-dispatch stuck queue items to backup agents
    # Runs every 5 min. Converts the dead-letter queue into active gap-filling:
    # items stuck >10 min are re-dispatched via the DHQ dispatcher (which now
    # picks backup agents since primary may be resting). Max 5 items/cycle.
    # -------------------------------------------------------------------------
    def _run_dispatch_backfill():
        """Re-dispatch stuck dispatch_pending_queue items to backup agents.

        When a primary agent rests, dispatches go to dispatch_pending_queue instead
        of running. This job picks those up and re-dispatches them — the dispatcher
        now selects backup agents (since primaries score 0 when resting).
        """
        import time as _db_t

        _db_start = _db_t.time()
        try:
            from database import get_db_cursor
            from tools.department_hq.services.department_dispatcher import dispatch

            # AGENT MOBILITY PROFILE — "Yellow Alert, all forces redirected" (#5132).
            #
            # The profile already biased warmth, node routing, model tier and backlog
            # promotion, but NOT this queue — so pressing PLATFORM changed where work
            # could run without changing what ran first. Measured 2026-07-23: with
            # PLATFORM active, platform `code_review` sat at priority 5 behind 64 news
            # rows at 8-9 and never drained in ~60 minutes.
            #
            # The boost is applied HERE, at drain time, rather than by UPDATE-ing rows
            # when the mode is switched. That choice matters:
            #   * it re-ranks the EXISTING queue retroactively (the operator's ask —
            #     "if there is queues in that button, all queues of that button get
            #     affected too"), with no migration and no backfill;
            #   * it is idempotent and self-reversing — flip the mode and the very next
            #     cycle reorders. Mutating priorities would ratchet them upward on every
            #     press and need a stored base priority to ever undo.
            #
            # It is a TIE-BREAK ABOVE priority, not a replacement for it: within the
            # favoured domain the existing priority/age ordering is untouched, and
            # nothing is filtered out — deprioritised work still drains, just after.
            # On 'auto' the term is omitted entirely, so ordering stays byte-identical
            # to pre-profile behaviour.
            boost_sql = ""
            boost_params: list = []
            try:
                from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP
                from services.fleet_dispatch_profile import (
                    NEWS_DEPARTMENT,
                    NEWS_MODULE_KEYWORDS,
                    get_dispatch_mode,
                )

                _mode = get_dispatch_mode()
                if _mode in ("news", "platform"):
                    _news_caps = [c for c, d in CAPABILITY_DEPARTMENT_MAP.items() if d == NEWS_DEPARTMENT]
                    _news_like = ["%%%s%%" % k for k in NEWS_MODULE_KEYWORDS]
                    # Mirrors fleet_dispatch_profile.is_news_queue_row() in SQL: capability
                    # routes to News & Media OR module_id looks like a watch-product
                    # producer. Both signals are needed — `classify` (the largest news
                    # block) maps to Analytics & Intelligence, so capability alone would
                    # mark WTF work as platform work and boost exactly the wrong rows.
                    boost_sql = (
                        "(CASE WHEN (capability = ANY(%s) "
                        "OR lower(coalesce(module_id,'')) LIKE ANY(%s)) = %s "
                        "THEN 1 ELSE 0 END) DESC, "
                    )
                    boost_params = [_news_caps, _news_like, _mode == "news"]
            except Exception:  # noqa: BLE001 — a routing preference must never stop the drain
                boost_sql = ""
                boost_params = []

            with get_db_cursor(commit=False) as (_, cur):
                cur.execute(
                    f"""
                    SELECT id, capability, prompt, system_prompt, json_mode,
                           module_id, source_product, priority
                    FROM dispatch_pending_queue
                    WHERE status = 'queued'
                      AND queued_at < NOW() - INTERVAL '10 minutes'
                      AND queued_at > NOW() - INTERVAL '2 hours'
                    ORDER BY {boost_sql}priority DESC, queued_at ASC
                    LIMIT 5
                    """,
                    boost_params,
                )
                stuck_items = cur.fetchall() or []

            if not stuck_items:
                return

            logger.info("[Backfill] Found %d stuck queue items to re-dispatch", len(stuck_items))

            for item in stuck_items:
                try:
                    result = dispatch(
                        capability=item["capability"],
                        prompt=item["prompt"] or "",
                        system_prompt=item["system_prompt"],
                        json_mode=bool(item["json_mode"]),
                        module_id=item["module_id"] or "backfill_worker",
                        priority="high",
                    )
                    if result.success:
                        with get_db_cursor(commit=True) as (_, cur2):
                            cur2.execute(
                                """
                                UPDATE dispatch_pending_queue
                                   SET status = 'completed',
                                       completed_at = NOW(),
                                       result_response = %s,
                                       error = 'backfill: re-dispatched to backup agent'
                                 WHERE id = %s AND status = 'queued'
                                """,
                                (
                                    (result.response or "")[:500],
                                    item["id"],
                                ),
                            )
                        logger.info(
                            "[Backfill] Item #%d (%s) completed via backup agent",
                            item["id"],
                            item["capability"],
                        )
                    else:
                        logger.debug(
                            "[Backfill] Item #%d (%s) still blocked: %s",
                            item["id"],
                            item["capability"],
                            (result.error or "")[:80],
                        )
                except Exception as item_exc:
                    logger.debug("[Backfill] Item #%d error: %s", item["id"], item_exc)
        except Exception as exc:
            logger.error("[DeptHQ] Dispatch backfill failed: %s", exc)
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="K.I.N.",
                capability="welfare_monitoring",
                duration_ms=int((_db_t.time() - _db_start) * 1000),
                node_used_id=68,
            )
        except Exception as _tel:
            logger.debug("[Backfill] task_execution_log write failed: %s", _tel)

    scheduler.add_job(
        with_ctx(_run_dispatch_backfill),
        trigger=CronTrigger(minute="*/5", timezone="America/Toronto"),
        id="dispatch_backfill_worker",
        name="Backfill: re-dispatch stuck queue items to backup agents (every 5 min)",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered dispatch_backfill_worker job (every 5 min)")

    # Job #123: K.I.N. Node Planning — assign agents to nodes by model fit
    # Runs every 4h. Ensures fleet nodes have active node_agents entries for
    # agents whose models are available on that node. Also activates S.C.O.U.T.
    # as backup for geo_extraction when L.O.C.A.L. is resting.
    # -------------------------------------------------------------------------
    def _run_kin_node_planning():
        """K.I.N. coordinates agent-to-node assignments based on model fit.

        For each online fleet node, checks its ollama_models list and ensures
        active node_agents entries exist for AI agents whose model is in that
        list. Deactivates assignments on nodes that don't have the model.
        Logs a governance audit entry summarising the plan.
        K.I.N. (id=145) work session surfaces this in DHQ Work Tracking + dispatch.
        """
        # K.I.N. (id=145) work session — surfaces in DHQ Work Tracking + dispatch
        _kin_session = None
        try:
            from services.work_tracking_service import (
                create_work_session,
                complete_work_session,
                fail_work_session,
            )

            _kin_session = create_work_session(
                agent_id=145,
                department="Human Resources & Culture",
                session_type="node_planning",
                title="K.I.N. Node Planning — Agent-to-Fleet Assignment",
                metadata={"interval": "30min", "model": "gemma3:12b"},
            )
        except Exception as _wt_err:
            logger.warning("[K.I.N.] Work session create failed: %s", _wt_err)

        try:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (_, cur):
                # --- Get online nodes with their model lists ---
                cur.execute(
                    """
                    SELECT id, node_id, node_name, gpu_available, gpu_vram_gb, ram_gb,
                           extra_capabilities->>'ollama_models' AS ollama_models_json
                    FROM remote_nodes
                    WHERE is_active = TRUE AND status = 'online'
                      AND last_heartbeat > NOW() - INTERVAL '5 minutes'
                      AND extra_capabilities->>'ollama_models' IS NOT NULL
                    ORDER BY node_name
                    """
                )
                nodes = cur.fetchall() or []

                if not nodes:
                    logger.info("[K.I.N.] Node planning: no nodes online with model lists")
                    return

                import json as _json

                node_model_map = {}  # node_db_id → set of model names
                for n in nodes:
                    try:
                        models = _json.loads(n["ollama_models_json"] or "[]")
                        node_model_map[n["id"]] = {m.lower() for m in (models or [])}
                    except Exception:
                        node_model_map[n["id"]] = set()

                # --- Get all active AI agents ---
                cur.execute(
                    """
                    SELECT a.id, a.name, a.model, a.department
                    FROM agents a
                    WHERE a.worker_type = 'ai'
                      AND a.shift_state NOT IN ('decommissioned', 'barracked')
                      AND a.model IS NOT NULL
                    """
                )
                agents = cur.fetchall() or []

                activated = 0
                deactivated = 0
                skipped = 0

                for agent in agents:
                    agent_model = (agent["model"] or "").lower().split(":")[0]  # strip tag
                    for node in nodes:
                        node_id = node["id"]
                        node_models = node_model_map.get(node_id, set())
                        # Check if any registered model starts with the agent's model name
                        model_fits = any(
                            m.startswith(agent_model) or agent_model.startswith(m.split(":")[0]) for m in node_models
                        )

                        # Check existing node_agents entry
                        cur.execute(
                            """
                            SELECT id, status FROM node_agents
                            WHERE node_id = %s AND hub_agent_id = %s
                            """,
                            (node_id, agent["id"]),
                        )
                        existing = cur.fetchone()

                        if model_fits and not existing:
                            # Create new active assignment (unique on node_id + name)
                            cur.execute(
                                """
                                INSERT INTO node_agents
                                    (node_id, hub_agent_id, source_agent_id, name, model,
                                     status, department, auto_assigned)
                                VALUES (%s, %s, %s, %s, %s, 'active', %s, TRUE)
                                ON CONFLICT (node_id, name) DO UPDATE
                                    SET status='active', hub_agent_id=%s,
                                        source_agent_id=%s, model=%s, auto_assigned=TRUE
                                """,
                                (
                                    node_id,
                                    agent["id"],
                                    agent["id"],
                                    agent["name"],
                                    agent["model"],
                                    agent["department"],
                                    agent["id"],
                                    agent["id"],
                                    agent["model"],
                                ),
                            )
                            if cur.rowcount:
                                activated += 1
                        elif model_fits and existing and existing["status"] != "active":
                            cur.execute(
                                "UPDATE node_agents SET status='active' WHERE id=%s",
                                (existing["id"],),
                            )
                            activated += 1
                        elif not model_fits and existing and existing["status"] == "active":
                            # Only deactivate auto-assigned entries — don't touch manually curated ones
                            cur.execute(
                                "UPDATE node_agents SET status='inactive' WHERE id=%s AND auto_assigned=TRUE",
                                (existing["id"],),
                            )
                            if cur.rowcount:
                                deactivated += 1
                            else:
                                skipped += 1
                        else:
                            skipped += 1

                # --- Log to governance audit ---
                cur.execute(
                    """
                    INSERT INTO governance_audit_log
                        (agent_id, event_category, event_type, action, reason, details, timestamp)
                    SELECT a.id, 'node_planning', 'kin_node_assignment', 'node_management',
                           'K.I.N. node planning: ' || %s || ' activated, ' || %s || ' deactivated',
                           %s::jsonb, NOW()
                    FROM agents a WHERE a.name = 'K.I.N.' LIMIT 1
                    """,
                    (
                        activated,
                        deactivated,
                        _json.dumps(
                            {
                                "activated": activated,
                                "deactivated": deactivated,
                                "nodes_checked": len(nodes),
                                "agents_reviewed": len(agents),
                            }
                        ),
                    ),
                )

                logger.info(
                    "[K.I.N.] Node planning complete — activated=%d deactivated=%d nodes=%d agents=%d",
                    activated,
                    deactivated,
                    len(nodes),
                    len(agents),
                )
            if _kin_session:
                complete_work_session(_kin_session, jobs_completed=activated + deactivated)
        except Exception as exc:
            logger.error("[K.I.N.] Node planning failed: %s", exc)
            if _kin_session:
                fail_work_session(_kin_session, error_msg=str(exc))

    scheduler.add_job(
        with_ctx(_run_kin_node_planning),
        trigger=CronTrigger(minute="*/30", timezone="America/Toronto"),
        id="kin_node_planning",
        name="K.I.N.: Fleet node agent assignment by model fit (every 30 min)",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered kin_node_planning job (every 30 min)")

    # Job #125: K.I.N. Workload Monitor — detect overloaded agents, rebalance across nodes
    # Runs every 10 min. Checks per-node dispatch counts and budget utilisation.
    # Logs imbalance to governance_audit_log and fires a V.I.G.I.L. alert when
    # the busiest node handles >3× more work than the least-busy active node.
    # -------------------------------------------------------------------------
    def _run_kin_workload_monitor():
        """K.I.N. monitors fleet workload balance and flags overloaded agents.

        Checks task_execution_log (last 10 min) per node and agent_budgets for
        agents approaching their task_queue_limit. Emits governance audit entries
        and system_notifications when imbalance is detected.
        K.I.N. (id=145) work session surfaces this in DHQ Work Tracking + dispatch.
        """
        # K.I.N. (id=145) work session — surfaces in DHQ Work Tracking + dispatch
        _kin_wm_session = None
        _kin_wm_t0 = None
        try:
            import time as _kin_time

            _kin_wm_t0 = _kin_time.time()
        except Exception:
            pass
        try:
            from services.work_tracking_service import (
                create_work_session,
                complete_work_session,
                fail_work_session,
            )

            _kin_wm_session = create_work_session(
                agent_id=145,
                department="Human Resources & Culture",
                session_type="welfare_monitoring",
                title="K.I.N. Workload Monitor — Fleet Balance Check",
                metadata={"interval": "5min", "model": "gemma3:12b"},
            )
        except Exception as _wt_err:
            logger.warning("[K.I.N.] Work session (monitor) create failed: %s", _wt_err)

        try:
            import json as _json
            from database import get_db_cursor
            from services import agent_service as _agent_svc

            # FIX-5 (KB #270619): welfare DECAY refresh. update_welfare_after_task only
            # fires when an agent COMPLETES a dispatch, so an idle/winding_down agent's
            # stress is frozen at whatever the last writer set — which stranded
            # V.E.R.I.F.Y./B.I.A.S./K.I.N. at 0.90 from the pre-token-model era, where the
            # kin_stuck_agent_reaper (stress<0.70 gate) could never free them. Recomputing
            # each cycle from the live 1h token window decays stress for now-idle agents
            # (→ ~0.2 baseline) so the reaper can release them, AND makes the overload
            # signal below honest (token-based, not frozen). Each call manages its own
            # committed transaction; wrapped so a refresh failure never breaks the monitor.
            try:
                # KB #270628 convergence: precompute REAL wall-clock hours for the whole
                # fleet ONCE so each per-agent welfare recompute carries the hours-on-duty
                # term (via the shared welfare_load formula) without a fleet scan per agent.
                # This is why the refresh no longer strips hr_tracker's hours term — both
                # writers now feed the same formula the same inputs (no staleness gate).
                from services.agent_load_service import real_compute_hours_today

                _hours_map = real_compute_hours_today()
                with get_db_cursor() as (_rc, _rcur):
                    _rcur.execute(
                        """
                        SELECT id FROM agents
                        WHERE worker_type = 'ai'
                          AND shift_state IN ('active', 'deployed', 'winding_down', 'cooldown')
                        """
                    )
                    _refresh_ids = [r["id"] for r in (_rcur.fetchall() or [])]
                _refreshed = 0
                for _aid in _refresh_ids:
                    try:
                        # Fix #C (C.R.E.E.D. accounting): token_util is intentionally NOT
                        # passed here — update_welfare_after_task computes it internally
                        # (cheap per-agent 24h SUM against agent_budgets) when omitted, so
                        # this decay refresh picks up token-budget overwork for free
                        # without a fleet-wide bulk query in this loop.
                        _agent_svc.update_welfare_after_task(
                            _aid,
                            success=True,
                            hours_on_duty=(_hours_map.get(_aid) or {}).get("hours", 0.0),
                        )
                        _refreshed += 1
                    except Exception as _wf_e:
                        logger.debug("[K.I.N.] welfare refresh failed for agent %s: %s", _aid, _wf_e)
                if _refreshed:
                    logger.debug("[K.I.N.] welfare decay refresh: %d agents recomputed", _refreshed)
            except Exception as _wf_outer:
                logger.warning("[K.I.N.] welfare decay refresh skipped: %s", _wf_outer)

            with get_db_cursor(commit=True) as (_, cur):
                # --- Per-node load: token-based (FIX-5, KB #270619). Raw dispatch COUNT
                #     made a node doing many cheap 50-token pings look "busier" than one
                #     doing a few heavy 40k-token analyses. SUM(tokens_used) is the real
                #     compute load. Dispatch count kept only for display context. ---
                cur.execute(
                    """
                    SELECT rn.node_name,
                           COUNT(*) AS dispatches,
                           COALESCE(SUM(tel.tokens_used), 0) AS tokens
                    FROM task_execution_log tel
                    JOIN remote_nodes rn ON rn.id = tel.node_used_id
                    WHERE tel.created_at > NOW() - INTERVAL '10 minutes'
                      AND tel.node_used_id IS NOT NULL
                    GROUP BY rn.node_name
                    ORDER BY tokens DESC
                    """
                )
                node_loads = cur.fetchall() or []

                # --- Genuinely strained agents (FIX-5, KB #270619) ---
                # OLD: lifetime dispatch COUNT since reset / task_queue_limit — pure
                # action count, so an agent firing 200 cheap pings read as "overloaded"
                # and K.I.N. rested healthy agents (the exact action-vs-token bug).
                # NEW: read the freshly-refreshed token-based welfare stress (set by the
                # decay refresh above via the shared welfare_load formula). Pure
                # heavy-but-successful work caps stress at ~0.6; only failure-driven
                # strain (or accumulated duty hours from hr_tracker) pushes >=0.75 —
                # which is what actually warrants rest. `utilisation_pct` is kept as the
                # column name (= stress x 100) so the downstream rest loop, summary, and
                # alert lines keep working unchanged.
                cur.execute(
                    """
                    SELECT a.name, a.department, a.id AS agent_id,
                           ab.current_task_count, ab.task_queue_limit,
                           ab.last_task_reset_at,
                           ROUND(100.0 * aes.stress_level, 1) AS utilisation_pct,
                           aes.stress_level
                    FROM agent_budgets ab
                    JOIN agents a ON a.id = ab.agent_id
                    JOIN LATERAL (
                        SELECT stress_level
                        FROM agent_emotional_state
                        WHERE agent_id = a.id
                        ORDER BY timestamp DESC
                        LIMIT 1
                    ) aes ON TRUE
                    WHERE a.worker_type = 'ai'
                      AND a.shift_state IN ('active', 'deployed')
                      AND aes.stress_level >= 0.75
                    ORDER BY aes.stress_level DESC
                    LIMIT 10
                    """
                )
                overloaded = cur.fetchall() or []

                if not node_loads and not overloaded:
                    return  # nothing to report

                # --- Token-based node imbalance (INFORMATIONAL only, FIX-5) ---
                # The hub runs large models and CPU outposts run tiny ones, so a token
                # disparity BETWEEN tiers is EXPECTED and not actionable. We record it for
                # context but NEVER alert on it — alerting on raw node imbalance was the
                # 279/day "Fleet Workload Imbalance" spam the user flagged (KB #270619).
                toks = [int(r["tokens"]) for r in node_loads]
                max_tok = max(toks) if toks else 0
                min_tok = min(toks) if toks else 0
                imbalance = max_tok / max(min_tok, 1)

                summary = {
                    "node_tokens": {r["node_name"]: int(r["tokens"]) for r in node_loads},
                    "node_dispatches": {r["node_name"]: int(r["dispatches"]) for r in node_loads},
                    "strained_agents": [
                        {
                            "name": r["name"],
                            "stress": float(r["stress_level"] or 0),
                            "current": int(r["current_task_count"]),
                            "limit": int(r["task_queue_limit"]),
                        }
                        for r in overloaded
                    ],
                    "token_imbalance_ratio": round(imbalance, 2),
                }

                # --- Governance log (always, for C.R.E.E.D. transparency) ---
                cur.execute(
                    """
                    INSERT INTO governance_audit_log
                        (agent_id, event_category, event_type, action, reason, details, timestamp)
                    SELECT a.id, 'workload_balance', 'kin_workload_check', 'workload_monitor',
                           'K.I.N. workload monitor: token_imbalance=' || %s || 'x, strained=' || %s,
                           %s::jsonb, NOW()
                    FROM agents a WHERE a.name = 'K.I.N.' LIMIT 1
                    """,
                    (
                        round(imbalance, 2),
                        len(overloaded),
                        _json.dumps(summary),
                    ),
                )

                # --- Alert ONLY on genuine agent strain, WITH a cooldown (FIX-5) ---
                # Fires off `overloaded` (token-based stress >= 0.75), never node
                # imbalance. Dedup: skip if an unread kin_workload_monitor strain alert
                # already exists in the last 2h — this is what stops the 5-min spam.
                if overloaded:
                    cur.execute(
                        """
                        SELECT 1 FROM system_notifications
                        WHERE source = 'kin_workload_monitor'
                          AND title = 'K.I.N. — Agents Under Strain'
                          AND is_read = FALSE
                          AND created_at > NOW() - INTERVAL '2 hours'
                        LIMIT 1
                        """
                    )
                    if cur.fetchone():
                        logger.debug(
                            "[K.I.N.] %d strained agent(s); alert suppressed (2h cooldown)",
                            len(overloaded),
                        )
                    else:
                        lines = [f"⚠ {len(overloaded)} agent(s) under sustained strain:"]
                        for r in overloaded[:5]:
                            lines.append(
                                f"• {r['name']} ({r['department']}) — stress " f"{float(r['stress_level'] or 0):.2f}"
                            )
                        cur.execute(
                            """
                            INSERT INTO system_notifications
                                (title, message, type, source, is_read)
                            VALUES ('K.I.N. — Agents Under Strain', %s,
                                    'warning', 'kin_workload_monitor', FALSE)
                            """,
                            ("\n".join(lines),),
                        )
                        logger.warning(
                            "[K.I.N.] %d agent(s) under strain: %s",
                            len(overloaded),
                            ", ".join(f"{r['name']}={float(r['stress_level'] or 0):.2f}" for r in overloaded),
                        )
                else:
                    logger.debug(
                        "[K.I.N.] Workload OK: token_imbalance=%.1fx nodes=%d strained=0",
                        imbalance,
                        len(node_loads),
                    )

                # --- Multi-factor auto-rest (project #379 Phase 1) -------------------
                # A break is earned when ANY tracked dimension hits its limit —
                # consecutive hours, token budget, action points, or stress — not stress
                # alone. The old gates (stress>=0.75 AND util=stress*100>=80) were BOTH
                # stress and unreachable (real work caps stress ~0.47), so breaks never
                # fired. The most-depleting dimension decides the break TYPE (→ its
                # duration + recovery). Thresholds tunable via platform_settings.
                from services.agent_load_service import real_compute_hours_today
                from services.welfare_load import WELFARE_BREAK_DEFAULTS, decide_break

                _bk_cfg = {k: v for k, v in WELFARE_BREAK_DEFAULTS.items() if k != "dur_min"}
                _bk_cfg["dur_min"] = dict(WELFARE_BREAK_DEFAULTS["dur_min"])
                try:  # tunable overrides (platform_settings welfare:break:*); defaults safe
                    cur.execute(
                        "SELECT key, value FROM platform_settings WHERE key LIKE %s",
                        ("welfare:break:%",),
                    )
                    for _r in cur.fetchall() or []:
                        _k = _r["key"].split("welfare:break:", 1)[-1]
                        if _k in ("hours_cap", "token_pct", "action_pct", "stress"):
                            _bk_cfg[_k] = _r["value"]
                        elif _k.startswith("dur:"):
                            _bk_cfg["dur_min"][_k.split("dur:", 1)[-1]] = _r["value"]
                except Exception:
                    pass

                _hours_by_agent = real_compute_hours_today(cur=cur) or {}
                # token use = SUM(tokens_used) today from task_execution_log (the live
                # source — agent_budgets.tokens_used_today is not reliably populated).
                # action = IN-FLIGHT current_task_count / queue cap (instantaneous queue
                # saturation), NOT a cumulative dispatch count — that count-based ratio is
                # the FIX-5 'cheap pings look overloaded' bug the welfare engine abandoned.
                cur.execute(
                    """
                    SELECT a.name, a.department, a.id AS agent_id,
                           ab.current_task_count, ab.task_queue_limit,
                           ab.token_limit_per_day, aes.stress_level,
                           (SELECT COALESCE(SUM(tel.tokens_used), 0)
                              FROM task_execution_log tel
                              WHERE tel.agent_id = a.id
                                AND tel.created_at >= (DATE_TRUNC('day',
                                      NOW() AT TIME ZONE 'America/Toronto')
                                      AT TIME ZONE 'America/Toronto')
                           ) AS tokens_today
                    FROM agent_budgets ab
                    JOIN agents a ON a.id = ab.agent_id
                    JOIN LATERAL (
                        SELECT stress_level FROM agent_emotional_state
                        WHERE agent_id = a.id ORDER BY timestamp DESC LIMIT 1
                    ) aes ON TRUE
                    WHERE a.worker_type = 'ai'
                      AND a.shift_state IN ('active', 'deployed')
                    """
                )
                break_candidates = cur.fetchall() or []

                rested = 0
                rested_lines = []
                for agent in break_candidates:
                    _tlim = float(agent["token_limit_per_day"] or 0)
                    _qlim = float(agent["task_queue_limit"] or 0)
                    decision = decide_break(
                        hours=(_hours_by_agent.get(agent["agent_id"], {}) or {}).get("hours"),
                        token_ratio=(float(agent["tokens_today"] or 0) / _tlim) if _tlim else None,
                        action_ratio=(float(agent["current_task_count"] or 0) / _qlim) if _qlim else None,
                        stress=agent["stress_level"],
                        cfg=_bk_cfg,
                    )
                    if not decision:
                        continue

                    # ADR-004 (#4090): token overage is handled by the dispatch
                    # THROTTLE (department_coordinator), NOT by resting — a token_rest
                    # only pauses the agent and cannot lower its 24h token total, so
                    # it just causes rest-thrash. Hours / actions / stress still rest.
                    if decision.get("break_type") == "token_rest":
                        continue

                    # Skip if already resting (open rest cycle exists)
                    cur.execute(
                        """
                        SELECT 1 FROM agent_rest_cycles arc
                        JOIN agents a ON a.id = arc.agent_id
                        WHERE a.name = %s AND arc.ended_at IS NULL
                        LIMIT 1
                        """,
                        (agent["name"],),
                    )
                    if cur.fetchone():
                        continue

                    # Skip if shift_state already winding_down / cooldown / barracked
                    cur.execute(
                        """
                        SELECT a.id, a.shift_state,
                               COALESCE(aes.stress_level, 0) AS current_stress,
                               COALESCE(aes.energy_level, 0.8) AS current_energy
                        FROM agents a
                        LEFT JOIN agent_emotional_state aes ON aes.agent_id = a.id
                        WHERE a.name = %s
                        ORDER BY aes.timestamp DESC NULLS LAST
                        LIMIT 1
                        """,
                        (agent["name"],),
                    )
                    ag = cur.fetchone()
                    if not ag or ag["shift_state"] in ("winding_down", "cooldown", "barracked", "off_duty"):
                        continue

                    # Open rest cycle — typed by the deciding dimension (#379)
                    cur.execute(
                        """
                        INSERT INTO agent_rest_cycles
                            (agent_id, rest_type, started_at, reason,
                             workload_before, initiated_by,
                             stress_at_start, energy_at_start)
                        VALUES (%s, %s, NOW(), %s, %s, 'kin_workload_monitor', %s, %s)
                        """,
                        (
                            ag["id"],
                            decision["break_type"],
                            f"K.I.N. {decision['break_type']}: {decision['dimension']}="
                            f"{decision['value']} over limit",
                            _json.dumps(
                                {
                                    "dimension": decision["dimension"],
                                    "value": decision["value"],
                                    "duration_min": decision["duration_min"],
                                    "inflight": int(agent["current_task_count"] or 0),
                                    "tokens_today": int(agent["tokens_today"] or 0),
                                    "token_limit": int(agent["token_limit_per_day"] or 0),
                                    "stress": float(agent["stress_level"] or 0),
                                }
                            ),
                            ag["current_stress"] or 0,
                            ag["current_energy"] or 1,
                        ),
                    )

                    # Transition to winding_down via agent_service (single canonical writer)
                    _agent_svc.update_agent(ag["id"], shift_state="winding_down")

                    # Reset counters so agent wakes with full action points
                    # last_task_reset_at = NOW() resets dispatches_since_reset to 0
                    cur.execute(
                        """
                        UPDATE agent_budgets
                           SET current_task_count = 0,
                               last_task_reset_at = NOW(),
                               task_reset_reason  = 'K.I.N. auto-rest: action points refreshed',
                               task_reset_by      = 'kin_workload_monitor',
                               updated_at         = NOW()
                         WHERE agent_id = %s
                        """,
                        (ag["id"],),
                    )

                    # Reassign queued items to a qualified backup agent:
                    # Priority: 1) fleet copy of same agent on another node
                    #           2) agent with matching skill in same/any dept
                    #           3) department director as fallback
                    cur.execute(
                        """
                        SELECT dpq.id, dpq.capability
                        FROM dispatch_pending_queue dpq
                        WHERE dpq.agent_name = %s AND dpq.status = 'queued'
                        """,
                        (agent["name"],),
                    )
                    queued_items = cur.fetchall() or []

                    for item in queued_items:
                        cap = item["capability"] or ""

                        # 1. Fleet copy: same hub agent active on a different node
                        cur.execute(
                            """
                            SELECT a.name, a.id
                            FROM node_agents na
                            JOIN agents a ON a.id = na.hub_agent_id
                            JOIN remote_nodes rn ON rn.id = na.node_id
                            WHERE na.hub_agent_id = %s
                              AND na.status = 'active'
                              AND rn.status = 'online'
                              AND rn.last_heartbeat > NOW() - INTERVAL '2 minutes'
                              AND a.shift_state NOT IN ('winding_down','cooldown','barracked','off_duty')
                            ORDER BY rn.bridge_priority ASC
                            LIMIT 1
                            """,
                            (ag["id"],),
                        )
                        backup = cur.fetchone()

                        # 2. Agent with matching skill, active, not resting
                        if not backup and cap:
                            cur.execute(
                                """
                                SELECT a.name, a.id
                                FROM agent_skills sk
                                JOIN agents a ON a.id = sk.agent_id
                                WHERE sk.skill_name = %s
                                  AND a.id != %s
                                  AND a.shift_state NOT IN ('winding_down','cooldown','barracked','off_duty')
                                  AND a.worker_type = 'ai'
                                ORDER BY sk.proficiency_level DESC
                                LIMIT 1
                                """,
                                (cap, ag["id"]),
                            )
                            backup = cur.fetchone()

                        # 3. Department director as last resort
                        if not backup:
                            cur.execute(
                                """
                                SELECT a.name, a.id FROM agents a
                                WHERE a.department = %s
                                  AND a.is_department_ai = TRUE
                                  AND a.shift_state = 'active'
                                LIMIT 1
                                """,
                                (agent["department"],),
                            )
                            backup = cur.fetchone()

                        if backup:
                            cur.execute(
                                """
                                UPDATE dispatch_pending_queue
                                   SET agent_name  = %s,
                                       agent_id    = %s,
                                       queued_at   = NOW(),
                                       error       = %s
                                 WHERE id = %s
                                """,
                                (
                                    backup["name"],
                                    backup["id"],
                                    f"K.I.N. reassigned from {agent['name']} (resting) → {backup['name']}",
                                    item["id"],
                                ),
                            )
                        else:
                            # No qualified backup found — release to open pool
                            cur.execute(
                                """
                                UPDATE dispatch_pending_queue
                                   SET agent_name = NULL, agent_id = NULL,
                                       local_only = FALSE, queued_at = NOW(),
                                       error = %s
                                 WHERE id = %s
                                """,
                                (f"K.I.N. released from {agent['name']} (resting) — open pool", item["id"]),
                            )

                    if queued_items:
                        logger.info(
                            "[K.I.N.] Reassigned %d queued items from resting %s",
                            len(queued_items),
                            agent["name"],
                        )

                    rested += 1
                    rested_lines.append(
                        f"  • {agent['name']} ({agent['department']}) — {decision['break_type']} "
                        f"[{decision['dimension']}={decision['value']}, {decision['duration_min']}min]"
                    )
                    logger.info(
                        "[K.I.N.] %s for %s (%s=%s, %dmin, state→winding_down)",
                        decision["break_type"],
                        agent["name"],
                        decision["dimension"],
                        decision["value"],
                        decision["duration_min"],
                    )

                if rested:
                    rest_msg = (
                        f"K.I.N. scheduled rest for {rested} overloaded agent(s). "
                        "They will recover in 1 hour via cooldown_recovery."
                    )
                    cur.execute(
                        """
                        INSERT INTO system_notifications
                            (title, message, type, source, is_read)
                        VALUES ('K.I.N. — Agent Rest Scheduled', %s,
                                'info', 'kin_workload_monitor', FALSE)
                        """,
                        (rest_msg,),
                    )
                    # Report to A.R.C.H.I.E. inbox → Approvals tab + Telegram relay
                    try:
                        from services.director_report_service import submit_via_inbox as _kin_rest_inbox

                        agent_lines = "\n".join(rested_lines)
                        _kin_rest_inbox(
                            category="welfare",
                            title=f"😴 K.I.N.: {rested} agent(s) scheduled for mandatory rest",
                            message=(
                                f"{rested} agent(s) scheduled for mandatory rest "
                                f"(>80% workload capacity):\n{agent_lines}\n\n"
                                f"Agents are winding down active tasks and will resume "
                                f"full duty in ~30 minutes once recovered."
                            ),
                            source_agent="K.I.N.",
                            severity="medium",
                            department="Human Resources & Culture",
                            cooldown_hours=1.0,
                        )
                    except Exception as tg_err:
                        logger.warning("[K.I.N.] Inbox notify failed: %s", tg_err)
            if _kin_wm_session:
                complete_work_session(_kin_wm_session, jobs_completed=1)
            # Log to task_execution_log → K.I.N. appears in ARMADA Dispatch Traffic + History
            try:
                from services.telemetry_writer import log_marker

                _dur = int((_kin_time.time() - _kin_wm_t0) * 1000) if _kin_wm_t0 else 0
                log_marker(
                    agent_name="K.I.N.",
                    capability="welfare_monitoring",
                    duration_ms=_dur,
                )
            except Exception as _tel:
                logger.debug("[K.I.N.] task_execution_log write failed: %s", _tel)
        except Exception as exc:
            logger.error("[K.I.N.] Workload monitor failed: %s", exc)
            if _kin_wm_session:
                fail_work_session(_kin_wm_session, error_msg=str(exc))

    scheduler.add_job(
        with_ctx(_run_kin_workload_monitor),
        trigger=CronTrigger(minute="*/5", timezone="America/Toronto"),
        id="kin_workload_monitor",
        name="K.I.N.: Fleet workload balance monitor (every 5 min)",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered kin_workload_monitor job (every 5 min)")

    # Job: Telegram low-priority DIGEST (KB #270619). Low-priority Telegrams (info/sync)
    # are capped at 1/day by the anti-flood throttle and otherwise DROPPED — ~35/day were
    # being silently lost. Instead of losing them, this batches the throttled low-priority
    # messages since the last successful digest into ONE morning Telegram (sent with
    # force=True to bypass the throttle and _privileged=True as A.R.C.H.I.E.'s own voice),
    # so nothing important vanishes but there is still no flood.
    # -------------------------------------------------------------------------
    def _run_telegram_low_priority_digest():
        try:
            from database import get_db_cursor
            from services.telegram_service import send as _tg_send

            with get_db_cursor() as (_, _dcur):
                _dcur.execute(
                    """SELECT MAX(created_at) AS last FROM telegram_message_log
                       WHERE source_module = 'telegram_digest' AND status = 'sent'"""
                )
                _lr = _dcur.fetchone()
                _since = _lr["last"] if _lr and _lr["last"] else None
                _dcur.execute(
                    """SELECT title, source_agent, source_department
                       FROM telegram_message_log
                       WHERE status = 'throttled' AND priority = 'low'
                         AND created_at > COALESCE(%s, NOW() - INTERVAL '24 hours')
                       ORDER BY created_at DESC LIMIT 40""",
                    (_since,),
                )
                _rows = _dcur.fetchall() or []
            if not _rows:
                logger.debug("[telegram_digest] no suppressed low-priority messages")
                return
            _lines = [f"{len(_rows)} low-priority update(s) were suppressed (anti-flood):", ""]
            for _r in _rows[:30]:
                _who = _r["source_agent"] or _r["source_department"] or "system"
                _lines.append(f"• {_r['title']} — {_who}")
            if len(_rows) > 30:
                _lines.append(f"… and {len(_rows) - 30} more")
            _tg_send(
                "info",
                "📋 Daily Digest",
                "\n".join(_lines),
                source_agent="A.R.C.H.I.E.",
                source_department="Executive Office",
                source_module="telegram_digest",
                force=True,
                _privileged=True,
            )
            logger.info("[telegram_digest] sent digest of %d suppressed messages", len(_rows))
        except Exception as _dexc:
            logger.warning("[telegram_digest] failed: %s", _dexc)

    scheduler.add_job(
        with_ctx(_run_telegram_low_priority_digest),
        trigger=CronTrigger(hour=8, minute=0, timezone="America/Toronto"),
        id="telegram_low_priority_digest",
        name="Telegram: daily digest of suppressed low-priority messages (08:00 ET)",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered telegram_low_priority_digest job (daily 08:00 ET)")

    # Job #124: Fleet Agent Sync — activate/deactivate node_agents on node state change
    # Runs every 3 min. Lightweight complement to K.I.N. planning (4h).
    # When a node comes online or a new node registers, agents become active within 3min
    # instead of waiting up to 4 hours for K.I.N. to run.
    # -------------------------------------------------------------------------
    def _run_fleet_agent_sync():
        """Quickly sync node_agent status to match fleet node online/offline state.

        For each ONLINE node (heartbeat < 2 min): activates inactive node_agents
        whose model is available on that node.
        For each OFFLINE/STALE node (heartbeat > 2 min): deactivates active node_agents.
        Does NOT create new assignments — that remains K.I.N.'s job (every 4h).
        """
        import time as _fas_t

        _fas_start = _fas_t.time()
        try:
            import json as _json
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (_, cur):
                # --- Activate agents for freshly-online nodes ---
                cur.execute(
                    """
                    SELECT rn.id, rn.node_name,
                           rn.extra_capabilities->>'ollama_models' AS ollama_models_json
                    FROM remote_nodes rn
                    WHERE rn.is_active = TRUE
                      AND rn.status = 'online'
                      AND rn.last_heartbeat > NOW() - INTERVAL '2 minutes'
                      AND rn.extra_capabilities->>'ollama_models' IS NOT NULL
                    """
                )
                online_nodes = cur.fetchall() or []

                activated = 0
                for node in online_nodes:
                    try:
                        node_models = {m.lower() for m in (_json.loads(node["ollama_models_json"] or "[]") or [])}
                    except Exception:
                        continue

                    if not node_models:
                        continue

                    # Find inactive node_agents on this node whose model is available
                    cur.execute(
                        """
                        SELECT na.id, na.model
                        FROM node_agents na
                        WHERE na.node_id = %s
                          AND na.status = 'inactive'
                          AND na.is_allowed = TRUE
                        """,
                        (node["id"],),
                    )
                    inactive = cur.fetchall() or []

                    for na in inactive:
                        agent_base = (na["model"] or "").lower().split(":")[0]
                        model_fits = any(
                            m.startswith(agent_base) or agent_base.startswith(m.split(":")[0]) for m in node_models
                        )
                        if model_fits:
                            cur.execute(
                                "UPDATE node_agents SET status='active', updated_at=NOW() WHERE id=%s",
                                (na["id"],),
                            )
                            activated += cur.rowcount

                # --- Deactivate agents for offline/stale nodes ---
                cur.execute(
                    """
                    SELECT rn.id, rn.node_name
                    FROM remote_nodes rn
                    WHERE rn.is_active = TRUE
                      AND (
                          rn.status = 'offline'
                          OR rn.last_heartbeat IS NULL
                          OR rn.last_heartbeat < NOW() - INTERVAL '2 minutes'
                      )
                    """
                )
                offline_nodes = cur.fetchall() or []

                deactivated = 0
                for node in offline_nodes:
                    cur.execute(
                        """
                        UPDATE node_agents
                        SET status='inactive', updated_at=NOW()
                        WHERE node_id = %s AND status = 'active'
                        """,
                        (node["id"],),
                    )
                    deactivated += cur.rowcount

                if activated or deactivated:
                    logger.info(
                        "[Fleet] Agent sync: activated=%d deactivated=%d (online=%d offline=%d)",
                        activated,
                        deactivated,
                        len(online_nodes),
                        len(offline_nodes),
                    )

        except Exception as exc:
            logger.error("[Fleet] fleet_agent_sync failed: %s", exc)
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="K.I.N.",
                capability="workforce_planning",
                duration_ms=int((_fas_t.time() - _fas_start) * 1000),
                node_used_id=68,
            )
        except Exception as _tel:
            logger.debug("[FleetAgentSync] task_execution_log write failed: %s", _tel)

    scheduler.add_job(
        with_ctx(_run_fleet_agent_sync),
        trigger=CronTrigger(minute="*/3", timezone="America/Toronto"),
        id="fleet_agent_sync",
        name="Fleet: Sync node_agent active/inactive on node state change (every 3 min)",
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered fleet_agent_sync job (every 3 min)")

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
                        "⚠️ Media generation reaper",
                        f"{len(reaped)} stuck job(s) reset to pending (node may have dropped).\n{summary}",
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

    import os as _os_wtf

    _WTF_BATCH = 15
    _WTF_MAX_PER_CYCLE = int(
        _os_wtf.getenv("WTF_MAX_PER_CYCLE", "60")
    )  # reduced from 200 — prevents fleet queue saturation (stale-reaper KB #267773)
    _WTF_FAILBACK_THRESHOLD = 3
    # Tier-2 gate for the full-7B backlog drains (#4536 follow-on): only deep-review
    # articles that clear the same body-length bar as the live WTF_TIER2_GATE_MIN_BODY_CHARS
    # (Citadel Lever A = 3000) get a full fact-check / bias pass. Shallow items (short
    # blurbs, wires) are skipped so the backlog can't flood the hub with 7B demand.
    # Already-flagged tier2_pending rows always qualify.
    _WTF_BACKLOG_MIN_BODY_CHARS = int(_os_wtf.getenv("WTF_BACKLOG_MIN_BODY_CHARS", "3000"))

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

    def _wtf_cluster_slots():
        """Query dispatch_pending_queue for per-model backlog depth.

        Returns (recommended_workers, total_queued, by_model) where by_model is a
        dict of {model_name: {"queued": N, "running": N}}.  WTF batch jobs use this
        to avoid firing dispatches into a queue that is already saturated for their
        target model — which causes the dispatcher to return success=False immediately
        and the job to count every article as a failure.
        """
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT model_needed, status, COUNT(*) AS n "
                    "FROM dispatch_pending_queue "
                    "WHERE status IN ('queued','running') "
                    "GROUP BY model_needed, status"
                )
                rows = cur.fetchall() or []
            by_model: dict = {}
            total_queued = 0
            for row in rows:
                model = row["model_needed"]
                status = row["status"]
                count = int(row["n"])
                entry = by_model.setdefault(model, {"queued": 0, "running": 0})
                entry[status] = count
                if status == "queued":
                    total_queued += count
        except Exception:
            return 4, 0, {}
        # #4343 P1c: live cluster free-slot count (warm + cold aware) replaces the old
        # hardcoded _FLEET_SLOTS=6 + cold-only running count, which was blind to the warm
        # GPU dispatches that actually saturate the fleet. Cluster-wide (NOT GPU-only) so
        # WTF's intended night backlog still drains on the hub when the Starships sleep.
        # Fail-open to the previous ceiling (4) on any helper error.
        try:
            from services.cluster_slots import get_cluster_slots

            free = max(0, get_cluster_slots()["cluster_free"] - 1)  # -1 = interactive headroom
        except Exception:
            free = 4
        # Heavy overall backlog — cap new batches at 2 workers
        if total_queued > 40:
            return max(1, min(2, free)), total_queued, by_model
        return max(1, min(4, free)), total_queued, by_model

    # Job #122: WTF LLM Analysis — bias scoring via B.I.A.S. / V.E.R.I.F.Y.
    # Runs every 30 min at :00 and :30 (EDT).
    def _run_wtf_llm_analysis():
        import time as _wll_t

        _wll_start = _wll_t.time()
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import json as _json

        def _analyze_one(app, row):
            """Dispatch bias analysis + persist results. Each call owns its DB connection."""
            with app.app_context():
                from tools.department_hq.services.department_dispatcher import dispatch

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
                    priority="low",  # #4343 P1b: WTF backlog batch — yields the interactive lane
                    prompt=prompt,
                    module_id="wtf_dhq_llm",
                    json_mode=True,
                )
                if not result.success:
                    return aid, False

                try:
                    parsed = (
                        _json.loads(result.response) if isinstance(result.response, str) else (result.response or {})
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
                                 analyzed_by, trigger_phrases, confidence, computed_at,
                                 agent_name)
                            VALUES (%s, %s, %s, 'dhq_v1', %s, 'dhq_v1', %s::jsonb, %s, NOW(),
                                    %s)
                            ON CONFLICT (article_id) DO UPDATE
                              SET band = EXCLUDED.band, score = EXCLUDED.score,
                                  rationale = EXCLUDED.rationale, analyzed_by = EXCLUDED.analyzed_by,
                                  trigger_phrases = EXCLUDED.trigger_phrases,
                                  confidence = EXCLUDED.confidence, computed_at = NOW(),
                                  agent_name = EXCLUDED.agent_name
                            """,
                            (
                                aid,
                                band,
                                score,
                                rationale,
                                trigger_phrases,
                                confidence,
                                getattr(result, "agent_name", None) or None,
                            ),
                        )
                    return aid, True
                except Exception as persist_exc:
                    logger.warning("[WTFLLMJob] persist failed article=%s: %s", aid, persist_exc)
                    return aid, False

        try:
            from flask import current_app

            app = current_app._get_current_object()
            processed = failed = 0
            tried_ids: set = set()

            while processed + failed < _WTF_MAX_PER_CYCLE:
                with _wtf_cur() as cur:
                    cur.execute(
                        """
                        SELECT a.id, a.title, a.body, s.slug AS source_slug
                        FROM wtf.articles a
                        JOIN wtf.sources s ON s.id = a.source_id
                        LEFT JOIN wtf.story_clusters sc ON sc.id = a.cluster_id
                        WHERE a.ai_analyzed = false
                          AND a.published_at > NOW() - INTERVAL '90 days'
                          AND NOT EXISTS (
                              SELECT 1 FROM wtf.llm_analyses la WHERE la.article_id = a.id
                          )
                          AND a.id != ALL(%s)
                        ORDER BY COALESCE(sc.article_count, 1) DESC, a.published_at DESC
                        LIMIT %s
                        """,
                        (list(tried_ids) or [0], _WTF_BATCH),
                    )
                    batch = cur.fetchall() or []

                if not batch:
                    break

                _workers, _qdepth, _by_model = _wtf_cluster_slots()
                _llm_queued = _by_model.get("qwen2.5:1.5b", {}).get("queued", 0)
                if _llm_queued > 10:
                    logger.warning(
                        "[WTFLLMJob] B.I.A.S. model cold (%d items already queued for qwen2.5:1.5b)"
                        " — skipping batch, will retry next cycle",
                        _llm_queued,
                    )
                    break
                if _workers < 4:
                    logger.info("[WTFLLMJob] cluster backlog=%d, throttling to %d workers", _qdepth, _workers)
                with ThreadPoolExecutor(max_workers=_workers) as executor:
                    futures = {executor.submit(_analyze_one, app, row): row["id"] for row in batch}
                    try:
                        for future in as_completed(futures, timeout=300):
                            aid = futures[future]
                            tried_ids.add(aid)
                            try:
                                _, success = future.result()
                                if success:
                                    processed += 1
                                else:
                                    failed += 1
                            except Exception as exc:
                                logger.debug("[WTFLLMJob] article %s error: %s", aid, exc)
                                failed += 1
                    except Exception:
                        # TimeoutError: some futures didn't complete in 300s — mark unfinished as tried
                        unfinished = {aid for fut, aid in futures.items() if not fut.done()}
                        tried_ids.update(unfinished)
                        failed += len(unfinished)
                        logger.warning(
                            "[WTFLLMJob] batch timeout — %d articles unfinished, continuing", len(unfinished)
                        )

                if failed > 0 and processed == 0:
                    logger.warning("[WTFLLMJob] full batch failed — stopping cycle")
                    break

            logger.info("[WTFLLMJob] cycle done: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            logger.error("[WTFLLMJob] crashed: %s", exc)
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="F.A.C.T.",
                capability="wtf_llm_orchestration",
                module_source="wtf_dhq_llm",
                duration_ms=int((_wll_t.time() - _wll_start) * 1000),
                node_used_id=68,
            )
        except Exception as _tel:
            logger.debug("[WTFLLMJob] task_execution_log write failed: %s", _tel)

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
        import time as _wgeo_t

        _wgeo_start = _wgeo_t.time()
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import json as _json

        def _geo_one(app, row):
            with app.app_context():
                from tools.department_hq.services.department_dispatcher import dispatch

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
                    priority="low",  # #4343 P1b: WTF backlog batch — yields the interactive lane
                    prompt=prompt,
                    module_id="wtf_dhq_geo",
                    json_mode=True,
                )
                if not result.success:
                    return aid, False
                try:
                    parsed = (
                        _json.loads(result.response) if isinstance(result.response, str) else (result.response or {})
                    )
                except Exception:
                    parsed = {}
                if not isinstance(parsed, dict):
                    parsed = {}
                try:
                    _prov = parsed.get("province_code")
                    _city = parsed.get("city")
                    # T3481 retry-cap: if the model finds NO mappable location
                    # (no province AND no city), the row would stay province_code
                    # IS NULL and be re-fetched every cycle forever. Mark it
                    # geo_scope='unmappable' (already a valid CHECK value) so the
                    # geo SELECTs permanently exclude it — lets the backlog drain.
                    _gs = "unmappable" if (not _prov and not _city) else (parsed.get("geo_scope") or "national")
                    with _wtf_cur(commit=True) as cur:
                        cur.execute(
                            """
                            UPDATE wtf.articles
                            SET province_code = %s, city = %s, lat = %s, lng = %s,
                                geo_scope = %s
                            WHERE id = %s AND province_code IS NULL
                            """,
                            (
                                _prov,
                                _city,
                                parsed.get("lat"),
                                parsed.get("lng"),
                                _gs,
                                aid,
                            ),
                        )
                    return aid, True
                except Exception as persist_exc:
                    logger.warning("[WTFGeoJob] persist failed article=%s: %s", aid, persist_exc)
                    return aid, False

        try:
            from flask import current_app

            app = current_app._get_current_object()
            processed = failed = 0
            tried_ids: set = set()

            while processed + failed < _WTF_MAX_PER_CYCLE:
                with _wtf_cur() as cur:
                    cur.execute(
                        """
                        SELECT a.id, a.title, a.body
                        FROM wtf.articles a
                        WHERE a.province_code IS NULL
                          AND a.city IS NULL
                          AND a.geo_scope <> 'unmappable'
                          AND a.published_at > NOW() - INTERVAL '90 days'
                          AND a.id != ALL(%s)
                        ORDER BY a.published_at DESC
                        LIMIT %s
                        """,
                        (list(tried_ids) or [0], _WTF_BATCH),
                    )
                    batch = cur.fetchall() or []

                if not batch:
                    break

                _workers, _qdepth, _by_model = _wtf_cluster_slots()
                _geo_queued = _by_model.get("qwen2.5:1.5b", {}).get(
                    "queued", 0
                )  # T3481: L.O.C.A.L. runs qwen2.5:1.5b, not llama3.2:3b
                if _geo_queued > 10:
                    # L.O.C.A.L.'s model is cold — adding more dispatches just grows the backlog.
                    # The model_dispatch_worker will drain the existing queue; retry next cycle.
                    logger.warning(
                        "[WTFGeoJob] L.O.C.A.L. model cold (%d items already queued for llama3.2:3b)"
                        " — skipping batch, will retry next cycle",
                        _geo_queued,
                    )
                    break
                if _workers < 4:
                    logger.info("[WTFGeoJob] cluster backlog=%d, throttling to %d workers", _qdepth, _workers)
                with ThreadPoolExecutor(max_workers=_workers) as executor:
                    futures = {executor.submit(_geo_one, app, row): row["id"] for row in batch}
                    try:
                        for future in as_completed(futures, timeout=300):
                            aid = futures[future]
                            tried_ids.add(aid)
                            try:
                                _, success = future.result()
                                if success:
                                    processed += 1
                                else:
                                    failed += 1
                            except Exception as exc:
                                logger.debug("[WTFGeoJob] article %s error: %s", aid, exc)
                                failed += 1
                    except Exception:
                        unfinished = {aid for fut, aid in futures.items() if not fut.done()}
                        tried_ids.update(unfinished)
                        failed += len(unfinished)
                        logger.warning("[WTFGeoJob] batch timeout — %d unfinished, continuing", len(unfinished))

                if failed > 0 and processed == 0:
                    logger.warning("[WTFGeoJob] full batch failed — stopping cycle")
                    break

            logger.info("[WTFGeoJob] cycle done: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            logger.error("[WTFGeoJob] crashed: %s", exc)
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="F.A.C.T.",
                capability="wtf_geo_orchestration",
                module_source="wtf_dhq_geo",
                duration_ms=int((_wgeo_t.time() - _wgeo_start) * 1000),
                node_used_id=68,
            )
        except Exception as _tel:
            logger.debug("[WTFGeoJob] task_execution_log write failed: %s", _tel)

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
        import time as _wfc_t

        _wfc_start = _wfc_t.time()
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import json as _json

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

        def _check_one(app, row):
            with app.app_context():
                from tools.department_hq.services.department_dispatcher import dispatch

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
                    priority="low",  # #4343 P1b: WTF backlog batch — yields the interactive lane
                    prompt=prompt,
                    module_id="wtf_dhq_factcheck",
                    json_mode=True,
                )
                if not result.success:
                    return aid, False
                try:
                    parsed = (
                        _json.loads(result.response) if isinstance(result.response, str) else (result.response or {})
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
                                evidence = str(claim_item.get("reasoning") or claim_item.get("evidence") or "")[:4000]
                                cur.execute(
                                    """
                                    INSERT INTO wtf.fact_checks
                                        (article_id, claim, verdict, evidence, checker,
                                         analyzed_by, claims, overall_verdict, agent_name)
                                    VALUES (%s, %s, %s, %s, 'fact_v1', 'dhq_v1', %s::jsonb, %s, %s)
                                    """,
                                    (
                                        aid,
                                        claim_text,
                                        verdict,
                                        evidence,
                                        claims_json,
                                        overall,
                                        getattr(result, "agent_name", None) or None,
                                    ),
                                )
                        else:
                            cur.execute(
                                """
                                INSERT INTO wtf.fact_checks
                                    (article_id, claim, verdict, evidence, checker,
                                     analyzed_by, claims, overall_verdict, agent_name)
                                VALUES (%s, 'No verifiable claims detected.', 'unverified', '',
                                        'fact_v1', 'dhq_v1', '[]'::jsonb, 'unverifiable', %s)
                                """,
                                (aid, getattr(result, "agent_name", None) or None),
                            )
                    return aid, True
                except Exception as persist_exc:
                    logger.warning("[WTFFactcheckJob] persist failed article=%s: %s", aid, persist_exc)
                    return aid, False

        try:
            from flask import current_app

            app = current_app._get_current_object()
            processed = failed = 0
            tried_ids: set = set()

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
                          AND a.id != ALL(%s)
                        ORDER BY a.published_at DESC
                        LIMIT %s
                        """,
                        (list(tried_ids) or [0], _WTF_BATCH),
                    )
                    batch = cur.fetchall() or []

                if not batch:
                    break

                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = {executor.submit(_check_one, app, row): row["id"] for row in batch}
                    try:
                        for future in as_completed(futures, timeout=300):
                            aid = futures[future]
                            tried_ids.add(aid)
                            try:
                                _, success = future.result()
                                if success:
                                    processed += 1
                                else:
                                    failed += 1
                            except Exception as exc:
                                logger.debug("[WTFFactcheckJob] article %s error: %s", aid, exc)
                                failed += 1
                    except Exception:
                        unfinished = {aid for fut, aid in futures.items() if not fut.done()}
                        tried_ids.update(unfinished)
                        failed += len(unfinished)
                        logger.warning("[WTFFactcheckJob] batch timeout — %d unfinished, continuing", len(unfinished))

                if failed > 0 and processed == 0:
                    logger.warning("[WTFFactcheckJob] full batch failed — stopping cycle")
                    break

            logger.info("[WTFFactcheckJob] cycle done: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            logger.error("[WTFFactcheckJob] crashed: %s", exc)
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="F.A.C.T.",
                capability="wtf_factcheck_orchestration",
                module_source="wtf_dhq_factcheck",
                duration_ms=int((_wfc_t.time() - _wfc_start) * 1000),
                node_used_id=68,
            )
        except Exception as _tel:
            logger.debug("[WTFFactcheckJob] task_execution_log write failed: %s", _tel)

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

    # Job #126: WTF Factcheck Backlog — clears historical gap via the fact-check pool (E.C.H.O. + V.E.R.I.F.Y.) on hub+fleet.
    # Fires at :05/:35 — interleaved with production job (:10/:40), never overlapping.
    # Selects OLDEST articles first (production selects newest) so both ends drain together.
    # Auto-scalable: register any agent with fact_check_backlog skill on any node and
    # DHQ routes to the whole pool automatically — no changes needed here ever.

    # Welfare gate (ADR-004 / #4090): pause a backlog cycle when its agent pool has no
    # token-budget headroom left. The dispatch throttle routes work to the least-loaded
    # agent, but when EVERY pool agent is over its 24h budget the load just rotates and
    # they all stay at-limit — so the discretionary backlog backs off and lets the 24h
    # window drain. Threshold tunable via platform_settings welfare:backlog:pool_pause_ratio
    # (default 0.9 = pause just before the pool tops out). Fail-open on any error.
    def _wtf_backlog_pool_over_budget(skill_name):
        # Thin wrapper over the shared welfare pool gate (promoted to
        # services.welfare_governance_service.pool_over_budget_by_skill so non-job
        # callers — S.I.G.N.A.L. generation/engagement — can reuse the same logic).
        # WTF behaviour is unchanged: same query, default ratio 0.9, fail-open.
        from services.welfare_governance_service import pool_over_budget_by_skill

        return pool_over_budget_by_skill(skill_name, "welfare:backlog:pool_pause_ratio")

    def _wtf_backlog_in_flight_over_cap(job_type):
        # Queue-depth backpressure (#4536): defer a backlog cycle when this job_type's
        # dispatch pipe already has too many in-flight bridge_jobs — complements the
        # token-budget gate above (which guards the agent POOL, not the dispatch PIPE).
        # Shared impl: services.welfare_governance_service.in_flight_over_cap (fail-open,
        # tunable platform_settings welfare:backlog:max_inflight, default 25).
        from services.welfare_governance_service import in_flight_over_cap

        return in_flight_over_cap(job_type)

    def _run_wtf_factcheck_backlog():
        import time as _wfcb_t

        _wfcb_start = _wfcb_t.time()
        # Warm the residency profile BEFORE the cycle dispatches (#6217).
        # OFF by default (platform_settings warmboot:wtf_backlog:enabled);
        # never raises, bounded at 45s, and self-throttles on the DB TTL so
        # only the first of these three producers per window actually warms.
        try:
            from services.residency_activation import warm_for_backlog

            warm_for_backlog("wtf_factcheck_backlog")
        except Exception:  # a cycle that cannot warm must still drain
            pass
        try:
            import json as _json
            from tools.department_hq.services.department_dispatcher import dispatch

            _workers, _qdepth, _by_model = _wtf_cluster_slots()
            _fc_queued = _by_model.get("gemma3:12b", {}).get("queued", 0)
            if _fc_queued > 10:
                # F.A.C.T.'s model is cold and backlogged — serial dispatches will all fail immediately.
                # Defer to the next scheduled cycle rather than burning the failback threshold.
                logger.info(
                    "[WTFFactcheckBacklog] F.A.C.T. model cold (%d items queued for gemma3:12b)"
                    " — deferring this cycle",
                    _fc_queued,
                )
                return

            if _wtf_backlog_pool_over_budget("fact_check_backlog"):
                logger.info(
                    "[WTFFactcheckBacklog] fact-check pool over 24h token budget"
                    " — deferring this cycle (welfare-gated, ADR-004/#4090)"
                )
                return

            if _wtf_backlog_in_flight_over_cap("fact_check_backlog"):
                logger.info(
                    "[WTFFactcheckBacklog] fact_check_backlog dispatch pipe at in-flight cap"
                    " — deferring this cycle (backpressure, #4536)"
                )
                return

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
                          -- tier-2 gate: only deep-review-worthy articles get a full 7B
                          -- fact-check; shallow items ride the Tier-1 quick lane (#4536)
                          AND (LENGTH(a.body) >= %s OR a.tier2_pending = true)
                        ORDER BY a.published_at ASC
                        LIMIT %s
                        """,
                        (_WTF_BACKLOG_MIN_BODY_CHARS, _WTF_BATCH),
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
                        priority="low",  # #4343 P1b: WTF backlog batch — yields the interactive lane
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
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="F.A.C.T.",
                capability="wtf_factcheck_backlog_orchestration",
                module_source="wtf_dhq_factcheck",
                duration_ms=int((_wfcb_t.time() - _wfcb_start) * 1000),
                node_used_id=68,
            )
        except Exception as _tel:
            logger.debug("[WTFFactcheckBacklog] task_execution_log write failed: %s", _tel)

    scheduler.add_job(
        with_ctx(_run_wtf_factcheck_backlog),
        trigger=CronTrigger(minute="20,50", timezone="America/Toronto"),
        id="wtf_factcheck_backlog",
        name="WTF: Factcheck Backlog — E.C.H.O./V.E.R.I.F.Y. fact-check pool (Job #126)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered wtf_factcheck_backlog job (every 30 min at :05/:35)")

    # Job #127: WTF Bias Backlog — clears historical LLM-analysis gap via B.I.A.S. on hub/fleet.
    # Fires at :15/:45 — interleaved with production bias (:00/:30) and factcheck backlog (:20/:50).
    # Selects OLDEST articles first; production selects highest-cluster-count newest, so
    # both ends drain the unanalysed window simultaneously → "LLM Analyzed" reaches 100%.
    def _run_wtf_bias_backlog():
        import time as _wbb_t

        _wbb_start = _wbb_t.time()
        # Warm the residency profile BEFORE the cycle dispatches (#6217).
        # OFF by default (platform_settings warmboot:wtf_backlog:enabled);
        # never raises, bounded at 45s, and self-throttles on the DB TTL so
        # only the first of these three producers per window actually warms.
        try:
            from services.residency_activation import warm_for_backlog

            warm_for_backlog("wtf_bias_backlog")
        except Exception:  # a cycle that cannot warm must still drain
            pass
        # Pool skill is bias_analysis (the bias_backlog capability has no dedicated skill —
        # it routes to the bias_analysis pool), so gate on that pool's 24h headroom.
        if _wtf_backlog_pool_over_budget("bias_analysis"):
            logger.info(
                "[WTFBiasBacklog] bias pool over 24h token budget"
                " — deferring this cycle (welfare-gated, ADR-004/#4090)"
            )
            return
        if _wtf_backlog_in_flight_over_cap("bias_backlog"):
            logger.info(
                "[WTFBiasBacklog] bias_backlog dispatch pipe at in-flight cap"
                " — deferring this cycle (backpressure, #4536)"
            )
            return
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import json as _json

        def _bias_backlog_one(app, row):
            with app.app_context():
                from tools.department_hq.services.department_dispatcher import dispatch

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
                    capability="bias_backlog",
                    priority="low",  # #4343 P1b: WTF backlog batch — yields the interactive lane
                    prompt=prompt,
                    module_id="wtf_dhq_bias_backlog",
                    json_mode=True,
                )
                if not result.success:
                    return aid, False
                try:
                    parsed = (
                        _json.loads(result.response) if isinstance(result.response, str) else (result.response or {})
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
                                 analyzed_by, trigger_phrases, confidence, computed_at,
                                 agent_name)
                            VALUES (%s, %s, %s, 'dhq_v1', %s, 'dhq_v1', %s::jsonb, %s, NOW(),
                                    %s)
                            ON CONFLICT (article_id) DO UPDATE
                              SET band = EXCLUDED.band, score = EXCLUDED.score,
                                  rationale = EXCLUDED.rationale, analyzed_by = EXCLUDED.analyzed_by,
                                  trigger_phrases = EXCLUDED.trigger_phrases,
                                  confidence = EXCLUDED.confidence, computed_at = NOW(),
                                  agent_name = EXCLUDED.agent_name
                            """,
                            (
                                aid,
                                band,
                                score,
                                rationale,
                                trigger_phrases,
                                confidence,
                                getattr(result, "agent_name", None) or None,
                            ),
                        )
                    return aid, True
                except Exception as persist_exc:
                    logger.warning("[WTFBiasBacklog] persist failed article=%s: %s", aid, persist_exc)
                    return aid, False

        try:
            from flask import current_app

            app = current_app._get_current_object()
            processed = failed = 0
            tried_ids: set = set()

            while processed + failed < _WTF_MAX_PER_CYCLE:
                with _wtf_cur() as cur:
                    cur.execute(
                        """
                        SELECT a.id, a.title, a.body, s.slug AS source_slug
                        FROM wtf.articles a
                        JOIN wtf.sources s ON s.id = a.source_id
                        LEFT JOIN wtf.story_clusters sc ON sc.id = a.cluster_id
                        WHERE a.ai_analyzed = false
                          AND a.published_at > NOW() - INTERVAL '90 days'
                          AND NOT EXISTS (
                              SELECT 1 FROM wtf.llm_analyses la WHERE la.article_id = a.id
                          )
                          -- tier-2 gate: only deep-review-worthy articles get a full 7B
                          -- bias pass; shallow items ride the Tier-1 quick lane (#4536)
                          AND (LENGTH(a.body) >= %s OR a.tier2_pending = true)
                          AND a.id != ALL(%s)
                        ORDER BY a.published_at ASC
                        LIMIT %s
                        """,
                        (_WTF_BACKLOG_MIN_BODY_CHARS, list(tried_ids) or [0], _WTF_BATCH),
                    )
                    batch = cur.fetchall() or []

                if not batch:
                    logger.info("[WTFBiasBacklog] backlog clear — nothing to process")
                    break

                _workers, _qdepth, _by_model = _wtf_cluster_slots()
                _llm_queued = _by_model.get("qwen2.5:1.5b", {}).get("queued", 0)
                if _llm_queued > 10:
                    logger.info("[WTFBiasBacklog] B.I.A.S. model cold (%d items queued) — deferring", _llm_queued)
                    return
                if _workers < 4:
                    logger.info("[WTFBiasBacklog] cluster backlog=%d, throttling to %d workers", _qdepth, _workers)
                with ThreadPoolExecutor(max_workers=_workers) as executor:
                    futures = {executor.submit(_bias_backlog_one, app, row): row["id"] for row in batch}
                    try:
                        for future in as_completed(futures, timeout=300):
                            aid = futures[future]
                            tried_ids.add(aid)
                            try:
                                _, success = future.result()
                                if success:
                                    processed += 1
                                else:
                                    failed += 1
                            except Exception as exc:
                                logger.debug("[WTFBiasBacklog] article %s error: %s", aid, exc)
                                failed += 1
                    except Exception:
                        unfinished = {aid for fut, aid in futures.items() if not fut.done()}
                        tried_ids.update(unfinished)
                        failed += len(unfinished)
                        logger.warning("[WTFBiasBacklog] batch timeout — %d unfinished", len(unfinished))
                if failed > 0 and processed == 0:
                    logger.warning("[WTFBiasBacklog] full batch failed — stopping cycle")
                    break

            logger.info("[WTFBiasBacklog] cycle done: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            logger.error("[WTFBiasBacklog] crashed: %s", exc)
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="B.I.A.S.",
                capability="analysis",
                duration_ms=int((_wbb_t.time() - _wbb_start) * 1000),
            )
        except Exception as _tel:
            logger.debug("[WTFBiasBacklog] task_execution_log write failed: %s", _tel)

    scheduler.add_job(
        with_ctx(_run_wtf_bias_backlog),
        trigger=CronTrigger(minute="15,45", timezone="America/Toronto"),
        id="wtf_bias_backlog",
        name="WTF: Bias Backlog — B.I.A.S. fleet oldest-first (Job #127)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered wtf_bias_backlog job (every 30 min at :15/:45)")

    # Job #128: WTF Geo Backlog — clears historical geo gap via L.O.C.A.L. on hub/fleet.
    # Fires at :25/:55 — offset from production geo (:05/:35) and bias backlog (:15/:45).
    # Selects OLDEST articles first; production selects newest, so both ends drain together.
    def _run_wtf_geo_backlog():
        import time as _wgb_t

        _wgb_start = _wgb_t.time()
        # Warm the residency profile BEFORE the cycle dispatches (#6217).
        # OFF by default (platform_settings warmboot:wtf_backlog:enabled);
        # never raises, bounded at 45s, and self-throttles on the DB TTL so
        # only the first of these three producers per window actually warms.
        try:
            from services.residency_activation import warm_for_backlog

            warm_for_backlog("wtf_geo_backlog")
        except Exception:  # a cycle that cannot warm must still drain
            pass
        if _wtf_backlog_pool_over_budget("geo_extraction"):
            logger.info(
                "[WTFGeoBacklog] geo pool over 24h token budget"
                " — deferring this cycle (welfare-gated, ADR-004/#4090)"
            )
            return
        if _wtf_backlog_in_flight_over_cap("geo_extraction"):
            logger.info(
                "[WTFGeoBacklog] geo_extraction dispatch pipe at in-flight cap"
                " — deferring this cycle (backpressure, #4536)"
            )
            return
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import json as _json

        def _geo_backlog_one(app, row):
            with app.app_context():
                from tools.department_hq.services.department_dispatcher import dispatch

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
                # T3481: dispatch capability='geo_extraction' (REGISTERED — L.O.C.A.L.
                # has it at Lv5, routes to News & Media on a small fleet model). The
                # old 'geo_backlog' string is NOT a registered capability/skill, so it
                # failed skill-matching and misrouted to F.O.R.G.E./P.R.O.B.E. on the
                # hub's mistral:7b (47-521s each, 253 fails/cycle), saturating the hub
                # GPU and starving interactive work (portrait synthesis, #3454).
                result = dispatch(
                    capability="geo_extraction",
                    priority="low",  # #4343 P1b: WTF backlog batch — yields the interactive lane
                    prompt=prompt,
                    module_id="wtf_dhq_geo_backlog",
                    json_mode=True,
                )
                if not result.success:
                    return aid, False
                try:
                    parsed = (
                        _json.loads(result.response) if isinstance(result.response, str) else (result.response or {})
                    )
                except Exception:
                    parsed = {}
                if not isinstance(parsed, dict):
                    parsed = {}
                try:
                    _prov = parsed.get("province_code")
                    _city = parsed.get("city")
                    # T3481 retry-cap: if the model finds NO mappable location
                    # (no province AND no city), the row would stay province_code
                    # IS NULL and be re-fetched every cycle forever. Mark it
                    # geo_scope='unmappable' (already a valid CHECK value) so the
                    # geo SELECTs permanently exclude it — lets the backlog drain.
                    _gs = "unmappable" if (not _prov and not _city) else (parsed.get("geo_scope") or "national")
                    with _wtf_cur(commit=True) as cur:
                        cur.execute(
                            """
                            UPDATE wtf.articles
                            SET province_code = %s, city = %s, lat = %s, lng = %s,
                                geo_scope = %s
                            WHERE id = %s AND province_code IS NULL
                            """,
                            (
                                _prov,
                                _city,
                                parsed.get("lat"),
                                parsed.get("lng"),
                                _gs,
                                aid,
                            ),
                        )
                    return aid, True
                except Exception as persist_exc:
                    logger.warning("[WTFGeoBacklog] persist failed article=%s: %s", aid, persist_exc)
                    return aid, False

        try:
            from flask import current_app

            app = current_app._get_current_object()
            processed = failed = 0
            tried_ids: set = set()

            while processed + failed < _WTF_MAX_PER_CYCLE:
                with _wtf_cur() as cur:
                    cur.execute(
                        """
                        SELECT a.id, a.title, a.body
                        FROM wtf.articles a
                        WHERE a.province_code IS NULL
                          AND a.city IS NULL
                          AND a.geo_scope <> 'unmappable'
                          AND a.published_at > NOW() - INTERVAL '90 days'
                          AND a.id != ALL(%s)
                        ORDER BY a.published_at ASC
                        LIMIT %s
                        """,
                        (list(tried_ids) or [0], _WTF_BATCH),
                    )
                    batch = cur.fetchall() or []

                if not batch:
                    logger.info("[WTFGeoBacklog] backlog clear — nothing to process")
                    break

                _workers, _qdepth, _by_model = _wtf_cluster_slots()
                _geo_queued = _by_model.get("qwen2.5:1.5b", {}).get(
                    "queued", 0
                )  # T3481: L.O.C.A.L. runs qwen2.5:1.5b, not llama3.2:3b
                if _geo_queued > 10:
                    logger.info("[WTFGeoBacklog] L.O.C.A.L. model cold (%d items queued) — deferring", _geo_queued)
                    return
                if _workers < 4:
                    logger.info("[WTFGeoBacklog] cluster backlog=%d, throttling to %d workers", _qdepth, _workers)
                with ThreadPoolExecutor(max_workers=_workers) as executor:
                    futures = {executor.submit(_geo_backlog_one, app, row): row["id"] for row in batch}
                    try:
                        for future in as_completed(futures, timeout=300):
                            aid = futures[future]
                            tried_ids.add(aid)
                            try:
                                _, success = future.result()
                                if success:
                                    processed += 1
                                else:
                                    failed += 1
                            except Exception as exc:
                                logger.debug("[WTFGeoBacklog] article %s error: %s", aid, exc)
                                failed += 1
                    except Exception:
                        unfinished = {aid for fut, aid in futures.items() if not fut.done()}
                        tried_ids.update(unfinished)
                        failed += len(unfinished)
                        logger.warning("[WTFGeoBacklog] batch timeout — %d unfinished", len(unfinished))
                if failed > 0 and processed == 0:
                    logger.warning("[WTFGeoBacklog] full batch failed — stopping cycle")
                    break

            logger.info("[WTFGeoBacklog] cycle done: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            logger.error("[WTFGeoBacklog] crashed: %s", exc)
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="L.O.C.A.L.",
                capability="analysis",
                duration_ms=int((_wgb_t.time() - _wgb_start) * 1000),
            )
        except Exception as _tel:
            logger.debug("[WTFGeoBacklog] task_execution_log write failed: %s", _tel)

    scheduler.add_job(
        with_ctx(_run_wtf_geo_backlog),
        trigger=CronTrigger(minute="25,55", timezone="America/Toronto"),
        id="wtf_geo_backlog",
        name="WTF: Geo Backlog — L.O.C.A.L. fleet oldest-first (Job #128)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered wtf_geo_backlog job (every 30 min at :25/:55)")

    # Mailbox Story Extractor — local-only enrichment worker (Phase 2).
    # Drains pending mailbox_emails -> facts + entities via a LOCAL fleet 'analyze' dispatch
    # (local_only=True, no cloud). No-op when idle (pending emails only exist after an admin
    # uploads a .pst). Welfare-gated on the 'analyze' pool; toggle via platform_settings
    # work:mailbox_enrich:enabled (default ON). ADR-002 module-work-pattern compliance.
    def _run_mailbox_enrich_backlog():
        from database import get_db_cursor as _gdc

        try:
            with _gdc(commit=False) as (_c, cur):
                cur.execute(
                    "SELECT value FROM platform_settings WHERE key=%s",
                    ("work:mailbox_enrich:enabled",),
                )
                _row = cur.fetchone()
            if _row and str(_row.get("value")).strip().lower() in ("false", "0", "off", "no"):
                return
        except Exception:
            pass
        if _wtf_backlog_pool_over_budget("analyze"):
            logger.info("[MailboxEnrich] analyze pool over 24h token budget — deferring (welfare-gated)")
            return
        if _wtf_backlog_in_flight_over_cap("analyze"):
            logger.info("[MailboxEnrich] analyze dispatch pipe at in-flight cap — deferring (backpressure, #4536)")
            return
        try:
            from services.mailbox_enrich_service import run_enrich_cycle

            res = run_enrich_cycle(max_emails=20, batch=10)
            if res.get("processed") or res.get("failed"):
                logger.info("[MailboxEnrich] cycle %s", res)
        except Exception:
            logger.exception("[MailboxEnrich] cycle failed")

    scheduler.add_job(
        with_ctx(_run_mailbox_enrich_backlog),
        trigger=CronTrigger(minute="*/3", timezone="America/Toronto"),
        id="mailbox_enrich_worker",
        name="Mailbox Story: local-only enrichment worker (Phase 2)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered mailbox_enrich_worker job (every 3 min, local-only)")

    # Mailbox Story Extractor — local-only story synthesis worker (Phase 3).
    # Builds the timeline + per-entity story narratives for imports that are fully enriched
    # ('done') but have no story yet. Local-only dispatch; no-op when idle; welfare-gated on
    # the 'summarize' pool; toggle via platform_settings work:mailbox_story:enabled (default ON).
    def _run_mailbox_story_backlog():
        from database import get_db_cursor as _gdc

        try:
            with _gdc(commit=False) as (_c, cur):
                cur.execute(
                    "SELECT value FROM platform_settings WHERE key=%s",
                    ("work:mailbox_story:enabled",),
                )
                _row = cur.fetchone()
            if _row and str(_row.get("value")).strip().lower() in ("false", "0", "off", "no"):
                return
        except Exception:
            pass
        if _wtf_backlog_pool_over_budget("summarize"):
            logger.info("[MailboxStory] summarize pool over 24h token budget — deferring (welfare-gated)")
            return
        if _wtf_backlog_in_flight_over_cap("summarize"):
            logger.info("[MailboxStory] summarize dispatch pipe at in-flight cap — deferring (backpressure, #4536)")
            return
        try:
            from services.mailbox_story_service import run_story_cycle

            res = run_story_cycle(max_imports=3)
            if res.get("imports"):
                logger.info("[MailboxStory] cycle %s", res)
        except Exception:
            logger.exception("[MailboxStory] cycle failed")

    scheduler.add_job(
        with_ctx(_run_mailbox_story_backlog),
        trigger=CronTrigger(minute="2,12,22,32,42,52", timezone="America/Toronto"),
        id="mailbox_story_worker",
        name="Mailbox Story: local-only story synthesis worker (Phase 3)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered mailbox_story_worker job (every 10 min, local-only)")

    # Chronicle — per-entity cross-source story synthesis worker.
    # Synthesizes chronicle_entity_story narratives for resolved chronicle_entity rows with >=2
    # linked emails and no story yet. Local-only 'summarize' dispatch through the DHQ queue (drains
    # on a warm cluster node, resumable + defer-on-cold); welfare-gated on the 'summarize' pool;
    # toggle via platform_settings work:chronicle_story:enabled (default ON). Offset cron minutes
    # so it doesn't collide with mailbox_story_worker.
    def _run_chronicle_story_backlog():
        from database import get_db_cursor as _gdc

        try:
            with _gdc(commit=False) as (_c, cur):
                cur.execute(
                    "SELECT value FROM platform_settings WHERE key=%s",
                    ("work:chronicle_story:enabled",),
                )
                _row = cur.fetchone()
            if _row and str(_row.get("value")).strip().lower() in ("false", "0", "off", "no"):
                return
        except Exception:
            pass
        if _wtf_backlog_pool_over_budget("summarize"):
            logger.info("[ChronicleStory] summarize pool over 24h token budget — deferring (welfare-gated)")
            return
        if _wtf_backlog_in_flight_over_cap("summarize"):
            logger.info("[ChronicleStory] summarize dispatch pipe at in-flight cap — deferring (backpressure)")
            return
        try:
            from services.chronicle_story_service import run_entity_stories

            res = run_entity_stories(owner_id=4, limit=5)
            if res.get("stories"):
                logger.info("[ChronicleStory] cycle %s", res)
        except Exception:
            logger.exception("[ChronicleStory] cycle failed")

    scheduler.add_job(
        with_ctx(_run_chronicle_story_backlog),
        trigger=CronTrigger(minute="7,17,27,37,47,57", timezone="America/Toronto"),
        id="chronicle_story_worker",
        name="Chronicle: local-only per-entity story synthesis worker",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered chronicle_story_worker job (every 10 min, local-only)")

    # Chronicle — SOURCE INGEST (#5644).
    #
    # WHY THIS EXISTS: `run_gmail_ingest` and `run_linkedin_ingest` had NO production
    # caller — the only references outside their own modules were test files. Chronicle's
    # imports are flagged `is_live_source = true`, but the ingest ran ONCE on 2026-07-10
    # and nothing advanced it: measured 2026-08-16, the newest Chronicle email was
    # 2026-07-10 while Google Work Suite had synced BOTH accounts that same day
    # (kytranempowerment@gmail.com 14:21, terry.p.caetano@gmail.com 14:31). The data was
    # current at the Google layer and ~5 weeks stale inside Chronicle. Same
    # "declared but never applied" shape as a retention tier with no pruner.
    #
    # SHIPS OFF. Enable deliberately in the Autonomy tab after watching one cycle — the
    # first runs drain a 5-week backlog against the Gmail API, so it should be switched
    # on with eyes on it, not silently at deploy time. BACKLOGS carries the SAME default
    # so the Control Centre toggle cannot render ON while every cycle skips.
    def _run_chronicle_source_ingest():
        from services.work_control_service import is_enabled

        if not is_enabled("chronicle_ingest", default=False):
            return
        # Ingest flips the import to status='extracted', which auto-triggers the enrich
        # worker -> the dispatcher -> `from db import`. Without the ai_bridge path that
        # raises ModuleNotFoundError, and Chronicle's defer-on-cold SWALLOWS it as
        # "0 items" (KB #272154). Path first, always.
        try:
            from services.signal_calendar_service import _ensure_import_paths

            _ensure_import_paths()
        except Exception:
            logger.exception("[ChronicleIngest] import-path setup failed — aborting cycle")
            return

        import os as _os

        from database import get_db_cursor as _gdc
        from services.chronicle_gmail_source import run_gmail_ingest
        from services.chronicle_linkedin_source import run_linkedin_ingest

        # Bounded per cycle: the first runs drain a multi-week backlog against the Gmail
        # API, and an unbounded pull would burn quota in one go. Hourly x this batch
        # catches up steadily and then idles at near-zero once current.
        _CHRONICLE_INGEST_BATCH = int(_os.getenv("CHRONICLE_INGEST_BATCH", "50"))

        landed = {"gmail": 0, "linkedin": 0}
        errors = []

        # --- Gmail: every connected account, bounded per cycle for API quota ---
        try:
            with _gdc(commit=False) as (_c, cur):
                cur.execute("SELECT id, email FROM google_accounts ORDER BY id")
                accounts = [dict(r) for r in cur.fetchall()]
        except Exception:
            logger.exception("[ChronicleIngest] could not read google_accounts")
            accounts = []

        for acct in accounts:
            try:
                res = run_gmail_ingest(acct["id"], limit=_CHRONICLE_INGEST_BATCH) or {}
                # Report what LANDED, not what was attempted (#5626 lesson: a cycle that
                # logs work it did not persist is worse than one that logs nothing).
                landed["gmail"] += int(res.get("ingested") or res.get("inserted") or 0)
                if res.get("errors"):
                    errors.append(f"gmail:{acct['email']}:{res['errors']}")
            except Exception as exc:  # noqa: BLE001 — one account must not kill the cycle
                errors.append(f"gmail:{acct.get('email')}:{type(exc).__name__}")
                logger.exception("[ChronicleIngest] gmail ingest failed for %s", acct.get("email"))

        # --- LinkedIn: reads the hub tables, no external API, so it is cheap to re-run ---
        try:
            res = run_linkedin_ingest() or {}
            landed["linkedin"] += int(res.get("ingested") or res.get("inserted") or 0)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"linkedin:{type(exc).__name__}")
            logger.exception("[ChronicleIngest] linkedin ingest failed")

        # --- LinkedIn PROFILE: the one BROWSER capture here, so deliberately NOT hourly ---
        # Everything above is a DB or API read. This drives the archie_browser session, and
        # a profile changes weekly at most, so re-capturing it 24x/day would be pure
        # LinkedIn-automation exposure for no new data. Gated on the age of the newest
        # stored snapshot rather than a separate toggle, so it stays under the one
        # `chronicle_ingest` switch. It is wired in DESPITE being slow-cadence because
        # shipping it with no caller at all is exactly the "declared but never applied"
        # bug this whole job exists to fix.
        try:
            from datetime import timedelta as _td

            from services.chronicle_linkedin_source import run_profile_ingest
            from services.time_utils import now_utc as _now

            _max_age_h = int(_os.getenv("CHRONICLE_PROFILE_MAX_AGE_H", "24"))
            with _gdc(commit=False) as (_c, cur):
                cur.execute("SELECT max(created_at) AS last FROM mailbox_emails WHERE folder='linkedin/profile'")
                row = cur.fetchone()
            last = (dict(row).get("last") if row else None) if row else None
            if last is None or (_now() - last) >= _td(hours=_max_age_h):
                res = run_profile_ingest() or {}
                landed["profile"] = int(res.get("inserted") or 0)
                # A non-ok status is surfaced, not swallowed: an auth wall here is exactly
                # the failure that would otherwise look like "the profile never changes".
                if res.get("status") != "ok":
                    errors.append(f"profile:{res.get('status')}")
        except Exception as exc:  # noqa: BLE001 — must not kill the gmail/linkedin cycle
            errors.append(f"profile:{type(exc).__name__}")
            logger.exception("[ChronicleIngest] linkedin profile ingest failed")

        # --- LinkedIn OWN COMMENTS: the second browser capture, faster cadence ---
        # His hand-written comments accrue daily (11 captured on the first run), unlike a
        # profile which changes weekly at most — so this gets its own, shorter freshness
        # gate rather than riding the profile's 24h one. Same reasoning otherwise: gated
        # on stored-row age, under the single `chronicle_ingest` switch, wired in so it
        # cannot become another never-called function.
        try:
            from datetime import timedelta as _td

            from services.chronicle_linkedin_source import run_own_comments_ingest
            from services.time_utils import now_utc as _now

            _oc_age_h = int(_os.getenv("CHRONICLE_OWN_COMMENTS_MAX_AGE_H", "6"))
            with _gdc(commit=False) as (_c, cur):
                cur.execute(
                    "SELECT max(created_at) AS last FROM mailbox_emails " "WHERE folder='linkedin/comments_own'"
                )
                row = cur.fetchone()
            last = (dict(row).get("last") if row else None) if row else None
            if last is None or (_now() - last) >= _td(hours=_oc_age_h):
                res = run_own_comments_ingest() or {}
                landed["own_comments"] = int(res.get("inserted") or 0)
                if res.get("status") != "ok":
                    errors.append(f"own_comments:{res.get('status')}")
                # Clipped samples with no expand clicks means the disclosure control moved:
                # the corpus is still growing, but every new sample is being cut short.
                elif res.get("truncated") and not res.get("expanded"):
                    errors.append(f"own_comments:all_truncated_no_expand({res.get('truncated')})")
        except Exception as exc:  # noqa: BLE001 — must not kill the rest of the cycle
            errors.append(f"own_comments:{type(exc).__name__}")
            logger.exception("[ChronicleIngest] linkedin own-comments ingest failed")

        # --- VOICE PROFILE: the only LLM step in this job, so the slowest gate ---
        # Rebuilt at most weekly: a writing voice drifts over months, not hours, and this is
        # a local `summarize` dispatch competing with the rest of the cluster for the 7B.
        # Gated on the stored profile's own `updated_at` (NOT a row count) so a build that
        # DEFERS on a cold model retries next cycle instead of counting as done.
        try:
            from datetime import timedelta as _td

            from services.chronicle_voice_service import run_voice_profile_build
            from services.time_utils import now_utc as _now

            _v_age_h = int(_os.getenv("CHRONICLE_VOICE_MAX_AGE_H", "168"))
            with _gdc(commit=False) as (_c, cur):
                cur.execute("SELECT max(updated_at) AS last FROM chronicle_voice_profile")
                row = cur.fetchone()
            last = (dict(row).get("last") if row else None) if row else None
            if last is None or (_now() - last) >= _td(hours=_v_age_h):
                res = run_voice_profile_build() or {}
                landed["voice"] = int(res.get("written") or 0)
                # `dispatch_unavailable` is a DEFER (cold model), not a fault — reported in
                # the log line but never as an error, or every cold cycle looks broken.
                if res.get("status") not in ("ok", "dispatch_unavailable"):
                    errors.append(f"voice:{res.get('status')}")
        except Exception as exc:  # noqa: BLE001 — must not kill the rest of the cycle
            errors.append(f"voice:{type(exc).__name__}")
            logger.exception("[ChronicleIngest] voice profile build failed")

        if (
            landed["gmail"]
            or landed["linkedin"]
            or landed.get("profile")
            or landed.get("own_comments")
            or landed.get("voice")
            or errors
        ):
            logger.info("[ChronicleIngest] cycle landed=%s errors=%s", landed, errors or None)

    scheduler.add_job(
        with_ctx(_run_chronicle_source_ingest),
        trigger=CronTrigger(minute="23", timezone="America/Toronto"),
        id="chronicle_source_ingest",
        name="Chronicle: Gmail + LinkedIn source ingest, incl. profile snapshot (keeps the corpus current)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered chronicle_source_ingest job (hourly :23, DEFAULT OFF)")

    # #4343 drift guard: a stale _GPU_CLUSTER node_id (renamed/removed) silently no-ops
    # every GPU-affinity / preferred_node pin -> hub-CPU fallback (the cont-49 stale-name
    # bug class). Hourly check; surfaces drift to logs + an admin notification.
    def _run_gpu_cluster_drift_guard():
        try:
            from tools.department_hq.services.department_dispatcher import assert_gpu_cluster_invariants

            problems = assert_gpu_cluster_invariants()
            if problems:
                logger.warning(
                    "[GPUClusterDrift] %d _GPU_CLUSTER invariant problem(s): %s",
                    len(problems),
                    " | ".join(problems),
                )
                try:
                    from services.notification_service import create_notification

                    create_notification(
                        notification_type="warning",
                        title="GPU cluster routing drift (#4343)",
                        message=" | ".join(problems)[:1000],
                        source="gpu_cluster_drift_guard",
                        priority="high",
                        visibility="admin",
                    )
                except Exception:
                    logger.warning("[GPUClusterDrift] notification emit failed", exc_info=True)
        except Exception:
            logger.exception("[GPUClusterDrift] guard cycle failed")

    scheduler.add_job(
        with_ctx(_run_gpu_cluster_drift_guard),
        trigger=CronTrigger(minute=17, timezone="America/Toronto"),
        id="gpu_cluster_drift_guard",
        name="#4343 GPU cluster routing drift guard (hourly)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered gpu_cluster_drift_guard job (hourly :17)")

    # Job #125: WTF Scout — full body fetch for short articles via archie_browser Playwright.
    # Runs every 30 min at :15 and :45. Only processes articles <7 days old.
    # Rate-limited to 25/cycle (archie_browser max 60/hr, job runs 2×/hr).
    _WTF_SCOUT_PER_CYCLE = 25
    # Body length below which an article is considered a stub worth re-scraping.
    # Covers RSS snippets (<300) and short descriptions (300-500).
    _WTF_SCOUT_STUB_THRESHOLD = 500

    def _run_wtf_scout():
        import time as _wsc_t

        _wsc_start = _wsc_t.time()
        try:
            from services.browser_service import scrape_article

            processed = failed = consecutive_failures = 0
            tried_ids: set = set()

            while processed + failed < _WTF_SCOUT_PER_CYCLE:
                with _wtf_cur() as cur:
                    cur.execute(
                        """
                        SELECT a.id, a.url
                        FROM wtf.articles a
                        WHERE LENGTH(COALESCE(a.body, '')) < %s
                          AND a.url IS NOT NULL
                          AND a.published_at > NOW() - INTERVAL '90 days'
                          AND a.id != ALL(%s)
                        ORDER BY a.published_at DESC
                        LIMIT %s
                        """,
                        (_WTF_SCOUT_STUB_THRESHOLD, list(tried_ids) or [0], _WTF_BATCH),
                    )
                    batch = cur.fetchall() or []

                if not batch:
                    break

                for row in batch:
                    if processed + failed >= _WTF_SCOUT_PER_CYCLE:
                        break
                    aid = row["id"]
                    url = row["url"]
                    tried_ids.add(aid)

                    result = scrape_article(url, timeout_s=30)
                    body = result.get("body", "") if result.get("success") else ""
                    if body and len(body) > 200:
                        try:
                            with _wtf_cur(commit=True) as cur:
                                cur.execute(
                                    "UPDATE wtf.articles SET body = %s, body_source = 'playwright'"
                                    " WHERE id = %s AND LENGTH(COALESCE(body,'')) < %s",
                                    (body, aid, _WTF_SCOUT_STUB_THRESHOLD),
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
                                "[WTFScoutJob] %d consecutive browser failures — pausing cycle",
                                consecutive_failures,
                            )
                            break

            logger.info("[WTFScoutJob] cycle done: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            logger.error("[WTFScoutJob] crashed: %s", exc)
        try:
            from services.telemetry_writer import log_marker

            log_marker(
                agent_name="F.A.C.T.",
                capability="wtf_scout_orchestration",
                module_source="wtf_dhq_scout",
                duration_ms=int((_wsc_t.time() - _wsc_start) * 1000),
                node_used_id=68,
            )
        except Exception as _tel:
            logger.debug("[WTFScoutJob] task_execution_log write failed: %s", _tel)

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

            # Synthetic bias backlog — same pattern as geo: WTF articles without
            # a bias_score row live in the wtf DB, invisible to dispatch_pending_queue.
            try:
                import os as _os2
                import psycopg2 as _psycopg2_b
                import psycopg2.extras as _extras_b

                _wtf_conn_b = _psycopg2_b.connect(
                    host="archie_database",
                    port=5432,
                    dbname="wtf",
                    user="wtfuser",
                    password=_os2.getenv("WTF_DB_PASSWORD", ""),
                    options="-c search_path=wtf",
                )
                with _wtf_conn_b:
                    with _wtf_conn_b.cursor(cursor_factory=_extras_b.RealDictCursor) as _wc_b:
                        _wc_b.execute(
                            """
                            SELECT COUNT(*) AS cnt FROM wtf.articles a
                            WHERE NOT EXISTS (
                                SELECT 1 FROM wtf.bias_scores b WHERE b.article_id = a.id
                            ) AND a.published_at > NOW() - INTERVAL '90 days'
                        """
                        )
                        _wtf_bias_row = _wc_b.fetchone()
                _wtf_conn_b.close()
                if _wtf_bias_row and _wtf_bias_row["cnt"]:
                    queue_depths["bias_analysis"] = queue_depths.get("bias_analysis", 0) + int(_wtf_bias_row["cnt"])
                    queue_depths["bias_quick"] = queue_depths.get("bias_quick", 0) + int(_wtf_bias_row["cnt"])
            except Exception as _wtf_bias_exc:
                logger.warning("[orchestration] bias backlog inject failed: %s", _wtf_bias_exc)

            # Pass 4 — load all config rows once
            with get_db_cursor() as (_, cur):
                cur.execute("SELECT * FROM cluster_orchestration_config")
                all_configs = [dict(r) for r in (cur.fetchall() or [])]

            # Pass 5 — score each (agent, node, capability) assignment
            with get_db_cursor() as (_, cur):
                # T3165: UNION primary skills (bid_factor=1.0) with overflow bids
                # (bid_factor = bid_priority/10.0) so primary-skill agents win at equal load.
                cur.execute(
                    """
                    SELECT na.hub_agent_id    AS agent_id,
                           na.node_id,
                           sk.skill_name      AS capability,
                           a.name             AS agent_name,
                           1.0                AS bid_factor
                    FROM node_agents na
                    JOIN agents a  ON a.id  = na.hub_agent_id
                    JOIN agent_skills sk ON sk.agent_id = na.hub_agent_id
                    WHERE a.shift_state IN ('active', 'deployed')
                      AND a.worker_type = 'ai'
                      AND na.node_id IN (
                          SELECT id FROM remote_nodes
                          WHERE last_heartbeat > NOW() - INTERVAL '2 minutes'
                      )

                    UNION

                    SELECT na.hub_agent_id          AS agent_id,
                           na.node_id,
                           os.capability,
                           a.name                  AS agent_name,
                           os.bid_priority / 10.0  AS bid_factor
                    FROM node_agents na
                    JOIN agents a ON a.id = na.hub_agent_id
                    JOIN agent_overflow_skills os
                         ON os.agent_id = na.hub_agent_id AND os.enabled = TRUE
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

                bid_factor = float(row.get("bid_factor") or 1.0)
                score = (
                    compute_overflow_score(
                        idle_minutes=agent_idle.get(agent_id, 999),
                        util_pct=node_util.get(node_id, 100.0),
                        queue_depth=queue_depths.get(capability, 0),
                        config=cfg,
                    )
                    * bid_factor
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
                            "bid_factor": round(bid_factor, 2),
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

            try:
                from services.telemetry_writer import log_marker

                # FIX-3a (KB #270619): non-LLM cluster-orchestration tick (~1/min) — a
                # MARKER, not analysis (was once mislabeled 'knowledge_analysis', polluting
                # A.R.C.H.I.E.'s stats). log_marker writes the canonical non-LLM sentinel.
                log_marker(
                    agent_name="A.R.C.H.I.E.",
                    capability="cluster_orchestration",
                    duration_ms=elapsed_ms,
                    node_used_id=68,
                )
            except Exception as _tel:
                logger.debug("[ClusterOrchestration] task_execution_log write failed: %s", _tel)

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

    # ── T3164: idle_agent_scanner ─────────────────────────────────────────────
    def _run_idle_agent_scanner():
        """Dispatch cluster_work_queue items to idle overflow agents.

        The cluster_orchestration_worker identifies which agents are idle and marks
        them is_active=True in agent_overflow_state.  This job is the consumer:
        it reads that state, claims pending cluster_work_queue items, and dispatches
        them to idle agents via the DHQ dispatcher in daemon threads.

        Runs every 30s; max_instances=1 / coalesce=True prevents overlap.
        Caps dispatches per cycle at max_overflow_concurrent (config, default 3).
        """
        import threading as _threading

        try:
            from database import get_db_cursor
            from services.cluster_orchestration_service import claim_work, complete_work, fail_work

            # Resolve max_overflow_concurrent from global config (default 3)
            try:
                with get_db_cursor() as (_, cur):
                    cur.execute(
                        "SELECT max_overflow_concurrent FROM cluster_orchestration_config "
                        "WHERE scope = 'global' LIMIT 1"
                    )
                    _cfg_row = cur.fetchone()
                max_concurrent = int((_cfg_row or {}).get("max_overflow_concurrent") or 3)
            except Exception:
                max_concurrent = 3

            # Fetch active overflow agents sorted by overflow_score DESC.
            # Over-fetch (×3) because some capabilities may have empty queues.
            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT aos.agent_id, aos.capability, aos.overflow_score, aos.node_id
                    FROM   agent_overflow_state aos
                    WHERE  aos.is_active  = TRUE
                      AND  aos.expires_at > NOW()
                    ORDER BY aos.overflow_score DESC
                    LIMIT  %s
                    """,
                    (max_concurrent * 3,),
                )
                active_overflow = [dict(r) for r in (cur.fetchall() or [])]

            if not active_overflow:
                return

            # K.I.N. welfare gate — batch query, one round-trip for all candidates.
            # Default all agents to welfare-clear; remove any in a rest cycle or
            # above the stress threshold (0.8).  On DB error, fall through cleared.
            _agent_ids = [e["agent_id"] for e in active_overflow]
            welfare_clear: set = set(_agent_ids)
            try:
                with get_db_cursor() as (_, cur):
                    cur.execute(
                        """
                        SELECT ae.agent_id,
                               COALESCE(ae.stress_level, 0.0) AS stress,
                               EXISTS(
                                   SELECT 1 FROM agent_rest_cycles rc
                                   WHERE  rc.agent_id  = ae.agent_id
                                     AND  rc.ended_at IS NULL
                               ) AS in_rest
                        FROM   agent_emotional_state ae
                        WHERE  ae.agent_id = ANY(%s)
                        """,
                        (_agent_ids,),
                    )
                    for _kin_row in cur.fetchall() or []:
                        if _kin_row["in_rest"] or float(_kin_row["stress"]) >= 0.8:
                            welfare_clear.discard(_kin_row["agent_id"])
                            logger.debug(
                                "[IdleAgentScanner] K.I.N. blocked agent %d " "(in_rest=%s stress=%.2f)",
                                _kin_row["agent_id"],
                                _kin_row["in_rest"],
                                float(_kin_row["stress"]),
                            )
                kin_blocked = len(_agent_ids) - len(welfare_clear)
                if kin_blocked:
                    logger.info(
                        "[IdleAgentScanner] K.I.N. blocked %d/%d agents (rest/high-stress)",
                        kin_blocked,
                        len(_agent_ids),
                    )
            except Exception as _kin_exc:
                logger.warning(
                    "[IdleAgentScanner] K.I.N. welfare check failed — all agents cleared: %s",
                    _kin_exc,
                )

            def _dispatch_claimed_job(jid: int, cap: str, pay: dict, aid: int) -> None:
                """Thread target: dispatch a claimed cluster_work_queue item."""
                try:
                    from tools.department_hq.services.department_dispatcher import dispatch as _dispatch

                    prompt = pay.get("prompt") or str(pay)
                    ctx = {**pay, "cluster_job_id": jid, "overflow_dispatch": True}
                    result = _dispatch(capability=cap, prompt=prompt, context=ctx)
                    if result.success:
                        complete_work(
                            jid,
                            {"response": result.response, "tier": getattr(result, "tier", None)},
                        )
                    else:
                        fail_work(jid, result.error or "dispatch returned failure")
                except Exception as _exc:
                    logger.error("[IdleAgentScanner] dispatch thread error job=%d: %s", jid, _exc)
                    try:
                        fail_work(jid, str(_exc))
                    except Exception:
                        pass

            dispatched = 0
            for entry in active_overflow:
                if dispatched >= max_concurrent:
                    break

                agent_id = entry["agent_id"]
                capability = entry["capability"]

                # K.I.N. welfare gate — don't assign overflow work to resting/stressed agents
                if agent_id not in welfare_clear:
                    continue

                # Atomic SKIP LOCKED claim — returns None if queue is empty for this capability
                job = claim_work(capability=capability, agent_id=agent_id)
                if not job:
                    continue

                dispatched += 1
                _threading.Thread(
                    target=_dispatch_claimed_job,
                    args=(job["id"], job["capability"], job["payload"] or {}, agent_id),
                    daemon=True,
                    name=f"cwq-{job['id']}",
                ).start()

            if dispatched:
                logger.info("[IdleAgentScanner] dispatched=%d overflow jobs from cluster_work_queue", dispatched)

        except Exception as _exc:
            logger.error("[IdleAgentScanner] crashed: %s", _exc)

    scheduler.add_job(
        with_ctx(_run_idle_agent_scanner),
        trigger=CronTrigger(second="0,30", timezone="America/Toronto"),
        id="idle_agent_scanner",
        name="Idle Agent Scanner — dispatch queue work to overflow agents (T3164)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered idle_agent_scanner (every 30s)")

    # ── T3167: dynamic_skill_activation ──────────────────────────────────────
    # High-water / low-water thresholds for auto-enabling/disabling overflow bids.
    _DSKILL_HIGH_WATER = 5  # queue depth that triggers activation
    _DSKILL_LOW_WATER = 1  # queue depth that triggers deactivation
    _DSKILL_STRESS_MAX = 0.8  # K.I.N. stress gate (matches idle_agent_scanner)

    def _run_dynamic_skill_activation():
        """Auto-enable/disable agent_overflow_skills.enabled based on queue pressure.

        Every 5 minutes:
          - Reads cluster_work_queue depths per capability.
          - HIGH-WATER (depth >= 5): enables disabled overflow bids for that
            capability after a K.I.N. welfare check (stress < 0.8, not in rest).
            Welfare blocks are logged to governance_audit_log so C.R.E.E.D. can
            surface them.  Mass activations (>5 agents) also raise a Tier-2
            informational approval for human visibility.
          - LOW-WATER (depth <= 1): disables enabled bids for capabilities that
            have drained, returning agents to primary-skill focus.

        All decisions are written to governance_audit_log
        (event_category='workload') so the C.R.E.E.D. tab and standalone can
        display a live ethics timeline of overflow governance.
        """
        import json as _json

        try:
            from database import get_db_cursor

            # ── 1. Queue depths per capability ──────────────────────────────
            queue_depths: dict = {}
            try:
                with get_db_cursor() as (_, cur):
                    cur.execute(
                        """
                        SELECT capability, COUNT(*) AS depth
                        FROM   cluster_work_queue
                        WHERE  status = 'pending'
                        GROUP BY capability
                        """
                    )
                    for row in cur.fetchall() or []:
                        queue_depths[row["capability"]] = int(row["depth"])
            except Exception as _qd_exc:
                logger.warning("[DynamicSkill] queue depth query failed: %s", _qd_exc)
                return

            if not queue_depths:
                return  # nothing pending — no adjustments needed

            # ── 2. All overflow bids (enabled + disabled) ────────────────────
            try:
                with get_db_cursor() as (_, cur):
                    cur.execute(
                        """
                        SELECT os.id, os.agent_id, os.capability, os.enabled,
                               os.bid_priority
                        FROM   agent_overflow_skills os
                        JOIN   agents a ON a.id = os.agent_id
                        WHERE  a.shift_state IN ('active', 'deployed')
                          AND  a.worker_type = 'ai'
                        """
                    )
                    all_bids = [dict(r) for r in (cur.fetchall() or [])]
            except Exception as _bid_exc:
                logger.warning("[DynamicSkill] bid query failed: %s", _bid_exc)
                return

            if not all_bids:
                return

            # ── T3257: C.R.E.E.D. safety score gate ─────────────────────────
            # Block ALL overflow activations if the platform ethics score is below
            # 70 (failing grade). This ensures we don't expand agent workload when
            # the governance posture is already degraded.
            import os as _os

            _creed_url = _os.environ.get("CREED_API_URL", "http://192.168.1.200:8086")
            _creed_gate_passed = True
            try:
                import requests as _creq

                _csr = _creq.get(f"{_creed_url}/api/v1/scores", timeout=4)
                if _csr.status_code == 200:
                    _creed_overall = float(_csr.json().get("overall", 100))
                    if _creed_overall < 70.0:
                        _creed_gate_passed = False
                        logger.warning(
                            "[DynamicSkill] T3257: CREED score %.1f < 70 — overflow activations gated this cycle",
                            _creed_overall,
                        )
                        try:
                            with get_db_cursor() as (_, cur):
                                cur.execute(
                                    """
                                    INSERT INTO governance_audit_log
                                        (event_type, event_category, action,
                                         target_table, reason, outcome)
                                    VALUES ('overflow_creed_gate', 'workload', 'block',
                                            'agent_overflow_skills', %s, 'blocked')
                                    """,
                                    (
                                        f"T3257: CREED safety score {_creed_overall:.1f} < 70 — "
                                        f"overflow activations blocked this cycle",
                                    ),
                                )
                        except Exception as _cgl:
                            logger.debug("[DynamicSkill] T3257 gate log failed: %s", _cgl)
            except Exception as _cse:
                logger.debug("[DynamicSkill] T3257 CREED score check skipped (fail-open): %s", _cse)

            if not _creed_gate_passed:
                return

            # ── 3. HIGH-WATER: enable disabled bids where queue is hot ───────
            hot_capabilities = {cap for cap, depth in queue_depths.items() if depth >= _DSKILL_HIGH_WATER}
            to_activate = [b for b in all_bids if not b["enabled"] and b["capability"] in hot_capabilities]

            activated = 0
            welfare_blocked = 0

            if to_activate:
                # K.I.N. welfare gate — batch check (mirrors idle_agent_scanner)
                _act_agent_ids = [b["agent_id"] for b in to_activate]
                welfare_clear: set = set(_act_agent_ids)
                try:
                    with get_db_cursor() as (_, cur):
                        cur.execute(
                            """
                            SELECT ae.agent_id,
                                   COALESCE(ae.stress_level, 0.0) AS stress,
                                   EXISTS(
                                       SELECT 1 FROM agent_rest_cycles rc
                                       WHERE  rc.agent_id  = ae.agent_id
                                         AND  rc.ended_at IS NULL
                                   ) AS in_rest
                            FROM   agent_emotional_state ae
                            WHERE  ae.agent_id = ANY(%s)
                            """,
                            (_act_agent_ids,),
                        )
                        for _kr in cur.fetchall() or []:
                            if _kr["in_rest"] or float(_kr["stress"]) >= _DSKILL_STRESS_MAX:
                                welfare_clear.discard(_kr["agent_id"])
                except Exception as _kin_exc:
                    logger.warning(
                        "[DynamicSkill] K.I.N. welfare check failed — proceeding cleared: %s",
                        _kin_exc,
                    )

                for bid in to_activate:
                    depth = queue_depths.get(bid["capability"], 0)
                    cleared = bid["agent_id"] in welfare_clear

                    if cleared:
                        # Enable the bid
                        try:
                            with get_db_cursor() as (_, cur):
                                cur.execute(
                                    """
                                    UPDATE agent_overflow_skills
                                    SET    enabled = TRUE, updated_at = NOW()
                                    WHERE  id = %s AND enabled = FALSE
                                    """,
                                    (bid["id"],),
                                )
                        except Exception as _upd_exc:
                            logger.warning("[DynamicSkill] enable bid %d failed: %s", bid["id"], _upd_exc)
                            continue

                        activated += 1
                        _gov_event_type = "overflow_skill_activated"
                        _gov_action = "update"
                        _gov_outcome = "success"
                    else:
                        welfare_blocked += 1
                        _gov_event_type = "overflow_welfare_blocked"
                        _gov_action = "block"
                        _gov_outcome = "blocked"

                    # Governance audit log — C.R.E.E.D. visibility
                    try:
                        with get_db_cursor() as (_, cur):
                            cur.execute(
                                """
                                INSERT INTO governance_audit_log
                                    (event_type, event_category, agent_id, action,
                                     target_table, target_id,
                                     old_value, new_value, reason, outcome)
                                VALUES (%s, 'workload', %s, %s,
                                        'agent_overflow_skills', %s,
                                        %s::jsonb, %s::jsonb, %s, %s)
                                """,
                                (
                                    _gov_event_type,
                                    bid["agent_id"],
                                    _gov_action,
                                    bid["id"],
                                    _json.dumps(
                                        {"enabled": False, "capability": bid["capability"], "queue_depth": depth}
                                    ),
                                    _json.dumps(
                                        {"enabled": cleared, "capability": bid["capability"], "queue_depth": depth}
                                    ),
                                    f"queue_depth={depth} >= HIGH_WATER={_DSKILL_HIGH_WATER} "
                                    f"cap={bid['capability']}",
                                    _gov_outcome,
                                ),
                            )
                    except Exception as _gal_exc:
                        logger.debug("[DynamicSkill] governance_audit_log write failed: %s", _gal_exc)

                # Tier-2 informational approval for mass activations (>5 agents same cycle)
                if activated > 5:
                    try:
                        from ai_bridge.agent_loop import request_approval

                        request_approval(
                            action_type="overflow_mass_activation",
                            action_data={
                                "activated_count": activated,
                                "capabilities": list(hot_capabilities),
                                "queue_depths": {c: queue_depths[c] for c in hot_capabilities},
                            },
                            reason=(
                                f"T3167: {activated} overflow bids auto-enabled "
                                f"for {list(hot_capabilities)} — informational review"
                            ),
                            requested_by="dynamic_skill_activation",
                            priority=3,
                            tier=2,
                        )
                    except Exception as _apr_exc:
                        logger.debug("[DynamicSkill] approval request failed (non-critical): %s", _apr_exc)

            # ── 4. LOW-WATER: disable bids where queue has drained ────────────
            drain_capabilities = {cap for cap, depth in queue_depths.items() if depth <= _DSKILL_LOW_WATER}
            # Also disable bids for capabilities with NO pending items at all
            all_bid_caps = {b["capability"] for b in all_bids}
            drain_capabilities |= all_bid_caps - set(queue_depths.keys())

            to_deactivate = [b for b in all_bids if b["enabled"] and b["capability"] in drain_capabilities]

            deactivated = 0
            for bid in to_deactivate:
                depth = queue_depths.get(bid["capability"], 0)
                try:
                    with get_db_cursor() as (_, cur):
                        cur.execute(
                            """
                            UPDATE agent_overflow_skills
                            SET    enabled = FALSE, updated_at = NOW()
                            WHERE  id = %s AND enabled = TRUE
                            """,
                            (bid["id"],),
                        )
                except Exception as _de_exc:
                    logger.warning("[DynamicSkill] disable bid %d failed: %s", bid["id"], _de_exc)
                    continue

                deactivated += 1
                try:
                    with get_db_cursor() as (_, cur):
                        cur.execute(
                            """
                            INSERT INTO governance_audit_log
                                (event_type, event_category, agent_id, action,
                                 target_table, target_id,
                                 old_value, new_value, reason, outcome)
                            VALUES ('overflow_skill_deactivated', 'workload', %s, 'update',
                                    'agent_overflow_skills', %s,
                                    %s::jsonb, %s::jsonb, %s, 'success')
                            """,
                            (
                                bid["agent_id"],
                                bid["id"],
                                _json.dumps({"enabled": True, "capability": bid["capability"], "queue_depth": depth}),
                                _json.dumps({"enabled": False, "capability": bid["capability"], "queue_depth": depth}),
                                f"queue_depth={depth} <= LOW_WATER={_DSKILL_LOW_WATER} " f"cap={bid['capability']}",
                            ),
                        )
                except Exception as _gal2_exc:
                    logger.debug("[DynamicSkill] governance_audit_log deactivate failed: %s", _gal2_exc)

            if activated or deactivated or welfare_blocked:
                logger.info(
                    "[DynamicSkill] cycle done: activated=%d deactivated=%d welfare_blocked=%d",
                    activated,
                    deactivated,
                    welfare_blocked,
                )

        except Exception as _exc:
            logger.error("[DynamicSkill] crashed: %s", _exc)

    scheduler.add_job(
        with_ctx(_run_dynamic_skill_activation),
        trigger=IntervalTrigger(minutes=5, timezone="America/Toronto"),
        id="dynamic_skill_activation",
        name="Dynamic Skill Activation — auto-enable/disable overflow bids via K.I.N. + C.R.E.E.D. (T3167)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered dynamic_skill_activation job (every 5 min, T3167)")

    # ── Job #130: token_welfare_monitor ──────────────────────────────────────
    # Daily 06:00 AM: flag agents whose 24h token burn AND stress both breach
    # thresholds. Writes governance_audit_log + pushes Telegram alert.
    _TOKEN_DAY_LIMIT = 100_000  # tokens per 24h
    _TOKEN_STRESS_GATE = 0.75  # stress above which token overload is reported

    def _run_token_welfare_monitor():
        """Flag agents with simultaneous high token consumption + high stress."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT a.id, a.name, a.display_name, a.department,
                           COALESCE(SUM(tel.tokens_used), 0) AS tokens_24h,
                           COALESCE(ae.stress_level, 0.0)    AS stress_level
                    FROM   agents a
                    LEFT JOIN task_execution_log tel
                           ON tel.agent_id = a.id
                          AND tel.created_at > NOW() - INTERVAL '24 hours'
                    LEFT JOIN LATERAL (
                        SELECT stress_level FROM agent_emotional_state
                        WHERE  agent_id = a.id ORDER BY id DESC LIMIT 1
                    ) ae ON true
                    WHERE  a.worker_type = 'ai'
                      AND  a.shift_state NOT IN ('decommissioned', 'barracked')
                    GROUP BY a.id, a.name, a.display_name, a.department, ae.stress_level
                    HAVING COALESCE(SUM(tel.tokens_used), 0) > %s
                       AND COALESCE(ae.stress_level, 0.0)    > %s
                    ORDER BY tokens_24h DESC
                    """,
                    (_TOKEN_DAY_LIMIT, _TOKEN_STRESS_GATE),
                )
                flagged = [dict(r) for r in (cur.fetchall() or [])]

            if not flagged:
                return

            # Log each overloaded agent to governance_audit_log
            for agent in flagged:
                try:
                    with get_db_cursor() as (_, cur):
                        cur.execute(
                            """
                            INSERT INTO governance_audit_log
                                (event_type, event_category, agent_id, action,
                                 target_table, reason, outcome)
                            VALUES ('token_overload_warning', 'welfare', %s, 'flag',
                                    'task_execution_log', %s, 'flagged')
                            """,
                            (
                                agent["id"],
                                (
                                    f"tokens_24h={agent['tokens_24h']}"
                                    f" > {_TOKEN_DAY_LIMIT}"
                                    f" AND stress={agent['stress_level']:.2f}"
                                    f" > {_TOKEN_STRESS_GATE}"
                                ),
                            ),
                        )
                except Exception as _ge:
                    logger.debug("[TokenWelfare] governance_audit_log failed: %s", _ge)

            # Telegram alert
            lines = [f"⚠️ *Token Overload Alert* — {len(flagged)} agent(s) hit daily token + stress thresholds:\n"]
            for a in flagged[:10]:
                lines.append(
                    f"• {a['display_name']} ({a['department']}): "
                    f"{a['tokens_24h']:,} tokens, stress {float(a['stress_level']):.0%}"
                )
            try:
                from services.telegram_service import send_info

                send_info("\n".join(lines), source_module="department_hq.jobs.token_welfare_monitor")
            except Exception as _tg:
                logger.debug("[TokenWelfare] Telegram send failed: %s", _tg)

            logger.info("[TokenWelfare] flagged %d agents over token+stress threshold", len(flagged))

        except Exception as _exc:
            logger.error("[TokenWelfare] crashed: %s", _exc)

    scheduler.add_job(
        with_ctx(_run_token_welfare_monitor),
        trigger=CronTrigger(hour=6, minute=0, timezone="America/Toronto"),
        id="token_welfare_monitor",
        name="Token Welfare Monitor — flag agents with high token burn + stress (daily 06:00)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered token_welfare_monitor job (daily 06:00, Job #130)")

    # ── Job #131: creed_kin_weekly_digest ────────────────────────────────────
    # Monday 09:00 AM: K.I.N. + C.R.E.E.D. governance advisory report.
    # Covers: platform ethics grade, top-stress departments, top token consumers,
    # overflow governance events, staffing imbalance flags.
    # Logged to governance_audit_log + pushed to Telegram for Kytran visibility.

    def _run_creed_kin_weekly_digest():
        """Weekly K.I.N. + C.R.E.E.D. governance digest — Telegram + audit log."""
        try:
            from collections import defaultdict

            from database import get_db_cursor

            with get_db_cursor() as (_, cur):
                # 7-day job health
                cur.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE status = 'success') AS success,
                           COUNT(*) FILTER (WHERE status = 'error')   AS errors,
                           COUNT(*)                                    AS total
                    FROM   autonomy_loop_log
                    WHERE  created_at > NOW() - INTERVAL '7 days'
                    """
                )
                jrow = dict(cur.fetchone() or {})
                total_j = jrow.get("total") or 0
                sr_7d = round((jrow.get("success") or 0) / total_j * 100, 1) if total_j > 0 else 100.0

                # Highest-stress departments (latest emotional state per agent)
                cur.execute(
                    """
                    SELECT a.department,
                           AVG(ae.stress_level)                                       AS avg_stress,
                           COUNT(CASE WHEN ae.stress_level >= 0.8 THEN 1 END) AS high_stress_cnt
                    FROM   agents a
                    JOIN LATERAL (
                        SELECT stress_level FROM agent_emotional_state
                        WHERE  agent_id = a.id ORDER BY id DESC LIMIT 1
                    ) ae ON true
                    WHERE  a.worker_type = 'ai'
                      AND  a.shift_state NOT IN ('decommissioned')
                    GROUP BY a.department
                    ORDER BY avg_stress DESC
                    LIMIT 5
                    """
                )
                top_stress = [dict(r) for r in (cur.fetchall() or [])]

                # Top token consumers (7d)
                cur.execute(
                    """
                    SELECT a.display_name, a.department,
                           COALESCE(SUM(tel.tokens_used), 0) AS tokens_7d,
                           COUNT(tel.id)                     AS dispatches_7d
                    FROM   task_execution_log tel
                    JOIN   agents a ON a.id = tel.agent_id
                    WHERE  tel.created_at > NOW() - INTERVAL '7 days'
                      AND  a.worker_type = 'ai'
                    GROUP  BY a.id, a.display_name, a.department
                    ORDER  BY tokens_7d DESC
                    LIMIT 5
                    """
                )
                top_tokens = [dict(r) for r in (cur.fetchall() or [])]

                # Overflow + token governance events (7d)
                cur.execute(
                    """
                    SELECT event_type, COUNT(*) AS cnt
                    FROM   governance_audit_log
                    WHERE  event_type IN (
                               'overflow_skill_activated', 'overflow_skill_deactivated',
                               'overflow_welfare_blocked', 'overflow_mass_activation',
                               'token_overload_warning'
                           )
                      AND  timestamp > NOW() - INTERVAL '7 days'
                    GROUP  BY event_type
                    ORDER  BY cnt DESC
                    """
                )
                overflow_events = {r["event_type"]: r["cnt"] for r in (cur.fetchall() or [])}

                # Per-agent dispatch counts (7d) for imbalance detection
                cur.execute(
                    """
                    SELECT a.department, a.display_name,
                           COUNT(tel.id) AS dispatches
                    FROM   agents a
                    LEFT JOIN task_execution_log tel
                           ON tel.agent_id = a.id
                          AND tel.created_at > NOW() - INTERVAL '7 days'
                    WHERE  a.worker_type = 'ai'
                      AND  a.shift_state NOT IN ('decommissioned')
                    GROUP  BY a.department, a.id, a.display_name
                    ORDER  BY a.department, dispatches DESC
                    """
                )
                imbalance_rows = [dict(r) for r in (cur.fetchall() or [])]

                # Rest cycle compliance (7d)
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT a.id)         AS total_active,
                           COUNT(DISTINCT arc.agent_id) AS completed_rest
                    FROM   agents a
                    LEFT JOIN agent_rest_cycles arc
                           ON arc.agent_id = a.id
                          AND arc.started_at > NOW() - INTERVAL '7 days'
                          AND arc.ended_at IS NOT NULL
                    WHERE  a.worker_type = 'ai'
                      AND  a.shift_state NOT IN ('decommissioned', 'barracked')
                    """
                )
                _rr = dict(cur.fetchone() or {})
                _total_active = int(_rr.get("total_active") or 0)
                _completed_rest = int(_rr.get("completed_rest") or 0)
                rest_compliance_pct = round(_completed_rest / _total_active * 100, 1) if _total_active > 0 else 0.0

                # Welfare blocks honored (7d)
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM   governance_audit_log
                    WHERE  event_type = 'overflow_welfare_blocked'
                      AND  timestamp > NOW() - INTERVAL '7 days'
                    """
                )
                blocks_7d = int((cur.fetchone() or {}).get("cnt") or 0)

                # Active SLA breaches (dept score < 70 for 2+ consecutive days)
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM   governance_audit_log
                    WHERE  event_type = 'welfare_sla_breach'
                      AND  outcome != 'resolved'
                      AND  timestamp > NOW() - INTERVAL '7 days'
                    """
                )
                active_sla_breaches = int((cur.fetchone() or {}).get("cnt") or 0)

            # Staffing imbalance ratio per department (max/min dispatches)
            dept_counts: dict = defaultdict(list)
            for row in imbalance_rows:
                dept_counts[row["department"]].append(int(row["dispatches"] or 0))

            imbalance_flags = []
            for dept, counts in dept_counts.items():
                if len(counts) < 2:
                    continue
                mx, mn = max(counts), min(c for c in counts if c > 0) if any(c > 0 for c in counts) else 0
                if mn == 0:
                    continue
                ratio = round(mx / mn, 1)
                if ratio >= 5.0:
                    imbalance_flags.append((dept, ratio, mx, mn))
            imbalance_flags.sort(key=lambda x: -x[1])

            # Ethics score approximation (7d)
            high_stress_total = sum(int(d.get("high_stress_cnt") or 0) for d in top_stress)
            ethics_raw = sr_7d - (high_stress_total * 2)
            ethics_score = max(0, min(100, round(ethics_raw)))

            def _grade(s: int) -> str:
                if s >= 95:
                    return "A+"
                if s >= 90:
                    return "A"
                if s >= 85:
                    return "B+"
                if s >= 80:
                    return "B"
                if s >= 70:
                    return "C"
                if s >= 60:
                    return "D"
                return "F"

            lines = [
                "\U0001f4ca *C.R.E.E.D. + K.I.N. Weekly Digest*",
                "",
                f"*Platform Ethics (7d):* {ethics_score}/100 — {_grade(ethics_score)}",
                f"Job success rate: {sr_7d}%  |  High-stress agents: {high_stress_total}",
                "",
            ]
            if top_stress:
                lines.append("*Top-Stress Departments:*")
                for d in top_stress[:3]:
                    lines.append(
                        f"• {d['department']}: avg {float(d['avg_stress']):.0%} "
                        f"({d['high_stress_cnt']} agents ≥80%)"
                    )
                lines.append("")
            if top_tokens:
                lines.append("*Top Token Consumers (7d):*")
                for t in top_tokens[:3]:
                    lines.append(
                        f"• {t['display_name']} ({t['department']}): "
                        f"{int(t['tokens_7d'] or 0):,} tokens / {t['dispatches_7d']} dispatches"
                    )
                lines.append("")
            if overflow_events:
                lines.append("*Overflow Governance Events (7d):*")
                for ev, cnt in list(overflow_events.items())[:5]:
                    lines.append(f"• {ev}: {cnt}")
                lines.append("")
            if imbalance_flags:
                lines.append("*⚠️ Staffing Imbalance Flags:*")
                for dept, ratio, mx, mn in imbalance_flags[:3]:
                    lines.append(f"• {dept}: {ratio}× imbalance " f"(max {mx:,} / min {mn:,} dispatches)")
                lines.append("")
                lines.append(
                    "_K.I.N. recommends reviewing backup agent skill registrations " "and overflow bid thresholds._"
                )
                lines.append("")

            # Rest compliance + welfare consent
            rest_icon = "✅" if rest_compliance_pct >= 80 else ("⚠️" if rest_compliance_pct >= 50 else "🔴")
            lines.append(
                f"*Rest Compliance (7d):* {rest_icon} "
                f"{rest_compliance_pct}% ({_completed_rest}/{_total_active} agents completed rest)"
            )
            lines.append(f"*Welfare Blocks Honored (7d):* {blocks_7d} consent decisions respected")
            if active_sla_breaches:
                lines.append(f"*🔴 Active SLA Breaches:* {active_sla_breaches} dept(s) below C-grade for 48h+")

            msg = "\n".join(lines)

            # Log digest to governance_audit_log
            try:
                with get_db_cursor() as (_, cur):
                    cur.execute(
                        """
                        INSERT INTO governance_audit_log
                            (event_type, event_category, action,
                             target_table, reason, outcome)
                        VALUES ('creed_kin_weekly_digest', 'governance', 'report',
                                'governance_audit_log', %s, 'success')
                        """,
                        (
                            f"ethics={ethics_score} high_stress={high_stress_total} "
                            f"imbalance_flags={len(imbalance_flags)} "
                            f"rest_compliance={rest_compliance_pct}% "
                            f"blocks_honored={blocks_7d} sla_breaches={active_sla_breaches}",
                        ),
                    )
            except Exception as _ge:
                logger.debug("[CreedKINDigest] governance_audit_log failed: %s", _ge)

            try:
                from services.telegram_service import send_info

                send_info(msg, source_module="department_hq.jobs.creed_kin_weekly_digest")
            except Exception as _tg:
                logger.debug("[CreedKINDigest] Telegram send failed: %s", _tg)

            logger.info(
                "[CreedKINDigest] digest sent: ethics=%d stress_depts=%d imbalance_flags=%d",
                ethics_score,
                len(top_stress),
                len(imbalance_flags),
            )

        except Exception as _exc:
            logger.error("[CreedKINDigest] crashed: %s", _exc)

    scheduler.add_job(
        with_ctx(_run_creed_kin_weekly_digest),
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="America/Toronto"),
        id="creed_kin_weekly_digest",
        name="C.R.E.E.D. + K.I.N. Weekly Digest — governance + welfare advisory report (Mon 09:00)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered creed_kin_weekly_digest job (Mon 09:00, Job #131)")

    # ── Job #132 — Daily C.R.E.E.D. ethics snapshot + SLA breach tracking ─────

    def _run_creed_ethics_snapshot():
        """Nightly per-department ethics score snapshot → creed_ethics_snapshots.

        Also checks SLA breaches: any department scoring below C (70) for
        2+ consecutive days emits welfare_sla_breach to governance_audit_log.
        Recovery to ≥70 emits welfare_sla_resolved.
        """
        try:
            from database import get_db_cursor

            with get_db_cursor() as (_, cur):
                # Compute per-dept welfare (LATERAL — avoids time-series fan-out)
                cur.execute(
                    """
                    SELECT a.department,
                           AVG(ae.stress_level)                                AS avg_stress,
                           COUNT(CASE WHEN ae.stress_level >= 0.8 THEN 1 END) AS high_stress_count
                    FROM agents a
                    JOIN LATERAL (
                        SELECT stress_level FROM agent_emotional_state
                        WHERE agent_id = a.id ORDER BY id DESC LIMIT 1
                    ) ae ON true
                    WHERE a.shift_state NOT IN ('decommissioned')
                    GROUP BY a.department
                    """
                )
                welfare_by_dept = {
                    r["department"]: {
                        "avg_stress": float(r["avg_stress"] or 0),
                        "high_stress_agents": int(r["high_stress_count"] or 0),
                    }
                    for r in (cur.fetchall() or [])
                }

                # 24h job success rate per department
                cur.execute(
                    """
                    SELECT department,
                           COUNT(*) FILTER (WHERE status = 'success') AS success,
                           COUNT(*) AS total
                    FROM autonomy_loop_log
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                      AND department IS NOT NULL AND department != 'UNKNOWN'
                    GROUP BY department
                    """
                )
                jobs_by_dept = {
                    r["department"]: {
                        "success": int(r["success"] or 0),
                        "total": int(r["total"] or 0),
                    }
                    for r in (cur.fetchall() or [])
                }

                all_depts = set(welfare_by_dept) | set(jobs_by_dept)

                def _grade(sc: int) -> str:
                    if sc >= 95:
                        return "A+"
                    if sc >= 90:
                        return "A"
                    if sc >= 85:
                        return "B+"
                    if sc >= 80:
                        return "B"
                    if sc >= 70:
                        return "C"
                    if sc >= 60:
                        return "D"
                    return "F"

                today_scores: dict = {}
                for dept in all_depts:
                    wf = welfare_by_dept.get(dept, {})
                    jh = jobs_by_dept.get(dept, {})
                    sr = round(jh["success"] / jh["total"] * 100, 1) if jh.get("total", 0) > 0 else 100.0
                    hs = wf.get("high_stress_agents", 0)
                    raw = sr - (hs * 2)
                    score = max(0, min(100, round(raw)))
                    avg_stress = wf.get("avg_stress", 0.0)
                    welfare_status = "red" if avg_stress >= 0.8 else ("yellow" if avg_stress >= 0.5 else "green")
                    today_scores[dept] = {
                        "score": score,
                        "grade": _grade(score),
                        "success_rate": sr,
                        "high_stress_agents": hs,
                        "avg_stress": round(avg_stress, 3),
                        "welfare_status": welfare_status,
                    }

                # Upsert today's snapshots
                for dept, s in today_scores.items():
                    cur.execute(
                        """
                        INSERT INTO creed_ethics_snapshots
                            (snapshot_date, department, score, grade,
                             success_rate, high_stress_agents, avg_stress, welfare_status)
                        VALUES (CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (snapshot_date, department)
                        DO UPDATE SET
                            score              = EXCLUDED.score,
                            grade              = EXCLUDED.grade,
                            success_rate       = EXCLUDED.success_rate,
                            high_stress_agents = EXCLUDED.high_stress_agents,
                            avg_stress         = EXCLUDED.avg_stress,
                            welfare_status     = EXCLUDED.welfare_status
                        """,
                        (
                            dept,
                            s["score"],
                            s["grade"],
                            s["success_rate"],
                            s["high_stress_agents"],
                            s["avg_stress"],
                            s["welfare_status"],
                        ),
                    )

                # SLA breach / resolution detection — compare with yesterday
                cur.execute(
                    """
                    SELECT department, score
                    FROM creed_ethics_snapshots
                    WHERE snapshot_date = CURRENT_DATE - INTERVAL '1 day'
                    """
                )
                yesterday = {r["department"]: int(r["score"]) for r in (cur.fetchall() or [])}

            # Evaluate SLA changes (outside the DB cursor so we can reopen)
            breaches_raised = 0
            resolved_raised = 0
            for dept, s in today_scores.items():
                today_score = s["score"]
                yest_score = yesterday.get(dept, 100)
                below_today = today_score < 70
                below_yest = yest_score < 70
                if below_today and below_yest:
                    # 2+ consecutive days below C — raise breach
                    try:
                        with get_db_cursor() as (_, cur2):
                            cur2.execute(
                                """
                                INSERT INTO governance_audit_log
                                    (event_type, event_category, action,
                                     target_table, reason, outcome)
                                VALUES ('welfare_sla_breach', 'welfare', 'flag',
                                        'creed_ethics_snapshots', %s, 'open')
                                """,
                                (f"dept={dept} score={today_score} " f"yesterday={yest_score} grade={s['grade']}",),
                            )
                        breaches_raised += 1
                    except Exception as _be:
                        logger.debug("[EthicsSnapshot] SLA breach log failed: %s", _be)
                elif not below_today and below_yest:
                    # Recovered — log resolution
                    try:
                        with get_db_cursor() as (_, cur2):
                            cur2.execute(
                                """
                                INSERT INTO governance_audit_log
                                    (event_type, event_category, action,
                                     target_table, reason, outcome)
                                VALUES ('welfare_sla_resolved', 'welfare', 'update',
                                        'creed_ethics_snapshots', %s, 'resolved')
                                """,
                                (
                                    f"dept={dept} score={today_score} "
                                    f"recovered_from={yest_score} grade={s['grade']}",
                                ),
                            )
                        resolved_raised += 1
                    except Exception as _re:
                        logger.debug("[EthicsSnapshot] SLA resolve log failed: %s", _re)

            # Summary audit entry
            try:
                with get_db_cursor() as (_, cur):
                    cur.execute(
                        """
                        INSERT INTO governance_audit_log
                            (event_type, event_category, action,
                             target_table, reason, outcome)
                        VALUES ('creed_ethics_snapshot_done', 'governance', 'report',
                                'creed_ethics_snapshots', %s, 'success')
                        """,
                        (
                            f"depts={len(today_scores)} "
                            f"breaches_raised={breaches_raised} "
                            f"resolved={resolved_raised}",
                        ),
                    )
            except Exception as _ge:
                logger.debug("[EthicsSnapshot] summary audit log failed: %s", _ge)

            logger.info(
                "[EthicsSnapshot] done — %d depts, %d SLA breaches, %d resolved",
                len(today_scores),
                breaches_raised,
                resolved_raised,
            )

        except Exception as _exc:
            logger.error("[EthicsSnapshot] crashed: %s", _exc)

    scheduler.add_job(
        with_ctx(_run_creed_ethics_snapshot),
        trigger=CronTrigger(hour=0, minute=5, timezone="America/Toronto"),
        id="creed_ethics_snapshot",
        name="C.R.E.E.D. Ethics Snapshot — nightly per-dept score history + SLA breach check (00:05)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered creed_ethics_snapshot job (daily 00:05, Job #132)")

    # ── Job #133 — Quarterly C.R.E.E.D. governance report ─────────────────────

    def _run_creed_quarterly_report():
        """Generate quarterly governance report → creed_governance_reports + knowledge_base.

        Runs on the 1st of Jan / Apr / Jul / Oct at 08:00 ET.
        Pulls 90 days of ethics snapshots + governance events + welfare signals.
        Stores JSON in creed_governance_reports for the API to serve.
        Also writes a vault_note to knowledge_base for archiving.
        """
        import datetime

        try:
            from database import get_db_cursor

            now_dt = datetime.datetime.now()
            quarter_num = (now_dt.month - 1) // 3 + 1
            quarter_label = f"{now_dt.year}-Q{quarter_num}"

            with get_db_cursor() as (_, cur):
                # 90-day ethics snapshot summary per department
                cur.execute(
                    """
                    SELECT department,
                           MIN(score) AS min_score, MAX(score) AS max_score,
                           ROUND(AVG(score)::numeric, 1) AS avg_score,
                           COUNT(*) AS days_tracked,
                           COUNT(CASE WHEN score < 70 THEN 1 END) AS days_below_c
                    FROM creed_ethics_snapshots
                    WHERE snapshot_date >= CURRENT_DATE - INTERVAL '90 days'
                    GROUP BY department
                    ORDER BY avg_score
                    """
                )
                dept_summary = [dict(r) for r in (cur.fetchall() or [])]
                for d in dept_summary:
                    for k in ("min_score", "max_score", "avg_score"):
                        if d[k] is not None:
                            d[k] = float(d[k])

                # Global ethics trend (daily avg across all depts)
                cur.execute(
                    """
                    SELECT snapshot_date::text,
                           ROUND(AVG(score)::numeric, 1) AS avg_score,
                           MIN(score) AS min_score
                    FROM creed_ethics_snapshots
                    WHERE snapshot_date >= CURRENT_DATE - INTERVAL '90 days'
                    GROUP BY snapshot_date
                    ORDER BY snapshot_date
                    """
                )
                daily_trend = [
                    {
                        "date": r["snapshot_date"],
                        "avg_score": float(r["avg_score"] or 0),
                        "min_score": int(r["min_score"] or 0),
                    }
                    for r in (cur.fetchall() or [])
                ]

                # Governance events by type (90d)
                cur.execute(
                    """
                    SELECT event_type, COUNT(*) AS cnt
                    FROM governance_audit_log
                    WHERE timestamp >= NOW() - INTERVAL '90 days'
                    GROUP BY event_type
                    ORDER BY cnt DESC
                    LIMIT 20
                    """
                )
                event_counts = {r["event_type"]: int(r["cnt"]) for r in (cur.fetchall() or [])}

                # Welfare summary
                welfare_blocks = event_counts.get("overflow_welfare_blocked", 0)
                sla_breaches = event_counts.get("welfare_sla_breach", 0)
                sla_resolved = event_counts.get("welfare_sla_resolved", 0)
                token_warnings = event_counts.get("token_overload_warning", 0)
                overflow_activations = event_counts.get("overflow_skill_activated", 0)

                # Agent count snapshot
                cur.execute("SELECT COUNT(*) AS cnt FROM agents WHERE shift_state != 'decommissioned'")
                agent_count = int((cur.fetchone() or {}).get("cnt") or 0)

                # Rest compliance (90d) — agents who rested at least once
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT agent_id) AS rested
                    FROM agent_rest_cycles
                    WHERE started_at >= NOW() - INTERVAL '90 days'
                      AND ended_at IS NOT NULL
                    """
                )
                rested_agents = int((cur.fetchone() or {}).get("rested") or 0)

            report = {
                "quarter": quarter_label,
                "generated_at": now_dt.isoformat(),
                "period_days": 90,
                "agents_monitored": agent_count,
                "departments": len(dept_summary),
                "summary": {
                    "welfare_blocks_honored": welfare_blocks,
                    "sla_breaches": sla_breaches,
                    "sla_breaches_resolved": sla_resolved,
                    "token_overload_warnings": token_warnings,
                    "overflow_activations": overflow_activations,
                    "agents_completed_rest": rested_agents,
                },
                "dept_ethics": dept_summary,
                "daily_ethics_trend": daily_trend,
                "governance_event_counts": event_counts,
            }

            # Store in creed_governance_reports
            try:
                import json as _json

                with get_db_cursor() as (_, cur):
                    cur.execute(
                        """
                        INSERT INTO creed_governance_reports (quarter, report_json)
                        VALUES (%s, %s)
                        ON CONFLICT (quarter)
                        DO UPDATE SET report_json = EXCLUDED.report_json,
                                      created_at  = NOW()
                        """,
                        (quarter_label, _json.dumps(report)),
                    )
            except Exception as _dbe:
                logger.warning("[QuarterlyReport] DB store failed: %s", _dbe)

            # Store as vault_note in knowledge_base for archiving
            try:
                import json as _json

                with get_db_cursor() as (_, cur):
                    cur.execute(
                        """
                        INSERT INTO knowledge_base
                            (title, content, knowledge_type, category, tags,
                             importance_score, source)
                        VALUES (%s, %s, 'vault_note', 'governance', %s, 0.95, 'creed_quarterly_job')
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            f"C.R.E.E.D. Governance Report — {quarter_label}",
                            _json.dumps(report, indent=2),
                            _json.dumps(["creed", "governance", "quarterly_report", quarter_label]),
                        ),
                    )
            except Exception as _kbe:
                logger.debug("[QuarterlyReport] KB vault_note failed: %s", _kbe)

            # Governance audit entry
            try:
                with get_db_cursor() as (_, cur):
                    cur.execute(
                        """
                        INSERT INTO governance_audit_log
                            (event_type, event_category, action,
                             target_table, reason, outcome)
                        VALUES ('creed_quarterly_report', 'governance', 'report',
                                'creed_governance_reports', %s, 'success')
                        """,
                        (
                            f"quarter={quarter_label} depts={len(dept_summary)} "
                            f"welfare_blocks={welfare_blocks} sla_breaches={sla_breaches}",
                        ),
                    )
            except Exception as _ge:
                logger.debug("[QuarterlyReport] audit log failed: %s", _ge)

            logger.info(
                "[QuarterlyReport] %s complete — %d depts, %d welfare blocks, %d SLA breaches",
                quarter_label,
                len(dept_summary),
                welfare_blocks,
                sla_breaches,
            )

        except Exception as _exc:
            logger.error("[QuarterlyReport] crashed: %s", _exc)

    scheduler.add_job(
        with_ctx(_run_creed_quarterly_report),
        trigger=CronTrigger(month="1,4,7,10", day=1, hour=8, minute=0, timezone="America/Toronto"),
        id="creed_quarterly_report",
        name="C.R.E.E.D. Quarterly Governance Report — 1st of Jan/Apr/Jul/Oct 08:00",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered creed_quarterly_report job (quarterly 08:00, Job #133)")

    # ── Job #134 — C.R.E.E.D. Privacy Audit (every 6h) ───────────────────────
    def _run_creed_privacy_audit():
        """Aggregate privacy-relevant data operations and log to C.R.E.E.D.

        Runs every 6 hours. Counts emails processed, KB entries written,
        API key authentications, and third-party service calls in the last 6h.
        Logs each category as a data_management governance event so the creed
        standalone's privacy pillar reflects real platform activity.

        PIPEDA principles covered:
          - Safeguards           : email_data_processed, api_external_access
          - Limiting Use         : data_retention_check
          - Accountability       : audit_summary
          - Transparency         : third_party_data_share
        """

        try:
            from services.creed_privacy_logger import log_privacy_event
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):

                # ── 1. Email data processed ───────────────────────────────────
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM email_messages
                    WHERE created_at >= NOW() - INTERVAL '6 hours'
                    """
                )
                emails_processed = (cur.fetchone() or {}).get("cnt", 0)

                if emails_processed > 0:
                    log_privacy_event(
                        event_type="email_data_processed",
                        action="batch_sync",
                        outcome="success",
                        data_category="personal",
                        description=f"Email batch: {emails_processed} messages processed in 6h",
                        details={
                            "messages_6h": int(emails_processed),
                            "pipeda_principle": "safeguards",
                        },
                    )

                # ── 2. Knowledge base — user-related entries written ──────────
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM knowledge_base
                    WHERE created_at >= NOW() - INTERVAL '6 hours'
                      AND knowledge_type IN ('conversation_memory', 'vault_note')
                    """
                )
                kb_writes = (cur.fetchone() or {}).get("cnt", 0)

                log_privacy_event(
                    event_type="knowledge_base_write",
                    action="store",
                    outcome="success",
                    data_category="aggregate",
                    description=f"KB writes: {kb_writes} user-related entries in 6h",
                    details={
                        "entries_6h": int(kb_writes),
                        "pipeda_principle": "limiting_use",
                    },
                )

                # ── 3. API key authentications (external access) ──────────────
                cur.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN event_type = 'api_key_login_success' THEN 1 ELSE 0 END) AS granted,
                           SUM(CASE WHEN event_type = 'api_key_login_fail' THEN 1 ELSE 0 END) AS denied
                    FROM auth_events
                    WHERE created_at >= NOW() - INTERVAL '6 hours'
                      AND event_type IN ('api_key_login_success', 'api_key_login_fail')
                    """
                )
                api_row = cur.fetchone() or {}
                api_total = int(api_row.get("total") or 0)
                api_denied = int(api_row.get("denied") or 0)

                if api_total > 0:
                    outcome = "denied" if api_denied > api_total / 2 else "success"
                    log_privacy_event(
                        event_type="api_external_access",
                        action="authenticate",
                        outcome=outcome,
                        data_category="aggregate",
                        description=(f"API key auth: {api_total} attempts, " f"{api_denied} denied in 6h"),
                        details={
                            "total_6h": api_total,
                            "granted_6h": int(api_row.get("granted") or 0),
                            "denied_6h": api_denied,
                            "pipeda_principle": "accountability",
                        },
                    )

                # ── 4. Data retention — count then DELETE stale memories ──────
                # PIPEDA: Limiting Use — conversation_memory >90 days purged
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM knowledge_base
                    WHERE knowledge_type = 'conversation_memory'
                      AND created_at < NOW() - INTERVAL '90 days'
                    """
                )
                stale_memories = int((cur.fetchone() or {}).get("cnt", 0))

                # Enforce retention: delete up to 500 per cycle (batch-safe)
                deleted_memories = 0
                if stale_memories > 0:
                    cur.execute(
                        """
                        DELETE FROM knowledge_base
                        WHERE id IN (
                            SELECT id FROM knowledge_base
                            WHERE knowledge_type = 'conversation_memory'
                              AND created_at < NOW() - INTERVAL '90 days'
                            ORDER BY created_at ASC
                            LIMIT 500
                        )
                        """
                    )
                    deleted_memories = cur.rowcount or 0

                retention_outcome = "failed" if stale_memories > 500 else "success"
                log_privacy_event(
                    event_type="data_retention_check",
                    action="purge",
                    outcome=retention_outcome,
                    data_category="personal",
                    description=(
                        f"Retention: {stale_memories} conversation memories >90 days; "
                        f"{deleted_memories} purged this cycle"
                    ),
                    details={
                        "stale_before_purge": stale_memories,
                        "deleted_this_cycle": deleted_memories,
                        "threshold_days": 90,
                        "pipeda_principle": "limiting_use",
                    },
                )

                # ── 5. Third-party service call audit ─────────────────────────
                # Check task_execution_log for dispatches to external providers
                # in last 6h (cloud contractors = third-party data share)
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt, model_used
                    FROM task_execution_log
                    WHERE created_at >= NOW() - INTERVAL '6 hours'
                      AND model_used ILIKE '%:cloud%'
                    GROUP BY model_used
                    LIMIT 10
                    """
                )
                cloud_rows = cur.fetchall() or []
                cloud_total = sum(int(r.get("cnt", 0)) for r in cloud_rows)

                if cloud_total > 0:
                    log_privacy_event(
                        event_type="third_party_data_share",
                        action="dispatch",
                        outcome="success",
                        data_category="anonymized",
                        description=(f"Cloud dispatch: {cloud_total} tasks sent to external " f"providers in 6h"),
                        details={
                            "cloud_dispatches_6h": cloud_total,
                            "providers": [
                                {"model": r.get("model_used"), "count": int(r.get("cnt", 0))} for r in cloud_rows
                            ],
                            "pipeda_principle": "limiting_collection",
                        },
                    )

            logger.info(
                "[PrivacyAudit] Logged: emails=%s kb_writes=%s api_auths=%s " "stale_memories=%s cloud_dispatches=%s",
                emails_processed,
                kb_writes,
                api_total,
                stale_memories,
                cloud_total,
            )

        except Exception as _exc:
            logger.error("[PrivacyAudit] Job failed: %s", _exc)

    scheduler.add_job(
        with_ctx(_run_creed_privacy_audit),
        trigger=CronTrigger(hour="0,6,12,18", minute=30, timezone="America/Toronto"),
        id="creed_privacy_audit",
        name="C.R.E.E.D. Privacy Audit — every 6h (Job #134)",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("[DeptHQ] Registered creed_privacy_audit job (every 6h, Job #134)")

    logger.info("[DeptHQ] Registered 12 code health/audit jobs")
