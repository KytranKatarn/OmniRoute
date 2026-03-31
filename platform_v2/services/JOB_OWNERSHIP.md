# Agent Loop Job Ownership

Maps each of the 81 agent_loop jobs to the module that should eventually own its implementation.

## How to Extract a Job

1. Create `tools/<module>/jobs.py` with `register_<module>_jobs(job_service)`
2. Move the handler function from `agent_loop.py` to the module
3. Register with job_service using `func=` pointing to the real function
4. Remove from agent_loop.py (or keep as fallback with `_HAS_MODULE_JOBS` guard)

## Ownership Map

| Job ID | Current Location | Owner Module | Department |
|--------|-----------------|--------------|------------|
| agent_consciousness_analysis | agent_loop.py | Consciousness | Research & Development |
| agent_consciousness_embedding | agent_loop.py | Consciousness | Research & Development |
| agent_skill_sync | agent_loop.py | Consciousness | Documentation & Knowledge |
| agent_github_auto_pull | agent_loop.py | Consciousness | Documentation & Knowledge |
| agent_skill_analyzer | agent_loop.py | Consciousness | Documentation & Knowledge |
| agent_conversation_consolidation | agent_loop.py | Consciousness | Research & Development |
| knowledge_deduplication | agent_loop.py | Consciousness | Research & Development |
| session_indexer | agent_loop.py | Consciousness | Research & Development |
| module_docs_updater | agent_loop.py | Consciousness | Research & Development |
| agent_fleet_health | agent_loop.py | Starbase | Operations & Infrastructure |
| agent_mesh_health | agent_loop.py | Starbase | Operations & Infrastructure |
| agent_model_state_save | agent_loop.py | Starbase | Operations & Infrastructure |
| agent_standalone_health | agent_loop.py | Starbase | Operations & Infrastructure |
| agent_ollama_model_health | agent_loop.py | Starbase | Operations & Infrastructure |
| fleet_ssl_renewal | agent_loop.py | Starbase | Operations & Infrastructure |
| agent_health_probe | agent_loop.py | Starbase | Operations & Infrastructure |
| agent_anomaly_detection | agent_loop.py | Security Network | Security & Compliance |
| agent_ethics_monitoring | agent_loop.py | Security Network | Security & Compliance |
| agent_network_discovery | agent_loop.py | Security Network | Security & Compliance |
| agent_ssh_monitor | agent_loop.py | Security Network | Security & Compliance |
| agent_security_audit | agent_loop.py | Security Network | Security & Compliance |
| agent_ssl_expiry_check | agent_loop.py | Security Network | Security & Compliance |
| agent_daily_dns_report | agent_loop.py | Security Network | Security & Compliance |
| agent_query_spike_detect | agent_loop.py | Security Network | Security & Compliance |
| agent_camera_anomaly | agent_loop.py | Security Network | Security & Compliance |
| agent_auto_block | agent_loop.py | Security Network | Security & Compliance |
| agent_compliance_scan | agent_loop.py | Security Network | Security & Compliance |
| dependabot_scan | agent_loop.py | Security Network | Security & Compliance |
| agent_auto_remediation | agent_loop.py | Security Network | Security & Compliance |
| agent_weekly_dependency_scan | agent_loop.py | Security Network | Security & Compliance |
| agent_email_queue | agent_loop.py | Communications | Marketing & Communications |
| agent_email_inbox | agent_loop.py | Communications | Marketing & Communications |
| agent_email_analyze | agent_loop.py | Communications | Marketing & Communications |
| agent_email_processing | agent_loop.py | Communications | Marketing & Communications |
| agent_telegram_notify | agent_loop.py | Autonomy | Marketing & Communications |
| agent_email_telegram_notify | agent_loop.py | Communications | Marketing & Communications |
| agent_calendar_drive | agent_loop.py | Communications | Marketing & Communications |
| agent_proactive_scan | agent_loop.py | Repair Bay | Engineering & Technology |
| agent_code_metrics | agent_loop.py | Consciousness | Engineering & Technology |
| agent_pattern_compliance | agent_loop.py | Consciousness | Engineering & Technology |
| agent_uncommitted_check | agent_loop.py | Consciousness | Engineering & Technology |
| agent_auto_execute_proposals | agent_loop.py | Repair Bay | Engineering & Technology |
| agent_code_health_scan | agent_loop.py | Consciousness | Engineering & Technology |
| agent_automated_module_audit | agent_loop.py | Consciousness | Engineering & Technology |
| agent_improvement_detection | agent_loop.py | Consciousness | Engineering & Technology |
| agent_batch_medium_issues | agent_loop.py | Repair Bay | Engineering & Technology |
| agent_hr_tracker | agent_loop.py | Department HQ | Human Resources & Culture |
| agent_training_tick | agent_loop.py | Department HQ | Human Resources & Culture |
| agent_welfare_recovery | agent_loop.py | Department HQ | Human Resources & Culture |
| agent_idle_volunteering | agent_loop.py | Department HQ | Human Resources & Culture |
| agent_crew_wellness_tick | agent_loop.py | Department HQ | Human Resources & Culture |
| agent_media_generation | agent_loop.py | Media Studio | Creative & Design |
| media_analytics_snapshot | agent_loop.py | Media Studio | Creative & Design |
| agent_media_queue_cleanup | agent_loop.py | Media Studio | Creative & Design |
| agent_media_export_cleanup | agent_loop.py | Media Studio | Creative & Design |
| social_video_generate | agent_loop.py | Social Media | Creative & Design |
| social_video_auto_approve | agent_loop.py | Social Media | Creative & Design |
| social_video_publish | agent_loop.py | Social Media | Creative & Design |
| agent_reports | agent_loop.py | Consciousness | Analytics & Intelligence |
| agent_performance_rankings | agent_loop.py | Department HQ | Analytics & Intelligence |
| department_metrics_rollup | agent_loop.py | Department HQ | Analytics & Intelligence |
| stock_price_updater | agent_loop.py | StockBot | Finance & Accounting |
| market_watch_cycle | agent_loop.py | Market Watch | Analytics & Intelligence |
| game_world_event_processor | agent_loop.py | Game Studio | Creative & Design |
| game_market_price_update | agent_loop.py | Game Studio | Creative & Design |
| agent_scheduled_tasks | agent_loop.py | Autonomy | Executive Office |
| agent_reminders | agent_loop.py | Autonomy | Executive Office |
| agent_approvals | agent_loop.py | Autonomy | Executive Office |
| agent_briefings | agent_loop.py | Autonomy | Executive Office |
| agent_daily_self_reflection | agent_loop.py | Consciousness | Executive Office |
| agent_stale_job_reaper | agent_loop.py | Autonomy | Operations & Infrastructure |
| agent_stuck_job_watchdog | agent_loop.py | Autonomy | Operations & Infrastructure |
| agent_mission_schedule | agent_loop.py | Starbase | Operations & Infrastructure |
| agent_notification_cleanup | agent_loop.py | Autonomy | Operations & Infrastructure |
| agent_browser_tasks | agent_loop.py | Autonomy | Operations & Infrastructure |
| git_change_tracker | agent_loop.py | Consciousness | Research & Development |
| agent_auto_log_ingestion | agent_loop.py | Consciousness | Research & Development |
| agent_weekly_memory_consolidation | agent_loop.py | Consciousness | Research & Development |
| job_47_chat_memories | agent_loop.py | Consciousness | Research & Development |
| agent_code_health_digest | agent_loop.py | Consciousness | Marketing & Communications |
| agent_competitor_scan | agent_loop.py | Consciousness | Marketing & Communications |
| budget_reset | job_service.py | Autonomy | Operations & Infrastructure |
| cooldown_recovery | job_service.py | Autonomy | Operations & Infrastructure |
