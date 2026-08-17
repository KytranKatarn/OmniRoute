# platform_v2/tools/security_network/ddns_service.py
"""DDNS management service — IP tracking, history, manual updates."""

import logging
import os
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)

_BASE_DIR = os.getenv("ARCHIE_BASE_DIR", "/mnt/archie_brain")
DDNS_SCRIPT = os.path.join(_BASE_DIR, "scripts", "ddns_updater.sh")
DDNS_LAST_IP_FILE = os.path.join(_BASE_DIR, "scripts", ".ddns_last_ip")
TIMEOUT_SECONDS = 30


class DdnsService:
    """Manages DDNS updates and IP change tracking."""

    def get_current_public_ip(self) -> str | None:
        """Read the last known public IP from the DDNS script's state file."""
        try:
            with open(DDNS_LAST_IP_FILE) as f:
                return f.read().strip()
        except FileNotFoundError:
            logger.warning(f"DDNS last IP file not found: {DDNS_LAST_IP_FILE}")
            return None

    def get_live_public_ip(self) -> str | None:
        """Fetch the current public IP from an external service."""
        try:
            result = subprocess.run(
                ["curl", "-s", "https://api.ipify.org"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception as e:
            logger.error(f"Failed to fetch public IP: {e}")
            return None

    def trigger_update(self) -> dict:
        """Manually trigger a DDNS update."""
        if not os.path.exists(DDNS_SCRIPT):
            return {"success": False, "error": f"Script not found: {DDNS_SCRIPT}"}
        try:
            result = subprocess.run(
                ["bash", DDNS_SCRIPT],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout.strip(),
                "error": result.stderr.strip() if result.returncode != 0 else None,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "DDNS update timed out"}

    def get_status(self) -> dict:
        """Get DDNS overall status."""
        stored_ip = self.get_current_public_ip()
        last_modified = None
        if os.path.exists(DDNS_LAST_IP_FILE):
            mtime = os.path.getmtime(DDNS_LAST_IP_FILE)
            last_modified = datetime.fromtimestamp(mtime).isoformat()
        return {
            "stored_ip": stored_ip,
            "last_updated": last_modified,
            "script_exists": os.path.exists(DDNS_SCRIPT),
        }

    def _query_db(self, query: str, params: tuple = ()) -> list[dict]:
        """Query the database for IP history."""
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(query, params)
            # get_db_cursor uses RealDictCursor, so rows are already dict-like.
            # The old dict(zip(columns, row)) zipped column names with the ROW's
            # keys -> every value became its own column name. Return the rows.
            return [dict(r) for r in cur.fetchall()]

    def get_ip_history(self, limit: int = 50) -> list[dict]:
        """Get IP change history from network_ip_history table."""
        return self._query_db(
            "SELECT * FROM network_ip_history ORDER BY changed_at DESC LIMIT %s",
            (limit,),
        )

    def record_ip_change(self, old_ip: str, new_ip: str, dns_updated: bool = False) -> int:
        """Record an IP change in the history table."""
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "INSERT INTO network_ip_history (old_ip, new_ip, dns_updated) VALUES (%s, %s, %s) RETURNING id",
                (old_ip, new_ip, dns_updated),
            )
            return cur.fetchone()[0]
