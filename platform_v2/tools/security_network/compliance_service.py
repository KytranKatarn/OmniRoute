"""
Compliance Scanning Engine
==========================
Loads STIG rule packs, executes checks via host_command_client,
stores results in the compliance_* tables.
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime

from psycopg2.extras import Json

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Host command client (lazy import — module may not exist in all environments)
# ---------------------------------------------------------------------------
_host_client = None


def _get_host_client():
    global _host_client
    if _host_client is None:
        try:
            from tools.system_operations.host_command_client import (
                is_queue_available,
                submit_and_wait,
            )

            _host_client = {
                "available": is_queue_available,
                "run": submit_and_wait,
            }
        except ImportError:
            _host_client = {"available": lambda: False, "run": None}
    return _host_client


RULE_PACKS_DIR = os.path.join(os.path.dirname(__file__), "rule_packs")


# ============================================================================
# Rule Pack Loading
# ============================================================================


def load_rule_pack(pack_path):
    """Read a JSON rule pack file and upsert into compliance_rule_packs."""
    with open(pack_path, "r") as f:
        data = json.load(f)

    pack_id = data["pack_id"]
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO compliance_rule_packs
                (pack_id, name, version, source, total_rules, rules, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (pack_id) DO UPDATE SET
                name = EXCLUDED.name,
                version = EXCLUDED.version,
                source = EXCLUDED.source,
                total_rules = EXCLUDED.total_rules,
                rules = EXCLUDED.rules,
                updated_at = NOW()
            """,
            (
                pack_id,
                data["name"],
                data.get("version", "1.0"),
                data.get("source", "DISA"),
                len(data["rules"]),
                Json(data["rules"]),
            ),
        )
    logger.info("Loaded rule pack %s (%d rules)", pack_id, len(data["rules"]))
    return {"pack_id": pack_id, "rule_count": len(data["rules"])}


def load_all_packs():
    """Load every JSON file from the rule_packs/ directory."""
    results = []
    if not os.path.isdir(RULE_PACKS_DIR):
        logger.warning("Rule packs directory not found: %s", RULE_PACKS_DIR)
        return results
    for fname in sorted(os.listdir(RULE_PACKS_DIR)):
        if not fname.endswith(".json"):
            continue
        try:
            info = load_rule_pack(os.path.join(RULE_PACKS_DIR, fname))
            results.append(info)
        except Exception as exc:
            logger.error("Failed to load pack %s: %s", fname, exc)
            results.append({"file": fname, "error": str(exc)})
    return results


# ============================================================================
# Scanning
# ============================================================================


