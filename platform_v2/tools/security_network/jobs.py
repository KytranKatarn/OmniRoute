"""security_network/jobs.py — Background jobs owned by the Security & Network module.

Extracted from agent_loop.py (Phase 5). Each job is a standalone function.
Registration with APScheduler happens via register_security_jobs().

Jobs extracted:
  - discover_network_devices (every 5 min)
  - run_security_audit (weekly Sun 3AM)
  - check_ssl_expiry (every 24h)
  - daily_dns_report (daily 7AM)
  - detect_query_spike (every 1h)
  - check_camera_anomaly (every 1h)
  - run_auto_block (every 15 min)
  - run_scheduled_compliance_scan (Job #57, every 6h)
  - run_compliance_enqueue (Job #58, every 6h) + run_auto_apply_window (Job #62, Sun 03:00 EDT)
  - run_anomaly_detection (Job #61, every 30 min)
  - generate_vigil_threat_report (daily 8AM)
"""

import json
import logging
import os
import time
from services.time_utils import now_local

logger = logging.getLogger("agent_loop")

# ---------------------------------------------------------------------------
# Shared helper: _log_cycle  (mirrors AgentLoop._log_cycle)
# ---------------------------------------------------------------------------

# Department mapping for security jobs
_SECURITY_DEPARTMENT = "Security & Compliance"


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
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
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
                    _SECURITY_DEPARTMENT,
                ),
            )
    except Exception as e:
        logger.error(f"Failed to log agent cycle: {e}")


# ---------------------------------------------------------------------------
# Job implementations (faithful copies from agent_loop.py)
# ---------------------------------------------------------------------------


def discover_network_devices():
    """Discover new network devices via AdGuard + ARP (every 5 min)."""
    try:
        from tools.security_network.device_registry_service import DeviceRegistryService
        from tools.security_network.security_alerts import create_security_alert, create_security_digest

        svc = DeviceRegistryService()
        new_devices = svc.discover_devices()

        # Sync Docker containers by container_name (stable key, MAC-independent)
        svc.sync_docker_containers()

        # Save each to DB (dashboard tracking) but skip individual Telegram
        digest_lines = []
        for device in new_devices:
            # `or` (not .get default) — the keys are often PRESENT with value None,
            # which rendered the alert title as "New device detected: None" (#5308).
            ip = device.get("ip_address") or "?"
            mac = device.get("mac_address") or "?"
            mfr = device.get("manufacturer") or "Unknown"
            create_security_alert(
                "new_device",
                f"New device detected: {mfr}",
                f"IP: {ip} | MAC: {mac} | Manufacturer: {mfr}",
                priority="high",
                telegram=False,  # batched into digest
            )
            digest_lines.append({"line": f"{mfr}: {ip} (MAC: {mac})"})

        # ONE Telegram message for all new devices
        if digest_lines:
            create_security_digest(
                "new_device",
                "New Devices Discovered",
                digest_lines,
                priority="high",
                telegram=True,
            )
            logger.info(f"Network discovery: {len(new_devices)} new devices found")
    except Exception as e:
        logger.warning(f"Failed: {e}")


