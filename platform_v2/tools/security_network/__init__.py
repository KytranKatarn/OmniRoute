"""
Security & Network Module
=========================
Security monitoring, network health, and system status dashboard.
"""

from flask import Blueprint

security_network_bp = Blueprint("security_network", __name__, url_prefix="/tools/security-network")

from . import routes  # noqa: E402

# Register station actions with Bridge dispatcher
try:
    from services.action_registry import register_station_actions

    register_station_actions(
        [
            {
                "action_key": "security_network.nmap_scan",
                "station_code": "SECURITY",
                "module_source": "security_network",
                "label": "NMAP SCAN",
                "description": "Port scan + service detection on target",
                "icon": "radar",
                "color_class": "red",
                "sort_order": 10,
                "endpoint_path": "/tools/security-network/api/recon/scan",
                "params_schema": [
                    {"key": "target", "label": "Target IP/Host", "type": "text", "required": True},
                    {"key": "module", "label": "Module", "type": "hidden", "default": "nmap_scan"},
                ],
                "creates_job": True,
                "job_type": "vulnerability_scan",
                "test_config": {
                    "capability": "security_analysis",
                    "prompt": "Analyze these nmap scan results for security risks and open ports that should be closed.",
                    "system_prompt": "You are a security analyst. List findings briefly with severity.",
                    "description": "Nmap port scan analysis",
                },
            },
            {
                "action_key": "security_network.nuclei_scan",
                "station_code": "SECURITY",
                "module_source": "security_network",
                "label": "NUCLEI SCAN",
                "description": "Template-based vulnerability scanner",
                "icon": "bug",
                "color_class": "red",
                "sort_order": 20,
                "endpoint_path": "/tools/security-network/api/recon/scan",
                "params_schema": [
                    {"key": "target", "label": "Target URL", "type": "text", "required": True},
                    {"key": "module", "label": "Module", "type": "hidden", "default": "nuclei_scan"},
                ],
                "creates_job": True,
                "job_type": "vulnerability_scan",
            },
            {
                "action_key": "security_network.ssl_check",
                "station_code": "SECURITY",
                "module_source": "security_network",
                "label": "SSL CHECK",
                "description": "SSL/TLS certificate and cipher analysis",
                "icon": "lock",
                "color_class": "green",
                "sort_order": 30,
                "endpoint_path": "/tools/security-network/api/recon/scan",
                "params_schema": [
                    {"key": "target", "label": "Domain", "type": "text", "required": True},
                    {"key": "module", "label": "Module", "type": "hidden", "default": "testssl_scan"},
                ],
                "creates_job": True,
                "job_type": "ssl_check",
            },
            {
                "action_key": "security_network.device_audit",
                "station_code": "SECURITY",
                "module_source": "security_network",
                "label": "DEVICE AUDIT",
                "description": "Discover and audit network devices",
                "icon": "wifi",
                "color_class": "cyan",
                "sort_order": 40,
                "endpoint_path": "/tools/security-network/api/devices/sync",
                "creates_job": True,
                "job_type": "device_audit",
            },
            {
                "action_key": "security_network.dns_report",
                "station_code": "SECURITY",
                "module_source": "security_network",
                "label": "DNS REPORT",
                "description": "Generate DNS activity report",
                "icon": "globe",
                "color_class": "blue",
                "sort_order": 50,
                "endpoint_path": "/tools/security-network/api/dns/adguard/stats",
                "creates_job": True,
                "job_type": "dns_report",
            },
            {
                "action_key": "security_network.ssh_audit",
                "station_code": "SECURITY",
                "module_source": "security_network",
                "label": "SSH AUDIT",
                "description": "Check SSH config and login attempts",
                "icon": "terminal",
                "color_class": "amber",
                "sort_order": 60,
                "creates_job": True,
                "job_type": "ssh_audit",
            },
        ]
    )
except Exception:
    pass  # Action registry may not be available during import
