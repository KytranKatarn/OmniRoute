"""
Tool Integration for Security & Network Module
===============================================
Provides integration with security tools (AdGuard, ntopng, scanners).
Stack management is handled by System Operations module.
"""

import os
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List


class AdGuardLocalAPI:
    """Interface with local AdGuard container"""

    def __init__(self, host: str = "host.docker.internal", port: int = 5354):
        # Try container name first, fall back to localhost with mapped port
        self.base_url = f"http://{host}:{port}"
        self.fallback_url = "http://192.168.1.200:5354"
        self.username = os.getenv("ADGUARD_USER", "admin")
        self.password = os.getenv("ADGUARD_PASS", "")

    def _request(self, method: str, endpoint: str, data: dict = None, timeout: int = 5) -> Optional[dict]:
        """Make API request to AdGuard"""
        urls = [self.base_url, self.fallback_url]

        for url in urls:
            try:
                full_url = f"{url}/control/{endpoint}"
                auth = (self.username, self.password) if self.password else None

                if method == "GET":
                    response = requests.get(full_url, auth=auth, timeout=timeout)
                elif method == "POST":
                    response = requests.post(full_url, auth=auth, json=data, timeout=timeout)
                else:
                    continue

                response.raise_for_status()
                return response.json() if response.content else {}
            except Exception:
                continue

        return None

    def get_status(self) -> Optional[Dict]:
        """Get AdGuard status"""
        return self._request("GET", "status")

    def get_stats(self) -> Optional[Dict]:
        """Get AdGuard statistics"""
        return self._request("GET", "stats")

    def get_query_log(self, limit: int = 100) -> Optional[Dict]:
        """Get DNS query log"""
        return self._request("GET", f"querylog?limit={limit}")

    def block_domain(self, domain: str) -> bool:
        """Add domain to blocklist"""
        try:
            result = self._request("POST", "filtering/add_url", {"name": domain, "url": f"||{domain}^"})
            return result is not None
        except Exception:
            return False

    def check_health(self) -> bool:
        """Check if AdGuard is reachable"""
        return self.get_status() is not None


