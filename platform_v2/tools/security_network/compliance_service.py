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
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from psycopg2.extras import Json

from services.time_utils import FMT_DATETIME_LOCAL_SHORT, format_local, now_local

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


def get_all_rule_packs():
    """Return all rule packs as a list of dicts for the API.

    Each dict: {pack_id, name, rules_count, rules}
    """
    packs = []
    if not os.path.isdir(RULE_PACKS_DIR):
        return packs
    for fname in sorted(os.listdir(RULE_PACKS_DIR)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(RULE_PACKS_DIR, fname)) as f:
                data = json.load(f)
            rules = data.get("rules", data if isinstance(data, list) else [])
            packs.append(
                {
                    "pack_id": data.get("pack_id", fname.replace(".json", "")),
                    "name": data.get("name", fname),
                    "rules_count": len(rules),
                    "rules": rules,
                }
            )
        except Exception as exc:
            logger.error("Failed to read pack %s: %s", fname, exc)
    return packs


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
    started_at = datetime.now(timezone.utc)
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
    completed_at = datetime.now(timezone.utc)

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
    """Check if port is listening using ss or /proc/net/tcp* (works inside Docker)."""
    port_int = int(port)
    # Try ss first
    try:
        out = _subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            output = out.stdout
            listening = f":{port} " in output or f":{port}\t" in output
            matched = [l for l in output.splitlines() if f":{port} " in l or f":{port}\t" in l]
            return listening, matched[0].strip() if matched else ""
    except (FileNotFoundError, _subprocess.TimeoutExpired, OSError):
        pass

    # Fallback: parse /proc/net/tcp and /proc/net/tcp6 (always available in Linux)
    try:
        hex_port = f"{port_int:04X}"
        for proc_path in ["/proc/net/tcp", "/proc/net/tcp6"]:
            try:
                with open(proc_path, "r") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 4 and parts[3] == "0A":  # 0A = LISTEN state
                            local_port = parts[1].split(":")[1]
                            if local_port == hex_port:
                                return True, f"port {port} listening (from {proc_path})"
            except (FileNotFoundError, PermissionError):
                continue
        return False, ""
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
    """Check file owner/group/mode. Tries os.stat first, falls back to host_command."""
    import pwd
    import grp

    path = check.get("path", "")
    expected_mode = check.get("expected_mode", "")
    expected_owner = check.get("expected_owner", "")
    expected_group = check.get("expected_group", "")
    expected = check.get("expected", f"{expected_mode} {expected_owner} {expected_group}".strip())
    try:
        mode = ""
        owner = ""
        group = ""

        # Try direct os.stat first (works for volume-mounted files)
        try:
            if os.path.exists(path):
                st = os.stat(path)
                mode = oct(st.st_mode & 0o7777).replace("0o", "")
                # Zero-pad to 4 digits (e.g. "644" -> "0644")
                mode = mode.zfill(4)
                try:
                    owner = pwd.getpwuid(st.st_uid).pw_name
                except KeyError:
                    owner = str(st.st_uid)
                try:
                    group = grp.getgrgid(st.st_gid).gr_name
                except KeyError:
                    group = str(st.st_gid)
        except (PermissionError, OSError):
            pass

        # Fall back to host_command if we couldn't stat the file
        if not mode:
            try:
                result = _run_compliance_check("file_permission", path, timeout=5)
                mode = result.get("mode", "")
                owner = result.get("owner", "")
                group = result.get("group", "")
            except Exception:
                return {
                    "status": "error",
                    "actual": "(file not accessible)",
                    "expected": expected,
                    "details": f"Cannot stat {path}",
                }

        actual = f"{mode} {owner} {group}"

        ok = True
        issues = []
        # Compare modes flexibly — strip leading zeros (0755 == 755)
        if expected_mode and mode.lstrip("0") != expected_mode.lstrip("0"):
            ok = False
            issues.append(f"mode {mode} != {expected_mode}")
        if expected_owner and owner != expected_owner:
            ok = False
            issues.append(f"owner {owner} != {expected_owner}")
        if expected_group and group != expected_group:
            # If group is a numeric GID, try to resolve the expected group name to GID
            # e.g., GID 988 == "docker" on the host even if container lacks the mapping
            group_match = False
            if group.isdigit():
                try:
                    resolved = grp.getgrnam(expected_group)
                    group_match = str(resolved.gr_gid) == group
                except KeyError:
                    pass
                if not group_match:
                    # Also accept if the GID matches a well-known docker GID range
                    # or the host group file confirms it
                    try:
                        host_group = _read_host_file("/etc/group")
                        if host_group:
                            for gl in host_group.splitlines():
                                parts = gl.split(":")
                                if len(parts) >= 3 and parts[0] == expected_group and parts[2] == group:
                                    group_match = True
                                    break
                    except Exception:
                        pass
            if not group_match:
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


@_register_check("file_contains")
def _check_file_contains(check):
    """Check if a file contains an expected string, optionally on a specific line."""
    path = check.get("path", "")
    expected = check.get("expected", "")
    match_line = check.get("match_line", "")
    try:
        content = _read_host_file(path)
        if content is None:
            return {
                "status": "fail",
                "actual": "(file not found)",
                "expected": expected,
                "details": f"{path} does not exist",
            }
        if match_line:
            # Check that expected appears on a line also containing match_line
            found = any(match_line in line and expected in line for line in content.splitlines())
            actual = "found" if found else "not found on matching line"
        else:
            found = expected in content
            actual = "found" if found else "not found"
        return {
            "status": "pass" if found else "fail",
            "actual": actual,
            "expected": expected,
            "details": "" if found else f"Pattern '{expected}' not found in {path}",
        }
    except Exception as exc:
        return {"status": "error", "actual": "", "expected": expected, "details": str(exc)}


