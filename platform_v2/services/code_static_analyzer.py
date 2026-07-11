"""Faithful-runtime static-analysis runner (Code Health scanner tier, Slice 1).

Runs the toolchain that found the 35 latent bugs (2026-07-11 session) — AST
interface-sweeps + pyflakes + ruff + mypy + pylint + bandit — and normalizes
everything to one finding shape for the auto-verify gate.

FAITHFUL RUNTIME: results are only trustworthy when the tools resolve imports
exactly like the deployed code does. The Slice-1 "platform" target uses
mode="local" because the deep-scan code itself already executes inside a
faithful container (archie_platform and archie_scheduler both mount the same
/app + ai_bridge with identical deps) — tools run as local subprocesses there,
which contains import side-effects and needs no docker socket. mode="docker"
(exec into another container) is the Slice-1b extension point for standalones.
NEVER fall back to a wrong-path host run — that manufactures false positives.

Deterministic tooling only — NO LLM calls in this module (verification happens
in finding_gate via the DHQ dispatcher).

Spec: docs/superpowers/specs/2026-07-11-code-health-static-analysis-scanner-tier-design.md §4.1
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

# ── Per-product runtime registry (Slice 1: platform only) ────────────────────
RUNTIME_REGISTRY: dict[str, dict] = {
    "platform": {
        "mode": "local",  # this code already runs inside the faithful container
        "app_root": "/app",  # == platform_v2 in-container
        "scan_roots": ["/app", "/mnt/archie_brain/ai_bridge"],  # file DISCOVERY roots
        # The daemon's REAL import environment (WORKDIR=/app + PYTHONPATH=
        # /mnt/archie_brain + the ai_bridge dir for bare `db` imports). Encoded
        # explicitly — resolver faithfulness must never depend on inherited env
        # (a clobbered PYTHONPATH manufactured false positives in live testing).
        "sys_path_roots": ["/app", "/mnt/archie_brain", "/mnt/archie_brain/ai_bridge"],
        "extra_sys_path": ["/mnt/archie_brain/ai_bridge"],  # bare `db` / `external_providers`
        "py_version": "3.11",
        "tool_timeout": 900,
    },
}

_DISCOVER_EXCLUDES = ("*/__pycache__/*", "*/node_modules/*", "*/.git/*", "*/tests/*", "*/migrations/*")


def pipeline_identity(runtime_path: str) -> tuple:
    """Translate a runtime file path to the (module_name, rel_file) identity that
    audit_pipeline.process_audit_findings expects — it rebuilds file_path as
    `platform_v2/tools/<module>/<file>` or `<[PLACEHOLDER]>/<file>` (see
    _audit_file_path + _PLACEHOLDER_MAP). Unknown roots return (None, path) so
    callers keep those findings advisory instead of minting a broken file_path.
    """
    tools_prefix = "/app/tools/"
    if runtime_path.startswith(tools_prefix):
        rest = runtime_path[len(tools_prefix) :]
        if "/" in rest:
            module, rel = rest.split("/", 1)
            return module, rel
    if runtime_path.startswith("/app/"):
        return "[APP_CORE]", runtime_path[len("/app/") :]
    ai_bridge_prefix = "/mnt/archie_brain/ai_bridge/"
    if runtime_path.startswith(ai_bridge_prefix):
        return "[AI_BRIDGE]", runtime_path[len(ai_bridge_prefix) :]
    return None, runtime_path


def _run_in_runtime(target: str, argv: list, extra_env: dict = None) -> subprocess.CompletedProcess:
    """The one execution seam (mocked in unit tests). Runs argv inside the
    target's faithful runtime — locally when this process already lives there,
    via docker exec for remote-container targets (Slice 1b)."""
    cfg = RUNTIME_REGISTRY[target]
    timeout = cfg.get("tool_timeout", 900)
    if cfg.get("mode") == "local":
        env = {**os.environ, **(extra_env or {})}
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cfg["app_root"], env=env)
    docker_argv = ["docker", "exec"]
    for key, value in (extra_env or {}).items():
        docker_argv.append(f"--env={key}={value}")
    docker_argv.append(cfg["container"])
    return subprocess.run(docker_argv + argv, capture_output=True, text=True, timeout=timeout)


# ── Tool runners — each returns partially-filled finding dicts ────────────────


def _require_tool(proc, name):
    """A tool missing from the runtime must surface as tools_skipped — a silent
    0-finding 'run' would read as clean coverage when nothing actually ran."""
    if proc.returncode != 0 and "No module named" in (proc.stderr or ""):
        raise RuntimeError(f"{name} is not installed in the runtime")


def _run_ast_sweeps(target: str, files: list) -> list:
    """AST interface-sweeps, executed IN the runtime via a short-lived subprocess
    (services.code_analysis.run_sweeps) so the resolver binds to the real
    sys.path and module-import side effects never touch this process."""
    cfg = RUNTIME_REGISTRY[target]
    # Resolver roots = the runtime's real import roots (sys_path_roots), NOT
    # the cwd used to load run_sweeps — keeps resolution faithful even when a
    # test overrides app_root to run the not-yet-deployed module from a bundle.
    roots = ",".join(cfg.get("sys_path_roots") or cfg["scan_roots"])
    proc = _run_in_runtime(target, ["python3", "-m", "services.code_analysis.run_sweeps", "--roots", roots, *files])
    _require_tool(proc, "ast_sweep(run_sweeps)")
    # Module imports inside the resolver may print banners to stdout; the JSON
    # payload is always the LAST line run_sweeps prints.
    stdout_lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    try:
        findings = json.loads(stdout_lines[-1] if stdout_lines else "[]")
    except ValueError:
        logger.warning("ast_sweep output was not JSON (rc=%s): %.200s", proc.returncode, proc.stderr)
        return []
    for finding in findings:
        finding["tool"] = "ast_sweep"
        finding["confidence"] = "high"
        finding.setdefault("message", finding.get("detail", ""))
    return findings


_PYFLAKES_LINE = re.compile(r"(?P<file>[^:]+):(?P<line>\d+):(?:\d+:?)?\s*(?P<msg>.+)")


def _pyflakes(target: str, files: list) -> list:
    proc = _run_in_runtime(target, ["python3", "-m", "pyflakes", *files])
    _require_tool(proc, "pyflakes")
    findings = []
    for line in (proc.stdout or "").splitlines():
        match = _PYFLAKES_LINE.match(line)
        if not match:
            continue
        msg = match.group("msg")
        is_undefined = "undefined name" in msg
        findings.append(
            {
                "file": match.group("file"),
                "line": int(match.group("line")),
                "tool": "pyflakes",
                "code": "F821" if is_undefined else "PYFLAKES",
                "severity": "red" if is_undefined else "yellow",
                "confidence": "high",
                "message": f"{msg} (line {match.group('line')})",
            }
        )
    return findings


def _ruff(target: str, files: list) -> list:
    proc = _run_in_runtime(target, ["python3", "-m", "ruff", "check", "--select=F", "--output-format=json", *files])
    _require_tool(proc, "ruff")
    try:
        rows = json.loads(proc.stdout or "[]")
    except ValueError:
        return []
    findings = []
    for row in rows:
        line = ((row.get("location") or {}).get("row")) or 0
        findings.append(
            {
                "file": row.get("filename", ""),
                "line": line,
                "tool": "ruff",
                "code": row.get("code") or "F",
                "severity": "yellow",
                "confidence": "high",
                "message": f"{row.get('message', '')} (line {line})",
            }
        )
    return findings


_MYPY_LINE = re.compile(r"(?P<file>[^:]+):(?P<line>\d+):(?:\d+:)?\s*error:\s*(?P<msg>.+?)\s*\[(?P<code>[\w-]+)\]")


def _mypy(target: str, files: list) -> list:
    cfg = RUNTIME_REGISTRY[target]
    mypypath = ":".join(cfg.get("sys_path_roots") or [cfg["app_root"], *cfg.get("extra_sys_path", [])])
    proc = _run_in_runtime(
        target,
        [
            "python3",
            "-m",
            "mypy",
            "--check-untyped-defs",
            "--follow-imports=silent",
            "--explicit-package-bases",
            "--ignore-missing-imports",
            f"--python-version={cfg['py_version']}",
            "--no-color-output",
            "--no-error-summary",
            *files,
        ],
        extra_env={"MYPYPATH": mypypath},
    )
    _require_tool(proc, "mypy")
    findings = []
    for line in (proc.stdout or "").splitlines():
        match = _MYPY_LINE.match(line)
        if not match:
            continue
        findings.append(
            {
                "file": match.group("file"),
                "line": int(match.group("line")),
                "tool": "mypy",
                "code": "TYPE_ERROR",
                "severity": "yellow",
                "confidence": "medium",
                "message": f"[{match.group('code')}] {match.group('msg')} (line {match.group('line')})",
            }
        )
    return findings


def _pylint(target: str, files: list) -> list:
    proc = _run_in_runtime(
        target,
        ["python3", "-m", "pylint", "-E", "--disable=import-error", "--output-format=json", *files],
    )
    _require_tool(proc, "pylint")
    try:
        rows = json.loads(proc.stdout or "[]")
    except ValueError:
        return []
    findings = []
    for row in rows:
        is_no_member = row.get("message-id") == "E1101"
        line = row.get("line") or 0
        findings.append(
            {
                "file": row.get("path", ""),
                "line": line,
                "tool": "pylint",
                "code": "MISSING_METHOD" if is_no_member else "PYLINT_ERROR",
                "severity": "red" if is_no_member else "yellow",
                "confidence": "medium",
                "message": f"{row.get('symbol', '')}: {row.get('message', '')} (line {line})",
            }
        )
    return findings


def _bandit(target: str, files: list) -> list:
    proc = _run_in_runtime(
        target,
        [
            "python3",
            "-m",
            "bandit",
            "-f",
            "json",
            "--severity-level",
            "medium",
            "--confidence-level",
            "medium",
            *files,
        ],
    )
    _require_tool(proc, "bandit")
    try:
        rows = (json.loads(proc.stdout or "{}") or {}).get("results", [])
    except ValueError:
        return []
    findings = []
    for row in rows:
        line = row.get("line_number") or 0
        findings.append(
            {
                "file": row.get("filename", ""),
                "line": line,
                "tool": "bandit",
                "code": "SECURITY_STATIC",
                "severity": "yellow",
                "confidence": "medium",
                "message": f"{row.get('issue_text', '')} (line {line})",
            }
        )
    return findings


# Tool name -> implementation attr. Resolved via globals() at CALL time so the
# seams stay monkeypatchable (a tuple of function refs would freeze the originals).
_TOOL_IMPLS = {
    "ast_sweep": "_run_ast_sweeps",
    "pyflakes": "_pyflakes",
    "ruff": "_ruff",
    "mypy": "_mypy",
    "pylint": "_pylint",
    "bandit": "_bandit",
}


def _discover_files(target: str) -> list:
    """Enumerate scannable .py files across the target's scan roots (in-runtime)."""
    cfg = RUNTIME_REGISTRY[target]
    excludes = " ".join(f"-not -path '{pattern}'" for pattern in _DISCOVER_EXCLUDES)
    roots = " ".join(cfg["scan_roots"])
    proc = _run_in_runtime(target, ["sh", "-c", f"find {roots} -name '*.py' {excludes}"])
    return [line for line in (proc.stdout or "").splitlines() if line.strip()]


