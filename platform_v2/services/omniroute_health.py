"""Alarm when the OmniRoute gateway stops producing inference.

WHY THIS EXISTS
---------------
OmniRoute is the gateway the codex / opencode / archie-tui coder lanes call
directly over HTTP. Measured 2026-09-14 it carried ~83% of all platform tokens.

Measured 2026-09-21 it had been returning **zero tokens on every call since
2026-09-18** — 1,667 calls over three days, every one an error — and nothing
alarmed. `omniroute_telemetry` was working perfectly and correctly skipping
them (a zero-token row is not inference), so the ledger went quiet and the
quiet looked like "nobody used the coder lanes". The distinction that matters:

    no calls at all      -> a lane nobody used. NOT a fault. Never page for it.
    calls, zero tokens   -> every request is failing. That is the fault.

This module only observes; it writes no rows and holds no lock. It reads the
same read-only sqlite mount `omniroute_telemetry` uses.

WHAT THE ALERT MUST SAY
-----------------------
It quotes the upstream refusal VERBATIM. An alert reading "gateway unhealthy"
starts an investigation; one reading

    [403]: OpenCode's free tier can only be used from within OpenCode

ends it — that is a provider closing external gateway access, not a
misconfiguration on this side, and no amount of retrying or re-pinning fixes
it. Three days of digging were avoidable.

ENTITLEMENT vs TRANSIENT
------------------------
Split deliberately, because the response differs completely:

  entitlement (401/402/403) -- credentials, plan or provider policy. Needs an
                               OWNER decision (add a key, change provider).
                               Retrying is pointless and rude.
  transient   (429/5xx)     -- rate limit or upstream wobble. Needs backoff,
                               and it may clear on its own.

Reporting one number for both is how "the gateway is erroring" gets triaged as
a transient blip for three days while the real cause is a closed free tier.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

OMNIROUTE_DB = os.getenv("ARCHIE_OMNIROUTE_DB", "/omniroute-data/storage.sqlite")

# A window long enough that a briefly-idle gateway is not mistaken for a broken
# one, short enough that three days never pass unnoticed again.
WINDOW_HOURS = float(os.getenv("ARCHIE_OMNIROUTE_WINDOW_HOURS", "6"))

# Below this, a run of failures is not yet evidence — a couple of 429s while a
# lane warms up is normal. Above it, a 0%-token window is a real outage.
MIN_CALLS = int(os.getenv("ARCHIE_OMNIROUTE_MIN_CALLS", "10"))

# Entitlement: the request was understood and REFUSED. Retrying cannot help.
_ENTITLEMENT_STATUSES = (401, 402, 403)

_REQUIRED_COLUMNS = {"timestamp", "status", "tokens_in", "tokens_out"}


def _classify(status: Optional[int]) -> str:
    # `int(status or 0)` would turn a MISSING status into 0 and classify it as
    # "other" -- quietly inventing a value for a row that never reported one.
    # This module's whole premise is that an unknown must read as unknown.
    if status is None or status == "":
        return "unknown"
    try:
        s = int(status)
    except (TypeError, ValueError):
        return "unknown"
    if s in _ENTITLEMENT_STATUSES:
        return "entitlement"
    if s == 429 or s >= 500:
        return "transient"
    if 200 <= s < 300:
        return "ok"
    return "other"


def summarize(
    rows: List[Dict[str, Any]],
    min_calls: int = MIN_CALLS,
    hours: float = WINDOW_HOURS,
) -> Dict[str, Any]:
    """Verdict for a window of call_logs rows. PURE — no I/O, no DB.

    ``rows`` need only ``status``, ``tokens_in``, ``tokens_out`` and optionally
    ``error_summary`` / ``requested_model``. ``hours`` is stated in the message
    and MUST be the window the rows actually came from -- an earlier version
    printed the module default regardless, so a 72h check reported "in the last
    6h". A status line that misstates its own window is the defect this module
    exists to catch, applied to itself.

    Conditions:
      ``None``            -- healthy, or too little evidence to judge
      ``no_inference``    -- calls happened and NOT ONE produced a token
      ``entitlement``     -- refusals dominate: credentials/plan/policy
      ``degraded``        -- producing tokens, but a high error share
    """
    total = len(rows)
    out: Dict[str, Any] = {
        "window_hours": hours,
        "window_calls": total,
        "with_tokens": 0,
        "entitlement": 0,
        "transient": 0,
        "condition": None,
        "detail": "",
        "top_error": None,
    }
    if not total:
        # A gateway nobody called is not a broken gateway. Deliberately not a
        # condition -- paging on silence trains people to ignore the channel.
        out["detail"] = "no calls in window"
        return out

    errors: Dict[str, int] = {}
    for r in rows:
        tin = int(r.get("tokens_in") or 0)
        tout = int(r.get("tokens_out") or 0)
        if tin + tout > 0:
            out["with_tokens"] += 1
        kind = _classify(r.get("status"))
        if kind in ("entitlement", "transient"):
            out[kind] += 1
        msg = (r.get("error_summary") or "").strip()
        if msg:
            errors[msg[:160]] = errors.get(msg[:160], 0) + 1

    if errors:
        top, n = max(errors.items(), key=lambda kv: kv[1])
        out["top_error"] = {"message": top, "count": n}

    if total < min_calls:
        out["detail"] = f"only {total} call(s) in window — not enough to judge"
        return out

    # Quote the upstream verbatim. See the module docstring: this is the whole
    # difference between an alert that ends the investigation and one that
    # starts it.
    quoted = ""
    if out["top_error"]:
        quoted = f' — top upstream error x{out["top_error"]["count"]}: {out["top_error"]["message"]}'

    if out["with_tokens"] == 0:
        ent = out["entitlement"]
        out["condition"] = "no_inference"
        out["detail"] = (
            f"{total} call(s) in the last {hours:g}h produced ZERO tokens — "
            f"every request is failing ({ent} refused on credentials/plan, "
            f"{out['transient']} rate-limited or upstream){quoted}"
        )
        return out

    err_share = (out["entitlement"] + out["transient"]) / total
    if out["entitlement"] >= max(min_calls, total * 0.5):
        out["condition"] = "entitlement"
        out["detail"] = (
            f"{out['entitlement']} of {total} call(s) REFUSED on credentials, plan or "
            f"provider policy — retrying cannot fix this{quoted}"
        )
    elif err_share >= 0.5:
        out["condition"] = "degraded"
        out["detail"] = f"{int(err_share * 100)}% of {total} call(s) errored but some tokens still " f"flowed{quoted}"
    else:
        out["detail"] = f"{out['with_tokens']}/{total} call(s) produced tokens"
    return out


def read_window(hours: float = WINDOW_HOURS, db_path: str = OMNIROUTE_DB) -> Optional[List[Dict[str, Any]]]:
    """call_logs rows from the last ``hours``, or None when unreadable.

    None means UNKNOWN — the mount is missing or the third-party schema moved —
    never an empty list, which would read as "no calls" and be reported as a
    healthy quiet gateway (ADR-017).
    """
    import datetime

    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    con = None
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cols = {r["name"] for r in cur.execute("PRAGMA table_info(call_logs)")}
        missing = _REQUIRED_COLUMNS - cols
        if missing:
            # Fail LOUD: a silent zero here would look exactly like a healthy
            # idle gateway, which is the failure this module exists to catch.
            logger.error("omniroute_health: call_logs schema changed — missing %s", sorted(missing))
            return None
        sel = ["timestamp", "status", "tokens_in", "tokens_out"]
        for opt in ("error_summary", "requested_model"):
            if opt in cols:
                sel.append(opt)
        cur.execute(
            f"SELECT {', '.join(sel)} FROM call_logs WHERE timestamp >= ? "  # noqa: S608 - names from PRAGMA
            "ORDER BY timestamp",
            (cutoff,),
        )
        return [dict(r) for r in cur.fetchall()]
    except (sqlite3.Error, OSError) as exc:
        logger.warning("omniroute_health: call_logs unreadable: %s", exc)
        return None
    finally:
        if con is not None:
            con.close()


def check_gateway_health(hours: float = WINDOW_HOURS) -> Dict[str, Any]:
    """Observe the gateway. Returns the summary; never raises, never writes."""
    rows = read_window(hours)
    if rows is None:
        return {
            "condition": "unreadable",
            "detail": "call_logs unreadable — gateway health is UNKNOWN, not healthy",
            "window_hours": hours,
            "window_calls": None,
        }
    return summarize(rows, hours=hours)
