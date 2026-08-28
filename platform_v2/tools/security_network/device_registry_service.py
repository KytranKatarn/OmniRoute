"""
Device Registry Service
========================
Network device discovery, registration, and AdGuard DNS sync.
Owns the network_devices table as source of truth.
"""

import json
import os
import logging
import subprocess
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

import requests
import psycopg2
from psycopg2.extras import RealDictCursor, Json

from database import get_db_cursor

logger = logging.getLogger(__name__)

# Zone -> AdGuard client policy mapping
ZONE_POLICIES = {
    "trusted": {
        "filtering_enabled": True,
        "safesearch": {"enabled": False},
        "safebrowsing_enabled": True,
        "parental_enabled": False,
        "blocked_services": [],
        "use_global_settings": False,
    },
    "family": {
        "filtering_enabled": True,
        "safesearch": {"enabled": True},
        "safebrowsing_enabled": True,
        "parental_enabled": True,
        "blocked_services": [],
        "use_global_settings": False,
    },
    "guest": {
        "filtering_enabled": True,
        "safesearch": {"enabled": True},
        "safebrowsing_enabled": True,
        "parental_enabled": True,
        "blocked_services": ["facebook", "tiktok", "instagram", "snapchat"],
        "use_global_settings": False,
    },
    "iot": {
        "filtering_enabled": True,
        "safesearch": {"enabled": False},
        "safebrowsing_enabled": True,
        "parental_enabled": False,
        "blocked_services": [],
        "use_global_settings": False,
    },
    "quarantined": {
        "filtering_enabled": True,
        "safesearch": {"enabled": True},
        "safebrowsing_enabled": True,
        "parental_enabled": True,
        "blocked_services": [],
        "use_global_settings": False,
    },
}

# Top 20 MAC OUI prefixes for vendor lookup
MAC_OUI_PREFIXES = {
    "00:03:93": "Apple",
    "00:05:02": "Apple",
    "00:0A:27": "Apple",
    "00:0A:95": "Apple",
    "00:0D:93": "Apple",
    "00:1B:63": "Apple",
    "00:1E:C2": "Apple",
    "00:25:00": "Apple",
    "00:26:BB": "Apple",
    "28:6A:BA": "Apple",
    "3C:15:C2": "Apple",
    "3C:22:FB": "Apple",
    "40:A6:D9": "Apple",
    "58:55:CA": "Apple",
    "70:DE:E2": "Apple",
    "78:7B:8A": "Apple",
    "7C:D1:C3": "Apple",
    "80:E6:50": "Apple",
    "84:FC:FE": "Apple",
    "8C:85:90": "Apple",
    "A4:B1:C1": "Apple",
    "AC:DE:48": "Apple",
    "B8:E8:56": "Apple",
    "C8:69:CD": "Apple",
    "DC:A9:04": "Apple",
    "E0:B9:BA": "Apple",
    "F0:D1:A9": "Apple",
    "00:1A:11": "Google",
    "3C:5A:B4": "Google",
    "54:60:09": "Google",
    "94:EB:2C": "Google",
    "F4:F5:D8": "Google",
    "A4:77:33": "Google",
    "00:15:5D": "Microsoft",
    "00:50:F2": "Microsoft",
    "28:18:78": "Microsoft",
    "7C:1E:52": "Microsoft",
    "00:1A:7D": "Samsung",
    "00:21:19": "Samsung",
    "00:26:37": "Samsung",
    "08:D4:2B": "Samsung",
    "10:1D:C0": "Samsung",
    "34:23:BA": "Samsung",
    "50:01:D9": "Samsung",
    "78:BD:BC": "Samsung",
    "84:25:DB": "Samsung",
    "94:35:0A": "Samsung",
    "A8:06:00": "Samsung",
    "C4:73:1E": "Samsung",
    "E4:7C:F9": "Samsung",
    "F8:04:2E": "Samsung",
    "00:13:E8": "Intel",
    "00:1B:21": "Intel",
    "00:1E:64": "Intel",
    "00:1F:3B": "Intel",
    "3C:97:0E": "Intel",
    "68:05:CA": "Intel",
    "B4:69:21": "Intel",
    "B8:27:EB": "Raspberry Pi",
    "DC:A6:32": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi",
    "28:D2:44": "Raspberry Pi",
    "D8:3A:DD": "Raspberry Pi",
    "2C:CF:67": "Raspberry Pi",
    "00:04:4B": "Nvidia",
    "00:1B:B1": "Huawei",
    "00:E0:FC": "Huawei",
    "20:F1:7C": "Huawei",
    "48:46:FB": "Huawei",
    "70:72:3C": "Huawei",
    "88:53:95": "Huawei",
    "AC:CF:85": "Huawei",
    "C8:D1:5E": "Huawei",
    "00:17:88": "Philips Hue",
    "EC:B5:FA": "Philips Hue",
    "00:1D:C9": "TP-Link",
    "30:B5:C2": "TP-Link",
    "50:C7:BF": "TP-Link",
    "60:32:B1": "TP-Link",
    "B0:4E:26": "TP-Link",
    "C0:06:C3": "TP-Link",
    "18:B4:30": "Nest",
    "64:16:66": "Nest",
    "00:0E:C6": "Asix (USB Ethernet)",
    "00:24:E4": "Withings",
    "00:17:C8": "Kyocera",
    "00:04:20": "Slim Devices (Sonos)",
    "00:0E:58": "Sonos",
    "5C:AA:FD": "Sonos",
    "78:28:CA": "Sonos",
    "B8:E9:37": "Sonos",
    "00:18:DD": "Silicondust (HDHomeRun)",
    "00:1D:FE": "Ring",
    "00:62:6E": "Amazon",
    "10:CE:A9": "Amazon",
    "34:D2:70": "Amazon",
    "44:65:0D": "Amazon",
    "68:54:FD": "Amazon",
    "74:C2:46": "Amazon",
    "A0:02:DC": "Amazon",
    "F0:F0:A4": "Amazon",
    "FC:65:DE": "Amazon",
}

