"""F.O.R.G.E. — Dependency Drift Detector.

Single source of truth for the nightly ``requirements.txt`` vs running
container comparison introduced in Project #272 Phase 2 / Task #2109.
Catches the class of bug where a package is declared in
``platform_v2/requirements.txt`` but missing from (or mismatched with)
the running ``archie_platform`` image — the exact failure mode that
surfaced as ``langdetect not installed`` during the 2026-04-18
translation-coverage session (#2097 in project #232).

Callers
-------
1. MCP tool ``mcp__archie__check_dep_drift`` — invocable on demand.
2. Agent-loop job ``forge_dep_drift`` — scheduled daily.
3. Future Dev HQ observers — can read ``autonomy_loop_log`` rows
   written by the agent-loop job.

Detected classes
----------------
1. **Missing** — package pinned in ``requirements.txt`` but NOT in
   ``pip freeze``. Container is behind the source of truth — a new
   image build is required before that code path can run.
2. **Version mismatch** — package in both, different versions. Image
   is ahead or behind what reqs says.
3. **Unpinned in requirements** — requirement uses ``>=`` / ``~=`` /
   no pin, which lets pip floating-version the runtime. Not a drift
   per se, but a drift *risk* — logged at info level.

We deliberately do **not** flag "extras" (packages in ``pip freeze``
that aren't in ``requirements.txt``). Nearly all of them are transitive
dependencies of pinned top-level packages, and listing ~200 of them
every run drowns the real signal.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# requirements.txt location varies by context:
#   • Inside the container: /app/requirements.txt  (COPY . . puts it at repo root)
#   • On the host / dev: /mnt/archie_brain/platform_v2/requirements.txt
# Probe all known locations in priority order; fall back to the first candidate
# so callers receive a meaningful "file not found" rather than requirements_count=0.
_REQUIREMENTS_CANDIDATES = [
    REPO_ROOT / "requirements.txt",  # container: /app/requirements.txt
    REPO_ROOT / "platform_v2" / "requirements.txt",  # host dev tree
    Path("/app/requirements.txt"),  # explicit container fallback
]
DEFAULT_REQUIREMENTS = next(
    (p for p in _REQUIREMENTS_CANDIDATES if p.exists()),
    _REQUIREMENTS_CANDIDATES[0],  # keep first as sentinel so error message is clear
)

# Container name to introspect when we're not inside Docker ourselves.
CONTAINER_NAME = os.getenv("ARCHIE_PLATFORM_CONTAINER", "archie_platform")

# PEP 503 normalization — lowercase + non-alphanumeric runs collapsed to
# a single hyphen. ``Flask_Login``, ``flask-login``, and ``flask.login``
# all normalize to ``flask-login``.
_NORMALIZE_RE = re.compile(r"[-_.]+")


def _normalize(name: str) -> str:
    return _NORMALIZE_RE.sub("-", name.strip().lower())


_VERSION_PIN_RE = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._\-\[\]]*)\s*" r"(==|>=|<=|~=|!=|>|<)?\s*([A-Za-z0-9._\-\+]*)\s*(?:;.*)?$"
)


def _parse_requirements_line(line: str) -> Tuple[str, str, str] | None:
    """Parse one line of requirements.txt.

    Returns ``(normalized_name, operator, version)`` or ``None`` if the
    line is a comment / blank / `-r other.txt` / `-e .` / unparseable.
    ``operator`` is ``""`` when no version pin is present.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith("-"):
        return None
    # Strip trailing inline comment
    if "#" in stripped:
        stripped = stripped.split("#", 1)[0].strip()
    match = _VERSION_PIN_RE.match(stripped)
    if not match:
        return None
    name, op, ver = match.group(1), match.group(2) or "", match.group(3) or ""
    # Drop extras like ``psycopg2[binary]`` for the key, keep for display later.
    name_key = name.split("[")[0]
    return _normalize(name_key), op, ver


def _load_requirements(path: Path) -> Dict[str, Dict[str, str]]:
    """Return ``{normalized_name: {"op": ..., "version": ..., "raw": ...}}``."""
    reqs: Dict[str, Dict[str, str]] = {}
    if not path.exists():
        return reqs
    for raw in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_requirements_line(raw)
        if not parsed:
            continue
        name, op, ver = parsed
        reqs[name] = {"op": op, "version": ver, "raw": raw.strip()}
    return reqs


