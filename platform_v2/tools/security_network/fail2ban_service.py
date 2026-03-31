# platform_v2/tools/security_network/fail2ban_service.py
"""fail2ban CLI wrapper for jail management.

Provides read/write access to fail2ban jails via subprocess calls
to fail2ban-client. All commands are validated to prevent injection.
"""
import ipaddress
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

FAIL2BAN_CMD = "fail2ban-client"
TIMEOUT_SECONDS = 10


class Fail2banService:
    """Wraps fail2ban-client CLI for jail management."""

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        """Run a fail2ban-client command safely."""
        cmd = ["sudo", FAIL2BAN_CMD] + args
        return subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)

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

    def get_status(self) -> dict:
        """Get overall fail2ban status."""
        try:
            result = self._run(["status"])
            if result.returncode != 0:
                return {"error": result.stderr.strip(), "running": False}
            return {"running": True, "raw": result.stdout.strip()}
        except FileNotFoundError:
            return {"error": "fail2ban-client not found", "running": False}
        except subprocess.TimeoutExpired:
            return {"error": "fail2ban-client timed out", "running": False}

    def get_jails(self) -> list[str]:
        """List all configured jail names."""
        try:
            result = self._run(["status"])
            if result.returncode != 0:
                return []
            for line in result.stdout.splitlines():
                if "Jail list:" in line:
                    jails_str = line.split("Jail list:")[1].strip()
                    return [j.strip() for j in jails_str.split(",") if j.strip()]
            return []
        except Exception as e:
            logger.error(f"Failed to get jails: {e}")
            return []

    def get_jail_status(self, jail_name: str) -> dict:
        """Get detailed status for a specific jail."""
        if not self._validate_jail_name(jail_name):
            return {"error": "Invalid jail name"}
        try:
            result = self._run(["status", jail_name])
            if result.returncode != 0:
                return {"error": result.stderr.strip()}
            output = result.stdout
            status = {
                "jail": jail_name,
                "currently_failed": 0,
                "total_failed": 0,
                "currently_banned": 0,
                "total_banned": 0,
                "banned_ips": [],
            }
            for line in output.splitlines():
                line = line.strip()
                if "Currently failed:" in line:
                    status["currently_failed"] = int(line.split(":")[-1].strip())
                elif "Total failed:" in line:
                    status["total_failed"] = int(line.split(":")[-1].strip())
                elif "Currently banned:" in line:
                    status["currently_banned"] = int(line.split(":")[-1].strip())
                elif "Total banned:" in line:
                    status["total_banned"] = int(line.split(":")[-1].strip())
                elif "Banned IP list:" in line:
                    ips_str = line.split(":")[-1].strip()
                    status["banned_ips"] = [ip.strip() for ip in ips_str.split() if ip.strip()]
            return status
        except Exception as e:
            logger.error(f"Failed to get jail status for {jail_name}: {e}")
            return {"error": str(e)}

    def ban_ip(self, jail_name: str, ip: str) -> bool:
        """Ban an IP in a specific jail."""
        if not self._validate_jail_name(jail_name):
            raise ValueError(f"Invalid jail name: {jail_name}")
        if not self._validate_ip(ip):
            raise ValueError(f"Invalid IP address: {ip}")
        try:
            result = self._run(["set", jail_name, "banip", ip])
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Failed to ban {ip} in {jail_name}: {e}")
            return False

    def unban_ip(self, jail_name: str, ip: str) -> bool:
        """Unban an IP from a specific jail."""
        if not self._validate_jail_name(jail_name):
            raise ValueError(f"Invalid jail name: {jail_name}")
        if not self._validate_ip(ip):
            raise ValueError(f"Invalid IP address: {ip}")
        try:
            result = self._run(["set", jail_name, "unbanip", ip])
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Failed to unban {ip} from {jail_name}: {e}")
            return False

    def get_all_jail_statuses(self) -> list[dict]:
        """Get status for all jails at once."""
        jails = self.get_jails()
        return [self.get_jail_status(j) for j in jails]
