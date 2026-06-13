"""HUB→STANDALONE welfare event emitter (project #379 Phase 3, roadmap item D).

The keystone that lands the live AI-workforce welfare grade on the PUBLIC
C.R.E.E.D. surface. Phase 2 shipped a DISTINCT welfare scorer on the standalone
(``kytran_creed/services/welfare_engine.py``) that scores ``category='welfare'``
governance events over a 30-day rolling window. Nothing emitted those events in
production — ``_emit_violations`` only ran inside the 06:00 daily job, which
samples the daily LOW of the 24h-rolling token window, so ~0 welfare events ever
reached the public store (audit 2026-06-13).

This module fixes that. Per agent snapshot (from
``welfare_governance_service.gather_snapshots``) it emits ONE
``category='welfare'`` event per welfare DIMENSION (hours/tokens/actions/stress)
with the event_type + ``metadata.dimension`` + severity the standalone
``welfare_engine`` expects, plus break-honor events — routed per-tenant via
``creed_emit`` (WTF agents → what-the-fact, everyone else → kytran-empowerment).

Two halves, deliberately split so the math is unit-testable without a DB:

* ``build_welfare_events(...)`` — PURE. snapshots → list of welfare event
  payloads (category/event_type/metadata.dimension/severity). No DB, no I/O.
* ``emit_welfare_events(cur, ...)`` — de-dupe against
  ``agent_welfare_emit_state`` (emit only on STATE CHANGE per agent/dimension,
  or once per heartbeat window) and push via ``creed_emit.emit_event``. Emit
  failures are LOUD (governance_audit_log + system_notification), never
  debug-swallowed (audit FIX-3).

ALIGNMENT WITH welfare_engine's SCORING CONTRACT (kytran_creed):
  - severity ladder is IDENTICAL: info=0, warning=1, violation=3, critical=5
    (``welfare_engine.SEVERITY_WEIGHTS``). A healthy dimension emits ``info``
    (weight 0 → contributes a perfect 100 to that dimension's violation rate);
    an over-budget/over-limit dimension emits warning/violation/critical so the
    standalone computes a real per-dimension violation rate.
  - event_type is exactly ``welfare_hours|welfare_tokens|welfare_actions|
    welfare_stress`` and ``metadata.dimension`` is the bare dimension, so
    ``welfare_engine._resolve_dimension`` attributes each event to the right
    by_dimension bucket (metadata.dimension wins, event_type prefix is fallback).
  - break-honor uses ``welfare_break_honored`` / ``welfare_break_violated``
    (``welfare_engine._BREAK_HONORED_TYPES`` / ``_BREAK_VIOLATED_TYPES``) so the
    standalone's ``break_honor_rate`` reflects reality.
  - category is ``'welfare'`` — NOT ``'accountability'`` — so welfare lands on
    the public welfare grade and is EXCLUDED from the ethics pillars
    (``scoring_engine.CATEGORIES`` has no 'welfare').
"""

import json
import logging

from services.welfare_governance import classify_agent, _num

logger = logging.getLogger(__name__)

# C.R.E.E.D. category for AI-workforce welfare — its OWN public pillar. This is
# the Phase-3 CATEGORY SWITCH: welfare no longer rides the 'accountability'
# ethics pillar (which double-counted it into the ethics grade); it is now a
# distinct metric scored by the standalone welfare_engine from these events.
WELFARE_CATEGORY = "welfare"
_CREED_MODULE = "Welfare"

# The four welfare dimensions (mirrors welfare_engine.DIMENSIONS). Each maps to a
# welfare_<dim> event_type the standalone resolver understands.
DIMENSIONS = ["hours", "tokens", "actions", "stress"]

# Break-honor pseudo-dimensions tracked in the de-dupe state table (NOT real
# welfare dimensions; they feed break_honor_rate on the standalone).
BREAK_DIMENSIONS = ["break_honored", "break_violated"]

