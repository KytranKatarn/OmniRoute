---
globs: ["platform_v2/tools/repair_bay/**", "platform_v2/services/scan_service.py", "platform_v2/services/proposal_service.py", "platform_v2/services/scan_pipeline.py"]
---

# Repair Bay Rules

## Structure
- Route: `/tools/repair-bay` | 9 tabs: Dashboard (Reviews), PR Review, Repairs, Diagnose, Test Bay, Ship, P.R.O.B.E. (QA), Pushes, Module Review + ENGINEERING station panel
- Service layer: `scan_service.py`, `proposal_service.py`, `sandbox_service.py` (business logic)
- Route files are thin HTTP handlers calling service functions
- Category: `AI_COMMAND` (not DEVELOPMENT_TOOLS — deleted)
- `SandboxManager` class at `platform_v2/tools/repair_bay/services/sandbox_manager.py` (top-level `platform_v2/sandbox_manager.py` does NOT exist — corrected 2026-05-29)

## Self-Evolution Pipeline
- Scan -> Proposal -> Sandbox -> Deploy (deploy stays manual)
- Critical/high -> individual proposals, medium -> weekly batch (Sunday 02:00)
- Proactive scan: `_run_proactive_scan()` in agent_loop (every 6h)
- Deduplication: `_has_open_proposal()` checks file_path + issue_type

## Gotchas
- `audit_log` from `logging_config` not `rbac`
- `register_*_routes(bp, admin_required)` pattern
