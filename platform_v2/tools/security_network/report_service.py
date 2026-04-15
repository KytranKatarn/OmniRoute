"""
Report Service for Security Scans
=================================
Generates PDF/HTML reports from security scan results.
"""

import os
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Any, List
from database import get_db_cursor

_BASE_DIR = os.getenv("ARCHIE_BASE_DIR", "/mnt/archie_brain")
SCANS_DIR = os.path.join(_BASE_DIR, "security_scans")
REPORTS_DIR = os.path.join(_BASE_DIR, "security_scans", "reports")


def ensure_reports_dir():
    """Ensure reports directory exists"""
    os.makedirs(REPORTS_DIR, exist_ok=True)


# ============================================================================
# SCAN PARSING
# ============================================================================


def parse_nmap_xml(filepath: str) -> Dict[str, Any]:
    """Parse nmap XML output"""
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()

        scan_info = {
            "scanner": "nmap",
            "args": root.get("args", ""),
            "start_time": root.get("startstr", ""),
            "hosts": [],
        }

        for host in root.findall(".//host"):
            host_info = {
                "status": (
                    host.find("status").get("state", "unknown") if host.find("status") is not None else "unknown"
                ),
                "addresses": [],
                "hostnames": [],
                "ports": [],
                "os": [],
            }

            # Addresses
            for addr in host.findall("address"):
                host_info["addresses"].append({"addr": addr.get("addr"), "type": addr.get("addrtype")})

            # Hostnames
            for hostname in host.findall(".//hostname"):
                host_info["hostnames"].append(hostname.get("name"))

            # Ports
            for port in host.findall(".//port"):
                port_info = {
                    "port": port.get("portid"),
                    "protocol": port.get("protocol"),
                    "state": (port.find("state").get("state") if port.find("state") is not None else "unknown"),
                    "service": {},
                }

                service = port.find("service")
                if service is not None:
                    port_info["service"] = {
                        "name": service.get("name", ""),
                        "product": service.get("product", ""),
                        "version": service.get("version", ""),
                    }

                # Scripts (vulnerabilities)
                for script in port.findall("script"):
                    if "vulnerabilities" not in port_info:
                        port_info["vulnerabilities"] = []
                    port_info["vulnerabilities"].append(
                        {
                            "id": script.get("id"),
                            "output": script.get("output", "")[:500],
                        }  # Truncate
                    )

                host_info["ports"].append(port_info)

            # OS detection
            for osmatch in host.findall(".//osmatch"):
                host_info["os"].append({"name": osmatch.get("name"), "accuracy": osmatch.get("accuracy")})

            scan_info["hosts"].append(host_info)

        return scan_info
    except Exception as e:
        return {"error": str(e), "scanner": "nmap"}


def parse_nikto_json(filepath: str) -> Dict[str, Any]:
    """Parse nikto JSON output"""
    try:
        with open(filepath, "r") as f:
            data = json.load(f)

        return {
            "scanner": "nikto",
            "target": data.get("host", ""),
            "ip": data.get("ip", ""),
            "port": data.get("port", ""),
            "vulnerabilities": data.get("vulnerabilities", []),
        }
    except Exception as e:
        return {"error": str(e), "scanner": "nikto"}


