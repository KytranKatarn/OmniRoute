"""Shared job-governance wrapper — DHQ Job Governance (project #332).

Wraps a scheduled / recurring APScheduler job so it emits an immutable
``governance_audit_log`` trail (start → success | failed) and, on failure,
notifies A.R.C.H.I.E. via ``telegram_service`` — respecting a configurable
Eastern-time (America/Toronto) quiet-hours window.

Design contract (project #332 spec):
  * "Pure automation" jobs (device scans, DNS, SSL, compliance, embedding, …)
    → governance_audit_log start/complete/fail + A.R.C.H.I.E. failure alert.
  * Agent-cognitive work already routes through the DHQ dispatcher, which
    applies the welfare + C.R.E.E.D. gate + cost tracking itself — so this
    wrapper deliberately does NOT gate/skip a job on a C.R.E.E.D. score.
    Silently skipping a live security or compliance scan would be unsafe.

Governance here is ADDITIVE and FAIL-SAFE: the audit write and the failure
notification can NEVER raise into the job, and a job exception is logged +
audited + notified but NOT re-raised — a single job failure must never crash
the shared APScheduler.

Reference implementation: Job #60 backup-retention cleanup. Reused by Security
Network (#2741), Consciousness (#2742), and Fleet / DHQ (#2743).
"""

import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# platform_settings key holding the failure-alert quiet window (local ET),
# format "H-H" (e.g. "22-7" = 22:00–06:59). "" / missing key => the default.
_QUIET_HOURS_KEY = "job_governance:quiet_hours"
_QUIET_HOURS_DEFAULT = "22-7"  # 10 PM–7 AM Eastern (Montreal), DST-aware


# --------------------------------------------------------------------------- #
# quiet hours (Eastern / America/Toronto)
# --------------------------------------------------------------------------- #
def _setting(key: str) -> Optional[str]:
    """Read a ``platform_settings`` value as a stripped string; None on any
    error / missing key (so callers fall back to a default)."""
    try:
        from db import get_db

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            cur.close()
        finally:
            conn.close()
        if not row:
            return None
        val = row["value"] if isinstance(row, dict) else row[0]
        # value is JSONB; a bare JSON string decodes to a Python str already.
        return str(val).strip() if val is not None else None
    except Exception:  # noqa: BLE001 — a settings hiccup must never break a job
        return None


def in_quiet_hours() -> bool:
    """True if the current Eastern-time hour is inside the failure-alert quiet
    window (default '22-7' = 22:00–06:59 ET, DST-aware EDT/EST).

    Fail-open: any parse/clock error returns False (NOT quiet) so the failure
    alert still fires — better to over-notify on a job failure than to miss it.
    Mirrors the mailhq ``in_quiet_hours`` convention for consistency."""
    raw = _setting(_QUIET_HOURS_KEY)
    if raw is None:
        raw = _QUIET_HOURS_DEFAULT
    raw = (raw or "").strip()
    if not raw or "-" not in raw:
        return False
    try:
        s, e = raw.split("-")
        start, end = int(s), int(e)
    except Exception:  # noqa: BLE001
        return False
    if start == end:
        return False
    try:
        from services.time_utils import now_local

        hour = now_local().hour
    except Exception:  # noqa: BLE001
        return False
    if start < end:
        return start <= hour < end
    # window wraps midnight (e.g. 22-7 => 22:00..06:59)
    return hour >= start or hour < end