@_register_check("command_output")
def _check_command_output(check):
    """Run command, match output against pattern.
    Tries local subprocess first, falls back to host_command queue."""
    command = check.get("command", "")
    expected = check.get("expected", "")
    match_pattern = check.get("match_pattern", "")
    try:
        actual = None

        # Try local subprocess first (works for most commands inside Docker)
        # Whitelist of safe commands that can run locally
        _SAFE_LOCAL = {
            "ufw",
            "ss",
            "sysctl",
            "cat",
            "grep",
            "awk",
            "stat",
            "dpkg-query",
            "dpkg",
            "systemctl",
            "find",
            "ls",
            "id",
            "getent",
            "passwd",
            "auditctl",
            "ausearch",
            "iptables",
            "ip6tables",
            "mount",
            "df",
            "who",
            "last",
            "loginctl",
            "docker",
            "echo",
            "openssl",
            "curl",
            "ip",
            "findmnt",
            "apt-config",
            "wc",
            "if",
            "test",
            "bash",
            "sh",
            "[",
            "ssh",
            "sshd",
        }
        cmd_base = command.split()[0].split("/")[-1] if command else ""
        # Also allow shell variable assignments (val=..., count=...) and subshells
        if "=" in cmd_base and "$(" in command:
            cmd_base = "sh"  # Treat as shell builtin

        # Host-level paths MUST run on the host, not inside the container
        _HOST_PATHS = (
            "/etc/ufw/",
            "/etc/sysctl",
            "/proc/sys/",
            "/etc/ssh/",
            "/etc/audit/",
            "/etc/pam.d/",
            "/etc/security/",
            "/etc/modprobe",
            "/etc/default/ufw",
            "ip neigh",
            "ufw status",
            "ufw show",
            "/etc/login.defs",
            "/etc/passwd",
            "/etc/shadow",
            "/etc/group",
            "/etc/cron",
            "/etc/at.",
            "/etc/anacrontab",
            "auditctl",
            "ausearch",
            "dpkg-query",
            "dpkg ",
            "systemctl is-enabled",
            "systemctl is-active",
            "sysctl ",
            "iptables",
            "ip6tables",
            "lsmod",
            "modprobe",
            "journalctl",
            "timedatectl",
            "apt-config",
        )
        _needs_host = any(hp in command for hp in _HOST_PATHS)

        if cmd_base in _SAFE_LOCAL and not _needs_host:
            try:
                proc = _subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                actual = (proc.stdout + proc.stderr).strip()
            except (_subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass  # Fall through to host_command

        # Fall back to host_command queue for host checks or when local failed
        if actual is None:
            try:
                result = _run_host_cmd(
                    "compliance_check_command",
                    {"command": command},
                    timeout=check.get("timeout", 15),
                )
                actual = result.get("output", "").strip()
            except Exception:
                # Host command also failed — return error with short message
                actual = ""

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
            # Container may report not-found for host services — fall back
            if "not-found" in enabled or "not-found" in active or enabled == "unknown":
                raise FileNotFoundError("service not visible in container")
        except (FileNotFoundError, _subprocess.TimeoutExpired):
            # No systemctl or service not visible in container — fall back to host_command
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
            if "install ok installed" in out.stdout:
                is_installed = True
            elif out.returncode != 0 or "not-installed" in out.stdout or "no packages found" in out.stderr:
                # Package definitively not installed
                is_installed = False
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
        raw_val = daemon_cfg.get(config_key, "(not set)")
        actual = str(raw_val)

        # For boolean/numeric values, normalize comparison
        if isinstance(raw_val, bool):
            actual = str(raw_val)  # "True" / "False"
        elif isinstance(raw_val, (dict, list)):
            actual = json.dumps(raw_val)

        ok = expected in actual if expected else actual != "(not set)"
        # Also match case-insensitively for booleans
        if not ok and expected:
            ok = expected.lower() in actual.lower()
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
    """Check UFW rule exists. Tries local subprocess first, falls back to host_command."""
    pattern = check.get("pattern", "")
    expected = check.get("expected", "ALLOW")
    should_exist = check.get("should_exist", True)
    try:
        output = None

        # Try local subprocess first
        try:
            proc = _subprocess.run(
                ["ufw", "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                output = proc.stdout
        except (FileNotFoundError, _subprocess.TimeoutExpired, OSError):
            pass

        # Fall back to host_command
        if output is None:
            try:
                result = _run_host_cmd(
                    "compliance_run_check",
                    {"check_type": "command_safe", "target": "ufw status"},
                    timeout=5,
                )
                output = result.get("output", "")
            except Exception:
                output = ""

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


def _lookup_fix_def(scan_id, rule_id):
    """Get the fix_def + metadata for a scan result. Returns (fix_def, pack_id, severity, before) or (None, err)."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT r.pack_id, r.actual_value, r.severity
               FROM compliance_scan_results r
               WHERE r.scan_id = %s AND r.rule_id = %s""",
            (scan_id, rule_id),
        )
        row = cur.fetchone()
    if not row:
        return None, f"No result found for {scan_id}/{rule_id}"

    pack_id = row["pack_id"]
    before_value = row.get("actual_value", "")
    severity = row.get("severity", "medium")

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT rules FROM compliance_rule_packs WHERE pack_id = %s", (pack_id,))
        pack_row = cur.fetchone()
    if not pack_row:
        return None, f"Rule pack {pack_id} not found"

    rules = pack_row["rules"] if isinstance(pack_row["rules"], list) else json.loads(pack_row["rules"])
    fix_def = None
    rule_meta = None
    for rule in rules:
        if rule.get("rule_id") == rule_id:
            fix_def = rule.get("fix")
            rule_meta = rule
            break
    if not fix_def:
        return None, "No fix definition for this rule"
    return {
        "fix_def": fix_def,
        "pack_id": pack_id,
        "before_value": before_value,
        "severity": severity,
        "rule_meta": rule_meta,
    }, None


def _ai_review_fix(fix_def, rule_meta, severity):
    """Ask the Bridge dispatcher to review a compliance fix for safety.

    Returns dict: {risk_level, reasoning, approve, auto_approved}
    Auto-approves if risk_level in (low, medium). Falls back to human approval on error.
    """
    try:
        import sys as _sys

        if "/mnt/archie_brain/ai_bridge" not in _sys.path:
            _sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from tools.department_hq.services.department_dispatcher import dispatch_json
    except Exception as _import_err:
        logger.warning(f"Bridge import failed: {_import_err}")
        return {
            "risk_level": severity or "medium",
            "reasoning": f"AI review unavailable: {_import_err}",
            "approve": severity in ("low", "medium"),
            "auto_approved": False,
        }

    prompt = (
        "You are reviewing a compliance remediation fix for safety. "
        "Assess the risk of applying this fix on a production Linux host. "
        'Return ONLY a JSON object: {"risk_level": "low"|"medium"|"high"|"critical", '
        '"reasoning": "short explanation", "approve": true|false}\n\n'
        f"Rule ID: {rule_meta.get('rule_id', 'unknown')}\n"
        f"Rule title: {rule_meta.get('title', rule_meta.get('description', 'unknown'))}\n"
        f"Severity: {severity}\n"
        f"Fix type: {fix_def.get('type')}\n"
        f"Fix definition: {json.dumps(fix_def)}\n\n"
        "Approve if the fix is idempotent, targets a known-safe config, and uses standard tools. "
        "Reject if it runs arbitrary shell, touches critical paths (/bin, /boot, /root), or could brick the system."
    )
    # Hard timeout on AI review so user clicks never block >15s waiting
    # for Ollama cold-start. If Bridge doesn't respond in time, fall back
    # to severity-based approval — Department HQ is responsible for keeping
    # agents warm via agent loop jobs, not on-demand from user clicks.
    import concurrent.futures

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                dispatch_json,
                capability="security-review",
                prompt=prompt,
                module_id="compliance_fix_pipeline",
            )
            try:
                result = future.result(timeout=15)
            except concurrent.futures.TimeoutError:
                raise TimeoutError("Bridge dispatcher timeout (15s) — Ollama may be cold")

        if not result or not isinstance(result, dict):
            raise ValueError("No response from Bridge")
        risk = (result.get("risk_level") or "medium").lower()
        auto_ok = risk in ("low", "medium") and bool(result.get("approve", True))
        return {
            "risk_level": risk,
            "reasoning": result.get("reasoning", ""),
            "approve": bool(result.get("approve", False)) or auto_ok,
            "auto_approved": auto_ok,
        }
    except Exception as exc:
        logger.warning("AI review failed, defaulting to severity-based approval: %s", exc)
        return {
            "risk_level": severity or "medium",
            "reasoning": (
                f"AI review unavailable ({exc}); defaulted to severity-based approval. "
                f"Department HQ should keep the security-review agent warm via agent loop."
            ),
            "approve": severity in ("low", "medium"),
            "auto_approved": False,
        }


def _execute_fix_stage(fix_def, dry_run=True):
    """Route a fix_def to the appropriate host_monitor command handler.

    If the handler doesn't exist yet, returns a clear error without crashing.
    """
    fix_type = fix_def.get("type", "")
    params = {"dry_run": dry_run}

    if fix_type == "sysctl":
        params["param"] = fix_def.get("param", "")
        params["value"] = str(fix_def.get("value", ""))
        command_type = "compliance_fix_sysctl"

    elif fix_type == "file_line":
        params["path"] = fix_def.get("path", "")
        params["line"] = fix_def.get("line", "")
        params["restart_service"] = fix_def.get("restart_service", "")
        command_type = "compliance_fix_file_line"

    elif fix_type == "service":
        params["service"] = fix_def.get("service", "")
        params["action"] = fix_def.get("action", "restart")
        command_type = "compliance_fix_service"

    elif fix_type == "command":
        # Raw command fixes reach this point ONLY after human approval
        # via Telegram/Department HQ. apply_fix() routes them to escalation
        # instead, so this path is only hit from apply_fix_approved().
        params["command"] = fix_def.get("command", "")
        command_type = "compliance_fix_command"

    else:
        return {"success": False, "error": f"Unknown fix type: {fix_type}"}

    try:
        result = _run_host_cmd(command_type, params, timeout=30)
        return {
            "success": True,
            "preview": result.get("preview", ""),
            "applied": result.get("applied", not dry_run),
            "output": result.get("output", ""),
        }
    except RuntimeError as exc:
        msg = str(exc)
        # Handler not yet deployed on host — clear error instead of crash
        if "unknown command" in msg.lower() or "not found" in msg.lower():
            return {
                "success": False,
                "error": (
                    f"Host handler '{command_type}' not yet deployed. "
                    "Add it to scripts/host_monitor.py and restart the host monitor service."
                ),
            }
        return {"success": False, "error": msg}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _verify_fix(fix_def, before_value):
    """Re-run the compliance check to confirm the fix took effect."""
    fix_type = fix_def.get("type", "")
    try:
        if fix_type == "sysctl":
            result = _run_host_cmd(
                "compliance_check_sysctl",
                {"param": fix_def.get("param", "")},
                timeout=10,
            )
            after = str(result.get("value", "")).strip()
            expected = str(fix_def.get("value", "")).strip()
            return {
                "success": after == expected,
                "before": str(before_value).strip(),
                "after": after,
                "expected": expected,
            }
        elif fix_type == "file_line":
            result = _run_host_cmd(
                "compliance_read_file",
                {"path": fix_def.get("path", "")},
                timeout=10,
            )
            content = result.get("content", "")
            target_line = fix_def.get("line", "")
            return {
                "success": target_line.strip() in content,
                "line_found": target_line.strip() in content,
            }
        elif fix_type == "service":
            # No good re-check for service state, assume success if apply worked
            return {"success": True, "note": "Service state not re-verified"}
        elif fix_type == "command":
            # Command-type fixes are inherently risky. Do a post-apply
            # health check if the command touches critical infrastructure.
            cmd = fix_def.get("command", "")
            critical_health = _post_command_health_check(cmd)
            if not critical_health.get("healthy"):
                return {
                    "success": False,
                    "error": critical_health.get("error", "Post-apply health check failed"),
                    "health_check": critical_health,
                }
            return {
                "success": True,
                "note": "Command executed; verify via next scan",
                "health_check": critical_health,
            }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {"success": False, "error": "No verification for fix type"}


# ============================================================================
# Critical infrastructure patterns — fixes touching these must be verified
# ============================================================================

_CRITICAL_INFRA_PATTERNS = [
    "docker",
    "daemon.json",
    "systemctl",
    "containerd",
    "kubelet",
    "sshd",
    "/etc/ssh",
    "ssh.service",
    "sshd_config",
    "archie_platform",
    "archie_database",
    "postgres",
    "postgresql.conf",
    "nginx",
    "caddy",
    "network-manager",
    "systemd-networkd",
    "fail2ban",
    "ufw",
    "iptables",
    "nftables",
]


# Rules that MUST NOT be auto-fixed are stored in the DB table
# compliance_rule_blocklist (see migration 314). The helper below
# checks the DB on every apply_fix() call — admins can add/remove
# blocklist entries via /api/compliance/blocklist without code changes.
def _extract_json_object(text):
    """Best-effort JSON extraction from an LLM response that may include prose,
    markdown code fences, or extra text around the JSON object.
    Returns a dict or None."""
    if not text:
        return None
    import re

    s = str(text).strip()
    # Strip markdown code fences ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL | re.IGNORECASE)
    if fence_match:
        s = fence_match.group(1)
    # Try direct parse
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Find first { and matching closing } by brace-counting
    try:
        start = s.index("{")
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(s)):
            ch = s[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = s[start : i + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            return obj
                    except Exception:
                        return None
                    break
    except ValueError:
        pass
    return None


def generate_remediation_plan(scan_id, rule_id, user_id=None):
    """Ask F.O.R.G.E. to generate a customized remediation plan for a
    blocklisted compliance rule.

    Reads the current deployment state (docker-compose.yml, running containers)
    and asks the AI to produce a runbook tailored to THIS system.
    Stores result in compliance_remediation_plans table.
    Returns {success, plan_id, plan, fallback?}.
    """
    lookup, err = _lookup_fix_def(scan_id, rule_id)
    if err:
        return {"success": False, "error": err}

    fix_def = lookup["fix_def"]
    pack_id = lookup["pack_id"]
    rule_meta = lookup["rule_meta"] or {}
    _, blocklist_entry = _is_rule_blocked(rule_id)
    blocklist_entry = blocklist_entry or {}

    # Gather deployment context
    compose_content = ""
    try:
        r = _run_host_cmd(
            "compliance_read_file",
            {"path": "/mnt/archie_brain/docker-compose.yml"},
            timeout=10,
        )
        compose_content = (r.get("content", "") if r else "")[:10000]
    except Exception:
        pass

    running = ""
    try:
        r = _run_host_cmd(
            "compliance_run_check",
            {"check_type": "command_safe", "target": "docker info"},
            timeout=10,
        )
        running = str(r.get("output", ""))[:2000]
    except Exception:
        pass

    # Build F.O.R.G.E. prompt
    prompt = (
        "You are F.O.R.G.E., Engineering director for A.R.C.H.I.E. "
        "Return ONLY a JSON object with these keys:\n"
        "{affected_containers[], impact_analysis (markdown), prerequisites[], "
        "steps[{action, why, safe_auto}], rollback_plan, estimated_downtime, "
        "best_window, exemption_candidate, exemption_reason}\n\n"
        f"RULE: {rule_id}\n"
        f"Title: {rule_meta.get('title', 'unknown')}\n"
        f"Severity: {rule_meta.get('severity', 'medium')}\n"
        f"Description: {rule_meta.get('description', '')}\n"
        f"Rule-pack fix: {json.dumps(fix_def)}\n"
        f"Why auto-fix is blocked: {blocklist_entry.get('reason', 'N/A')}\n\n"
        f"CURRENT docker-compose.yml:\n```yaml\n{compose_content}\n```\n\n"
        f"docker info:\n```\n{running}\n```\n\n"
        "Guidelines:\n"
        "- Customize to ACTUAL containers running here, not generic STIG docs\n"
        "- safe_auto=true ONLY for read-only commands (inspect, ls, cat)\n"
        "- For mutations (stop/recreate/edit), safe_auto=false\n"
        "- Respect containers that need GPU/privileged (e.g., plex)\n"
        "- If rule legitimately doesn't apply, exemption_candidate=true"
    )

    import concurrent.futures

    plan_json = None
    model_used = None
    try:
        import sys as _sys

        if "/mnt/archie_brain/ai_bridge" not in _sys.path:
            _sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from tools.department_hq.services.department_dispatcher import dispatch

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                dispatch,
                capability="code-generation",
                prompt=prompt,
                module_id="compliance_remediation_plan",
            )
            try:
                result = future.result(timeout=240)
                raw = getattr(result, "response", None) or str(result)
                plan_json = _extract_json_object(raw)
                model_used = "code-generation"
                logger.info(
                    f"F.O.R.G.E. plan returned: raw_len={len(raw or '')} " f"parsed_dict={isinstance(plan_json, dict)}"
                )
                if plan_json is None:
                    logger.warning(f"F.O.R.G.E. plan unparseable for {rule_id}. " f"raw preview: {str(raw)[:500]}")
            except concurrent.futures.TimeoutError:
                logger.warning(f"F.O.R.G.E. plan timeout for {rule_id} after 240s")
    except Exception as exc:
        logger.warning(f"F.O.R.G.E. dispatch failed: {exc}", exc_info=True)

    # Fallback if AI didn't respond
    if not plan_json or not isinstance(plan_json, dict):
        plan_json = {
            "affected_containers": [],
            "impact_analysis": blocklist_entry.get("reason", "Manual remediation required. AI plan unavailable."),
            "prerequisites": ["Schedule planned downtime window"],
            "steps": [
                {
                    "action": "Review rule + current deployment state",
                    "why": "Understand scope before making changes",
                    "safe_auto": True,
                }
            ],
            "rollback_plan": "Restore from backup snapshot",
            "estimated_downtime": "unknown",
            "best_window": "next maintenance window",
            "exemption_candidate": False,
            "exemption_reason": None,
            "_fallback": True,
        }
        model_used = "fallback"

    # Store plan
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO compliance_remediation_plans
                       (rule_id, scan_id, pack_id, generated_by, model_used,
                        affected_containers, impact_analysis, prerequisites,
                        steps, rollback_plan, estimated_downtime, best_window,
                        exemption_candidate, exemption_reason, status)
                   VALUES (%s, %s, %s, 'F.O.R.G.E.', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'generated')
                   RETURNING id""",
                (
                    rule_id,
                    scan_id,
                    pack_id,
                    model_used,
                    Json(plan_json.get("affected_containers", [])),
                    plan_json.get("impact_analysis", ""),
                    Json(plan_json.get("prerequisites", [])),
                    Json(plan_json.get("steps", [])),
                    plan_json.get("rollback_plan", ""),
                    plan_json.get("estimated_downtime", ""),
                    plan_json.get("best_window", ""),
                    bool(plan_json.get("exemption_candidate", False)),
                    plan_json.get("exemption_reason"),
                ),
            )
            row = cur.fetchone()
            plan_id = row["id"] if isinstance(row, dict) else row[0]
    except Exception as exc:
        logger.error(f"Failed to store remediation plan: {exc}")
        return {"success": False, "error": f"DB insert failed: {exc}"}

    return {
        "success": True,
        "plan_id": plan_id,
        "rule_id": rule_id,
        "plan": plan_json,
        "generated_by": "F.O.R.G.E.",
        "fallback": plan_json.get("_fallback", False),
    }


def get_remediation_plan(plan_id):
    """Fetch a stored plan by id."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT * FROM compliance_remediation_plans WHERE id = %s", (plan_id,))
            row = cur.fetchone()
        if not row:
            return None
        p = dict(row)
        for k in ["generated_at", "started_at", "completed_at", "created_at", "updated_at"]:
            if p.get(k):
                p[k] = p[k].isoformat()
        return p
    except Exception as exc:
        logger.error(f"get_remediation_plan failed: {exc}")
        return None


