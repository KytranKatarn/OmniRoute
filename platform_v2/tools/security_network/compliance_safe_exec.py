"""Compliance safe-execution gate.

Single code path for applying any compliance fix:
  snapshot → apply → health gate → rollback on failure.

Used by both:
  - Repair Bay manual-click flow (proposal_routes.proposals_execute)
  - Sunday maintenance-window auto-apply (jobs.run_auto_apply_window)

Only fix types (sysctl, file_line, service) are supported — command
types are rejected here and must be run via the existing
compliance_service.apply_fix code path after an admin click.
"""

import hashlib
import json
import logging
import subprocess
from typing import Any, Dict, Tuple

from database import get_db_cursor

logger = logging.getLogger(__name__)

SAFE_FIX_TYPES = frozenset(("sysctl", "file_line", "service"))
HEALTH_GATE_WAIT_SECONDS = 10
COMPLIANCE_SYSCTL_CONF = "/etc/sysctl.d/99-compliance.conf"


def _snapshot_sysctl(fix_def: Dict[str, Any]) -> Dict[str, Any]:
    """Read current sysctl value so we can restore it on rollback.

    fix_def example: {"type": "sysctl", "param": "net.ipv4.ip_forward", "value": "0"}
    """
    param = fix_def.get("param")
    if not param:
        raise ValueError(f"sysctl fix_def missing 'param': {fix_def}")

    result = subprocess.run(
        ["sysctl", "-n", param],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to read sysctl {param}: {result.stderr}")

    return {
        "fix_type": "sysctl",
        "param": param,
        "prev_value": result.stdout.strip(),
        "had_compliance_conf": _file_exists(COMPLIANCE_SYSCTL_CONF),
    }


def _file_exists(path: str) -> bool:
    import os

    return os.path.exists(path)


def _snapshot_file(fix_def: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot a file before editing so we can restore byte-exact on rollback.

    fix_def example: {"type": "file_line", "path": "/etc/ssh/sshd_config",
                      "line": "X11Forwarding no", "restart_service": "sshd"}
    """
    path = fix_def.get("path")
    if not path:
        raise ValueError(f"file_line fix_def missing 'path': {fix_def}")

    try:
        with open(path, "rb") as fh:
            content = fh.read()
        sha = hashlib.sha256(content).hexdigest()
        existed = True
    except FileNotFoundError:
        content = b""
        sha = ""
        existed = False

    return {
        "fix_type": "file_line",
        "path": path,
        "prev_content": content,
        "prev_sha256": sha,
        "existed": existed,
        "restart_service": fix_def.get("restart_service"),
    }


def _snapshot_service(fix_def: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot systemd service enabled/active state.

    fix_def example: {"type": "service", "service": "avahi-daemon",
                      "action": "disable"}
    """
    svc = fix_def.get("service")
    if not svc:
        raise ValueError(f"service fix_def missing 'service': {fix_def}")

    enabled_res = subprocess.run(
        ["systemctl", "is-enabled", svc],
        capture_output=True,
        text=True,
        timeout=5,
    )
    active_res = subprocess.run(
        ["systemctl", "is-active", svc],
        capture_output=True,
        text=True,
        timeout=5,
    )
    enabled = enabled_res.stdout.strip()
    active = active_res.stdout.strip()
    # systemctl `is-enabled`/`is-active` return non-zero for inactive/disabled
    # states, so a nonzero rc alone is NOT a failure. But empty stdout means
    # systemctl itself failed (missing, permission error) and the snapshot
    # would be meaningless — refuse to proceed rather than silently record
    # a bogus pre-state we cannot roll back to.
    if not enabled or not active:
        raise RuntimeError(
            f"systemctl status unreadable for {svc}: "
            f"enabled={enabled!r} active={active!r} "
            f"stderr_enabled={enabled_res.stderr.strip()!r} "
            f"stderr_active={active_res.stderr.strip()!r}"
        )

    return {
        "fix_type": "service",
        "service": svc,
        "prev_enabled": enabled,
        "prev_active": active,
    }


def _snapshot(fix_def: Dict[str, Any]) -> Dict[str, Any]:
    fix_type = fix_def.get("type")
    if fix_type == "sysctl":
        return _snapshot_sysctl(fix_def)
    if fix_type == "file_line":
        return _snapshot_file(fix_def)
    if fix_type == "service":
        return _snapshot_service(fix_def)
    raise ValueError(f"Unsupported fix_type for safe execution: {fix_type}. " f"Supported: {SAFE_FIX_TYPES}")


def _rollback_sysctl(snap: Dict[str, Any]) -> None:
    param = snap["param"]
    prev = snap["prev_value"]
    logger.warning("Rolling back sysctl %s → %s", param, prev)
    subprocess.run(
        ["sysctl", "-w", f"{param}={prev}"],
        check=True,
        timeout=5,
    )
    # The compliance auto-apply path writes /etc/sysctl.d/99-compliance.conf.
    # If the file did not exist before the fix, remove it so the change
    # does not persist across reboot.
    if not snap.get("had_compliance_conf") and _file_exists(COMPLIANCE_SYSCTL_CONF):
        import os

        os.remove(COMPLIANCE_SYSCTL_CONF)
        logger.warning("Removed %s", COMPLIANCE_SYSCTL_CONF)


def _rollback_file(snap: Dict[str, Any]) -> None:
    path = snap["path"]
    logger.warning("Rolling back file %s (sha=%s)", path, snap["prev_sha256"][:8])
    if not snap["existed"]:
        import os

        if _file_exists(path):
            os.remove(path)
        return
    with open(path, "wb") as fh:
        fh.write(snap["prev_content"])
    svc = snap.get("restart_service")
    if svc:
        subprocess.run(
            ["systemctl", "restart", svc],
            check=True,
            timeout=10,
        )


def _rollback_service(snap: Dict[str, Any]) -> None:
    svc = snap["service"]
    prev_enabled = snap["prev_enabled"]
    prev_active = snap["prev_active"]
    logger.warning(
        "Rolling back service %s → enabled=%s active=%s",
        svc,
        prev_enabled,
        prev_active,
    )
    if prev_enabled == "enabled":
        subprocess.run(["systemctl", "enable", svc], check=False, timeout=10)
    else:
        subprocess.run(["systemctl", "disable", svc], check=False, timeout=10)
    if prev_active == "active":
        subprocess.run(["systemctl", "start", svc], check=False, timeout=10)
    else:
        subprocess.run(["systemctl", "stop", svc], check=False, timeout=10)


def _rollback(snap: Dict[str, Any]) -> None:
    fix_type = snap["fix_type"]
    if fix_type == "sysctl":
        return _rollback_sysctl(snap)
    if fix_type == "file_line":
        return _rollback_file(snap)
    if fix_type == "service":
        return _rollback_service(snap)
    raise ValueError(f"Cannot roll back unknown fix_type: {fix_type}")


def _count_containers() -> int:
    result = subprocess.run(
        ["docker", "ps", "-q"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker ps failed: {result.stderr}")
    return len([ln for ln in result.stdout.splitlines() if ln.strip()])


def _curl_ok(url: str, timeout: int = 5) -> bool:
    try:
        result = subprocess.run(
            ["curl", "-f", "-sS", "-m", str(timeout), url],
            capture_output=True,
            timeout=timeout + 2,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def _docker_exec_curl_ok(container: str, url: str, timeout: int = 5) -> bool:
    try:
        result = subprocess.run(
            ["docker", "exec", container, "curl", "-f", "-sS", "-m", str(timeout), url],
            capture_output=True,
            timeout=timeout + 5,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def _run_probe_smoke() -> Tuple[bool, str]:
    """Run the compliance-smoke P.R.O.B.E. suite. Returns (passed, detail)."""
    try:
        from services.qa_service import run_qa_suite  # type: ignore
    except ImportError:
        try:
            from services.probe_service import run_qa_suite  # type: ignore
        except ImportError:
            logger.error("run_qa_suite not importable — treating as FAIL")
            return False, "run_qa_suite import failed"

    try:
        result = run_qa_suite("compliance-smoke")
    except Exception as exc:
        logger.error("compliance-smoke suite raised: %s", exc)
        return False, f"suite error: {exc}"

    status = (result or {}).get("status", "unknown")
    return status == "passed", json.dumps(result)[:500]


def _health_gate(baseline_container_count: int) -> Tuple[bool, str]:
    """All four checks must pass. Returns (ok, first_failure_detail).

    Blanket-catches any exception (including subprocess.TimeoutExpired from
    helpers that don't already swallow it, and RuntimeError from
    _count_containers) and converts it into a FAILED health gate so that
    _safe_execute_fix always reaches the rollback branch rather than
    propagating the exception and leaving the system in an undefined state.
    """
    try:
        if not _curl_ok("http://localhost:3000/health", timeout=5):
            return False, "dashboard /health not reachable"

        current = _count_containers()
        if current != baseline_container_count:
            return False, f"container count changed: {baseline_container_count} → {current}"

        if not _docker_exec_curl_ok("archie_platform", "https://www.google.com", timeout=5):
            return False, "container → internet reachability failed (forwarding broken?)"

        probe_ok, probe_detail = _run_probe_smoke()
        if not probe_ok:
            return False, f"P.R.O.B.E. compliance-smoke failed: {probe_detail}"

        return True, "all checks green"
    except Exception as exc:
        logger.exception("health gate raised unexpectedly — treating as FAIL")
        return False, f"health gate exception: {type(exc).__name__}: {exc}"


def _load_proposal(proposal_id: int) -> Dict[str, Any]:
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, category, status, metadata
               FROM improvement_proposals
               WHERE id = %s""",
            (proposal_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"proposal {proposal_id} not found")
        meta = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
        return {
            "id": row["id"],
            "category": row["category"],
            "status": row["status"],
            "metadata": meta,
        }


def _mark_proposal(proposal_id: int, status: str, note: str) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE improvement_proposals
               SET status = %s,
                   reviewed_at = NOW(),
                   metadata = metadata || %s::jsonb
               WHERE id = %s""",
            (status, json.dumps({"safe_exec_note": note}), proposal_id),
        )


def _fire_rollback_failed_alert(rule_id: str, snap: Dict[str, Any], detail: str) -> None:
    """Best-effort Telegram alert when rollback itself fails.
    Never raises — rollback-failed is already the worst case."""
    try:
        from services.telegram_service import send_security

        msg = (
            f"Rule: {rule_id}\n"
            f"Snapshot: {json.dumps({k: str(v)[:80] for k, v in snap.items()})}\n"
            f"Detail: {detail}\n\n"
            f"MANUAL INTERVENTION REQUIRED."
        )
        send_security("Compliance Rollback Failed", msg, source_module="compliance_safe_exec")
    except Exception as exc:
        logger.error("Failed to send rollback-failed telegram: %s", exc)


def _safe_execute_fix(proposal_id: int, user_id: int) -> Dict[str, Any]:
    """Single safety gate for compliance fixes.

    Returns: {success: bool, status: str, detail: str, proposal_id: int}
    """
    import time
    from tools.security_network import compliance_service

    proposal = _load_proposal(proposal_id)
    if proposal["category"] != "compliance_fix":
        return {
            "success": False,
            "status": "not_compliance_fix",
            "detail": f"category={proposal['category']}",
            "proposal_id": proposal_id,
        }

    meta = proposal["metadata"]
    rule_id = meta.get("rule_id")
    scan_id = meta.get("scan_id")
    fix_def = meta.get("fix_def") or {}
    fix_type = fix_def.get("type")

    if fix_type not in SAFE_FIX_TYPES:
        return {
            "success": False,
            "status": "rejected",
            "detail": f"fix_type={fix_type} not in {sorted(SAFE_FIX_TYPES)}",
            "proposal_id": proposal_id,
        }

    # 1. Snapshot
    try:
        snap = _snapshot(fix_def)
    except Exception as exc:
        _mark_proposal(proposal_id, "failed", f"snapshot error: {exc}")
        return {"success": False, "status": "snapshot_failed", "detail": str(exc), "proposal_id": proposal_id}

    baseline_containers = _count_containers()

    # 2. Apply via existing code path
    try:
        apply_result = compliance_service.apply_fix_approved(scan_id, rule_id, user_id)
    except Exception as exc:
        logger.error("apply_fix_approved raised for %s: %s", rule_id, exc)
        apply_result = {"success": False, "error": str(exc)}

    if not apply_result.get("success"):
        _mark_proposal(proposal_id, "failed", f"apply_fix_approved returned {apply_result.get('error', 'unknown')}")
        return {
            "success": False,
            "status": "apply_failed",
            "detail": apply_result.get("error", "unknown"),
            "proposal_id": proposal_id,
        }

    # 3. Wait, then run health gate
    time.sleep(HEALTH_GATE_WAIT_SECONDS)
    ok, detail = _health_gate(baseline_containers)

    if ok:
        _mark_proposal(proposal_id, "resolved", "safe_exec green")
        return {"success": True, "status": "resolved", "detail": "health gate green", "proposal_id": proposal_id}

    # 4. Health failed — roll back
    logger.error("Health gate failed after applying %s: %s — rolling back", rule_id, detail)
    try:
        _rollback(snap)
    except Exception as rb_exc:
        _mark_proposal(proposal_id, "rollback_failed", f"apply ok but rollback raised: {rb_exc}")
        _fire_rollback_failed_alert(rule_id, snap, f"{detail} / rollback raised: {rb_exc}")
        return {"success": False, "status": "rollback_failed", "detail": str(rb_exc), "proposal_id": proposal_id}

    # Rollback ran — re-check health
    time.sleep(HEALTH_GATE_WAIT_SECONDS)
    ok2, detail2 = _health_gate(baseline_containers)
    if ok2:
        _mark_proposal(proposal_id, "rolled_back", f"health gate failed ({detail}); rollback green")
        return {"success": False, "status": "rolled_back", "detail": detail, "proposal_id": proposal_id}

    _mark_proposal(proposal_id, "rollback_failed", f"health still red after rollback: {detail2}")
    _fire_rollback_failed_alert(rule_id, snap, f"post-rollback health red: {detail2}")
    return {"success": False, "status": "rollback_failed", "detail": detail2, "proposal_id": proposal_id}
