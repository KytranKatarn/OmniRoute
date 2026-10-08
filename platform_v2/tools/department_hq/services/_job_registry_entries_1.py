"""Static department job entries, section 1."""

JOB_ENTRIES = {
    # ── Chronicle (#5644) ──
    # Both were absent from this registry until 2026-08-16, so neither appeared in the
    # DHQ Jobs view. `chronicle_story_worker` had been running every 10 minutes, unlisted.
    "chronicle_source_ingest": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": (
            "Keeps the Chronicle corpus current: pulls new Gmail (every connected account) "
            "and the LinkedIn authored corpus into Chronicle via ingest_source. Bounded per "
            "cycle for Gmail API quota (CHRONICLE_INGEST_BATCH, default 50/account). "
            "DEFAULT OFF — toggled in Autonomy tab. Added because run_gmail_ingest / "
            "run_linkedin_ingest had NO scheduled caller and the corpus had gone ~5 weeks "
            "stale while Google Work Suite kept syncing normally."
        ),
        "interval": "hourly :23 ET",
        "source_file": "tools/department_hq/jobs.py",
    },
    "chronicle_story_worker": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": (
            "Local-only per-entity story synthesis: builds chronicle_entity_story for "
            "resolved entities with >=2 linked emails and no story. Welfare-gated on the "
            "'summarize' pool, resumable, defer-on-cold."
        ),
        "interval": "every 10 min (:7,:17,:27,:37,:47,:57 ET)",
        "source_file": "tools/department_hq/jobs.py",
    },
    # ── Code Health static tier (2026-07-11 spec) ──
    "hub_deploy_advisor": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": (
            "Hub deploy advisory (spec 2026-08-26): watches the volume-mounted hub tree; when merged "
            "changes await checkout/restart it advises via Telegram (dedup'd). Advisory only — "
            "nothing restarts automatically. DEFAULT ON."
        ),
        "interval": "every 30 min",
    },
    "code_health_reverify": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": (
            "Daily re-audit of deployed proposals (loop closure, spec 2026-08-26): stamps "
            "reverified=fixed/still_open independently of audit-all, and alerts when the "
            "still_open population grows. DEFAULT ON."
        ),
        "interval": "daily 04:40 ET",
    },
    "agent_code_health_autoheal": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": (
            "Autonomous Code Health heal cycle: static deep scan -> auto-verify gate -> "
            "Repair Bay proposals -> DHQ fix dispatch -> static reverify. Deploy human-gated. "
            "DEFAULT OFF — toggled in Autonomy tab"
        ),
        "interval": "daily 02:45 ET",
        "source_file": "tools/department_hq/jobs.py",
    },
    # =========================================================================
    # ai_bridge/agent_loop.py — 55 jobs
    # =========================================================================
    # ── Backlog Drain (Phase 3, #676) ──
    "fleet_backlog_runner": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Promote pending backlog tasks to the fleet — DEFAULT OFF, toggled in Autonomy tab",
        "interval": "60s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "engine_autopull_cycle": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "A.R.C.H.I.E. Building Machine — pulls one in-scope platform issue and triggers archie_engine to build a GATED PR (never auto-merged); DEFAULT ON, toggled in Autonomy tab",
        "interval": "6h",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Communications / Notifications ──
    "agent_email_queue": {
        "department": "Customer Success & Support",
        "director": "R.E.S.O.L.V.E.",
        "description": "Process pending outbound email queue",
        "interval": "60s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_telegram_notify": {
        "department": "Customer Success & Support",
        "director": "R.E.S.O.L.V.E.",
        "description": "Forward system notifications to Telegram",
        "interval": "15s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_email_telegram_notify": {
        "department": "Customer Success & Support",
        "director": "R.E.S.O.L.V.E.",
        "description": "Forward email notifications to Telegram",
        "interval": "30s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_email_processing": {
        "department": "Customer Success & Support",
        "director": "R.E.S.O.L.V.E.",
        "description": "Gmail inbox processing for agent emails",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "resolve_email_oversight": {
        "department": "Customer Success & Support",
        "director": "R.E.S.O.L.V.E.",
        "description": "R.E.S.O.L.V.E. scans for unanswered inbound emails >24h, auto-assigns and creates unified_tasks as tickets, sends Telegram alert",
        "interval": "30m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_notification_cleanup": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Archive stale system notifications older than threshold",
        "interval": "6h",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Scheduling / Approvals ──
    "agent_scheduled_tasks": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Process due scheduled tasks from task queue",
        "interval": "30s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_reminders": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Process due reminders and send alerts",
        "interval": "30s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_approvals": {
        "department": "Executive Office",
        "director": "A.R.C.H.I.E.",
        "description": "Auto-approve tier-1 requests, expire stale tier-2, execute approved",
        "interval": "60s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "resume_approved_bridge_jobs": {
        "department": "Executive Office",
        "director": "A.R.C.H.I.E.",
        "description": "Re-dispatch web-approved bridge_jobs image_generation rows to paid cloud provider",
        "interval": "30s",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    "agent_briefings": {
        "department": "Executive Office",
        "director": "A.R.C.H.I.E.",
        "description": "Generate scheduled executive briefings",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Reports ──
    # NOTE: agent_loop.py registers "agent_anomaly_detection" but it is
    # overridden at runtime by security_network/jobs.py (registered later,
    # same scheduler id). The security_network version is the active one —
    # see "agent_anomaly_detection_network" below in security_network section.
    "agent_reports": {
        "department": "Analytics & Intelligence",
        "director": "S.P.E.C.T.R.A.",
        "description": "Generate scheduled analytical reports",
        "interval": "15m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Browser / Research ──
    "agent_browser_tasks": {
        "department": "Research & Development",
        "director": "D.A.R.W.I.N.",
        "description": "Execute scheduled browser automation tasks",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Job Lifecycle ──
    "agent_stale_job_reaper": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Reap stale jobs that exceeded their max duration",
        "interval": "2m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_stuck_job_watchdog": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Detect and recover stuck jobs in processing state",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── QA / Code Quality ──
    "qa_scheduled_run": {
        "department": "Engineering & Technology",
        "director": "P.R.O.B.E.",
        "description": "P.R.O.B.E. scheduled QA test suite execution — runs all active suites, auto-creates Repair Bay proposals on regression",
        "interval": "6h",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_proactive_scan": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Proactive code scan for issues and vulnerabilities",
        "interval": "6h",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "dependency_audit": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Dependency CVE audit — scan for known vulnerabilities",
        "interval": "6h",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "dependabot_scan": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Dependabot vulnerability scan — poll alerts and triage",
        "interval": "6h",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_batch_medium_issues": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Weekly batch of medium-severity code issues (Sunday 2 AM)",
        "interval": "weekly Sun 02:00",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_weekly_dependency_scan": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Weekly full dependency scan (Sunday 4 AM)",
        "interval": "weekly Sun 04:00",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_auto_execute_proposals": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Auto-execute approved dev pipeline improvement proposals",
        "interval": "30m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_uncommitted_check": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Monitor for uncommitted changes in tracked repositories",
        "interval": "1h",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Infrastructure ──
    "ddns_ip_monitor": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "DDNS public IP monitor — detect and update IP changes",
        "interval": "15m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_auto_log_ingestion": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Auto-ingest system logs for analysis",
        "interval": "30m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_ollama_model_health": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Ollama model health check — verify loaded models are responsive",
        "interval": "30m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_mission_schedule": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Check and execute mission profile schedules",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Knowledge / Memory ──
    "job_47_chat_memories": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Extract and store memories from chat conversations",
        "interval": "2m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "module_docs_updater": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Auto-update module documentation from code analysis",
        "interval": "24h",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "quality_review": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Knowledge quality review — score and flag low-quality entries",
        "interval": "30m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Git / Version Control ──
    "git_change_tracker": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Track git changes and log commit activity",
        "interval": "30m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Security (in agent_loop.py) ──
    "agent_ssh_monitor": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Monitor SSH login attempts and alert on anomalies",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Media / Creative ──
    "agent_media_generation": {
        "department": "Creative & Design",
        "director": "M.U.S.E.",
        "description": "Check agent media generation schedules and trigger if due",
        "interval": "15m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "media_generation_worker": {
        "department": "Creative & Design",
        "director": "M.U.S.E.",
        "description": "Process pending ComfyUI image/video queue entries — handles cold boot, VRAM, fleet routing",
        "interval": "30s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "portrait_refinement_worker": {
        "department": "Creative & Design",
        "director": "M.U.S.E.",
        "description": "Process queued portrait refinement jobs — vision analysis + agent consultation + M.U.S.E. synthesis via DHQ",
        "interval": "30s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "model_dispatch_worker": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Model-affinity dispatch queue drainer — routes all agent requests to wherever the required model is warm (hub or fleet node). Minimises VRAM swaps. All products enqueue here. ADR-004.",
        "interval": "15s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "website_deploy_worker": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Daily full-site deploy to Hostinger (kytranempowerment.com + creed-ai.org). Also triggered manually via Repair Bay → Ship → Website tab.",
        "interval": "daily 03:00",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "media_analytics_snapshot": {
        "department": "Creative & Design",
        "director": "M.U.S.E.",
        "description": "Compute hourly media analytics snapshot",
        "interval": "1h",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "agent_media_queue_cleanup": {
        "department": "Creative & Design",
        "director": "M.U.S.E.",
        "description": "Clean up completed/expired media generation queue items",
        "interval": "1h",
        "source_file": "ai_bridge/agent_loop.py",
    },
}