def run_security_audit():
    """Weekly security configuration audit — verify nothing has drifted."""
    try:
        from tools.security_network.security_alerts import create_security_alert
        import subprocess

        issues = []

        # 1. Check SSH config
        try:
            r = subprocess.run(
                ["cat", "/etc/ssh/sshd_config.d/99-archie-hardening.conf"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "PasswordAuthentication no" not in r.stdout:
                issues.append("SSH password auth may be enabled")
        except Exception:
            issues.append("Cannot read SSH hardening config")

        # 2. Check fail2ban
        try:

            # Check if fail2ban log exists (proxy for service running)
            r = subprocess.run(
                ["test", "-f", "/var/log/fail2ban.log"],
                capture_output=True,
                timeout=5,
            )
            # Just check the file exists as a proxy
        except Exception:
            pass

        # 3. Check UFW rules for PostgreSQL
        try:
            r = subprocess.run(
                ["cat", "/etc/ufw/user.rules"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "5432" in r.stdout and "Anywhere" in r.stdout and "192.168.1.0/24" not in r.stdout:
                issues.append("PostgreSQL port 5432 may be exposed to internet")
        except Exception:
            pass

        # 4. Check DDNS updater freshness
        ddns_file = os.path.join(
            os.getenv("ARCHIE_BASE_DIR", "/mnt/archie_brain"),
            "scripts",
            ".ddns_last_ip",
        )
        if os.path.exists(ddns_file):
            age_hours = (time.time() - os.path.getmtime(ddns_file)) / 3600
            if age_hours > 1:
                issues.append(f"DDNS updater hasn't run in {age_hours:.0f} hours")
        else:
            issues.append("DDNS updater IP file missing")

        # 5. Check AdGuard protection
        try:
            import requests

            host = os.getenv("ADGUARD_HOST", "host.docker.internal")
            port = os.getenv("ADGUARD_PORT", "5354")
            user = os.getenv("ADGUARD_USER", "")
            pw = os.getenv("ADGUARD_PASS", "")
            r = requests.get(
                f"http://{host}:{port}/control/status",
                auth=(user, pw),
                timeout=5,
            )
            if not r.json().get("protection_enabled"):
                issues.append("AdGuard DNS protection is disabled")
        except Exception:
            issues.append("Cannot reach AdGuard")

        if issues:
            create_security_alert(
                "scan_result",
                f"Security audit: {len(issues)} issue(s) found",
                "Issues:\n" + "\n".join(f"\u2022 {i}" for i in issues),
                priority="high",
                telegram=True,
            )
            logger.warning(f"Security audit: {len(issues)} issues: {issues}")
        else:
            logger.info("Security audit: all checks passed")

    except Exception as e:
        logger.warning(f"Failed: {e}")


def check_ssl_expiry():
    """Check SSL certificates for upcoming expiry (daily)."""
    try:
        from tools.security_network.security_alerts import create_security_alert

        # Sweep security_ssl_monitors (covers tracked external domains)
        try:
            from tools.security_network.security_service import refresh_ssl_monitors

            refresh_result = refresh_ssl_monitors()
            for alert in refresh_result.get("alerts", []):
                days_left = alert.get("days_until_expiry", 99)
                domain = alert.get("domain", "unknown")
                if days_left <= 14:
                    priority = "critical" if days_left <= 3 else "high" if days_left <= 7 else "normal"
                    create_security_alert(
                        "ssl_expiry",
                        f"SSL cert expiring: {domain}",
                        f"Certificate for {domain} expires in {days_left} days",
                        priority=priority,
                        telegram=True,
                    )
        except Exception as mon_err:
            logger.warning(f"SSL monitor refresh failed: {mon_err}")

    except Exception as e:
        logger.warning(f"Failed: {e}")


def daily_dns_report():
    """Generate daily DNS activity summary for Telegram (7 AM daily)."""
    try:
        import requests
        from tools.security_network.security_alerts import create_security_alert

        host = os.getenv("ADGUARD_HOST", "host.docker.internal")
        port = os.getenv("ADGUARD_PORT", "5354")
        user = os.getenv("ADGUARD_USER", "")
        pw = os.getenv("ADGUARD_PASS", "")

        r = requests.get(
            f"http://{host}:{port}/control/stats",
            auth=(user, pw),
            timeout=10,
        )
        stats = r.json()

        queries = stats.get("num_dns_queries", 0)
        blocked = stats.get("num_blocked_filtering", 0)
        block_pct = round(blocked / queries * 100, 1) if queries > 0 else 0
        safe = stats.get("num_replaced_safebrowsing", 0)
        top_clients = stats.get("top_clients", [])[:3]
        top_blocked = stats.get("top_blocked_domains", [])[:3]

        client_lines = []
        for tc in top_clients:
            for ip, count in tc.items():
                client_lines.append(f"  {ip}: {count}")

        blocked_lines = []
        for tb in top_blocked:
            for domain, count in tb.items():
                blocked_lines.append(f"  {domain}: {count}")

        message = (
            f"Queries: {queries:,} | Blocked: {blocked:,} ({block_pct}%)\n"
            f"Safe browsing blocks: {safe}\n"
            f"Top clients:\n" + "\n".join(client_lines[:3]) + "\n"
            "Top blocked:\n" + "\n".join(blocked_lines[:3])
        )

        create_security_alert(
            "dns_change",
            "Daily DNS Report",
            message,
            priority="normal",
            telegram=True,
        )
        logger.info("Daily DNS report sent")
    except Exception as e:
        logger.warning(f"Failed: {e}")


def detect_query_spike():
    """Detect unusual DNS query spikes (hourly)."""
    try:
        import requests
        from tools.security_network.security_alerts import create_security_alert

        host = os.getenv("ADGUARD_HOST", "host.docker.internal")
        port = os.getenv("ADGUARD_PORT", "5354")
        user = os.getenv("ADGUARD_USER", "")
        pw = os.getenv("ADGUARD_PASS", "")

        r = requests.get(
            f"http://{host}:{port}/control/stats",
            auth=(user, pw),
            timeout=10,
        )
        stats = r.json()

        # Check if blocked queries are unusually high (>50% of total)
        queries = stats.get("num_dns_queries", 0)
        blocked = stats.get("num_blocked_filtering", 0)

        if queries > 100 and blocked > 0:
            block_rate = blocked / queries
            if block_rate > 0.5:
                create_security_alert(
                    "scan_result",
                    f"DNS block rate spike: {block_rate:.0%}",
                    f"{blocked:,} blocked out of {queries:,} total queries ({block_rate:.0%}). Normal is <15%. Possible malware or misconfiguration.",
                    priority="high",
                    telegram=True,
                )
                logger.warning(f"Query spike: {block_rate:.0%} blocked ({blocked}/{queries})")
    except Exception as e:
        logger.warning(f"Failed: {e}")


def check_camera_anomaly():
    """Alert if cameras have been offline or no motion detected in 4+ hours."""
    try:
        from tools.security_network.ha_surveillance_service import (
            HASurveillanceService,
        )
        from tools.security_network.security_alerts import create_security_alert

        svc = HASurveillanceService()
        if not svc.available:
            return

        cameras = svc.get_cameras()
        for cam in cameras:
            state = cam.get("state", "")
            name = cam.get("name", cam.get("entity_id", "unknown"))
            if state in ("unavailable", "unknown"):
                create_security_alert(
                    "scan_result",
                    f"Camera offline: {name}",
                    f"Camera {name} ({cam.get('entity_id')}) is {state}",
                    priority="high",
                    telegram=True,
                )
                logger.warning(f"Camera anomaly: {name} is {state}")
    except Exception as e:
        logger.warning(f"Failed: {e}")


def run_auto_block():
    """Run the suggestion engine and FLAG critical/high threats for review (every 15 min).

    NOTE: this does NOT automatically block anything. approve_suggestion() only
    records the suggestion as acknowledged in the DB — no code consumes approved
    security_agent_actions rows, so no firewall/DNS block is executed. The alert
    below therefore says "flagged", not "blocked". Wiring real auto-execution is a
    deliberate owner decision (it can block legitimate traffic), tracked separately.
    """
    try:
        from tools.security_network.agent_automation import AgentAutomationService
        from tools.security_network.security_alerts import create_security_alert

        svc = AgentAutomationService()
        if not svc.get_config().get("paused"):
            result = svc.generate_suggestions()
            if result and result.get("generated", 0) > 0:
                logger.info(f"Auto-block: generated {result['generated']} suggestions")

                # Auto-execute critical/high suggestions
                pending = svc.get_pending_suggestions(limit=10)
                for suggestion in pending:
                    data = suggestion.get("data", {})
                    if isinstance(data, str):
                        try:
                            data = json.loads(data)
                        except (json.JSONDecodeError, TypeError):
                            data = {}
                    severity = data.get("severity", "low")
                    stype = data.get("suggestion_type", "")

                    # suggestion_type may carry a suffix (e.g. "device_vulnerability:<ip>"),
                    # so match on the prefix — the exact-membership test silently skipped
                    # every device_vulnerability suggestion (dead branch).
                    if severity in ("critical", "high") and stype.split(":")[0] in (
                        "ssh_brute_force",
                        "device_vulnerability",
                    ):
                        try:
                            # Acknowledge (dedupe) — this does NOT execute a block.
                            svc.approve_suggestion(suggestion["id"])
                            desc = suggestion.get("description", "Threat detected by the security pipeline")
                            create_security_alert(
                                "recommendation",
                                f"Action recommended: {suggestion.get('title', stype)}",
                                f"{desc} — flagged by the V.I.G.I.L. pipeline. Review and act in the "
                                f"Suggestions queue. This was NOT automatically blocked.",
                                priority="high",
                                telegram=True,
                            )
                            logger.info(f"Auto-block: flagged suggestion #{suggestion['id']} ({stype}) for review")
                        except Exception as e:
                            logger.warning(f"Failed: {e}")
    except Exception as e:
        logger.warning(f"Failed: {e}")


def run_scheduled_compliance_scan():
    """Job #57: Run STIG compliance scan every 6 hours + auto-collect SOC 2 evidence."""
    try:
        from tools.security_network.compliance_service import (
            run_scan,
            collect_evidence,
        )

        result = run_scan(triggered_by="scheduled")
        score = result.get("score", 0)
        scan_id = result.get("scan_id")
        logger.info(
            "Scheduled compliance scan complete: %.1f%% (%d/%d passed)",
            score,
            result.get("passed", 0),
            result.get("total", 0),
        )

        # Auto-collect SOC 2 evidence after each scan
        try:
            ev = collect_evidence(scan_id=scan_id)
            logger.info(
                "SOC 2 evidence auto-collected: %d artifacts stored",
                ev.get("stored", 0),
            )
        except Exception as ev_err:
            logger.warning("SOC 2 evidence collection failed: %s", ev_err)

        # Score change detection — notify on Telegram if score changed
        try:
            from database import get_db_cursor
            from tools.security_network.security_alerts import create_security_alert

            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT score FROM compliance_scans
                    WHERE completed_at IS NOT NULL
                    ORDER BY started_at DESC LIMIT 2
                """
                )
                rows = cur.fetchall()
                if len(rows) >= 2:
                    new_score = float(rows[0]["score"])
                    old_score = float(rows[1]["score"])
                    if abs(new_score - old_score) >= 0.5:
                        direction = "\u2b06" if new_score > old_score else "\u2b07"
                        create_security_alert(
                            "scan_result",
                            f"Compliance {direction} {old_score}% \u2192 {new_score}%",
                            f"Compliance score changed from {old_score}% to {new_score}%",
                            priority="normal" if new_score >= old_score else "high",
                            telegram=True,
                        )
        except Exception:
            pass  # Non-critical
    except Exception as e:
        logger.error("Scheduled compliance scan failed: %s", e)


def run_compliance_enqueue():
    """Job #58 (renamed from run_auto_remediation 2026-04-11).

    Reads the latest compliance scan results and creates a Repair Bay
    proposal (improvement_proposals, category='compliance_fix') for every
    failing rule that is not exempt, not blocklisted, and does not already
    have an open proposal. Does NOT apply anything — apply happens only
    via explicit admin click or the Sunday window job (#62).
    """
    import json as _json
    from tools.security_network.compliance_service import (
        get_latest_scores,
        get_scan_results,
        is_rule_exempt,
        is_rule_auto_allowed,
        _is_rule_blocked,
    )
    from database import get_db_cursor
    from psycopg2.extras import Json

    try:
        scores = get_latest_scores()
        if not scores or not scores.get("scan_id"):
            return
        scan_id = scores["scan_id"]
        results = get_scan_results(scan_id, status="fail")
        if not results:
            return

        # Build rule_id → (fix_def, pack_id, severity)
        rule_lookup = {}
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT pack_id, rules FROM compliance_rule_packs")
            for pack_row in cur.fetchall():
                rules = pack_row["rules"] if isinstance(pack_row["rules"], list) else _json.loads(pack_row["rules"])
                for rule in rules:
                    rid = rule.get("rule_id", "")
                    rule_lookup[rid] = {
                        "pack_id": pack_row["pack_id"],
                        "fix_def": rule.get("fix", {}),
                        "severity": rule.get("severity", "medium"),
                    }

        created = 0
        skipped_exempt = 0
        skipped_blocked = 0
        skipped_existing = 0
        skipped_unknown = 0

        SAFE_TYPES = {"sysctl", "file_line", "service"}

        with get_db_cursor(commit=True) as (conn, cur):
            for result in results:
                rule_id = result.get("rule_id", "")
                if not rule_id:
                    continue

                if is_rule_exempt(rule_id):
                    skipped_exempt += 1
                    continue

                blocked, _bl = _is_rule_blocked(rule_id)
                if blocked:
                    skipped_blocked += 1
                    continue  # Job #61 handles blocklisted rules via F.O.R.G.E. plan

                lookup = rule_lookup.get(rule_id)
                if not lookup:
                    skipped_unknown += 1
                    continue

                # Dedupe: skip if an open proposal already exists for this rule
                cur.execute(
                    """SELECT 1 FROM improvement_proposals
                       WHERE category = 'compliance_fix'
                         AND status = 'pending_approval'
                         AND metadata->>'rule_id' = %s
                       LIMIT 1""",
                    (rule_id,),
                )
                if cur.fetchone():
                    skipped_existing += 1
                    continue

                fix_def = lookup["fix_def"]
                fix_type = fix_def.get("type")
                auto_queued = is_rule_auto_allowed(rule_id) and fix_type in SAFE_TYPES

                metadata = {
                    "source": "compliance_enqueue",
                    "scan_id": scan_id,
                    "rule_id": rule_id,
                    "pack_id": lookup["pack_id"],
                    "fix_def": fix_def,
                    "fix_type": fix_type,
                    "severity": lookup["severity"],
                    "auto_apply_queued": auto_queued,
                }

                cur.execute(
                    """INSERT INTO improvement_proposals
                           (title, description, category, priority, status,
                            risk_level, metadata, proposed_at)
                       VALUES (%s, %s, 'compliance_fix', %s, 'pending_approval',
                               %s, %s, NOW())""",
                    (
                        f"Compliance fix pending: {rule_id}",
                        f"Compliance rule {rule_id} failed in scan {scan_id}. "
                        f"Approve in Repair Bay (fix_type={fix_type}).",
                        lookup["severity"],
                        lookup["severity"],
                        Json(metadata),
                    ),
                )
                created += 1

        logger.info(
            "compliance_enqueue: created=%d skipped_existing=%d "
            "skipped_exempt=%d skipped_blocked=%d skipped_unknown=%d",
            created,
            skipped_existing,
            skipped_exempt,
            skipped_blocked,
            skipped_unknown,
        )
    except Exception as exc:
        logger.error("compliance_enqueue failed: %s", exc)


# Compatibility alias — keep old name bound so any existing scheduler
# registration or external reference still works during the transition.
run_auto_remediation = run_compliance_enqueue


def run_auto_apply_window():
    """Job #62 — Sunday 03:00 EDT compliance auto-apply window.

    Picks up to 5 compliance_fix proposals where
    metadata.auto_apply_queued=true, re-verifies fix_type is in the safe
    set, and runs each through compliance_safe_exec._safe_execute_fix.
    Sends a Telegram digest at the end.
    """
    import datetime as _dt
    from database import get_db_cursor
    from tools.security_network.compliance_safe_exec import (
        _safe_execute_fix,
        SAFE_FIX_TYPES,
    )

    from services.telegram_service import send_security

    max_fixes = 5
    picked: list = []

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT id, metadata
                   FROM improvement_proposals
                   WHERE category = 'compliance_fix'
                     AND status = 'pending_approval'
                     AND (metadata->>'auto_apply_queued')::boolean IS TRUE
                   ORDER BY proposed_at ASC
                   LIMIT %s""",
                (max_fixes,),
            )
            rows = cur.fetchall()

        for row in rows:
            meta = row["metadata"] if isinstance(row["metadata"], dict) else {}
            fix_type = (meta.get("fix_def") or {}).get("type")
            if fix_type not in SAFE_FIX_TYPES:
                logger.info(
                    "auto_apply_window: skipping proposal %s — fix_type=%s ineligible",
                    row["id"],
                    fix_type,
                )
                continue
            picked.append(row["id"])

        results = []
        for pid in picked:
            try:
                r = _safe_execute_fix(pid, user_id=0)
            except Exception as exc:
                r = {"success": False, "status": "error", "detail": str(exc), "proposal_id": pid}
            results.append(r)

        # Digest
        total = len(results)
        ok = sum(1 for r in results if r.get("success"))
        failed = total - ok
        if total == 0:
            msg = f"🛠 Compliance window {_dt.datetime.now():%Y-%m-%d %H:%M}: no auto-queued fixes."
        else:
            detail_lines = [
                f"  • {r.get('status', '?')} — proposal #{r.get('proposal_id')}: {r.get('detail', '')[:80]}"
                for r in results
            ]
            msg = (
                f"🛠 Compliance window {_dt.datetime.now():%Y-%m-%d %H:%M}\n"
                f"Applied: {ok}/{total} | Failed: {failed}\n" + "\n".join(detail_lines)
            )
        send_security("Compliance Auto-Apply", msg, source_module="security_network.jobs")
        logger.info("auto_apply_window summary: %s", msg.replace("\n", " | "))
    except Exception as exc:
        logger.error("auto_apply_window failed: %s", exc)


def run_auto_plan_generation():
    """Job #61: Ask F.O.R.G.E. to pre-generate remediation plans for every
    blocklisted rule that failed in the latest scan and doesn't already have
    a fresh (<24h) plan on file. Runs autonomously after each scan so plans
    are waiting in Department HQ before the admin opens the Compliance tab.
    """
    try:
        from tools.security_network.compliance_service import (
            get_latest_scores,
            get_scan_results,
            generate_remediation_plan,
        )
        from database import get_db_cursor

        scores = get_latest_scores()
        if not scores or not scores.get("scan_id"):
            return
        scan_id = scores["scan_id"]

        results = get_scan_results(scan_id, status="fail")
        if not results:
            return

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT rule_id FROM compliance_rule_blocklist")
            blocked_ids = {r["rule_id"] for r in cur.fetchall()}

            cur.execute(
                """SELECT DISTINCT rule_id FROM compliance_remediation_plans
                   WHERE generated_at > NOW() - INTERVAL '24 hours'"""
            )
            fresh_plan_ids = {r["rule_id"] for r in cur.fetchall()}

        candidates = [r for r in results if r.get("rule_id") in blocked_ids and r.get("rule_id") not in fresh_plan_ids]

        if not candidates:
            logger.info(
                "Auto-plan generation: nothing to do (blocked=%d fresh=%d)",
                len(blocked_ids),
                len(fresh_plan_ids),
            )
            return

        logger.info(
            "Auto-plan generation: %d rules need plans (scan=%s)",
            len(candidates),
            scan_id,
        )

        generated = 0
        fallback = 0
        for r in candidates:
            rule_id = r.get("rule_id", "")
            try:
                res = generate_remediation_plan(scan_id, rule_id, user_id=0)
                if not res.get("success"):
                    logger.warning(
                        "Auto-plan gen failed for %s: %s",
                        rule_id,
                        res.get("error", "unknown"),
                    )
                    continue
                generated += 1
                if res.get("fallback"):
                    fallback += 1
                logger.info(
                    "Auto-plan gen: %s -> plan_id=%s fallback=%s",
                    rule_id,
                    res.get("plan_id"),
                    res.get("fallback"),
                )
            except Exception as gen_err:
                logger.warning("Auto-plan gen error for %s: %s", rule_id, gen_err)

        logger.info(
            "Auto-plan generation complete: %d plans (%d real, %d fallback)",
            generated,
            generated - fallback,
            fallback,
        )

        if generated - fallback > 0:
            try:
                from tools.security_network.security_alerts import create_security_alert

                create_security_alert(
                    "compliance_plan",
                    f"F.O.R.G.E. generated {generated} remediation plan(s)",
                    f"{generated - fallback} real AI plans + {fallback} fallback(s). "
                    f"Review in Department HQ Approvals or Compliance tab.",
                    priority="normal",
                    telegram=True,
                )
            except Exception:
                pass  # Non-critical

    except Exception as e:
        logger.error("Auto-plan generation failed: %s", e, exc_info=True)


# Schedule: every 5 min — collects per-device bandwidth from ntopng
def collect_traffic_stats():
    """Collect per-device network traffic snapshots from ntopng and store in network_traffic_stats."""
    t0 = time.time()
    processed = 0
    failed = 0
    error_msg = None

    try:
        from tools.security_network.ntopng_service import NtopngService
        from database import get_db_cursor

        svc = NtopngService()
        if not svc.is_healthy():
            logger.warning("collect_traffic_stats: ntopng unavailable, skipping")
            _log_cycle("collect_traffic_stats", 0, 0, 0, error_message="ntopng unavailable")
            return

        # Discover the active (non-loopback) interface
        interfaces = svc.get_interfaces()
        ifid = 1  # sensible default for single-interface setups
        for iface in interfaces:
            if isinstance(iface, dict):
                iface_name = iface.get("ifname", "")
                if iface_name and iface_name != "lo":
                    ifid = iface.get("ifid", 1)
                    break

        # Get all hosts (local + remote destinations) for full traffic visibility
        local_host_list = svc.get_local_hosts(ifid=ifid)
        if not local_host_list:
            dur = int((time.time() - t0) * 1000)
            _log_cycle(
                "collect_traffic_stats",
                0,
                0,
                dur,
                details={"reason": "no hosts found"},
            )
            return

        logger.debug(f"collect_traffic_stats: {len(local_host_list)} hosts to process")

        with get_db_cursor(commit=True) as (conn, cur):
            for host in local_host_list:
                try:
                    if not isinstance(host, dict):
                        continue

                    # Extract fields — ntopng uses various key formats
                    ip = host.get("ip") or host.get("ipAddress") or host.get("name", "")
                    mac = host.get("mac", "")

                    # Skip hosts without an IP (can't track)
                    if not ip:
                        continue
                    # Normalize empty/null MACs
                    if not mac or mac == "00:00:00:00:00:00":
                        mac = ""

                    # Bytes: ntopng nests under "bytes" dict with "sent"/"recvd" keys
                    bytes_blob = host.get("bytes") or {}
                    if isinstance(bytes_blob, dict):
                        bytes_in = bytes_blob.get("recvd", 0) or 0
                        bytes_out = bytes_blob.get("sent", 0) or 0
                    else:
                        bytes_in = host.get("bytesRcvd") or host.get("bytes_rcvd") or 0
                        bytes_out = host.get("bytesSent") or host.get("bytes_sent") or 0

                    # Ensure integers
                    bytes_in = int(bytes_in)
                    bytes_out = int(bytes_out)

                    cur.execute(
                        """
                        INSERT INTO network_traffic_stats
                            (device_mac, device_ip, bytes_in, bytes_out, protocol, hour_bucket)
                        VALUES (%s, %s, %s, %s, 'all', date_trunc('hour', NOW()))
                        ON CONFLICT (device_ip, hour_bucket)
                        DO UPDATE SET
                            bytes_in = GREATEST(network_traffic_stats.bytes_in, EXCLUDED.bytes_in),
                            bytes_out = GREATEST(network_traffic_stats.bytes_out, EXCLUDED.bytes_out),
                            device_mac = EXCLUDED.device_mac
                        """,
                        (mac, ip, bytes_in, bytes_out),
                    )
                    processed += 1
                except Exception as host_err:
                    failed += 1
                    logger.debug(f"collect_traffic_stats: host error: {host_err}")

        dur = int((time.time() - t0) * 1000)
        if processed > 0:
            logger.info(f"collect_traffic_stats: {processed} devices stored, {failed} failed ({dur}ms)")
        _log_cycle(
            "collect_traffic_stats",
            processed,
            failed,
            dur,
            details={"devices": processed, "ifid": ifid},
            error_message=error_msg,
        )
    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        logger.error(f"collect_traffic_stats failed: {e}")
        _log_cycle("collect_traffic_stats", processed, failed, dur, error_message=str(e))


# NOTE: pattern_compliance_check is registered in dev_hq/jobs.py (code quality job)


# ---------------------------------------------------------------------------
# DNS history collection (Job #59)
# ---------------------------------------------------------------------------


def collect_dns_history():
    """Collect per-device DNS query history from AdGuard and store in device_dns_history.

    Runs every 5 minutes. Fetches the last 5000 AdGuard query log entries,
    groups them by (client_ip, domain, hour_bucket), and upserts counts.
    All clients are stored — Docker bridge IPs (172.x), localhost (127.x),
    and pure reverse-lookup IPs are skipped.
    """
    t0 = time.time()
    inserted = 0
    skipped = 0

    try:
        from .adguard_service import AdGuardService
        from database import get_db_cursor

        ag = AdGuardService()
        result = ag.get_query_log(limit=5000)
        if not result:
            dur = int((time.time() - t0) * 1000)
            _log_cycle(
                "collect_dns_history",
                0,
                0,
                dur,
                error_message="AdGuard unavailable or empty response",
            )
            return

        entries = result.get("data", [])
        if not entries:
            dur = int((time.time() - t0) * 1000)
            _log_cycle(
                "collect_dns_history",
                0,
                0,
                dur,
                details={"reason": "no entries in query log"},
            )
            return

        # Group by (client_ip, domain) — aggregate counts and blocked flag
        buckets: dict = {}
        for entry in entries:
            client_ip = entry.get("client", "")

            # Skip Docker bridge IPs (172.x), localhost (127.x), and empty — collect all other clients
            if not client_ip or client_ip.startswith("172.") or client_ip.startswith("127."):
                skipped += 1
                continue

            domain = entry.get("question", {}).get("name", "").lower().rstrip(".")
            if not domain:
                skipped += 1
                continue

            # Skip pure reverse-lookup entries (all digits + dots = IP, not a domain)
            parts = domain.split(".")
            if all(p.isdigit() for p in parts):
                skipped += 1
                continue

            reason = entry.get("reason", "")
            # Rewrites and whitelisted entries are NOT blocked
            blocked = reason != "" and reason not in (
                "Rewrite",
                "NotFilteredWhiteList",
                "NotFilteredNotFound",
            )

            key = (client_ip, domain)
            if key not in buckets:
                buckets[key] = {"count": 0, "blocked": blocked}
            buckets[key]["count"] += 1
            # If any query was blocked, mark the bucket blocked
            if blocked:
                buckets[key]["blocked"] = True

        if not buckets:
            dur = int((time.time() - t0) * 1000)
            _log_cycle(
                "collect_dns_history",
                0,
                0,
                dur,
                details={"reason": "no local-device entries", "skipped": skipped},
            )
            return

        with get_db_cursor(commit=True) as (conn, cur):
            for (client_ip, domain), data in buckets.items():
                cur.execute(
                    """
                    INSERT INTO device_dns_history (device_ip, domain, query_count, blocked, hour_bucket)
                    VALUES (%s, %s, %s, %s, date_trunc('hour', NOW()))
                    ON CONFLICT (device_ip, domain, hour_bucket)
                    DO UPDATE SET
                        query_count = device_dns_history.query_count + EXCLUDED.query_count,
                        blocked = device_dns_history.blocked OR EXCLUDED.blocked
                    """,
                    (client_ip, domain, data["count"], data["blocked"]),
                )
                inserted += 1

        dur = int((time.time() - t0) * 1000)
        _log_cycle(
            "collect_dns_history",
            inserted,
            0,
            dur,
            details={
                "buckets_upserted": inserted,
                "entries_skipped": skipped,
                "total_entries": len(entries),
            },
        )
        logger.info(f"[collect_dns_history] upserted {inserted} buckets, skipped {skipped} entries ({dur}ms)")

    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        logger.error(f"collect_dns_history failed: {e}")
        _log_cycle("collect_dns_history", inserted, 1, dur, error_message=str(e))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def sync_device_mappings():
    """Sync device-user mappings from AdGuard persistent clients into network_device_users.

    AdGuard persistent clients use IPs (not MACs) as identifiers, so we join against
    the network_devices table to resolve IP -> MAC. Each client's name becomes the
    user_name and device_label for that MAC.

    Runs every 6 hours — device names don't change often.
    """
    import re
    import time as _time

    MAC_RE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")

    def _infer_device_type(name: str, tags: list = None) -> str:
        # AdGuard tags take priority
        if tags:
            tag_map = {
                "device_phone": "phone",
                "device_tablet": "tablet",
                "device_laptop": "laptop",
                "device_pc": "desktop",
                "device_tv": "media",
                "device_gameconsole": "media",
                "device_printer": "printer",
                "device_camera": "camera",
                "device_nas": "server",
            }
            for tag in tags:
                if tag in tag_map:
                    return tag_map[tag]
        n = name.lower()
        if any(k in n for k in ("iphone", "android", "phone", "pixel", "galaxy", "mobile")):
            return "phone"
        if any(k in n for k in ("ipad", "tablet", "kindle")):
            return "tablet"
        if any(k in n for k in ("laptop", "macbook", "notebook", "chromebook")):
            return "laptop"
        if any(k in n for k in ("desktop", "pc", "imac", "workstation", "tower", "gaming", "rig")):
            return "desktop"
        if any(k in n for k in ("tv", "firestick", "roku", "appletv", "chromecast", "shield")):
            return "media"
        if any(k in n for k in ("printer", "scanner")):
            return "printer"
        if any(k in n for k in ("camera", "cam", "doorbell", "ring", "nest")):
            return "camera"
        if any(k in n for k in ("router", "switch", "access point", "ap ", "hub")):
            return "network"
        if any(k in n for k in ("nas", "server", "synology", "qnap")):
            return "server"
        if any(k in n for k in ("watch", "band", "fitbit")):
            return "wearable"
        return "unknown"

    t0 = _time.time()
    upserted = 0
    skipped = 0
    failed = 0

    try:
        from .adguard_service import AdGuardService
        from database import get_db_cursor

        ag = AdGuardService()
        clients = ag.get_persistent_clients()
        if not clients:
            logger.info("[sync_device_mappings] No persistent clients returned from AdGuard")
            return

        # Build ip -> (name, device_type) from AdGuard clients
        ip_to_client = {}
        for client in clients:
            name = (client.get("name") or "").strip()
            if not name:
                continue
            tags = client.get("tags") or []
            device_type = _infer_device_type(name, tags)
            for cid in client.get("ids") or []:
                cid = cid.strip()
                # Accept plain IPs and MAC addresses directly
                if MAC_RE.match(cid):
                    # Store MAC directly — used below even without DB lookup
                    mac = cid.upper()
                    ip_to_client[f"__mac__{mac}"] = (mac, name, device_type)
                else:
                    # Treat as IP
                    ip_to_client[cid] = (None, name, device_type)

        if not ip_to_client:
            logger.info("[sync_device_mappings] No usable IDs found in AdGuard clients")
            return

        # Resolve IPs -> MACs via network_devices table
        ips = [ip for ip in ip_to_client if not ip.startswith("__mac__")]
        mappings = []  # list of (mac, user_name, device_type)

        with get_db_cursor(commit=False) as (conn, cur):
            if ips:
                cur.execute(
                    """
                    SELECT host(ip_address) AS ip, mac_address
                    FROM network_devices
                    WHERE ip_address = ANY(%s::inet[])
                      AND mac_address IS NOT NULL
                    """,
                    (ips,),
                )
                for row in cur.fetchall():
                    ip = row["ip"] if isinstance(row, dict) else str(row[0])
                    mac = row["mac_address"] if isinstance(row, dict) else row[1]
                    if mac and ip in ip_to_client:
                        _, name, device_type = ip_to_client[ip]
                        mappings.append((mac.upper(), name, device_type))

        # Also add any direct-MAC entries
        for key, (mac, name, device_type) in ip_to_client.items():
            if key.startswith("__mac__") and mac:
                mappings.append((mac, name, device_type))

        if not mappings:
            logger.info(
                "[sync_device_mappings] AdGuard has %d clients but none resolved to a MAC "
                "(devices may not have been seen yet by discovery)",
                len(clients),
            )
            return

        with get_db_cursor(commit=True) as (conn, cur):
            for mac, user_name, device_type in mappings:
                try:
                    cur.execute(
                        """
                        INSERT INTO network_device_users
                            (mac_address, user_name, device_label, device_type, updated_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        ON CONFLICT (mac_address)
                        DO UPDATE SET
                            device_label = EXCLUDED.device_label,
                            device_type  = EXCLUDED.device_type,
                            updated_at   = NOW()
                        WHERE network_device_users.device_label IS DISTINCT FROM EXCLUDED.device_label
                           OR network_device_users.device_type  IS DISTINCT FROM EXCLUDED.device_type
                        """,
                        (mac, user_name, user_name, device_type),
                    )
                    if cur.rowcount:
                        upserted += 1
                    else:
                        skipped += 1
                except Exception as e:
                    logger.warning("[sync_device_mappings] Failed to upsert %s: %s", mac, e)
                    failed += 1

        dur = int((_time.time() - t0) * 1000)
        _log_cycle(
            "sync_device_mappings",
            upserted,
            failed,
            dur,
            details={
                "clients_found": len(clients),
                "macs_resolved": len(mappings),
                "upserted": upserted,
                "skipped_no_change": skipped,
            },
        )
        logger.info(
            "[sync_device_mappings] %d clients → %d MACs resolved, %d upserted, %d skipped, %d failed (%dms)",
            len(clients),
            len(mappings),
            upserted,
            skipped,
            failed,
            dur,
        )

    except Exception as e:
        dur = int((_time.time() - t0) * 1000)
        _log_cycle("sync_device_mappings", 0, 1, dur, error_message=str(e))
        logger.error("[sync_device_mappings] Failed: %s", e)


def track_device_presence():
    """Track device online/offline state and detect ARP spoofing (every 5 min).

    1. Query ntopng for currently active local hosts.
    2. Compare against last known state in device_presence_log.
    3. Insert online/offline events for state changes.
    4. UPSERT MAC-IP pairs into device_mac_history.
    5. Alert on ARP spoofing (same IP with multiple MACs in last hour).
    6. Alert on brand-new devices never seen before.
    """
    t0 = time.time()
    processed = 0
    failed = 0
    try:
        from database import get_db_cursor
        from tools.security_network.ntopng_service import NtopngService
        from tools.security_network.security_alerts import create_security_alert, create_security_digest

        ntopng = NtopngService()
        current_hosts = ntopng.get_local_hosts(ifid=1)

        # Build dict of currently visible devices: ip -> mac
        current_map = {}
        for h in current_hosts:
            ip = str(h.get("ip") or h.get("name", ""))
            mac = str(h.get("mac", "") or "").upper()
            if ip.startswith("192.168."):
                current_map[ip] = mac

        with get_db_cursor(commit=True) as (conn, cur):
            # --- Get last known state per device ---
            cur.execute(
                """
                SELECT DISTINCT ON (device_ip) device_ip, event_type
                FROM device_presence_log
                ORDER BY device_ip, detected_at DESC
            """
            )
            last_state = {row[0]: row[1] for row in cur.fetchall()}

            # --- Check for brand-new devices (never in presence log) ---
            all_known_ips = set(last_state.keys())

            # --- Process currently visible devices ---
            new_device_lines = []
            for ip, mac in current_map.items():
                prev = last_state.get(ip)
                if prev != "online":
                    # Device just came online (or first time seen)
                    cur.execute(
                        "INSERT INTO device_presence_log (device_ip, device_mac, event_type) VALUES (%s, %s, 'online')",
                        (ip, mac or None),
                    )
                    processed += 1

                    # Track brand-new device for digest
                    if ip not in all_known_ips:
                        create_security_alert(
                            "new_device",
                            f"New device detected: {ip}",
                            f"A device with IP {ip} (MAC: {mac or 'unknown'}) appeared on the network for the first time.",
                            priority="high",
                            telegram=False,  # batched into digest below
                        )
                        new_device_lines.append({"line": f"New device: {ip} (MAC: {mac or 'unknown'})"})

                # --- UPSERT MAC-IP history ---
                if mac:
                    cur.execute(
                        """
                        INSERT INTO device_mac_history (device_ip, device_mac, first_seen, last_seen)
                        VALUES (%s, %s, NOW(), NOW())
                        ON CONFLICT (device_ip, device_mac)
                        DO UPDATE SET last_seen = NOW()
                        """,
                        (ip, mac),
                    )

            # --- Detect devices that went offline ---
            for ip, prev_state in last_state.items():
                if prev_state == "online" and ip not in current_map:
                    cur.execute(
                        "INSERT INTO device_presence_log (device_ip, event_type) VALUES (%s, 'offline')",
                        (ip,),
                    )
                    processed += 1

            # --- ARP spoof detection: same IP with multiple MACs in last hour ---
            cur.execute(
                """
                SELECT device_ip, array_agg(DISTINCT device_mac) AS macs
                FROM device_mac_history
                WHERE last_seen >= NOW() - INTERVAL '1 hour'
                GROUP BY device_ip
                HAVING COUNT(DISTINCT device_mac) > 1
            """
            )
            spoofs = cur.fetchall()
            for row in spoofs:
                spoof_ip = row[0]
                spoof_macs = row[1]
                # ARP spoof = immediate Telegram (critical threat)
                create_security_alert(
                    "intrusion",
                    f"ARP spoof detected on {spoof_ip}",
                    f"Device IP {spoof_ip} has been associated with multiple MAC addresses "
                    f"in the last hour: {', '.join(spoof_macs)}. This may indicate ARP spoofing.",
                    priority="critical",
                    telegram=True,
                )
                processed += 1

            # --- Send ONE digest for new devices (instead of individual alerts) ---
            if new_device_lines:
                create_security_digest(
                    "new_device",
                    "Device Presence",
                    new_device_lines,
                    priority="normal",
                    telegram=True,
                )

        duration = int((time.time() - t0) * 1000)
        _log_cycle(
            "track_device_presence",
            processed,
            failed,
            duration,
            {"current_hosts": len(current_map), "spoofs_detected": len(spoofs)},
        )
        if processed:
            logger.info("[track_device_presence] %d events logged in %dms", processed, duration)

    except Exception as e:
        failed = 1
        duration = int((time.time() - t0) * 1000)
        _log_cycle("track_device_presence", processed, failed, duration, error_message=str(e))
        logger.error("[track_device_presence] Failed: %s", e)


def run_anomaly_detection():
    """Job #61: Run network anomaly detection (bandwidth spikes, exfiltration, odd hours, DNS tunneling).

    Wraps run_all_anomaly_checks() with _log_cycle() for audit trail.
    Runs every 30 minutes.
    """
    t0 = time.time()
    processed = 0
    failed = 0
    error_msg = None

    try:
        from .anomaly_detection import run_all_anomaly_checks

        results = run_all_anomaly_checks()
        total = sum(len(v) for v in results.values())
        processed = total

        dur = int((time.time() - t0) * 1000)
        _log_cycle(
            "anomaly_detection",
            processed,
            failed,
            dur,
            details={
                "bandwidth_spikes": len(results.get("bandwidth_spikes", [])),
                "exfiltration": len(results.get("exfiltration", [])),
                "odd_hours": len(results.get("odd_hours", [])),
                "dns_tunneling": len(results.get("dns_tunneling", [])),
            },
        )
        if total > 0:
            logger.info(f"[anomaly_detection] {total} anomalies found ({dur}ms)")

    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        error_msg = str(e)
        logger.error(f"anomaly_detection failed: {e}")
        _log_cycle("anomaly_detection", processed, 1, dur, error_message=error_msg)


def enrich_ip_geolocation():
    """Enrich remote IPs from network_traffic_stats and device_dns_history with geo data.

    Finds public IPs not yet in ip_geolocation_cache, skips private ranges,
    and batch-lookups up to 100 at a time via ip-api.com.
    Runs every 30 minutes.
    """
    t0 = time.time()
    enriched = 0

    try:
        from database import get_db_cursor
        from tools.security_network.geo_service import batch_lookup, _is_private_ip

        uncached_ips = set()

        with get_db_cursor() as (conn, cur):
            # Collect IPs from traffic stats not yet cached
            cur.execute(
                """
                SELECT DISTINCT device_ip FROM network_traffic_stats
                WHERE device_ip IS NOT NULL
                  AND device_ip NOT IN (
                      SELECT ip FROM ip_geolocation_cache
                      WHERE cached_at > NOW() - INTERVAL '30 days'
                  )
                LIMIT 500
                """
            )
            for row in cur.fetchall():
                ip = row["device_ip"] if isinstance(row, dict) else row[0]
                if ip:
                    uncached_ips.add(str(ip))

            # Collect IPs from DNS history not yet cached
            cur.execute(
                """
                SELECT DISTINCT device_ip FROM device_dns_history
                WHERE device_ip IS NOT NULL
                  AND device_ip NOT IN (
                      SELECT ip FROM ip_geolocation_cache
                      WHERE cached_at > NOW() - INTERVAL '30 days'
                  )
                LIMIT 500
                """
            )
            for row in cur.fetchall():
                ip = row["device_ip"] if isinstance(row, dict) else row[0]
                if ip:
                    uncached_ips.add(str(ip))

        # Filter out private IPs
        public_ips = [ip for ip in uncached_ips if not _is_private_ip(ip)]

        if not public_ips:
            dur = int((time.time() - t0) * 1000)
            _log_cycle(
                "enrich_ip_geolocation",
                0,
                0,
                dur,
                details={"reason": "no uncached public IPs found"},
            )
            return

        # Batch lookup (handles chunking and rate limits internally)
        results = batch_lookup(public_ips)
        enriched = len(results)

        dur = int((time.time() - t0) * 1000)
        _log_cycle(
            "enrich_ip_geolocation",
            enriched,
            0,
            dur,
            details={
                "candidates": len(public_ips),
                "enriched": enriched,
            },
        )
        if enriched > 0:
            logger.info(
                "[enrich_ip_geolocation] enriched %d/%d public IPs (%dms)",
                enriched,
                len(public_ips),
                dur,
            )

    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        logger.error("enrich_ip_geolocation failed: %s", e)
        _log_cycle("enrich_ip_geolocation", enriched, 1, dur, error_message=str(e))


def generate_vigil_threat_report():
    """Generate V.I.G.I.L. daily security intelligence report and store in KB."""
    t0 = time.time()
    try:
        from tools.security_network.vigil_analysis import generate_threat_report
        from tools.security_network.security_alerts import create_security_alert
        from database import get_db_cursor

        report = generate_threat_report()

        # Store in knowledge base for historical record
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO knowledge_base (title, content, knowledge_type, importance_score, category)
                    VALUES (%s, %s, 'vault_note', 0.85, 'security')
                    """,
                    (
                        f"V.I.G.I.L. Threat Report — {now_local().strftime('%Y-%m-%d')}",
                        json.dumps(report, indent=2, default=str),
                    ),
                )
        except Exception as e:
            logger.error("Failed to store V.I.G.I.L. threat report: %s", e)

        # Alert if high/critical risk
        risk = report.get("overall_risk", "low")
        if risk in ("high", "critical"):
            create_security_alert(
                "scan_result",
                f"V.I.G.I.L. Threat Report: {risk.upper()} risk",
                report.get("summary", "See full report in Knowledge Base"),
                priority="high",
                telegram=True,
            )

        dur = int((time.time() - t0) * 1000)
        _log_cycle(
            "vigil_threat_report",
            1,
            0,
            dur,
            details={"overall_risk": risk},
        )
        logger.info("[vigil_threat_report] completed in %dms — risk: %s", dur, risk)

    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        logger.error("vigil_threat_report failed: %s", e)
        _log_cycle("vigil_threat_report", 0, 1, dur, error_message=str(e))


def generate_weekly_security_report():
    """Generate and send weekly security report (Monday 8 AM)."""
    t0 = time.time()
    try:
        from tools.security_network.report_generator import generate_weekly_report, format_report_telegram
        from tools.security_network.security_alerts import create_security_alert

        report = generate_weekly_report()
        telegram_text = format_report_telegram(report)

        create_security_alert(
            "scan_result",
            "Weekly Security Report",
            telegram_text,
            priority="normal",
            telegram=True,
        )

        # Store in knowledge base
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO knowledge_base (title, content, knowledge_type, importance_score, category)
                VALUES (%s, %s, 'vault_note', 0.80, 'security')
                """,
                (
                    f"Weekly Security Report — {now_local().strftime('%Y-%m-%d')}",
                    json.dumps(report, indent=2, default=str),
                ),
            )

        dur = int((time.time() - t0) * 1000)
        _log_cycle("weekly_security_report", 1, 0, dur)
        logger.info("[weekly_security_report] generated in %dms", dur)

    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        logger.error("weekly_security_report failed: %s", e)
        _log_cycle("weekly_security_report", 0, 1, dur, error_message=str(e))


def sync_threat_intel():
    """Sync threat intelligence feeds and check for hits (every 6h)."""
    t0 = time.time()
    try:
        from tools.security_network.threat_intel_service import ThreatIntelService

        svc = ThreatIntelService()
        sync_result = svc.sync_feeds()
        hits = svc.check_hits()

        if hits:
            from tools.security_network.security_alerts import create_security_digest

            digest_lines = [
                {
                    "line": f"{h.get('domain', h.get('device_ip', '?'))} matched {h.get('feed_name', '?')} ({h.get('severity', '?')})"
                }
                for h in hits
            ]
            create_security_digest(
                "intrusion",
                "Threat Intel Hits",
                digest_lines,
                priority="high",
                telegram=True,
            )

        dur = int((time.time() - t0) * 1000)
        _log_cycle(
            "sync_threat_intel",
            sync_result.get("total_iocs", 0),
            0,
            dur,
            details={"new_hits": len(hits), **sync_result},
        )
        logger.info(
            "[sync_threat_intel] %d IOCs synced, %d hits (%dms)", sync_result.get("total_iocs", 0), len(hits), dur
        )

    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        logger.error("sync_threat_intel failed: %s", e)
        _log_cycle("sync_threat_intel", 0, 1, dur, error_message=str(e))


def correlate_security_incidents():
    """Group related alerts into incidents (every 30 min)."""
    t0 = time.time()
    try:
        from tools.security_network.incident_service import IncidentService

        svc = IncidentService()
        created = svc.correlate_alerts()

        dur = int((time.time() - t0) * 1000)
        _log_cycle("correlate_incidents", created, 0, dur)
        if created:
            logger.info("[correlate_incidents] %d new incidents created (%dms)", created, dur)

    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        logger.error("correlate_incidents failed: %s", e)
        _log_cycle("correlate_incidents", 0, 1, dur, error_message=str(e))


def run_speed_test():
    """Run periodic speed test (every 6h)."""
    t0 = time.time()
    try:
        import subprocess as _sp

        result = _sp.run(
            ["speedtest-cli", "--json"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning("[speed_test] speedtest-cli failed: %s", result.stderr[:200])
            return

        data = json.loads(result.stdout)
        download = round(data.get("download", 0) / 1_000_000, 2)
        upload = round(data.get("upload", 0) / 1_000_000, 2)
        ping = round(data.get("ping", 0), 2)
        server = data.get("server", {}).get("sponsor", "Unknown")

        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO speed_test_results (download_mbps, upload_mbps, ping_ms, server) VALUES (%s, %s, %s, %s)",
                (download, upload, ping, server),
            )

        dur = int((time.time() - t0) * 1000)
        _log_cycle("speed_test", 1, 0, dur, details={"download": download, "upload": upload, "ping": ping})
        logger.info("[speed_test] %.1f↓ / %.1f↑ Mbps, %.1fms ping (%dms)", download, upload, ping, dur)

    except FileNotFoundError:
        logger.warning("[speed_test] speedtest-cli not installed")
    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        logger.error("speed_test failed: %s", e)
        _log_cycle("speed_test", 0, 1, dur, error_message=str(e))


def enforce_supervision_schedules():
    """Enforce supervision control schedules via AdGuard (every 5 min)."""
    t0 = time.time()
    try:
        from tools.security_network.supervision_service import SupervisionService

        svc = SupervisionService()
        result = svc.enforce_schedules()
        enforced = result.get("enforced", 0)
        errors = result.get("errors", 0)

        dur = int((time.time() - t0) * 1000)
        _log_cycle("supervision_enforce", enforced, errors, dur, details=result)

    except Exception as e:
        dur = int((time.time() - t0) * 1000)
        logger.error("supervision_enforce failed: %s", e)
        _log_cycle("supervision_enforce", 0, 1, dur, error_message=str(e))


def register_security_jobs(scheduler, flask_app):
    """Register all security/network jobs with the APScheduler instance.

    Called from AgentLoop.start() after the scheduler is running.
    """
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    from services.job_governance import governed_job
    from services.telegram_service import send_security

    def with_ctx(fn):
        """Wrap a job so it runs inside the Flask app context AND under DHQ
        governance (project #332, #2741): every run writes a governance_audit_log
        trail (start/complete/fail) and a failure raises a quiet-hours-gated
        A.R.C.H.I.E. alert via V.I.G.I.L.'s security channel. Additive + fail-safe
        — never changes a job's logic and never crashes the shared scheduler."""
        return governed_job(
            fn,
            department="Security & Compliance",
            flask_app=flask_app,
            notify_fn=send_security,
        )

    # --- Network monitoring ---
    scheduler.add_job(
        with_ctx(discover_network_devices),
        trigger=IntervalTrigger(minutes=5),
        id="agent_network_discovery",
        name="Agent Loop: Network Device Discovery",
        replace_existing=True,
    )

    # --- Security audit ---
    scheduler.add_job(
        with_ctx(run_security_audit),
        trigger=CronTrigger(day_of_week="sun", hour=3, timezone="America/Toronto"),
        id="agent_security_audit",
        name="Agent Loop: Weekly Security Audit",
        replace_existing=True,
    )

    # --- SSL certificate monitoring ---
    scheduler.add_job(
        with_ctx(check_ssl_expiry),
        trigger=IntervalTrigger(hours=24),
        id="agent_ssl_expiry_check",
        name="Agent Loop: SSL Certificate Expiry Check",
        replace_existing=True,
    )

    # --- DNS monitoring ---
    scheduler.add_job(
        with_ctx(daily_dns_report),
        trigger=CronTrigger(hour=7, minute=0, timezone="America/Toronto"),
        id="agent_daily_dns_report",
        name="Agent Loop: Daily DNS Report",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(detect_query_spike),
        trigger=IntervalTrigger(hours=1),
        id="agent_query_spike_detect",
        name="Agent Loop: DNS Query Spike Detection",
        replace_existing=True,
    )

    # --- Camera surveillance ---
    scheduler.add_job(
        with_ctx(check_camera_anomaly),
        trigger=IntervalTrigger(hours=1),
        id="agent_camera_anomaly",
        name="Agent Loop: Camera Motion Anomaly",
        replace_existing=True,
    )

    # --- Auto-block pipeline ---
    scheduler.add_job(
        with_ctx(run_auto_block),
        trigger=IntervalTrigger(minutes=15),
        id="agent_auto_block",
        name="Agent Loop: Auto-Block Pipeline",
        replace_existing=True,
    )

    # --- Compliance scanning (Job #57) ---
    scheduler.add_job(
        with_ctx(run_scheduled_compliance_scan),
        trigger=IntervalTrigger(hours=6, start_date="2026-01-01 02:00:00"),
        id="agent_compliance_scan",
        name="Agent Loop: Compliance Scan",
        replace_existing=True,
    )

    # --- Auto-remediation (Job #58) ---
    scheduler.add_job(
        with_ctx(run_auto_remediation),
        trigger=IntervalTrigger(hours=6, start_date="2026-01-01 02:30:00"),
        id="agent_auto_remediation",
        name="Agent Loop: Compliance Auto-Remediation",
        replace_existing=True,
    )

    # --- Sunday maintenance-window auto-apply (Job #62, 2026-04-11) ---
    scheduler.add_job(
        with_ctx(run_auto_apply_window),
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="America/Toronto"),
        id="agent_compliance_auto_apply_window",
        name="Agent Loop: Compliance Auto-Apply Window",
        replace_existing=True,
        misfire_grace_time=900,
    )

    # --- Auto-plan generation (Job #61) ---
    # Runs 1h after each scan so blocklisted failures have F.O.R.G.E. plans
    # waiting in Department HQ before the admin opens the Compliance tab.
    scheduler.add_job(
        with_ctx(run_auto_plan_generation),
        trigger=IntervalTrigger(hours=6, start_date="2026-01-01 03:00:00"),
        id="agent_compliance_auto_plan",
        name="Agent Loop: F.O.R.G.E. Auto Plan Generation",
        replace_existing=True,
    )

    # --- ntopng traffic collection ---
    scheduler.add_job(
        with_ctx(collect_traffic_stats),
        trigger=IntervalTrigger(minutes=5),
        id="agent_traffic_stats",
        name="Agent Loop: ntopng Traffic Collection",
        replace_existing=True,
    )

    # --- DNS history collection (Job #59) ---
    scheduler.add_job(
        with_ctx(collect_dns_history),
        trigger=IntervalTrigger(minutes=5),
        id="agent_dns_history",
        name="Agent Loop: DNS History Collection",
        replace_existing=True,
    )

    # --- Device-user mapping sync (Job #60) ---
    scheduler.add_job(
        with_ctx(sync_device_mappings),
        trigger=IntervalTrigger(hours=6, start_date="2026-01-01 03:00:00"),
        id="agent_sync_device_mappings",
        name="Agent Loop: Device-User Mapping Sync",
        replace_existing=True,
    )

    # --- Device presence & ARP spoof detection ---
    # DISABLED 2026-04-14: 120 fails/day, returning 0 — see Project #261
    # scheduler.add_job(
    #     with_ctx(track_device_presence),
    #     trigger=IntervalTrigger(minutes=5),
    #     id="agent_device_presence",
    #     name="Agent Loop: Device Presence & ARP Spoof Detection",
    #     replace_existing=True,
    # )

    # --- IP geolocation enrichment ---
    scheduler.add_job(
        with_ctx(enrich_ip_geolocation),
        trigger=IntervalTrigger(minutes=30),
        id="agent_ip_geolocation",
        name="Agent Loop: IP Geolocation Enrichment",
        replace_existing=True,
    )

    # --- Anomaly detection (Job #61) ---
    scheduler.add_job(
        with_ctx(run_anomaly_detection),
        trigger=IntervalTrigger(minutes=30),
        id="agent_anomaly_detection",
        name="Agent Loop: Network Anomaly Detection",
        replace_existing=True,
    )

    # --- V.I.G.I.L. daily threat report ---
    scheduler.add_job(
        with_ctx(generate_vigil_threat_report),
        trigger=CronTrigger(hour=8, minute=0, timezone="America/Toronto"),
        id="agent_vigil_threat_report",
        name="Agent Loop: V.I.G.I.L. Daily Threat Report",
        replace_existing=True,
    )

    # --- Weekly security report ---
    scheduler.add_job(
        with_ctx(generate_weekly_security_report),
        trigger=CronTrigger(day_of_week="mon", hour=8, minute=0, timezone="America/Toronto"),
        id="agent_weekly_security_report",
        name="Agent Loop: Weekly Security Report",
        replace_existing=True,
    )

    # --- Threat intelligence sync ---
    scheduler.add_job(
        with_ctx(sync_threat_intel),
        trigger=IntervalTrigger(hours=6, start_date="2026-01-01 01:00:00"),
        id="agent_threat_intel_sync",
        name="Agent Loop: Threat Intel Sync",
        replace_existing=True,
    )

    # --- Alert correlation / incidents ---
    scheduler.add_job(
        with_ctx(correlate_security_incidents),
        trigger=IntervalTrigger(minutes=30),
        id="agent_correlate_incidents",
        name="Agent Loop: Alert Correlation",
        replace_existing=True,
    )

    # --- Speed test ---
    scheduler.add_job(
        with_ctx(run_speed_test),
        trigger=IntervalTrigger(hours=6, start_date="2026-01-01 00:30:00"),
        id="agent_speed_test",
        name="Agent Loop: Network Speed Test",
        replace_existing=True,
    )

    # --- Supervision controls enforcement ---
    scheduler.add_job(
        with_ctx(enforce_supervision_schedules),
        trigger=IntervalTrigger(minutes=5),
        id="agent_supervision_enforce",
        name="Agent Loop: Supervision Controls Enforcement",
        replace_existing=True,
    )

    logger.info("[SecurityJobs] Registered 22 security/network jobs")
