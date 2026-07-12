"""COO command surface — Tools & Actions (Slice 4). A CURATED, SAFE catalog of diagnostics she
runs from the cockpit chat. Two execution paths, both READ-ONLY:
  • `capability` entries run a known-tool via the delegation service (DHQ welfare/cost/C.R.E.E.D.).
  • `runner` entries call a local read-only status service directly and format a one-line summary.
run_action executes them synchronously. Only catalog keys run — nothing state-changing.
Every runner below MUST be a pure read: no writes, deploys, sends, generation, or proposals.
"""

from __future__ import annotations

from typing import Any, Dict


# --- Local read-only diagnostic runners --------------------------------------------------
# Each returns {"success": bool, "summary": str, "result": dict}. Imports are lazy so importing
# this module stays cheap. All are pure reads over verified sync services (no request context).


def _diag_welfare() -> Dict[str, Any]:
    from services.agent_service import get_kin_welfare_digest

    d = get_kin_welfare_digest() or {}
    m = d.get("summary_metrics") or {}
    sev = d.get("severity") or "ok"
    summary = (
        f"Welfare [{sev}]: {m.get('agents_working_now', 0)} working now, "
        f"{m.get('total_over_budget', 0)} over-budget, {m.get('total_at_risk', 0)} at-risk, "
        f"{m.get('total_starving', 0)} starving."
    )
    return {"success": True, "summary": summary, "result": m}


def _diag_infra() -> Dict[str, Any]:
    from services.infra_heartbeat_service import check_all_critical

    d = check_all_critical() or {}
    m = d.get("summary_metrics") or {}
    sev = d.get("severity") or "ok"
    down = d.get("down_names") or []
    tail = f" (down: {', '.join(down[:5])})" if down else ""
    summary = (
        f"Infra [{sev}]: {m.get('healthy', 0)}/{m.get('total', 0)} healthy, "
        f"{m.get('down', 0)} down{tail}, {m.get('warnings', 0)} warnings."
    )
    return {"success": True, "summary": summary, "result": m}


def _diag_dispatch() -> Dict[str, Any]:
    from services.dispatch_health_service import dispatch_health

    d = dispatch_health(24.0) or {}
    total = d.get("total", 0) or 0
    succ = d.get("success", 0) or 0
    pct = round(succ / total * 100) if total else 0
    summary = (
        f"Dispatch 24h: {total} jobs, {pct}% success, "
        f"{d.get('failed_real', 0)} real fails, {d.get('failed_timeout', 0)} timeouts, "
        f"{d.get('pending', 0)} pending."
    )
    return {"success": True, "summary": summary, "result": d}


def _diag_knowledge() -> Dict[str, Any]:
    # Direct COUNT over knowledge_base — a pure read that avoids importing the heavy
    # tools.consciousness package (route registration + ai_bridge chain). `embedding IS NOT NULL`
    # is the documented "embedded" check.
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT COUNT(*) AS total, COUNT(embedding) AS embedded FROM knowledge_base")
        row = cur.fetchone() or {}
    total = (row.get("total") if hasattr(row, "get") else row[0]) or 0
    emb = (row.get("embedded") if hasattr(row, "get") else row[1]) or 0
    pct = round(emb / total * 100) if total else 0
    summary = f"Knowledge base: {total} entries, {emb} embedded ({pct}% coverage)."
    return {"success": True, "summary": summary, "result": {"total": total, "embedded": emb, "coverage_pct": pct}}


def _diag_fleet() -> Dict[str, Any]:
    from services.fleet_service import list_nodes

    nodes = list_nodes() or []
    total = len(nodes)
    gpu = sum(1 for n in nodes if n.get("gpu_model"))
    reporting = 0
    try:  # "reporting" = a heartbeat within the last 5 minutes; degrade gracefully if unavailable
        from datetime import timedelta, timezone

        from services.time_utils import now_utc

        now = now_utc()
        for n in nodes:
            hb = n.get("last_heartbeat")
            if hb is None:
                continue
            if getattr(hb, "tzinfo", None) is None:
                hb = hb.replace(tzinfo=timezone.utc)
            if (now - hb) <= timedelta(minutes=5):
                reporting += 1
        head = f"{reporting}/{total} reporting (5m)"
    except Exception:
        head = f"{total} nodes"
    summary = f"Fleet: {head}, {gpu} with GPU."
    return {"success": True, "summary": summary, "result": {"total": total, "reporting": reporting, "gpu": gpu}}


# key -> {label, description, + EITHER capability OR runner}. SAFE read-only diagnostics ONLY.
# Do NOT add state-changing entries (deploy_*, restore_*, *_proposal_adapter, external_fetch,
# capture_*, translation_coverage_scan, portrait_*, documentation, ...).
_CATALOG = {
    "health": {
        "label": "Platform health",
        "capability": "check_platform_health",
        "description": "Live platform + service health.",
    },
    "qa": {
        "label": "QA suite",
        "capability": "run_qa_suite",
        "description": "Run the platform QA test suite.",
    },
    "dep_drift": {
        "label": "Dependency drift",
        "capability": "check_dep_drift",
        "description": "Check for dependency drift.",
    },
    "misroute_audit": {
        "label": "Misroute audit",
        "capability": "run_misroute_audit",
        "description": "Audit agent dispatch misroutes.",
    },
    "briefing_health": {
        "label": "Briefing health",
        "capability": "run_briefing_health",
        "description": "Check the session-briefing pipeline.",
    },
    "welfare": {
        "label": "Agent welfare",
        "runner": _diag_welfare,
        "description": "K.I.N. welfare digest — stress, budget, at-risk agents.",
    },
    "infra": {
        "label": "Infra heartbeat",
        "runner": _diag_infra,
        "description": "Critical container health across the stack.",
    },
    "dispatch": {
        "label": "Dispatch health",
        "runner": _diag_dispatch,
        "description": "24h dispatch success / failure / pending.",
    },
    "knowledge": {
        "label": "Knowledge base",
        "runner": _diag_knowledge,
        "description": "Knowledge-base size + embedding coverage.",
    },
    "fleet": {
        "label": "Fleet status",
        "runner": _diag_fleet,
        "description": "Fleet node count, GPU, and heartbeat.",
    },
}


def list_actions():
    return [{"key": k, "label": v["label"], "description": v["description"]} for k, v in _CATALOG.items()]


def run_action(key):
    entry = _CATALOG.get((key or "").strip())
    if not entry:
        return {"ok": False, "error": "unknown_action"}
    try:
        runner = entry.get("runner")
        if runner is not None:
            res = runner()  # local read-only diagnostic
        else:
            from services.delegation_service import _execute_known_tool

            res = _execute_known_tool(entry["capability"], {}, f"Cockpit action: {entry['label']}")
        if res and res.get("success"):
            return {
                "ok": True,
                "label": entry["label"],
                "summary": res.get("summary") or "",
                "result": res.get("result"),
            }
        return {"ok": False, "label": entry["label"], "error": (res or {}).get("error") or "failed"}
    except Exception:
        return {"ok": False, "label": entry["label"], "error": "exception"}