def run_scan(pack_ids=None, triggered_by="manual"):
    """Run a full compliance scan against loaded rule packs.

    Args:
        pack_ids: list of pack_id strings, or None for all packs
        triggered_by: 'manual' | 'scheduled' | 'agent_loop'

    Returns:
        dict with scan_id, score, counts, per-pack breakdown
    """
    scan_id = str(uuid.uuid4())
    started_at = datetime.utcnow()

    # Load rules from DB
    with get_db_cursor(commit=False) as (conn, cur):
        if pack_ids:
            cur.execute(
                "SELECT pack_id, name, rules FROM compliance_rule_packs WHERE pack_id = ANY(%s)",
                (pack_ids,),
            )
        else:
            cur.execute("SELECT pack_id, name, rules FROM compliance_rule_packs")
        packs = cur.fetchall()

    if not packs:
        return {"scan_id": scan_id, "error": "No rule packs loaded"}

    # Create scan record (pack_ids is text[] not jsonb)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO compliance_scans
                (scan_id, triggered_by, started_at, pack_ids)
            VALUES (%s, %s, %s, %s)
            """,
            (scan_id, triggered_by, started_at, [p["pack_id"] for p in packs]),
        )

    # Check host_command availability once
    hc = _get_host_client()
    host_available = hc["available"]()

    total = 0
    passed = 0
    failed = 0
    errors = 0
    pack_scores = {}

    for pack in packs:
        pack_id = pack["pack_id"]
        rules = pack["rules"] if isinstance(pack["rules"], list) else json.loads(pack["rules"])
        pack_pass = 0
        pack_total = 0

        for rule in rules:
            total += 1
            pack_total += 1
            rule_id = rule.get("rule_id", f"unknown-{total}")

            try:
                if not host_available:
                    result = {
                        "status": "error",
                        "actual": "",
                        "expected": rule.get("check", {}).get("expected", ""),
                        "details": "Host command queue unavailable — host_monitor.py may not be running",
                    }
                else:
                    result = _execute_check(rule.get("check", {}))
            except Exception as exc:
                logger.error("Check %s failed: %s", rule_id, exc)
                result = {
                    "status": "error",
                    "actual": "",
                    "expected": rule.get("check", {}).get("expected", ""),
                    "details": str(exc),
                }

            status = result.get("status", "error")
            if status == "pass":
                passed += 1
                pack_pass += 1
            elif status == "fail":
                failed += 1
            else:
                errors += 1

            # Store individual result
            try:
                soc2 = rule.get("soc2_mapping", [])
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """
                        INSERT INTO compliance_scan_results
                            (scan_id, pack_id, rule_id, severity, status,
                             actual_value, expected_value, details, soc2_controls)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            scan_id,
                            pack_id,
                            rule_id,
                            rule.get("severity", "medium"),
                            status,
                            result.get("actual", "")[:2000],
                            result.get("expected", "")[:2000],
                            result.get("details", ""),
                            soc2 if soc2 else None,
                        ),
                    )
            except Exception as exc:
                logger.error("Failed to store result for %s: %s", rule_id, exc)

        pack_scores[pack_id] = {
            "name": pack["name"],
            "passed": pack_pass,
            "total": pack_total,
            "score": round((pack_pass / pack_total) * 100, 1) if pack_total > 0 else 0,
        }

    # Calculate overall score
    score = round((passed / total) * 100, 1) if total > 0 else 0
    completed_at = datetime.utcnow()

    # Update scan record
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE compliance_scans SET
                completed_at = %s,
                total_rules = %s,
                passed = %s,
                failed = %s,
                errors = %s,
                score = %s
            WHERE scan_id = %s
            """,
            (
                completed_at,
                total,
                passed,
                failed,
                errors,
                score,
                scan_id,
            ),
        )

    duration_s = (completed_at - started_at).total_seconds()
    summary = {
        "scan_id": scan_id,
        "status": "completed",
        "score": score,
        "total": total,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "duration_seconds": round(duration_s, 2),
        "pack_scores": pack_scores,
    }
    logger.info(
        "Compliance scan %s complete: %.1f%% (%d/%d passed)",
        scan_id,
        score,
        passed,
        total,
    )
    return summary


# ============================================================================
# Check Dispatching
# ============================================================================

_CHECK_HANDLERS = {}


def _execute_check(check):
    """Dispatch to the appropriate check type handler."""
    check_type = check.get("type", "")
    handler = _CHECK_HANDLERS.get(check_type)
    if handler is None:
        return {
            "status": "error",
            "actual": "",
            "expected": check.get("expected", ""),
            "details": f"Unknown check type: {check_type}",
        }
    return handler(check)


def _register_check(check_type):
    """Decorator to register a check type handler."""

    def decorator(fn):
        _CHECK_HANDLERS[check_type] = fn
        return fn

    return decorator


def _run_host_cmd(command, timeout=30):
    """Run a shell command via host_command_client, return stdout string."""
    hc = _get_host_client()
    result = hc["run"]("shell_command", {"command": command}, timeout=timeout)
    if result.get("status") == "error":
        raise RuntimeError(result.get("error", "host command failed"))
    return result.get("output", result.get("stdout", "")).strip()


# ============================================================================
# Check Type Handlers
# ============================================================================


@_register_check("file_content")
def _check_file_content(check):
    """Read file, grep for pattern, compare to expected."""
    path = check.get("path", "")
    pattern = check.get("pattern", "")
    expected = check.get("expected", "")
    try:
        # Escape single quotes in pattern for shell
        safe_pattern = pattern.replace("'", "'\\''")
        output = _run_host_cmd(f"grep -E '{safe_pattern}' {path} 2>/dev/null || echo ''")
        actual = output.strip()
        if not actual:
            return {
                "status": "fail",
                "actual": "(not found)",
                "expected": expected,
                "details": f"Pattern '{pattern}' not found in {path}",
            }
        # Check if expected value is present in the matched line(s)
        if expected and expected in actual:
            return {"status": "pass", "actual": actual, "expected": expected, "details": ""}
        elif not expected:
            # Just checking pattern exists
            return {"status": "pass", "actual": actual, "expected": pattern, "details": ""}
        else:
            return {
                "status": "fail",
                "actual": actual,
                "expected": expected,
                "details": f"Pattern found but value mismatch",
            }
    except Exception as exc:
        return {"status": "error", "actual": "", "expected": expected, "details": str(exc)}


@_register_check("file_permission")
def _check_file_permission(check):
    """Check file owner/group/mode."""
    path = check.get("path", "")
    expected_mode = check.get("expected_mode", "")
    expected_owner = check.get("expected_owner", "")
    expected_group = check.get("expected_group", "")
    expected = check.get("expected", f"{expected_mode} {expected_owner} {expected_group}".strip())
    try:
        output = _run_host_cmd(f"stat -c '%a %U %G' {path} 2>/dev/null || echo 'NOT_FOUND'")
        if "NOT_FOUND" in output:
            return {
                "status": "fail",
                "actual": "file not found",
                "expected": expected,
                "details": f"{path} does not exist",
            }
        parts = output.split()
        mode = parts[0] if len(parts) > 0 else ""
        owner = parts[1] if len(parts) > 1 else ""
        group = parts[2] if len(parts) > 2 else ""

        ok = True
        issues = []
        if expected_mode and mode != expected_mode:
            ok = False
            issues.append(f"mode {mode} != {expected_mode}")
        if expected_owner and owner != expected_owner:
            ok = False
            issues.append(f"owner {owner} != {expected_owner}")
        if expected_group and group != expected_group:
            ok = False
            issues.append(f"group {group} != {expected_group}")

        return {
            "status": "pass" if ok else "fail",
            "actual": output,
            "expected": expected,
            "details": "; ".join(issues) if issues else "",
        }
    except Exception as exc:
        return {"status": "error", "actual": "", "expected": expected, "details": str(exc)}


@_register_check("file_exists")
def _check_file_exists(check):
    """Check if file exists."""
    path = check.get("path", "")
    should_exist = check.get("should_exist", True)
    expected = "exists" if should_exist else "missing"
    try:
        output = _run_host_cmd(f"test -f {path} && echo 'exists' || echo 'missing'")
        actual = output.strip()
        ok = (actual == "exists") == should_exist
        return {
            "status": "pass" if ok else "fail",
            "actual": actual,
            "expected": expected,
            "details": "",
        }
    except Exception as exc:
        return {"status": "error", "actual": "", "expected": expected, "details": str(exc)}


@_register_check("command_output")
def _check_command_output(check):
    """Run command, match output against pattern."""
    command = check.get("command", "")
    expected = check.get("expected", "")
    match_pattern = check.get("match_pattern", "")
    try:
        output = _run_host_cmd(command, timeout=check.get("timeout", 30))
        actual = output.strip()

        if match_pattern:
            ok = bool(re.search(match_pattern, actual))
        elif expected:
            ok = expected in actual
        else:
            ok = len(actual) > 0

        return {
            "status": "pass" if ok else "fail",
            "actual": actual[:500],
            "expected": expected or match_pattern,
            "details": "" if ok else "Output does not match expected pattern",
        }
    except Exception as exc:
        return {
            "status": "error",
            "actual": "",
            "expected": expected or match_pattern,
            "details": str(exc),
        }


@_register_check("service_status")
def _check_service_status(check):
    """Check systemd service state."""
    service = check.get("service", "")
    expected_enabled = check.get("expected_enabled", True)
    expected_active = check.get("expected_active", True)
    expected = check.get("expected", "enabled/active" if expected_enabled and expected_active else "")
    try:
        enabled = _run_host_cmd(f"systemctl is-enabled {service} 2>/dev/null || echo 'unknown'")
        active = _run_host_cmd(f"systemctl is-active {service} 2>/dev/null || echo 'unknown'")
        actual = f"{enabled}/{active}"

        ok = True
        issues = []
        if expected_enabled and enabled != "enabled":
            ok = False
            issues.append(f"not enabled ({enabled})")
        if not expected_enabled and enabled == "enabled":
            ok = False
            issues.append(f"should not be enabled")
        if expected_active and active != "active":
            ok = False
            issues.append(f"not active ({active})")
        if not expected_active and active == "active":
            ok = False
            issues.append(f"should not be active")

        return {
            "status": "pass" if ok else "fail",
            "actual": actual,
            "expected": expected,
            "details": "; ".join(issues) if issues else "",
        }
    except Exception as exc:
        return {"status": "error", "actual": "", "expected": expected, "details": str(exc)}


@_register_check("sysctl_value")
def _check_sysctl_value(check):
    """Read kernel parameter."""
    param = check.get("param", "")
    expected = check.get("expected", "")
    try:
        actual = _run_host_cmd(f"sysctl -n {param} 2>/dev/null || echo 'NOT_FOUND'")
        ok = actual.strip() == expected.strip()
        return {
            "status": "pass" if ok else "fail",
            "actual": actual.strip(),
            "expected": expected,
            "details": "" if ok else f"Kernel param {param} mismatch",
        }
    except Exception as exc:
        return {"status": "error", "actual": "", "expected": expected, "details": str(exc)}


@_register_check("package_installed")
def _check_package_installed(check):
    """Check if package is installed."""
    package = check.get("package", "")
    should_be_installed = check.get("should_be_installed", True)
    expected = "installed" if should_be_installed else "not installed"
    try:
        output = _run_host_cmd(f"dpkg-query -W -f='${{Status}}' {package} 2>/dev/null || echo 'not-installed'")
        is_installed = "install ok installed" in output
        ok = is_installed == should_be_installed
        return {
            "status": "pass" if ok else "fail",
            "actual": "installed" if is_installed else "not installed",
            "expected": expected,
            "details": "",
        }
    except Exception as exc:
        return {"status": "error", "actual": "", "expected": expected, "details": str(exc)}


@_register_check("docker_config")
def _check_docker_config(check):
    """Check Docker daemon.json or container config."""
    config_key = check.get("config_key", "")
    expected = check.get("expected", "")
    container = check.get("container", "")
    inspect_format = check.get("inspect_format", "")
    try:
        if container and inspect_format:
            actual = _run_host_cmd(
                f"docker inspect --format '{inspect_format}' {container} 2>/dev/null || echo 'NOT_FOUND'"
            )
        else:
            # Read daemon.json
            output = _run_host_cmd("cat /etc/docker/daemon.json 2>/dev/null || echo '{}'")
            try:
                daemon_cfg = json.loads(output)
            except json.JSONDecodeError:
                return {
                    "status": "error",
                    "actual": output[:200],
                    "expected": expected,
                    "details": "Failed to parse daemon.json",
                }
            actual = str(daemon_cfg.get(config_key, "(not set)"))

        ok = expected in actual if expected else actual != "(not set)"
        return {
            "status": "pass" if ok else "fail",
            "actual": actual[:500],
            "expected": expected,
            "details": "" if ok else f"Docker config mismatch for {config_key or container}",
        }
    except Exception as exc:
        return {"status": "error", "actual": "", "expected": expected, "details": str(exc)}


@_register_check("firewall_rule")
def _check_firewall_rule(check):
    """Check UFW rule exists."""
    pattern = check.get("pattern", "")
    expected = check.get("expected", "ALLOW")
    should_exist = check.get("should_exist", True)
    try:
        safe_pattern = pattern.replace("'", "'\\''")
        output = _run_host_cmd(f"ufw status verbose 2>/dev/null | grep -E '{safe_pattern}' || echo ''")
        actual = output.strip()
        found = len(actual) > 0

        ok = found == should_exist
        if found and expected:
            ok = ok and expected in actual

        return {
            "status": "pass" if ok else "fail",
            "actual": actual if actual else "(no matching rule)",
            "expected": f"{'Rule exists' if should_exist else 'No rule'}: {pattern}",
            "details": "",
        }
    except Exception as exc:
        return {"status": "error", "actual": "", "expected": expected, "details": str(exc)}


@_register_check("port_listening")
def _check_port_listening(check):
    """Check if port is listening (or not)."""
    port = check.get("port", "")
    should_listen = check.get("should_listen", True)
    expected = f"port {port} {'listening' if should_listen else 'not listening'}"
    try:
        output = _run_host_cmd(f"ss -tlnp 2>/dev/null | grep ':{port} ' || echo ''")
        actual = output.strip()
        is_listening = len(actual) > 0
        ok = is_listening == should_listen
        return {
            "status": "pass" if ok else "fail",
            "actual": actual if actual else f"port {port} not listening",
            "expected": expected,
            "details": "",
        }
    except Exception as exc:
        return {"status": "error", "actual": "", "expected": expected, "details": str(exc)}


# ============================================================================
# Fix Application
# ============================================================================


def apply_fix(scan_id, rule_id, user_id):
    """Look up rule fix definition from the rule pack and execute it via host_command.

    Returns dict with success status and details.
    """
    # Get the scan result + rule pack to find the fix definition
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT r.pack_id, r.actual_value, r.severity
            FROM compliance_scan_results r
            WHERE r.scan_id = %s AND r.rule_id = %s
            """,
            (scan_id, rule_id),
        )
        row = cur.fetchone()

    if not row:
        return {"success": False, "error": f"No result found for {scan_id}/{rule_id}"}

    pack_id = row["pack_id"]
    before_value = row.get("actual_value", "")

    # Look up fix from the rule pack JSON
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT rules FROM compliance_rule_packs WHERE pack_id = %s",
            (pack_id,),
        )
        pack_row = cur.fetchone()

    if not pack_row:
        return {"success": False, "error": f"Rule pack {pack_id} not found"}

    rules = pack_row["rules"] if isinstance(pack_row["rules"], list) else json.loads(pack_row["rules"])
    fix_def = None
    for rule in rules:
        if rule.get("rule_id") == rule_id:
            fix_def = rule.get("fix")
            break

    if not fix_def:
        return {"success": False, "error": "No fix definition for this rule"}

    hc = _get_host_client()
    if not hc["available"]():
        return {"success": False, "error": "Host command queue unavailable"}

    fix_type = fix_def.get("type", "")
    command_executed = ""

    try:
        if fix_type == "file_line":
            path = fix_def["path"]
            line = fix_def["line"]
            key = line.split()[0] if line.strip() else ""
            if key:
                command_executed = f"sed -i '/^{key}/d' {path} && echo '{line}' >> {path}"
            else:
                command_executed = f"echo '{line}' >> {path}"
            _run_host_cmd(command_executed)
            restart = fix_def.get("restart_service")
            if restart:
                _run_host_cmd(f"systemctl restart {restart}")
                command_executed += f" && systemctl restart {restart}"

        elif fix_type == "command":
            command_executed = fix_def.get("command", "")
            if not command_executed:
                return {"success": False, "error": "No command in fix definition"}
            _run_host_cmd(command_executed, timeout=60)

        elif fix_type == "sysctl":
            param = fix_def.get("param", "")
            value = fix_def.get("value", "")
            command_executed = f"sysctl -w {param}={value}"
            _run_host_cmd(command_executed)
            _run_host_cmd(
                f"grep -q '^{param}' /etc/sysctl.conf && "
                f"sed -i 's/^{param}.*/{param} = {value}/' /etc/sysctl.conf || "
                f"echo '{param} = {value}' >> /etc/sysctl.conf"
            )

        elif fix_type == "service":
            action = fix_def.get("action", "restart")
            service = fix_def.get("service", "")
            command_executed = f"systemctl {action} {service}"
            _run_host_cmd(command_executed)

        else:
            return {"success": False, "error": f"Unknown fix type: {fix_type}"}

        # Record successful remediation
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO compliance_remediations
                    (scan_id, rule_id, pack_id, action_type, command_executed,
                     result, risk_level, executed_by, before_value, executed_at)
                VALUES (%s, %s, %s, %s, %s, 'success', %s, %s, %s, NOW())
                """,
                (
                    scan_id,
                    rule_id,
                    pack_id,
                    fix_type,
                    command_executed,
                    fix_def.get("risk", "medium"),
                    user_id,
                    before_value,
                ),
            )

        return {
            "success": True,
            "fix_type": fix_type,
            "risk": fix_def.get("risk", "medium"),
        }

    except Exception as exc:
        logger.error("Fix failed for %s/%s: %s", scan_id, rule_id, exc)
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO compliance_remediations
                        (scan_id, rule_id, pack_id, action_type, command_executed,
                         result, risk_level, executed_by, before_value, executed_at)
                    VALUES (%s, %s, %s, %s, %s, 'failed', %s, %s, %s, NOW())
                    """,
                    (
                        scan_id,
                        rule_id,
                        pack_id,
                        fix_type,
                        command_executed,
                        fix_def.get("risk", "medium"),
                        user_id,
                        before_value,
                    ),
                )
        except Exception:
            pass
        return {"success": False, "error": str(exc)}