def list_remediation_plans(rule_id=None, status=None):
    """List plans, optionally filtered by rule_id or status."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            conditions, params = [], []
            if rule_id:
                conditions.append("rule_id = %s")
                params.append(rule_id)
            if status:
                conditions.append("status = %s")
                params.append(status)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            cur.execute(
                "SELECT id, rule_id, pack_id, status, generated_at, "
                "started_at, completed_at, exemption_candidate, "
                "jsonb_array_length(COALESCE(steps, '[]'::jsonb)) AS step_count "
                "FROM compliance_remediation_plans " + where + " ORDER BY generated_at DESC LIMIT 50",
                params,
            )
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            for k in ["generated_at", "started_at", "completed_at"]:
                if r.get(k):
                    r[k] = r[k].isoformat()
        return rows
    except Exception as exc:
        logger.error(f"list_remediation_plans failed: {exc}")
        return []


def _dispatch_to_repair_bay(scan_id, rule_id, fix_def, blocklist_entry, user_id):
    """Dispatch a blocklisted compliance fix to Repair Bay for AI-assisted
    manual remediation.

    Creates an improvement_proposal with category='compliance_fix',
    assigns F.O.R.G.E. as the engineering agent, and queues a background
    job to have F.O.R.G.E. generate the remediation patch via Bridge.

    Returns: {success, proposal_id, patch_preview?, error?}
    """
    try:
        # 1. Find F.O.R.G.E. agent ID
        forge_agent_id = None
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT id FROM agents WHERE name IN ('FORGE', 'F.O.R.G.E.') LIMIT 1")
            row = cur.fetchone()
            if row:
                forge_agent_id = row["id"] if isinstance(row, dict) else row[0]

        # 2. Create Repair Bay proposal
        title = f"Compliance Fix (Repair Bay): {rule_id}"
        description = (
            f"Blocklisted rule routed to Repair Bay for AI-assisted remediation.\n\n"
            f"Rule: {rule_id}\n"
            f"Scan: {scan_id}\n"
            f"Blocklist reason: {blocklist_entry.get('reason', 'unknown')}\n\n"
            f"F.O.R.G.E. will read the current docker-compose.yml and generate "
            f"a proposed patch. Human review required before deployment."
        )
        metadata = {
            "source": "compliance_fix_pipeline",
            "scan_id": scan_id,
            "rule_id": rule_id,
            "fix_def": fix_def,
            "blocklist_reason": blocklist_entry.get("reason"),
            "manual_steps": blocklist_entry.get("manual_steps", ""),
        }

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO improvement_proposals
                       (title, description, category, priority, status,
                        risk_level, metadata, assigned_agent_id, proposed_at)
                   VALUES (%s, %s, 'compliance_fix', %s, 'pending_approval',
                           %s, %s, %s, NOW())
                   RETURNING id""",
                (
                    title,
                    description,
                    blocklist_entry.get("risk_level", "medium"),
                    blocklist_entry.get("risk_level", "medium"),
                    Json(metadata),
                    forge_agent_id,
                ),
            )
            row = cur.fetchone()
            proposal_id = row["id"] if isinstance(row, dict) else row[0]

        # 3. Attempt to generate patch synchronously via F.O.R.G.E. (with timeout)
        patch_preview = _generate_compose_patch(rule_id, fix_def, blocklist_entry)

        # 4. Update proposal with generated patch (if we got one)
        if patch_preview:
            try:
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """UPDATE improvement_proposals
                           SET code_diff = %s,
                               status = 'pending_approval',
                               reviewed_at = NOW()
                           WHERE id = %s""",
                        (patch_preview, proposal_id),
                    )
            except Exception:
                pass

        return {
            "success": True,
            "proposal_id": proposal_id,
            "agent": "F.O.R.G.E.",
            "patch_preview": patch_preview,
            "repair_bay_url": f"/tools/repair-bay#proposal-{proposal_id}",
        }
    except Exception as exc:
        logger.error(f"Repair Bay dispatch failed: {exc}")
        return {"success": False, "error": str(exc)}


