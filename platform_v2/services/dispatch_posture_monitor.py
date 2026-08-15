"""Rolling-baseline dispatch posture alarm (#5596).

WHY THIS EXISTS
On 2026-08-04 both hub GPUs fell off the PCIe bus. The platform then ran
degraded for EIGHT DAYS and nothing paged. Measured from task_execution_log:

    day         runs    ok     failed  avg_s
    2026-08-03  11750   11569    181    24.5   <- healthy
    2026-08-04  13101   12685    416    26.9   <- GPUs drop 22:11 / 22:23
    2026-08-06   7436    6434   1002    44.9   <- degraded
    2026-08-11   6640    5709    931    46.2   <- still degraded, 7 days on

avg dispatch 21-27s -> 45-55s (2x), failure rate ~1-3% -> ~13-16% (~10x),
throughput 11-13k -> 5-7k runs/day (half). For eight days
``get_quick_summary`` answered "Platform: OK", because it asks whether
components ANSWER, never whether they answer WELL.

DESIGN — SYMPTOM-BASED, NOT CAUSE-BASED
A GPU-enumeration check would have caught this ONE incident. This watches the
platform's actual output instead, so it also catches node loss, a bad model
pin, a saturated queue, or a cause nobody has thought of yet. The 08-04
outage is the calibration case, not the scope.

THE BASELINE IS THE PLATFORM'S OWN RECENT HISTORY, not a hardcoded number.
Absolute thresholds rot: they are set once against today's hardware and then
silently mis-describe the platform after every capacity change. A ratio
against trailing behaviour keeps meaning as the cluster grows.

NO LLM IN THE ALERT PATH — deterministic arithmetic only, same as
``backup_posture_monitor`` and ``dr_posture_monitor``. An alarm that needs
inference to fire cannot report that inference is broken.

FAIL-SAFE DIRECTION
Every uncertain input yields ``unknown``, never an alert: too little data,
no baseline, a bad threshold override. A fresh deploy or a quiet night must
not page. The inverse (staying silent when data is thin) is the failure this
file exists to fix, so ``unknown`` is REPORTED in the result even when it is
not alerted — callers can surface it without being woken by it.
"""

from __future__ import annotations

import logging
from typing import Dict

logger = logging.getLogger(__name__)

# Calibrated against the 08-04 incident: every one of these would have fired
# on 2026-08-06, the first full degraded day, ~36h after the GPUs died.
_DEFAULTS: Dict[str, float] = {
    # Windows.
    "recent_hours": 6.0,
    "baseline_hours": 168.0,  # 7 days
    "liveness_hours": 1.0,
    # Throughput gets its OWN, LONGER recent window. Dispatch volume is
    # strongly diurnal (agents rest 8PM-6AM ET), so comparing a 6h window
    # against a 7-day average would fire every quiet night — a false page
    # that trains people to ignore the alarm, which is worse than no alarm.
    # 24h vs 7d has no time-of-day bias in either term.
    "throughput_recent_hours": 24.0,
    # Failure rate: ratio vs baseline AND an absolute floor, so a platform
    # with a near-zero baseline does not page on 0.1% -> 0.4%.
    "fail_ratio": 3.0,
    "fail_floor_pct": 8.0,  # incident hit 13-16%; healthy is 1-3%
    # ABSOLUTE BACKSTOPS — fire regardless of baseline.
    # A rolling baseline has one failure mode: after a LONG incident it
    # absorbs the incident and goes blind to a recurrence of the same size.
    # Measured live on 2026-08-15, with the 8-day outage still inside the
    # 7-day window: baseline 12.2% / 48.1s, pushing the relative trip points
    # to 36.7% / 77.0s — i.e. the alarm had quietly lost most of its
    # sensitivity precisely because the platform had been sick for a while.
    # These ceilings are absolute "this is bad on its own terms" limits that
    # no baseline can raise. Set well above healthy (1-3%, 21-27s) so they
    # never fire on a good day, and below the poisoned trip points so they
    # still bite while the baseline heals.
    "fail_ceiling_pct": 20.0,
    "latency_ceiling_s": 70.0,
    # Latency: incident doubled (21-27s -> 45-55s). Set at 1.6 rather than
    # 1.8 for margin: healthy days already range 21->27s (1.28x) on their
    # own, so 1.6 sits clear of normal variation while still firing on the
    # incident's mildest degraded day (44.9s vs 24.5s baseline = 1.83x).
    "latency_ratio": 1.6,
    # Throughput: incident halved (11-13k/day -> 5-7k/day).
    "throughput_drop_ratio": 0.6,
    # Sample-size guards — below these, report `unknown`, never alert.
    "min_recent_samples": 40.0,
    "min_baseline_samples": 500.0,
}

