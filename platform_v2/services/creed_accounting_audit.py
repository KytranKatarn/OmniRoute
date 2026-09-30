"""C.R.E.E.D. accounting self-audit — the platform holding ITSELF to its own
transparency standard ("use our own tools").

Periodically ASSERTS the token / welfare / carbon accounting invariants that the
rest of the platform relies on (Token Economy, K.I.N. welfare digest, the
environmental pillar) and reports drift as findings. This module does **not**
fix anything — it is detection-only, read-only, and side-effect-free, so these
accounting bugs (fabricated cloud carbon, silently-undercounted tokens, agents
with no budget/welfare row, unattributed cloud spend) can't silently regress
without someone noticing.

Called daily by ``ai_bridge/agent_loop.py`` (``creed_accounting_audit`` job),
which is the ONLY caller that alerts (C.R.E.E.D. governance event + A.R.C.H.I.E.
Telegram advisory) on a violation — ``run_accounting_audit()`` itself never
emits anything, so it is safe to call from tests or ad-hoc checks without
spamming Telegram.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from database import get_db_cursor
from services.carbon_footprint_service import _is_llm_model

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds — module-level constants so a retune never needs a code review of
# the query logic, just these numbers.
# ---------------------------------------------------------------------------
WINDOW_HOURS = 24
TOKEN_UNDERCOUNT_MAX_FRACTION = 0.05  # >5% zero-token real-LLM rows = drift
CLOUD_UNATTRIBUTED_MAX_FRACTION = 0.50  # >50% unattributed contract rows = drift

# Explicit belt-and-suspenders exclusion for the token-undercount check, kept
# independent of carbon_footprint_service._NON_LLM_MODELS so a future edit to
# that sentinel set can't silently widen (or narrow) what this check covers.
_EXTRA_NON_TOKEN_MODELS = {"internal", "browser"}


def _finding(code: str, severity: str, detail: str, count: int) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "detail": detail, "count": int(count)}


def _check_no_cloud_carbon(cur) -> Dict[str, Any] | None:
    """Cloud dispatches (``worker_type='contract'``) that used a real-LLM
    ``model_used`` would get watts x Canada-grid-factor carbon fabricated onto
    them by ``carbon_footprint_service.run_carbon_footprint_job()`` /
    ``per_agent_efficiency()``. As of PR #2175 all three carbon consumers
    (co2_g_sql + both Python aggregators) exclude ``worker_type='contract'``, so
    no cloud carbon is fabricated. This is now an INFO awareness signal for the
    PRECONDITION: a cloud dispatch that is actually fabricatable (success + real
    ``duration_ms`` + real-LLM model) — a runtime audit can't prove a code guard
    is present (that is covered by the PR #2175 unit tests), so it surfaces such
    rows so the guards can be confirmed. Duration-less/failed cloud rows can't
    fabricate carbon (watts x 0 = 0) and are ignored. 0 rows expected normally."""
    cur.execute(
        """
        SELECT model_used, COUNT(*) AS n
        FROM task_execution_log
        WHERE worker_type = 'contract'
          AND success = true
          AND duration_ms > 0
          AND created_at >= NOW() - INTERVAL '%s hours'
        GROUP BY model_used
        """,
        (WINDOW_HOURS,),
    )
    offending = {r["model_used"]: int(r["n"]) for r in cur.fetchall() if _is_llm_model(r["model_used"])}
    count = sum(offending.values())
    if count <= 0:
        return None
    return _finding(
        "no_cloud_carbon",
        "info",
        (
            f"{count} fabricatable cloud (worker_type='contract') dispatch(es) in the last "
            f"{WINDOW_HOURS}h (real-LLM model + real duration). The carbon consumers all exclude "
            f"'contract' (PR #2175, unit-tested), so no carbon is fabricated — this is an awareness "
            f"signal to confirm those guards hold. By model: {offending}"
        ),
        count,
    )


def _check_token_undercount(cur) -> Dict[str, Any] | None:
    """Fraction of REAL-LLM task_execution_log rows (worker_type set, model_used
    a real inference model per ``_is_llm_model``, explicitly excluding the
    'internal'/'browser' sentinels) that logged ``tokens_used=0``. A spike above
    threshold usually means a new dispatch write-site forgot to persist
    tokens_used (the historical pattern behind KB mistake #276900 / the A.R.M.A.D.A.
    accounting fixes).

    Only SUCCESSFUL rows are counted. A failed dispatch (timeout, reaper kill,
    admission-gate shed) produced nothing to meter and legitimately logs
    ``tokens_used=0``; counting those measured the failure rate, not the write
    site. 2026-09-29: 18.0% flagged (1823/10121) but 0.5% (47/9404) on success
    only — 1288 of wtf_hub's 1290 zero rows were failures. A real write-site
    regression still shows here, as successful rows that persisted no tokens.
    The failure rate itself is watched elsewhere (dispatch_health_service)."""
    cur.execute(
        """
        SELECT model_used,
               COUNT(*) AS n,
               SUM(CASE WHEN COALESCE(tokens_used, 0) = 0 THEN 1 ELSE 0 END) AS zero_n
        FROM task_execution_log
        WHERE worker_type IS NOT NULL
          AND success = true
          AND created_at >= NOW() - INTERVAL '%s hours'
        GROUP BY model_used
        """,
        (WINDOW_HOURS,),
    )
    total = 0
    zero = 0
    for row in cur.fetchall():
        model = row["model_used"]
        if not _is_llm_model(model):
            continue
        if (model or "").strip().lower() in _EXTRA_NON_TOKEN_MODELS:
            continue
        total += int(row["n"])
        zero += int(row["zero_n"] or 0)
    if total <= 0:
        return None
    fraction = zero / total
    if fraction <= TOKEN_UNDERCOUNT_MAX_FRACTION:
        return None
    return _finding(
        "token_undercount",
        "warning",
        (
            f"{zero}/{total} ({fraction:.1%}) SUCCESSFUL real-LLM task_execution_log rows in the last "
            f"{WINDOW_HOURS}h logged tokens_used=0 — above the {TOKEN_UNDERCOUNT_MAX_FRACTION:.0%} "
            "threshold. Likely a dispatch write-site regression (missing tokens_used persistence)."
        ),
        zero,
    )


def _check_budgets_present(cur) -> Dict[str, Any] | None:
    """Every active AI agent (worker_type='ai', status != 'decommissioned') must
    have an agent_budgets row with a positive token_limit_per_day — otherwise it
    dispatches with no daily ceiling, defeating the welfare/budget system."""
    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM agents a
        LEFT JOIN agent_budgets ab ON ab.agent_id = a.id
        WHERE a.worker_type = 'ai'
          AND a.status <> 'decommissioned'
          AND (ab.token_limit_per_day IS NULL OR ab.token_limit_per_day = 0)
        """
    )
    count = int((cur.fetchone() or {}).get("n") or 0)
    if count <= 0:
        return None
    return _finding(
        "budgets_present",
        "warning",
        (
            f"{count} active AI agent(s) have no agent_budgets row, or a NULL/0 "
            "token_limit_per_day — they would dispatch with no daily token ceiling."
        ),
        count,
    )


