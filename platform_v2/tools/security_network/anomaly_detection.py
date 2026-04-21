"""
anomaly_detection.py — Network behavior anomaly detection.

Analyzes traffic patterns for suspicious activity:
  - Bandwidth spikes (current hour vs 7-day average)
  - Data exfiltration (upload >> download)
  - Odd-hours activity (midnight-5AM DNS queries)
  - DNS tunneling (long domains, high query rate, unique subdomains)
"""

import logging
import time
from datetime import datetime, timedelta

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------

BANDWIDTH_SPIKE_MULTIPLIER = 5.0  # alert if current > N x 7-day average
BANDWIDTH_MIN_BYTES = 10_000_000  # ignore devices with < 10 MB average

EXFIL_UPLOAD_RATIO = 1.5  # upload must exceed download by this factor
EXFIL_MIN_UPLOAD_BYTES = 100_000_000  # at least 100 MB upload

ODD_HOURS_START = 0  # midnight
ODD_HOURS_END = 4  # up to 04:59 (EXTRACT HOUR BETWEEN 0 AND 4)
ODD_HOURS_MIN_QUERIES = 50

DNS_TUNNEL_LONG_DOMAIN_LEN = 80  # raised from 50 — CDNs/SRV records are 50-70 chars
DNS_TUNNEL_HIGH_QUERY_RATE = 200  # queries/hour to one base domain (raised from 100)
DNS_TUNNEL_UNIQUE_SUBDOMAINS = 50  # distinct subdomains under one parent (raised from 20)

# Hub IP excluded from bandwidth spike alerts (it's a server)
HUB_IP = "192.168.1.200"

# Known legitimate domains with long names or many subdomains — NOT tunneling
DNS_TUNNEL_WHITELIST = {
    "epicgames.com",
    "googleapis.com",
    "google.com",
    "apple.com",
    "microsoft.com",
    "facebook.com",
    "fbcdn.net",
    "akamai.net",
    "akadns.net",
    "aaplimg.com",
    "tiktokcdn.com",
    "gvt2.com",
    "googlevideo.com",
    "roblox.com",
    "amazonaws.com",
    "cloudflare.com",
    "cae.com",
    "cae.ca",  # work VPN
    "a2z.com",  # Amazon devices (Alexa/Ring)
    "icloud.com",
    "mzstatic.com",  # Apple services
    "xbox.com",
    "xboxlive.com",  # Gaming
    "twitch.tv",
    "steampowered.com",
    "snapchat.com",
    "snap.com",
    "spotify.com",
    "scdn.co",
    "netflix.com",
    "nflxvideo.net",
    "tiktokv.com",
    "bytedance.com",
    "adobe.com",
    "adobelogin.com",
}


# ---------------------------------------------------------------------------
# Detection functions
# ---------------------------------------------------------------------------


def detect_bandwidth_spikes():
    """Compare each device's current-hour bandwidth against its 7-day hourly average.

    Returns list of dicts: {"device_ip", "current", "average", "ratio"}
    for devices where current > BANDWIDTH_SPIKE_MULTIPLIER x average.
    """
    findings = []
    try:
        with get_db_cursor() as (conn, cur):
            # Current hour bandwidth per device
            cur.execute(
                """
                SELECT device_ip, SUM(bytes_in + bytes_out) AS current_bytes
                FROM network_traffic_stats
                WHERE hour_bucket >= date_trunc('hour', NOW())
                GROUP BY device_ip
                """
            )
            current_map = {row["device_ip"]: int(row["current_bytes"]) for row in cur.fetchall()}

            if not current_map:
                return findings

            # 7-day hourly average per device (excluding current hour)
            cur.execute(
                """
                SELECT device_ip, AVG(hourly_total) AS avg_bytes
                FROM (
                    SELECT device_ip, hour_bucket,
                           SUM(bytes_in + bytes_out) AS hourly_total
                    FROM network_traffic_stats
                    WHERE hour_bucket >= NOW() - INTERVAL '7 days'
                      AND hour_bucket < date_trunc('hour', NOW())
                    GROUP BY device_ip, hour_bucket
                ) sub
                GROUP BY device_ip
                """
            )
            avg_map = {row["device_ip"]: float(row["avg_bytes"]) for row in cur.fetchall()}

            for ip, current in current_map.items():
                # Skip the hub — it's a server with high traffic
                if ip == HUB_IP:
                    continue

                avg = avg_map.get(ip, 0)
                if avg < BANDWIDTH_MIN_BYTES:
                    continue

                ratio = current / avg if avg > 0 else 0
                if ratio >= BANDWIDTH_SPIKE_MULTIPLIER:
                    findings.append(
                        {
                            "device_ip": ip,
                            "current": current,
                            "average": round(avg),
                            "ratio": round(ratio, 1),
                        }
                    )

    except Exception as e:
        logger.error("[AnomalyDetection] detect_bandwidth_spikes failed: %s", e)

    return findings


