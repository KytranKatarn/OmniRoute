"""Media Hub scheduled health jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from health_observer_common import *  # noqa: F401,F403
from health_observer_services import arr_database_probe, grab_notify_probe, indexer_health_probe, maven_diagnostic_probe, quality_probe, service_health_probe
from health_observer_downloads import download_client_health_probe, download_pipeline_probe
from health_observer_queues import library_coverage_probe, stale_queue_probe
from health_observer_maven_jobs import _maven_daily_optimize_proposal, _maven_optimize_executor, _maven_removal_executor, _tdarr_dispatch_orchestration, _tdarr_library_review

from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger("media_hub.observer")

def start_scheduler() -> BackgroundScheduler:
    """Idempotent — safe to call on every app boot; subsequent calls return
    the already-running scheduler."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True, timezone=timezone.utc)
    _scheduler.add_job(
        service_health_probe,
        "interval",
        minutes=30,
        id="service_health",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),  # fire once at startup
    )
    _scheduler.add_job(
        indexer_health_probe,
        "interval",
        minutes=30,
        id="indexer_health",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    # Execute A.R.C.H.I.E.-approved M.A.V.E.N. removals (project #385 task #4745).
    # No startup fire — a pending approval can wait the first 5 min.
    _scheduler.add_job(
        _maven_removal_executor,
        "interval",
        minutes=5,
        id="maven_removal_executor",
        max_instances=1,
        coalesce=True,
    )
    # Tdarr video optimize (project #385 Phase 3): drain approved transcodes + periodic review.
    _scheduler.add_job(
        _maven_optimize_executor,
        "interval",
        minutes=5,
        id="maven_optimize_executor",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _tdarr_library_review,
        "interval",
        hours=6,
        id="tdarr_library_review",
        max_instances=1,
        coalesce=True,
    )
    # Dispatch-orchestrated Tdarr drain (#385): yield GPU transcode workers to DHQ
    # inference every minute while an approved optimize run is active (+ cleanup when
    # idle). Cheap local Tdarr reads + one fail-open hub call; no startup fire.
    _scheduler.add_job(
        _tdarr_dispatch_orchestration,
        "interval",
        minutes=1,
        id="tdarr_dispatch_orchestration",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        maven_diagnostic_probe,
        "interval",
        minutes=30,
        id="maven_diagnostic",
        max_instances=1,
        coalesce=True,
        # Offset 5 min from startup so service health runs first
        next_run_time=datetime.now(timezone.utc).replace(second=0, microsecond=0),
    )
    _scheduler.add_job(
        quality_probe,
        "interval",
        hours=12,
        id="quality_probe",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        download_pipeline_probe,
        "interval",
        minutes=30,
        id="download_pipeline",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.add_job(
        download_client_health_probe,
        "interval",
        minutes=30,
        id="download_client_health",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.add_job(
        library_coverage_probe,
        "interval",
        hours=2,
        id="library_coverage",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.add_job(
        arr_database_probe,
        "interval",
        minutes=30,
        id="arr_database",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.add_job(
        stale_queue_probe,
        "interval",
        minutes=30,
        id="stale_queue",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.add_job(
        grab_notify_probe,
        "interval",
        minutes=5,
        id="grab_notify",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    # Owner-requested: one optimize approval per day (Telegram + DHQ Approvals). Hour is UTC
    # (this scheduler runs UTC); default 14:00 UTC ~= 10:00 ET. Env MAVEN_DAILY_OPTIMIZE_HOUR_UTC.
    import os as _os

    _scheduler.add_job(
        _maven_daily_optimize_proposal,
        "cron",
        hour=int(_os.getenv("MAVEN_DAILY_OPTIMIZE_HOUR_UTC", "14")),
        minute=0,
        id="maven_daily_optimize",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    log.info(
        "media hub observer scheduler started ("
        "every 5m: grab_notify; "
        "every 30m: service_health, indexer_health, maven_diagnostic, download_pipeline, "
        "download_client_health, arr_database, stale_queue; "
        "every 2h: library_coverage; every 12h: quality_probe; "
        "daily: maven_daily_optimize)"
    )
    return _scheduler
