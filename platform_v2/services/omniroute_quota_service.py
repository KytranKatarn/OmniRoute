"""Compute OmniRoute throttle-rate status per upstream provider.

Deep Space Nine phase 2 (quota awareness). Reads call_logs directly -- NOT
task_execution_log -- because omniroute_telemetry.py's collector deliberately
drops every row where tokens_in==0 and tokens_out==0 ("a refused call is not
inference"), and a quota-exhausted or rate-limited call is exactly that shape.
See docs/superpowers/specs/2026-09-19-omniroute-quota-awareness-design.md.

Writes one snapshot row per provider per scan to omniroute_quota_snapshots so
the dashboard card and alert logic have a real trend, not just a point-in-time
read. The table is seeded by scripts/omniroute/seed_quota_snapshots.sql.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

OMNIROUTE_DB = os.getenv("OMNIROUTE_DB_PATH", "/omniroute-data/storage.sqlite")
THROTTLE_ERROR_TYPES = ("quota_exhausted", "rate_limited")


def _is_keepalive_row(row) -> bool:
    """A recurring OmniRoute-internal keep-alive/model-refresh ping, not a real
    call of ours -- observed hourly on opencode-zen with this exact shape.
    Excluded by exact match, not by a blanket "0 tokens = refused" rule: a
    genuine throttle IS a 0-token row, so the exclusion must be narrow."""
    return (
        row["status"] == 200
        and (row["tokens_in"] or 0) == 0
        and (row["tokens_out"] or 0) == 0
        and row["error_type"] is None
        and row["requested_model"] is None
    )


def _get_setting_int(key: str, default: int) -> int:
    """Read an int tunable from platform_settings (no-deploy retunable)."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if row and row["value"] not in (None, ""):
            return int(row["value"])
    except Exception:
        logger.warning("omniroute_quota: bad/missing int setting %s, using default %s", key, default)
    return default


def _get_setting_float(key: str, default: float) -> float:
    """Read a float tunable from platform_settings (no-deploy retunable)."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
        if row and row["value"] not in (None, ""):
            return float(row["value"])
    except Exception:
        logger.warning("omniroute_quota: bad/missing float setting %s, using default %s", key, default)
    return default


def _status_for_rate(rate: Optional[float]) -> str:
    """rate is None (no calls in window) -> 'unknown': an idle provider isn't a
    healthy one, it's just unmeasured (spec §8)."""
    if rate is None:
        return "unknown"
    degraded_at = _get_setting_float("omniroute_quota:degraded_threshold", 0.30)
    exhausted_at = _get_setting_float("omniroute_quota:exhausted_threshold", 0.70)
    if rate >= exhausted_at:
        return "exhausted"
    if rate >= degraded_at:
        return "degraded"
    return "ok"