# ============================================================================
# Query Functions
# ============================================================================


def get_scan_results(scan_id, status=None, severity=None, pack_id=None):
    """Query scan results with optional filters."""
    query = "SELECT * FROM compliance_scan_results WHERE scan_id = %s"
    params = [scan_id]

    if status:
        query += " AND status = %s"
        params.append(status)
    if severity:
        query += " AND severity = %s"
        params.append(severity)
    if pack_id:
        query += " AND pack_id = %s"
        params.append(pack_id)

    query += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, rule_id"

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(query, params)
        return cur.fetchall()


def get_scan_history(limit=20):
    """Recent scans ordered by date."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT scan_id, triggered_by, started_at, completed_at,
                   total_rules, passed, failed, errors, score, pack_ids, node_id
            FROM compliance_scans
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        for row in rows:
            for key in ("started_at", "completed_at"):
                if row.get(key) and hasattr(row[key], "isoformat"):
                    row[key] = row[key].isoformat()
        return rows


def get_latest_scores():
    """Get the most recent completed scan's scores."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT scan_id, score, total_rules, passed, failed, errors,
                   started_at, completed_at, pack_ids
            FROM compliance_scans
            WHERE completed_at IS NOT NULL
            ORDER BY started_at DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        for key in ("started_at", "completed_at"):
            if row.get(key) and hasattr(row[key], "isoformat"):
                row[key] = row[key].isoformat()
        return row


def get_loaded_packs():
    """List all loaded rule packs."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT pack_id, name, version, source, total_rules, updated_at
            FROM compliance_rule_packs
            ORDER BY name
            """
        )
        rows = cur.fetchall()
        for row in rows:
            if row.get("updated_at") and hasattr(row["updated_at"], "isoformat"):
                row["updated_at"] = row["updated_at"].isoformat()
        return rows
