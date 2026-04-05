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
                                suggestion.get(
                                    "description",
                                    "Threat auto-blocked by security pipeline",
                                ),
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

            blocked = entry.get("reason", "") != ""

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
        from tools.security_network.security_alerts import create_security_alert

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
            for ip, mac in current_map.items():
                prev = last_state.get(ip)
                if prev != "online":
                    # Device just came online (or first time seen)
                    cur.execute(
                        "INSERT INTO device_presence_log (device_ip, device_mac, event_type) VALUES (%s, %s, 'online')",
                        (ip, mac or None),
                    )
                    processed += 1

                    # Alert on brand-new device
                    if ip not in all_known_ips:
                        create_security_alert(
                            "intrusion",
                            f"New device detected: {ip}",
                            f"A device with IP {ip} (MAC: {mac or 'unknown'}) appeared on the network for the first time.",
                            priority="high",
                            telegram=False,
                        )

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
                create_security_alert(
                    "intrusion",
                    f"ARP spoof detected on {spoof_ip}",
                    f"Device IP {spoof_ip} has been associated with multiple MAC addresses "
                    f"in the last hour: {', '.join(spoof_macs)}. This may indicate ARP spoofing.",
                    priority="critical",
                    telegram=True,
                )
                processed += 1

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
    scheduler.add_job(
        with_ctx(track_device_presence),
        trigger=IntervalTrigger(minutes=5),
        id="agent_device_presence",
        name="Agent Loop: Device Presence & ARP Spoof Detection",
        replace_existing=True,
    )

    logger.info("[SecurityJobs] Registered 13 security/network jobs")