def _get_installed_packages() -> Dict[str, str]:
    """Run ``pip freeze`` against the running archie_platform environment.

    Inside the container (``/.dockerenv`` present) we call ``pip freeze``
    directly. From the host (MCP server, ad-hoc invocation) we shell
    out to ``docker exec`` so we introspect the actual running image,
    not whatever the host happens to have.

    Returns ``{normalized_name: version}``.
    """
    if os.path.exists("/.dockerenv"):
        cmd = ["pip", "freeze", "--disable-pip-version-check"]
    else:
        cmd = ["docker", "exec", CONTAINER_NAME, "pip", "freeze", "--disable-pip-version-check"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    except FileNotFoundError as e:
        raise RuntimeError(f"pip freeze invocation failed: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"pip freeze timed out: {e}") from e

    if result.returncode != 0:
        raise RuntimeError(f"pip freeze exited {result.returncode}: {result.stderr.strip()[:200]}")

    installed: Dict[str, str] = {}
    for raw in result.stdout.splitlines():
        parsed = _parse_requirements_line(raw)
        if not parsed:
            continue
        name, op, ver = parsed
        # ``pip freeze`` always emits ``==`` pins (or ``@ file://`` for
        # editable installs which we skip). If no version parsed, skip.
        if not ver:
            continue
        installed[name] = ver
    return installed


def _compute_severity(findings: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    missing = len(findings["missing"])
    mismatched = len(findings["version_mismatch"])
    unpinned = len(findings["unpinned_in_requirements"])

    severity = "info"
    reasons: List[str] = []
    if missing > 0:
        severity = "error"
        reasons.append(f"{missing} package(s) in requirements.txt not installed " f"— rebuild required")
    if mismatched > 0 and severity != "error":
        severity = "warning"
    if mismatched > 0:
        reasons.append(f"{mismatched} version mismatch(es)")
    # Unpinned requirements are informational only — never escalate
    # severity on their own. Lots of platform packages use ``>=`` pins
    # deliberately (Google APIs, OpenAI, Anthropic, etc.) to pick up
    # security patches. We still surface the count in the summary.
    if unpinned > 0:
        reasons.append(f"{unpinned} unpinned requirement(s) (informational)")

    return {
        "severity": severity,
        "anomaly_count": missing + mismatched + unpinned,
        "summary_metrics": {
            "missing": missing,
            "version_mismatch": mismatched,
            "unpinned_in_requirements": unpinned,
        },
        "reasons": reasons,
    }


def check_dep_drift(requirements_path: str | os.PathLike | None = None) -> Dict[str, Any]:
    """Compare requirements.txt against the running container's pip freeze.

    Args:
        requirements_path: Override for the source-of-truth file.
            Defaults to ``platform_v2/requirements.txt``.

    Returns a structured findings payload — caller decides what to do
    with it (log, notify, render).
    """
    path = Path(requirements_path) if requirements_path else DEFAULT_REQUIREMENTS
    reqs = _load_requirements(path)
    installed = _get_installed_packages()

    missing: List[Dict[str, Any]] = []
    mismatched: List[Dict[str, Any]] = []
    unpinned: List[Dict[str, Any]] = []

    for name, meta in sorted(reqs.items()):
        op = meta["op"]
        required_version = meta["version"]
        installed_version = installed.get(name)

        if op != "==" or not required_version:
            if required_version:
                unpinned.append(
                    {
                        "package": name,
                        "declared": meta["raw"],
                        "installed_version": installed_version,
                    }
                )
            continue

        if installed_version is None:
            missing.append(
                {
                    "package": name,
                    "required_version": required_version,
                    "declared": meta["raw"],
                }
            )
        elif installed_version != required_version:
            mismatched.append(
                {
                    "package": name,
                    "required_version": required_version,
                    "installed_version": installed_version,
                    "declared": meta["raw"],
                }
            )

    findings = {
        "missing": missing,
        "version_mismatch": mismatched,
        "unpinned_in_requirements": unpinned,
    }
    severity = _compute_severity(findings)
    return {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "requirements_path": str(path),
        "container": CONTAINER_NAME,
        "requirements_count": len(reqs),
        "installed_count": len(installed),
        "findings": findings,
        **severity,
    }


def format_alert_message(result: Dict[str, Any]) -> str:
    """Compact Telegram / system-notifications message from a check_dep_drift result."""
    metrics = result["summary_metrics"]
    lines = [
        "F.O.R.G.E. — dependency drift audit",
        f"Severity: *{result['severity'].upper()}* · " f"{result['anomaly_count']} drift item(s)",
        "",
        f"• missing from container: {metrics['missing']}",
        f"• version mismatches: {metrics['version_mismatch']}",
        f"• unpinned in requirements: {metrics['unpinned_in_requirements']}",
    ]
    # Include the first few missing packages by name — that's the single
    # most actionable signal and fits in a Telegram snippet.
    if result["findings"]["missing"]:
        lines.append("")
        lines.append("Missing:")
        for item in result["findings"]["missing"][:5]:
            lines.append(f"  – {item['package']}=={item['required_version']}")
        if len(result["findings"]["missing"]) > 5:
            lines.append(f"  …and {len(result['findings']['missing']) - 5} more")
    if result.get("reasons"):
        lines.append("")
        lines.append("Reasons:")
        for reason in result["reasons"]:
            lines.append(f"  – {reason}")
    return "\n".join(lines)