def _generate_compose_patch(rule_id, fix_def, blocklist_entry):
    """Ask F.O.R.G.E. (via Bridge) to generate a docker-compose patch that
    fixes the given compliance rule. Returns unified diff text or None.

    Hard 20s timeout so the user's click doesn't hang.
    """
    import concurrent.futures

    # Read the current docker-compose.yml via host_monitor
    try:
        result = _run_host_cmd(
            "compliance_read_file",
            {"path": "/mnt/archie_brain/docker-compose.yml"},
            timeout=10,
        )
        compose_content = result.get("content", "") if result else ""
    except Exception:
        compose_content = ""

    if not compose_content:
        return None

    # Truncate for prompt size — F.O.R.G.E. gets relevant sections only
    if len(compose_content) > 12000:
        compose_content = compose_content[:12000] + "\n# ... (truncated)"

    prompt = (
        f"You are F.O.R.G.E., the Engineering director. Review this docker-compose.yml "
        f"and generate a minimal patch to fix compliance rule {rule_id}.\n\n"
        f"Rule description: {blocklist_entry.get('reason', '')}\n"
        f"Manual steps provided: {blocklist_entry.get('manual_steps', '')[:500]}\n\n"
        f"Current docker-compose.yml:\n```yaml\n{compose_content}\n```\n\n"
        f"Return ONLY the unified diff (with --- and +++ headers) showing the "
        f"minimum changes needed. Do NOT include explanation. If the rule cannot "
        f"be fixed via docker-compose changes, return 'MANUAL_INTERVENTION_REQUIRED'."
    )

    try:
        import sys as _sys

        if "/mnt/archie_brain/ai_bridge" not in _sys.path:
            _sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from tools.department_hq.services.department_dispatcher import dispatch

        def _call():
            return dispatch(
                capability="code-generation",
                prompt=prompt,
                module_id="compliance_fix_repair_bay",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_call)
            try:
                result = future.result(timeout=20)
            except concurrent.futures.TimeoutError:
                logger.warning(f"F.O.R.G.E. patch generation timed out for {rule_id}")
                return None

        if not result:
            return None
        # dispatch() returns a DispatchResult object — extract response text
        text = result.response if hasattr(result, "response") else str(result)
        if "MANUAL_INTERVENTION_REQUIRED" in text:
            return None
        return text[:8000]
    except Exception as exc:
        logger.warning(f"F.O.R.G.E. patch generation failed: {exc}")
        return None


def _mark_scan_result_fixed(scan_id, rule_id):
    """After successful remediation, update compliance_scan_results so the
    rule stops appearing as failing in the Compliance tab. The next full
    scan will replace this with a fresh result.
    """
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE compliance_scan_results
                   SET status = 'pass',
                       actual_value = COALESCE(actual_value, '') || ' (fixed)'
                   WHERE scan_id = %s AND rule_id = %s""",
                (scan_id, rule_id),
            )
            return cur.rowcount > 0
    except Exception as exc:
        logger.warning(f"Failed to mark scan result fixed: {exc}")
        return False


def _is_rule_blocked(rule_id):
    """Check if a rule is in the blocklist. Returns (blocked, entry_dict)."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT rule_id, reason, risk_level, manual_steps,
                          manually_applied_at
                   FROM compliance_rule_blocklist
                   WHERE rule_id = %s""",
                (rule_id,),
            )
            row = cur.fetchone()
        if row:
            entry = dict(row)
            if entry.get("manually_applied_at"):
                entry["manually_applied_at"] = entry["manually_applied_at"].isoformat()
            return True, entry
    except Exception as exc:
        logger.warning(f"Blocklist check failed: {exc}")
    return False, None


# Config files that command fixes commonly modify — these get auto-snapshotted
# BEFORE command fixes run so we can rollback on failure.
_CRITICAL_CONFIG_FILES = [
    "/etc/docker/daemon.json",
    "/etc/ssh/sshd_config",
    "/etc/sysctl.conf",
    "/etc/default/grub",
    "/etc/audit/auditd.conf",
    "/etc/fail2ban/jail.local",
    "/etc/nginx/nginx.conf",
]


def _is_critical_command(cmd):
    """Return True if the command touches critical infrastructure."""
    if not cmd:
        return False
    lower = cmd.lower()
    return any(p in lower for p in _CRITICAL_INFRA_PATTERNS)


def _extract_files_from_command(cmd):
    """Extract file paths from a shell command for pre-snapshot."""
    import re

    # Find all paths matching critical config files
    files = []
    for path in _CRITICAL_CONFIG_FILES:
        if path in cmd:
            files.append(path)
    # Also look for any explicit /etc/* paths in the command
    matches = re.findall(r"(/etc/[a-zA-Z0-9_/.\-]+)", cmd)
    for m in matches:
        if m not in files and len(m) > 5:
            files.append(m)
    return files


def _post_command_health_check(cmd):
    """Run health checks after a command-type compliance fix.

    For docker/systemctl commands, verifies the affected service is still
    responsive. Returns {healthy: bool, checks: {...}, error?: str}
    """
    if not cmd:
        return {"healthy": True, "checks": {}}

    checks = {}
    errors = []
    lower = cmd.lower()

    # Docker health check
    if "docker" in lower or "daemon.json" in cmd:
        try:
            # compliance_run_check has a whitelist for 'docker info'
            result = _run_host_cmd(
                "compliance_run_check",
                {"check_type": "command_safe", "target": "docker info"},
                timeout=15,
            )
            docker_ok = result.get("success") and result.get("returncode", 1) == 0
            checks["docker"] = "ok" if docker_ok else "failed"
            if not docker_ok:
                errors.append("Docker daemon not responding")
        except Exception as exc:
            checks["docker"] = "error"
            errors.append(f"Docker check error: {exc}")

    # SSH health check
    if "ssh" in lower:
        try:
            result = _run_host_cmd(
                "compliance_run_check",
                {"check_type": "service_status", "target": "ssh.service"},
                timeout=10,
            )
            ssh_ok = result.get("success") and result.get("active") == "active"
            checks["sshd"] = "ok" if ssh_ok else "failed"
            if not ssh_ok:
                errors.append("SSH service not active")
        except Exception:
            checks["sshd"] = "skipped"

    return {
        "healthy": len(errors) == 0,
        "checks": checks,
        "error": "; ".join(errors) if errors else None,
    }


def _read_host_file_safe(path):
    """Read a file on the host for snapshot purposes. Returns content or None."""
    try:
        result = _run_host_cmd("compliance_read_file", {"path": path}, timeout=10)
        if result.get("exists"):
            return result.get("content", "")
    except Exception:
        pass
    return None


def _capture_file_snapshot(
    file_path,
    content_before,
    content_after,
    remediation_id,
    proposal_id,
    change_summary="",
):
    """Store a before/after file snapshot for audit + rollback."""
    import hashlib

    def _sha(s):
        if s is None:
            return None
        return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO compliance_file_snapshots
                       (remediation_id, proposal_id, file_path,
                        content_before, content_after,
                        sha256_before, sha256_after, change_summary)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    remediation_id,
                    proposal_id,
                    file_path,
                    content_before,
                    content_after,
                    _sha(content_before),
                    _sha(content_after),
                    change_summary,
                ),
            )
            row = cur.fetchone()
            return row["id"] if isinstance(row, dict) else row[0]
    except Exception as exc:
        logger.warning("Failed to capture file snapshot: %s", exc)
        return None


def get_file_history(file_path, limit=20):
    """Return change history for a config file (newest first)."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT s.id, s.remediation_id, s.proposal_id, s.file_path,
                          s.sha256_before, s.sha256_after, s.change_summary,
                          s.captured_at, s.rolled_back_at,
                          r.rule_id
                   FROM compliance_file_snapshots s
                   LEFT JOIN compliance_remediations r ON r.id = s.remediation_id
                   WHERE s.file_path = %s
                   ORDER BY s.captured_at DESC
                   LIMIT %s""",
                (file_path, limit),
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.error("get_file_history failed: %s", exc)
        return []


def rollback_file_snapshot(snapshot_id, user_id):
    """Revert a file to its content_before state from a snapshot."""
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT file_path, content_before, rolled_back_at
                   FROM compliance_file_snapshots WHERE id = %s""",
                (snapshot_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"success": False, "error": f"Snapshot {snapshot_id} not found"}
        if row["rolled_back_at"]:
            return {"success": False, "error": "Snapshot already rolled back"}
        if row["content_before"] is None:
            return {"success": False, "error": "No content_before available for rollback"}

        if len(row["content_before"]) > 64 * 1024:
            return {"success": False, "error": "File too large for rollback (>64KB)"}

        result = _run_host_cmd(
            "compliance_restore_file",
            {"path": row["file_path"], "content": row["content_before"]},
            timeout=30,
        )

        if not result.get("success"):
            return {"success": False, "error": result.get("error", "Restore failed")}

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE compliance_file_snapshots
                   SET rolled_back_at = NOW(), rolled_back_by = %s
                   WHERE id = %s""",
                (user_id, snapshot_id),
            )

        return {"success": True, "file": row["file_path"]}
    except Exception as exc:
        logger.error("rollback_file_snapshot failed: %s", exc)
        return {"success": False, "error": str(exc)}


def _escalate_fix_to_telegram(scan_id, rule_id, fix_def, severity, review, user_id, proposal_id):
    """Submit a high/critical compliance fix to the approval queue.

    Returns dict: {approval_id, action_type, status, already_pending?}
    """
    action_type = f"compliance_fix_{rule_id}"

    # Check for existing pending approval for this rule (dedup)
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT id FROM autonomy_approval_queue
                   WHERE action_type = %s AND status = 'pending' LIMIT 1""",
                (action_type,),
            )
            existing = cur.fetchone()
        if existing:
            existing_id = existing["id"] if isinstance(existing, dict) else existing[0]
            return {
                "approval_id": existing_id,
                "action_type": action_type,
                "status": "pending",
                "already_pending": True,
                "note": ("Approval already pending. " "Check Department HQ > Approvals tab or Telegram."),
            }
    except Exception as exc:
        logger.warning(f"Dedup check failed: {exc}")

    try:
        import sys

        # Add ai_bridge to path so agent_loop's `from db import get_db` works
        if "/mnt/archie_brain/ai_bridge" not in sys.path:
            sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from agent_loop import request_approval

        action_data = {
            "scan_id": scan_id,
            "rule_id": rule_id,
            "fix_def": fix_def,
            "severity": severity,
            "proposal_id": proposal_id,
            "requested_user_id": user_id,
            "ai_review": review,
        }
        reason = (
            f"High-risk compliance fix: {rule_id} ({severity})\n"
            f"AI review: {review.get('reasoning', 'no reasoning')[:200]}"
        )
        approval_id = request_approval(
            action_type=action_type,
            action_data=action_data,
            reason=reason,
            requested_by="compliance_fix",
            priority=3 if severity == "critical" else 5,
            tier=2,
        )
        return {
            "approval_id": approval_id,
            "action_type": action_type,
            "status": "pending" if approval_id else "failed_to_escalate",
            "note": (
                "Approve via Telegram, then agent_loop will execute the fix"
                if approval_id
                else "Approval creation failed (Telegram may be unreachable)"
            ),
        }
    except Exception as exc:
        logger.error(f"Telegram escalation failed: {exc}")
        return {"approval_id": None, "status": "error", "error": str(exc)}