class NtopngLocalAPI:
    """Interface with local ntopng container (host mode — use host IP)"""

    def __init__(self, host: str = None, port: int = None):
        _host = host or os.getenv("NTOPNG_HOST", "192.168.1.200")
        _port = port or int(os.getenv("NTOPNG_PORT", "3001"))
        self.base_url = f"http://{_host}:{_port}"
        self.username = os.getenv("NTOPNG_USER", "admin")
        self.password = os.getenv("NTOPNG_ADMIN_PASSWORD", os.getenv("NTOPNG_PASS", "admin"))
        self._session = requests.Session()
        self._authenticated = False

    def _ensure_auth(self):
        """Cookie-based session auth (ntopng does not support basic auth)."""
        if self._authenticated:
            return
        try:
            resp = self._session.post(
                f"{self.base_url}/authorize.html",
                data={"user": self.username, "password": self.password},
                allow_redirects=True,
                timeout=5,
            )
            # Auth succeeds if we don't land on login or wrong-credentials page
            self._authenticated = "login" not in resp.url and "wrong" not in resp.url
        except Exception:
            self._authenticated = False

    def _request(self, endpoint: str, params: dict = None, timeout: int = 5) -> Optional[dict]:
        """Make API request to ntopng with cookie auth (REST v2)"""
        self._ensure_auth()
        try:
            full_url = f"{self.base_url}/lua/rest/v2/{endpoint}"
            response = self._session.get(full_url, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            if data.get("rc") == 0:
                return data
            return None
        except Exception:
            return None

    def get_interface_stats(self) -> Optional[Dict]:
        """Get network interface statistics"""
        return self._request("get/interface/data.lua", {"ifid": 0})

    def get_top_hosts(self, limit: int = 10) -> Optional[Dict]:
        """Get top hosts by traffic"""
        return self._request("get/host/active.lua", {"ifid": 0, "perPage": limit})

    def get_alerts(self) -> Optional[Dict]:
        """Get active alerts"""
        return self._request("get/alert/list.lua", {"ifid": 0})

    def check_health(self) -> bool:
        """Check if ntopng is reachable"""
        return self.get_interface_stats() is not None


class SecurityScannerService:
    """Interface with security scanner containers via Docker SDK"""

    def __init__(self):
        _base_dir = os.getenv("ARCHIE_BASE_DIR", "/mnt/archie_brain")
        self.scans_dir = os.path.join(_base_dir, "security_scans")

    def _docker_exec(self, container: str, command: List[str], timeout: int = 300) -> Dict[str, Any]:
        """Execute command in a container using Docker SDK (not shell)"""
        try:
            import docker

            client = docker.from_env()
            container_obj = client.containers.get(container)

            # Docker SDK exec_run is safe - command is passed as a list, not shell string
            exec_result = container_obj.exec_run(command, demux=True)

            stdout = exec_result.output[0].decode() if exec_result.output[0] else ""
            stderr = exec_result.output[1].decode() if exec_result.output[1] else ""

            return {
                "success": exec_result.exit_code == 0,
                "exit_code": exec_result.exit_code,
                "stdout": stdout,
                "stderr": stderr,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def run_nmap_scan(self, target: str, scan_type: str = "quick") -> Dict[str, Any]:
        """Run nmap scan on target"""
        # Validate target to prevent injection
        if not self._validate_target(target):
            return {"success": False, "error": "Invalid target format"}

        scan_id = f"nmap_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        output_file = f"/tmp/{scan_id}.xml"

        # Build nmap command based on scan type - command passed as list for safety
        # "--" ends nmap option parsing so a validated target can never be
        # re-interpreted as an option flag.
        if scan_type == "quick":
            cmd = ["nmap", "-T4", "-F", "-oX", output_file, "--", target]
        elif scan_type == "full":
            cmd = ["nmap", "-T4", "-A", "-p-", "-oX", output_file, "--", target]
        elif scan_type == "vuln":
            cmd = ["nmap", "-T4", "--script=vuln", "-oX", output_file, "--", target]
        else:
            cmd = ["nmap", "-T4", "-oX", output_file, "--", target]

        result = self._docker_exec("security_nmap", cmd)
        result["scan_id"] = scan_id
        result["output_file"] = output_file.replace("/tmp/", f"{self.scans_dir}/")

        return result

    def run_nikto_scan(self, target: str) -> Dict[str, Any]:
        """Run nikto web vulnerability scan"""
        if not self._validate_target(target):
            return {"success": False, "error": "Invalid target format"}

        scan_id = f"nikto_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        output_file = f"/tmp/{scan_id}.json"

        cmd = ["nikto.pl", "-h", target, "-Format", "csv", "-output", output_file]

        result = self._docker_exec("security_nikto", cmd, timeout=600)
        result["scan_id"] = scan_id
        result["output_file"] = output_file.replace("/tmp/", f"{self.scans_dir}/")

        return result

    def run_nuclei_scan(self, target: str, templates: str = "cves") -> Dict[str, Any]:
        """Run nuclei vulnerability scan"""
        if not self._validate_target(target):
            return {"success": False, "error": "Invalid target format"}

        # Validate templates parameter
        allowed_templates = [
            "dast",
            "dns",
            "http",
            "network",
            "ssl",
            "vulnerabilities",
            "exposures",
            "misconfiguration",
            "default-logins",
        ]
        if templates not in allowed_templates:
            templates = "cves"

        scan_id = f"nuclei_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        output_file = f"/tmp/{scan_id}.json"

        template_dir = f"/root/nuclei-templates/{templates}"
        cmd = ["nuclei", "-u", target, "-t", template_dir, "-jsonl", "-o", output_file]

        result = self._docker_exec("security_nuclei", cmd, timeout=600)
        result["scan_id"] = scan_id
        result["output_file"] = output_file.replace("/tmp/", f"{self.scans_dir}/")

        return result

    def run_ssl_scan(self, domain: str) -> Dict[str, Any]:
        """Run SSL/TLS analysis"""
        if not self._validate_domain(domain):
            return {"success": False, "error": "Invalid domain format"}

        scan_id = f"ssl_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        output_file = f"/tmp/{scan_id}.json"

        cmd = ["/usr/local/bin/testssl.sh", "--jsonfile", output_file, "--", domain]

        result = self._docker_exec("security_testssl", cmd, timeout=300)
        result["scan_id"] = scan_id
        result["output_file"] = output_file.replace("/tmp/", f"{self.scans_dir}/")

        return result

    def _validate_target(self, target: str) -> bool:
        """Validate a scan target for injection safety.

        Delegates to the shared ``scan_input_validator`` which — unlike the old
        regex here — rejects a leading ``-`` (nmap/nuclei argument injection)
        as well as shell metacharacters. SSRF / internal-target policy is
        enforced at the ROUTE layer (where the ``confirm_internal`` opt-in
        lives), so this service-level guard passes ``allow_internal=True`` and
        stays purely an injection guard (defense in depth for internal callers
        such as the campaign worker).
        """
        from .scan_input_validator import ScanInputError, validate_target

        try:
            validate_target(target, allow_internal=True)
            return True
        except ScanInputError:
            return False

    def _validate_domain(self, domain: str) -> bool:
        """Validate domain name format"""
        import re

        pattern = r"^[a-zA-Z0-9][a-zA-Z0-9\-_.]*[a-zA-Z0-9]$"
        return bool(re.match(pattern, domain)) and len(domain) <= 253

    def get_zap_status(self) -> Optional[Dict]:
        """Get ZAP daemon status"""
        try:
            response = requests.get("http://security_zap:8090/JSON/core/view/version/", timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass

        try:
            response = requests.get("http://localhost:8090/JSON/core/view/version/", timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass

        return None

    def start_zap_scan(self, target: str, scan_type: str = "spider") -> Dict[str, Any]:
        """Start ZAP scan on target"""
        if not self._validate_target(target):
            return {"success": False, "error": "Invalid target format"}

        base_urls = ["http://security_zap:8090", "http://localhost:8090"]

        for base_url in base_urls:
            try:
                # First, access the target
                response = requests.get(
                    f"{base_url}/JSON/core/action/accessUrl/",
                    params={"url": target},
                    timeout=10,
                )

                if scan_type == "spider":
                    # Start spider scan
                    response = requests.get(
                        f"{base_url}/JSON/spider/action/scan/",
                        params={"url": target, "maxChildren": 10},
                        timeout=10,
                    )
                elif scan_type == "active":
                    # Start active scan
                    response = requests.get(
                        f"{base_url}/JSON/ascan/action/scan/",
                        params={"url": target},
                        timeout=10,
                    )
                else:
                    # Passive scan (default after spider)
                    response = requests.get(
                        f"{base_url}/JSON/spider/action/scan/",
                        params={"url": target},
                        timeout=10,
                    )

                if response.status_code == 200:
                    result = response.json()
                    return {
                        "success": True,
                        "scan_id": result.get("scan", result.get("scanId", "unknown")),
                        "scan_type": scan_type,
                        "target": target,
                    }
            except Exception:
                continue

        return {"success": False, "error": "Could not connect to ZAP"}


def check_external_tools_status() -> Dict[str, Any]:
    """Check connectivity to all security tools (not stacks - use System Operations for that)"""
    adguard = AdGuardLocalAPI()
    ntopng = NtopngLocalAPI()
    scanner = SecurityScannerService()

    return {
        "adguard": {"online": adguard.check_health(), "type": "dns_filter"},
        "ntopng": {"online": ntopng.check_health(), "type": "traffic_analysis"},
        "zap": {"online": scanner.get_zap_status() is not None, "type": "web_scanner"},
    }


# Instantiate for easy import
adguard_api = AdGuardLocalAPI()
ntopng_api = NtopngLocalAPI()
scanner_service = SecurityScannerService()
