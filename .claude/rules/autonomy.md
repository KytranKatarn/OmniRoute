---
globs: ["platform_v2/tools/autonomy/**", "ai_bridge/agent_loop.py", "ai_bridge/telegram_gateway.py"]
---

# Autonomy & Agent Loop Rules

## Agent Loop
- 17 APScheduler jobs | Approval: Tier 1 auto, Tier 2 human (Telegram)
- Training: `_process_training_tick()` — proficiency Lv1-5, Lv4+ unlocks cloud
- Tier 1 types: notification, reminder, kb_update, briefing, internal_log, cloud_throughput_escalation, translate, improvement_approve

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
