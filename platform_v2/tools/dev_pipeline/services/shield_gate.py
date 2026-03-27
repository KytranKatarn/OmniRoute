"""S.H.I.E.L.D. compliance gate -- validates fixes before auto-merge."""

import logging
from typing import Dict

logger = logging.getLogger(__name__)

SUSPICIOUS_FILES = {".env", "secrets.json", "credentials.json", ".secrets", "id_rsa", "id_ed25519"}
MAX_BUMP_DIFF_LINES = 20
MANIFEST_FILES = {
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "go.mod",
    "go.sum",
    "Gemfile",
    "Gemfile.lock",
    "Cargo.toml",
    "Cargo.lock",
}


def _check_tests_passed(report: Dict) -> tuple:
    if not report.get("test_passed", False):
        return False, "Tests failed -- fix must pass full test suite before merge"
    return True, ""


def _check_suspicious_files(report: Dict) -> tuple:
    changed = set(report.get("files_changed", []))
    suspicious = changed & SUSPICIOUS_FILES
    if suspicious:
        return False, f"Suspicious files in diff: {', '.join(suspicious)} -- possible secret exposure"
    return True, ""


def _check_diff_scope(report: Dict) -> tuple:
    changed = set(report.get("files_changed", []))
    diff_lines = report.get("diff_lines", 0)
    non_manifest = {f for f in changed if f.split("/")[-1] not in MANIFEST_FILES}
    if non_manifest:
        return False, f"Non-manifest files changed: {', '.join(non_manifest)} -- scope exceeds version bump"
    if diff_lines > MAX_BUMP_DIFF_LINES:
        return False, f"Diff too large ({diff_lines} lines) for a version bump -- review manually"
    return True, ""


def validate_fix(report: Dict) -> Dict:
    """Run S.H.I.E.L.D. validation checks on a proposed fix.

    Args:
        report: Dict with keys: repair_item_id, pr_number, package_name,
                old_version, new_version, test_passed, files_changed, diff_lines

    Returns: {"approved": bool, "reason": str, "checks": [...]}
    """
    checks = []
    all_passed = True

    for check_fn in [_check_tests_passed, _check_suspicious_files, _check_diff_scope]:
        passed, reason = check_fn(report)
        check_name = check_fn.__name__.replace("_check_", "")
        checks.append({"check": check_name, "passed": passed, "reason": reason})
        if not passed:
            all_passed = False

    result = {
        "approved": all_passed,
        "repair_item_id": report.get("repair_item_id"),
        "pr_number": report.get("pr_number"),
        "checks": checks,
    }

    if not all_passed:
        failed = [c for c in checks if not c["passed"]]
        result["reason"] = failed[0]["reason"]
        logger.warning(
            "S.H.I.E.L.D. REJECTED fix for %s (PR #%s): %s",
            report.get("package_name"),
            report.get("pr_number"),
            result["reason"],
        )
    else:
        result["reason"] = "All checks passed"
        logger.info(
            "S.H.I.E.L.D. APPROVED fix for %s (PR #%s)",
            report.get("package_name"),
            report.get("pr_number"),
        )

    return result
