"""Department Job Registry — maps every platform job to its owning department.

Single source of truth for job ownership. Used by:
- Job monitoring dashboard in Department HQ
- autonomy_loop_log department column
- Job health reporting

Total: 128 active jobs across 8 source files and 13 departments.
"""

# Each entry: job_id -> {department, director, description, interval, source_file}
JOB_REGISTRY = {
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
    "agent_media_export_cleanup": {
        "department": "Creative & Design",
        "director": "M.U.S.E.",
        "description": "Clean up old media export files from disk",
        "interval": "1h",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Game Studio ──
    "game_world_event_processor": {
        "department": "Creative & Design",
        "director": "M.U.S.E.",
        "description": "Process game world events and NPC actions",
        "interval": "30s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "game_market_price_update": {
        "department": "Creative & Design",
        "director": "M.U.S.E.",
        "description": "Update in-game market prices based on supply/demand",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Calendar / Productivity ──
    "agent_calendar_drive": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Calendar + Google Drive autonomy — sync events and files",
        "interval": "15m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── StockBot (stub — migrated to Market Watch) ──
    "stock_price_updater": {
        "department": "Analytics & Intelligence",
        "director": "S.P.E.C.T.R.A.",
        "description": "Stock price updater (stub — migrated to Market Watch)",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Market Watch ──
    "market_watch_cycle": {
        "department": "Analytics & Intelligence",
        "director": "S.P.E.C.T.R.A.",
        "description": "M.A.R.K.E.T. trading cycle during market hours (Mon-Fri 9-15 ET)",
        "interval": "cron Mon-Fri 9-15 ET every 30m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Social Video ──
    "social_video_generate": {
        "department": "Marketing & Communications",
        "director": "S.I.G.N.A.L.",
        "description": "Social video content generation pipeline",
        "interval": "4h",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "social_video_auto_approve": {
        "department": "Marketing & Communications",
        "director": "S.I.G.N.A.L.",
        "description": "Auto-approve generated social video content",
        "interval": "15m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "social_video_publish": {
        "department": "Marketing & Communications",
        "director": "S.I.G.N.A.L.",
        "description": "Publish scheduled social video content",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── V.I.G.I.L. Security Jobs (in agent_loop.py) ──
    "vigilil_network_health": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Network health monitor — connectivity and latency checks",
        "interval": "60s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "vigilil_traffic_aggregator": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Aggregate network traffic statistics",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "vigilil_nagios_sync": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Sync monitoring data from Nagios",
        "interval": "2m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "vigilil_device_watcher": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Watch for new/unauthorized devices on network",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "vigilil_dns_anomaly": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "DNS anomaly detection — suspicious query patterns",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "vigilil_log_health": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Log health monitor — check log integrity and gaps",
        "interval": "15m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "vigilil_daily_report": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Daily bandwidth and network usage report (6 AM)",
        "interval": "daily 06:00",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "vigilil_threat_responder": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Active threat response — block and mitigate detected threats",
        "interval": "30s",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "vigilil_vpn_scan": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "VPN usage monitor — track active VPN connections",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    "vigilil_bandwidth_alerts": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Bandwidth threshold monitor — alert on excessive usage",
        "interval": "30m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── Agent Wellness ──
    "agent_crew_wellness_tick": {
        "department": "Human Resources & Culture",
        "director": "K.I.N.",
        "description": "Crew wellness tick — update fatigue, stress, mood for all agents",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # ── C.R.E.E.D. Governance ──
    "creed_governance_reporter": {
        "department": "Legal & Regulatory",
        "director": "G.A.V.E.L.",
        "description": "C.R.E.E.D. governance metrics reporter",
        "interval": "5m",
        "source_file": "ai_bridge/agent_loop.py",
    },
    # =========================================================================
    # platform_v2/tools/security_network/jobs.py — 21 jobs
    # =========================================================================
    "agent_network_discovery": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Network device discovery — scan for new devices via ARP/ping",
        "interval": "5m",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_security_audit": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Weekly comprehensive security audit (Sunday 3 AM)",
        "interval": "weekly Sun 03:00",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_ssl_expiry_check": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "SSL certificate expiry check for all tracked domains",
        "interval": "24h",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_daily_dns_report": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Daily DNS health and change report (7 AM)",
        "interval": "daily 07:00",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_query_spike_detect": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "DNS query spike detection — alert on unusual volume",
        "interval": "1h",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_camera_anomaly": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Camera motion anomaly detection for surveillance feeds",
        "interval": "1h",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_auto_block": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Auto-block pipeline — block malicious IPs and domains",
        "interval": "15m",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_compliance_scan": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "STIG/HIPAA/CIS compliance rule evaluation scan",
        "interval": "6h",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_auto_remediation": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Compliance auto-remediation — fix low-risk failures automatically",
        "interval": "6h",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_compliance_auto_apply_window": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Sunday maintenance-window auto-apply for compliance fixes",
        "interval": "weekly Sun 03:00 ET",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_compliance_auto_plan": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "F.O.R.G.E. auto plan generation for blocklisted compliance failures",
        "interval": "6h",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_traffic_stats": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "ntopng traffic statistics collection",
        "interval": "5m",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_dns_history": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "DNS history collection — log all DNS query patterns",
        "interval": "5m",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_sync_device_mappings": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Device-user mapping sync — correlate devices to users",
        "interval": "6h",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_ip_geolocation": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "IP geolocation enrichment for network traffic analysis",
        "interval": "30m",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_anomaly_detection": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Network anomaly detection — statistical outlier analysis",
        "interval": "30m",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_vigil_threat_report": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "V.I.G.I.L. daily threat report (8 AM)",
        "interval": "daily 08:00",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_weekly_security_report": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Weekly security summary report (Monday 8 AM)",
        "interval": "weekly Mon 08:00",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_threat_intel_sync": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Threat intelligence feed sync — update IOC databases",
        "interval": "6h",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_correlate_incidents": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Alert correlation — group related alerts into security incidents",
        "interval": "30m",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_speed_test": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Network speed test — bandwidth measurement",
        "interval": "6h",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    "agent_supervision_enforce": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Supervision controls enforcement — parental/access schedules",
        "interval": "5m",
        "source_file": "platform_v2/tools/security_network/jobs.py",
    },
    # =========================================================================
    # platform_v2/tools/consciousness/jobs.py — 19 jobs
    # =========================================================================
    "knowledge_deduplication": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Knowledge base deduplication — merge near-duplicate entries",
        "interval": "24h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "session_indexer": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Index Claude session transcripts into knowledge base",
        "interval": "12h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_consciousness_analysis": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Consciousness analysis batch — AI-powered knowledge extraction",
        "interval": "6h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_consciousness_embedding": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Consciousness embedding batch — vectorize knowledge entries",
        "interval": "30m",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_skill_sync": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Sync learned skills from knowledge base to Claude rules",
        "interval": "6h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_github_auto_pull": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "GitHub auto-pull — refresh tracked repos and re-index changed files",
        "interval": "12h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_skill_analyzer": {
        "department": "Research & Development",
        "director": "D.A.R.W.I.N.",
        "description": "Skill analyzer — AI-powered quality scoring for discovered skills",
        "interval": "6h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_conversation_consolidation": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Consolidate conversation fragments into coherent knowledge",
        "interval": "1h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_improvement_detection": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Detect improvement opportunities from knowledge patterns",
        "interval": "6h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_daily_self_reflection": {
        "department": "Executive Office",
        "director": "A.R.C.H.I.E.",
        "description": "Daily self-reflection — system introspection at midnight",
        "interval": "daily 00:00",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_weekly_memory_consolidation": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Weekly memory consolidation — prune and merge memories (Sunday 3 AM)",
        "interval": "weekly Sun 03:00",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_knowledge_auto_link": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Auto-link knowledge entries to relevant projects",
        "interval": "5m",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_auto_generate_docs": {
        "department": "Research & Development",
        "director": "D.A.R.W.I.N.",
        "description": "D.A.R.W.I.N. auto-documentation generation for projects",
        "interval": "6h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_weekly_knowledge_report": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "C.O.D.E.X. weekly knowledge health reports (Sunday 3 AM)",
        "interval": "weekly Sun 03:00",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_github_repo_analysis": {
        "department": "Research & Development",
        "director": "D.A.R.W.I.N.",
        "description": "GitHub repo relevance analysis — score and rank tracked repos",
        "interval": "6h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_skill_installer": {
        "department": "Documentation & Knowledge",
        "director": "C.O.D.E.X.",
        "description": "Install discovered skills to Claude Code configuration",
        "interval": "2h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_skill_tester": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Skill tester — structural validation and dry-run testing",
        "interval": "4h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_skill_fleet_push": {
        "department": "Fleet & Infrastructure",
        "director": "A.R.M.A.D.A.",
        "description": "Push validated skills to fleet nodes for cluster distribution",
        "interval": "6h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    "agent_skill_adaptation": {
        "department": "Research & Development",
        "director": "D.A.R.W.I.N.",
        "description": "Adapt external skills for A.R.C.H.I.E. platform conventions",
        "interval": "12h",
        "source_file": "platform_v2/tools/consciousness/jobs.py",
    },
    # =========================================================================
    # platform_v2/tools/department_hq/jobs.py — 6 jobs
    # =========================================================================
    "agent_code_metrics": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Daily codebase metrics snapshot with stale audit detection (3 AM)",
        "interval": "daily 03:00",
        "source_file": "platform_v2/tools/department_hq/jobs.py",
    },
    "agent_pattern_compliance": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Pattern compliance check — ADR-013 and coding standard violations (4 AM)",
        "interval": "daily 04:00",
        "source_file": "platform_v2/tools/department_hq/jobs.py",
    },
    "agent_automated_module_audit": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Automated module audit with Repair Bay proposal generation (3:30 AM)",
        "interval": "daily 03:30",
        "source_file": "platform_v2/tools/department_hq/jobs.py",
    },
    "agent_code_health_digest": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Daily code health Telegram digest summary (8 AM)",
        "interval": "daily 08:00",
        "source_file": "platform_v2/tools/department_hq/jobs.py",
    },
    "agent_code_health_scan": {
        "department": "Engineering & Technology",
        "director": "F.O.R.G.E.",
        "description": "Daily codebase scan — save snapshot for Code Health tab (2 AM)",
        "interval": "daily 02:00",
        "source_file": "platform_v2/tools/department_hq/jobs.py",
    },
    "agent_competitor_scan": {
        "department": "Analytics & Intelligence",
        "director": "S.P.E.C.T.R.A.",
        "description": "AI competitor landscape scan — track and update competitor profiles",
        "interval": "14d",
        "source_file": "platform_v2/tools/department_hq/jobs.py",
    },
    "dispatch_retention_prune": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Nightly prune of old rows: TERMINAL bridge_jobs + dispatch_pending_queue (allowlist) + age-only autonomy_loop_log (14d) + governance_audit_log (365d, signed compliance trail) — bounds unbounded growth (#4542). Tunable via platform_settings retention:*",
        "interval": "daily 04:15",
        "source_file": "platform_v2/tools/department_hq/jobs.py",
    },
    # =========================================================================
    # platform_v2/services/fleet_jobs.py — 6 jobs
    # =========================================================================
    "agent_fleet_health": {
        "department": "Fleet & Infrastructure",
        "director": "A.R.M.A.D.A.",
        "description": "Fleet node heartbeat monitor — return agents to barracks if offline",
        "interval": "30s",
        "source_file": "platform_v2/services/fleet_jobs.py",
    },
    "agent_mesh_health": {
        "department": "Fleet & Infrastructure",
        "director": "A.R.M.A.D.A.",
        "description": "Mesh VPN connectivity monitor for fleet nodes",
        "interval": "60s",
        "source_file": "platform_v2/services/fleet_jobs.py",
    },
    "agent_model_state_save": {
        "department": "Fleet & Infrastructure",
        "director": "A.R.M.A.D.A.",
        "description": "Save loaded model state to DB for restart recovery",
        "interval": "5m",
        "source_file": "platform_v2/services/fleet_jobs.py",
    },
    "agent_standalone_health": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Standalone product health monitor — alert on downtime",
        "interval": "60s",
        "source_file": "platform_v2/services/fleet_jobs.py",
    },
    "department_metrics_rollup": {
        "department": "Analytics & Intelligence",
        "director": "S.P.E.C.T.R.A.",
        "description": "Department metrics rollup — daily aggregation (2 AM)",
        "interval": "daily 02:00",
        "source_file": "platform_v2/services/fleet_jobs.py",
    },
    "fleet_ssl_renewal": {
        "department": "Security & Compliance",
        "director": "V.I.G.I.L.",
        "description": "Fleet wildcard SSL certificate renewal check (3 AM)",
        "interval": "daily 03:00",
        "source_file": "platform_v2/services/fleet_jobs.py",
    },
    # =========================================================================
    # platform_v2/services/agent_jobs.py — 11 jobs
    # =========================================================================
    "agent_hr_tracker": {
        "department": "Human Resources & Culture",
        "director": "K.I.N.",
        "description": "HR tracker — shift transitions, time tracking, attendance",
        "interval": "5m",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    "agent_ethics_monitoring": {
        "department": "Legal & Regulatory",
        "director": "G.A.V.E.L.",
        "description": "Ethics monitoring — C.R.E.E.D. compliance checks for all agents",
        "interval": "15m",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    "agent_training_tick": {
        "department": "Human Resources & Culture",
        "director": "K.I.N.",
        "description": "Training progression tick — advance agent proficiency levels",
        "interval": "5m",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    "agent_welfare_recovery": {
        "department": "Human Resources & Culture",
        "director": "K.I.N.",
        "description": "Welfare recovery — heal stressed/fatigued agents over time",
        "interval": "30m",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    "agent_idle_volunteering": {
        "department": "Human Resources & Culture",
        "director": "K.I.N.",
        "description": "Idle volunteering — assign idle agents to pending work",
        "interval": "5m",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    "agent_performance_rankings": {
        "department": "Analytics & Intelligence",
        "director": "S.P.E.C.T.R.A.",
        "description": "Update agent performance rankings across departments",
        "interval": "15m",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    "agent_queue_exhaustion": {
        "department": "Human Resources & Culture",
        "director": "K.I.N.",
        "description": "DHQ observer — alert when agent is at task_queue_limit (Project #261 #2101)",
        "interval": "10m",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    "agent_counter_drift": {
        "department": "Human Resources & Culture",
        "director": "K.I.N.",
        "description": "Reconcile agent_budgets counter vs bridge_jobs live count — alert on drift > 3",
        "interval": "1h",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    "agent_understaffed_digest": {
        "department": "Human Resources & Culture",
        "director": "K.I.N.",
        "description": "Daily digest — capabilities with no Lv4+ dispatchable agent",
        "interval": "daily 09:00",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    "ollama_lifecycle_telemetry": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Snapshot Ollama loaded models + alert on KEEP_ALIVE stall (#1898)",
        "interval": "5m",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    "department_welfare_digest": {
        "department": "Human Resources & Culture",
        "director": "K.I.N.",
        "description": "Daily welfare roll-up — alert on elevated stress / agents-at-risk (#1933)",
        "interval": "daily 09:05",
        "source_file": "platform_v2/services/agent_jobs.py",
    },
    # =========================================================================
    # platform_v2/tools/social_media/social_worker.py — 3 jobs
    # =========================================================================
    "social_process_queue": {
        "department": "Marketing & Communications",
        "director": "S.I.G.N.A.L.",
        "description": "Process social media post queue — publish pending posts",
        "interval": "60s",
        "source_file": "platform_v2/tools/social_media/social_worker.py",
    },
    "social_refresh_tokens": {
        "department": "Marketing & Communications",
        "director": "S.I.G.N.A.L.",
        "description": "Refresh expiring OAuth tokens for social media platforms",
        "interval": "1h",
        "source_file": "platform_v2/tools/social_media/social_worker.py",
    },
    "social_fetch_analytics": {
        "department": "Marketing & Communications",
        "director": "S.I.G.N.A.L.",
        "description": "Fetch post analytics from social media platforms",
        "interval": "1h",
        "source_file": "platform_v2/tools/social_media/social_worker.py",
    },
    # =========================================================================
    # platform_v2/services/budget_jobs.py — 2 jobs (via JobService)
    # =========================================================================
    "budget_reset": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Daily zero-out of agent task counts and token usage (4 AM)",
        "interval": "daily 04:00",
        "source_file": "platform_v2/services/budget_jobs.py",
    },
    "cooldown_recovery": {
        "department": "Operations & Infrastructure",
        "director": "B.A.S.E.",
        "description": "Transition cooldown agents with cleared budgets back to active (4:05 AM)",
        "interval": "daily 04:05",
        "source_file": "platform_v2/services/budget_jobs.py",
    },
}

# Note: agent_loop.py and security_network/jobs.py both register
# id="agent_anomaly_detection". The security_network version wins at runtime
# (registered later, replace_existing=True). The agent_loop.py version is
# effectively dead — only the security_network entry is in this registry.


def get_department_for_job(job_name):
    """Look up department for a job name.

    Handles both APScheduler IDs (e.g. 'agent_fleet_health') and the shorter
    names used by ``_log_cycle`` (e.g. 'fleet_health_check').  Lookup order:
    1. Exact match
    2. With ``agent_`` prefix
    3. With ``agent_`` prefix + ``_check`` suffix stripped

    Args:
        job_name: Job identifier (APScheduler id or _log_cycle short name).

    Returns:
        Department name string, or 'UNKNOWN' if not registered.
    """
    # 1. Exact match
    entry = JOB_REGISTRY.get(job_name)
    if entry:
        return entry["department"]

    # 2. Try with agent_ prefix
    prefixed = f"agent_{job_name}"
    entry = JOB_REGISTRY.get(prefixed)
    if entry:
        return entry["department"]

    # 3. Fallback — scan for substring match (handles rename drift)
    return "UNKNOWN"


def get_jobs_by_department(department=None):
    """Get all jobs, optionally filtered by department.

    Args:
        department: Optional department name to filter by.

    Returns:
        Dict of job_id -> metadata for matching jobs.
    """
    if department:
        return {k: v for k, v in JOB_REGISTRY.items() if v["department"] == department}
    return JOB_REGISTRY


def get_all_departments():
    """Get list of all departments with job counts.

    Returns:
        Dict of department_name -> {director, count}.
    """
    depts = {}
    for meta in JOB_REGISTRY.values():
        d = meta["department"]
        if d not in depts:
            depts[d] = {"director": meta["director"], "count": 0}
        depts[d]["count"] += 1
    return depts


def get_job_info(job_name):
    """Get full metadata for a specific job.

    Args:
        job_name: The APScheduler job id.

    Returns:
        Dict with department, director, description, interval, source_file
        or None if not found.
    """
    return JOB_REGISTRY.get(job_name)


def get_unregistered_jobs(scheduler_job_ids):
    """Find jobs running in the scheduler that aren't in the registry.

    Args:
        scheduler_job_ids: List of job ids from APScheduler.

    Returns:
        List of job ids not found in JOB_REGISTRY.
    """
    registered = set(JOB_REGISTRY.keys())
    return [jid for jid in scheduler_job_ids if jid not in registered]
