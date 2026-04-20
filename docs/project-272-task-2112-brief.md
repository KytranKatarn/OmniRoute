# Project #272, Task #2112 — Observation → Proactive Fix Loop

**Status:** Scoping brief · 2026-04-20 · not yet implemented
**Source of truth on pieces already shipped:** this doc, audited against code
**Intended implementor:** next session (fresh context) or a subagent following this brief

## TL;DR

The 6-step chain in the task description (*S.P.E.C.T.R.A. → F.O.R.G.E. → V.I.G.I.L. → approval → F.O.R.G.E. apply → P.R.O.B.E. verify*) is **85% built** in `platform_v2/services/audit_pipeline.py`. The **only missing link** is a misroute-signal **input** that feeds into `process_audit_findings()`. Everything downstream (proposal creation, C.R.E.E.D. ethics gate, Bridge dispatch for fix generation, approval integration, post-deploy verify) already exists.

Phase 1 MVP = plumb the misroute signal. ~1 file new + 1 file edited. ~2-4 hours implementation + test.

## What's already built (exact pointers)

### `platform_v2/services/audit_pipeline.py` — 33 KB, 9 top-level functions

| Line | Function | Role |
|-----:|----------|------|
| 49 | `creed_gate_pre_fix(proposal_id, agent_id)` | V.I.G.I.L./C.R.E.E.D. ethics check **before** F.O.R.G.E. generates a fix |
| 173 | `creed_gate_pre_apply(proposal_id)` | C.R.E.E.D. ethics check **before** applying an approved fix |
| 291 | `process_audit_findings(module_name, issues_list)` | **ENTRY POINT** — takes audit results and creates proposals |
| 355 | `_has_open_audit_proposal(file_path, issue_code)` | Dedup — prevents same proposal twice |
| 372 | `_create_audit_proposal(issue, module_name, file_path)` | INSERTs into `improvement_proposals` with `metadata.source='code_health_audit'` |
| 514 | `dispatch_proposal_fix(proposal_id)` | Single-proposal dispatch to F.O.R.G.E. |
| 739 | `dispatch_audit_proposals(limit=20)` | Batch dispatch of pending proposals |
| 802 | `verify_fix_deployment(module_name, proposal_id, pre_issue_count)` | P.R.O.B.E.-style post-apply verify |

### `platform_v2/tools/department_hq/jobs.py:290`

Existing repair pipeline job calls `dispatch_audit_proposals(limit=10)` nightly. **Triggering infrastructure is live.**

### `ai_bridge/agent_loop.py:2774`

`elif action_type == "improvement_approve":` handler:
1. Updates proposal to `status='approved'`
2. If `metadata.source='code_health_audit'` → skips old auto_run, lets repair pipeline dispatch via Bridge (exactly the path we want)
3. For other sources → falls through to old Phase-4 `auto_run` path

### `improvement_proposals` table

32 columns including `priority`, `status`, `risk_level`, `metadata` (jsonb), `approved_at`, `auto_deployed`, `conversation_id`, `execution_results`, `required_skills`, `complexity`. Nothing schema-side to add for MVP.

### Approval queue (shipped PR #222-era)

`GET /api/approvals/pending` returns unified list including `bridge_jobs.status='pending_approval'`. Adding `improvement_proposals.status='pending_approval'` to the same endpoint is the UI surface (may already be covered — needs verify).

## The gap — S.P.E.C.T.R.A. misroute audit output

Task #2105 ("Nightly dispatch_misroute_audit job — S.P.E.C.T.R.A. ownership") is marked `completed`, but:

- `grep -rn "dispatch_misroute|misroute_audit|SPECTRA.*audit|capability_routing"` returns **zero job/service matches**
- Only match: a comment at `department_dispatcher.py:162` ("Was previously misrouted to Analytics")
- No `*.py` file in `services/` or `tools/department_hq/` is named for this

**Two possibilities:**
1. **Completed but mis-labeled** — the audit ships under a different name (e.g. `dispatch_routing_audit`, `capability_drift`). Spend 15 min with `git log --all -p | grep -i "misroute"` or look at PRs referencing #2105.
2. **Completed as a dashboard only** — task #2110 shipped the "S.P.E.C.T.R.A. capability routing dashboard" — perhaps #2105's signal is read-only exposed via that UI but never written to `improvement_proposals`.

