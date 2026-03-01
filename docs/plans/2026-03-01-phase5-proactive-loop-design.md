# Phase 5: Proactive Self-Improvement Loop — Design

**Project**: #101 ARCHIE Self-Evolution Pipeline
**Task**: #711 (Proactive self-improvement loop via Autonomy scheduler)
**Date**: 2026-03-01
**Status**: Approved

---

## Problem

The self-improvement pipeline from Phases 2-4 requires manual triggering — someone must run a Code Sentinel scan, then approve proposals. There's no autonomous loop where ARCHIE proactively scans its own code, creates proposals, and routes them through the approval system.

## Approach: Integrate with Existing Autonomy Tier System

Add a scheduled proactive scan job to the agent_loop, and route auto-generated proposals through the existing Tier 1/2 approval queue.

## Part 1: Scheduled Proactive Scans

New agent_loop job `_run_proactive_scan()` running every 6 hours:
1. Uses `git diff --name-only HEAD~5` to find recently changed Python files
2. Falls back to rotating set of key platform files if no recent changes
3. Calls Code Sentinel's scan logic for each file
4. Phase 4 hooks auto-create proposals from scan findings

## Part 2: Approval Queue Integration

After creating a proposal in `scan_pipeline._create_proposal_for_issue()`, submit to the autonomy approval queue:
- Low risk (risk_level low/medium, priority medium/low) → Tier 1 auto-approve
- High risk (risk_level high/critical, priority high/critical) → Tier 2 human approval via Telegram

New action type `improvement_approve` added to `tier1_auto_approve.types`.

New execution handler in `agent_loop._execute_approved_action()` that approves the improvement proposal (triggering Phase 4's auto-execution pipeline).

## Part 3: Full Autonomous Loop

```
Every 6h: _run_proactive_scan()
    → Code Sentinel scan → code_scans + code_issues
    → scan_pipeline.process_scan_results() [Phase 4]
    → Proposal created + approval queue entry
    → Low risk: Tier 1 auto-approve → auto-execute (code gen → sandbox → test)
    → High risk: Tier 2 → Telegram → human approves → auto-execute
    → Tests pass → "tested" status → admin notification
    → Deploy stays MANUAL (safety gate)
```

## Files Changed

| File | Change |
|------|--------|
| `ai_bridge/agent_loop.py` | Add `_run_proactive_scan()` job + `improvement_approve` handler |
| `platform_v2/services/scan_pipeline.py` | Add approval queue submission after proposal creation |
| DB migration | Add `improvement_approve` to `tier1_auto_approve.types` |