# How long a steadily-over agent/dimension may go without re-emitting before the
# emitter fires a heartbeat anyway (so the 30-day rolling welfare score keeps a
# fresh signal for a sustained problem, without per-cycle flooding). Tunable.
DEFAULT_HEARTBEAT_HOURS = 6.0


def _dimension_severity(snap, dim, klass, break_cfg):
    """Severity for ONE welfare dimension of ONE agent — aligned to
    welfare_engine.SEVERITY_WEIGHTS (info<warning<violation<critical).

    PURE. healthy (not over this dim) → 'info' (weight 0 → perfect dimension
    score). Over the limit → graded by how far over, and whether a rest was
    honored:

      tokens : the dispatch THROTTLE manages token overage automatically
               (#4123 — "throttle, don't rest"), so being over budget is a real
               but MANAGED pressure → 'warning' up to 2x, 'violation' beyond 2x.
      hours/actions/stress : a REST-requiring dimension. Over the limit with a
               break taken today → 'warning' (honored — pressure was managed).
               Over the limit and NOT rested → 'violation', escalating to
               'critical' for hours (an unrested over-hours agent is the worst
               welfare state — matches score_welfare's over_hours_cap violation).
    """
    if dim not in (klass.get("over") or []):
        return "info"

    rested = _num(snap.get("rested_today")) >= 1
    if dim == "tokens":
        ratio = _num(snap.get("token_ratio"))
        return "violation" if ratio >= 2.0 else "warning"

    # hours / actions / stress — rest-requiring dimensions
    if rested:
        return "warning"
    if dim == "hours":
        return "critical"
    return "violation"


def build_welfare_events(snapshots, break_cfg=None, heartbeat_hours=DEFAULT_HEARTBEAT_HOURS):
    """PURE. snapshots → list of welfare event payloads (pre-dedupe).

    One event per agent × dimension (4 dims) carrying the standalone contract:
    ``category='welfare'``, ``event_type='welfare_<dim>'``,
    ``metadata.dimension='<dim>'``, severity from ``_dimension_severity``. Plus a
    break-honor event per over-limit agent (``welfare_break_honored`` when a
    rest-requiring overage was rested today, ``welfare_break_violated`` when it
    was not). Each payload also carries a ``dedupe_dimension`` (the key the
    state table de-dupes on) and a human ``description``.

    Returns ``[{agent_id, agent_name, dedupe_dimension, event_type, category,
    severity, metadata, description}, ...]``.
    """
    events = []
    for snap in snapshots or []:
        aid = snap.get("agent_id")
        name = snap.get("name")
        klass = classify_agent(snap, break_cfg)
        over = klass.get("over") or []

        for dim in DIMENSIONS:
            sev = _dimension_severity(snap, dim, klass, break_cfg)
            ratio_key = {"tokens": "token_ratio", "actions": "action_ratio"}.get(dim)
            detail = ""
            if dim == "tokens" and snap.get("token_ratio") is not None:
                detail = f" ({_num(snap.get('token_ratio')):.2f}x budget)"
            elif dim == "actions" and snap.get("action_ratio") is not None:
                detail = f" ({_num(snap.get('action_ratio')):.0%} of queue)"
            elif dim == "hours" and snap.get("hours") is not None:
                detail = f" ({_num(snap.get('hours')):.1f}h)"
            elif dim == "stress" and snap.get("stress") is not None:
                detail = f" (stress {_num(snap.get('stress')):.2f})"
            state = "within bounds" if sev == "info" else "over limit"
            events.append(
                {
                    "agent_id": aid,
                    "agent_name": name,
                    "dedupe_dimension": dim,
                    "event_type": f"welfare_{dim}",
                    "category": WELFARE_CATEGORY,
                    "severity": sev,
                    "metadata": {"dimension": dim},
                    "description": f"Welfare/{dim}: {name} {state}{detail}",
                }
            )

        # Break-honor signal — only meaningful when the agent is over a
        # REST-requiring dimension (hours/actions/stress). Token overage is
        # throttle-managed (#4123) and does not require a break, so it never
        # produces a break_violated event.
        rest_over = [d for d in over if d != "tokens"]
        if rest_over:
            rested = _num(snap.get("rested_today")) >= 1
            if rested:
                events.append(
                    {
                        "agent_id": aid,
                        "agent_name": name,
                        "dedupe_dimension": "break_honored",
                        "event_type": "welfare_break_honored",
                        "category": WELFARE_CATEGORY,
                        "severity": "info",
                        "metadata": {"dimension": "actions", "rest_dimensions": rest_over},
                        "description": f"Welfare/break: {name} rested while over {', '.join(rest_over)}",
                    }
                )
            else:
                events.append(
                    {
                        "agent_id": aid,
                        "agent_name": name,
                        "dedupe_dimension": "break_violated",
                        "event_type": "welfare_break_violated",
                        "category": WELFARE_CATEGORY,
                        "severity": "violation",
                        "metadata": {"dimension": "actions", "rest_dimensions": rest_over},
                        "description": f"Welfare/break: {name} over {', '.join(rest_over)} with no rest today",
                    }
                )
    return events