def scan_quota_status(window_hours: Optional[int] = None) -> Dict[str, Any]:
    """Read call_logs for the window, exclude keep-alive rows, group by
    provider, write one snapshot row per provider. Fail-open: any error
    leaves prior snapshots standing and writes nothing new (a counting bug
    must never manufacture a false alert)."""
    from database import get_db_cursor

    window_hours = window_hours if window_hours is not None else _get_setting_int(
        "omniroute_quota:window_hours", 24
    )

    if not os.path.exists(OMNIROUTE_DB):
        logger.warning("omniroute_quota: call_logs not found at %s", OMNIROUTE_DB)
        return {"ok": False, "error": "call_logs unreachable", "providers": []}

    try:
        conn = sqlite3.connect(f"file:{OMNIROUTE_DB}?mode=ro&immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        # Compute the cutoff in Python ISO form, not SQLite's space-separated
        # datetime('now') string: call_logs.timestamp stores ISO with 'T' and 'Z'
        # (e.g. '2026-09-22T17:30:51.404Z'), and a lexicographic comparison
        # against 'YYYY-MM-DD HH:MM:SS' would always rank any boundary-day row
        # above the cutoff, silently widening the window. Match telemetry's
        # watermark idiom: bind an ISO cutoff and compare in ISO space.
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
        cur = conn.execute(
            "SELECT provider, status, tokens_in, tokens_out, error_type, requested_model "
            "FROM call_logs WHERE timestamp >= ?",
            (cutoff,),
        )
        rows = cur.fetchall()
        conn.close()
    except sqlite3.OperationalError as e:
        # Schema drift (renamed/missing column) fails loud, writes nothing --
        # same precedent as omniroute_telemetry.py.
        logger.error("omniroute_quota: call_logs schema mismatch: %s", e)
        return {"ok": False, "error": str(e), "providers": []}
    except Exception as e:
        logger.error("omniroute_quota: scan failed: %s", e)
        return {"ok": False, "error": str(e), "providers": []}

    per_provider: Dict[str, Dict[str, int]] = {}
    for row in rows:
        if _is_keepalive_row(row):
            continue
        provider = row["provider"] or "unknown"
        bucket = per_provider.setdefault(provider, {"total": 0, "throttled": 0})
        bucket["total"] += 1
        if row["error_type"] in THROTTLE_ERROR_TYPES:
            bucket["throttled"] += 1

    results: List[Dict[str, Any]] = []
    with get_db_cursor(commit=True) as (conn, cur):
        for provider, counts in per_provider.items():
            rate = counts["throttled"] / counts["total"] if counts["total"] else None
            status = _status_for_rate(rate)
            cur.execute(
                """INSERT INTO omniroute_quota_snapshots
                   (provider, window_hours, total_calls, throttled_calls, rate, status)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (provider, window_hours, counts["total"], counts["throttled"], rate, status),
            )
            results.append(
                {
                    "provider": provider,
                    "window_hours": window_hours,
                    "total": counts["total"],
                    "throttled": counts["throttled"],
                    "rate": rate,
                    "status": status,
                }
            )

    return {"ok": True, "providers": results, "error": None}


def get_quota_status(provider: Optional[str] = None) -> Any:
    """Read the LATEST snapshot per provider. Returns a dict for one provider
    or a list of dicts for all known providers.

    This is the routing-hint interface for a future phase: shaped to mirror
    ai_bridge/external_providers.py's weekly_budget_status() so a future
    dispatch/combo-selection guard could consume it with no data-layer
    changes. Nothing calls it for that purpose in this phase."""
    from database import get_db_cursor

    if provider:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT provider, window_hours, total_calls, throttled_calls,
                          rate, status, created_at
                   FROM omniroute_quota_snapshots
                   WHERE provider = %s ORDER BY created_at DESC LIMIT 1""",
                (provider,),
            )
            row = cur.fetchone()
        if not row:
            return {
                "provider": provider,
                "window_hours": None,
                "total": 0,
                "throttled": 0,
                "rate": None,
                "status": "unknown",
                "last_scan_at": None,
            }
        return _row_to_status(row)

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT DISTINCT ON (provider) provider, window_hours, total_calls,
                      throttled_calls, rate, status, created_at
               FROM omniroute_quota_snapshots
               ORDER BY provider, created_at DESC"""
        )
        rows = cur.fetchall()
    return [_row_to_status(r) for r in rows]


def _row_to_status(row) -> Dict[str, Any]:
    created_at = row["created_at"]
    return {
        "provider": row["provider"],
        "window_hours": row["window_hours"],
        "total": row["total_calls"],
        "throttled": row["throttled_calls"],
        "rate": float(row["rate"]) if row["rate"] is not None else None,
        "status": row["status"],
        "last_scan_at": created_at.isoformat() if created_at else None,
    }


def _all_providers_with_snapshots() -> List[str]:
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute("SELECT DISTINCT provider FROM omniroute_quota_snapshots")
        return [r["provider"] for r in cur.fetchall()]


def _recent_snapshots(provider: str, limit: int) -> List[Dict[str, Any]]:
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT status, rate FROM omniroute_quota_snapshots
               WHERE provider = %s ORDER BY created_at DESC LIMIT %s""",
            (provider, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def _snapshot_before(provider: str, offset: int) -> Optional[Dict[str, Any]]:
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT status FROM omniroute_quota_snapshots
               WHERE provider = %s ORDER BY created_at DESC LIMIT 1 OFFSET %s""",
            (provider, offset),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def check_and_alert() -> None:
    """Compare each provider's most recent K snapshots to what came before;
    alert on a CONFIRMED (K consecutive) transition into 'exhausted', and once
    on recovery out of it. Uses the platform's own telegram_service, not a
    separate path -- this is a hub-local computation (spec §6). One alert per
    transition, never spammed every cycle."""
    from services.telegram_service import send_system

    confirm_k = _get_setting_int("omniroute_quota:confirm_k", 2)

    for provider in _all_providers_with_snapshots():
        recent = _recent_snapshots(provider, confirm_k)
        if len(recent) < confirm_k:
            continue  # not enough history yet to confirm anything

        prior = _snapshot_before(provider, confirm_k)
        was_exhausted_before = bool(prior and prior["status"] == "exhausted")
        all_exhausted_now = all(r["status"] == "exhausted" for r in recent)

        if all_exhausted_now and not was_exhausted_before:
            rate = recent[0]["rate"]
            send_system(
                title=f"⚠️ OmniRoute quota: {provider} exhausted",
                message=(
                    f"{provider} has been throttled "
                    f"({rate:.0%} of calls) for {confirm_k} consecutive scans."
                ),
            )
        elif was_exhausted_before and not all_exhausted_now and recent[0]["status"] != "exhausted":
            send_system(
                title=f"✅ OmniRoute quota: {provider} recovered",
                message=f"{provider} is no longer throttled (current: {recent[0]['status']}).",
            )


# ============================================================================
# PHASE 3 — ROUTING-HINT CONSUMPTION
# These helpers turn the phase-2 observability into a routing hint the
# platform's own OmniRoute gateway call readers consult BEFORE sending:
#   * upstream_for_model(model)          — which upstream will serve this model
#   * gate_upstream(upstream, threshold) — should a call to this upstream go out
#   * prefer_least_throttled_upstream()  — rotation picker over snapshot data
# The plan (docs/superpowers/plans/2026-09-19-omniroute-quota-awareness.md §12)
# deferred consuming get_quota_status() to this phase: "have combo-selection or
# a dispatch guard actually act on the quota hint". Consumption is additive and
# fail-open — a quota error must never block a call that would otherwise work.
# ============================================================================

# Model-prefix → upstream mapping, observed live from call_logs.requested_model
# (2026-09-22): auto/* is served by the auto upstream, opencode/* by opencode,
# felo-web/* by felo-web. Keep this in sync if OmniRoute adds a front.
_UPSTREAM_FOR_MODEL_PREFIX = (
    ("oc/", "opencode"),      # the omniroute provider row's default (oc/big-pickle)
    ("opencode/", "opencode"),
    ("auto/", "auto"),
    ("felo-web/", "felo-web"),
)


def upstream_for_model(model: Optional[str]) -> Optional[str]:
    """Which OmniRoute upstream serves the given requested model. Prefix match
    against observed call_logs.requested_model values. None when unknown."""
    if not model:
        return None
    m = str(model).strip()
    for prefix, upstream in _UPSTREAM_FOR_MODEL_PREFIX:
        if m.startswith(prefix):
            return upstream
    return None


def gate_upstream(upstream: str, thresholds: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Phase 3 routing gate: should a call routed to ``upstream`` go out?

    Returns ``{"allow": bool, "status": str, "rate": float|None, "reason": str}``.
      * no snapshot yet           → allow (fail-open: unmeasured, not blocked)
      * status ok                 → allow
      * status degraded           → allow, but reason says so (warn, don't block)
      * status exhausted          → allow=False  (caller should fall back)
    Thresholds may be overridden (used by tests to force a band cheaply).
    """
    thresholds = thresholds or {
        "degraded": _get_setting_float("omniroute_quota:degraded_threshold", 0.30),
        "exhausted": _get_setting_float("omniroute_quota:exhausted_threshold", 0.70),
    }
    try:
        st = get_quota_status(upstream)
    except Exception as e:  # noqa: BLE001 — fail-open
        logger.warning("omniroute_quota: gate_upstream(%s) failed open: %s", upstream, e)
        return {"allow": True, "status": "unknown", "rate": None, "reason": "quota unavailable, fail-open"}

    status = (st or {}).get("status") or "unknown"
    rate = (st or {}).get("rate")
    if status == "exhausted":
        return {
            "allow": False,
            "status": status,
            "rate": rate,
            "reason": f"upstream {upstream} exhausted (throttle rate {rate:.0%})",
        }
    if status == "degraded":
        return {
            "allow": True,
            "status": status,
            "rate": rate,
            "reason": f"upstream {upstream} degraded (throttle rate {rate:.0%}) — warn, not block",
        }
    return {"allow": True, "status": status or "unknown", "rate": rate, "reason": "ok"}


def prefer_least_throttled_upstream(
    candidates: Optional[List[str]] = None,
    prefer: Optional[str] = None,
    thresholds: Optional[Dict[str, float]] = None,
) -> Optional[str]:
    """Rotation picker over snapshot data (plan §12): among ``candidates`` still
    allowing calls, return the one with the LOWEST throttle rate (most headroom).
    ``prefer`` sticks when it is still allowed. Returns None when every candidate
    is exhausted — the caller falls back to local, mirroring
    pick_free_text_provider()'s contract. Fail-open → prefer (or first) when no
    snapshot reads."""
    cands = candidates or ["opencode", "auto", "felo-web"]
    scored: List[tuple] = []
    for u in cands:
        try:
            gate = gate_upstream(u, thresholds=thresholds)
            if not gate["allow"]:
                continue
            rate = gate.get("rate")
            scored.append((rate if rate is not None else 0.0, u, gate["status"]))
        except Exception as e:  # noqa: BLE001
            logger.warning("omniroute_quota: prefer pick for %s: %s", u, e)
            scored.append((0.0, u, "unknown"))  # fail-open: unmeasured sorts first
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[2] != "ok"))
    if prefer and prefer in cands:
        for _rate, u, _st in scored:
            if u == prefer:
                return prefer
    return scored[0][1]