def run(target: str = "platform", files: list = None) -> dict:
    """Run the full toolchain over the target. A tool crash/timeout skips that
    tool and is reported in coverage — the scan never silently truncates and
    never fails wholesale. Returns {target, findings, coverage}."""
    if target not in RUNTIME_REGISTRY:
        raise ValueError(f"unknown scan target: {target}")
    files = files or _discover_files(target)
    findings: list = []
    tools_run: list = []
    tools_skipped: list = []

    for name, impl_name in _TOOL_IMPLS.items():
        tool_fn = globals()[impl_name]
        try:
            raw = tool_fn(target, files)
        except Exception as exc:  # partial coverage, surfaced explicitly
            tools_skipped.append(f"{name}: {exc}")
            logger.warning("static scan tool %s skipped on %s: %s", name, target, exc)
            continue
        for finding in raw:
            finding.setdefault("tool", name)
            finding.setdefault("confidence", "medium")
            finding["target"] = target
            module, rel_file = pipeline_identity(finding.get("file", ""))
            finding["module"] = module
            finding["rel_file"] = rel_file
            finding["capability"] = (
                "security" if (finding["tool"] == "bandit" or finding.get("code") == "SECURITY_STATIC") else "code"
            )
            findings.append(finding)
        tools_run.append(name)

    logger.info(
        "static scan of %s: %d findings over %d files (%d tools ran, %d skipped)",
        target,
        len(findings),
        len(files),
        len(tools_run),
        len(tools_skipped),
    )
    return {
        "target": target,
        "findings": findings,
        "coverage": {"tools_run": tools_run, "tools_skipped": tools_skipped},
    }
