"""
Argus Reconnaissance Service
==============================
Wrapper for Argus CLI toolkit and direct Python recon capabilities.
Curated ~25 modules from Argus's 135 for home network security.
"""

import os
import json
import socket
import ssl
import subprocess
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime
import requests
import psycopg2
from psycopg2.extras import RealDictCursor, Json


def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD", ""),
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

    def get_module_count(self) -> int:
        return sum(len(mods) for mods in CURATED_MODULES.values())

    def start_scan(
        self, module_id: str, target: str, options: dict = None, triggered_by: str = "user"
    ) -> Optional[int]:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO security_recon_scans (module_name, target, options, status, triggered_by)
                VALUES (%s, %s, %s, 'running', %s) RETURNING id
            """,
                (module_id, target, Json(options or {}), triggered_by),
            )
            scan_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            conn.close()

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
            else:
                results = self._run_argus_cli(module_id, target)
            status = "completed"
        except Exception as e:
            results = {"error": str(e)}
            status = "failed"

        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE security_recon_scans
                SET results = %s, status = %s, completed_at = NOW()
                WHERE id = %s
            """,
                (Json(results), status, scan_id),
            )
            conn.commit()
            cur.close()
            conn.close()
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
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM security_recon_scans WHERE id = %s", (scan_id,))
            result = cur.fetchone()
            cur.close()
            conn.close()
            return dict(result) if result else None
        except Exception:
            return None

    def get_scan_history(self, limit: int = 50) -> List[Dict]:
        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, module_name, target, status, started_at, completed_at, triggered_by
                FROM security_recon_scans ORDER BY started_at DESC LIMIT %s
            """,
                (limit,),
            )
            results = cur.fetchall()
            cur.close()
            conn.close()
            return [dict(r) for r in results]
        except Exception:
            return []

    def check_health(self) -> bool:
        return True
