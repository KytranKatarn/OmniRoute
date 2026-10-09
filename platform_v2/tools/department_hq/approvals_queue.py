"""Unified pending approval data for the web tab and internal cockpit."""

import logging
from .approvals_helpers import _code_fix_label, _code_fix_reason, _build_escalation_chain

logger = logging.getLogger(__name__)


def list_pending_approvals():
    """Unified pending Tier-2 approvals (autonomy + contractor + bridge + hire)
    as a plain list of dicts — no Flask/session. Shared by the @admin_required
    /api/approvals/pending route AND the @_require_internal_key cockpit endpoint.
    Row shaping (incl. the PR #2205 code-fix labels + escalation chain) is
    identical to what the DHQ Approvals tab renders."""
    from database import get_db_cursor

    approvals: list = []

    with get_db_cursor() as (conn, cur):
        # Prefetch Code-Health proposal metadata for rich code-fix labels
        # (one query, keyed by proposal_id) so every improvement_approve*
        # card shows real module/issue/file instead of the raw action_type.
        _prop_meta = {}
        try:
            cur.execute(
                """SELECT id, metadata FROM improvement_proposals
                   WHERE id IN (
                       SELECT (action_data->>'proposal_id')::int
                       FROM autonomy_approval_queue
                       WHERE status = 'pending' AND tier >= 2
                         AND action_type IN ('improvement_approve', 'improvement_approve_red')
                         AND action_data->>'proposal_id' ~ '^[0-9]+$')"""
            )
            import json as _json

            for _pr in cur.fetchall():
                _pr = dict(_pr)
                _md = _pr["metadata"] if isinstance(_pr["metadata"], dict) else _json.loads(_pr["metadata"] or "{}")
                _prop_meta[_pr["id"]] = _md
        except Exception:
            logger.warning("approvals: code-fix metadata prefetch failed", exc_info=True)

        # 1. autonomy_approval_queue — Tier-2 agent loop
        cur.execute(
            """SELECT id, action_type, action_data, tier, priority,
                      requested_by, reason, created_at, expires_at
               FROM autonomy_approval_queue
               WHERE status = 'pending' AND tier >= 2
               ORDER BY priority ASC, created_at ASC"""
        )
        for r in cur.fetchall():
            r = dict(r)
            at = r.get("action_type", "")
            if at.startswith("compliance_fix_"):
                category, display = "compliance_fix", "Compliance Fix"
            elif at == "cloud_throughput_escalation":
                category, display = "cloud_escalation", "Cloud Model Escalation"
            elif at == "create_agent":
                category, display = "agent_creation", "Create New Agent"
            elif at == "linkedin_post":
                _ad = r.get("action_data") or {}
                _pt = _ad.get("post_type", "personal") if isinstance(_ad, dict) else "personal"
                _acct_label = {"company": "KE Inc.", "creed": "Creed-AI", "personal": "Kytran"}.get(_pt, _pt.title())
                category, display = "linkedin_post", f"LinkedIn Post — {_acct_label}"
            elif at == "linkedin_like":
                _ad = r.get("action_data") or {}
                _rx = _ad.get("reaction", "like") if isinstance(_ad, dict) else "like"
                category, display = "linkedin_like", f"LinkedIn {str(_rx).title()}"
            elif at == "linkedin_comment":
                category, display = "linkedin_comment", "LinkedIn Comment"
            elif at == "pr_merge":
                # Tier-3 / sensitive-path PR awaiting Kytran's merge (#5283).
                # Without this it rendered as category 'other' with the raw
                # action_type as its label — present in the tab, but not
                # recognisable as the merge decision it is.
                _ad = r.get("action_data") or {}
                _pr = _ad.get("pr_number") if isinstance(_ad, dict) else None
                _ptitle = (_ad.get("title") or "") if isinstance(_ad, dict) else ""
                category, display = "pr_merge", f"🔀 Merge PR #{_pr} — {_ptitle[:60]}"
            elif at == "contractor_dispatch":
                category, display = "contractor_dispatch", "Contractor Dispatch"
            elif at == "host_root_command":
                # Host-root action awaiting the owner's signature. The label
                # carries the literal argv, because "Host Root Command" alone
                # would ask the owner to approve something they cannot see.
                _ad = r.get("action_data") or {}
                _argv = _ad.get("argv_preview") if isinstance(_ad, dict) else None
                _argv_s = " ".join(_argv) if isinstance(_argv, list) else str(_argv or "?")
                category, display = "host_root_command", f"🛡️ HOST ROOT — {_argv_s[:140]}"
            elif at == "restart_container":
                category, display = "restart_container", "Container Restart"
            elif at == "welfare_rest_8h":
                # K.I.N. welfare approval — agent overwork >12h
                _ad = r.get("action_data") or {}
                _aname = _ad.get("agent_name", "Agent") if isinstance(_ad, dict) else "Agent"
                _hrs = _ad.get("hours", "12+") if isinstance(_ad, dict) else "12+"
                category, display = "welfare", f"😴 {_aname} — {_hrs}h overwork (8h rest?)"
            elif at == "email_reply":
                _ad = r.get("action_data") or {}
                _to = (_ad.get("to_address") or "?") if isinstance(_ad, dict) else "?"
                _subj = (_ad.get("subject") or "") if isinstance(_ad, dict) else ""
                category, display = "email_reply", f"✉️ Reply to {_to} — {_subj[:50]}"
            elif at in ("improvement_approve", "improvement_approve_red"):
                _ad = r.get("action_data") or {}
                try:
                    _pid = (
                        int(_ad.get("proposal_id"))
                        if isinstance(_ad, dict) and _ad.get("proposal_id") is not None
                        else None
                    )
                except (TypeError, ValueError):
                    _pid = None
                _md = _prop_meta.get(_pid, {})
                category, display = _code_fix_label(at, _md)
                # override the reason with the concrete finding detail
                r["reason"] = _code_fix_reason(_md, _pid) or r.get("reason")
            else:
                category, display = "other", at
            approvals.append(
                {
                    "id": f"autonomy:{r['id']}",
                    "source": "autonomy_approval_queue",
                    "source_id": r["id"],
                    "category": category,
                    "display_name": display,
                    "action_type": at,
                    "tier": r.get("tier"),
                    "priority": r.get("priority"),
                    "reason": r.get("reason"),
                    "requested_by": r.get("requested_by"),
                    "agent_name": None,
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                    "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
                }
            )

        # 2. contractor_approval_requests — cost-gated contractor dispatch
        cur.execute(
            """SELECT r.id, r.agent_id, r.task_type, r.task_description,
                      r.module_source, r.estimated_cost, r.estimated_tokens,
                      r.contractor_provider, r.contractor_model,
                      r.priority, r.created_at, r.expires_at,
                      a.name AS agent_name, a.display_name AS agent_display
               FROM contractor_approval_requests r
               LEFT JOIN agents a ON a.id = r.agent_id
               WHERE r.status = 'pending'
               ORDER BY r.priority ASC NULLS LAST, r.created_at ASC"""
        )
        for r in cur.fetchall():
            r = dict(r)
            approvals.append(
                {
                    "id": f"contractor:{r['id']}",
                    "source": "contractor_approval_requests",
                    "source_id": r["id"],
                    "category": "contractor_dispatch",
                    "display_name": "Contractor Dispatch",
                    "action_type": r.get("task_type") or "contractor_dispatch",
                    "module_source": r.get("module_source"),
                    "contractor": f"{r.get('contractor_provider') or ''}/{r.get('contractor_model') or ''}".strip("/"),
                    "estimated_cost": (float(r["estimated_cost"]) if r.get("estimated_cost") is not None else None),
                    "estimated_tokens": r.get("estimated_tokens"),
                    "priority": r.get("priority"),
                    "reason": (r.get("task_description") or "")[:300] or None,
                    "agent_name": r.get("agent_display") or r.get("agent_name"),
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                    "expires_at": r["expires_at"].isoformat() if r.get("expires_at") else None,
                }
            )

        # 3. bridge_jobs.pending_approval — cloud dispatch gate
        cur.execute(
            """SELECT id, agent_name, module_source, description, created_at
               FROM bridge_jobs
               WHERE status = 'pending_approval'
               ORDER BY created_at ASC"""
        )
        for r in cur.fetchall():
            r = dict(r)
            desc = r.get("description") or ""
            approvals.append(
                {
                    "id": f"bridge:{r['id']}",
                    "source": "bridge_jobs",
                    "source_id": r["id"],
                    "category": "cloud_dispatch",
                    "display_name": "Cloud Dispatch",
                    "action_type": "cloud_dispatch",
                    "module_source": r.get("module_source"),
                    "reason": desc[:300] if desc else None,
                    "agent_name": r.get("agent_name"),
                    "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                }
            )

        # 4. hiring_candidates — Phase A of task #2102
        cur.execute(
            """SELECT
                   hc.id,
                   hc.capability,
                   hc.gap_reason,
                   hc.narrative,
                   hc.shortlist,
                   hc.proposed_at,
                   hc.proposed_by_agent_id,
                   a.display_name AS proposer_name,
                   -- #5829: age ONLY. Pure arithmetic on a column already selected —
                   -- no join, no scan.
                   --
                   -- ⚠️ An earlier revision of this query ALSO computed demand_30d and
                   -- active_holders here, as correlated subqueries over
                   -- task_execution_log. That table holds 1,238,358 rows and is
                   -- deliberately never pruned (it is the token ledger, #4550), and the
                   -- lower(replace(...)) on both sides defeated every index — so it ran
                   -- ONE FULL SCAN PER HIRING ROW. Measured live: this endpoint went
                   -- from ~70ms to 57-84s and the tab died with "Unexpected end of JSON
                   -- input" as the worker timed out mid-response. Even the corrected
                   -- single-aggregate form costs 778ms, which is still wrong for an
                   -- endpoint the UI polls.
                   --
                   -- Demand belongs where it already lives: the SCHEDULED gate in
                   -- welfare_governance_service.recommend_sole_agent_staffing_gaps(),
                   -- which stops a no-demand proposal from ever being created. A UI
                   -- poll must not re-derive it.
                   EXTRACT(EPOCH FROM (NOW() - hc.proposed_at)) / 86400.0 AS age_days_sql
               FROM hiring_candidates hc
               LEFT JOIN agents a ON a.id = hc.proposed_by_agent_id
               WHERE hc.status = 'pending'
               ORDER BY hc.proposed_at DESC"""
        )
        for r in cur.fetchall():
            r = dict(r)
            shortlist = r.get("shortlist")
            if shortlist is None:
                shortlist = []
            approvals.append(
                {
                    "id": f"hire:{r['id']}",
                    "source": "hire",
                    "source_id": r["id"],
                    "category": "hiring",
                    "display_name": r["capability"],
                    "action_type": "hire_candidate",
                    "reason": r.get("narrative") or r.get("gap_reason"),
                    "agent_name": r.get("proposer_name") or "K.I.N.",
                    "created_at": r["proposed_at"].isoformat() if r.get("proposed_at") else None,
                    "payload": {
                        "shortlist": shortlist,
                        "gap_reason": r.get("gap_reason"),
                        "narrative": r.get("narrative"),
                        # #5829: a proposal nobody drains should show its own age.
                        # 15 sat pending, oldest 08-17, none ever actioned.
                        "age_days": (round(float(r["age_days_sql"]), 1) if r.get("age_days_sql") is not None else None),
                        "stale": bool(r.get("age_days_sql") is not None and float(r["age_days_sql"]) >= 7.0),
                    },
                }
            )

    # Decorate each row with escalation_chain
    try:
        from services.agent_service import get_agent_cache

        agent_cache = get_agent_cache() or {}
    except Exception:
        agent_cache = {}

    for a in approvals:
        display = a.get("agent_name")
        department = None
        if display:
            for cached in agent_cache.values():
                cname = cached.get("display_name") or cached.get("name")
                if cname == display:
                    department = cached.get("department")
                    break
        a["escalation_chain"] = _build_escalation_chain(display, department, agent_cache)
    return approvals
