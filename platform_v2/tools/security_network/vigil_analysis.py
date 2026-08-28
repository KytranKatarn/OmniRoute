"""
vigil_analysis.py -- V.I.G.I.L. AI-powered network security analysis.

Uses Bridge dispatch for LLM inference to classify threats,
profile device behavior, and generate security intelligence.
"""

import json
import logging
import re

from database import get_db_cursor

logger = logging.getLogger(__name__)

VIGIL_SYSTEM_PROMPT = """You are V.I.G.I.L. (Vigilant Intelligence for Governance, Integrity & Liability),
the AI Security Director for A.R.C.H.I.E. platform. You analyze network traffic patterns,
DNS queries, and device behavior to identify security threats, policy violations, and anomalies.

Your analysis should be:
- Concise and actionable
- Prioritized by severity (critical, high, medium, low)
- Include specific device IPs and domains
- Suggest remediation steps when threats are found
- Written in a professional security analyst tone

Respond in JSON format when requested."""


def _extract_json(text):
    """Extract a JSON object from LLM response text."""
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _dispatch_to_vigil(prompt):
    """Send a prompt to V.I.G.I.L. via DHQ dispatcher and return parsed JSON or raw text."""
    from tools.department_hq.services.department_dispatcher import dispatch_json

    result = dispatch_json(
        capability="security",
        prompt=prompt,
        module_id="security_network",
        system_prompt=VIGIL_SYSTEM_PROMPT,
    )
    response_text = result.get("response", "") if isinstance(result, dict) else str(result)
    parsed = _extract_json(response_text)
    if parsed:
        return parsed
    return {"raw_response": response_text[:1000]}


def analyze_device_behavior(device_ip):
    """Use LLM to analyze a device's network behavior and assess risk."""
    try:
        with get_db_cursor() as (conn, cur):
            # Top 30 domains for this device
            cur.execute(
                """
                SELECT domain, SUM(query_count) as queries, bool_or(blocked) as blocked
                FROM device_dns_history
                WHERE device_ip = %s AND hour_bucket >= NOW() - INTERVAL '7 days'
                GROUP BY domain ORDER BY queries DESC LIMIT 30
                """,
                (device_ip,),
            )
            domains = [dict(r) for r in cur.fetchall()]

            # Bandwidth
            cur.execute(
                """
                SELECT SUM(bytes_in) as download, SUM(bytes_out) as upload
                FROM network_traffic_stats
                WHERE device_ip = %s AND hour_bucket >= NOW() - INTERVAL '7 days'
                """,
                (device_ip,),
            )
            bw = cur.fetchone() or {"download": 0, "upload": 0}

        prompt = f"""Analyze this device's network behavior and provide a security assessment.

Device IP: {device_ip}
Bandwidth (7 days): Download {bw.get('download') or 0} bytes, Upload {bw.get('upload') or 0} bytes
Top domains visited (last 7 days):
{json.dumps(domains, indent=2, default=str)}

Respond in JSON:
{{
    "device_classification": "gaming_pc|work_laptop|phone|iot|server|unknown",
    "risk_level": "low|medium|high|critical",
    "risk_factors": ["list of specific concerns"],
    "behavior_summary": "one paragraph summary",
    "recommendations": ["list of suggested actions"]
}}"""

        return _dispatch_to_vigil(prompt)
    except Exception as e:
        logger.error("V.I.G.I.L. analysis failed for %s: %s", device_ip, e)
        return {"error": str(e)}