**Before implementing #2112, confirm which.** If #1, call `process_audit_findings()` from that audit's end. If #2, write the audit properly first.

## Phase 1 MVP scope

Assuming the misroute audit exists and emits structured findings:

### New file: `platform_v2/services/misroute_to_proposal_adapter.py` (~60 LOC)

```python
"""Convert S.P.E.C.T.R.A. misroute findings into audit proposals.

Bridges the dispatch-routing audit (task #2105) to the self-healing
audit pipeline (audit_pipeline.process_audit_findings).
"""

def run():
    misroutes = _fetch_recent_misroutes()  # from wherever #2105 stores them
    if not misroutes:
        return {"findings": 0, "proposals": 0}

    issues = [_misroute_to_issue(m) for m in misroutes]
    from services.audit_pipeline import process_audit_findings
    result = process_audit_findings(module_name="dispatch_routing", issues_list=issues)
    return {"findings": len(misroutes), "proposals": result.get("created", 0)}

def _misroute_to_issue(m):
    return {
        "issue_code": "DISPATCH_MISROUTE",
        "file_path": m.get("caller_path") or "tools/department_hq/services/department_dispatcher.py",
        "line": m.get("caller_line"),
        "severity": "medium",
        "description": f"Dispatch for '{m['capability']}' went to {m['actual_dept']}, expected {m['expected_dept']} ({m['count']}× in 24h)",
        "suggested_fix": m.get("suggested_fix"),
    }
```

### Edited file: `ai_bridge/agent_loop.py`

Add a nightly job that calls `misroute_to_proposal_adapter.run()` — ~10 LOC insert in the job-registration block around line 620.

### Verification path (no new code — uses existing pieces)

1. First run — creates proposals for each misroute
2. Nightly `dispatch_audit_proposals` job picks them up → F.O.R.G.E. drafts fix diff
3. `creed_gate_pre_fix` gates → approve or flag (existing V.I.G.I.L. check)
4. Proposal hits `status='pending_approval'` → `/api/approvals/pending` surfaces in DHQ UI
5. Kytran clicks approve → `improvement_approve` action triggers apply
6. `verify_fix_deployment` runs P.R.O.B.E. QA post-apply

Everything from step 2 onward is **existing infrastructure**. We just need step 1 (the adapter).

## Phase 2 extensions (separate follow-up tasks, not in MVP)

Each reuses the same `process_audit_findings()` funnel with a different source:

| Signal | Source (already shipped) | Proposal `issue_code` |
|--------|-------------------------|----------------------|
| Budget drift | #2106 K.I.N. welfare digest | `BUDGET_DRIFT` |
| Dep drift | #2109 F.O.R.G.E. dep drift detector | `DEP_DRIFT` |
| Infra outage | #2127 V.I.G.I.L. infra heartbeat | `INFRA_HEARTBEAT_FAIL` |
| Doc drift | #2108 C.O.D.E.X. auto-documentation | `DOC_DRIFT` |

Each is its own ~60-LOC adapter following the same pattern.

## Proposed subtasks under #272

| # | Title | Est |
|---|------|----:|
| a | Confirm S.P.E.C.T.R.A. misroute audit output location & shape (#2105 artifact) | 30 min |
| b | Author `misroute_to_proposal_adapter.py` + nightly job registration | 1-2 hr |
| c | Integration test: inject a fake misroute, confirm proposal → approval queue → applied | 1 hr |
| d | (Phase 2) Extend adapter pattern to budget/dep/infra/doc drift | separate |

## Risk & gotchas

- `creed_gate_pre_fix` may reject auto-generated fixes aggressively. Test with low-risk misroutes first.
- `dispatch_audit_proposals` serializes per GPU — a flood of misroutes could starve other audit sources. Cap the nightly adapter output (e.g. 5 worst misroutes per run).
- `metadata.source='code_health_audit'` is the branch that bypasses old auto_run in `agent_loop.py:2774`. The adapter MUST set this same source value or proposals go down the wrong path.
- `_has_open_audit_proposal` dedups by `(file_path, issue_code)` — if two different misroutes hit the same call site, only the first becomes a proposal. Acceptable for MVP; track rejection count in observability.

---

**Authored during 2026-04-20 session while Phase 2 portrait regen was running. Did not implement due to epic scope + fresh-context requirement for the S.P.E.C.T.R.A. gap investigation.**