_SETTING_PREFIX = "dispatch:posture:"


def _thresholds(cur) -> Dict[str, float]:
    """Live overrides from platform_settings — tunable with no deploy.

    A malformed override is IGNORED with a warning rather than raising: a
    typo in a settings row must not take the alarm offline, which would
    recreate the very blind spot this file closes.
    """
    out = dict(_DEFAULTS)
    try:
        cur.execute(
            "SELECT key, value FROM platform_settings WHERE key LIKE %s",
            (_SETTING_PREFIX + "%",),
        )
        for row in cur.fetchall() or []:
            key = (row["key"] if isinstance(row, dict) else row[0]) or ""
            raw = row["value"] if isinstance(row, dict) else row[1]
            name = key[len(_SETTING_PREFIX) :]
            if name not in out:
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                logger.warning("dispatch_posture: ignoring non-numeric override %s=%r", key, raw)
                continue
            if val <= 0:
                logger.warning("dispatch_posture: ignoring non-positive override %s=%r", key, raw)
                continue
            out[name] = val
    except Exception as exc:  # pragma: no cover - settings table optional
        logger.warning("dispatch_posture: threshold overrides unavailable (%s)", exc)
    return out


def _fail_pct(health: Dict) -> float:
    """Failure share of DECIDED dispatches, infra timeouts included.

    Deliberately uses `failed` (not `failed_real`): a queue timeout still
    means work did not get done. #4538 splits them for the DHQ tile, where a
    human is reading; an alarm should not learn to discount a whole class of
    failure.
    """
    decided = int(health.get("decided") or 0)
    if decided <= 0:
        return 0.0
    return round(int(health.get("failed") or 0) / decided * 100, 2)


