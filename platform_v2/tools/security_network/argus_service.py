"""
Argus Reconnaissance Service
==============================
Wrapper for Argus CLI toolkit and direct Python recon capabilities.
Curated ~25 modules from Argus's 135 for home network security.
"""

import json
import socket
import ssl
import subprocess
import threading
from typing import Optional, Dict, List
import requests
from psycopg2.extras import Json
from database import get_db_cursor

from .scan_input_validator import (
    ScanInputError,
    validate_ports,
    validate_severity,
    validate_target,
)

CURATED_MODULES = {
    "network": [
        {"id": "dns_lookup", "name": "DNS Lookup", "description": "Resolve domain to IP addresses"},
        {"id": "reverse_dns", "name": "Reverse DNS", "description": "IP to hostname resolution"},
        {"id": "whois", "name": "WHOIS Lookup", "description": "Domain registration info"},
        {"id": "port_scan", "name": "Port Scan", "description": "Scan for open ports on target"},
        {"id": "traceroute", "name": "Traceroute", "description": "Network path to target"},
        {"id": "dnssec_check", "name": "DNSSEC Check", "description": "Validate DNSSEC configuration"},
        {"id": "tls_check", "name": "TLS/SSL Check", "description": "Analyze TLS certificate and cipher suites"},
        {"id": "ip_geolocation", "name": "IP Geolocation", "description": "Geographic location of IP"},
    ],
    "web": [
        {"id": "tech_detect", "name": "Technology Detection", "description": "Identify web technologies in use"},
        {"id": "header_analysis", "name": "Header Analysis", "description": "HTTP security header check"},
        {"id": "subdomain_enum", "name": "Subdomain Enumeration", "description": "Find subdomains of a domain"},
        {"id": "robots_txt", "name": "robots.txt Parser", "description": "Parse and analyze robots.txt"},
        {"id": "sitemap_parse", "name": "Sitemap Parser", "description": "Parse XML sitemap"},
        {"id": "cors_check", "name": "CORS Check", "description": "Test CORS misconfiguration"},
        {"id": "ssl_cert_info", "name": "SSL Certificate Info", "description": "Detailed certificate analysis"},
    ],
    "threat_intel": [
        {"id": "virustotal", "name": "VirusTotal Lookup", "description": "Check domain/IP against VT database"},
        {"id": "shodan", "name": "Shodan Search", "description": "Search Shodan for exposed services"},
        {"id": "hibp_check", "name": "HIBP Breach Check", "description": "Check email in breach databases"},
        {"id": "ip_reputation", "name": "IP Reputation", "description": "Check IP against threat feeds"},
        {"id": "malware_check", "name": "Malware Domain Check", "description": "Check domain against malware lists"},
    ],
    "discovery": [
        {"id": "crawler", "name": "Web Crawler", "description": "Crawl and map website structure"},
        {"id": "dir_brute", "name": "Directory Discovery", "description": "Find hidden directories and files"},
        {"id": "js_analysis", "name": "JavaScript Analysis", "description": "Analyze JS files for sensitive data"},
        {"id": "email_harvest", "name": "Email Harvester", "description": "Find email addresses from target"},
    ],
    "scanning": [
        {
            "id": "nmap_scan",
            "name": "Nmap Scan",
            "description": "Full port scan + service detection (Docker)",
            "container": "security_nmap",
        },
        {
            "id": "nikto_scan",
            "name": "Nikto Scan",
            "description": "Web server vulnerability scanner (Docker)",
            "container": "security_nikto",
        },
        {
            "id": "nuclei_scan",
            "name": "Nuclei Scan",
            "description": "Template-based vulnerability scanner (Docker)",
            "container": "security_nuclei",
        },
        {
            "id": "zap_scan",
            "name": "ZAP Scan",
            "description": "OWASP ZAP web app security scanner (Docker)",
            "container": "security_zap",
        },
        {
            "id": "testssl_scan",
            "name": "TestSSL Scan",
            "description": "SSL/TLS analysis and grading (Docker)",
            "container": "security_testssl",
        },
    ],
}

# Docker container names for scanning tools
SCAN_CONTAINERS = {
    "nmap_scan": "security_nmap",
    "nikto_scan": "security_nikto",
    "nuclei_scan": "security_nuclei",
    "zap_scan": "security_zap",
    "testssl_scan": "security_testssl",
}