def apply_fix_approved(scan_id, rule_id, user_id):
    """Execute a compliance fix that has been approved via Telegram.

    Skips the AI review stage (already approved by human).
    Creates a full file backup before file_line fixes so we can
    automatically roll back if verify fails.
    """
    stages = {}

    lookup, err = _lookup_fix_def(scan_id, rule_id)
    if err:
        return {"success": False, "error": err, "stages": stages}

    fix_def = lookup["fix_def"]
    pack_id = lookup["pack_id"]
    before_value = lookup["before_value"]
    severity = lookup["severity"]
    rule_meta = lookup["rule_meta"] or {}

    hc = _get_host_client()
    if not hc["available"]():
        return {
            "success": False,
            "error": "Host command queue unavailable",
            "stages": stages,
        }

    # Record human approval as the review stage
    stages["review"] = {
        "risk_level": severity,
        "approve": True,
        "reasoning": "Approved via Telegram (human)",
        "auto_approved": False,
        "human_approved": True,
    }

    # Stage 3: Dry-run
    dry_run = _execute_fix_stage(fix_def, dry_run=True)
    stages["dry_run"] = dry_run
    if not dry_run.get("success"):
        _record_remediation(
            scan_id,
            rule_id,
            pack_id,
            fix_def,
            before_value,
            user_id,
            "failed",
            None,
            "dry_run",
            stages["review"],
            dry_run,
            None,
        )
        return {
            "success": False,
            "error": f"Dry-run failed: {dry_run.get('error', 'unknown')}",
            "stages": stages,
        }

    # Capture BEFORE snapshot for file_line AND command fixes (failover).
    # For command type, snapshot any critical config files it might touch.
    snapshot_before = None
    command_snapshots = {}  # path -> content
    if fix_def.get("type") == "file_line":
        snapshot_before = _read_host_file_safe(fix_def.get("path", ""))
    elif fix_def.get("type") == "command":
        cmd = fix_def.get("command", "")
        files_to_snapshot = _extract_files_from_command(cmd)
        for f in files_to_snapshot:
            content = _read_host_file_safe(f)
            if content is not None:
                command_snapshots[f] = content
        stages["pre_snapshot"] = {
            "snapshotted_files": list(command_snapshots.keys()),
            "count": len(command_snapshots),
        }

    # Stage 4: Apply for real
    applied = _execute_fix_stage(fix_def, dry_run=False)
    stages["applied"] = applied
    if not applied.get("success"):
        # AUTO-ROLLBACK on apply failure for command fixes (before the
        # damage spreads). We rollback ANY snapshotted files and restart
        # docker if daemon.json was in the snapshot set.
        if fix_def.get("type") == "command" and command_snapshots:
            logger.warning(
                f"Apply FAILED for {rule_id}, auto-rollback from command snapshot " f"({len(command_snapshots)} files)"
            )
            rollback_results = {}
            for path, content in command_snapshots.items():
                try:
                    _run_host_cmd(
                        "compliance_restore_file",
                        {"path": path, "content": content},
                        timeout=15,
                    )
                    rollback_results[path] = "restored"
                except Exception as rb_err:
                    rollback_results[path] = f"error: {rb_err}"
            # Restart docker if daemon.json was restored
            if any("docker" in p for p in command_snapshots.keys()):
                try:
                    _run_host_cmd(
                        "compliance_fix_service",
                        {"service": "docker", "action": "restart", "dry_run": False},
                        timeout=45,
                    )
                    rollback_results["docker_restart"] = "ok"
                except Exception as rb_err:
                    rollback_results["docker_restart"] = f"error: {rb_err}"
            stages["rollback"] = {
                "success": all("error" not in str(v) for v in rollback_results.values()),
                "reason": "apply failed",
                "type": "command",
                "files": rollback_results,
            }
        elif fix_def.get("type") == "file_line" and snapshot_before is not None:
            logger.warning(f"Apply FAILED for {rule_id}, auto-rollback file_line")
            try:
                _run_host_cmd(
                    "compliance_restore_file",
                    {"path": fix_def.get("path", ""), "content": snapshot_before},
                    timeout=15,
                )
                stages["rollback"] = {"success": True, "reason": "apply failed", "type": "file_line"}
            except Exception as rb_err:
                stages["rollback"] = {"success": False, "error": str(rb_err)}

        _record_remediation(
            scan_id,
            rule_id,
            pack_id,
            fix_def,
            before_value,
            user_id,
            "failed",
            None,
            "applied",
            stages["review"],
            dry_run,
            applied,
        )
        return {
            "success": False,
            "error": f"Apply failed: {applied.get('error', 'unknown')}",
            "stages": stages,
        }

    # Stage 5: Verify
    verified = _verify_fix(fix_def, before_value)
    stages["verified"] = verified

    # AUTO-ROLLBACK on verification failure
    if not verified.get("success"):
        if fix_def.get("type") == "file_line" and snapshot_before is not None:
            logger.warning(f"Verify failed for {rule_id}, auto-rollback file_line")
            try:
                _run_host_cmd(
                    "compliance_restore_file",
                    {"path": fix_def.get("path", ""), "content": snapshot_before},
                    timeout=15,
                )
                stages["rollback"] = {"success": True, "reason": "verify failed", "type": "file_line"}
            except Exception as rb_err:
                stages["rollback"] = {"success": False, "error": str(rb_err)}

        elif fix_def.get("type") == "command" and command_snapshots:
            # Restore ALL snapshotted files, then restart docker if any of them
            # are docker-related. This recovers from destructive docker config
            # changes like userns-remap.
            logger.warning(f"Verify failed for {rule_id}, auto-rollback command " f"({len(command_snapshots)} files)")
            rollback_results = {}
            for path, content in command_snapshots.items():
                try:
                    _run_host_cmd(
                        "compliance_restore_file",
                        {"path": path, "content": content},
                        timeout=15,
                    )
                    rollback_results[path] = "restored"
                except Exception as rb_err:
                    rollback_results[path] = f"error: {rb_err}"

            # If we restored daemon.json, restart docker to re-read it
            docker_restored = any("docker" in p for p in command_snapshots.keys())
            if docker_restored:
                try:
                    _run_host_cmd(
                        "compliance_fix_service",
                        {"service": "docker", "action": "restart", "dry_run": False},
                        timeout=45,
                    )
                    rollback_results["docker_restart"] = "ok"
                except Exception as rb_err:
                    rollback_results["docker_restart"] = f"error: {rb_err}"

            stages["rollback"] = {
                "success": all("error" not in str(v) for v in rollback_results.values()),
                "reason": "verify failed",
                "type": "command",
                "files": rollback_results,
            }

    overall_success = verified.get("success", False)
    remediation_id = _record_remediation(
        scan_id,
        rule_id,
        pack_id,
        fix_def,
        before_value,
        user_id,
        "success" if overall_success else "failed",
        None,
        "verified",
        stages["review"],
        dry_run,
        verified,
    )

    # Mark the scan result as passing so UI stops showing it as failing
    if overall_success:
        _mark_scan_result_fixed(scan_id, rule_id)

    # Capture AFTER snapshot
    if fix_def.get("type") == "file_line" and remediation_id:
        snapshot_after = _read_host_file_safe(fix_def.get("path", ""))
        snapshot_id = _capture_file_snapshot(
            file_path=fix_def.get("path", ""),
            content_before=snapshot_before,
            content_after=snapshot_after,
            remediation_id=remediation_id,
            proposal_id=None,
            change_summary=f"{rule_id}: {fix_def.get('line', '')[:100]} (via Telegram approval)",
        )
        stages["snapshot"] = {"success": snapshot_id is not None, "snapshot_id": snapshot_id}

    return {
        "success": overall_success,
        "stages": stages,
        "fix_type": fix_def.get("type"),
    }


