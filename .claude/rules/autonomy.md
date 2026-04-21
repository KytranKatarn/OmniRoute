---
globs: ["platform_v2/tools/autonomy/**", "ai_bridge/agent_loop.py", "ai_bridge/telegram_gateway.py"]
---

# Autonomy & Agent Loop Rules

## Agent Loop
- 20+ APScheduler jobs | Approval: Tier 1 auto, Tier 2 human (Telegram)
- Training: `_process_training_tick()` — proficiency Lv1-5, Lv4+ unlocks cloud
- Tier 1 types: notification, reminder, kb_update, briefing, internal_log, translate, improvement_approve
- Tier 2 types (human approval): cloud_throughput_escalation, create_agent (cost/security sensitive)
- Dedup: `submit_approval()` skips if a pending approval of the same type already exists

## Delegation (Project #276, 2026-04-21)
Claude (or Kytran) can hand work to A.R.C.H.I.E. via `mcp__archie__delegate_task`. The task is persisted to `unified_tasks` with `delegation_source` set (`claude` / `user_cli` / `telegram` / `web_chat` / `mcp_client` / `automation`). The **delegate_task_worker** job (30s interval, `max_instances=1`, `coalesce=True`) claims up to 3 pending rows per cycle and routes to either:
  - **Known-tool shortcut** — `run_qa_suite`, `run_misroute_audit`, `run_misroute_to_proposal_adapter`, `check_dep_drift`, `health_check` / `check_platform_health` → direct service call (no LLM)
  - **Dispatcher fallback** — everything else flows through `department_dispatcher.dispatch()` (agent selection + C.R.E.E.D. + cost tracking)

Result lands in `work_notes`; task flips `completed` or `blocked`. Events emit to Unified Comms via `telegram_service.send_info` (start/complete) or `send_system` (fail). Streaming errors are always suppressed — comms bugs cannot break the worker. See `services/delegation_service.py` + `docs/delegation-demo.md`. ADR-001 logged.

## Scheduled job families (non-exhaustive, added this session)
- `spectra_misroute_audit` — 24h at 02:15 UTC (Project #272 #2105)
- `misroute_to_proposal_adapter` — 24h at 02:30 UTC (Project #272 #2186)
- `kin_welfare_digest` — 24h at 02:45 UTC (#2106)
- `forge_dep_drift` — 24h at 03:15 UTC (#2109)
- `codex_event_docs` — 30min (#2108)
- `vigil_infra_heartbeat` — 5min (#2127)
- `delegate_task_worker` — 30s (Project #276 #2209)

## Telegram
- Daemon thread, own asyncio loop, starts if `TELEGRAM_BOT_TOKEN` set
- 5-step escalation: normal -> same-station -> cross-station -> free cloud -> paid cloud
- Buttons: `esc_ack`, `esc_cloud`, `esc_paid`, `esc_approve_{id}`, `esc_deny_{id}`, `esc_defer_{id}`
- `python-telegram-bot` must be pip-installed (needs Dockerfile update)

## DB Gotchas
- `telegram_users` (NOT `telegram_linked_accounts`)
- `system_notifications` CHECK: info/warning/error/success/reminder/alert/briefing
- `governance_audit_log` uses `timestamp`/`event_category`
- `agent_rest_cycles` uses `started_at`
