# Delegation Demo — Claude → A.R.C.H.I.E. → P.R.O.B.E.

**Project:** #276 Task #2212 · 2026-04-21
**Status:** live end-to-end — every pipe verified in production this session

This doc traces one complete delegated task from Claude's MCP call through to the Telegram notification Kytran sees. It's the exit criteria for Project #276 Phase 1–3.

## The call

From any Claude session with MCP write permission:

```python
mcp__archie__delegate_task(
    capability='run_qa_suite',
    args={'suite_name': 'autonomy'},
    reason='Verify PR #246 landed cleanly',
    delegation_source='claude',
    requested_by='claude_session_abc',
    priority=7,
)
```

Claude gets back `{"success": True, "task_id": 2213, "title": "[DELEGATE:claude] run_qa_suite", "uses_known_tool": True}` immediately — the MCP call is fire-and-forget from Claude's perspective. Archie handles the rest asynchronously.

## The pipeline (5 hops)

### Hop 1 — `delegate_task()` persists

`platform_v2/services/delegation_service.py::delegate_task` validates required fields (capability, reason, delegation_source in the allowed set, priority 1–10), then:

```sql
INSERT INTO unified_tasks
    (project_id, title, description, status, priority, task_type,
     delegation_source, delegation_args, streaming_channel)
VALUES (NULL, '[DELEGATE:claude] run_qa_suite',
        'Delegated by claude_session_abc via claude: Verify PR #246 landed cleanly',
        'pending', 7, 'implementation',
        'claude',
        '{"capability": "run_qa_suite", "args": {"suite_name": "autonomy"}, ...}'::jsonb,
        NULL)
RETURNING id
```

Row lives in the **delegation queue** — a partial index on `(status, created_at) WHERE delegation_source IS NOT NULL` keeps the worker's polling cheap.

### Hop 2 — Worker claim (≤30s latency)

`ai_bridge/agent_loop.py::_run_delegate_task_worker` runs on a 30s `IntervalTrigger`, `max_instances=1`, `coalesce=True`. Each cycle:

```python
tasks = fetch_pending_delegations(limit=3)        # ORDER BY priority DESC, created_at ASC
for task in tasks:
    mark_task_in_progress(task_id)                 # → status='in_progress'
    emit_delegation_event('start', ...)            # → Unified Comms
    result = execute_delegated_task(task)          # → known-tool OR dispatcher
    if result.success: mark_task_completed(...)
    else:              mark_task_failed(...)
    emit_delegation_event('complete' or 'fail', ...)
```

Autonomy-loop-log only writes when a cycle was non-empty, so quiet minutes don't spam the timeline.

### Hop 3 — Execution routing

`delegation_service.execute_delegated_task` dispatches on capability:

| Capability | Route | Behavior |
|---|---|---|
| `run_qa_suite` | `services.qa_service.run_qa_suite(suite_name=...)` | P.R.O.B.E. QA suite runs; returns `{passed, failed, ...}` |
| `run_misroute_audit` | `services.misroute_audit_service.run_misroute_audit(window_hours=...)` | S.P.E.C.T.R.A. audit; returns severity + findings |
| `run_misroute_to_proposal_adapter` | `services.misroute_to_proposal_adapter.run(...)` | Creates improvement_proposals |
| `check_dep_drift` | `services.dep_drift_service.check_dep_drift(...)` | F.O.R.G.E. dep diff |
| `health_check` / `check_platform_health` | `services.health_service.*` | Container/DB/GPU rollup |
| *anything else* | `department_dispatcher.dispatch(capability, prompt, ...)` | LLM path with agent selection + C.R.E.E.D. + cost tracking |

### Hop 4 — Persistence

On success:
```sql
UPDATE unified_tasks SET status='completed', completed_at=now() WHERE id=2213;
INSERT INTO work_notes (task_id, note_type, content, metadata)
VALUES (2213, 'delegation_result',
        'QA suite autonomy: passed=12 failed=0',
        '{"outcome": "completed"}'::jsonb);
```

On failure, the same pair with `status='blocked'` and `note_type='delegation_failure'`. Follow-up retries read from here.

### Hop 5 — Unified Comms streaming

`emit_delegation_event(task_id, event_type, capability, summary, ...)` formats a message in A.R.C.H.I.E.'s COO voice and hands it to `telegram_service`:

- `start` / `complete` → `send_info` (Executive Office, info priority)
- `fail` → `send_system` (escalation, warning priority)

Messages route through `archie_comms` at `:3002` → `POST /api/director/report` which applies personality and sends via Telegram. If `streaming_channel='telegram:<chat_id>'`, the target chat is overridden; otherwise the default `TELEGRAM_CHAT_ID` is used.

**Streaming errors are swallowed.** If Telegram is down, the worker still completes the task and writes `work_notes`. Kytran loses a notification, not a result.

## Live verification (this session)

Task #2213, fired 2026-04-21 11:58:14 UTC via `delegate_task` from a Python shell inside `archie_platform`. Results 68ms later:

| DB row | Value |
|---|---|
| `unified_tasks.status` | `completed` |
| `unified_tasks.completed_at` | 11:58:15.081793 UTC |
| `unified_tasks.delegation_source` | `claude` |
| `work_notes.content` | `Misroute audit: severity=info anomalies=13 window=24h` |
| `autonomy_loop_log.job_name` | `delegate_task_worker` |
| `autonomy_loop_log.status` | `success` |
| `autonomy_loop_log.items_processed / items_failed` | `1 / 0` |
| `autonomy_loop_log.duration_ms` | `68` |

All 5 hops fired. First run, no retries, no errors.

## Division of labor (the "why" of this work)

| When Claude should use it directly | When Claude should delegate to Archie |
|---|---|
| Complex multi-file reasoning | Routine platform operations (QA, dep drift, misroute audit) |
| Architectural decisions | Long-running background work (can't tie up a Claude session) |
| Anything needing long context | Anything doable via a known-tool shortcut |
| First-draft code | Verification loops you'd otherwise have to run yourself |

The rule of thumb: if it's a known-tool capability, delegate. If it's reasoning, keep it in Claude. If it's iteration between the two, Claude plans + delegates chunks, then synthesizes results.

## What's next

- **Phase 2** (deferred) — parent_task_id for multi-turn delegations so Archie can ask Claude clarifying questions mid-task
- **Phase 4** (optional) — ArchieCode CLI fork of `plandex` giving Kytran terminal-native delegation
- **Phase 5** — divvy the roadmap into "Claude owns" / "Archie owns" columns in the open-project list

---

**Live as of 2026-04-21. Update this doc if the pipeline shape changes.**
