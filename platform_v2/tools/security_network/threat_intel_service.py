"""
Threat Intelligence Service
===========================
Syncs IOC feeds (abuse.ch URLhaus, Feodo Tracker, SSL Blacklist),
cross-references against local DNS/traffic data, and tracks hits.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
from database import get_db_cursor

logger = logging.getLogger(__name__)

FEEDS = {
    # urlhaus disabled — requires API key since 2026
    # "urlhaus": {
    #     "url": "https://urlhaus-api.abuse.ch/v1/urls/recent/",
    #     "method": "POST",
    #     "ioc_type": "domain",
    # },
    "feodo_tracker": {
        "url": "https://feodotracker.abuse.ch/downloads/ipblocklist_recommended.txt",
        "method": "GET",
        "ioc_type": "ip",
    },
    "ssl_blacklist": {
        "url": "https://sslbl.abuse.ch/blacklist/sslipblacklist.txt",
        "method": "GET",
        "ioc_type": "ip",
    },
    "blocklist_de": {
        "url": "https://lists.blocklist.de/lists/all.txt",
        "method": "GET",
        "ioc_type": "ip",
    },
    "cinsscore": {
        "url": "https://cinsscore.com/list/ci-badguys.txt",
        "method": "GET",
        "ioc_type": "ip",
    },
}

# Map URLhaus threat types to severity levels
URLHAUS_SEVERITY_MAP = {
    "malware_download": "critical",
    "crypto_mining": "high",
    "phishing": "high",
    "exploit": "critical",
}


class ThreatIntelService:
    """Manages threat intelligence feed synchronisation and hit detection."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync_feeds(self) -> Dict[str, Any]:
        """Pull IOCs from all configured feeds and upsert into DB.

        Returns a dict with per-feed counts and a total.
        """
        results: Dict[str, Any] = {}
        total_new = 0
        total_updated = 0

        for feed_name, feed_cfg in FEEDS.items():
            try:
                iocs = self._fetch_feed(feed_name, feed_cfg)
                new, updated = self._upsert_iocs(iocs, feed_name)
                results[feed_name] = {"new": new, "updated": updated, "error": None}
                total_new += new
                total_updated += updated
                logger.info("Feed %s: %d new, %d updated IOCs", feed_name, new, updated)
            except Exception as exc:
                logger.warning("Feed %s sync failed: %s", feed_name, exc)
                results[feed_name] = {"new": 0, "updated": 0, "error": str(exc)}

        return {"feeds": results, "total_new": total_new, "total_updated": total_updated}

    def check_hits(self) -> List[Dict[str, Any]]:
        """Cross-reference IOCs against local DNS and traffic data (last 24h).

        Returns list of newly created hit records.
        """
        new_hits: List[Dict[str, Any]] = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        new_hits.extend(self._check_domain_hits(cutoff))
        new_hits.extend(self._check_ip_hits(cutoff))

        return new_hits

    def get_feed_status(self) -> Dict[str, Any]:
        """Return per-feed statistics (count, last_updated)."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT feed_name,
                       COUNT(*) AS ioc_count,
                       MAX(last_updated) AS last_updated
                FROM threat_intel_iocs
                GROUP BY feed_name
                """
            )
            rows = cur.fetchall()

        status: Dict[str, Any] = {}
        for row in rows:
            status[row["feed_name"]] = {
                "count": row["ioc_count"],
                "last_updated": row["last_updated"].isoformat() if row["last_updated"] else None,
            }
        return status

    def get_recent_hits(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent hits joined with IOC details."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT h.id, h.ioc_id, h.device_ip, h.domain,
                       h.detected_at,
                       i.ioc_type, i.ioc_value, i.severity, i.feed_name,
                       i.description
                FROM threat_intel_hits h
                JOIN threat_intel_iocs i ON i.id = h.ioc_id
                ORDER BY h.detected_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

        return [
            {
                "id": r["id"],
                "ioc_id": r["ioc_id"],
                "device_ip": r["device_ip"],
                "domain": r["domain"],
                "detected_at": r["detected_at"].isoformat() if r["detected_at"] else None,
                "ioc_type": r["ioc_type"],
                "ioc_value": r["ioc_value"],
                "severity": r["severity"],
                "feed_name": r["feed_name"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Feed fetching
    # ------------------------------------------------------------------

    def _fetch_feed(self, feed_name: str, feed_cfg: Dict[str, str]) -> List[Dict[str, str]]:
        """Fetch and parse a single feed into a list of IOC dicts."""
        if feed_name == "urlhaus":
            return self._parse_urlhaus(feed_cfg["url"])
        else:
            return self._parse_ip_list(feed_cfg["url"], feed_name)

    def _parse_urlhaus(self, url: str) -> List[Dict[str, str]]:
        """Parse URLhaus recent URLs JSON response into domain IOCs."""
        resp = requests.post(url, data={"limit": 1000}, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        seen_domains: set = set()
        iocs: List[Dict[str, str]] = []

        for entry in data.get("urls", []):
            raw_url = entry.get("url", "")
            threat = entry.get("threat", "")
            try:
                parsed = urlparse(raw_url)
                domain = parsed.hostname
            except Exception:
                continue

            if not domain or domain in seen_domains:
                continue
            seen_domains.add(domain)

            severity = URLHAUS_SEVERITY_MAP.get(threat, "medium")
            iocs.append(
                {
                    "ioc_type": "domain",
                    "ioc_value": domain,
                    "severity": severity,
                    "description": threat or "unknown",
                }
            )

        return iocs

    def _parse_ip_list(self, url: str, feed_name: str) -> List[Dict[str, str]]:
        """Parse a plain-text IP blocklist (one IP per line, # comments)."""
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()

        iocs: List[Dict[str, str]] = []
        for line in resp.text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Some lists have IP:port — take only the IP
            ip = line.split(":")[0].strip()
            if not ip:
                continue
            iocs.append(
                {
                    "ioc_type": "ip",
                    "ioc_value": ip,
                    "severity": "high",
                    "description": feed_name,
                }
            )

        return iocs

    # ------------------------------------------------------------------
    # DB upsert
    # ------------------------------------------------------------------

    def _upsert_iocs(self, iocs: List[Dict[str, str]], feed_name: str) -> tuple:
        """Upsert IOCs into threat_intel_iocs. Returns (new_count, updated_count)."""
        if not iocs:
            return 0, 0

        new_count = 0
        updated_count = 0
        now = datetime.now(timezone.utc)

        with get_db_cursor(commit=True) as (conn, cur):
            for ioc in iocs:
                cur.execute(
                    """
                    INSERT INTO threat_intel_iocs
                        (feed_name, ioc_type, ioc_value, severity, description,
                         first_seen, last_updated)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (feed_name, ioc_type, ioc_value) DO UPDATE
                        SET severity = EXCLUDED.severity,
                            description = EXCLUDED.description,
                            last_updated = EXCLUDED.last_updated
                    RETURNING (xmax = 0) AS is_new
                    """,
                    (
                        feed_name,
                        ioc["ioc_type"],
                        ioc["ioc_value"],
                        ioc["severity"],
                        ioc.get("description", ""),
                        now,
                        now,
                    ),
                )
                row = cur.fetchone()
                if row and row["is_new"]:
                    new_count += 1
                else:
                    updated_count += 1

        return new_count, updated_count

    # ------------------------------------------------------------------
    # Hit detection
    # ------------------------------------------------------------------

    def _check_domain_hits(self, cutoff: datetime) -> List[Dict[str, Any]]:
        """Check domain IOCs against device_dns_history."""
        hits: List[Dict[str, Any]] = []

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                SELECT DISTINCT d.device_ip, d.domain, i.id AS ioc_id,
                       i.ioc_value, i.severity, i.feed_name
                FROM device_dns_history d
                JOIN threat_intel_iocs i
                    ON i.ioc_type = 'domain'
                    AND (d.domain = i.ioc_value
                         OR d.domain LIKE '%%.' || i.ioc_value)
                WHERE d.hour_bucket >= %s
                  AND NOT EXISTS (
                      SELECT 1 FROM threat_intel_hits h
                      WHERE h.ioc_id = i.id
                        AND h.device_ip = d.device_ip
                        AND h.domain = d.domain
                  )
                """,
                (cutoff,),
            )
            rows = cur.fetchall()

            now = datetime.now(timezone.utc)
            for r in rows:
                cur.execute(
                    """
                    INSERT INTO threat_intel_hits
                        (ioc_id, device_ip, domain, detected_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (r["ioc_id"], r["device_ip"], r["domain"], now),
                )
                hit_row = cur.fetchone()
                hits.append(
                    {
                        "id": hit_row["id"],
                        "ioc_id": r["ioc_id"],
                        "device_ip": r["device_ip"],
                        "domain": r["domain"],
                        "severity": r["severity"],
                        "feed_name": r["feed_name"],
                    }
                )

        return hits

    def _check_ip_hits(self, cutoff: datetime) -> List[Dict[str, Any]]:
        """Check IP IOCs against network_traffic_stats."""
        hits: List[Dict[str, Any]] = []

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                SELECT DISTINCT t.device_ip, i.id AS ioc_id,
                       i.ioc_value, i.severity, i.feed_name
                FROM network_traffic_stats t
                JOIN threat_intel_iocs i
                    ON i.ioc_type = 'ip'
                    AND t.device_ip = i.ioc_value
                WHERE t.hour_bucket >= %s
                  AND NOT EXISTS (
                      SELECT 1 FROM threat_intel_hits h
                      WHERE h.ioc_id = i.id
                        AND h.device_ip = t.device_ip
                  )
                """,
                (cutoff,),
            )
            rows = cur.fetchall()

            now = datetime.now(timezone.utc)
            for r in rows:
                cur.execute(
                    """
                    INSERT INTO threat_intel_hits
                        (ioc_id, device_ip, domain, detected_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    (r["ioc_id"], r["device_ip"], r["ioc_value"], now),
                )
                hit_row = cur.fetchone()
                hits.append(
                    {
                        "id": hit_row["id"],
                        "ioc_id": r["ioc_id"],
                        "device_ip": r["device_ip"],
                        "domain": r["ioc_value"],
                        "severity": r["severity"],
                        "feed_name": r["feed_name"],
                    }
                )

        return hits
