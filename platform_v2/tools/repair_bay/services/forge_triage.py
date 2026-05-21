"""F.O.R.G.E. triage: determine fix strategy and dispatch to Engineering agents."""

import re
import logging
from typing import Dict, Optional

from tools.repair_bay.services.dependabot_service import update_repair_item

logger = logging.getLogger(__name__)


def _get_current_version(package_name: str, manifest_path: str) -> Optional[str]:
    """Read current pinned version from a manifest file."""
    try:
        full_path = f"/mnt/archie_brain/{manifest_path}"
        with open(full_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                match = re.match(
                    rf"^{re.escape(package_name)}\s*[=~<>!]+\s*([\d.]+)",
                    line,
                    re.IGNORECASE,
                )
                if match:
                    return match.group(1)
    except (FileNotFoundError, PermissionError):
        pass
    return None


def _is_major_upgrade(current: str, target: str) -> bool:
    """Check if target is a major version bump from current."""
    if not current or not target:
        return False
    try:
        cur_major = int(current.split(".")[0])
        tgt_major = int(target.split(".")[0])
        return tgt_major > cur_major
    except (ValueError, IndexError):
        return False


def determine_fix_strategy(alert: Dict) -> Dict:
    """Determine how to fix a vulnerability alert.

    Returns: {"action": "version_bump"|"major_upgrade"|"no_fix", ...}
    """
    fix_version = alert.get("fix_version")

    if not fix_version:
        return {
            "action": "no_fix",
            "reason": "No patched version available",
            "package": alert.get("package_name"),
        }

    current = _get_current_version(alert["package_name"], alert.get("manifest_path", ""))

    if _is_major_upgrade(current, fix_version):
        return {
            "action": "major_upgrade",
            "package": alert["package_name"],
            "current_version": current,
            "target_version": fix_version,
            "reason": f"Major version upgrade {current} -> {fix_version} requires review",
        }

    return {
        "action": "version_bump",
        "package": alert["package_name"],
        "current_version": current,
        "target_version": fix_version,
        "manifest_path": alert.get("manifest_path"),
    }


def _dispatch_fix(alert: Dict, strategy: Dict) -> Dict:
    """Dispatch fix to an Engineering staff agent via Bridge."""
    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        prompt = (
            f"Fix vulnerability in {strategy['package']}: "
            f"bump from {strategy.get('current_version', 'unknown')} "
            f"to {strategy['target_version']} in {strategy.get('manifest_path')}. "
            f"Update the version pin, run tests, and report results."
        )
        dispatcher = get_dispatcher()
        result = dispatcher.dispatch(
            capability="code_fix",
            prompt=prompt,
            module_id="repair_bay",
            system_prompt=(
                "You are an Engineering staff agent working for F.O.R.G.E. "
                "Fix the dependency vulnerability by bumping the version in the manifest file. "
                "Verify the fix doesn't break imports or tests."
            ),
        )
        return {"success": result.success, "response": result.response}
    except Exception as e:
        logger.error("Bridge dispatch failed: %s", e)
        return {"success": False, "error": str(e)}


def triage_alert(alert: Dict) -> Dict:
    """Triage a single repair queue item."""
    item_id = alert["id"]
    strategy = determine_fix_strategy(alert)

    if strategy["action"] == "no_fix":
        update_repair_item(item_id, status="dismissed", dismiss_reason="no_fix_available")
        logger.info("Alert %d dismissed: no fix for %s", item_id, alert.get("package_name"))
        return {"success": True, "action": "dismissed", "reason": strategy["reason"]}

    if strategy["action"] == "major_upgrade":
        update_repair_item(item_id, status="escalated")
        logger.info("Alert %d escalated: major upgrade for %s", item_id, alert.get("package_name"))
        return {"success": True, "action": "escalated", "reason": strategy["reason"]}

    # version_bump — dispatch to staff agent
    update_repair_item(item_id, status="in_progress", assigned_agent="F.O.R.G.E.")
    dispatch_result = _dispatch_fix(alert, strategy)

    if dispatch_result["success"]:
        return {"success": True, "action": "dispatched", "strategy": strategy}
    else:
        update_repair_item(item_id, status="failed")
        return {"success": False, "action": "dispatch_failed", "error": dispatch_result.get("error")}


def triage_pending_queue() -> Dict:
    """Triage all pending items in the repair queue."""
    from tools.repair_bay.services.dependabot_service import get_repair_queue

    pending = get_repair_queue(status="pending")
    if not pending["success"]:
        return pending

    results = {"dispatched": 0, "escalated": 0, "dismissed": 0, "failed": 0}
    for item in pending["items"]:
        result = triage_alert(item)
        action = result.get("action", "failed")
        if action in results:
            results[action] += 1

    return {"success": True, **results}
