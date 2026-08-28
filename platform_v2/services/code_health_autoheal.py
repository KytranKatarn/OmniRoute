"""Autonomous Code Health heal cycle (scanner-tier autonomy, 2026-07-11 spec).

Chains: deep static scan (faithful-runtime analyzer -> auto-verify gate ->
Repair Bay proposals) -> DHQ fix dispatch (audit_pipeline.dispatch_audit_proposals
-> get_dispatcher().request_work — F.O.R.G.E./V.I.G.I.L. selected via
CAPABILITY_DEPARTMENT_MAP, welfare-gated like all fleet work) -> static
reverify (deployed static proposals vs the fresh scan's fingerprints) ->
optionally a handoff to the archie_engine build loop for tested PRs.

DELIBERATELY ABSENT: deploy/merge. The human gate is unchanged — autonomy stops
at fix generation (ready_for_review) and, with engine_build=True, a tested PR
awaiting human merge (the engine build loop refuses protected branches and
never merges). A test guards this file against ever growing a deploy path.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ── Seams (lazy imports; stubbed in unit tests) ───────────────────────────────


def _deep_scan(target):
    from tools.consciousness.code_health_routes import _deep_scan_worker

    return _deep_scan_worker(target)


def _dispatch_fixes(limit):
    from services.audit_pipeline import dispatch_audit_proposals

    return dispatch_audit_proposals(limit=limit)


def _load_deployed_static():
    """Deployed/implemented static-tier proposals awaiting reverify."""
    import json

    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, metadata FROM improvement_proposals
               WHERE metadata->>'source' = 'code_health_audit'
                 AND metadata->>'scan_tier' = 'static'
                 AND status IN ('deployed', 'implemented')
                 AND COALESCE(metadata->>'reverified', '') = ''"""
        )
        rows = cur.fetchall()
    out = []
    for row in rows:
        md = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
        out.append({"id": row["id"], "metadata": md})
    return out


def _stamp_reverified(proposal_id, verdict):
    from services.audit_pipeline import _set_reverified

    _set_reverified(proposal_id, verdict)


def _reverify_static(fingerprints):
    """Static counterpart of audit_pipeline.reverify_deployed_findings (which
    deliberately excludes scan_tier='static'). A deployed static proposal whose
    (file_path, issue_code) fingerprint is ABSENT from the fresh deep scan is
    'fixed'; still present -> 'still_open' (a surfaced regression)."""
    from services.audit_pipeline import _audit_file_path

    current = {(_audit_file_path(module, rel_file), code) for module, rel_file, code in fingerprints}
    fixed = still_open = 0
    for row in _load_deployed_static():
        md = row["metadata"]
        verdict = "still_open" if (md.get("file_path"), md.get("issue_code")) in current else "fixed"
        if verdict == "fixed":
            fixed += 1
        else:
            still_open += 1
        _stamp_reverified(row["id"], verdict)
    if fixed or still_open:
        logger.info("static reverify: %d fixed, %d still-open", fixed, still_open)
    return {"fixed": fixed, "still_open": still_open}