def check_dispatch_posture(**overrides) -> Dict[str, object]:
    """Compare a recent dispatch window against a trailing baseline.

    Returns a dict with `checks` (each `ok` / `alert` / `unknown`), the
    measured numbers behind each verdict, and `alerts_sent`. Never raises —
    a monitor that can crash is a monitor that stops monitoring.
    """
    result: Dict[str, object] = {"ok": True, "checks": {}, "alerts_sent": 0}
    try:
        from database import get_db_cursor
        from services.dispatch_health_service import dispatch_health

        with get_db_cursor() as (_conn, cur):
            th = _thresholds(cur)
        th.update({k: float(v) for k, v in overrides.items() if k in _DEFAULTS})

        recent_h = th["recent_hours"]
        base_h = th["baseline_hours"]

        recent = dispatch_health(recent_h)
        # NOTE: dispatch_health only takes "last N hours", so the baseline
        # window CONTAINS the recent one. At 6h in 168h the dilution is ~3.6%
        # and it biases CONSERVATIVE — a degraded present drags the baseline
        # toward itself, making the alarm harder to trip, never easier. Worth
        # the imprecision to keep ONE definition of dispatch health (the
        # dispatch_health_service SSOT) rather than forking the SQL.
        baseline = dispatch_health(base_h)

        r_total = int(recent.get("total") or 0)
        b_total = int(baseline.get("total") or 0)
        checks: Dict[str, Dict] = {}
        alerts = []

        # --- 1. LIVENESS -------------------------------------------------
        # Catches the failure the 8-day drift check CANNOT: a platform that
        # stops dispatching entirely. archie_platform sat dead 29 minutes on
        # 2026-08-15 (boot-order race, workers failed, no retry) with nothing
        # paging. Deliberately a SHORT window and an absolute zero, because
        # "no work at all" needs no baseline to interpret.
        live = dispatch_health(th["liveness_hours"])
        live_total = int(live.get("total") or 0)
        if live_total <= 0:
            checks["liveness"] = {
                "status": "alert",
                "window_hours": th["liveness_hours"],
                "dispatches": 0,
            }
            alerts.append(
                (
                    "Dispatch STOPPED — no activity",
                    f"ZERO dispatches in the last {th['liveness_hours']:.0f}h. "
                    f"The platform is not doing any work. Check archie_platform "
                    f"and archie_scheduler are running, and that the DB is reachable.",
                    "critical",
                    1.0,
                )
            )
        else:
            checks["liveness"] = {
                "status": "ok",
                "window_hours": th["liveness_hours"],
                "dispatches": live_total,
            }

        # --- sample-size gate for the comparative checks -----------------
        if r_total < th["min_recent_samples"] or b_total < th["min_baseline_samples"]:
            for name in ("failure_rate", "latency", "throughput"):
                checks[name] = {
                    "status": "unknown",
                    "reason": (
                        f"insufficient samples (recent={r_total}/"
                        f"{int(th['min_recent_samples'])}, "
                        f"baseline={b_total}/{int(th['min_baseline_samples'])})"
                    ),
                }
            result["checks"] = checks
            result["alerts_sent"] = _send(alerts)
            _record_run(result)
            return result

        # --- 2. FAILURE RATE ---------------------------------------------
        r_fail = _fail_pct(recent)
        b_fail = _fail_pct(baseline)
        # Relative trip (must beat BOTH the ratio and the materiality floor),
        # OR the absolute ceiling which no baseline can raise.
        fail_trip = min(max(b_fail * th["fail_ratio"], th["fail_floor_pct"]), th["fail_ceiling_pct"])
        if r_fail >= fail_trip:
            checks["failure_rate"] = {
                "status": "alert",
                "recent_pct": r_fail,
                "baseline_pct": b_fail,
                "threshold_pct": round(fail_trip, 2),
            }
            alerts.append(
                (
                    "Dispatch failure rate spike",
                    f"Failures {r_fail}% over the last {recent_h:.0f}h vs {b_fail}% "
                    f"baseline ({base_h/24:.0f}d) — threshold {fail_trip:.1f}%. "
                    f"{recent.get('failed')} of {recent.get('decided')} decided dispatches failed.",
                    "critical",
                    6.0,
                )
            )
        else:
            checks["failure_rate"] = {
                "status": "ok",
                "recent_pct": r_fail,
                "baseline_pct": b_fail,
                "threshold_pct": round(fail_trip, 2),
            }

        # --- 3. LATENCY ---------------------------------------------------
        r_ms = float(recent.get("avg_duration_ms") or 0)
        b_ms = float(baseline.get("avg_duration_ms") or 0)
        if b_ms > 0 and r_ms > 0:
            lat_trip = min(b_ms * th["latency_ratio"], th["latency_ceiling_s"] * 1000.0)
            if r_ms >= lat_trip:
                checks["latency"] = {
                    "status": "alert",
                    "recent_s": round(r_ms / 1000, 1),
                    "baseline_s": round(b_ms / 1000, 1),
                    "threshold_s": round(lat_trip / 1000, 1),
                }
                alerts.append(
                    (
                        "Dispatch latency degraded",
                        f"Average dispatch {r_ms/1000:.1f}s over the last {recent_h:.0f}h "
                        f"vs {b_ms/1000:.1f}s baseline ({base_h/24:.0f}d) — "
                        f"threshold {lat_trip/1000:.1f}s. Work is completing, but "
                        f"{r_ms/b_ms:.1f}x slower than normal.",
                        "warning",
                        6.0,
                    )
                )
            else:
                checks["latency"] = {
                    "status": "ok",
                    "recent_s": round(r_ms / 1000, 1),
                    "baseline_s": round(b_ms / 1000, 1),
                    "threshold_s": round(lat_trip / 1000, 1),
                }
        else:
            checks["latency"] = {"status": "unknown", "reason": "no duration data in one window"}

        # --- 4. THROUGHPUT ------------------------------------------------
        # Own window (see throughput_recent_hours): diurnal volume swings make
        # a 6h-vs-7d rate comparison fire on quiet nights.
        thr_h = th["throughput_recent_hours"]
        thr_recent = dispatch_health(thr_h)
        r_rate = int(thr_recent.get("total") or 0) / thr_h if thr_h else 0.0
        b_rate = b_total / base_h if base_h else 0.0
        if b_rate > 0:
            thr_trip = b_rate * th["throughput_drop_ratio"]
            if r_rate <= thr_trip:
                checks["throughput"] = {
                    "status": "alert",
                    "recent_per_hour": round(r_rate, 1),
                    "baseline_per_hour": round(b_rate, 1),
                    "threshold_per_hour": round(thr_trip, 1),
                }
                alerts.append(
                    (
                        "Dispatch throughput drop",
                        f"{r_rate:.0f} dispatches/hour over the last {recent_h:.0f}h vs "
                        f"{b_rate:.0f}/hour baseline ({base_h/24:.0f}d) — "
                        f"threshold {thr_trip:.0f}/hour. The platform is doing "
                        f"{(1-r_rate/b_rate)*100:.0f}% less work than normal.",
                        "warning",
                        6.0,
                    )
                )
            else:
                checks["throughput"] = {
                    "status": "ok",
                    "recent_per_hour": round(r_rate, 1),
                    "baseline_per_hour": round(b_rate, 1),
                    "threshold_per_hour": round(thr_trip, 1),
                }
        else:
            checks["throughput"] = {"status": "unknown", "reason": "no baseline throughput"}

        result["checks"] = checks
        result["alerts_sent"] = _send(alerts)
        _record_run(result)
        return result

    except Exception as exc:  # pragma: no cover - must never break the job
        logger.error("dispatch_posture: check failed: %s", exc, exc_info=True)
        result["ok"] = False
        result["error"] = str(exc)
        # Heartbeat on the FAILURE path too. A monitor that crashes every run
        # would otherwise leave the same silence as one that never starts —
        # and "broken" needs to look different from "quiet".
        _record_run(result)
        return result