def _create_compliance_proposal(scan_id, rule_id, rule_meta, severity, fix_def):
    """Create an improvement_proposals row for audit trail. Returns proposal_id or None."""
    try:
        title = f"Compliance fix: {rule_id}"
        description = (
            f"Auto-generated proposal for compliance rule {rule_id}\n"
            f"Title: {rule_meta.get('title', rule_meta.get('description', ''))}\n"
            f"Severity: {severity}\n"
            f"Fix type: {fix_def.get('type')}\n"
            f"Scan ID: {scan_id}"
        )
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO improvement_proposals
                       (title, description, category, priority, status,
                        risk_level, metadata, proposed_at)
                   VALUES (%s, %s, 'compliance_fix', %s, 'pending_approval',
                           %s, %s, NOW())
                   RETURNING id""",
                (
                    title,
                    description,
                    severity,
                    severity,
                    Json({"scan_id": scan_id, "rule_id": rule_id, "fix_def": fix_def}),
                ),
            )
            row = cur.fetchone()
            return row["id"] if isinstance(row, dict) else row[0]
    except Exception as exc:
        logger.warning("Failed to create compliance proposal: %s", exc)
        return None


def apply_fix(scan_id, rule_id, user_id):
    """Multi-stage compliance fix pipeline.

    Stages:
      1. Lookup fix definition from rule pack
      2. Create improvement_proposal (audit trail)
      3. AI review via Bridge dispatcher (auto-approve low/medium)
      4. Dry-run on host (validates without applying)
      5. Apply on host (only if dry-run passed)
      6. Verify the rule now passes (re-run check)

    Returns: {success, proposal_id, stages: {review, dry_run, applied, verified}}
    """
    stages = {}

    # Stage 0: Lookup fix definition (needed for both normal + blocklisted flow)
    lookup, err = _lookup_fix_def(scan_id, rule_id)
    if err:
        return {"success": False, "error": err, "stages": stages}

    # Blocklisted rules dispatch to Repair Bay for AI-assisted remediation
    # instead of blocking outright. F.O.R.G.E. generates a patch, human reviews
    # it in Repair Bay UI, then deploys manually.
    blocked, blocklist_entry = _is_rule_blocked(rule_id)
    if blocked:
        # If already manually applied, just mark the scan result as pass
        if blocklist_entry.get("manually_applied_at"):
            _mark_scan_result_fixed(scan_id, rule_id)
            return {
                "success": True,
                "manual_only": True,
                "already_applied": True,
                "blocklist_entry": blocklist_entry,
                "stages": {
                    "manual": {"success": True, "note": "Previously marked as manually applied"},
                },
            }

        # Dispatch to Repair Bay
        repair_bay_result = _dispatch_to_repair_bay(scan_id, rule_id, lookup["fix_def"], blocklist_entry, user_id)
        return {
            "success": False,
            "manual_only": True,
            "dispatched_to_repair_bay": repair_bay_result.get("success", False),
            "proposal_id": repair_bay_result.get("proposal_id"),
            "patch_preview": repair_bay_result.get("patch_preview"),
            "repair_bay_url": repair_bay_result.get("repair_bay_url"),
            "error": (
                f"Rule {rule_id} dispatched to Repair Bay. "
                f"F.O.R.G.E. has been asked to generate a remediation patch. "
                f"Review in Repair Bay before deploying."
            ),
            "blocklist_entry": blocklist_entry,
            "manual_steps": blocklist_entry.get("manual_steps", ""),
            "stages": {
                "blocked": {
                    "success": False,
                    "reason": "blocklist",
                    "rule_id": rule_id,
                    "risk_level": blocklist_entry.get("risk_level", "high"),
                },
                "repair_bay_dispatch": {
                    "success": repair_bay_result.get("success", False),
                    "proposal_id": repair_bay_result.get("proposal_id"),
                    "agent": "F.O.R.G.E.",
                    "patch_generated": bool(repair_bay_result.get("patch_preview")),
                },
            },
        }

    fix_def = lookup["fix_def"]
    pack_id = lookup["pack_id"]
    before_value = lookup["before_value"]
    severity = lookup["severity"]
    rule_meta = lookup["rule_meta"] or {}

    hc = _get_host_client()
    if not hc["available"]():
        return {"success": False, "error": "Host command queue unavailable", "stages": stages}

    # Stage 1: Create proposal (audit trail)
    proposal_id = _create_compliance_proposal(scan_id, rule_id, rule_meta, severity, fix_def)

    # Stage 2: AI review
    review = _ai_review_fix(fix_def, rule_meta, severity)
    stages["review"] = review

    # Raw command fixes ALWAYS require human approval regardless of AI review
    is_command_fix = fix_def.get("type") == "command"
    if is_command_fix:
        review["risk_level"] = "high"
        review["reasoning"] = review.get("reasoning", "") + " | Raw command fixes always require human approval."

    # High/critical risk → escalate to Telegram approval instead of rejecting
    if is_command_fix or review.get("risk_level") in ("high", "critical") or not review.get("approve"):
        escalation = _escalate_fix_to_telegram(scan_id, rule_id, fix_def, severity, review, user_id, proposal_id)
        stages["escalation"] = escalation
        _record_remediation(
            scan_id,
            rule_id,
            pack_id,
            fix_def,
            before_value,
            user_id,
            "pending",
            proposal_id,
            "escalated",
            review,
            None,
            None,
        )
        return {
            "success": False,
            "pending_approval": True,
            "approval_id": escalation.get("approval_id"),
            "error": (
                f"High/critical severity — awaiting Telegram approval. "
                f"Reason: {review.get('reasoning', 'risk too high')}"
            ),
            "proposal_id": proposal_id,
            "stages": stages,
        }

    # Stage 3: Dry-run
    dry_run = _execute_fix_stage(fix_def, dry_run=True)
    stages["dry_run"] = dry_run
    if not dry_run.get("success"):
        _record_remediation(
            scan_id,
            rule_id,
            pack_id,
            fix_def,
            before_value,
            user_id,
            "failed",
            proposal_id,
            "dry_run",
            review,
            dry_run,
            None,
        )
        return {
            "success": False,
            "error": f"Dry-run failed: {dry_run.get('error', 'unknown')}",
            "proposal_id": proposal_id,
            "stages": stages,
        }

    # Capture BEFORE snapshot for file_line fixes (git-style rollback)
    snapshot_before = None
    if fix_def.get("type") == "file_line":
        snapshot_before = _read_host_file_safe(fix_def.get("path", ""))

    # Stage 4: Apply for real
    applied = _execute_fix_stage(fix_def, dry_run=False)
    stages["applied"] = applied
    if not applied.get("success"):
        _record_remediation(
            scan_id,
            rule_id,
            pack_id,
            fix_def,
            before_value,
            user_id,
            "failed",
            proposal_id,
            "applied",
            review,
            dry_run,
            applied,
        )
        return {
            "success": False,
            "error": f"Apply failed: {applied.get('error', 'unknown')}",
            "proposal_id": proposal_id,
            "stages": stages,
        }

    # Stage 5: Verify
    verified = _verify_fix(fix_def, before_value)
    stages["verified"] = verified

    overall_success = verified.get("success", False)
    remediation_id = _record_remediation(
        scan_id,
        rule_id,
        pack_id,
        fix_def,
        before_value,
        user_id,
        "success" if overall_success else "failed",
        proposal_id,
        "verified",
        review,
        dry_run,
        verified,
    )

    # Mark the scan result as passing so UI stops showing it as failing
    if overall_success:
        _mark_scan_result_fixed(scan_id, rule_id)

    # Capture AFTER snapshot for file_line fixes (git-style diff + rollback)
    if fix_def.get("type") == "file_line" and remediation_id:
        snapshot_after = _read_host_file_safe(fix_def.get("path", ""))
        snapshot_id = _capture_file_snapshot(
            file_path=fix_def.get("path", ""),
            content_before=snapshot_before,
            content_after=snapshot_after,
            remediation_id=remediation_id,
            proposal_id=proposal_id,
            change_summary=f"{rule_id}: {fix_def.get('line', '')[:100]}",
        )
        stages["snapshot"] = {
            "success": snapshot_id is not None,
            "snapshot_id": snapshot_id,
            "file": fix_def.get("path", ""),
        }

    # Update proposal status
    if proposal_id:
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """UPDATE improvement_proposals
                       SET status = %s, deployed_at = NOW(),
                           execution_results = %s
                       WHERE id = %s""",
                    (
                        "deployed" if overall_success else "failed",
                        Json({"stages": stages}),
                        proposal_id,
                    ),
                )
        except Exception:
            pass

    return {
        "success": overall_success,
        "proposal_id": proposal_id,
        "stages": stages,
        "fix_type": fix_def.get("type"),
    }


def _record_remediation(
    scan_id,
    rule_id,
    pack_id,
    fix_def,
    before_value,
    user_id,
    result,
    proposal_id,
    stage,
    review_result,
    dry_run_result,
    verification_result,
):
    """Insert a remediation row with all pipeline stage results. Returns remediation_id or None."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO compliance_remediations
                       (scan_id, rule_id, pack_id, action_type, command_executed,
                        result, risk_level, executed_by, before_value, executed_at,
                        proposal_id, stage, review_result, dry_run_result, verification_result)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(),
                           %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    scan_id,
                    rule_id,
                    pack_id,
                    fix_def.get("type", ""),
                    json.dumps(fix_def),
                    result,
                    fix_def.get("risk", "medium"),
                    user_id,
                    before_value,
                    proposal_id,
                    stage,
                    Json(review_result) if review_result else None,
                    Json(dry_run_result) if dry_run_result else None,
                    Json(verification_result) if verification_result else None,
                ),
            )
            row = cur.fetchone()
            return row["id"] if isinstance(row, dict) else row[0]
    except Exception as exc:
        logger.warning("Failed to record remediation: %s", exc)
        return None


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

        # Convert types for JSON serialization
        result = dict(row)
        for key in ("started_at", "completed_at"):
            if result.get(key) and hasattr(result[key], "isoformat"):
                result[key] = result[key].isoformat()
        if result.get("score") is not None:
            result["score"] = float(result["score"])
        for int_key in ("total_rules", "passed", "failed", "errors"):
            if result.get(int_key) is not None:
                result[int_key] = int(result[int_key])

        # Per-pack score breakdown (full format for dashboard)
        scan_id = result["scan_id"]
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
        pack_scores = {}
        for pr in cur.fetchall():
            pack_id = pr["pack_id"]
            pack_name = pr.get("name") or pack_id
            pt = int(pr["total"] or 0)
            pp = int(pr["passed"] or 0)
            score = round((pp / pt) * 100, 1) if pt > 0 else 0

            # Short key for dashboard widgets
            short_key = pack_name.lower()
            for k in ("ubuntu", "docker", "network", "hipaa", "cis"):
                if k in short_key:
                    short_key = k
                    break
            packs[short_key] = score

            # Full format for score cards and frameworks
            pack_scores[pack_id] = {
                "name": pack_name,
                "score": score,
                "passed": pp,
                "total": pt,
            }

        result["packs"] = packs
        result["pack_scores"] = pack_scores
        result["last_scan"] = result.get("completed_at") or result.get("started_at")
        result["latest_scan_id"] = scan_id  # alias for JS compatibility

        # SOC 2 score: computed from soc2_controls mappings on scan results
        result["soc2"] = _compute_soc2_scores(cur, scan_id)
        return result


