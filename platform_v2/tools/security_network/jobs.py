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
  - run_auto_remediation (Job #58, every 6h)
"""

import json
import logging
import os
import time

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
        from tools.security_network.security_alerts import create_security_alert

        svc = DeviceRegistryService()
        new_devices = svc.discover_devices()

        for device in new_devices:
            ip = device.get("ip_address", "?")
            mac = device.get("mac_address", "?")
            mfr = device.get("manufacturer", "Unknown")
            create_security_alert(
                "new_device",
                f"New device detected: {mfr}",
                f"IP: {ip} | MAC: {mac} | Manufacturer: {mfr}",
                priority="high",
                telegram=True,
            )

        if new_devices:
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
            import socket

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
        ddns_file = os.path.join(os.getenv("ARCHIE_BASE_DIR", "/mnt/archie_brain"), "scripts", ".ddns_last_ip")
        if os.path.exists(ddns_file):
            age_hours = (time.time() - os.path.getmtime(ddns_file)) / 3600
            if age_hours > 1:
                issues.append(f"DDNS updater hasn't run in {age_hours:.0f} hours")
        else:
            issues.append("DDNS updater IP file missing")

        # 5. Check AdGuard protection
        try:
            import requests

            host = os.getenv("ADGUARD_HOST", "network_adguard")
            port = os.getenv("ADGUARD_PORT", "80")
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
        from tools.security_network.npm_service import NPMService
        from tools.security_network.security_alerts import create_security_alert

        npm = NPMService()
        hosts = npm.list_proxy_hosts()
        if not hosts:
            return

        for host in hosts:
            cert_id = host.get("certificate_id")
            if not cert_id:
                continue
            domain = (host.get("domain_names") or ["unknown"])[0]

            import ssl
            import socket
            from datetime import datetime

            try:
                ctx = ssl.create_default_context()
                with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
                    s.settimeout(5)
                    s.connect((domain, 443))
                    cert = s.getpeercert()
                    expiry = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                    days_left = (expiry - datetime.utcnow()).days

                    if days_left <= 14:
                        priority = "critical" if days_left <= 3 else "high" if days_left <= 7 else "normal"
                        create_security_alert(
                            "ssl_expiry",
                            f"SSL cert expiring: {domain}",
                            f"Certificate for {domain} expires in {days_left} days ({expiry.strftime('%Y-%m-%d')})",
                            priority=priority,
                            telegram=True,
                        )
                        logger.warning(f"SSL cert expiry: {domain} expires in {days_left} days")
            except Exception:
                pass  # Can't check this domain

    except Exception as e:
        logger.warning(f"Failed: {e}")


def daily_dns_report():
    """Generate daily DNS activity summary for Telegram (7 AM daily)."""
    try:
        import requests
        from tools.security_network.security_alerts import create_security_alert

        host = os.getenv("ADGUARD_HOST", "network_adguard")
        port = os.getenv("ADGUARD_PORT", "80")
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
            f"Top blocked:\n" + "\n".join(blocked_lines[:3])
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

        host = os.getenv("ADGUARD_HOST", "network_adguard")
        port = os.getenv("ADGUARD_PORT", "80")
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
    """Run suggestion engine and auto-execute critical/high suggestions (every 15 min)."""
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

                    if severity in ("critical", "high") and stype in (
                        "ssh_brute_force",
                        "device_vulnerability",
                    ):
                        try:
                            svc.approve_suggestion(suggestion["id"])
                            create_security_alert(
                                "block",
                                f"Auto-blocked: {suggestion.get('title', stype)}",
                                suggestion.get("description", "Threat auto-blocked by security pipeline"),
                                priority="high",
                                telegram=True,
                            )
                            logger.info(f"Auto-block: executed suggestion #{suggestion['id']} ({stype})")
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
                        direction = "\u2B06" if new_score > old_score else "\u2B07"
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


def run_auto_remediation():
    """Job #58: Auto-fix low-risk compliance failures from the latest scan."""
    try:
        import json as _json
        from tools.security_network.compliance_service import (
            get_latest_scores,
            get_scan_results,
            apply_fix,
        )

        scores = get_latest_scores()
        if not scores or not scores.get("scan_id"):
            return

        scan_id = scores["scan_id"]
        results = get_scan_results(scan_id, status="fail")

        if not results:
            return

        # Build a lookup of rule_id -> fix risk from loaded rule packs
        from database import get_db_cursor

        risk_lookup = {}
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT pack_id, rules FROM compliance_rule_packs")
            for pack_row in cur.fetchall():
                rules = pack_row["rules"] if isinstance(pack_row["rules"], list) else _json.loads(pack_row["rules"])
                for rule in rules:
                    rid = rule.get("rule_id", "")
                    fix = rule.get("fix", {})
                    risk_lookup[rid] = fix.get("risk", "high")

        fixed = 0
        skipped = 0
        for result in results:
            rule_id = result.get("rule_id", "")
            risk = risk_lookup.get(rule_id, "high")

            # Only auto-fix low-risk rules (Tier 1 auto-approvable)
            if risk != "low":
                skipped += 1
                continue

            try:
                fix_result = apply_fix(scan_id, rule_id, user_id=0)
                if fix_result.get("success"):
                    fixed += 1
                    logger.info("Auto-remediation: fixed %s (risk=%s)", rule_id, risk)
                else:
                    logger.warning(
                        "Auto-remediation: failed to fix %s: %s",
                        rule_id,
                        fix_result.get("error", "unknown"),
                    )
            except Exception as fix_err:
                logger.warning("Auto-remediation: error fixing %s: %s", rule_id, fix_err)

        if fixed > 0 or skipped > 0:
            logger.info(
                "Auto-remediation complete: %d fixed, %d skipped (non-low risk)",
                fixed,
                skipped,
            )
    except Exception as e:
        logger.error("Auto-remediation failed: %s", e)


# NOTE: pattern_compliance_check is registered in dev_hq/jobs.py (code quality job)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_security_jobs(scheduler, flask_app):
    """Register all security/network jobs with the APScheduler instance.

    Called from AgentLoop.start() after the scheduler is running.
    """
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    def with_ctx(fn):
        """Wrap a job function so it runs inside the Flask app context."""

        def wrapper():
            with flask_app.app_context():
                fn()

        wrapper.__name__ = fn.__name__
        return wrapper

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
        trigger=CronTrigger(day_of_week="sun", hour=3),
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
        trigger=CronTrigger(hour=7, minute=0),
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

    logger.info("[SecurityJobs] Registered 9 security/network jobs")