def detect_exfiltration():
    """Flag devices where upload significantly exceeds download over 24 hours.

    Returns list of dicts: {"device_ip", "upload", "download", "ratio"}
    """
    findings = []
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT device_ip,
                       SUM(bytes_out) AS upload,
                       SUM(bytes_in)  AS download
                FROM network_traffic_stats
                WHERE hour_bucket >= NOW() - INTERVAL '24 hours'
                GROUP BY device_ip
                HAVING SUM(bytes_out) > SUM(bytes_in) * %s
                   AND SUM(bytes_out) > %s
                """,
                (EXFIL_UPLOAD_RATIO, EXFIL_MIN_UPLOAD_BYTES),
            )
            for row in cur.fetchall():
                upload = int(row["upload"])
                download = int(row["download"])
                ratio = upload / download if download > 0 else float("inf")
                findings.append(
                    {
                        "device_ip": row["device_ip"],
                        "upload": upload,
                        "download": download,
                        "ratio": round(ratio, 1),
                    }
                )

    except Exception as e:
        logger.error("[AnomalyDetection] detect_exfiltration failed: %s", e)

    return findings


def detect_odd_hours_activity():
    """Flag devices with significant DNS activity between midnight and 5 AM.

    Returns list of dicts: {"device_ip", "queries"}
    """
    findings = []
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT device_ip, SUM(query_count) AS queries
                FROM device_dns_history
                WHERE hour_bucket >= NOW() - INTERVAL '24 hours'
                  AND EXTRACT(HOUR FROM hour_bucket) BETWEEN %s AND %s
                GROUP BY device_ip
                HAVING SUM(query_count) > %s
                """,
                (ODD_HOURS_START, ODD_HOURS_END, ODD_HOURS_MIN_QUERIES),
            )
            for row in cur.fetchall():
                findings.append(
                    {
                        "device_ip": row["device_ip"],
                        "queries": int(row["queries"]),
                    }
                )

    except Exception as e:
        logger.error("[AnomalyDetection] detect_odd_hours_activity failed: %s", e)

    return findings


