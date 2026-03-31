"""agent_loop_bridge.py — Bridge between AgentLoop and JobService.

Phase 5 of Agent Lifecycle Coordination.
Scans APScheduler for all agent_loop jobs and registers them with
job_service so Autonomy can see, monitor, and control them.

We register metadata only — APScheduler continues to own execution.
Jobs are inserted directly into job_service._jobs to avoid creating
duplicate APScheduler entries (agent_loop already owns the schedule).
"""

import logging

logger = logging.getLogger(__name__)

# Map job IDs to departments (expanded from agent_loop's JOB_DEPARTMENT_MAP)
AGENT_LOOP_DEPARTMENTS = {
    # Executive Office
    "agent_scheduled_tasks": "Executive Office",
    "agent_reminders": "Executive Office",
    "agent_approvals": "Executive Office",
    "agent_briefings": "Executive Office",
    "agent_daily_self_reflection": "Executive Office",
    # Communications
    "agent_email_queue": "Marketing & Communications",
    "agent_email_inbox": "Marketing & Communications",
    "agent_email_analyze": "Marketing & Communications",
    "agent_email_processing": "Marketing & Communications",
    "agent_telegram_notify": "Marketing & Communications",
    "agent_email_telegram_notify": "Marketing & Communications",
    "agent_calendar_drive": "Marketing & Communications",
    # Security
    "agent_anomaly_detection": "Security & Compliance",
    "agent_ethics_monitoring": "Security & Compliance",
    "agent_network_discovery": "Security & Compliance",
    "agent_ssh_monitor": "Security & Compliance",
    "agent_security_audit": "Security & Compliance",
    "agent_ssl_expiry_check": "Security & Compliance",
    "agent_daily_dns_report": "Security & Compliance",
    "agent_query_spike_detect": "Security & Compliance",
    "agent_camera_anomaly": "Security & Compliance",
    "agent_auto_block": "Security & Compliance",
    "agent_compliance_scan": "Security & Compliance",
    "dependabot_scan": "Security & Compliance",
    "agent_auto_remediation": "Security & Compliance",
    "agent_weekly_dependency_scan": "Security & Compliance",
    # Operations
    "agent_browser_tasks": "Operations & Infrastructure",
    "agent_stale_job_reaper": "Operations & Infrastructure",
    "agent_stuck_job_watchdog": "Operations & Infrastructure",
    "agent_mission_schedule": "Operations & Infrastructure",
    "agent_fleet_health": "Operations & Infrastructure",
    "agent_mesh_health": "Operations & Infrastructure",
    "agent_model_state_save": "Operations & Infrastructure",
    "agent_notification_cleanup": "Operations & Infrastructure",
    "agent_health_probe": "Operations & Infrastructure",
    "agent_ollama_model_health": "Operations & Infrastructure",
    "agent_standalone_health": "Operations & Infrastructure",
    "fleet_ssl_renewal": "Operations & Infrastructure",
    # Engineering
    "agent_proactive_scan": "Engineering & Technology",
    "agent_code_metrics": "Engineering & Technology",
    "agent_pattern_compliance": "Engineering & Technology",
    "agent_uncommitted_check": "Engineering & Technology",
    "agent_auto_execute_proposals": "Engineering & Technology",
    "agent_code_health_scan": "Engineering & Technology",
    "agent_automated_module_audit": "Engineering & Technology",
    "agent_improvement_detection": "Engineering & Technology",
    "agent_batch_medium_issues": "Engineering & Technology",
    # Research
    "knowledge_deduplication": "Research & Development",
    "session_indexer": "Research & Development",
    "module_docs_updater": "Research & Development",
    "git_change_tracker": "Research & Development",
    "agent_consciousness_analysis": "Research & Development",
    "agent_consciousness_embedding": "Research & Development",
    "agent_conversation_consolidation": "Research & Development",
    "agent_weekly_memory_consolidation": "Research & Development",
    "agent_auto_log_ingestion": "Research & Development",
    "job_47_chat_memories": "Research & Development",
    # Documentation
    "agent_skill_sync": "Documentation & Knowledge",
    "agent_github_auto_pull": "Documentation & Knowledge",
    "agent_skill_analyzer": "Documentation & Knowledge",
    # Human Resources
    "agent_hr_tracker": "Human Resources & Culture",
    "agent_training_tick": "Human Resources & Culture",
    "agent_welfare_recovery": "Human Resources & Culture",
    "agent_idle_volunteering": "Human Resources & Culture",
    "agent_crew_wellness_tick": "Human Resources & Culture",
    # Creative
    "agent_media_generation": "Creative & Design",
    "media_analytics_snapshot": "Creative & Design",
    "agent_media_queue_cleanup": "Creative & Design",
    "agent_media_export_cleanup": "Creative & Design",
    "social_video_generate": "Creative & Design",
    "social_video_auto_approve": "Creative & Design",
    "social_video_publish": "Creative & Design",
    # Analytics
    "agent_reports": "Analytics & Intelligence",
    "agent_performance_rankings": "Analytics & Intelligence",
    "department_metrics_rollup": "Analytics & Intelligence",
    # Marketing
    "agent_code_health_digest": "Marketing & Communications",
    "agent_competitor_scan": "Marketing & Communications",
    # SaaS
    "stock_price_updater": "Finance & Accounting",
    "market_watch_cycle": "Analytics & Intelligence",
    # Game Studio
    "game_world_event_processor": "Creative & Design",
    "game_market_price_update": "Creative & Design",
}


def bridge_agent_loop_to_job_service(scheduler, job_service):
    """Scan APScheduler for all agent_loop jobs and register with job_service.

    This creates a metadata overlay — job_service tracks status/department
    while APScheduler continues to own execution. We write directly to
    job_service._jobs to avoid creating duplicate APScheduler entries.

    Args:
        scheduler: APScheduler BackgroundScheduler instance
        job_service: JobService instance

    Returns:
        int: Number of jobs bridged
    """
    if not scheduler or not job_service:
        logger.warning("[AgentLoopBridge] Missing scheduler or job_service")
        return 0

    registered = 0
    for job in scheduler.get_jobs():
        job_id = job.id
        # Skip jobs already registered by job_service itself
        if job_id.startswith("jobsvc_"):
            continue

        # Extract interval from trigger
        interval_hours = _get_interval_hours(job)
        department = AGENT_LOOP_DEPARTMENTS.get(job_id, "Operations & Infrastructure")

        # Register metadata only — write directly to _jobs dict
        # to avoid _schedule_with_apscheduler creating duplicates
        job_service._jobs[job_id] = {
            "name": job_id,
            "func": job.func,  # Reference to actual APScheduler func
            "interval_hours": interval_hours,
            "department": department,
            "enabled": True,
            "description": job.name or job_id,
            "cron_hour": None,
            "cron_minute": 0,
            "last_run": None,
            "last_status": None,
            "last_duration_ms": None,
            "run_count": 0,
            "error_count": 0,
        }
        registered += 1

    logger.info(
        "[AgentLoopBridge] Registered %d agent_loop jobs with job_service",
        registered,
    )
    return registered


def _get_interval_hours(job):
    """Extract interval in hours from an APScheduler job trigger."""
    trigger = job.trigger
    trigger_str = str(trigger)

    # IntervalTrigger
    if hasattr(trigger, "interval"):
        return trigger.interval.total_seconds() / 3600.0
    # CronTrigger — approximate as 24h
    if "cron" in trigger_str.lower():
        return 24.0
    return 1.0