def decide_emissions(candidates, prior_state, now, heartbeat_hours=DEFAULT_HEARTBEAT_HOURS):
    """PURE de-dupe. Decide which candidate events to actually emit.

    ``candidates``  : output of ``build_welfare_events``.
    ``prior_state`` : ``{(agent_id, dedupe_dimension): {"last_severity": str,
                       "last_emit_at": datetime|None}}`` — the persisted markers.
    ``now``         : timezone-aware current time (caller supplies; pure here).
    ``heartbeat_hours`` : re-emit an UNCHANGED state after this many hours so a
                       sustained problem keeps a fresh public signal.

    Emit when EITHER:
      * the severity changed since last emit for this (agent, dimension), OR
      * the last emit aged past the heartbeat window (or there is no prior emit).

    A still-healthy ``info`` dimension that has ALREADY emitted ``info`` and is
    inside the heartbeat window is skipped — that is what stops 54×4 from
    becoming thousands of identical events/day.

    Returns ``(to_emit, to_skip)`` — two lists of candidate dicts (each emit dict
    annotated with ``_reason``: 'changed' | 'heartbeat' | 'first').
    """
    to_emit, to_skip = [], []
    for ev in candidates:
        key = (ev.get("agent_id"), ev.get("dedupe_dimension"))
        prior = prior_state.get(key)
        if prior is None:
            ev = {**ev, "_reason": "first"}
            to_emit.append(ev)
            continue
        changed = prior.get("last_severity") != ev.get("severity")
        last_at = prior.get("last_emit_at")
        aged = True
        if last_at is not None:
            try:
                aged = (now - last_at).total_seconds() >= heartbeat_hours * 3600.0
            except TypeError:
                aged = True  # naive/aware mismatch → treat as aged (safe)
        if changed:
            to_emit.append({**ev, "_reason": "changed"})
        elif aged:
            to_emit.append({**ev, "_reason": "heartbeat"})
        else:
            to_skip.append(ev)
    return to_emit, to_skip


def _load_emit_state(cur):
    """Read the persisted per-(agent,dimension) emit markers → dict keyed
    ``(agent_id, dimension)``."""
    cur.execute(
        "SELECT agent_id, dimension, last_severity, last_emit_at "
        "FROM agent_welfare_emit_state"
    )
    state = {}
    for r in cur.fetchall() or []:
        state[(r["agent_id"], r["dimension"])] = {
            "last_severity": r["last_severity"],
            "last_emit_at": r["last_emit_at"],
        }
    return state