def detect_dns_tunneling():
    """Look for signs of DNS tunneling:
    1. Domains with unusually long names (data encoded in subdomain)
    2. High query rate to a single base domain
    3. High ratio of unique subdomains under one parent domain

    Returns list of dicts with "type" key indicating which check triggered.
    """
    findings = []
    try:
        with get_db_cursor() as (conn, cur):
            # 1. Long domain names (potential encoded data)
            cur.execute(
                """
                SELECT device_ip, domain, query_count
                FROM device_dns_history
                WHERE hour_bucket >= NOW() - INTERVAL '24 hours'
                  AND LENGTH(domain) > %s
                """,
                (DNS_TUNNEL_LONG_DOMAIN_LEN,),
            )
            for row in cur.fetchall():
                domain = row["domain"]
                # Skip whitelisted base domains
                base = ".".join(domain.rsplit(".", 2)[-2:]) if "." in domain else domain
                if base in DNS_TUNNEL_WHITELIST:
                    continue
                # Skip SRV/service records anywhere in the name (_ldap, _kerberos, _tcp, etc.)
                if "_" in domain.split(".")[0] or "._tcp." in domain or "._udp." in domain:
                    continue
                # Skip reverse DNS lookups (ip6.arpa, in-addr.arpa)
                if domain.endswith(".arpa"):
                    continue
                # Skip S3/CDN bucket-style subdomains (contain hyphens + region pattern)
                if ".s3" in domain and base in ("amazonaws.com",):
                    continue
                findings.append(
                    {
                        "type": "long_domain",
                        "device_ip": row["device_ip"],
                        "domain": domain,
                        "query_count": int(row["query_count"]),
                        "domain_length": len(domain),
                    }
                )

            # 2. High query rate / many unique subdomains to one base domain
            cur.execute(
                """
                SELECT device_ip,
                       SUBSTRING(domain FROM '([^.]+\\.[^.]+)$') AS base_domain,
                       SUM(query_count) AS total_queries,
                       COUNT(DISTINCT domain) AS unique_subdomains
                FROM device_dns_history
                WHERE hour_bucket >= NOW() - INTERVAL '1 hour'
                GROUP BY device_ip, SUBSTRING(domain FROM '([^.]+\\.[^.]+)$')
                HAVING SUM(query_count) > %s
                    OR COUNT(DISTINCT domain) > %s
                """,
                (DNS_TUNNEL_HIGH_QUERY_RATE, DNS_TUNNEL_UNIQUE_SUBDOMAINS),
            )
            for row in cur.fetchall():
                base = row["base_domain"] or "unknown"
                if base in DNS_TUNNEL_WHITELIST:
                    continue
                findings.append(
                    {
                        "type": "high_rate_or_unique_subdomains",
                        "device_ip": row["device_ip"],
                        "base_domain": base,
                        "total_queries": int(row["total_queries"]),
                        "unique_subdomains": int(row["unique_subdomains"]),
                    }
                )

    except Exception as e:
        logger.error("[AnomalyDetection] detect_dns_tunneling failed: %s", e)

    return findings


# ---------------------------------------------------------------------------
# Master function
# ---------------------------------------------------------------------------


def _get_trusted_ips() -> set:
    """Return IP addresses classified as trusted zone in network_devices.

    Trusted devices (Kytran's phone, admin laptop, etc.) generate behavior
    that would otherwise trip the detectors — long TLS SNI names, photo
    backups that look like exfiltration, overnight sync traffic, per-app
    subdomain queries. Exempting them stops the flood without disabling
    the detector for unknown/quarantined devices where it matters.
    """
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT host(ip_address) AS ip FROM network_devices WHERE security_zone = 'trusted'")
            return {row["ip"] for row in cur.fetchall()}
    except Exception as e:
        logger.error("[AnomalyDetection] trusted-IP lookup failed: %s", e)
        return set()


def _filter_trusted(findings: list, trusted: set) -> tuple:
    """Split findings into (kept, suppressed) based on trusted IP set."""
    kept = [f for f in findings if f.get("device_ip") not in trusted]
    suppressed = [f for f in findings if f.get("device_ip") in trusted]
    return kept, suppressed


