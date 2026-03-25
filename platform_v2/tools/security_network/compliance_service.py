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
    _clear_file_cache()

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
                # Always try the check — handlers now try direct methods first,
                # only falling back to host_command queue if needed
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


import time as _time

# Cache for host file reads — avoids re-reading /etc/ssh/sshd_config 10 times
_file_cache = {}


def _clear_file_cache():
    """Clear file cache between scans."""
    _file_cache.clear()


def _run_host_cmd(command_type, params, timeout=10):
    """Run a command via host_command_client with a whitelisted command type."""
    hc = _get_host_client()
    result_data = hc["run"](command_type, params, timeout=timeout)
    cmd_result = result_data.get("result", result_data)
    if not cmd_result.get("success", False):
        raise RuntimeError(cmd_result.get("error", "host command failed"))
    return cmd_result


def _read_host_file(path, timeout=15):
    """Read a file on the host. Tries direct read first, falls back to host_command queue.
    Results are cached per-scan to avoid re-reading the same config file."""
    if path in _file_cache:
        return _file_cache[path]

    # Try direct filesystem read first (works for files visible inside Docker)
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                content = f.read(64 * 1024)  # Max 64KB
            _file_cache[path] = content
            return content
    except (PermissionError, OSError):
        pass  # Fall through to host_command

    # Fall back to host_command queue (for files only on the host)
    try:
        result = _run_host_cmd("compliance_read_file", {"path": path}, timeout=timeout)
        if not result.get("exists", False):
            _file_cache[path] = None
            return None
        content = result.get("content", "")
        _file_cache[path] = content
        return content
    except Exception:
        _file_cache[path] = None
        return None


import subprocess as _subprocess


def _check_sysctl(param, timeout=10):
    """Read a sysctl parameter — try /proc/sys first (works inside Docker), fall back to host_command."""
    # Direct read via /proc/sys (no queue needed)
    proc_path = "/proc/sys/" + param.replace(".", "/")
    try:
        with open(proc_path, "r") as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError):
        pass
    # Fall back to host_command
    result = _run_host_cmd("compliance_check_sysctl", {"param": param}, timeout=timeout)
    return result.get("value", "")


def _check_port_direct(port):
    """Check if port is listening using ss inside the container (shared network namespace)."""
    try:
        out = _subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
        output = out.stdout
        listening = f":{port} " in output or f":{port}\t" in output
        matched = [l for l in output.splitlines() if f":{port} " in l or f":{port}\t" in l]
        return listening, matched[0].strip() if matched else ""
    except Exception:
        return None, ""  # None means fallback to host_command