def parse_nuclei_json(filepath: str) -> Dict[str, Any]:
    """Parse nuclei JSON output (newline-delimited JSON)"""
    try:
        findings = []
        with open(filepath, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        finding = json.loads(line)
                        findings.append(
                            {
                                "template_id": finding.get("template-id", ""),
                                "name": finding.get("info", {}).get("name", ""),
                                "severity": finding.get("info", {}).get("severity", "info"),
                                "type": finding.get("type", ""),
                                "host": finding.get("host", ""),
                                "matched_at": finding.get("matched-at", ""),
                                "description": finding.get("info", {}).get("description", ""),
                            }
                        )
                    except json.JSONDecodeError:
                        continue

        return {
            "scanner": "nuclei",
            "findings": findings,
            "counts": {
                "critical": len([f for f in findings if f["severity"] == "critical"]),
                "high": len([f for f in findings if f["severity"] == "high"]),
                "medium": len([f for f in findings if f["severity"] == "medium"]),
                "low": len([f for f in findings if f["severity"] == "low"]),
                "info": len([f for f in findings if f["severity"] == "info"]),
            },
        }
    except Exception as e:
        return {"error": str(e), "scanner": "nuclei"}


def parse_ssl_json(filepath: str) -> Dict[str, Any]:
    """Parse testssl JSON output"""
    try:
        with open(filepath, "r") as f:
            data = json.load(f)

        # testssl outputs an array of findings
        findings = []
        vulnerabilities = []

        for item in data if isinstance(data, list) else [data]:
            if item.get("severity") in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
                vulnerabilities.append(
                    {
                        "id": item.get("id", ""),
                        "severity": item.get("severity", "").lower(),
                        "finding": item.get("finding", ""),
                    }
                )
            else:
                findings.append(
                    {
                        "id": item.get("id", ""),
                        "finding": item.get("finding", ""),
                        "severity": item.get("severity", "info"),
                    }
                )

        return {
            "scanner": "testssl",
            "findings": findings,
            "vulnerabilities": vulnerabilities,
        }
    except Exception as e:
        return {"error": str(e), "scanner": "testssl"}


def parse_scan_file(filepath: str) -> Dict[str, Any]:
    """Parse scan file based on extension and content"""
    filename = os.path.basename(filepath)

    if filename.startswith("nmap_") and filepath.endswith(".xml"):
        return parse_nmap_xml(filepath)
    elif filename.startswith("nikto_") and filepath.endswith(".json"):
        return parse_nikto_json(filepath)
    elif filename.startswith("nuclei_") and filepath.endswith(".json"):
        return parse_nuclei_json(filepath)
    elif filename.startswith("ssl_") and filepath.endswith(".json"):
        return parse_ssl_json(filepath)
    else:
        return {"error": "Unknown scan type", "filename": filename}


# ============================================================================
# REPORT GENERATION
# ============================================================================


def generate_html_report(scan_data: Dict[str, Any], title: str = "Security Scan Report") -> str:
    """Generate HTML report from scan data"""
    scanner = scan_data.get("scanner", "unknown")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px; margin: 0 auto; padding: 20px;
            background: #0a0f1a; color: #e0e0e0;
        }}
        h1 {{ color: #00d4aa; border-bottom: 2px solid #00d4aa; padding-bottom: 10px; }}
        h2 {{ color: #00bcd4; margin-top: 30px; }}
        h3 {{ color: #4dd0e1; }}
        .meta {{ background: #1a1f2e; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
        .meta p {{ margin: 5px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #2a3f5f; }}
        th {{ background: #1a2744; color: #00d4aa; }}
        tr:hover {{ background: #1a2744; }}
        .severity-critical {{ color: #ff1744; font-weight: bold; }}
        .severity-high {{ color: #ff6b6b; }}
        .severity-medium {{ color: #ffa726; }}
        .severity-low {{ color: #66bb6a; }}
        .severity-info {{ color: #42a5f5; }}
        .host {{
            background: #1a2744; padding: 15px; border-radius: 8px;
            margin: 15px 0; border-left: 4px solid #00d4aa;
        }}
        .port-open {{ color: #66bb6a; }}
        .port-closed {{ color: #ff6b6b; }}
        .summary {{
            display: grid; grid-template-columns: repeat(5, 1fr);
            gap: 15px; margin: 20px 0;
        }}
        .summary-card {{ background: #1a2744; padding: 20px; text-align: center; border-radius: 8px; }}
        .summary-card h3 {{ margin: 0 0 10px 0; font-size: 14px; text-transform: uppercase; }}
        .summary-card .count {{ font-size: 32px; font-weight: bold; }}
        .finding {{
            background: #1a1f2e; padding: 15px; margin: 10px 0;
            border-radius: 8px; border-left: 4px solid #4dd0e1;
        }}
        code {{ background: #0d1117; padding: 2px 6px; border-radius: 4px; font-family: monospace; }}
        .timestamp {{ color: #7f8c8d; font-size: 14px; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div class="meta">
        <p><strong>Scanner:</strong> {scanner.upper()}</p>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
"""

    if scanner == "nmap":
        html += f"""
        <p><strong>Command:</strong> <code>{scan_data.get('args', 'N/A')}</code></p>
        <p><strong>Start Time:</strong> {scan_data.get('start_time', 'N/A')}</p>
    </div>

    <h2>Discovered Hosts</h2>
"""
        for host in scan_data.get("hosts", []):
            addresses = ", ".join([a["addr"] for a in host.get("addresses", [])])
            hostnames = ", ".join(host.get("hostnames", [])) or "N/A"

            html += f"""
    <div class="host">
        <h3>{addresses}</h3>
        <p><strong>Status:</strong> {host.get('status', 'unknown')}</p>
        <p><strong>Hostnames:</strong> {hostnames}</p>
"""
            if host.get("os"):
                os_name = host["os"][0].get("name", "Unknown")
                os_acc = host["os"][0].get("accuracy", "?")
                html += f"<p><strong>OS:</strong> {os_name} ({os_acc}%)</p>"

            if host.get("ports"):
                html += """
        <h4>Open Ports</h4>
        <table>
            <tr><th>Port</th><th>Protocol</th><th>State</th><th>Service</th><th>Version</th></tr>
"""
                for port in host["ports"]:
                    state_class = "port-open" if port["state"] == "open" else "port-closed"
                    service = port.get("service", {})
                    html += f"""
            <tr>
                <td>{port['port']}</td>
                <td>{port['protocol']}</td>
                <td class="{state_class}">{port['state']}</td>
                <td>{service.get('name', '')}</td>
                <td>{service.get('product', '')} {service.get('version', '')}</td>
            </tr>"""

                    if port.get("vulnerabilities"):
                        for vuln in port["vulnerabilities"]:
                            html += f"""
            <tr>
                <td colspan="5" style="background: #2a1a1a; border-left: 4px solid #ff6b6b; padding-left: 20px;">
                    <strong class="severity-high">{vuln['id']}</strong><br>
                    <small>{vuln['output'][:300]}...</small>
                </td>
            </tr>"""

                html += "</table>"
            html += "</div>"

    elif scanner == "nuclei":
        counts = scan_data.get("counts", {})
        html += (
            """
    </div>

    <h2>Vulnerability Summary</h2>
    <div class="summary">
        <div class="summary-card" style="border-top: 4px solid #ff1744;">
            <h3>Critical</h3>
            <div class="count severity-critical">"""
            + str(counts.get("critical", 0))
            + """</div>
        </div>
        <div class="summary-card" style="border-top: 4px solid #ff6b6b;">
            <h3>High</h3>
            <div class="count severity-high">"""
            + str(counts.get("high", 0))
            + """</div>
        </div>
        <div class="summary-card" style="border-top: 4px solid #ffa726;">
            <h3>Medium</h3>
            <div class="count severity-medium">"""
            + str(counts.get("medium", 0))
            + """</div>
        </div>
        <div class="summary-card" style="border-top: 4px solid #66bb6a;">
            <h3>Low</h3>
            <div class="count severity-low">"""
            + str(counts.get("low", 0))
            + """</div>
        </div>
        <div class="summary-card" style="border-top: 4px solid #42a5f5;">
            <h3>Info</h3>
            <div class="count severity-info">"""
            + str(counts.get("info", 0))
            + """</div>
        </div>
    </div>

    <h2>Findings</h2>
"""
        )
        for finding in scan_data.get("findings", []):
            severity = finding.get("severity", "info")
            html += f"""
    <div class="finding" style="border-left-color: {'#ff1744' if severity == 'critical' else '#ff6b6b' if severity == 'high' else '#ffa726' if severity == 'medium' else '#66bb6a' if severity == 'low' else '#42a5f5'};">
        <h4><span class="severity-{severity}">[{severity.upper()}]</span> {finding.get('name', 'Unknown')}</h4>
        <p><strong>Template:</strong> <code>{finding.get('template_id', '')}</code></p>
        <p><strong>Host:</strong> {finding.get('host', '')}</p>
        <p><strong>Matched At:</strong> <code>{finding.get('matched_at', '')}</code></p>
        {f"<p>{finding.get('description', '')}</p>" if finding.get('description') else ''}
    </div>
"""

    elif scanner == "testssl":
        html += """
    </div>

    <h2>SSL/TLS Analysis</h2>
"""
        if scan_data.get("vulnerabilities"):
            html += "<h3>Vulnerabilities</h3>"
            for vuln in scan_data["vulnerabilities"]:
                severity = vuln.get("severity", "info")
                sev_colors = {
                    "critical": "#ff1744",
                    "high": "#ff6b6b",
                    "medium": "#ffa726",
                }
                border_color = sev_colors.get(severity, "#66bb6a")
                html += f"""
    <div class="finding" style="border-left-color: {border_color};">
        <h4><span class="severity-{severity}">[{severity.upper()}]</span> {vuln.get('id', '')}</h4>
        <p>{vuln.get('finding', '')}</p>
    </div>
"""

        if scan_data.get("findings"):
            html += "<h3>Certificate & Protocol Details</h3><table><tr><th>Check</th><th>Result</th></tr>"
            for finding in scan_data["findings"][:30]:  # Limit
                html += f"<tr><td>{finding.get('id', '')}</td><td>{finding.get('finding', '')}</td></tr>"
            html += "</table>"

    else:
        html += f"""
    </div>
    <pre>{json.dumps(scan_data, indent=2, default=str)}</pre>
"""

    html += """
    <div class="meta" style="margin-top: 40px;">
        <p class="timestamp">Generated by A.R.C.H.I.E. Security Module</p>
    </div>
</body>
</html>"""

    return html


def generate_scan_report(scan_filename: str) -> Dict[str, Any]:
    """Generate report for a single scan"""
    ensure_reports_dir()

    filepath = os.path.join(SCANS_DIR, scan_filename)
    if not os.path.exists(filepath):
        return {"success": False, "error": "Scan file not found"}

    try:
        # Parse the scan
        scan_data = parse_scan_file(filepath)

        if scan_data.get("error"):
            return {"success": False, "error": scan_data["error"]}

        # Generate HTML report
        report_name = scan_filename.rsplit(".", 1)[0] + "_report.html"
        report_path = os.path.join(REPORTS_DIR, report_name)

        html = generate_html_report(
            scan_data,
            f"Security Scan Report - {scan_data.get('scanner', 'Unknown').upper()}",
        )

        with open(report_path, "w") as f:
            f.write(html)

        return {
            "success": True,
            "report_file": report_name,
            "report_path": report_path,
            "scan_data": scan_data,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_assessment_report(
    scan_filenames: List[str],
    client_name: str = "Assessment",
    assessment_name: str = "Security Assessment",
) -> Dict[str, Any]:
    """Generate combined assessment report from multiple scans"""
    ensure_reports_dir()

    all_scan_data = []
    total_findings = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

    for filename in scan_filenames:
        filepath = os.path.join(SCANS_DIR, filename)
        if os.path.exists(filepath):
            scan_data = parse_scan_file(filepath)
            scan_data["filename"] = filename
            all_scan_data.append(scan_data)

            # Aggregate counts
            if scan_data.get("counts"):
                for sev in total_findings:
                    total_findings[sev] += scan_data["counts"].get(sev, 0)

    if not all_scan_data:
        return {"success": False, "error": "No valid scan files found"}

    # Generate combined report
    report_name = f"assessment_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    report_path = os.path.join(REPORTS_DIR, report_name)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{assessment_name} - {client_name}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px; margin: 0 auto; padding: 20px;
            background: #0a0f1a; color: #e0e0e0;
        }}
        h1 {{ color: #00d4aa; border-bottom: 2px solid #00d4aa; padding-bottom: 10px; }}
        h2 {{ color: #00bcd4; margin-top: 30px; }}
        .meta {{ background: #1a1f2e; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
        .summary {{
            display: grid; grid-template-columns: repeat(5, 1fr);
            gap: 15px; margin: 20px 0;
        }}
        .summary-card {{ background: #1a2744; padding: 20px; text-align: center; border-radius: 8px; }}
        .summary-card h3 {{ margin: 0 0 10px 0; font-size: 14px; color: #7f8c8d; }}
        .summary-card .count {{ font-size: 32px; font-weight: bold; }}
        .severity-critical {{ color: #ff1744; }}
        .severity-high {{ color: #ff6b6b; }}
        .severity-medium {{ color: #ffa726; }}
        .severity-low {{ color: #66bb6a; }}
        .severity-info {{ color: #42a5f5; }}
        .scan-section {{ background: #1a1f2e; padding: 20px; border-radius: 8px; margin: 20px 0; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #2a3f5f; }}
        th {{ background: #1a2744; color: #00d4aa; }}
    </style>
</head>
<body>
    <h1>{assessment_name}</h1>
    <div class="meta">
        <p><strong>Client:</strong> {client_name}</p>
        <p><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>Scans Included:</strong> {len(all_scan_data)}</p>
    </div>

    <h2>Executive Summary</h2>
    <div class="summary">
        <div class="summary-card" style="border-top: 4px solid #ff1744;">
            <h3>Critical</h3>
            <div class="count severity-critical">{total_findings['critical']}</div>
        </div>
        <div class="summary-card" style="border-top: 4px solid #ff6b6b;">
            <h3>High</h3>
            <div class="count severity-high">{total_findings['high']}</div>
        </div>
        <div class="summary-card" style="border-top: 4px solid #ffa726;">
            <h3>Medium</h3>
            <div class="count severity-medium">{total_findings['medium']}</div>
        </div>
        <div class="summary-card" style="border-top: 4px solid #66bb6a;">
            <h3>Low</h3>
            <div class="count severity-low">{total_findings['low']}</div>
        </div>
        <div class="summary-card" style="border-top: 4px solid #42a5f5;">
            <h3>Info</h3>
            <div class="count severity-info">{total_findings['info']}</div>
        </div>
    </div>

    <h2>Included Scans</h2>
    <table>
        <tr><th>Scan</th><th>Scanner</th><th>Summary</th></tr>
"""

    for scan in all_scan_data:
        summary = ""
        if scan.get("scanner") == "nmap":
            host_count = len(scan.get("hosts", []))
            summary = f"{host_count} host(s) discovered"
        elif scan.get("scanner") == "nuclei":
            counts = scan.get("counts", {})
            summary = f"C:{counts.get('critical', 0)} H:{counts.get('high', 0)} M:{counts.get('medium', 0)}"
        elif scan.get("scanner") == "testssl":
            vuln_count = len(scan.get("vulnerabilities", []))
            summary = f"{vuln_count} SSL issue(s)"

        html += f"""
        <tr>
            <td>{scan.get('filename', 'Unknown')}</td>
            <td>{scan.get('scanner', 'Unknown').upper()}</td>
            <td>{summary}</td>
        </tr>
"""

    html += """
    </table>

    <div class="meta" style="margin-top: 40px;">
        <p>Generated by A.R.C.H.I.E. Security Module</p>
    </div>
</body>
</html>"""

    try:
        with open(report_path, "w") as f:
            f.write(html)

        return {
            "success": True,
            "report_file": report_name,
            "report_path": report_path,
            "scans_included": len(all_scan_data),
            "total_findings": total_findings,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def export_vulnerabilities(scan_filename: str, format: str = "json") -> Dict[str, Any]:
    """Export vulnerabilities from a scan in various formats"""
    filepath = os.path.join(SCANS_DIR, scan_filename)
    if not os.path.exists(filepath):
        return {"success": False, "error": "Scan file not found"}

    try:
        scan_data = parse_scan_file(filepath)

        # Extract vulnerabilities based on scanner type
        vulns = []

        if scan_data.get("scanner") == "nuclei":
            for finding in scan_data.get("findings", []):
                vulns.append(
                    {
                        "id": finding.get("template_id", ""),
                        "title": finding.get("name", ""),
                        "severity": finding.get("severity", "info"),
                        "host": finding.get("host", ""),
                        "description": finding.get("description", ""),
                    }
                )

        elif scan_data.get("scanner") == "nmap":
            for host in scan_data.get("hosts", []):
                for port in host.get("ports", []):
                    for vuln in port.get("vulnerabilities", []):
                        vulns.append(
                            {
                                "id": vuln.get("id", ""),
                                "title": vuln.get("id", ""),
                                "severity": "medium",
                                "host": host.get("addresses", [{}])[0].get("addr", ""),
                                "port": port.get("port", ""),
                                "description": vuln.get("output", ""),
                            }
                        )

        elif scan_data.get("scanner") == "testssl":
            for vuln in scan_data.get("vulnerabilities", []):
                vulns.append(
                    {
                        "id": vuln.get("id", ""),
                        "title": vuln.get("id", ""),
                        "severity": vuln.get("severity", "info"),
                        "description": vuln.get("finding", ""),
                    }
                )

        if format == "json":
            return {"success": True, "vulnerabilities": vulns, "format": "json"}

        elif format == "csv":
            import csv
            import io

            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=["id", "title", "severity", "host", "description"])
            writer.writeheader()
            for vuln in vulns:
                writer.writerow(vuln)

            return {"success": True, "csv": output.getvalue(), "format": "csv"}

        else:
            return {"success": False, "error": f"Unknown format: {format}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


def list_reports() -> List[Dict[str, Any]]:
    """List all generated reports"""
    ensure_reports_dir()

    reports = []
    try:
        for filename in os.listdir(REPORTS_DIR):
            if filename.endswith(".html"):
                filepath = os.path.join(REPORTS_DIR, filename)
                stat = os.stat(filepath)
                reports.append(
                    {
                        "filename": filename,
                        "size": stat.st_size,
                        "created_at": stat.st_mtime,
                    }
                )

        reports.sort(key=lambda x: x["created_at"], reverse=True)
        return reports
    except Exception:
        return []


# ============================================================================
# DAILY NOC REPORTS (network traffic + DNS aggregation)
# ============================================================================


class ReportService:
    """Generates and stores daily network usage reports in network_daily_reports."""

    SERVICE_PATTERNS = {
        "Netflix": ["netflix", "nflx"],
        "YouTube": ["youtube", "googlevideo", "ytimg"],
        "Disney+": ["disney", "bamgrid", "dssott"],
        "Amazon Video": ["primevideo", "amazonvideo"],
        "Twitch": ["twitch", "jtvnw"],
        "Spotify": ["spotify", "scdn"],
        "TikTok": ["tiktok", "tiktokcdn"],
        "Instagram": ["instagram", "cdninstagram"],
        "Facebook": ["facebook", "fbcdn"],
        "Gaming": ["epicgames", "steampowered", "playstation", "xbox.com"],
        "Porn": ["pornhub", "xvideos", "xhamster", "xnxx", "redtube", "youporn", "onlyfans"],
    }

    def _detect_services_for_client(self, client_ip, ag):
        """Query AdGuard log for a client and detect streaming services."""
        ql = ag.get_query_log(limit=1000, search=client_ip) or {}
        entries = ql.get("data", [])
        services = {}
        for e in entries:
            domain = e.get("question", {}).get("name", "").lower()
            for svc, patterns in self.SERVICE_PATTERNS.items():
                if any(p in domain for p in patterns):
                    services[svc] = services.get(svc, 0) + 1
        return services

    def generate_daily_device_report(self, report_date=None):
        """Generate a daily per-device DNS activity report from AdGuard + DB data."""
        from datetime import date as _date

        if report_date is None:
            report_date = _date.today()
        elif isinstance(report_date, str):
            report_date = datetime.strptime(report_date, "%Y-%m-%d").date()

        data: Dict[str, Any] = {"report_date": str(report_date), "devices": []}

        # Pull per-client DNS stats from AdGuard
        try:
            from .adguard_service import AdGuardService

            ag = AdGuardService()
            stats = ag.get_stats() or {}

            # Top clients with query counts
            clients = []
            for client in stats.get("top_clients", []):
                for ip, count in client.items():
                    clients.append({"device_ip": ip, "dns_queries": count})

            # Top queried domains (for the report)
            top_domains = []
            for domain in stats.get("top_queried_domains", [])[:20]:
                for name, count in domain.items():
                    top_domains.append({"domain": name, "queries": count})

            # Top blocked domains
            top_blocked = []
            for domain in stats.get("top_blocked_domains", [])[:20]:
                for name, count in domain.items():
                    top_blocked.append({"domain": name, "blocked": count})

            data["top_queried_domains"] = top_domains
            data["top_blocked_domains"] = top_blocked
            data["total_dns_queries"] = stats.get("num_dns_queries", 0)
            data["total_blocked"] = stats.get("num_blocked_filtering", 0)

            # Enrich clients with device info from DB
            try:
                with get_db_cursor() as (conn, cur):
                    for client in clients:
                        ip = client["device_ip"]
                        cur.execute(
                            """SELECT nd.mac_address, nd.hostname, nd.friendly_name,
                                      nd.manufacturer, ndu.user_name, ndu.device_label
                               FROM network_devices nd
                               LEFT JOIN network_device_users ndu ON ndu.mac_address = nd.mac_address
                               WHERE nd.ip_address = %s LIMIT 1""",
                            (ip,),
                        )
                        row = cur.fetchone()
                        if row:
                            client["mac_address"] = row["mac_address"]
                            client["hostname"] = row["hostname"]
                            client["friendly_name"] = row["friendly_name"]
                            client["manufacturer"] = row["manufacturer"]
                            client["user_name"] = row["user_name"]
                            client["device_label"] = row["device_label"]
                        # Detect streaming services for this client
                        client["services"] = self._detect_services_for_client(ip, ag)
                        data["devices"].append(client)
            except Exception:
                data["devices"] = clients
        except Exception as exc:
            data["error"] = str(exc)

        data["total_devices"] = len(data["devices"])
        return self._store_report(report_date, "daily_device", data)

    def generate_daily_user_report(self, report_date=None):
        """Generate a daily per-user DNS activity report grouped by assigned user."""
        from datetime import date as _date

        if report_date is None:
            report_date = _date.today()
        elif isinstance(report_date, str):
            report_date = datetime.strptime(report_date, "%Y-%m-%d").date()

        data: Dict[str, Any] = {"report_date": str(report_date), "users": []}

        try:
            from .adguard_service import AdGuardService

            ag = AdGuardService()
            stats = ag.get_stats() or {}

            # Get per-client DNS data
            client_queries = {}
            for client in stats.get("top_clients", []):
                for ip, count in client.items():
                    client_queries[ip] = count

            # Group by user from device_users table
            user_map = {}  # user_name -> {queries, devices}
            try:
                with get_db_cursor() as (conn, cur):
                    cur.execute(
                        """SELECT ndu.user_name, nd.ip_address, ndu.device_label
                           FROM network_device_users ndu
                           JOIN network_devices nd ON nd.mac_address = ndu.mac_address
                           WHERE nd.ip_address IS NOT NULL"""
                    )
                    for row in cur.fetchall():
                        user, ip, label = row[0], row[1], row[2]
                        if user not in user_map:
                            user_map[user] = {"dns_queries": 0, "devices": [], "device_count": 0}
                        queries = client_queries.pop(ip, 0)
                        user_map[user]["dns_queries"] += queries
                        user_map[user]["devices"].append({"ip": ip, "label": label, "queries": queries})
                        user_map[user]["device_count"] += 1
            except Exception:
                pass

            # Remaining unassigned clients
            if client_queries:
                unassigned = {"dns_queries": 0, "devices": [], "device_count": 0}
                for ip, count in client_queries.items():
                    unassigned["dns_queries"] += count
                    unassigned["devices"].append({"ip": ip, "label": "", "queries": count})
                    unassigned["device_count"] += 1
                user_map["Unassigned"] = unassigned

            for user_name, info in sorted(user_map.items(), key=lambda x: -x[1]["dns_queries"]):
                data["users"].append({"user_name": user_name, **info})

            data["total_dns_queries"] = stats.get("num_dns_queries", 0)
            data["total_blocked"] = stats.get("num_blocked_filtering", 0)
        except Exception as exc:
            data["error"] = str(exc)

        data["total_users"] = len(data["users"])
        return self._store_report(report_date, "daily_user", data)

    def _store_report(self, report_date, report_type, data):
        """Store a report into network_daily_reports and return the full data."""
        import json as _json
        import psycopg2.extras

        try:
            clean = _json.loads(_json.dumps(data, default=str))
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """INSERT INTO network_daily_reports
                       (report_date, report_type, data_json, created_at)
                       VALUES (%s, %s, %s, NOW())
                       RETURNING id""",
                    (str(report_date), report_type, psycopg2.extras.Json(clean)),
                )
                row = cur.fetchone()
                data["report_id"] = row["id"] if isinstance(row, dict) else row[0]
        except Exception as exc:
            import logging
            import traceback

            logging.getLogger(__name__).error("_store_report failed: %s\n%s", exc, traceback.format_exc())
            data["store_error"] = repr(exc)

        return data

    def get_reports(self, report_type=None, limit=50):
        """List stored daily reports (metadata only)."""
        try:
            with get_db_cursor() as (conn, cur):
                if report_type:
                    cur.execute(
                        """SELECT id, report_date, report_type, created_at
                           FROM network_daily_reports
                           WHERE report_type = %s
                           ORDER BY report_date DESC LIMIT %s""",
                        (report_type, limit),
                    )
                else:
                    cur.execute(
                        """SELECT id, report_date, report_type, created_at
                           FROM network_daily_reports
                           ORDER BY report_date DESC LIMIT %s""",
                        (limit,),
                    )
                rows = cur.fetchall()
                return [
                    {
                        "id": r["id"],
                        "report_date": str(r["report_date"]) if r["report_date"] else None,
                        "report_type": r["report_type"],
                        "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                    }
                    for r in rows
                ]
        except Exception:
            return []

    def get_report_detail(self, report_id):
        """Fetch a single report by ID including full data payload."""
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    SELECT id, report_date, report_type, data_json, created_at
                    FROM network_daily_reports WHERE id = %s
                    """,
                    (report_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row["id"],
                    "report_date": str(row["report_date"]) if row["report_date"] else None,
                    "report_type": row["report_type"],
                    "data": row["data_json"],
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                }
        except Exception:
            return None
