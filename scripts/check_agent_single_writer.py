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
    r"(?ix)" r"(?:" r"  UPDATE\s+agents\s+SET" r"| INSERT\s+INTO\s+agents\s*\(" r"| DELETE\s+FROM\s+agents\s+WHERE" r")"
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
    # Legacy application modules — pre-existing stale imports before Project Alpha (2026-05-06).
    # Migration to canonical DHQ dispatcher in Project Alpha module rebuild backlog.
    "platform_v2/tools/doc/routes.py",
    "platform_v2/tools/therapy/routes.py",
    "platform_v2/tools/fitness/routes.py",
)

# ---- Check 3: raw api/generate outside ollama_options + allowlist -----------
# Spec: docs/superpowers/specs/2026-04-19-dispatcher-gpu-awareness-design.md
# Reason: every dispatcher-initiated inference must flow through
# build_options() so GPU placement is explicit and observable. Retrofitted
# consumer files keep their api/generate string literals (now inside
# _node_url(opts[...]) expressions) but consume the helper.

_API_GENERATE_RE = re.compile(r"api/(generate|chat)(?![\w/])")

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
    # Contractor health probe (DS9) — the same category as the health-ping loop above,
    # and for the same reason: a monitoring check, never inference on a user's behalf.
    # It spends a 1-token generate against ollama.com to answer "can this contractor
    # serve at all", for the two rows whose base_url is the `ollama_cloud_proxy` sentinel
    # and which are therefore reached through Ollama Cloud rather than their own
    # endpoint. Cloud models are not GPU-placed — there is no local GPU in the path — so
    # build_options() has nothing to say about them. It deliberately does NOT go through
    # call_ollama_cloud, which would log usage and bill the weekly free allowance.
    "platform_v2/services/contractor_health_service.py",
    # Legacy pre-migration sites — covered by follow-up tasks in the
    # ai_bridge → department_hq migration backlog.
    "ai_bridge/archie_bridge.py",
    "ai_bridge/knowledge_analyzer.py",
    # Agentic tool-use KB search (#3534) — native /api/chat tools=[] loop, a DHQ
    # execution primitive invoked by department_dispatcher (agent + model already
    # DHQ-selected; each tool call logged to task_execution_log). Same sanctioned
    # inference layer as call_ollama. Flag-gated (agentic_tool_search), default OFF.
    "ai_bridge/agentic_search.py",
    # Agent jobs — string literal in an alert message body ("inspect
    # systemctl status ollama and recent /api/generate logs") not raw
    # inference. All actual dispatch goes through department_dispatcher.
    # Pre-existing false positive surfaced by #2102 Task 10.
    "platform_v2/services/agent_jobs.py",
    # archie-comms Flask app — exposes its own REST namespace
    # `@app.route("/api/chat/...")` (send_message / escalate / conversations /
    # messages / new). Not Ollama inference. Follow-up to refine the guardrail
    # regex so route decorators no longer trigger: task #2228.
    "archie-comms/app_comms.py",
    # archie-comms chat voice — intentionally direct-Ollama (ADR-013 waiver) so
    # A.R.C.H.I.E. can still talk if the platform/DHQ is down. Standalone app's own
    # api/chat call, NOT dispatcher-initiated GPU-placed inference. (#4266)
    "archie-comms/services/archie_voice_service.py",
    # Consciousness module — Flask route decorators for `/api/chat-volume`,
    # `/api/chat/history`, `/api/chat/upload` (admin-side conversation analytics
    # routes). Not Ollama inference. Same false-positive shape as archie-comms;
    # cleared by the same regex refinement (#2228).
    "platform_v2/tools/consciousness/routes.py",
    # Media Hub standalone — M.A.V.E.N. chat surface (task #2238, phase 1)
    # talks to Ollama directly at 192.168.1.200:11434 because the standalone
    # container doesn't ship tools.department_hq.services.ollama_options.
    # Phase 2 of task #2237 will replace this with a hub-side HTTP dispatch
    # endpoint that routes through build_options() on the hub's behalf.
    # Until that lands, keep the raw call behind this entry.
    "standalone/media_hub/maven/chat.py",
    # Department HQ model load/unload admin routes. Ollama has no dedicated
    # load endpoint — load = POST /api/generate with keep_alive=5m, unload =
    # same with keep_alive=0. Not user-facing inference; these are explicit
    # lifecycle controls invoked from the Fleet tab. Refactoring would just
    # wrap build_options() around an empty-prompt request that intentionally
    # never generates a token. Pre-existing.
    "platform_v2/tools/department_hq/model_routes.py",
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
    # Department HQ jobs — model unload via keep_alive=0 at line ~278.
    # Admin-plane operation (not user-facing inference): the only documented
    # way to evict a model from Ollama VRAM is POST /api/generate with
    # keep_alive=0. Cannot route through build_options() because that path
    # is for inference, not eviction. Pre-existing false positive surfaced
    # when jobs.py was first modified for #2235.
    "platform_v2/tools/department_hq/jobs.py",
    # model_service.py — lifecycle manager (load + unload via keep_alive).
    # Uses /api/generate with keep_alive="5m" to warm a model and keep_alive=0
    # to evict it from VRAM. Neither is user-facing inference; eviction is the
    # only documented Ollama API path for VRAM management. Cannot route through
    # build_options() which is inference-only. Added with VRAM-aware eviction
    # fix (migration 354 / Project #286).
    "platform_v2/services/model_service.py",
    # Applications modules (doc, therapy, fitness) — legacy archie_bridge
    # path with stale ai_bridge.bridge_dispatcher imports and raw Ollama
    # fallback. Pre-existing before Project Alpha auth fix (2026-05-06).
    # Migration to canonical DHQ dispatcher tracked as part of Project Alpha
    # module rebuild backlog.
    "platform_v2/tools/doc/routes.py",
    "platform_v2/tools/therapy/routes.py",
    "platform_v2/tools/fitness/routes.py",
    # Node client — runs ON the remote node, not inside the platform.
    # Talks to its own LOCAL Ollama for inference (not the hub's). Cannot
    # route through build_options() which lives on the hub. The node client
    # is a standalone agent that manages its own GPU placement independently.
    # Added when updating endpoints from /tools/starbase/ → /tools/department-hq/.
    "node_client/node_sync.py",
    "node_client/node_api.py",
    # Dev HQ routes — model warmup ping: POST /api/generate with keep_alive=5m
    # and prompt="warmup" to pre-warm a model before dispatch. Not user-facing
    # inference; cannot route through build_options() (warmup, not generation).
    # Surfaced by consciousness dispatch migration (Task #2536).
    "platform_v2/tools/consciousness/devhq_routes.py",
    # MCP server creation tools — line 801 references the legacy
    # /tools/figma/api/generate URL inside import_figma_design (vision/
    # multimodal handler). Same dead-route pattern as generate_code +
    # trigger_code_review which were migrated to dispatch() in this commit;
    # Figma needs a vision/multimodal capability path and is split out as a
    # follow-up to Task #1298. The match is on the URL path string, not an
    # actual Ollama inference call.
    "platform_v2/mcp_server/tools/creation.py",
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
        if basename.endswith("_test.py") or basename.startswith("test_") or "/tests/" in rel:
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
            "\n\033[1;31m" "K.I.N. single-writer guardrail: raw agents-table mutation detected" "\033[0m\n"
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
        sys.stderr.write("\n\033[1;31m" "K.I.N. architecture guardrail: stale ai_bridge dispatcher import" "\033[0m\n")
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
            "\n\033[1;31m" "K.I.N. GPU-placement guardrail: raw api/generate or api/chat detected" "\033[0m\n"
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