# --------------------------------------------------------------------------- #
# audit + failure notification (both fail-safe — never raise into the job)
# --------------------------------------------------------------------------- #
def _audit(job_name: str, outcome: str, department: str, details: Optional[dict] = None) -> None:
    """Write one immutable ``governance_audit_log`` row. Never raises.

    event_type='scheduled_job' makes the whole governance rollout queryable
    (``WHERE event_type='scheduled_job'``); outcome ∈ running|success|failed."""
    try:
        import json

        from db import get_db

        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO governance_audit_log
                (event_type, event_category, action, outcome, details, timestamp)
                VALUES ('scheduled_job', 'automation', %s, %s, %s, NOW())
                """,
                (
                    f"{job_name}:{outcome}",
                    outcome,
                    json.dumps({**(details or {}), "department": department, "job": job_name}),
                ),
            )
            conn.commit()
            cur.close()
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 — audit must never break a job
        logger.error("job_governance audit write failed for %s: %s", job_name, e)


def _notify_failure(job_name: str, department: str, error: BaseException, notify_fn: Callable) -> bool:
    """Telegram a job failure via A.R.C.H.I.E. — quiet-hours-gated (ET). Never
    raises. Returns True iff an alert was actually sent."""
    try:
        if in_quiet_hours():
            logger.info("job_governance: suppressed failure alert for %s (quiet hours)", job_name)
            return False
        title = f"Scheduled job failed: {job_name}"
        message = f"{department} job `{job_name}` raised: {str(error)[:400]}"
        notify_fn(title, message)
        return True
    except Exception as e:  # noqa: BLE001 — a comms bug must never break a job
        logger.error("job_governance failure-notify failed for %s: %s", job_name, e)
        return False


# --------------------------------------------------------------------------- #
# the wrapper
# --------------------------------------------------------------------------- #
def governed_job(
    fn: Callable,
    *,
    department: str,
    flask_app=None,
    notify_fn: Optional[Callable] = None,
    notify_on_fail: bool = True,
    fn_args: tuple = (),
) -> Callable:
    """Wrap a scheduled-job callable with additive, fail-safe DHQ governance.

    - runs ``fn(*fn_args)`` inside ``flask_app.app_context()`` when ``flask_app``
      given (so DB/telegram inside the job — and the failure alert — have context).
      ``fn_args`` defaults to ``()`` (zero-arg); pass e.g. ``(flask_app,)`` for a
      job registered as ``fn(app)`` or ``(flask_app, scheduler)`` for ``fn(app, sched)``.
    - writes governance_audit_log: start(running) → success(duration_ms)
      | failed(duration_ms + error)
    - on failure (and ``notify_on_fail``): A.R.C.H.I.E. Telegram via ``notify_fn``
      (default ``services.telegram_service.send_system``), quiet-hours-gated (ET)
    - governance + telegram never raise into the job; a job exception is logged,
      audited, and notified but NOT re-raised (a crash must not kill the scheduler)

    Preserves ``fn.__name__`` so APScheduler job ids / logs are unchanged.
    """
    job_name = getattr(fn, "__name__", "job")

    def _default_notify(title: str, message: str) -> None:
        from services.telegram_service import send_system

        send_system(title, message)

    def _safe_audit(outcome: str, details: Optional[dict] = None) -> None:
        # a broken audit path must NEVER stop or crash the wrapped job
        try:
            _audit(job_name, outcome, department, details)
        except Exception:  # noqa: BLE001
            logger.exception("job_governance audit(%s) raised for %s", outcome, job_name)

    def _run() -> None:
        nf = notify_fn or _default_notify
        started = time.monotonic()
        _safe_audit("running")
        try:
            fn(*fn_args)
        except Exception as e:  # noqa: BLE001 — swallow so the scheduler survives
            dur = int((time.monotonic() - started) * 1000)
            logger.exception("Scheduled job %s failed", job_name)
            _safe_audit("failed", {"duration_ms": dur, "error": str(e)[:500]})
            if notify_on_fail:
                _notify_failure(job_name, department, e, nf)
            return
        dur = int((time.monotonic() - started) * 1000)
        _safe_audit("success", {"duration_ms": dur})

    def wrapper() -> None:
        if flask_app is not None:
            with flask_app.app_context():
                _run()
        else:
            _run()

    wrapper.__name__ = job_name
    return wrapper