class ArgusService:
    """Argus reconnaissance toolkit wrapper"""

    def __init__(self):
        self.argus_available = self._check_argus()

    def _check_argus(self) -> bool:
        try:
            result = subprocess.run(["python3", "-m", "argus", "--version"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False

    def get_modules(self) -> Dict[str, List[Dict]]:
        return CURATED_MODULES

    def start_scan(
        self, module_id: str, target: str, options: dict = None, triggered_by: str = "user"
    ) -> Optional[int]:
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO security_recon_scans (module_name, target, options, status, triggered_by)
                    VALUES (%s, %s, %s, 'running', %s) RETURNING id
                """,
                    (module_id, target, Json(options or {}), triggered_by),
                )
                scan_id = cur.fetchone()["id"]

            thread = threading.Thread(
                target=self._execute_scan, args=(scan_id, module_id, target, options or {}), daemon=True
            )
            thread.start()
            return scan_id
        except Exception:
            return None

    def _execute_scan(self, scan_id: int, module_id: str, target: str, options: dict):
        results = {}
        try:
            if module_id == "dns_lookup":
                results = self._dns_lookup(target)
            elif module_id == "reverse_dns":
                results = self._reverse_dns(target)
            elif module_id == "whois":
                results = self._whois_lookup(target)
            elif module_id == "port_scan":
                results = self._port_scan(target, options)
            elif module_id == "header_analysis":
                results = self._header_analysis(target)
            elif module_id == "tls_check":
                results = self._tls_check(target)
            elif module_id == "ssl_cert_info":
                results = self._tls_check(target)
            elif module_id in SCAN_CONTAINERS:
                results = self._docker_scan(module_id, target, options)
            else:
                results = self._run_argus_cli(module_id, target)
            status = "completed"
        except Exception as e:
            results = {"error": str(e)}
            status = "failed"

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    UPDATE security_recon_scans
                    SET results = %s, status = %s, completed_at = NOW()
                    WHERE id = %s
                """,
                    (Json(results), status, scan_id),
                )
        except Exception:
            pass

    def _dns_lookup(self, target: str) -> Dict:
        try:
            results = socket.getaddrinfo(target, None)
            ips = list(set(r[4][0] for r in results))
            return {"domain": target, "addresses": ips, "count": len(ips)}
        except Exception as e:
            return {"error": str(e)}

    def _reverse_dns(self, target: str) -> Dict:
        try:
            hostname = socket.gethostbyaddr(target)
            return {"ip": target, "hostname": hostname[0], "aliases": hostname[1]}
        except Exception as e:
            return {"error": str(e)}

    def _whois_lookup(self, target: str) -> Dict:
        try:
            import whois

            w = whois.whois(target)
            return {
                "domain": target,
                "registrar": str(w.registrar) if w.registrar else None,
                "creation_date": str(w.creation_date) if w.creation_date else None,
                "expiration_date": str(w.expiration_date) if w.expiration_date else None,
                "name_servers": list(w.name_servers) if w.name_servers else [],
            }
        except Exception as e:
            return {"error": str(e)}

    def _port_scan(self, target: str, options: dict) -> Dict:
        ports = options.get("ports", [22, 53, 80, 443, 3000, 5432, 8080, 8123, 8443])
        open_ports = []
        for port in ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((target, port))
                if result == 0:
                    open_ports.append(port)
                sock.close()
            except Exception:
                pass
        return {"target": target, "open_ports": open_ports, "scanned": len(ports)}

    def _header_analysis(self, target: str) -> Dict:
        url = target if target.startswith("http") else f"https://{target}"
        try:
            resp = requests.head(url, timeout=10, allow_redirects=True)
            security_headers = {
                "Strict-Transport-Security": resp.headers.get("Strict-Transport-Security"),
                "Content-Security-Policy": resp.headers.get("Content-Security-Policy"),
                "X-Content-Type-Options": resp.headers.get("X-Content-Type-Options"),
                "X-Frame-Options": resp.headers.get("X-Frame-Options"),
                "X-XSS-Protection": resp.headers.get("X-XSS-Protection"),
                "Referrer-Policy": resp.headers.get("Referrer-Policy"),
            }
            missing = [h for h, v in security_headers.items() if not v]
            return {
                "url": url,
                "status_code": resp.status_code,
                "headers": security_headers,
                "missing_headers": missing,
                "score": f"{(6 - len(missing))}/6",
            }
        except Exception as e:
            return {"error": str(e)}

    def _tls_check(self, target: str) -> Dict:
        try:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(socket.socket(), server_hostname=target) as s:
                s.settimeout(5)
                s.connect((target, 443))
                cert = s.getpeercert()
                return {
                    "domain": target,
                    "issuer": dict(x[0] for x in cert.get("issuer", [])),
                    "subject": dict(x[0] for x in cert.get("subject", [])),
                    "not_before": cert.get("notBefore"),
                    "not_after": cert.get("notAfter"),
                    "version": s.version(),
                    "cipher": s.cipher(),
                }
        except Exception as e:
            return {"error": str(e)}

    def _docker_scan(self, module_id: str, target: str, options: dict = None) -> Dict:
        """Run a scan via Docker container."""
        container = SCAN_CONTAINERS.get(module_id)
        if not container:
            return {"error": f"Unknown scan module: {module_id}"}

        options = options or {}
        # Hardening: validate the caller-supplied target before it reaches any
        # scanner argv (argument-injection + SSRF guard). Internal targets need
        # an explicit opt-in (confirm_internal / allow_internal).
        allow_internal = bool(options.get("allow_internal") or options.get("confirm_internal"))
        try:
            target = validate_target(target, allow_internal=allow_internal)
        except ScanInputError as exc:
            return {"error": f"invalid scan target: {exc}"}

        timeout = options.get("timeout", 300)

        try:
            if module_id == "nmap_scan":
                try:
                    ports = validate_ports(options.get("ports", "-F"))
                except ScanInputError as exc:
                    return {"error": f"invalid ports: {exc}"}
                # "--" ends option parsing so a target can never be read as a flag.
                cmd = ["docker", "exec", container, "nmap", "-sV", "--open", ports, "--", target]
            elif module_id == "nikto_scan":
                cmd = ["docker", "exec", container, "nikto", "-h", target, "-Format", "json", "-output", "/dev/stdout"]
            elif module_id == "nuclei_scan":
                try:
                    severity = validate_severity(options.get("severity", "medium,high,critical"))
                except ScanInputError as exc:
                    return {"error": f"invalid severity: {exc}"}
                cmd = ["docker", "exec", container, "nuclei", "-u", target, "-severity", severity, "-jsonl"]
            elif module_id == "zap_scan":
                # ZAP uses API — baseline scan. Target is validated above; URL-encode
                # it so it cannot break out of the querystring.
                from urllib.parse import quote as _quote

                enc_target = _quote(target, safe="")
                zap_url = "http://security_zap:8080"
                try:
                    resp = requests.get(f"{zap_url}/JSON/spider/action/scan/?url={enc_target}", timeout=30)
                    scan_id = resp.json().get("scan", "0")
                    # Wait for spider to complete (max 60s)
                    import time

                    for _ in range(60):
                        status = requests.get(f"{zap_url}/JSON/spider/view/status/?scanId={scan_id}", timeout=10).json()
                        if int(status.get("status", "0")) >= 100:
                            break
                        time.sleep(1)
                    # Get alerts
                    alerts = requests.get(f"{zap_url}/JSON/core/view/alerts/?baseurl={enc_target}", timeout=15).json()
                    return {"alerts": alerts.get("alerts", []), "scan_id": scan_id, "target": target}
                except Exception as e:
                    return {"error": f"ZAP scan failed: {str(e)}"}
            elif module_id == "testssl_scan":
                cmd = ["docker", "exec", container, "testssl.sh", "--jsonfile", "/dev/stdout", "--", target]
            else:
                return {"error": f"Unsupported scan: {module_id}"}

            if module_id != "zap_scan":
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                if result.returncode == 0 or result.stdout:
                    try:
                        return {"output": json.loads(result.stdout), "target": target}
                    except json.JSONDecodeError:
                        return {"raw_output": result.stdout[:5000], "target": target}
                return {"error": result.stderr[:1000] or "Scan returned no output"}

        except subprocess.TimeoutExpired:
            return {"error": f"Scan timed out after {timeout}s"}
        except Exception as e:
            return {"error": str(e)}

    def _run_argus_cli(self, module_id: str, target: str) -> Dict:
        try:
            result = subprocess.run(
                ["python3", "-m", "argus", "-m", module_id, "-t", target, "--json"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"raw_output": result.stdout}
            return {"error": result.stderr or "Scan failed"}
        except subprocess.TimeoutExpired:
            return {"error": "Scan timed out"}
        except Exception as e:
            return {"error": str(e)}

    def get_scan(self, scan_id: int) -> Optional[Dict]:
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute("SELECT * FROM security_recon_scans WHERE id = %s", (scan_id,))
                result = cur.fetchone()
                return dict(result) if result else None
        except Exception:
            return None

    def get_scan_history(self, limit: int = 50) -> List[Dict]:
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT id, module_name, target, status, started_at, completed_at, triggered_by
                    FROM security_recon_scans ORDER BY started_at DESC LIMIT %s
                """,
                    (limit,),
                )
                results = cur.fetchall()
                return [dict(r) for r in results]
        except Exception:
            return []

    def get_container_status(self) -> Dict[str, bool]:
        """Check which scanning containers are running."""
        status = {}
        for module_id, container in SCAN_CONTAINERS.items():
            try:
                result = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Running}}", container],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                status[module_id] = result.stdout.strip() == "true"
            except Exception:
                status[module_id] = False
        return status

    def get_module_count(self) -> int:
        """Count total available modules."""
        count = 0
        for category in CURATED_MODULES.values():
            count += len(category)
        return count

    def check_health(self) -> bool:
        """Check if at least some scanning capability is available."""
        containers = self.get_container_status()
        return any(containers.values()) or True  # Built-in Python modules always work
