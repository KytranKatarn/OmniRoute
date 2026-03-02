# Phase 2 Design: Bridge Dispatcher Rewrite for Code Sentinel & Improvement Labs

**Date**: 2026-03-01
**Project**: #101 — ARCHIE Self-Evolution Pipeline
**Tasks**: #705 (Code Sentinel), #706 (Improvement Labs)
**ADR**: 073 (Bridge Integration Audit)

## Goal

Replace all direct `archie_bridge()` calls in Code Sentinel and Improvement Labs with `dispatcher.request_work()` so that all AI work flows through the Bridge Command dispatcher pipeline (agent selection, welfare, escalation, HR tracking, IAAE governance).

## Approach

Direct replacement — no wrappers, no new abstractions. The dispatcher IS the abstraction layer.

## Scope

### Code Sentinel (`tools/code_sentinel/routes.py`)

4 call sites:

| # | Function | Line | Current Call | New Call |
|---|----------|------|-------------|---------|
| 1 | `scan_file()` | ~462 | `route_task_to_station("code_review", ...)` | `dispatcher.request_work("code_review", ...)` |
| 2 | `scan_file()` | ~500 | `execute_agent_task(agent_id, task, ...)` | (eliminated — folded into #1) |
| 3 | `scan_file()` | ~545 | `archie_bridge(prompt, try_local_first=True)` | (eliminated — #1 handles fallback) |
| 4 | `_run_multi_agent_review()` | ~1506 | `archie_bridge(prompt, model=model)` | `dispatcher.request_work("code_review", ..., system_prompt=persona)` |

The 3-layer fallback in `scan_file()` (route → execute → archie_bridge) collapses to a single `request_work()` call. The dispatcher handles all escalation internally.

### Improvement Labs — code_generation_engine.py (`ai_bridge/code_generation_engine.py`)

4 call sites:

| # | Phase | Line | Current Call | New Call |
|---|-------|------|-------------|---------|
| 1 | Architect | ~509 | `archie_bridge(prompt, system_prompt, force_model)` | `dispatcher.request_work("code_analysis", prompt, system_prompt=...)` |
| 2 | Editor | ~531 | `archie_bridge(prompt, system_prompt, force_model)` | `dispatcher.request_work("code", prompt, system_prompt=...)` |
| 3 | Retry | ~581 | `archie_bridge(prompt, system_prompt, force_model)` | `dispatcher.request_work("code", prompt, system_prompt=...)` |
| 4 | Legacy V1 | ~929 | `archie_bridge(prompt, force_model)` | `dispatcher.request_work("code", prompt)` |

### Improvement Labs — team_consensus_orchestrator.py (`ai_bridge/team_consensus_orchestrator.py`)

1 call site:

| # | Function | Line | Current Call | New Call |
|---|----------|------|-------------|---------|
| 1 | `_real_evaluation()` | ~355 | `archie_bridge(prompt, agent_id, force_model)` | `dispatcher.request_work("code_review", prompt, prefer_agent=agent_name)` |

### Not in scope (no AI calls)

- `step_guidance_generator.py` — pure template-based
- `code_diff_engine.py` — pure difflib
- `improvement_learning.py` — analytics/DB only
- `improvement_engine.py` — SQL detection only
- `manager.py` — DB operations only

### External helpers (audit + wire if needed)

- `improvement_chat.py` — check if it calls archie_bridge directly
- `team_discussion_engine.py` — check
- `collaborative_report_generator.py` — check

## API Contract

```python
from ai_bridge.bridge_dispatcher import get_dispatcher

dispatcher = get_dispatcher()
result = dispatcher.request_work(
    capability="code_review",       # Maps to ENGINEERING station
    prompt="Analyze this code...",
    module_id="code_sentinel",      # For HR tracking
    system_prompt="You are...",     # Optional persona override
    json_mode=True,                 # Expect JSON response
    user_id=user_id,                # Optional
    prefer_agent="CodeSmith",       # Optional agent pinning
    priority="normal",              # low/normal/high/critical
    timeout=300,                    # Seconds
)

# DispatchResult fields:
result.success          # bool
result.response         # str (the AI response text)
result.agent_name       # str
result.model_used       # str
result.error            # Optional[str]
result.duration_ms      # int
```

## Error Handling Pattern

```python
result = dispatcher.request_work(...)
if not result.success:
    logger.warning(f"Dispatch failed: {result.error}")
    # Return graceful degradation (static analysis only, etc.)
    return fallback_response()

# Parse response
try:
    data = json.loads(result.response)
except json.JSONDecodeError:
    # AI returned non-JSON despite json_mode
    data = {"raw": result.response}
```

## Imports Change

```python
# REMOVE these imports:
from ai_bridge.archie_bridge import archie_bridge
from ai_bridge.archie_bridge import route_task_to_station, execute_agent_task

# ADD this import:
from ai_bridge.bridge_dispatcher import get_dispatcher
```

## Risks

- **Low**: Response format change (`DispatchResult` vs dict) — straightforward field mapping
- **Low**: JSON parsing — `json_mode=True` hints but doesn't guarantee valid JSON; keep existing parse+fallback logic
- **Medium**: Multi-agent review thread safety — `get_dispatcher()` returns singleton, `request_work()` is thread-safe (uses DB queries for agent selection)