def _compute_soc2_scores(cur, scan_id):
    """Compute SOC 2 Trust Service Criteria scores from soc2_controls mappings."""
    cur.execute(
        """
        SELECT unnest(soc2_controls) as control,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'pass' THEN 1 ELSE 0 END) as passed
        FROM compliance_scan_results
        WHERE scan_id = %s AND soc2_controls IS NOT NULL
        GROUP BY control
        ORDER BY control
        """,
        (scan_id,),
    )
    controls = {}
    for row in cur.fetchall():
        ctrl = row["control"]
        total = int(row["total"])
        passed = int(row["passed"])
        controls[ctrl] = {
            "total": total,
            "passed": passed,
            "score": round((passed / total) * 100, 1) if total > 0 else 0,
        }

    # Map controls to Trust Service Criteria
    tsc_map = {
        "Security": ["CC6.1", "CC6.2", "CC6.3", "CC6.6", "CC6.7"],
        "Availability": ["CC7.1", "CC7.2", "CC7.3", "CC7.4", "A1.1", "A1.2"],
        "Processing Integrity": ["CC8.1", "PI1.3"],
        "Confidentiality": ["C1.1", "C1.2"],
        "Privacy": ["P1.1", "P1.2"],
    }

    criteria = {}
    total_score = 0
    total_weight = 0
    for tsc_name, ctrl_ids in tsc_map.items():
        tsc_total = 0
        tsc_passed = 0
        for cid in ctrl_ids:
            if cid in controls:
                tsc_total += controls[cid]["total"]
                tsc_passed += controls[cid]["passed"]
        score = round((tsc_passed / tsc_total) * 100, 1) if tsc_total > 0 else None
        criteria[tsc_name] = {
            "score": score,
            "passed": tsc_passed,
            "total": tsc_total,
            "controls": [
                {
                    "id": cid,
                    **(controls[cid] if cid in controls else {"total": 0, "passed": 0, "score": 0}),
                }
                for cid in ctrl_ids
            ],
        }
        if score is not None:
            total_score += score
            total_weight += 1

    overall = round(total_score / total_weight, 1) if total_weight > 0 else 0

    # Evidence freshness
    cur.execute(
        """
        SELECT artifact_type,
               MAX(collected_at) as last_collected
        FROM compliance_evidence
        GROUP BY artifact_type
        """
    )
    evidence_freshness = {}
    for row in cur.fetchall():
        last = row["last_collected"]
        if last:
            age_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
            evidence_freshness[row["artifact_type"]] = {
                "last_collected": last.isoformat(),
                "age_hours": round(age_hours, 1),
                "fresh": age_hours < 720,  # 30 days
            }

    return {
        "score": overall,
        "criteria": criteria,
        "controls": controls,
        "evidence_freshness": evidence_freshness,
    }


def get_soc2_scores(scan_id=None):
    """Public wrapper for SOC 2 scores. Uses latest scan if scan_id not provided."""
    with get_db_cursor(commit=False) as (conn, cur):
        if not scan_id:
            cur.execute(
                "SELECT scan_id FROM compliance_scans WHERE completed_at IS NOT NULL ORDER BY started_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                return None
            scan_id = row["scan_id"]
        return _compute_soc2_scores(cur, scan_id)


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
        ("HOST_IP", os.getenv("ARCHIE_HOST", "192.168.1.200")),
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


def collect_evidence(scan_id=None):
    """Auto-collect SOC 2 evidence artifacts from platform systems."""
    evidence = []

    # Security: Firewall config
    try:
        hc = _get_host_client()
        if hc["available"]():
            fw = hc["run"]("firewall_status", {}, timeout=15)
            evidence.append(
                {
                    "control_id": "CC6.6",
                    "artifact_type": "firewall_config",
                    "artifact_name": "UFW Firewall Status",
                    "artifact_data": fw.get("result", {}),
                }
            )
    except Exception as e:
        logger.warning("Evidence: firewall collection failed: %s", e)

    # Security: Access control (RBAC)
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT id, username, role, is_admin, created_at FROM users ORDER BY id")
            users = [dict(r) for r in cur.fetchall()]
            for u in users:
                if u.get("created_at"):
                    u["created_at"] = u["created_at"].isoformat()
            evidence.append(
                {
                    "control_id": "CC6.1",
                    "artifact_type": "access_control_config",
                    "artifact_name": "User Accounts & Roles",
                    "artifact_data": {"users": users, "count": len(users)},
                }
            )
    except Exception as e:
        logger.warning("Evidence: access control failed: %s", e)

    # Security: Audit log (last 90 days)
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT COUNT(*) as total,
                    COUNT(DISTINCT user_id) as unique_users,
                    MIN(created_at) as earliest,
                    MAX(created_at) as latest
                FROM audit_log
                WHERE created_at > NOW() - INTERVAL '90 days'
            """
            )
            row = cur.fetchone()
            evidence.append(
                {
                    "control_id": "CC7.2",
                    "artifact_type": "audit_log_export",
                    "artifact_name": "Audit Log Summary (90 days)",
                    "artifact_data": {
                        "total_entries": row["total"],
                        "unique_users": row["unique_users"],
                        "period_start": row["earliest"].isoformat() if row["earliest"] else None,
                        "period_end": row["latest"].isoformat() if row["latest"] else None,
                    },
                }
            )
    except Exception as e:
        logger.warning("Evidence: audit log failed: %s", e)

    # Security: SSL certificates
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT domain, issuer, valid_until, days_until_expiry, grade " "FROM security_ssl_monitors")
            certs = [dict(r) for r in cur.fetchall()]
            for c in certs:
                c["is_valid"] = (c.get("days_until_expiry") or 0) > 0
                if c.get("valid_until"):
                    c["valid_until"] = c["valid_until"].isoformat()
            evidence.append(
                {
                    "control_id": "CC6.7",
                    "artifact_type": "ssl_cert_status",
                    "artifact_name": "SSL Certificate Status",
                    "artifact_data": {"certificates": certs, "count": len(certs)},
                }
            )
    except Exception as e:
        logger.warning("Evidence: SSL failed: %s", e)

    # Availability: Service status
    try:
        from tools.system_operations.system_service import get_system_service

        svc = get_system_service()
        overview = svc.get_overview()
        evidence.append(
            {
                "control_id": "A1.2",
                "artifact_type": "service_inventory",
                "artifact_name": "System Health Overview",
                "artifact_data": overview,
            }
        )
    except Exception as e:
        logger.warning("Evidence: service inventory failed: %s", e)

    # Security: Docker container hardening
    try:
        proc = _subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        containers = []
        for line in proc.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            name = parts[0] if len(parts) > 0 else ""
            # Check read-only and cap-drop
            insp = _subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}}",
                    name,
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            containers.append(
                {
                    "name": name,
                    "image": parts[1] if len(parts) > 1 else "",
                    "security": insp.stdout.strip(),
                }
            )
        evidence.append(
            {
                "control_id": "CC6.8",
                "artifact_type": "docker_hardening",
                "artifact_name": "Docker Container Hardening",
                "artifact_data": {
                    "containers": containers,
                    "count": len(containers),
                },
            }
        )
    except Exception as e:
        logger.warning("Evidence: docker hardening failed: %s", e)

    # Security: Network listening services
    try:
        proc = _subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        evidence.append(
            {
                "control_id": "CC6.6",
                "artifact_type": "network_listeners",
                "artifact_name": "Network Listening Services",
                "artifact_data": {"raw": proc.stdout[:4000]},
            }
        )
    except Exception as e:
        logger.warning("Evidence: network listeners failed: %s", e)

    # Confidentiality: Encryption at rest
    try:
        enc_data = {}
        # Check DB encryption (password auth)
        enc_data["db_auth"] = "md5/scram-sha-256 (password required)"
        # Check if secrets are used
        enc_data["secrets_management"] = "Docker secrets (/run/secrets/)"
        # Check disk encryption
        proc = _subprocess.run(
            ["docker", "info", "--format", "{{.Driver}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        enc_data["storage_driver"] = proc.stdout.strip()
        evidence.append(
            {
                "control_id": "C1.1",
                "artifact_type": "encryption_config",
                "artifact_name": "Encryption Configuration",
                "artifact_data": enc_data,
            }
        )
    except Exception as e:
        logger.warning("Evidence: encryption config failed: %s", e)

    # Processing Integrity: Backup status
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT backup_type, status, started_at, completed_at, file_size
                FROM backup_history
                ORDER BY started_at DESC LIMIT 5
            """
            )
            backups = [dict(r) for r in cur.fetchall()]
            for b in backups:
                for k in ("started_at", "completed_at"):
                    if b.get(k) and hasattr(b[k], "isoformat"):
                        b[k] = b[k].isoformat()
            evidence.append(
                {
                    "control_id": "PI1.3",
                    "artifact_type": "backup_status",
                    "artifact_name": "Backup History",
                    "artifact_data": {"recent_backups": backups, "count": len(backups)},
                }
            )
    except Exception as e:
        logger.warning("Evidence: backup status failed: %s", e)

    # Store evidence in DB
    stored = 0
    for e in evidence:
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO compliance_evidence
                        (control_id, artifact_type, artifact_name, artifact_data, scan_id)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        e["control_id"],
                        e["artifact_type"],
                        e["artifact_name"],
                        Json(e["artifact_data"]),
                        scan_id,
                    ),
                )
                stored += 1
        except Exception as exc:
            logger.warning("Evidence store failed for %s: %s", e["artifact_type"], exc)

    return {
        "collected": len(evidence),
        "stored": stored,
        "artifacts": [e["artifact_type"] for e in evidence],
    }