def generate_threat_report():
    """Generate a V.I.G.I.L. network threat assessment report."""
    try:
        with get_db_cursor() as (conn, cur):
            # Top blocked domains (potential threats)
            cur.execute(
                """
                SELECT domain, SUM(query_count) as queries, COUNT(DISTINCT device_ip) as devices
                FROM device_dns_history WHERE blocked = true
                AND hour_bucket >= NOW() - INTERVAL '24 hours'
                GROUP BY domain ORDER BY queries DESC LIMIT 20
                """
            )
            blocked = [dict(r) for r in cur.fetchall()]

            # Devices with most blocked queries
            cur.execute(
                """
                SELECT device_ip, SUM(query_count) as blocked_queries
                FROM device_dns_history WHERE blocked = true
                AND hour_bucket >= NOW() - INTERVAL '24 hours'
                GROUP BY device_ip ORDER BY blocked_queries DESC LIMIT 10
                """
            )
            noisy_devices = [dict(r) for r in cur.fetchall()]

            # Active device count
            cur.execute(
                """
                SELECT COUNT(DISTINCT device_ip) as active
                FROM network_traffic_stats
                WHERE hour_bucket >= NOW() - INTERVAL '24 hours'
                """
            )
            row = cur.fetchone()
            active_count = row["active"] if row else 0

        prompt = f"""Generate a concise network security threat assessment for the last 24 hours.

Active devices: {active_count}
Top blocked domains: {json.dumps(blocked, default=str)}
Noisiest devices (most blocked queries): {json.dumps(noisy_devices, default=str)}

Provide a threat assessment in JSON:
{{
    "overall_risk": "low|medium|high|critical",
    "summary": "2-3 sentence executive summary",
    "threats": [
        {{"severity": "...", "description": "...", "affected_devices": ["..."], "recommendation": "..."}}
    ],
    "positive_findings": ["things that look good"],
    "action_items": ["prioritized list of recommended actions"]
}}"""

        return _dispatch_to_vigil(prompt)
    except Exception as e:
        logger.error("V.I.G.I.L. threat report failed: %s", e)
        return {"error": str(e)}


def classify_unknown_device(device_ip):
    """For devices without a label, analyze traffic to classify what they are."""
    try:
        with get_db_cursor() as (conn, cur):
            # Top domains
            cur.execute(
                """
                SELECT domain, SUM(query_count) as queries
                FROM device_dns_history
                WHERE device_ip = %s AND hour_bucket >= NOW() - INTERVAL '7 days'
                GROUP BY domain ORDER BY queries DESC LIMIT 20
                """,
                (device_ip,),
            )
            domains = [dict(r) for r in cur.fetchall()]

            # Traffic pattern (hourly distribution)
            cur.execute(
                """
                SELECT EXTRACT(HOUR FROM hour_bucket)::int as hour,
                       SUM(bytes_in + bytes_out) as total_bytes
                FROM network_traffic_stats
                WHERE device_ip = %s AND hour_bucket >= NOW() - INTERVAL '7 days'
                GROUP BY hour ORDER BY hour
                """,
                (device_ip,),
            )
            hourly = [dict(r) for r in cur.fetchall()]

            # Total bandwidth
            cur.execute(
                """
                SELECT SUM(bytes_in) as download, SUM(bytes_out) as upload
                FROM network_traffic_stats
                WHERE device_ip = %s AND hour_bucket >= NOW() - INTERVAL '7 days'
                """,
                (device_ip,),
            )
            bw = cur.fetchone() or {"download": 0, "upload": 0}

        prompt = f"""Classify this unknown network device based on its traffic patterns.

Device IP: {device_ip}
Bandwidth (7 days): Download {bw.get('download') or 0} bytes, Upload {bw.get('upload') or 0} bytes
Top domains: {json.dumps(domains, default=str)}
Hourly traffic pattern: {json.dumps(hourly, default=str)}

Respond in JSON:
{{
    "device_type": "gaming_pc|work_laptop|phone|tablet|smart_tv|iot_sensor|printer|server|nas|camera|unknown",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation of classification logic",
    "suggested_label": "human-friendly device name suggestion",
    "os_guess": "Windows|macOS|Linux|iOS|Android|embedded|unknown"
}}"""

        return _dispatch_to_vigil(prompt)
    except Exception as e:
        logger.error("V.I.G.I.L. classify failed for %s: %s", device_ip, e)
        return {"error": str(e)}