_LAST_RUN_KEY = _SETTING_PREFIX + "last_run"


def _record_run(result: Dict) -> None:
    """Make the observer OBSERVABLE (#5606).

    An alert-only monitor is silent when healthy, so "running and finding
    nothing wrong" looks EXACTLY like "not running at all" — which is #5596's
    own failure mode recursing onto the thing built to fix it. Hit for real on
    2026-08-15: after deploying this job its registration could only be
    inferred from the ABSENCE of an error, the weak evidence this whole file
    exists to stop relying on.

    Two traces, because they answer different questions:
      * one INFO line per run  -> "is it alive?" from the scheduler log
      * platform_settings stamp -> "when did it last run?" from SQL / the UI,
        without log access, and monitorable by the same freshness logic
        backup_posture_monitor applies to backups.

    DELIBERATELY ONE LINE PER RUN (~96/day), never per-check, and never above
    INFO when healthy. A noisy observer gets filtered, and a filtered observer
    is a blind spot with extra steps.

    Fail-safe: recording is best-effort. A monitor must not die because it
    could not write its own heartbeat.
    """
    checks = result.get("checks") or {}
    try:
        logger.info(
            "dispatch posture: %s | alerts=%s | %s",
            "OK" if result.get("ok") else "ERROR",
            result.get("alerts_sent", 0),
            " ".join(f"{name}={c.get('status')}" for name, c in checks.items()) or "no-checks",
        )
    except Exception:  # pragma: no cover - logging must never break the job
        pass

    try:
        import json

        from database import get_db_cursor
        from services.time_utils import now_utc

        payload = json.dumps(
            {
                "at": now_utc().isoformat(),
                "ok": bool(result.get("ok")),
                "alerts_sent": result.get("alerts_sent", 0),
                "statuses": {n: c.get("status") for n, c in checks.items()},
            }
        )
        with get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                INSERT INTO platform_settings (key, value, value_type, description, updated_at)
                VALUES (%s, %s, 'json', 'Last dispatch posture monitor run (#5606)', NOW())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, value_type = 'json', updated_at = NOW()
                """,
                (_LAST_RUN_KEY, payload),
            )
    except Exception:
        logger.warning("dispatch_posture: could not record last_run", exc_info=True)


def _send(alerts) -> int:
    """Emit alerts via B.A.S.E.

    Each alert carries a DISTINCT title: send_system dedups on (title,
    source), so a shared title would let one firing condition mute the
    others — the same trap documented for the per-tier backup alarm.
    """
    if not alerts:
        return 0
    sent = 0
    try:
        from services.telegram_service import send_system
    except Exception as exc:  # pragma: no cover
        logger.error("dispatch_posture: telegram unavailable, %d alert(s) undelivered: %s", len(alerts), exc)
        return 0
    for title, message, severity, cooldown in alerts:
        try:
            send_system(title=title, message=message, severity=severity, cooldown_hours=cooldown)
            sent += 1
        except Exception as exc:  # pragma: no cover
            logger.error("dispatch_posture: failed to send %r: %s", title, exc)
    return sent