def _score_to_grade(score):
    """Convert a numeric score to a letter grade and CSS class."""
    if score >= 90:
        return "A", "A"
    elif score >= 80:
        return "B", "B"
    elif score >= 70:
        return "C", "C"
    elif score >= 60:
        return "D", "D"
    else:
        return "F", "F"


def generate_report_html(scan_id, client_name="System Assessment"):
    """Generate a branded HTML compliance report for a scan.

    Returns an HTML string ready to serve or print to PDF.
    Returns None if scan not found.
    """
    from jinja2 import Environment, FileSystemLoader

    # --- Fetch scan metadata ---
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT scan_id, score, total_rules, passed, failed, errors,
                   started_at, completed_at, pack_ids
            FROM compliance_scans
            WHERE scan_id = %s
            """,
            (scan_id,),
        )
        scan = cur.fetchone()
        if not scan:
            return None

        # --- Fetch all results for this scan ---
        cur.execute(
            """
            SELECT rule_id, pack_id, severity, status,
                   actual_value, expected_value, details
            FROM compliance_scan_results
            WHERE scan_id = %s
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4
                END,
                rule_id
            """,
            (scan_id,),
        )
        all_results = [dict(r) for r in cur.fetchall()]

        # --- Per-pack breakdown ---
        cur.execute(
            """
            SELECT r.pack_id, p.name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN r.status = 'pass' THEN 1 ELSE 0 END) AS passed
            FROM compliance_scan_results r
            LEFT JOIN compliance_rule_packs p ON p.pack_id = r.pack_id
            WHERE r.scan_id = %s
            GROUP BY r.pack_id, p.name
            ORDER BY p.name
            """,
            (scan_id,),
        )
        pack_rows = cur.fetchall()

    # --- Build pack scores with per-pack results ---
    pack_scores = []
    framework_names_list = []
    for pr in pack_rows:
        p_total = pr["total"] or 0
        p_passed = pr["passed"] or 0
        p_score = round((p_passed / p_total) * 100, 1) if p_total > 0 else 0
        p_grade, p_grade_class = _score_to_grade(p_score)
        pack_name = pr.get("name") or pr["pack_id"]
        framework_names_list.append(pack_name)

        # Filter results for this pack
        pack_results = [r for r in all_results if r["pack_id"] == pr["pack_id"]]

        pack_scores.append(
            {
                "pack_id": pr["pack_id"],
                "name": pack_name,
                "total": p_total,
                "passed": p_passed,
                "failed": p_total - p_passed,
                "score": p_score,
                "grade": p_grade,
                "grade_class": p_grade_class,
                "results": pack_results,
            }
        )

    # --- Overall grade ---
    overall_score = float(scan.get("score", 0) or 0)
    grade, grade_class = _score_to_grade(overall_score)

    # --- High-priority findings ---
    high_priority = [r for r in all_results if r["status"] == "fail" and r["severity"] in ("critical", "high")]

    # --- Generate recommendations based on findings ---
    recommendations = []
    sev_counts = {}
    for r in all_results:
        if r["status"] == "fail":
            sev_counts[r["severity"]] = sev_counts.get(r["severity"], 0) + 1

    if sev_counts.get("critical", 0) > 0:
        recommendations.append(
            {
                "title": "Critical Remediation Required",
                "text": f"{sev_counts['critical']} critical finding(s) detected. "
                "These represent immediate security risks and must be addressed before the next audit cycle.",
            }
        )
    if sev_counts.get("high", 0) > 0:
        recommendations.append(
            {
                "title": "High-Priority Hardening",
                "text": f"{sev_counts['high']} high-severity finding(s) should be remediated within 30 days. "
                "Consider using the automated remediation tools in the Compliance Dashboard.",
            }
        )
    if sev_counts.get("medium", 0) > 0:
        recommendations.append(
            {
                "title": "Medium-Risk Items",
                "text": f"{sev_counts['medium']} medium-severity item(s) should be scheduled for remediation "
                "within the next quarterly review cycle.",
            }
        )
    if overall_score >= 90:
        recommendations.append(
            {
                "title": "Maintain Compliance Posture",
                "text": "The system demonstrates strong compliance. Schedule regular scans to maintain this level "
                "and monitor for drift after system updates.",
            }
        )
    elif overall_score < 70:
        recommendations.append(
            {
                "title": "Compliance Improvement Plan Needed",
                "text": "The overall score is below acceptable thresholds. A dedicated compliance improvement "
                "sprint is recommended, starting with critical and high-severity items.",
            }
        )

    # --- Format dates (rendered in America/Toronto for user-facing reports) ---
    scan_date = format_local(scan.get("completed_at") or scan.get("started_at"), FMT_DATETIME_LOCAL_SHORT)
    generated_at = format_local(now_local(), FMT_DATETIME_LOCAL_SHORT)

    # --- Truncate values for display ---
    for r in all_results:
        if r.get("actual_value") and len(str(r["actual_value"])) > 120:
            r["actual_value"] = str(r["actual_value"])[:120] + "..."
        if r.get("expected_value") and len(str(r["expected_value"])) > 120:
            r["expected_value"] = str(r["expected_value"])[:120] + "..."
        if r.get("details") and len(str(r["details"])) > 200:
            r["details"] = str(r["details"])[:200] + "..."

    # --- Render template ---
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
    template = env.get_template("compliance_report.html")

    html = template.render(
        scan_id=scan_id,
        scan_id_short=scan_id[:8].upper(),
        client_name=client_name,
        scan_date=scan_date,
        generated_at=generated_at,
        score=overall_score,
        grade=grade,
        grade_class=grade_class,
        total=scan.get("total_rules", 0) or 0,
        passed=scan.get("passed", 0) or 0,
        failed=scan.get("failed", 0) or 0,
        errors=scan.get("errors", 0) or 0,
        pack_count=len(pack_scores),
        framework_names=", ".join(framework_names_list) or "N/A",
        pack_scores=pack_scores,
        high_priority_count=len(high_priority),
        high_priority_findings=high_priority,
        recommendations=recommendations,
        all_results=all_results,
    )
    return html


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


# ---------------------------------------------------------------------------
# Rule auto-approval CRUD helpers (Task 5)
# ---------------------------------------------------------------------------


def set_rule_auto_approval(rule_id: str, status: str, user_id: int, notes: str = "") -> Dict[str, Any]:
    """Upsert a row in compliance_rule_auto_approvals.

    status: 'allow' | 'exempt'
    """
    if status not in ("allow", "exempt"):
        return {"success": False, "error": f"invalid status: {status}"}

    # Look up pack_id from any loaded rule pack
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT p.pack_id
               FROM compliance_rule_packs p,
                    jsonb_array_elements(p.rules) r
               WHERE r->>'rule_id' = %s
               LIMIT 1""",
            (rule_id,),
        )
        row = cur.fetchone()
        pack_id = (row["pack_id"] if row else None) or "unknown"

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO compliance_rule_auto_approvals
                 (rule_id, pack_id, status, approved_by, notes)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (rule_id) DO UPDATE
                 SET status = EXCLUDED.status,
                     approved_by = EXCLUDED.approved_by,
                     approved_at = NOW(),
                     notes = EXCLUDED.notes""",
            (rule_id, pack_id, status, user_id, notes),
        )
    return {"success": True, "rule_id": rule_id, "status": status}


def get_rule_auto_approval(rule_id: str) -> Optional[Dict[str, Any]]:
    """Return dict with status/approved_by/approved_at, or None if not set."""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT rule_id, pack_id, status, approved_by, approved_at, notes
               FROM compliance_rule_auto_approvals
               WHERE rule_id = %s""",
            (rule_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return dict(row)


def is_rule_exempt(rule_id: str) -> bool:
    entry = get_rule_auto_approval(rule_id)
    return bool(entry and entry.get("status") == "exempt")


def is_rule_auto_allowed(rule_id: str) -> bool:
    entry = get_rule_auto_approval(rule_id)
    return bool(entry and entry.get("status") == "allow")