def _load_unapproved_reds():
    """Red proposals still awaiting owner permission with NO live pending card —
    created before the red gate existed, or their 24h card expired.

    Covers BOTH red producers: deep-scan statics (scan_tier='static') AND the
    audit pipeline (source='code_health_audit'), which stamps no scan_tier at
    all. Matching only the static stamp left 11 audit reds pending 5-16 days
    with no card — invisible in the Approvals tab by construction (2026-08-28).
    Unknown third-party producers stay out of scope on purpose."""
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT p.id, p.title FROM improvement_proposals p
               WHERE (p.metadata->>'scan_tier' = 'static'
                      OR p.metadata->>'source' = 'code_health_audit')
                 AND p.metadata->>'severity_tier' = 'red'
                 AND p.status = 'pending'
                 AND NOT EXISTS (
                     SELECT 1 FROM autonomy_approval_queue q
                     WHERE q.action_type = 'improvement_approve_red'
                       AND q.status = 'pending'
                       AND q.action_data->>'proposal_id' = p.id::text)"""
        )
        return [dict(row) for row in cur.fetchall()]


def _request_red_approval(proposal):
    """Card the owner (Telegram approve/deny) for one red proposal."""
    import sys

    sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
    from agent_loop import request_approval

    request_approval(
        action_type="improvement_approve_red",
        action_data={"proposal_id": proposal["id"], "title": proposal.get("title", "")},
        reason=f"RED Code Health finding awaits owner permission: {(proposal.get('title') or '')[:120]}",
        requested_by="code_health_autoheal",
        priority=3,
        tier=2,
    )


def _recard_unapproved_reds():
    """Safety net: re-card red proposals whose Telegram card expired or never
    existed, so a missed 24h window can never orphan a red fix. Idempotent —
    _check_existing_approval dedups per proposal."""
    recarded = 0
    for proposal in _load_unapproved_reds():
        try:
            _request_red_approval(proposal)
            recarded += 1
        except Exception:
            logger.warning("autoheal: red re-card failed for proposal %s", proposal.get("id"), exc_info=True)
    if recarded:
        logger.info("autoheal: re-carded %d red proposals for owner permission", recarded)
    return recarded


def _trigger_engine_build():
    """Ask the archie_engine (Building Machine) to pull Repair Bay work and run
    its coordinate->build->test->PR loop. Mirrors the proven WS frame used by
    agent_loop._engine_autopull_cycle. The engine NEVER merges; PR creation
    fails closed without ARCHIE_GITHUB_TOKEN."""
    import asyncio
    import json

    async def _ask():
        import websockets

        async with websockets.connect("ws://archie_engine:9090", open_timeout=15, close_timeout=5) as ws:
            await ws.send(json.dumps({"type": "pull_repair_work"}))
            # Wide window: a full engine build (plan retries + apply/test/push)
            # is validated at up to ~15 min — same rationale as the 6h autopull.
            raw = await asyncio.wait_for(ws.recv(), timeout=900)
            return json.loads(raw) if raw else {}

    result = asyncio.run(_ask())
    logger.info("autoheal: engine build handoff result: %s", result)
    return result


# ── The cycle ─────────────────────────────────────────────────────────────────


def run_autoheal_cycle(target="platform", max_fixes=10, engine_build=False):
    """One autonomous heal cycle. Every fix routes through the DHQ dispatcher;
    deploy stays human-gated. Returns the summary dict used by the scheduled
    job's telemetry."""
    scan = _deep_scan(target)

    # Re-card any red proposal whose owner-permission card expired (fix work on
    # reds is HELD until the owner approves; yellows flow advise-only).
    reds_recarded = 0
    try:
        reds_recarded = _recard_unapproved_reds()
    except Exception:
        logger.warning("autoheal: red re-card step failed", exc_info=True)

    fix_dispatch = {"dispatched": 0, "failed": 0, "skipped": 0}
    if scan.get("proposals_created", 0) > 0:
        try:
            fix_dispatch = _dispatch_fixes(max_fixes) or fix_dispatch
        except Exception:
            logger.warning("autoheal: fix dispatch failed", exc_info=True)

    if engine_build:
        try:
            _trigger_engine_build()
        except Exception as exc:  # non-fatal: diffs were already generated via DHQ
            logger.warning("autoheal: engine build handoff failed (non-fatal): %s", exc)

    try:
        static_reverify = _reverify_static(scan.get("fingerprints") or [])
    except Exception:
        logger.warning("autoheal: static reverify failed", exc_info=True)
        static_reverify = {"fixed": 0, "still_open": 0}

    summary = {
        "scanned": target,
        "confirmed": scan.get("confirmed", 0),
        "advisory": scan.get("advisory", 0),
        "proposals_created": scan.get("proposals_created", 0),
        "skipped_duplicates": scan.get("skipped_duplicates", 0),
        "reds_recarded": reds_recarded,
        "fix_dispatch": fix_dispatch,
        "static_reverify": static_reverify,
        "coverage": scan.get("coverage", {}),
    }
    logger.info("autoheal cycle complete: %s", summary)
    return summary
