"""APScheduler sidecar daemon.

Path C of the QA-scheduled flake fix (decision_id 557). APScheduler
lived in the gunicorn worker process, which forced ``--workers=1`` to
avoid double-firing the 117 scheduled jobs. Bulk QA load pinned the
sole worker and made auth fail in cascades. This entrypoint runs the
exact same scheduler in its own container so the platform gunicorn can
scale workers freely.

Strategy: import ``app:app`` (the Flask app) so all 117 jobs keep their
``with_app_context()`` closures pointing at a real Flask app instance.
Two env flags gate the side effects in ``app.py`` so the work doesn't
double-up:

  * ``ARCHIE_RUN_SCHEDULER`` — set to ``1`` here, ``0`` on the platform
    container (after Path C activation) so only this process owns the
    scheduler.
  * ``ARCHIE_RUN_TELEGRAM`` — set to ``0`` here so the Telegram bot
    fcntl lock stays with the platform container.

A ``pg_advisory_lock`` guards against a second scheduler instance
starting accidentally — duplicate schedulers would re-introduce the
same double-fire bug we're trying to escape.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import time

# Flip env BEFORE importing app — app.py reads these at module load
os.environ["ARCHIE_RUN_SCHEDULER"] = "1"
os.environ.setdefault("ARCHIE_RUN_TELEGRAM", "0")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="[%(asctime)s] %(levelname)s scheduler_daemon: %(message)s",
)
logger = logging.getLogger(__name__)

# Singleton guard — pg_advisory_lock keyed on a constant. If two
# scheduler containers start, only one wins this lock; the other
# exits with a clear error.
_ADVISORY_LOCK_KEY = 0x4152434843484544  # "ARCHCHED" — Archie scheduler
_advisory_conn = None  # held for the lifetime of the process


def _acquire_singleton_lock() -> None:
    """Take a session-level advisory lock on the platform DB. Exits if
    another scheduler instance already holds it."""
    global _advisory_conn
    import psycopg2

    # Resolve password via the same Docker-secret + env-var fallback the
    # rest of the platform uses (database.py:_get_db_password).
    pw_file = os.environ.get("DB_PASSWORD_FILE", "/run/secrets/db_password")
    db_password = ""
    if os.path.exists(pw_file):
        try:
            with open(pw_file) as f:
                db_password = f.read().strip()
        except Exception as e:
            logger.warning("Could not read %s: %s", pw_file, e)
    if not db_password:
        db_password = os.environ.get("DB_PASSWORD", "")

    dsn = {
        "host": os.getenv("DB_HOST", "archie_database"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "database": os.getenv("DB_NAME", "archie"),
        "user": os.getenv("DB_USER", "archie"),
        "password": db_password,
    }
    _advisory_conn = psycopg2.connect(**dsn)
    _advisory_conn.autocommit = True
    with _advisory_conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
        got = cur.fetchone()[0]
    if not got:
        logger.error(
            "Another scheduler container already holds the singleton lock — "
            "refusing to start. Stop the other instance and retry."
        )
        sys.exit(2)
    logger.info("Acquired pg_advisory_lock %s — singleton confirmed", hex(_ADVISORY_LOCK_KEY))


def _shutdown(signum, _frame):
    logger.info("Received signal %s — shutting down scheduler", signum)
    try:
        scheduler = app.config.get("CONSCIOUSNESS_SCHEDULER")  # noqa: F821
        if scheduler is not None and getattr(scheduler, "running", False):
            scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped cleanly")
    except Exception as exc:
        logger.warning("Scheduler shutdown raised: %s", exc)
    if _advisory_conn is not None:
        try:
            _advisory_conn.close()
        except Exception:
            pass
    sys.exit(0)


def main() -> None:
    _acquire_singleton_lock()

    # Importing app triggers init_consciousness_scheduler() + AgentLoop.start()
    # + JobService init when ARCHIE_RUN_SCHEDULER=1 (gated in app.py).
    global app  # noqa: PLW0603 — exposed for _shutdown handler
    from app import app  # type: ignore  # noqa: F401

    scheduler = app.config.get("CONSCIOUSNESS_SCHEDULER")
    agent_loop = app.config.get("AGENT_LOOP")

    if scheduler is None:
        logger.error("Scheduler did not initialize. Is ARCHIE_RUN_SCHEDULER=1 set?")
        sys.exit(3)

    job_count = len(scheduler.get_jobs())
    logger.info(
        "Scheduler daemon online — host=%s, jobs=%d, agent_loop=%s",
        socket.gethostname(),
        job_count,
        "running" if agent_loop and getattr(agent_loop, "running", False) else "stopped",
    )

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Block forever — APScheduler runs jobs in its own thread pool.
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