def _format_bytes(b):
    """Human-readable byte string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def run_all_anomaly_checks():
    """Run all anomaly detectors and create security alerts for findings.

    Uses **digest mode**: all individual findings are saved to the DB for
    full dashboard visibility, but Telegram receives ONE batched summary
    message per run instead of one message per finding.

    Exfiltration findings are the exception — they always fire an immediate
    Telegram alert because they may indicate active data theft.

    Returns dict with counts per check type.
    """
    from .security_alerts import create_security_alert, create_security_digest

    all_findings = {
        "bandwidth_spikes": [],
        "exfiltration": [],
        "odd_hours": [],
        "dns_tunneling": [],
    }

    # Collect digest lines (batched into one Telegram message at the end)
    digest_lines = []

    # Trusted-zone devices are exempt from the four anomaly detectors —
    # their normal behavior generates false positives (photo-backup
    # uploads look like exfil, per-app subdomains look like tunneling,
    # phone sync at 3 AM looks like odd-hours activity). Unknown /
    # quarantined devices still get flagged as before.
    trusted_ips = _get_trusted_ips()
    suppressed_total = 0

    # 1. Bandwidth spikes — dashboard + digest
    spikes_raw = detect_bandwidth_spikes()
    spikes, suppressed = _filter_trusted(spikes_raw, trusted_ips)
    suppressed_total += len(suppressed)
    for s in spikes:
        create_security_alert(
            "intrusion",
            f"Bandwidth spike: {s['device_ip']}",
            f"Current: {_format_bytes(s['current'])}, "
            f"Avg: {_format_bytes(s['average'])}, "
            f"Ratio: {s['ratio']}x (threshold: {BANDWIDTH_SPIKE_MULTIPLIER}x)",
            priority="high",
            telegram=False,  # goes into digest instead
        )
        digest_lines.append({"line": f"Bandwidth spike: {s['device_ip']} ({s['ratio']}x avg)"})
    all_findings["bandwidth_spikes"] = spikes

    # 2. Data exfiltration — IMMEDIATE Telegram (active threat)
    exfil_raw = detect_exfiltration()
    exfil, suppressed = _filter_trusted(exfil_raw, trusted_ips)
    suppressed_total += len(suppressed)
    for e in exfil:
        create_security_alert(
            "intrusion",
            f"Possible exfiltration: {e['device_ip']}",
            f"Upload: {_format_bytes(e['upload'])}, "
            f"Download: {_format_bytes(e['download'])}, "
            f"Ratio: {e['ratio']}x",
            priority="high",
            telegram=True,
        )
    all_findings["exfiltration"] = exfil

    # 3. Odd-hours activity — dashboard + digest
    odd_raw = detect_odd_hours_activity()
    odd, suppressed = _filter_trusted(odd_raw, trusted_ips)
    suppressed_total += len(suppressed)
    for o in odd:
        create_security_alert(
            "intrusion",
            f"Odd-hours DNS activity: {o['device_ip']}",
            f"{o['queries']} DNS queries between {ODD_HOURS_START}:00-{ODD_HOURS_END + 1}:00",
            priority="normal",
            telegram=False,
        )
        digest_lines.append({"line": f"Odd-hours DNS: {o['device_ip']} ({o['queries']} queries)"})
    all_findings["odd_hours"] = odd

    # 4. DNS tunneling — dashboard + digest
    tunneling_raw = detect_dns_tunneling()
    tunneling, suppressed = _filter_trusted(tunneling_raw, trusted_ips)
    suppressed_total += len(suppressed)
    for t in tunneling:
        if t["type"] == "long_domain":
            detail = f"Long domain ({t['domain_length']} chars): {t['domain'][:60]}"
            create_security_alert(
                "intrusion",
                f"DNS tunneling suspect: {t['device_ip']}",
                detail,
                priority="high",
                telegram=False,
            )
            digest_lines.append({"line": f"DNS tunnel (long): {t['device_ip']} — {t['domain'][:40]}…"})
        else:
            detail = (
                f"Base domain: {t['base_domain']}, "
                f"Queries: {t['total_queries']}, "
                f"Unique subdomains: {t['unique_subdomains']}"
            )
            create_security_alert(
                "intrusion",
                f"DNS tunneling suspect: {t['device_ip']}",
                detail,
                priority="high",
                telegram=False,
            )
            digest_lines.append(
                {"line": f"DNS tunnel: {t['device_ip']} → {t['base_domain']} " f"({t['unique_subdomains']} subdomains)"}
            )
    all_findings["dns_tunneling"] = tunneling

    total = sum(len(v) for v in all_findings.values())

    # --- Send ONE digest to Telegram (if there are non-exfil findings) ---
    if digest_lines:
        create_security_digest(
            "intrusion",
            "Anomaly Digest",
            digest_lines,
            priority="high",
            telegram=True,
        )

    if total > 0:
        logger.warning(
            "[AnomalyDetection] %d findings: %d spikes, %d exfil, %d odd-hours, %d tunneling "
            "(%d suppressed from trusted zone)",
            total,
            len(spikes),
            len(exfil),
            len(odd),
            len(tunneling),
            suppressed_total,
        )
    elif suppressed_total > 0:
        logger.info(
            "[AnomalyDetection] All clear (%d findings suppressed from trusted zone)",
            suppressed_total,
        )
    else:
        logger.info("[AnomalyDetection] All clear -- no anomalies detected")

    return all_findings