def _check_welfare_fresh(cur) -> Dict[str, Any] | None:
    """Every active AI agent must have at least one agent_emotional_state row —
    otherwise welfare simply isn't being tracked for it (K.I.N.'s digest and the
    C.R.E.E.D. welfare governance score both silently skip agents with no row)."""
    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM agents a
        WHERE a.worker_type = 'ai'
          AND a.status <> 'decommissioned'
          AND NOT EXISTS (SELECT 1 FROM agent_emotional_state es WHERE es.agent_id = a.id)
        """
    )
    count = int((cur.fetchone() or {}).get("n") or 0)
    if count <= 0:
        return None
    return _finding(
        "welfare_fresh",
        "warning",
        f"{count} active AI agent(s) have no agent_emotional_state row — welfare is not being written for them.",
        count,
    )


def _check_cloud_attribution(cur) -> Dict[str, Any] | None:
    """Fraction of last-window cloud (worker_type='contract') dispatches with
    ``agent_id IS NULL`` — unattributed cloud spend can't be charged to an
    agent's budget or folded into its welfare/cost accounting. Informational
    only: this is the KNOWN gap the cloud-attribution fix (in flight elsewhere)
    is expected to close, so this finding should flip to healthy once that
    lands rather than needing action here."""
    cur.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN agent_id IS NULL THEN 1 ELSE 0 END) AS unattributed
        FROM task_execution_log
        WHERE worker_type = 'contract'
          AND created_at >= NOW() - INTERVAL '%s hours'
        """,
        (WINDOW_HOURS,),
    )
    row = cur.fetchone() or {}
    total = int(row.get("total") or 0)
    unattributed = int(row.get("unattributed") or 0)
    if total <= 0:
        return None
    fraction = unattributed / total
    if fraction <= CLOUD_UNATTRIBUTED_MAX_FRACTION:
        return None
    return _finding(
        "cloud_attribution",
        "info",
        (
            f"{unattributed}/{total} ({fraction:.1%}) cloud (worker_type='contract') dispatches in "
            f"the last {WINDOW_HOURS}h have agent_id IS NULL — cloud usage is not attributed to an "
            "agent for cost/welfare accounting."
        ),
        unattributed,
    )


_CHECKS = (
    _check_no_cloud_carbon,
    _check_token_undercount,
    _check_budgets_present,
    _check_welfare_fresh,
    _check_cloud_attribution,
)


def run_accounting_audit() -> Dict[str, Any]:
    """Read-only assertion of the token/welfare/carbon accounting invariants.

    Never mutates anything and never alerts — pure detection. Returns
    ``{ok, checked_at, findings}`` where ``findings`` is a list of
    ``{code, severity, detail, count}`` dicts, one per VIOLATED invariant
    (an empty list means every invariant currently holds).
    """
    checked_at = datetime.now(timezone.utc).isoformat()
    findings: List[Dict[str, Any]] = []

    try:
        with get_db_cursor() as (_conn, cur):
            for check in _CHECKS:
                finding = check(cur)
                if finding is not None:
                    findings.append(finding)
    except Exception as exc:  # noqa: BLE001 — never let a DB hiccup crash the caller
        logger.warning("creed_accounting_audit: query failed: %s", exc)
        return {
            "ok": False,
            "checked_at": checked_at,
            "findings": [_finding("audit_error", "error", f"audit query failed: {exc}", 1)],
        }

    # ok = no ACTIONABLE finding. 'info' findings (awareness signals like a fabricatable
    # cloud row, or historical unattributed rows that age out of the window) are reported
    # but do NOT fail the audit — only warning/critical/error do.
    actionable = [f for f in findings if f.get("severity") in ("warning", "critical", "error")]
    return {"ok": len(actionable) == 0, "checked_at": checked_at, "findings": findings}
