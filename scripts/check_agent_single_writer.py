#!/usr/bin/env python3
"""K.I.N. Single-Writer & Architecture Guardrails.

THREE classes of violations are rejected:

1. **agents-table single writer** — any raw ``UPDATE agents``,
   ``INSERT INTO agents``, or ``DELETE FROM agents WHERE`` statement
   outside of ``platform_v2/services/agent_service.py`` and tests.
   Part of Project #241 Track C.4.

2. **Dispatcher import path** — any ``from ai_bridge.bridge_dispatcher``
   / ``from ai_bridge.orchestration_engine`` / ``from ai_bridge.smart_router``
   import. The real modules live at
   ``platform_v2.tools.department_hq.services.*`` since Project #244
   Phase 2. The ai_bridge paths are back-compat shims only — new code
   must import from the canonical location.

3. **Raw api/generate or api/chat outside build_options + allowlist** —
   every dispatcher-initiated inference must flow through
   ``tools.department_hq.services.ollama_options.build_options()`` so
   GPU placement is explicit and observable.
   Spec: docs/superpowers/specs/2026-04-19-dispatcher-gpu-awareness-design.md
   Phase 1 of Project #261 #2079.

Usage:
    python3 scripts/check_agent_single_writer.py file1.py file2.py ...

Exits 0 clean, exits 1 with actionable error output listing every
violation and the migration path.

Hooks:
    - .pre-commit-config.yaml (runs on changed files at commit time)
    - .github/workflows/single-writer-guardrail.yml (runs on PR diff)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# ---- Check 1: raw agents-table writes ---------------------------------------
# Permissive regex — case-insensitive + whitespace-tolerant so multi-line
# and indented forms get caught (the original audit missed three such sites
# during Tracks C.1-C.3).
AGENTS_WRITE_RE = re.compile(
    r"(?ix)"
    r"(?:"
    r"  UPDATE\s+agents\s+SET"
    r"| INSERT\s+INTO\s+agents\s*\("
    r"| DELETE\s+FROM\s+agents\s+WHERE"
    r")"
)

# ---- Check 2: stale ai_bridge dispatcher imports ----------------------------
# Fires on `from ai_bridge.bridge_dispatcher import X`,
# `import ai_bridge.bridge_dispatcher`, and the bare `from bridge_dispatcher`
# sys.path-hack variant. The real modules live in department_hq/services/ —
# the ai_bridge/ paths are shims during the transition window.
DISPATCHER_IMPORT_RE = re.compile(
    r"(?x)"
    r"(?:"
    r"  from\s+ai_bridge\.(bridge_dispatcher|orchestration_engine|smart_router)"
    r"| import\s+ai_bridge\.(bridge_dispatcher|orchestration_engine|smart_router)"
    r")"
)

# Allow-list for Check 1 (agents writes)
ALLOWED_AGENTS_PATHS = (
    "platform_v2/services/agent_service.py",
    "scripts/check_agent_single_writer.py",
    "/tests/",
)

# Allow-list for Check 2 (dispatcher imports)
# The shim files themselves need to re-export from the new location, so
# they're allowed to reference the new path.
ALLOWED_DISPATCHER_PATHS = (
    "ai_bridge/bridge_dispatcher.py",  # the shim itself
    "ai_bridge/orchestration_engine.py",  # the shim itself
    "ai_bridge/smart_router.py",  # the shim itself
    "scripts/check_agent_single_writer.py",
    "/tests/",
    "platform_v2/tools/department_hq/services/",  # the real modules
)

# ---- Check 3: raw api/generate outside ollama_options + allowlist -----------
# Spec: docs/superpowers/specs/2026-04-19-dispatcher-gpu-awareness-design.md
# Reason: every dispatcher-initiated inference must flow through
# build_options() so GPU placement is explicit and observable. Retrofitted
# consumer files keep their api/generate string literals (now inside
# _node_url(opts[...]) expressions) but consume the helper.

_API_GENERATE_RE = re.compile(r"api/(generate|chat)(?!\w)")

# Files allowed to reference api/generate or api/chat. Add new entries
# ONLY with a follow-up task ID explaining why the file is still raw.
_API_GENERATE_ALLOWLIST: set[str] = {
    # This script — references the pattern name in docs/error messages only.
    "scripts/check_agent_single_writer.py",
    # The helper — this IS the single writer.
    "platform_v2/tools/department_hq/services/ollama_options.py",
    # Retrofitted consumers (Tasks 6 + 7) — strings are inside
    # _node_url(opts[...]) expressions after build_options() calls.
    "platform_v2/tools/department_hq/services/department_dispatcher.py",
    "platform_v2/tools/department_hq/services/orchestration_engine.py",
    # Health-ping loop — passes explicit num_gpu=0 for non-GPU models;
    # not a user-facing dispatch path.
    "ai_bridge/agent_loop.py",
    # Legacy pre-migration sites — covered by follow-up tasks in the
    # ai_bridge → department_hq migration backlog.
    "ai_bridge/archie_bridge.py",
    "ai_bridge/knowledge_analyzer.py",
    # Agent jobs — string literal in an alert message body ("inspect
    # systemctl status ollama and recent /api/generate logs") not raw
    # inference. All actual dispatch goes through department_dispatcher.
    # Pre-existing false positive surfaced by #2102 Task 10.
    "platform_v2/services/agent_jobs.py",
    # Media Studio — Flask route path @bp.route("/api/generate") for image
    # generation (ComfyUI-backed, not Ollama). Legitimate false positive on
    # the regex. Actual LLM dispatches from this module go through
    # tools.department_hq.services.department_dispatcher.
    "platform_v2/tools/media_studio/routes.py",
    # app.py — legitimate false positives only after Project #262 follow-up
    # migration (#2184): 3 Flask route decorators /api/chat/pin{,ned,/<id>}
    # for the pin-message feature (not Ollama inference). All real
    # inference sites have been migrated: warmup/eviction → model_service,
    # /api/translate → Bridge dispatcher. Hook regex api/(generate|chat)(?!\w)
    # matches these route path strings — deferred hook refinement to future
    # work.
    "platform_v2/app.py",
}


def _check_raw_api_generate(paths: list) -> list:
    """Return violation strings for raw api/generate or api/chat outside allowlist."""
    violations: list[str] = []
    for p in paths:
        rel = str(p).replace("\\", "/")
        # Test files are always allowed — match on basename only so that
        # tmp_path directories (e.g. /tmp/pytest-.../test_xxx/) don't
        # accidentally exempt production files.
        basename = Path(p).name
        if (
            basename.endswith("_test.py")
            or basename.startswith("test_")
            or "/tests/" in rel
        ):
            continue
        # Skip non-Python files.
        if not rel.endswith(".py"):
            continue
        # Allowlist match by suffix (caller may pass absolute paths).
        if any(rel.endswith(allowed) for allowed in _API_GENERATE_ALLOWLIST):
            continue
        try:
            text = Path(p).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            # Skip pure comment lines.
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _API_GENERATE_RE.search(line):
                violations.append(
                    f"{rel}:{i}: raw api/generate or api/chat — route through "
                    f"tools.department_hq.services.ollama_options.build_options()"
                )
    return violations


def _is_allowed(path: str, allow_list: tuple) -> bool:
    """True if the path is on the given allow-list."""
    normalized = str(path).replace("\\", "/")
    return any(allowed in normalized for allowed in allow_list)


def _check_file(path: Path) -> tuple[list, list]:
    """Return (agents_write_hits, dispatcher_import_hits) for one file.

    Each hit is a (line_number, line_content) tuple.
    """
    if not path.exists() or path.suffix != ".py":
        return [], []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return [], []

    agents_hits: list[tuple[int, str]] = []
    dispatcher_hits: list[tuple[int, str]] = []

    check_agents = not _is_allowed(str(path), ALLOWED_AGENTS_PATHS)
    check_dispatcher = not _is_allowed(str(path), ALLOWED_DISPATCHER_PATHS)

    for idx, line in enumerate(text.splitlines(), start=1):
        if check_agents and AGENTS_WRITE_RE.search(line):
            agents_hits.append((idx, line.strip()))
        if check_dispatcher and DISPATCHER_IMPORT_RE.search(line):
            dispatcher_hits.append((idx, line.strip()))
    return agents_hits, dispatcher_hits


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        # Nothing staged — nothing to check.
        return 0

    agents_report: list[str] = []
    dispatcher_report: list[str] = []
    agents_total = 0
    dispatcher_total = 0

    paths = [Path(arg) for arg in argv[1:]]

    for path in paths:
        agents_hits, dispatcher_hits = _check_file(path)
        if agents_hits:
            agents_report.append(f"\n  \033[1;31m{path}\033[0m")
            for lineno, line in agents_hits:
                agents_report.append(f"    line {lineno}: {line[:120]}")
                agents_total += 1
        if dispatcher_hits:
            dispatcher_report.append(f"\n  \033[1;31m{path}\033[0m")
            for lineno, line in dispatcher_hits:
                dispatcher_report.append(f"    line {lineno}: {line[:120]}")
                dispatcher_total += 1

    # ---- Check 3: raw api/generate ----
    api_generate_violations = _check_raw_api_generate(paths)

    if agents_total == 0 and dispatcher_total == 0 and not api_generate_violations:
        return 0

    # ---- Render agents-write violations ----
    if agents_total:
        sys.stderr.write(
            "\n\033[1;31m"
            "K.I.N. single-writer guardrail: raw agents-table mutation detected"
            "\033[0m\n"
        )
        sys.stderr.write("".join(f"{line}\n" for line in agents_report))
        sys.stderr.write(
            "\n\033[1;33m"
            "The agents table has a single canonical writer: "
            "platform_v2/services/agent_service.py\n"
            "Use one of these helpers instead of raw SQL:\n"
            "    agent_service.create_agent(name, display_name, department, model, **kwargs)\n"
            "    agent_service.update_agent(agent_id, **fields)\n"
            "    agent_service.delete_agent(agent_id, hard=False)\n"
            "    agent_service.barracks(agent_id) / activate(agent_id) / deploy_to_node(...)\n"
            "    agent_service.increment_usage(agent_id, tier)\n"
            "    agent_service.update_performance_metrics(agent_id, success)\n"
            "\n"
            "If you need a new atomic pattern that these helpers don't cover, add\n"
            "a new helper to agent_service.py rather than writing raw SQL in a\n"
            "caller. See Project #241 Tracks A-C.3 for context.\n"
            "\033[0m"
        )

    # ---- Render dispatcher-import violations ----
    if dispatcher_total:
        sys.stderr.write(
            "\n\033[1;31m"
            "K.I.N. architecture guardrail: stale ai_bridge dispatcher import"
            "\033[0m\n"
        )
        sys.stderr.write("".join(f"{line}\n" for line in dispatcher_report))
        sys.stderr.write(
            "\n\033[1;33m"
            "The dispatcher, orchestration engine, and smart router moved to\n"
            "platform_v2/tools/department_hq/services/ in Project #244 Phase 2.\n"
            "The ai_bridge/ paths are back-compat shims only — new code must\n"
            "import from the canonical location:\n"
            "\n"
            "    from tools.department_hq.services.department_dispatcher import dispatch\n"
            "    from tools.department_hq.services.department_dispatcher import get_dispatcher\n"
            "    from tools.department_hq.services.orchestration_engine import OrchestrationEngine\n"
            "    from tools.department_hq.services.smart_router import get_router, TIER_ORDER\n"
            "\n"
            "Inside the services/ package, prefer relative imports:\n"
            "    from .department_dispatcher import get_dispatcher\n"
            "    from .smart_router import get_router\n"
            "\033[0m"
        )

    # ---- Render api/generate violations ----
    if api_generate_violations:
        sys.stderr.write(
            "\n\033[1;31m"
            "K.I.N. GPU-placement guardrail: raw api/generate or api/chat detected"
            "\033[0m\n"
        )
        for v in api_generate_violations:
            sys.stderr.write(f"  {v}\n")
        sys.stderr.write(
            "\n\033[1;33m"
            "Every dispatcher-initiated inference must flow through build_options()\n"
            "so GPU placement is explicit and observable.\n"
            "\n"
            "    from tools.department_hq.services.ollama_options import build_options\n"
            "    opts = build_options(model, num_gpu=..., num_ctx=..., temperature=...)\n"
            "    url = f\"{base_url}/{opts['endpoint']}\"  # api/generate or api/chat\n"
            "    payload = opts['payload']\n"
            "\n"
            "If this file must remain raw (e.g. health pings, legacy migration site),\n"
            "add it to _API_GENERATE_ALLOWLIST in scripts/check_agent_single_writer.py\n"
            "with a comment referencing the follow-up task ID.\n"
            "Spec: docs/superpowers/specs/2026-04-19-dispatcher-gpu-awareness-design.md\n"
            "Project #261 #2079.\n"
            "\033[0m"
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