def _run_compliance_check(check_type, target, timeout=10):
    """Run a compliance_run_check on the host."""
    result = _run_host_cmd(
        "compliance_run_check",
        {"check_type": check_type, "target": target},
        timeout=timeout,
    )
    return result


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
        content = _read_host_file(path)
        if content is None:
            return {
                "status": "fail",
                "actual": "(file not found)",
                "expected": expected,
                "details": f"{path} does not exist",
            }
        # Search for pattern in file content
        matched_lines = []
        for line in content.splitlines():
            if re.search(pattern, line):
                matched_lines.append(line.strip())
        actual = "\n".join(matched_lines)
        if not matched_lines:
            return {
                "status": "fail",
                "actual": "(not found)",
                "expected": expected,
                "details": f"Pattern '{pattern}' not found in {path}",
            }
        if expected and expected in actual:
            return {"status": "pass", "actual": actual, "expected": expected, "details": ""}
        elif not expected:
            return {"status": "pass", "actual": actual, "expected": pattern, "details": ""}
        else:
            return {
                "status": "fail",
                "actual": actual,
                "expected": expected,
                "details": "Pattern found but value mismatch",
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
        result = _run_compliance_check("file_permission", path)
        mode = result.get("mode", "")
        owner = result.get("owner", "")
        group = result.get("group", "")
        actual = f"{mode} {owner} {group}"

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
            "actual": actual,
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
        content = _read_host_file(path)
        actual = "exists" if content is not None else "missing"
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
        # Map known commands to safe command_safe targets
        result = _run_host_cmd(
            "compliance_run_check",
            {"check_type": "command_safe", "target": command},
            timeout=check.get("timeout", 30),
        )
        actual = result.get("output", "").strip()

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
    """Check systemd service state. Tries direct systemctl first, falls back to host_command."""
    service = check.get("service", "")
    expected_enabled = check.get("expected_enabled", True)
    expected_active = check.get("expected_active", True)
    expected = check.get("expected", "enabled/active" if expected_enabled and expected_active else "")
    try:
        # Try direct subprocess first (works if systemctl is available in container)
        enabled = "unknown"
        active = "unknown"
        try:
            e = _subprocess.run(["systemctl", "is-enabled", service], capture_output=True, text=True, timeout=5)
            enabled = e.stdout.strip() if e.returncode == 0 else ("disabled" if "disabled" in e.stdout else "unknown")
            a = _subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True, timeout=5)
            active = a.stdout.strip() if a.returncode == 0 else ("inactive" if "inactive" in a.stdout else "unknown")
        except (FileNotFoundError, _subprocess.TimeoutExpired):
            # No systemctl in container — fall back to host_command
            result = _run_compliance_check("service_status", service)
            enabled = result.get("enabled", "unknown")
            active = result.get("active", "unknown")
        actual = f"{enabled}/{active}"

        ok = True
        issues = []
        if expected_enabled and enabled != "enabled":
            ok = False
            issues.append(f"not enabled ({enabled})")
        if not expected_enabled and enabled == "enabled":
            ok = False
            issues.append("should not be enabled")
        if expected_active and active != "active":
            ok = False
            issues.append(f"not active ({active})")
        if not expected_active and active == "active":
            ok = False
            issues.append("should not be active")

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
        actual = _check_sysctl(param)
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
    """Check if package is installed. Tries direct dpkg first, falls back to host_command."""
    package = check.get("package", "")
    should_be_installed = check.get("should_be_installed", True)
    expected = "installed" if should_be_installed else "not installed"
    try:
        # Try direct dpkg-query first
        is_installed = None
        try:
            out = _subprocess.run(
                ["dpkg-query", "-W", "-f=${Status}", package],
                capture_output=True,
                text=True,
                timeout=5,
            )
            is_installed = "install ok installed" in out.stdout
        except (FileNotFoundError, _subprocess.TimeoutExpired):
            pass

        if is_installed is None:
            # Fall back to host_command
            result = _run_compliance_check("package_installed", package)
            is_installed = result.get("installed", False)
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
    try:
        content = _read_host_file("/etc/docker/daemon.json")
        if content is None:
            return {
                "status": "error",
                "actual": "(daemon.json not found)",
                "expected": expected,
                "details": "/etc/docker/daemon.json does not exist",
            }
        try:
            daemon_cfg = json.loads(content)
        except json.JSONDecodeError:
            return {
                "status": "error",
                "actual": content[:200],
                "expected": expected,
                "details": "Failed to parse daemon.json",
            }
        actual = str(daemon_cfg.get(config_key, "(not set)"))

        ok = expected in actual if expected else actual != "(not set)"
        return {
            "status": "pass" if ok else "fail",
            "actual": actual[:500],
            "expected": expected,
            "details": "" if ok else f"Docker config mismatch for {config_key}",
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
        result = _run_host_cmd(
            "compliance_run_check",
            {"check_type": "command_safe", "target": "ufw status"},
        )
        output = result.get("output", "")
        # Search for pattern in UFW output
        matched = [line for line in output.splitlines() if re.search(pattern, line)]
        actual = "\n".join(matched).strip()
        found = len(matched) > 0

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
    """Check if port is listening (or not). Uses direct ss inside container first."""
    port = str(check.get("port", ""))
    should_listen = check.get("should_listen", True)
    expected = f"port {port} {'listening' if should_listen else 'not listening'}"
    try:
        # Try direct check first (instant, no queue)
        is_listening, matched_line = _check_port_direct(port)
        if is_listening is None:
            # Fallback to host_command
            result = _run_compliance_check("port_listening", port)
            is_listening = result.get("listening", False)
            actual_output = result.get("output", "")
            ml = [l for l in actual_output.splitlines() if f":{port} " in l or f":{port}\t" in l]
            matched_line = ml[0].strip() if ml else ""

        actual = matched_line if matched_line else f"port {port} not listening"
        ok = is_listening == should_listen
        return {
            "status": "pass" if ok else "fail",
            "actual": actual,
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
    """Get the most recent completed scan's scores with per-pack breakdown."""
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

        # Per-pack score breakdown
        scan_id = row["scan_id"]
        cur.execute(
            """
            SELECT r.pack_id, p.name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN r.status = 'pass' THEN 1 ELSE 0 END) AS passed
            FROM compliance_scan_results r
            LEFT JOIN compliance_rule_packs p ON p.pack_id = r.pack_id
            WHERE r.scan_id = %s
            GROUP BY r.pack_id, p.name
            """,
            (scan_id,),
        )
        packs = {}
        for pr in cur.fetchall():
            name = (pr.get("name") or pr["pack_id"]).lower()
            # Map pack names to short keys for dashboard
            key = name
            for k in ("ubuntu", "docker", "network"):
                if k in name:
                    key = k
                    break
            pt = pr["total"] or 0
            pp = pr["passed"] or 0
            packs[key] = round((pp / pt) * 100, 1) if pt > 0 else 0

        row["packs"] = packs
        row["last_scan"] = row.get("completed_at") or row.get("started_at")
        return row


def generate_ckl(scan_id):
    """Generate a STIG Viewer-compatible .ckl XML file for a scan.

    Returns XML string.
    """
    import xml.etree.ElementTree as ET

    # Get scan metadata
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT scan_id, score, total_rules, passed, failed, errors, started_at, completed_at, pack_ids "
            "FROM compliance_scans WHERE scan_id = %s",
            (scan_id,),
        )
        scan = cur.fetchone()

    if not scan:
        return None

    # Get all results for this scan
    results = get_scan_results(scan_id)

    # Get pack names for STIG_INFO
    pack_names = {}
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT pack_id, name, version FROM compliance_rule_packs")
        for row in cur.fetchall():
            pack_names[row["pack_id"]] = {"name": row["name"], "version": row.get("version", "V1R1")}

    # Get rule titles from rule packs
    rule_titles = {}
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT pack_id, rules FROM compliance_rule_packs")
        for row in cur.fetchall():
            rules = row["rules"] if isinstance(row["rules"], list) else json.loads(row["rules"])
            for rule in rules:
                rule_titles[rule.get("rule_id", "")] = rule.get("title", rule.get("rule_id", ""))

    # Status mapping: pass -> NotAFinding, fail -> Open, error -> Not_Reviewed, not_applicable -> Not_Applicable
    STATUS_MAP = {
        "pass": "NotAFinding",
        "fail": "Open",
        "error": "Not_Reviewed",
        "not_applicable": "Not_Applicable",
    }

    # Build XML
    checklist = ET.Element("CHECKLIST")

    # ASSET
    asset = ET.SubElement(checklist, "ASSET")
    for tag, val in [
        ("ROLE", "None"),
        ("ASSET_TYPE", "Computing"),
        ("HOST_NAME", "archie-hub"),
        ("HOST_IP", "192.168.1.200"),
        ("HOST_FQDN", "archie.local"),
        ("TARGET_KEY", "4072"),
        ("WEB_OR_DATABASE", "false"),
    ]:
        el = ET.SubElement(asset, tag)
        el.text = val

    # STIGS
    stigs = ET.SubElement(checklist, "STIGS")

    # Group results by pack_id
    results_by_pack = {}
    for r in results:
        pid = r.get("pack_id", "unknown")
        if pid not in results_by_pack:
            results_by_pack[pid] = []
        results_by_pack[pid].append(r)

    for pack_id, pack_results in results_by_pack.items():
        istig = ET.SubElement(stigs, "iSTIG")

        # STIG_INFO
        stig_info = ET.SubElement(istig, "STIG_INFO")
        pinfo = pack_names.get(pack_id, {"name": pack_id, "version": "V1R1"})

        si_title = ET.SubElement(stig_info, "SI_DATA")
        ET.SubElement(si_title, "SID_NAME").text = "title"
        ET.SubElement(si_title, "SID_DATA").text = pinfo["name"]

        si_ver = ET.SubElement(stig_info, "SI_DATA")
        ET.SubElement(si_ver, "SID_NAME").text = "version"
        ET.SubElement(si_ver, "SID_DATA").text = pinfo.get("version", "V1R1")

        # One VULN per result
        for r in pack_results:
            vuln = ET.SubElement(istig, "VULN")

            # STIG_DATA entries
            for attr, val in [
                ("Vuln_Num", r.get("rule_id", "")),
                ("Severity", r.get("severity", "medium")),
                ("Rule_Title", rule_titles.get(r.get("rule_id", ""), r.get("rule_id", ""))),
            ]:
                sd = ET.SubElement(vuln, "STIG_DATA")
                ET.SubElement(sd, "VULN_ATTRIBUTE").text = attr
                ET.SubElement(sd, "ATTRIBUTE_DATA").text = str(val)

            status_el = ET.SubElement(vuln, "STATUS")
            status_el.text = STATUS_MAP.get(r.get("status", "error"), "Not_Reviewed")

            finding_el = ET.SubElement(vuln, "FINDING_DETAILS")
            details = r.get("details", "") or ""
            actual = r.get("actual_value", "") or ""
            finding_el.text = (
                f"Automated check: {r.get('status', 'unknown').upper()}. Actual value: {actual}" if actual else details
            )

            comments_el = ET.SubElement(vuln, "COMMENTS")
            comments_el.text = "Scanned by A.R.C.H.I.E. Compliance Engine"

    # Serialize to XML string
    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'
    ET.indent(checklist, space="  ")
    xml_body = ET.tostring(checklist, encoding="unicode")
    return xml_declaration + xml_body


def generate_evidence_zip(scan_id):
    """Generate an evidence ZIP file containing scan summary, CSV results, and .ckl file.

    Returns bytes (ZIP file content).
    """
    import csv
    import io
    import zipfile

    # Get scan metadata
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT scan_id, score, total_rules, passed, failed, errors, "
            "started_at, completed_at, triggered_by, pack_ids "
            "FROM compliance_scans WHERE scan_id = %s",
            (scan_id,),
        )
        scan = cur.fetchone()

    if not scan:
        return None

    results = get_scan_results(scan_id)

    # Build ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. scan-summary.json
        summary = {
            "scan_id": scan["scan_id"],
            "score": float(scan["score"]) if scan.get("score") is not None else None,
            "total_rules": scan.get("total_rules", 0),
            "passed": scan.get("passed", 0),
            "failed": scan.get("failed", 0),
            "errors": scan.get("errors", 0),
            "triggered_by": scan.get("triggered_by", "unknown"),
            "started_at": (
                scan["started_at"].isoformat()
                if hasattr(scan.get("started_at"), "isoformat")
                else str(scan.get("started_at", ""))
            ),
            "completed_at": (
                scan["completed_at"].isoformat()
                if scan.get("completed_at") and hasattr(scan["completed_at"], "isoformat")
                else str(scan.get("completed_at", ""))
            ),
            "pack_ids": scan.get("pack_ids", []),
            "generated_by": "A.R.C.H.I.E. Compliance Engine",
        }
        zf.writestr("scan-summary.json", json.dumps(summary, indent=2))

        # 2. results.csv
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(["rule_id", "pack_id", "severity", "status", "actual", "expected", "details"])
        for r in results:
            writer.writerow(
                [
                    r.get("rule_id", ""),
                    r.get("pack_id", ""),
                    r.get("severity", ""),
                    r.get("status", ""),
                    r.get("actual_value", ""),
                    r.get("expected_value", ""),
                    r.get("details", ""),
                ]
            )
        zf.writestr("results.csv", csv_buffer.getvalue())

        # 3. checklist.ckl
        ckl_xml = generate_ckl(scan_id)
        if ckl_xml:
            zf.writestr("checklist.ckl", ckl_xml)

    zip_buffer.seek(0)
    return zip_buffer.read()


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