ONLINE_THRESHOLD_MINUTES = 15

# IPs to skip during discovery
SKIP_IPS = {"127.0.0.1", "::1", "192.168.1.200"}


class DeviceRegistryService:
    """Network device registry with AdGuard sync."""

    _discovery_running = False

    def __init__(self):
        self.adguard_host = os.getenv("ADGUARD_HOST", "host.docker.internal")
        self.adguard_port = os.getenv("ADGUARD_PORT", "5354")
        self.adguard_user = os.getenv("ADGUARD_USER", "")
        self.adguard_pass = os.getenv("ADGUARD_PASS", "")
        self.adguard_base = f"http://{self.adguard_host}:{self.adguard_port}"
        self._dns_active_cache = None
        self._dns_active_cache_ts = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _adguard_auth(self):
        """Return HTTP Basic auth tuple."""
        return (self.adguard_user, self.adguard_pass) if self.adguard_user else None

    @staticmethod
    def _is_online(last_seen_at) -> bool:
        """True if device was seen within the last 15 minutes."""
        if not last_seen_at:
            return False
        if isinstance(last_seen_at, str):
            last_seen_at = datetime.fromisoformat(last_seen_at.replace("Z", "+00:00"))
        # DB may hand back naive UTC — tag it so aware arithmetic works
        if last_seen_at.tzinfo is None:
            last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - last_seen_at) < timedelta(minutes=ONLINE_THRESHOLD_MINUTES)

    @staticmethod
    def _parse_query_ts(raw: str) -> datetime:
        """Parse an AdGuard RFC3339 timestamp into an aware UTC datetime.

        AdGuard emits nanosecond fractions (9 digits) that fromisoformat
        rejects — trim the fraction to microseconds but KEEP the offset
        (the old split('.')[0] approach dropped the offset entirely).
        """
        raw = raw.strip().replace("Z", "+00:00")
        if "." in raw:
            head, _, tail = raw.partition(".")
            digits = ""
            for ch in tail:
                if not ch.isdigit():
                    break
                digits += ch
            offset = tail[len(digits) :]
            raw = f"{head}.{digits[:6] or '0'}{offset}"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _get_dns_active_clients(self) -> dict:
        """Get DNS-active clients with query count and last query time (cached 60s).

        Returns dict of ip -> {"count": N, "last_query": "ISO timestamp"}.
        """
        import time as _time

        now = _time.time()
        if self._dns_active_cache is not None and (now - self._dns_active_cache_ts) < 60:
            return self._dns_active_cache

        active = {}
        try:
            # Get query counts from stats
            resp = requests.get(
                f"{self.adguard_base}/control/stats",
                auth=self._adguard_auth(),
                timeout=10,
            )
            resp.raise_for_status()
            for entry in resp.json().get("top_clients", []):
                for ip, count in entry.items():
                    active[ip] = {"count": count, "last_query": None}
        except Exception as e:
            logger.debug("Failed to fetch AdGuard stats for DNS active clients: %s", e)

        # Get last query timestamp per client from query log
        try:
            resp = requests.get(
                f"{self.adguard_base}/control/querylog?limit=200",
                auth=self._adguard_auth(),
                timeout=10,
            )
            resp.raise_for_status()
            for entry in resp.json().get("data", []):
                client = entry.get("client", "")
                ts = entry.get("time", "")
                if client and ts:
                    if client not in active:
                        active[client] = {"count": 0, "last_query": ts}
                    elif active[client]["last_query"] is None:
                        active[client]["last_query"] = ts
        except Exception as e:
            logger.debug("Failed to fetch AdGuard query log: %s", e)

        self._dns_active_cache = active
        self._dns_active_cache_ts = now
        return active

    @staticmethod
    def _serialize_device(row: Dict, dns_active_clients: dict = None) -> Dict:
        """Convert a DB row dict to JSON-safe dict."""
        if not row:
            return row
        d = dict(row)
        # Convert inet to string
        for key in ("ip_address",):
            if key in d and d[key] is not None:
                d[key] = str(d[key])
        # Convert timestamps to isoformat
        for key in (
            "first_seen_at",
            "last_seen_at",
            "created_at",
            "updated_at",
        ):
            if key in d and d[key] is not None:
                d[key] = d[key].isoformat() if hasattr(d[key], "isoformat") else d[key]
        # Tag whether this device is using AdGuard DNS
        dns_online = False
        if dns_active_clients is not None:
            ip = d.get("ip_address", "")
            client_info = dns_active_clients.get(ip, {})
            d["dns_query_count"] = client_info.get("count", 0) if isinstance(client_info, dict) else 0
            d["dns_last_query"] = client_info.get("last_query") if isinstance(client_info, dict) else None
            # Protected = has made a DNS query in the last 15 minutes
            if d.get("dns_last_query"):
                try:
                    last_q = DeviceRegistryService._parse_query_ts(d["dns_last_query"])
                    diff_mins = (datetime.now(timezone.utc) - last_q).total_seconds() / 60
                    d["dns_active"] = diff_mins <= 15
                    dns_online = diff_mins <= 5
                except Exception as e:
                    logger.debug("Failed to parse dns_last_query timestamp: %s", e)
                    d["dns_active"] = False
            else:
                d["dns_active"] = False
        else:
            d["dns_active"] = False
            d["dns_query_count"] = 0
            d["dns_last_query"] = None
        # Online = last DNS query within 5 min OR last_seen within 15 min
        d["is_online"] = dns_online or DeviceRegistryService._is_online(row.get("last_seen_at"))
        return d

    # ------------------------------------------------------------------
    # DB Query Methods
    # ------------------------------------------------------------------

    def get_device(self, device_id: int) -> Optional[Dict]:
        """Get a single device by ID."""
        dns_clients = self._get_dns_active_clients()
        with get_db_cursor(commit=False) as (conn, cur):
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM network_devices WHERE id = %s", (device_id,))
            row = cur.fetchone()
        return self._serialize_device(row, dns_clients) if row else None

    def get_devices(
        self,
        zone: Optional[str] = None,
        device_type: Optional[str] = None,
        owner: Optional[str] = None,
        online: Optional[bool] = None,
        status: Optional[str] = None,
    ) -> List[Dict]:
        """Get filtered list of devices."""
        conditions = []
        params = []

        if zone:
            conditions.append("security_zone = %s")
            params.append(zone)
        if device_type:
            conditions.append("device_type = %s")
            params.append(device_type)
        if owner:
            conditions.append("owner = %s")
            params.append(owner)
        if status:
            conditions.append("status = %s")
            params.append(status)
        if online is not None:
            threshold = datetime.now(timezone.utc) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)
            if online:
                conditions.append("last_seen_at >= %s")
            else:
                conditions.append("(last_seen_at < %s OR last_seen_at IS NULL)")
            params.append(threshold)

        where = " AND ".join(conditions) if conditions else "TRUE"
        query = f"SELECT * FROM network_devices WHERE {where} ORDER BY last_seen_at DESC NULLS LAST"

        dns_clients = self._get_dns_active_clients()
        with get_db_cursor(commit=False) as (conn, cur):
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(query, params)
            rows = cur.fetchall()

        return [self._serialize_device(r, dns_clients) for r in rows]

    def get_unregistered(self) -> List[Dict]:
        """Get unregistered active devices."""
        dns_clients = self._get_dns_active_clients()
        with get_db_cursor(commit=False) as (conn, cur):
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT * FROM network_devices "
                "WHERE is_registered = FALSE AND status = 'active' "
                "ORDER BY last_seen_at DESC NULLS LAST"
            )
            rows = cur.fetchall()
        return [self._serialize_device(r, dns_clients) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        """Get device counts by zone, online/offline, registered/unregistered."""
        dns_clients = self._get_dns_active_clients()
        set(dns_clients.keys())

        with get_db_cursor(commit=False) as (conn, cur):
            cur = conn.cursor(cursor_factory=RealDictCursor)
            threshold = datetime.now(timezone.utc) - timedelta(minutes=ONLINE_THRESHOLD_MINUTES)

            cur.execute("SELECT COUNT(*) AS total FROM network_devices WHERE status = 'active'")
            total = cur.fetchone()["total"]

            # Online = last DNS query within 5 min OR last_seen within 15 min
            dns_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
            cur.execute("SELECT ip_address, last_seen_at FROM network_devices WHERE status = 'active'")
            online = 0
            for row in cur.fetchall():
                seen_recently = row["last_seen_at"] and row["last_seen_at"] >= threshold
                ip = str(row["ip_address"])
                dns_online = False
                client_info = dns_clients.get(ip, {})
                if isinstance(client_info, dict) and client_info.get("last_query"):
                    try:
                        dns_online = self._parse_query_ts(client_info["last_query"]) >= dns_threshold
                    except Exception as e:
                        logger.debug("Failed to parse DNS last_query for stats: %s", e)
                if seen_recently or dns_online:
                    online += 1

            cur.execute(
                "SELECT COUNT(*) AS cnt FROM network_devices " "WHERE is_registered = FALSE AND status = 'active'"
            )
            unregistered = cur.fetchone()["cnt"]

            cur.execute(
                "SELECT security_zone, COUNT(*) AS cnt FROM network_devices "
                "WHERE status = 'active' GROUP BY security_zone ORDER BY security_zone"
            )
            zones = {r["security_zone"]: r["cnt"] for r in cur.fetchall()}

        return {
            "total": total,
            "online": online,
            "unregistered": unregistered,
            "zones": zones,
        }

    # ------------------------------------------------------------------
    # Discovery Methods
    # ------------------------------------------------------------------

    def discover_devices(self) -> List[Dict]:
        """Main discovery: poll AdGuard auto_clients + ARP scan.

        Returns list of truly new devices (for alerting).
        """
        if DeviceRegistryService._discovery_running:
            logger.debug("Discovery already running, skipping")
            return []

        DeviceRegistryService._discovery_running = True
        new_devices = []
        try:
            discovered = {}  # ip -> {ip, mac, hostname}

            # 1) Poll AdGuard auto_clients
            try:
                resp = requests.get(
                    f"{self.adguard_base}/control/clients",
                    auth=self._adguard_auth(),
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                for client in data.get("auto_clients", []):
                    ip = client.get("ip", "")
                    if ip and not self._should_skip_ip(ip):
                        discovered[ip] = {
                            "ip": ip,
                            "mac": "",
                            "hostname": client.get("name", ""),
                        }
            except Exception as e:
                logger.debug("AdGuard client poll failed (continuing with ARP): %s", e)

            # 1b) Also pull top clients from AdGuard stats (real LAN IPs appear here)
            try:
                resp = requests.get(
                    f"{self.adguard_base}/control/stats",
                    auth=self._adguard_auth(),
                    timeout=10,
                )
                resp.raise_for_status()
                stats_data = resp.json()
                for entry in stats_data.get("top_clients", []):
                    for ip in entry:
                        if ip and not self._should_skip_ip(ip) and ip not in discovered:
                            discovered[ip] = {
                                "ip": ip,
                                "mac": "",
                                "hostname": "",
                            }
            except Exception as e:
                logger.debug("AdGuard stats poll failed: %s", e)

            # 2) ARP scan
            arp_entries = self._parse_arp_table()
            for entry in arp_entries:
                ip = entry["ip"]
                if self._should_skip_ip(ip):
                    continue
                if ip in discovered:
                    # Merge MAC from ARP into AdGuard entry
                    if entry.get("mac") and entry["mac"] != "00:00:00:00:00:00":
                        discovered[ip]["mac"] = entry["mac"]
                else:
                    discovered[ip] = entry

            # 3) Upsert into DB — two-phase: MAC first (IP change), then IP (new device)
            for ip, info in discovered.items():
                mac = info.get("mac") or None
                hostname = info.get("hostname") or None
                manufacturer = self.mac_vendor_lookup(mac) if mac else None

                with get_db_cursor(commit=True) as (conn, cur):
                    cur = conn.cursor(cursor_factory=RealDictCursor)

                    # Phase 1: Check if this MAC exists at a different IP (DHCP IP change)
                    if mac:
                        cur.execute(
                            "SELECT id, ip_address FROM network_devices WHERE mac_address = %s",
                            (mac,),
                        )
                        existing = cur.fetchone()
                        if existing and str(existing["ip_address"]) != ip:
                            old_ip = str(existing["ip_address"])

                            # Clear any stale UNREGISTERED row that currently
                            # holds the new IP. Registered rows are never
                            # auto-deleted. Without this, the UPDATE below
                            # would collide on idx_network_devices_ip and log
                            # a duplicate-key error (#2077).
                            cur.execute(
                                """DELETE FROM network_devices
                                   WHERE ip_address = %s AND id != %s
                                     AND is_registered = false""",
                                (ip, existing["id"]),
                            )

                            # If a REGISTERED row still owns the new IP,
                            # we can't re-point our MAC there — fall through
                            # to Phase 2 upsert which handles it gracefully.
                            cur.execute(
                                """SELECT id FROM network_devices
                                   WHERE ip_address = %s AND id != %s""",
                                (ip, existing["id"]),
                            )
                            if cur.fetchone():
                                logger.debug(
                                    "device_registry: IP %s claimed by another registered device; "
                                    "skipping Phase 1 MAC-follow for MAC %s",
                                    ip,
                                    mac,
                                )
                                continue

                            try:
                                cur.execute(
                                    """UPDATE network_devices SET
                                        ip_address = %s, last_seen_at = NOW(), updated_at = NOW()
                                       WHERE id = %s RETURNING *""",
                                    (ip, existing["id"]),
                                )
                                updated = cur.fetchone()
                            except psycopg2.IntegrityError as e:
                                logger.debug(
                                    "device_registry: Phase 1 UPDATE collided on IP %s: %s",
                                    ip,
                                    e,
                                )
                                conn.rollback()
                                continue
                            if updated and updated.get("is_registered"):
                                self._log_ip_change(self._serialize_device(updated), old_ip, ip)
                                # Re-sync AdGuard with new IP
                                self._delete_adguard_client(updated.get("friendly_name", ""))
                                self._sync_device_to_adguard(self._serialize_device(updated))
                            continue

                    # Phase 2: IP-based upsert (new or returning device)
                    # Always update last_seen_at; only overwrite name/MAC/mfr on unregistered
                    cur.execute(
                        """
                        INSERT INTO network_devices
                            (ip_address, mac_address, hostname, manufacturer,
                             first_seen_at, last_seen_at)
                        VALUES (%s, %s, %s, %s, NOW(), NOW())
                        ON CONFLICT (ip_address) DO UPDATE SET
                            last_seen_at = NOW(),
                            mac_address = CASE WHEN network_devices.is_registered
                                THEN COALESCE(network_devices.mac_address, EXCLUDED.mac_address)
                                ELSE COALESCE(EXCLUDED.mac_address, network_devices.mac_address) END,
                            hostname = CASE WHEN network_devices.is_registered
                                THEN network_devices.hostname
                                ELSE COALESCE(EXCLUDED.hostname, network_devices.hostname) END,
                            manufacturer = CASE WHEN network_devices.is_registered
                                THEN network_devices.manufacturer
                                ELSE COALESCE(EXCLUDED.manufacturer, network_devices.manufacturer) END
                        RETURNING id, ip_address, mac_address, hostname, manufacturer,
                                  (xmax = 0) AS was_inserted
                        """,
                        (ip, mac, hostname, manufacturer),
                    )
                    result = cur.fetchone()
                    if result and result.get("was_inserted"):
                        new_devices.append(self._serialize_device(result))

        except Exception as e:
            logger.error("Device discovery failed: %s", e)
        finally:
            DeviceRegistryService._discovery_running = False

        return new_devices

    def sync_docker_containers(self) -> List[Dict]:
        """Sync running Docker containers into network_devices.

        Keyed on metadata->>'container_name' (stable across container recreation).
        Updates IP + MAC on every call so stale values from a previous run are
        corrected even when the container was recreated with a new random MAC.

        Returns list of updated device dicts.
        """
        updated = []
        try:
            result = subprocess.run(
                ["docker", "ps", "-q"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            ids = result.stdout.strip().split()
            if not ids:
                return updated

            inspect = subprocess.run(
                ["docker", "inspect"] + ids,
                capture_output=True,
                text=True,
                timeout=15,
            )
            containers = json.loads(inspect.stdout)
        except Exception as e:
            logger.warning("sync_docker_containers: docker inspect failed: %s", e)
            return updated

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                for c in containers:
                    name = c.get("Name", "").lstrip("/")
                    if not name:
                        continue
                    for net_cfg in c.get("NetworkSettings", {}).get("Networks", {}).values():
                        ip = net_cfg.get("IPAddress", "")
                        mac = (net_cfg.get("MacAddress", "") or "").upper()
                        if not ip or ip.startswith("127."):
                            continue

                        # 1. Try match by container_name stored in metadata (stable key)
                        cur.execute(
                            """UPDATE network_devices SET
                                 ip_address   = %s,
                                 mac_address  = CASE WHEN %s != '' THEN %s
                                                     ELSE mac_address END,
                                 last_seen_at = NOW(),
                                 updated_at   = NOW()
                               WHERE metadata->>'container_name' = %s
                               RETURNING id, ip_address, mac_address, friendly_name""",
                            (ip, mac, mac, name),
                        )
                        row = cur.fetchone()
                        if row:
                            updated.append(dict(row))
                            continue

                        # 2. No metadata match — stamp container_name onto any
                        #    unregistered entry that owns this IP so future
                        #    syncs use the stable key.
                        cur.execute(
                            """UPDATE network_devices SET
                                 mac_address  = CASE WHEN %s != '' THEN %s
                                                     ELSE mac_address END,
                                 metadata     = metadata || jsonb_build_object(
                                                  'container_name', %s,
                                                  'device_class', 'docker_container'),
                                 last_seen_at = NOW(),
                                 updated_at   = NOW()
                               WHERE ip_address = %s AND is_registered = false
                               RETURNING id, ip_address, mac_address, friendly_name""",
                            (mac, mac, name, ip),
                        )
                        row = cur.fetchone()
                        if row:
                            updated.append(dict(row))

            logger.info("sync_docker_containers: updated %d container entries", len(updated))
        except Exception as e:
            logger.error("sync_docker_containers failed: %s", e)

        return updated

    def _parse_arp_table(self) -> List[Dict]:
        """Get ARP table from the HOST via host_command_client.

        Falls back to container's own `ip neigh show` if host queue unavailable.
        """
        # Try host command queue first (gets real LAN MACs)
        try:
            from tools.system_operations.host_command_client import (
                submit_and_wait,
                is_queue_available,
            )

            if is_queue_available():
                result = submit_and_wait("arp_scan", {}, timeout=30, submitted_by="device_registry")
                if result and result.get("result", {}).get("success"):
                    entries = result["result"]["entries"]
                    # Normalize MAC to uppercase
                    for e in entries:
                        if e.get("mac"):
                            e["mac"] = e["mac"].upper()
                    logger.debug("Host ARP scan: %d entries", len(entries))
                    return entries
        except Exception as e:
            logger.debug("Host ARP scan failed, falling back to container: %s", e)

        # Fallback: container's own ARP (only sees Docker bridge IPs)
        entries = []
        try:
            result = subprocess.run(
                ["ip", "neigh", "show"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 4:
                    continue
                ip = parts[0]
                mac = ""
                state = parts[-1] if parts else ""
                for part in parts:
                    if re.match(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$", part):
                        mac = part.upper()
                        break
                if state in ("FAILED", "INCOMPLETE"):
                    continue
                entries.append({"ip": ip, "mac": mac, "state": state})
        except Exception as e:
            logger.warning("ARP table parse failed: %s", e)
        return entries

    @staticmethod
    def _should_skip_ip(ip: str) -> bool:
        """Filter out Docker, localhost, multicast, link-local, IPv6, this server."""
        if ip in SKIP_IPS:
            return True
        if ip.startswith("172."):
            return True
        # Skip all IPv6 — we only track IPv4 LAN devices
        if ":" in ip:
            return True
        # Skip non-routable
        if ip.startswith("169.254."):
            return True
        return False

    @staticmethod
    def mac_vendor_lookup(mac: Optional[str]) -> str:
        """Lookup manufacturer from MAC OUI prefix."""
        if not mac:
            return "Unknown"
        prefix = mac.upper()[:8]
        return MAC_OUI_PREFIXES.get(prefix, "Unknown")

    # ------------------------------------------------------------------
    # Registration + Sync Methods
    # ------------------------------------------------------------------

    def register_device(
        self,
        device_id: int,
        friendly_name: str,
        device_type: str,
        owner: str,
        security_zone: str,
        notes: Optional[str] = None,
    ) -> Optional[Dict]:
        """Register a device: update DB and sync to AdGuard."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                UPDATE network_devices SET
                    friendly_name = %s,
                    device_type = %s,
                    owner = %s,
                    security_zone = %s,
                    notes = %s,
                    is_registered = TRUE,
                    adguard_client_id = friendly_name,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING *
                """,
                (friendly_name, device_type, owner, security_zone, notes, device_id),
            )
            row = cur.fetchone()

        if not row:
            return None

        device = self._serialize_device(row)
        self._sync_device_to_adguard(device)
        self._inject_allowlist_rules(device)
        return device

    def update_device(self, device_id: int, **kwargs) -> Optional[Dict]:
        """Update device fields dynamically and re-sync if needed."""
        allowed = {
            "friendly_name",
            "device_type",
            "owner",
            "security_zone",
            "notes",
            "status",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return self.get_device(device_id)

        # Get old device for change detection
        old_device = self.get_device(device_id)
        if not old_device:
            return None

        set_clauses = [f"{k} = %s" for k in updates]
        set_clauses.append("updated_at = NOW()")
        if "friendly_name" in updates:
            set_clauses.append("adguard_client_id = %s")

        params = list(updates.values())
        if "friendly_name" in updates:
            params.append(updates["friendly_name"])
        params.append(device_id)

        query = f"UPDATE network_devices SET {', '.join(set_clauses)} WHERE id = %s RETURNING *"

        with get_db_cursor(commit=True) as (conn, cur):
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(query, params)
            row = cur.fetchone()

        if not row:
            return None

        device = self._serialize_device(row)

        # Re-sync to AdGuard if zone, name, or IP changed
        if row.get("is_registered"):
            zone_changed = "security_zone" in updates
            name_changed = "friendly_name" in updates
            if zone_changed or name_changed:
                # Delete old client if name changed
                if name_changed and old_device.get("friendly_name"):
                    self._delete_adguard_client(old_device["friendly_name"])
                self._sync_device_to_adguard(device)
                if zone_changed:
                    self._inject_allowlist_rules(device)

        return device

    def delete_device(self, device_id: int) -> bool:
        """Delete device from DB and AdGuard."""
        device = self.get_device(device_id)
        if not device:
            return False

        # Remove from AdGuard first
        if device.get("friendly_name") and device.get("is_registered"):
            self._delete_adguard_client(device["friendly_name"])

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM network_devices WHERE id = %s", (device_id,))

        return True

    def sync_to_adguard(self) -> Dict[str, Any]:
        """Full sync: push all registered devices to AdGuard."""
        devices = self.get_devices(status="active")
        registered = [d for d in devices if d.get("is_registered")]

        synced = 0
        errors = 0
        for device in registered:
            try:
                self._sync_device_to_adguard(device)
                synced += 1
            except Exception as e:
                logger.warning("Sync failed for %s: %s", device.get("friendly_name"), e)
                errors += 1

        return {"synced": synced, "errors": errors, "total": len(registered)}

    def _sync_device_to_adguard(self, device: Dict) -> bool:
        """Push a single device's zone policy to AdGuard."""
        if not device.get("friendly_name") or not device.get("ip_address"):
            return False

        client_payload = self._build_adguard_client(device)
        auth = self._adguard_auth()

        try:
            # Try update first
            resp = requests.post(
                f"{self.adguard_base}/control/clients/update",
                json={"name": device["friendly_name"], "data": client_payload},
                auth=auth,
                timeout=10,
            )
            if resp.status_code == 200:
                return True

            # If not found, add as new client
            resp = requests.post(
                f"{self.adguard_base}/control/clients/add",
                json=client_payload,
                auth=auth,
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.warning("AdGuard sync failed for %s: %s", device.get("friendly_name"), e)
            return False

    @staticmethod
    def _build_adguard_client(device: Dict) -> Dict:
        """Build AdGuard client payload from device + zone policy."""
        zone = device.get("security_zone", "quarantined")
        policy = ZONE_POLICIES.get(zone, ZONE_POLICIES["quarantined"]).copy()

        return {
            "name": device["friendly_name"],
            "ids": [str(device["ip_address"])],
            **policy,
        }

    def _inject_allowlist_rules(self, device: Dict) -> None:
        """Inject client-specific allowlist rules for iot/quarantined zones.

        Uses AdGuard user rules with client syntax: @@||domain^$client=IP
        """
        zone = device.get("security_zone", "")
        if zone not in ("iot", "quarantined"):
            return

        ip = str(device.get("ip_address", ""))
        if not ip:
            return

        # Quarantine lite: allow device activation + captive portal detection
        allowlist_domains = [
            "albert.apple.com",
            "captive.apple.com",
            "gs.apple.com",
            "connectivitycheck.gstatic.com",
            "clients3.google.com",
            "detectportal.firefox.com",
            "msftconnecttest.com",
        ]

        # Build allowlist rules
        rules = [f"@@||{domain}^$client={ip}" for domain in allowlist_domains]
        rules_text = "\n".join(rules)

        try:
            # Get current user rules
            resp = requests.get(
                f"{self.adguard_base}/control/filtering/status",
                auth=self._adguard_auth(),
                timeout=10,
            )
            resp.raise_for_status()
            current_rules = resp.json().get("user_rules", [])

            # Remove any existing rules for this client IP
            marker = f"$client={ip}"
            filtered = [r for r in current_rules if marker not in r]

            # Add new rules
            filtered.extend(rules)

            # Update rules
            requests.post(
                f"{self.adguard_base}/control/filtering/set_rules",
                json={"rules": filtered},
                auth=self._adguard_auth(),
                timeout=10,
            )
            logger.info("Injected %d allowlist rules for %s (%s)", len(rules), device.get("friendly_name", ip), zone)
        except Exception as e:
            logger.warning("Failed to inject allowlist rules for %s: %s", ip, e)

    def _log_ip_change(self, device: Dict, old_ip: str, new_ip: str) -> None:
        """Log IP address change to security_dns_changes table."""
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO security_dns_changes
                       (source, action, domain, details, changed_by, created_at)
                       VALUES ('network', 'ip_change', %s, %s, 'discovery', NOW())""",
                    (
                        device.get("friendly_name") or str(new_ip),
                        Json(
                            {
                                "old_ip": old_ip,
                                "new_ip": new_ip,
                                "mac": device.get("mac_address"),
                                "device_id": device.get("id"),
                            }
                        ),
                    ),
                )
        except Exception as e:
            logger.debug("Failed to log IP change: %s", e)

    def _delete_adguard_client(self, name: str) -> bool:
        """Remove a client from AdGuard by name."""
        try:
            resp = requests.post(
                f"{self.adguard_base}/control/clients/delete",
                json={"name": name},
                auth=self._adguard_auth(),
                timeout=10,
            )
            return resp.status_code == 200
        except Exception as e:
            logger.debug("AdGuard client delete failed for %s: %s", name, e)
            return False
