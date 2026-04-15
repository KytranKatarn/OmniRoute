# platform_v2/tools/security_network/fail2ban_service.py
"""fail2ban management via host command queue.

Uses the host_command_client to execute fail2ban-client commands on the host,
since fail2ban runs on the host OS, not inside the Docker container.
"""

import ipaddress
import logging
import re

logger = logging.getLogger(__name__)


class Fail2banService:
    """Manages fail2ban jails via host command queue."""

    def _validate_ip(self, ip: str) -> bool:
        """Validate an IP address to prevent command injection."""
        try:
            ipaddress.ip_address(ip)
            return True
        except ValueError:
            return False

    def _validate_jail_name(self, name: str) -> bool:
        """Validate jail name — alphanumeric + hyphens only."""
        return bool(re.match(r"^[a-zA-Z0-9_-]+$", name))

    def _submit(self, command_type: str, params: dict = None, timeout: int = 60) -> dict:
        """Submit a command to the host command queue and wait for result."""
        try:
            from tools.system_operations.host_command_client import (
                submit_and_wait,
                is_queue_available,
            )

            if not is_queue_available():
                return {"success": False, "error": "Host command queue unavailable"}
            result_data = submit_and_wait(command_type, params or {}, timeout=timeout, submitted_by="security_network")
            return result_data.get("result", {"success": False, "error": "No result"})
        except Exception as e:
            logger.error(f"fail2ban host command failed: {e}")
            return {"success": False, "error": str(e)}

    def get_status(self) -> dict:
        """Get overall fail2ban status."""
        result = self._submit("fail2ban_status")
        if result.get("success"):
            return {"running": True, "jails": result.get("jails", []), "raw": result.get("raw", "")}
        return {"running": False, "error": result.get("error", "Unknown error")}

    def get_jails(self) -> list:
        """List all configured jail names."""
        status = self.get_status()
        return status.get("jails", [])

    def get_jail_status(self, jail_name: str) -> dict:
        """Get detailed status for a specific jail."""
        if not self._validate_jail_name(jail_name):
            return {"error": "Invalid jail name"}
        result = self._submit("fail2ban_jail_status", {"jail": jail_name})
        if result.get("success"):
            return {
                "jail": result.get("jail", jail_name),
                "name": result.get("jail", jail_name),
                "active": True,
                "status": "active",
                "currently_failed": result.get("currently_failed", 0),
                "total_failed": result.get("total_failed", 0),
                "currently_banned": result.get("currently_banned", 0),
                "total_banned": result.get("total_banned", 0),
                "banned_ips": result.get("banned_ips", []),
            }
        return {
            "name": jail_name,
            "active": False,
            "status": "inactive",
            "error": result.get("error", "Failed to get jail status"),
        }

    def ban_ip(self, jail_name: str, ip: str) -> bool:
        """Ban an IP in a specific jail."""
        if not self._validate_jail_name(jail_name):
            raise ValueError(f"Invalid jail name: {jail_name}")
        if not self._validate_ip(ip):
            raise ValueError(f"Invalid IP address: {ip}")
        result = self._submit("fail2ban_ban", {"jail": jail_name, "ip": ip})
        return result.get("success", False)

    def unban_ip(self, jail_name: str, ip: str) -> bool:
        """Unban an IP from a specific jail."""
        if not self._validate_jail_name(jail_name):
            raise ValueError(f"Invalid jail name: {jail_name}")
        if not self._validate_ip(ip):
            raise ValueError(f"Invalid IP address: {ip}")
        result = self._submit("fail2ban_unban", {"jail": jail_name, "ip": ip})
        return result.get("success", False)

    def get_all_jail_statuses(self) -> list:
        """Get status for all jails at once."""
        jails = self.get_jails()
        return [self.get_jail_status(j) for j in jails]