def _persist_emit_state(cur, agent_id, dimension, severity, event_type):
    """Upsert the emit marker for one (agent, dimension)."""
    cur.execute(
        """
        INSERT INTO agent_welfare_emit_state
            (agent_id, dimension, last_severity, last_event_type, last_emit_at, updated_at)
        VALUES (%s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (agent_id, dimension) DO UPDATE
           SET last_severity = EXCLUDED.last_severity,
               last_event_type = EXCLUDED.last_event_type,
               last_emit_at = NOW(),
               updated_at = NOW()
        """,
        (agent_id, dimension, severity, event_type),
    )


def _record_emit_failure(cur, ev, reason):
    """FIX-3: make an emit failure LOUD — write a governance_audit_log row AND a
    system_notification, instead of debug-swallowing. Never raises."""
    desc = f"C.R.E.E.D. welfare emit failed for {ev.get('agent_name')} ({ev.get('dedupe_dimension')}): {reason}"
    try:
        cur.execute(
            """
            INSERT INTO governance_audit_log
                (event_type, event_category, agent_id, action, reason, outcome, new_value)
            VALUES (%s, 'welfare', %s, 'emit', %s, 'failure', %s)
            """,
            (
                "welfare_emit_failed",
                ev.get("agent_id"),
                desc,
                json.dumps({"event_type": ev.get("event_type"), "severity": ev.get("severity")}),
            ),
        )
    except Exception:
        logger.warning("welfare_emit: governance_audit_log write failed", exc_info=True)
    try:
        cur.execute(
            """
            INSERT INTO system_notifications (title, message, type, source, is_read)
            VALUES (%s, %s, 'warning', 'welfare_emit', FALSE)
            """,
            ("C.R.E.E.D. welfare emit failed", desc),
        )
    except Exception:
        logger.warning("welfare_emit: system_notification write failed", exc_info=True)


def emit_welfare_events(cur, snapshots, break_cfg=None, heartbeat_hours=DEFAULT_HEARTBEAT_HOURS):
    """Build → de-dupe → emit welfare events for the active workforce.

    Returns a summary dict ``{built, emitted, skipped, failed}``. Designed for the
    intraday job (kin_workload_monitor cadence / a dedicated hourly job). Each
    successful emit advances the de-dupe marker; each failure is recorded loudly
    (FIX-3) and does NOT advance the marker (so it retries next cycle).
    """
    from datetime import datetime, timezone

    try:
        from services.creed_emit import emit_event
    except Exception:
        logger.warning("welfare_emit: creed_emit unavailable, skipping", exc_info=True)
        return {"built": 0, "emitted": 0, "skipped": 0, "failed": 0}

    now = datetime.now(timezone.utc)
    candidates = build_welfare_events(snapshots, break_cfg, heartbeat_hours)
    prior = _load_emit_state(cur)
    to_emit, to_skip = decide_emissions(candidates, prior, now, heartbeat_hours)

    emitted = failed = 0
    for ev in to_emit:
        ok = False
        try:
            ok = emit_event(
                category=ev["category"],
                severity=ev["severity"],
                description=ev["description"],
                event_type=ev["event_type"],
                agent_id=ev.get("agent_id"),
                agent_name=ev.get("agent_name"),
                module=_CREED_MODULE,
                metadata=ev.get("metadata"),
            )
        except Exception as exc:  # emit_event already swallows, but be defensive
            _record_emit_failure(cur, ev, str(exc))
            failed += 1
            continue
        if ok:
            _persist_emit_state(
                cur, ev.get("agent_id"), ev.get("dedupe_dimension"),
                ev.get("severity"), ev.get("event_type"),
            )
            emitted += 1
        else:
            _record_emit_failure(cur, ev, "emit_event returned False (push rejected / no key)")
            failed += 1

    logger.info(
        "welfare_emit: built=%d emitted=%d skipped=%d failed=%d",
        len(candidates), emitted, len(to_skip), failed,
    )
    return {"built": len(candidates), "emitted": emitted, "skipped": len(to_skip), "failed": failed}
