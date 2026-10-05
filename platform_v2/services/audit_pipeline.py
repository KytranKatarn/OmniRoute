"""Audit pipeline — auto-creates Repair Bay proposals from Code Health audit findings.

Called after audit_single_module() completes. Red (security) issues get individual
high-priority proposals with Tier 2 (human) approval. Yellow (quality) issues get
medium-priority proposals with Tier 1 (auto) approval. Info (style) issues are skipped.

Import:
    from services.audit_pipeline import process_audit_findings, dispatch_proposal_fix,
        dispatch_audit_proposals, verify_fix_deployment
"""

import difflib
import json
import logging
import os
import re
import sys

import psycopg2

from database import get_db_cursor

logger = logging.getLogger(__name__)


def _ensure_import_paths() -> None:
    """Make the DHQ dispatcher importable from ANY process, not just the app boot path.

    The dispatcher chain does `from db import ...`, resolved from the ai_bridge package
    dir, which only lands on sys.path via app.py at boot. The scheduler sidecar and any
    bare exec import this module directly, so `from tools.department_hq.services.
    department_dispatcher import ...` raises ModuleNotFoundError('db') instantly there.

    That is an ENVIRONMENT failure, but dispatch_proposal_fix reported it as a dispatch
    error, and the drain marked those proposals permanently attempted — 18 unrelated
    proposals parked in 0.8s on 2026-07-20, never retried again. Mirrors the identical
    guard in services/cluster_dispatch.py and signal_calendar_service.py. KB #272154.
    """
    import importlib.util

    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    spec = importlib.util.find_spec("ai_bridge")
    if spec and spec.submodule_search_locations:
        pkg_dir = list(spec.submodule_search_locations)[0]
        if pkg_dir not in sys.path:
            sys.path.insert(0, pkg_dir)


# ---------------------------------------------------------------------------
# C.R.E.E.D. Governance Gates
# ---------------------------------------------------------------------------

# The automated repair pipeline must never auto-fix its OWN oversight / execution
# machinery — that would let the AI workforce weaken the controls on its own fixes.
# This is TARGET-based (file path / module) and agent-independent, checked BEFORE
# dispatch so a denied proposal never costs an LLM call. A human can still fix these
# files via a normal PR. (Replaces the old department-based self-mod rule, which
# wrongly blocked F.O.R.G.E. — the platform's sole code-fixer — from every
# Engineering-filed module incl. consciousness/dev_hq; #4934.)
_SELF_GOVERNANCE_MODULES = {"repair_bay", "creed_command"}
_SELF_GOVERNANCE_PATH_MARKERS = (
    "services/audit_pipeline.py",  # this pipeline + the C.R.E.E.D. gate itself
    "services/agent_service.py",  # agent definitions / lifecycle
    "services/agent_dispatch.py",
    "services/agent_models.py",
    "department_dispatcher.py",  # dispatch / orchestration substrate
    "orchestration_engine.py",
    "smart_router.py",
    "creed_emit.py",  # C.R.E.E.D. governance emission
    "welfare_governance",  # welfare governance scorers / services
)


def creed_gate_pre_dispatch(proposal_id):
    """C.R.E.E.D. Gate 1a — self-governance check, run BEFORE inference.

    The automated repair pipeline must not auto-fix its own oversight/execution
    machinery (this gate, agent_service, the dispatcher/router, C.R.E.E.D.
    emission, the repair_bay module). Target-based and agent-independent, so it
    runs before dispatch and a denied proposal costs no LLM call. A human can
    still fix these files via a normal PR.

    Returns {"approved": bool, "reason": str}.
    """
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT metadata FROM improvement_proposals WHERE id = %s",
                (proposal_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"approved": False, "reason": f"proposal #{proposal_id} not found"}
            meta = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
            module_name = (meta.get("module_name") or "").strip()
            target = (meta.get("file_path") or meta.get("runtime_file") or "").replace("\\", "/").lower()
            if module_name in _SELF_GOVERNANCE_MODULES or any(
                marker in target for marker in _SELF_GOVERNANCE_PATH_MARKERS
            ):
                reason = (
                    "self-modification blocked — the automated repair pipeline may not "
                    f"auto-fix its own oversight machinery ({module_name or target or '?'}); "
                    "requires human review"
                )
                _log_creed_gate("repair_fix_generation", "denied", None, reason)
                return {"approved": False, "reason": reason}
    except Exception as e:
        logger.error("C.R.E.E.D. pre-dispatch gate error for proposal #%d: %s", proposal_id, e)
        return {"approved": False, "reason": f"gate error: {e}"}
    return {"approved": True, "reason": "self-governance check passed"}


def creed_gate_pre_fix(proposal_id, agent_id):
    """C.R.E.E.D. Gate 1 — agent-state check, run AFTER the fix agent is resolved.

    Checks the agent that actually produced the fix:
        1. Welfare check (stress/energy thresholds)
        2. Capability check (agent exists and is active)

    The self-modification / self-governance constraint is target-based and runs
    BEFORE dispatch — see creed_gate_pre_dispatch() — so a self-governance denial
    never costs an LLM call (#4934).

    Returns:
        {"approved": bool, "reason": str}
    """
    reason = "all checks passed"
    approved = True

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            # --- Resolve the agent that produced the fix ---
            cur.execute(
                """SELECT a.name, a.display_name, a.department, a.shift_state
                   FROM agents a WHERE a.id = %s""",
                (agent_id,),
            )
            agent = cur.fetchone()

            if not agent:
                approved = False
                reason = f"agent id={agent_id} not found"
                _log_creed_gate(
                    "repair_fix_generation",
                    "denied",
                    agent_id,
                    reason,
                )
                return {"approved": approved, "reason": reason}

            # --- 1. Welfare check ---
            cur.execute(
                """SELECT stress_level, energy_level
                   FROM agent_emotional_state
                   WHERE agent_id = %s
                   ORDER BY id DESC LIMIT 1""",
                (agent_id,),
            )
            welfare = cur.fetchone()
            if welfare:
                stress = float(welfare.get("stress_level") or 0)
                energy = float(welfare.get("energy_level") or 1)
                if stress >= 0.8 or energy <= 0.2:
                    approved = False
                    reason = (
                        f"agent welfare threshold exceeded — "
                        f"stress={stress:.2f} (max 0.8), energy={energy:.2f} (min 0.2)"
                    )
                    _log_creed_gate(
                        "repair_fix_generation",
                        "denied",
                        agent_id,
                        reason,
                    )
                    return {"approved": approved, "reason": reason}

            # --- 2. Capability check (agent exists and is dispatchable) ---
            # `winding_down` is a SOFT state, and this gate must agree with the component
            # that does the selecting. department_coordinator.score_agent admits
            # ("active", "winding_down") and merely applies a -0.3 preference penalty
            # (line ~606); the HARD blocks there are an open rest cycle and task-queue
            # saturation. Rejecting winding_down here contradicted that contract — and
            # because this gate runs AFTER dispatch_proposal_fix has already read
            # result.response, the denial landed post-inference: one measured drain
            # produced 30 completed fixes / 62,661 tokens / 301 GPU-seconds and reported
            # dispatched=0, discarding every one. Worse, those tokens still bill the
            # agent and still raise its stress, causing more rests and more denials.
            #
            # Welfare is NOT weakened by admitting winding_down:
            #   - stress >= 0.8 / energy <= 0.2 still denies, above (the real guard)
            #   - an agent with an OPEN rest cycle is hard-blocked at SELECTION, so it
            #     never reaches this gate
            #   - cooldown / barracked / off_duty are still denied here
            # Task #5028.
            shift = (agent.get("shift_state") or "").strip()
            if shift not in ("active", "deployed", "winding_down"):
                approved = False
                reason = f"agent shift_state is '{shift}', expected active, deployed or winding_down"
                _log_creed_gate(
                    "repair_fix_generation",
                    "denied",
                    agent_id,
                    reason,
                )
                return {"approved": approved, "reason": reason}

    except Exception as e:
        logger.error("C.R.E.E.D. Gate 1 error for proposal #%d: %s", proposal_id, e)
        approved = False
        reason = f"gate error: {e}"

    _log_creed_gate(
        "repair_fix_generation",
        "approved" if approved else "denied",
        agent_id,
        reason,
    )
    return {"approved": approved, "reason": reason}


def creed_gate_pre_apply(proposal_id):
    """C.R.E.E.D. Gate 2 — called BEFORE a generated fix is applied to the codebase.

    Checks:
        1. Scope check (diff only touches the target file)
        2. Severity-based approval tier

    Returns:
        {"approved": bool, "reason": str, "tier": int}
    """
    approved = True
    reason = "all checks passed"
    tier = 1

    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT code_changes, metadata, priority
                   FROM improvement_proposals WHERE id = %s""",
                (proposal_id,),
            )
            row = cur.fetchone()

        if not row:
            _log_creed_gate_apply("denied", f"proposal #{proposal_id} not found")
            return {"approved": False, "reason": f"proposal #{proposal_id} not found", "tier": 0}

        meta = row["metadata"] if isinstance(row["metadata"], dict) else json.loads(row["metadata"] or "{}")
        target_file = meta.get("file_path", "")
        severity_tier = meta.get("severity_tier", "yellow")
        diff_text = row.get("code_changes") or ""

        # --- 1. Scope check — diff should only reference the target file ---
        if diff_text and target_file:
            # Look for diff headers like "--- a/path" or "+++ b/path"
            import re

            file_refs = re.findall(r"^(?:---|\+\+\+)\s+[ab]/(.+)$", diff_text, re.MULTILINE)
            target_basename = os.path.basename(target_file)
            for ref in file_refs:
                ref_basename = os.path.basename(ref)
                if ref_basename != target_basename and ref != "/dev/null":
                    approved = False
                    reason = f"scope violation — diff references '{ref}' " f"but target is '{target_file}'"
                    _log_creed_gate_apply("denied", reason)
                    return {"approved": False, "reason": reason, "tier": 0}

        # --- 2. Severity-based approval tier ---
        if severity_tier == "red":
            tier = 2
            approved = False
            reason = "red severity requires human approval"
            _log_creed_gate_apply("denied", reason)
            return {"approved": False, "reason": reason, "tier": 2}

        # Yellow: auto-approve if diff is short enough (< 50 lines)
        diff_line_count = len(diff_text.strip().splitlines()) if diff_text else 0
        if diff_line_count >= 50:
            tier = 2
            approved = False
            reason = f"diff too large ({diff_line_count} lines >= 50) — requires human review"
            _log_creed_gate_apply("denied", reason)
            return {"approved": False, "reason": reason, "tier": 2}

    except Exception as e:
        logger.error("C.R.E.E.D. Gate 2 error for proposal #%d: %s", proposal_id, e)
        _log_creed_gate_apply("denied", f"gate error: {e}")
        return {"approved": False, "reason": f"gate error: {e}", "tier": 0}

    _log_creed_gate_apply("approved", reason)
    return {"approved": approved, "reason": reason, "tier": tier}


def _log_creed_gate(event_type, outcome, agent_id, reason):
    """Log a C.R.E.E.D. gate decision to governance_audit_log."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO governance_audit_log
                   (event_type, event_category, action, outcome, agent_id, reason, timestamp)
                   VALUES (%s, 'creed_gate', 'pre_fix_check', %s, %s, %s, NOW())""",
                (event_type, outcome, agent_id, (reason or "")[:500]),
            )
    except Exception as e:
        logger.warning("Failed to log C.R.E.E.D. gate event: %s", e)


def _log_creed_gate_apply(outcome, reason):
    """Log a C.R.E.E.D. Gate 2 (pre-apply) decision to governance_audit_log."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO governance_audit_log
                   (event_type, event_category, action, outcome, agent_id, reason, timestamp)
                   VALUES ('repair_fix_apply', 'creed_gate', 'pre_apply_check', %s, NULL, %s, NOW())""",
                (outcome, (reason or "")[:500]),
            )
    except Exception as e:
        logger.warning("Failed to log C.R.E.E.D. Gate 2 event: %s", e)


# Map audit severity tiers to proposal attributes
_TIER_CONFIG = {
    "red": {
        "priority": "critical",
        "risk_level": "high",
        "approval_tier": 2,
        "approval_priority": 3,
    },
    "yellow": {
        "priority": "medium",
        "risk_level": "medium",
        "approval_tier": 1,
        "approval_priority": 7,
    },
}


# ADR-013 carve-out (#5706): the DHQ dispatcher + orchestration engine ARE the
# sanctioned direct-Ollama callers — every other module routes through them, so
# flagging these two files as DIRECT_OLLAMA violations is a structural false
# positive that regenerated proposals forever. Exempt exactly these paths.
_DIRECT_OLLAMA_SANCTIONED_SUFFIXES = (
    "department_hq/services/department_dispatcher.py",
    "department_hq/services/orchestration_engine.py",
)


def process_audit_findings(module_name, issues_list):
    """Process audit findings and create Repair Bay proposals for red/yellow issues.

    Args:
        module_name: The module that was audited (e.g. 'consciousness')
        issues_list: List of issue dicts from audit_single_module, each with
                     code, severity (red/yellow/info), file, detail

    Returns:
        {"proposals_created": int, "skipped_duplicates": int, "info_skipped": int}
    """
    proposals_created = 0
    skipped = 0
    info_skipped = 0

    for issue in issues_list:
        severity = issue.get("severity", "info")

        # Skip info-tier issues — no proposals for style findings
        if severity not in _TIER_CONFIG:
            info_skipped += 1
            continue

        try:
            # Build file path — handle platform modules, standalone, and website products
            issue_file = issue.get("file", module_name)
            if module_name.startswith("standalone_") or module_name.startswith("website_"):
                file_path = f"{module_name}/{issue_file}"
            elif module_name.startswith("["):
                file_path = f"{module_name}/{issue_file}"
            else:
                file_path = f"platform_v2/tools/{module_name}/{issue_file}"
            issue_code = issue["code"]

            # Sanctioned ADR-013 Ollama callers are not DIRECT_OLLAMA violations.
            if issue_code == "DIRECT_OLLAMA" and file_path.endswith(_DIRECT_OLLAMA_SANCTIONED_SUFFIXES):
                info_skipped += 1
                continue

            if _has_open_audit_proposal(file_path, issue_code, issue.get("detail")):
                skipped += 1
                continue

            proposal_id = _create_audit_proposal(issue, module_name, file_path)
            if proposal_id:
                proposals_created += 1
        except psycopg2.Error as db_err:
            # Systemic DB failure (missing table, wrong column, etc.) — this would
            # fail for EVERY issue, so don't bury it as a per-issue warning. Surface
            # it loudly with a traceback and abort the batch so the breakage is
            # visible (the caller in agent_loop wraps this call in its own handler).
            logger.error(
                "Audit pipeline DB error writing proposal for %s/%s — aborting batch: %s",
                module_name,
                issue.get("code"),
                db_err,
                exc_info=True,
            )
            raise
        except Exception as e:
            logger.warning(
                "Failed to create audit proposal for %s/%s: %s",
                module_name,
                issue.get("code"),
                e,
            )

    logger.info(
        "Audit pipeline: %s — %d proposals created, %d duplicates skipped, %d info skipped",
        module_name,
        proposals_created,
        skipped,
        info_skipped,
    )

    return {
        "proposals_created": proposals_created,
        "skipped_duplicates": skipped,
        "info_skipped": info_skipped,
    }


def _audit_file_path(module_name, issue_file):
    """Rebuild the exact file_path key process_audit_findings uses, so a re-audit's
    findings fingerprint-match the proposals created from the original audit."""
    issue_file = issue_file or module_name
    if module_name.startswith("standalone_") or module_name.startswith("website_") or module_name.startswith("["):
        return f"{module_name}/{issue_file}"
    return f"platform_v2/tools/{module_name}/{issue_file}"


# #5945 — the inverse of _audit_file_path, for FIXERS rather than fingerprints.
#
# `file_path` is a FINGERPRINT KEY: _audit_file_path deliberately preserves a
# "["-prefixed module token so a re-audit's findings match the proposals created from
# the original audit. That is correct for matching and useless for FIXING — nothing can
# open "[AI_BRIDGE]/semantic_search.py".
#
# ⚠️ DO NOT "fix" this by rewriting file_path. The fingerprint would stop matching, every
# affected proposal would fall out of `current` in the reverify, and each one would flip to
# "fixed" — converting a real backlog into a fake clean bill of health.
#
# Roots were DERIVED, not assumed: each token's file list was tested against candidate
# roots on disk. [AI_BRIDGE] 43/43, [APP_CORE] 262/274, [MIGRATIONS] 7/8.
# ⚠️ "[dispatch_routing]" is deliberately ABSENT — only 1 of its 69 files resolves anywhere,
# so it is a LOGICAL grouping, not a directory. Guessing a root for it would write paths
# that silently point at nothing.
_FIX_PATH_ROOTS = {
    "[AI_BRIDGE]": "ai_bridge",
    "[ai_bridge]": "ai_bridge",
    "[APP_CORE]": "platform_v2",
    "[MIGRATIONS]": "database/migrations",
}


def resolve_fix_path(file_path: str):
    """Repo-relative path a fixer can open, or None when the token has no known root.

    PURE: no filesystem access, so it returns the same answer in the container (where
    /app is platform_v2 and ai_bridge/ is not a sibling) as on the host. Callers that
    need certainty should confirm the file exists; the backfill does exactly that.
    Returns file_path unchanged when it is already a real path.
    """
    if not file_path or not isinstance(file_path, str):
        return None
    if not file_path.startswith("["):
        return file_path
    token, _, rel = file_path.partition("/")
    root = _FIX_PATH_ROOTS.get(token)
    if not root or not rel:
        return None
    return f"{root}/{rel}"


def _set_reverified(proposal_id, verdict):
    """Stamp a proposal's metadata with the re-verify verdict + timestamp (UTC)."""
    import datetime as _dt

    stamp = json.dumps({"reverified": verdict, "reverified_at": _dt.datetime.now(_dt.timezone.utc).isoformat()})
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE improvement_proposals SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb WHERE id = %s",
            (stamp, proposal_id),
        )


def reverify_deployed_findings(module_name=None):
    """Close the self-healing loop. For Code-Health proposals now marked deployed/
    implemented, re-audit the source module and confirm the finding is ACTUALLY gone:

      - fingerprint (file_path, issue_code) absent from the fresh audit  -> 'fixed'
      - still present                                                    -> 'still_open'

    'still_open' is the important case: it means a deploy was marked done but the
    scanner still flags the issue — a real regression we surface instead of trusting
    the deploy blindly. Stamps metadata.reverified on each proposal. module_name
    optionally scopes to one module. Returns {modules, fixed, still_open, details}.
    """
    from services.code_metrics_service import audit_single_module, scan_codebase

    # scan_tier='static' proposals are reverified by the static deep-scan
    # (code_health_autoheal) — this regex re-audit cannot see those codes and
    # would wrongly stamp them 'fixed'.
    sql = (
        "SELECT id, metadata FROM improvement_proposals "
        "WHERE metadata->>'source' = 'code_health_audit' "
        "AND COALESCE(metadata->>'scan_tier', 'regex') <> 'static' "
        "AND status IN ('deployed', 'implemented') "
        "AND COALESCE(metadata->>'reverified', '') = '' "
    )
    params = []
    if module_name:
        sql += "AND metadata->>'module_name' = %s "
        params.append(module_name)
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(sql, params)
        rows = cur.fetchall()
    if not rows:
        return {"modules": 0, "fixed": 0, "still_open": 0, "details": []}

    by_module = {}
    for r in rows:
        md = r["metadata"] if isinstance(r["metadata"], dict) else json.loads(r["metadata"] or "{}")
        mod = md.get("module_name")
        if mod:
            by_module.setdefault(mod, []).append((r["id"], md))

    all_modules = (scan_codebase() or {}).get("modules", {})
    fixed = still_open = 0
    details = []
    for mod, props in by_module.items():
        try:
            _f, _n, _s, issues_list, _p = audit_single_module(mod, module_data=all_modules.get(mod, {}))
        except Exception:
            logger.warning("reverify: re-audit failed for %s — skipping", mod, exc_info=True)
            continue
        current = {(_audit_file_path(mod, iss.get("file")), iss.get("code")) for iss in (issues_list or [])}
        for pid, md in props:
            verdict = "still_open" if (md.get("file_path"), md.get("issue_code")) in current else "fixed"
            if verdict == "fixed":
                fixed += 1
            else:
                still_open += 1
            _set_reverified(pid, verdict)
            details.append({"proposal_id": pid, "module": mod, "issue_code": md.get("issue_code"), "verdict": verdict})

    logger.info(
        "reverify: %d module(s), %d confirmed fixed, %d still-open (regressions)",
        len(by_module),
        fixed,
        still_open,
    )
    return {"modules": len(by_module), "fixed": fixed, "still_open": still_open, "details": details}


def _audit_path_variants(file_path):
    """Every alias spelling of one file across the [MODULE]/ placeholder prefixes.

    The scanner emits the same file as e.g. 'platform_v2/app.py' AND
    '[APP_CORE]/app.py' depending on the scan entry point, so a bare equality
    dedup created twin proposals for the same defect (#5706). Normalize via
    _PLACEHOLDER_MAP in both directions and dedup against every spelling.
    """
    variants = {file_path}
    canonical = file_path
    for placeholder, real_root in _PLACEHOLDER_MAP.items():
        if file_path.startswith(placeholder):
            canonical = real_root + file_path[len(placeholder) :]
            variants.add(canonical)
            break
    for placeholder, real_root in _PLACEHOLDER_MAP.items():
        if canonical.startswith(real_root):
            variants.add(placeholder + canonical[len(real_root) :])
    return sorted(variants)


# The ruff tier (F401, F811, …) and the static tier (blanket code PYFLAKES) report the
# SAME pyflakes-class defect under DIFFERENT issue codes — cross-detector dedup below
# only considers codes in this family, so unrelated codes can never over-dedup.
_LINT_FAMILY_RE = re.compile(r"^(?:PYFLAKES|F\d{3})$")


def _has_open_audit_proposal(file_path, issue_code, detail=None):
    """Check if an open proposal already exists for this file + issue code
    (under ANY alias spelling of the path — see _audit_path_variants).

    An exact issue_code match alone minted twin rows when the ruff and static tiers
    each reported the same finding (11235/11259, 2026-08-27 — both reached the owner's
    Approvals tab and one burned a human approval on an already-merged fix). For
    lint-family codes, a second pass compares detector-neutral fingerprints against
    open rows carrying a DIFFERENT code."""
    variants = _audit_path_variants(file_path)
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT id FROM improvement_proposals
            WHERE status NOT IN ('deployed', 'implemented', 'rejected', 'archived', 'failed', 'superseded')
              AND metadata->>'source' = 'code_health_audit'
              AND metadata->>'file_path' = ANY(%s)
              AND metadata->>'issue_code' = %s
            LIMIT 1
            """,
            (variants, issue_code),
        )
        if cur.fetchone() is not None:
            return True

        if not detail or not _LINT_FAMILY_RE.match(issue_code or ""):
            return False

        from services.code_issue_reconciler import finding_fingerprint

        mine = finding_fingerprint(issue_code, detail)
        if not mine:
            return False
        cur.execute(
            """
            SELECT metadata->>'issue_code' AS code, metadata->>'detail' AS detail
            FROM improvement_proposals
            WHERE status NOT IN ('deployed', 'implemented', 'rejected', 'archived', 'failed', 'superseded')
              AND metadata->>'source' = 'code_health_audit'
              AND metadata->>'file_path' = ANY(%s)
              AND metadata->>'issue_code' <> %s
            """,
            (variants, issue_code),
        )
        for row in cur.fetchall():
            if _LINT_FAMILY_RE.match(row["code"] or "") and finding_fingerprint(row["code"], row["detail"]) == mine:
                return True
    return False


def _approval_action_type(severity):
    """Red findings card the OWNER for permission at PROPOSAL time (owner order
    2026-07-11): improvement_approve_red is NOT in the tier-1 auto-approve list,
    so the requested Tier-2 stands and a Telegram approve/deny card is sent.
    Yellow quality findings stay advise-only (auto-approved improvement_approve)."""
    return "improvement_approve_red" if severity == "red" else "improvement_approve"


def _proposal_metadata(issue, module_name, file_path):
    """Build the proposal metadata dict. Optional issue['meta_extra'] keys (e.g.
    scan_tier/tool/verified_by/line from the static-analysis tier) are merged in
    but can never override the core pipeline keys the fix/dedup/reverify paths
    depend on."""
    return {
        **(issue.get("meta_extra") or {}),
        "source": "code_health_audit",
        "file_path": file_path,
        "issue_code": issue["code"],
        "severity_tier": issue["severity"],
        "module_name": module_name,
        "detail": issue.get("detail", ""),
        "auto_generated": True,
    }


def _create_audit_proposal(issue, module_name, file_path):
    """Create an improvement proposal from a single audit finding. Returns proposal_id."""
    severity = issue["severity"]
    issue_code = issue["code"]
    detail = issue.get("detail", "")
    fname = issue.get("file", "")
    config = _TIER_CONFIG[severity]

    title = f"[{config['priority'].upper()}] {issue_code}: {module_name}/{fname}"
    if detail:
        title = f"{title} ({detail})"
    # Truncate title to reasonable length
    title = title[:120]

    description = (
        f"Code Health audit detected a **{severity}** issue in `{file_path}`.\n\n"
        f"**Check:** {issue_code}\n"
        f"**Module:** {module_name}\n"
    )
    if detail:
        description += f"**Detail:** {detail}\n"

    description += (
        f"\n**Severity tier:** {severity} "
        f"({'security — requires immediate attention' if severity == 'red' else 'quality — should be addressed'})\n"
    )

    metadata = json.dumps(_proposal_metadata(issue, module_name, file_path))

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO improvement_proposals
            (title, category, description, code_changes, rationale,
             priority, risk_level, status, metadata, collaboration_enabled)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s::jsonb, false)
            RETURNING id
            """,
            (
                title,
                issue_code.lower(),
                description,
                "",
                f"Auto-detected by Code Health audit of {module_name}",
                config["priority"],
                config["risk_level"],
                metadata,
            ),
        )
        proposal_id = cur.fetchone()["id"]
        logger.info(
            "Created audit proposal #%d for %s %s in %s",
            proposal_id,
            severity,
            issue_code,
            file_path,
        )

    # Route through autonomy approval queue
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from agent_loop import request_approval

        request_approval(
            action_type=_approval_action_type(severity),
            action_data={
                "proposal_id": proposal_id,
                "title": title,
                "file_path": file_path,
                "severity": severity,
                "risk_level": config["risk_level"],
            },
            reason=f"Auto-generated from Code Health audit: {issue_code} in {module_name}",
            requested_by="audit_pipeline",
            priority=config["approval_priority"],
            tier=config["approval_tier"],
        )
    except Exception as approval_err:
        logger.warning(
            "Approval queue submission failed for audit proposal #%d: %s",
            proposal_id,
            approval_err,
        )

    return proposal_id


# Map issue codes to Bridge dispatch capabilities
_ISSUE_CAPABILITY_MAP = {
    # HARDCODED_SECRET / SQL_INJECTION_RISK are security findings whose FIX is
    # mechanical code work (os.getenv() / parameterized queries). Route them to
    # `code_review` (F.O.R.G.E. + P.R.O.B.E., active Engineering) rather than
    # `vulnerability_scan` (only V.I.G.I.L. + S.H.I.E.L.D.) so the self-heal drain
    # doesn't stall when both security agents are busy/resting — the pool of
    # active candidates is wider. Deploy stays human-gated; SECURITY_STATIC
    # (real bandit-confirmed findings) keeps routing to vulnerability_scan below.
    "HARDCODED_SECRET": "code_review",
    "SQL_INJECTION_RISK": "code_review",
    "DIRECT_OLLAMA": "code_review",
    "DIRECT_CLOUD": "code_review",
    "BARE_EXCEPT": "code_review",
    "LARGE_FILE": "code_review",
    "MISSING_INIT": "code",
    # Static-analysis scanner tier (Slice 1, 2026-07-11) — imports/symbols/arity/
    # types route to F.O.R.G.E. (code); bandit-confirmed security to V.I.G.I.L.
    "WRONG_ROOT_IMPORT": "code",
    "WRONG_SUBMODULE_IMPORT": "code",
    "MISSING_SYMBOL": "code",
    "MISSING_METHOD": "code",
    "WRONG_KWARG": "code",
    "ARITY_MISMATCH": "code",
    "TYPE_ERROR": "code",
    "SYNTAX_ERROR": "code",
    "SECURITY_STATIC": "vulnerability_scan",
}

_FIX_PROMPTS = {
    "HARDCODED_SECRET": (
        "Replace the hardcoded secret with an os.getenv() call. "
        "Use a descriptive env var name. Keep all other code unchanged."
    ),
    "SQL_INJECTION_RISK": (
        "Replace f-string or %-formatting in .execute() calls with parameterized queries (%s placeholders). "
        "Keep all other code unchanged."
    ),
    "DIRECT_OLLAMA": (
        "Replace the direct call_ollama() call with Bridge dispatcher: "
        "from bridge_dispatcher import get_dispatcher; get_dispatcher().dispatch(). "
        "Keep all other code unchanged."
    ),
    "DIRECT_CLOUD": (
        "Replace the direct cloud API call with Bridge dispatcher: "
        "from bridge_dispatcher import get_dispatcher; get_dispatcher().dispatch(). "
        "Keep all other code unchanged."
    ),
    "BARE_EXCEPT": (
        "Replace bare 'except:' with 'except Exception:' (or a more specific exception type if obvious). "
        "Keep all other code unchanged."
    ),
    "LARGE_FILE": (
        "Analyze this large file and suggest how to split it into smaller modules. "
        "Identify logical groupings of functions that could become separate files. "
        "Return a plan, not a rewrite."
    ),
    "MISSING_INIT": ("Create an __init__.py that imports and exposes the module's public Blueprint and key functions."),
    # Static-analysis scanner tier (Slice 1, 2026-07-11)
    "WRONG_ROOT_IMPORT": (
        "The import path does not resolve in the runtime. Find the correct module path for "
        "the imported symbols (check tools/, services/, ai_bridge/) and fix ONLY the import "
        "statement. Keep all other code unchanged."
    ),
    "WRONG_SUBMODULE_IMPORT": (
        "The submodule in this import path does not exist (the root package does). Find the "
        "correct submodule path for the imported symbols and fix ONLY the import statement. "
        "Keep all other code unchanged."
    ),
    "MISSING_SYMBOL": (
        "The named symbol is not exported by that module. Locate the correct symbol name, or "
        "the module that actually exports it, and fix the import. Keep all other code unchanged."
    ),
    "MISSING_METHOD": (
        "The method/attribute does not exist on that object. Either call the correct existing "
        "method or add the missing method following the class's conventions. Keep the change minimal."
    ),
    "WRONG_KWARG": (
        "The call passes a keyword argument the function does not accept. Consult the function's "
        "real signature and fix the call site with the correct parameter names. Keep all other "
        "code unchanged."
    ),
    "ARITY_MISMATCH": (
        "The call passes more positional arguments than the function accepts. Consult the real "
        "signature and fix the call site. Keep all other code unchanged."
    ),
    "TYPE_ERROR": (
        "mypy flags a type inconsistency at the flagged line. Fix the value/annotation mismatch "
        "without changing behavior. Keep the change minimal."
    ),
    "SYNTAX_ERROR": ("The file fails to parse. Fix the syntax error at the flagged line only."),
    "SECURITY_STATIC": (
        "Bandit flagged a potential security issue and an agent verified it as real. Apply the "
        "minimal secure fix (parameterize queries, avoid unsafe primitives, validate input). "
        "Keep all other code unchanged."
    ),
}

# Codes whose detail strings carry "(line N)" — the fix prompt excerpts around
# that line instead of sending the first 200 lines (useless for a bug at L4000).
_LINE_EXCERPT_CODES = (
    "SQL_INJECTION_RISK",
    "BARE_EXCEPT",
    "HARDCODED_SECRET",
    "WRONG_ROOT_IMPORT",
    "WRONG_SUBMODULE_IMPORT",
    "MISSING_SYMBOL",
    "MISSING_METHOD",
    "WRONG_KWARG",
    "ARITY_MISMATCH",
    "TYPE_ERROR",
    "SYNTAX_ERROR",
)

# Code Health scanner emits module placeholders that don't match real filesystem paths.
# Map placeholder prefix -> real path root (relative to /mnt/archie_brain).
_PLACEHOLDER_MAP = {
    "[APP_CORE]/": "platform_v2/",
    "[AI_BRIDGE]/": "ai_bridge/",
    "[MIGRATIONS]/": "database/migrations/",
    "standalone_kytran_business_suite/": "kytran-business-suite/",
    "standalone_kytran_system_operations/": "kytran-server-manager/",
    "standalone_kytran_gov_watch/": "kytran-gov-watch/",
    "standalone_archie_comms/": "archie-comms/",
    "standalone_media_hub/": "standalone/media_hub/",
    "standalone_creed_governance/": "kytran-creed/",
    "website_kytranempowerment/": "website/kytranempowerment.com/",
    "website_creed_ai/": "website/creed-ai.org/",
    "website_what_the_fact/": "website/what-the-fact.com/",
}

# Synthetic placeholders that don't represent real files (e.g., routing rules) — skip rather than fail noisily.
_SKIP_PREFIXES = ("[dispatch_routing]/",)


def resolve_proposal_source(file_path):
    """Resolve a code-health proposal's file_path to a real on-disk source.

    Single source of truth for the resolution ``dispatch_proposal_fix`` performs, so the
    archive sweep classifies "fixable" identically to what dispatch actually does.

    Returns (abs_path, display_path, status):
      status 'skip'    -> synthetic non-file label (_SKIP_PREFIXES); abs_path None; display == input
      status 'ok'      -> abs_path is an existing, readable file; display is the substituted path
      status 'missing' -> resolved (or unresolved) but no on-disk file; abs_path None
    """
    if not file_path:
        return (None, file_path, "missing")
    if any(file_path.startswith(p) for p in _SKIP_PREFIXES):
        return (None, file_path, "skip")
    resolved = file_path
    for placeholder, real_root in _PLACEHOLDER_MAP.items():
        if resolved.startswith(placeholder):
            resolved = real_root + resolved[len(placeholder) :]
            break
    # Path-containment (#4979): a corrupt/adversarial file_path must not traverse
    # out of the tree. 'platform_v2/../../etc/x' would otherwise os.path.join into
    # a real file outside the repo → returned 'ok' → base-synced + patched. Reject
    # absolute paths and any '..' component (fail-closed → 'missing').
    if os.path.isabs(resolved) or ".." in resolved.replace("\\", "/").split("/"):
        return (None, resolved, "missing")
    # Try /mnt/archie_brain first (host + container mount), fall back to /app/ (Docker)
    abs_path = os.path.join("/mnt/archie_brain", resolved)
    if not os.path.isfile(abs_path) and resolved.startswith("platform_v2/"):
        abs_path = os.path.join("/app", resolved[len("platform_v2/") :])
    if os.path.isfile(abs_path):
        return (abs_path, resolved, "ok")
    return (None, resolved, "missing")


def _parse_fix_json(text):
    """Extract a {"find","replace"} JSON object from an LLM reply (fence/prose tolerant)."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        parts = s.split("```")
        if len(parts) >= 2:
            s = parts[1]
            if s.lstrip()[:4].lower() == "json":
                s = s.lstrip()[4:]
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b == -1 or b < a:
        return None
    try:
        obj = json.loads(s[a : b + 1])
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _strip_wrapping_fence(block):
    """Strip a markdown code fence that wraps a whole block, e.g. a model that put
    ```python … ``` INSIDE the <<<FIND>>> block (real fix_debug sample #1654). Only
    strips when the block literally starts with ``` (a leading-backtick line is a
    fence, never Python source); a wrong strip only makes the match fail-closed."""
    b = block.strip("\r\n")
    if not b.startswith("```"):
        return block
    lines = b.split("\n")
    lines = lines[1:]  # drop the opening ```lang line
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]  # drop the closing fence line
    return "\n".join(lines)


def _parse_fix_delimited(text):
    """Extract {"find","replace"} from the quote-safe delimiter format:

        <<<FIND>>>
        <code copied verbatim>
        <<<REPLACE>>>
        <corrected code>
        <<<END>>>

    Preferred over JSON because a small model cannot reliably escape code — and
    especially triple-quoted SQL (``\"\"\"SELECT ...\"\"\"``) — inside a JSON string,
    which was the dominant ``unparseable`` failure (KB fix_debug evidence, 2026-07-18).
    Only the format's surrounding newlines are stripped; code indentation is preserved
    (the unique-match + strip fallback in ``_fix_match_candidates`` handles the rest).
    ``<<<END>>>`` is optional. Returns a dict or ``None``.
    """
    if not text or "<<<FIND>>>" not in text or "<<<REPLACE>>>" not in text:
        return None
    s = text
    # Tolerate a stray markdown fence wrapper around the whole block.
    if "```" in s:
        for part in s.split("```"):
            if "<<<FIND>>>" in part and "<<<REPLACE>>>" in part:
                s = part
                break
    try:
        after_find = s.split("<<<FIND>>>", 1)[1]
        find_part, rest = after_find.split("<<<REPLACE>>>", 1)
        replace_part = rest.split("<<<END>>>", 1)[0]
    except (IndexError, ValueError):
        return None
    find = _strip_wrapping_fence(find_part).strip("\r\n")
    replace = _strip_wrapping_fence(replace_part).strip("\r\n")
    if not find:
        return None
    return {"find": find, "replace": replace}


def _parse_fix_response(text):
    """Parse an LLM fix reply. Prefers the quote-safe delimiter format; falls back to
    the legacy JSON format for backward compatibility (and robustness if a model still
    emits JSON)."""
    return _parse_fix_delimited(text) or _parse_fix_json(text)


def _fix_match_candidates(find, replace):
    """Yield (find, replace) candidates from strictest to most whitespace-tolerant.

    The caller applies the unique-match + no-gut guards to EACH candidate, so this
    tolerance never bypasses fail-closed safety — it only recovers a `find` that is
    verbatim except for surrounding whitespace the model added or dropped. Internal
    indentation is deliberately NOT normalized (re-splicing that safely is a
    separate, data-driven change).
    """
    yield find, replace
    trimmed = find.strip()
    if trimmed != find and len(trimmed) >= 4:
        yield trimmed, replace.strip()


def _capture_fix_failure(proposal_id, raw_response, reason):
    """Persist the model's raw reply + attempted ``find`` on a fix-apply failure.

    The real yield fix (more tolerant matching / parsing) is deliberately
    data-driven — but nothing captured WHAT the model returned when it failed, so
    the find_not_located / unparseable patterns were invisible. This records a
    truncated snapshot under ``metadata.fix_debug`` (failure path only, best-effort;
    never blocks dispatch). Changes no matching behavior.
    """
    try:
        from services.time_utils import now_utc

        # Parse with the SAME parser the fix path uses (delimiter-first), so
        # attempted_find populates for delimiter replies too — not just legacy
        # JSON. Was _parse_fix_json → blank attempted_find for every <<<FIND>>>
        # reply, which is now the dominant format (#4989 measure fidelity).
        parsed = _parse_fix_response(raw_response) or {}
        debug = {
            "reason": reason,
            "raw_response": (raw_response or "")[:1500],
            "attempted_find": (parsed.get("find") or "")[:600],
            "captured_at": now_utc().isoformat(),
        }
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE improvement_proposals "
                "SET metadata = metadata || jsonb_build_object('fix_debug', %s::jsonb) "
                "WHERE id = %s",
                (json.dumps(debug), proposal_id),
            )
    except Exception as e:  # diagnostics must never break the pipeline
        logger.warning("fix-failure capture failed for #%s: %s", proposal_id, e)


def _archive_stale_proposal(proposal_id, *, archived_by="stale_filter_nofix", archive_reason="stale:model_nofix"):
    """Archive an unfixable/stale proposal reversibly so the drain stops re-spending
    slots on it. Two callers:
      - NOFIX (default tags): the model judged the source already correct (`<<<NOFIX>>>`).
      - unresolvable source at dispatch (archived_by='scope_filter_unresolvable'):
        the proposal's file_path no longer resolves to a real on-disk file.
    Reversible via the ``archived_by`` tag; a wrong archive self-corrects — a future
    scan re-creates the finding (at the current path)."""
    try:
        from services.time_utils import now_utc

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE improvement_proposals SET status='archived', " "metadata = metadata || %s::jsonb WHERE id = %s",
                (
                    json.dumps(
                        {
                            "archive_reason": archive_reason,
                            "archived_by": archived_by,
                            "archived_at": now_utc().isoformat(),
                        }
                    ),
                    proposal_id,
                ),
            )
    except Exception as e:
        logger.warning("stale-archive failed for #%s: %s", proposal_id, e)


def _indent_tolerant_match(source, find, replace):
    """Last-resort locator for a multi-line ``find`` whose per-line indentation the
    model reproduced imperfectly (the dominant live ``find_not_located`` cause —
    fix_debug samples #1655/#1805, multi-line SQL/blocks).

    Matches on a UNIQUE run of source lines compared by ``.strip()`` (ignoring only
    per-line leading/trailing whitespace, NOT line content or order), reconstructs
    the EXACT source block (source's real indentation), and reindents ``replace`` by
    the single source-vs-model indent delta measured at the first non-blank line.

    Fail-closed — returns ``(orig_block, new_block)`` or ``None``. Bails on: <2 lines,
    0 or >1 line-run matches, a reconstructed block that isn't uniquely present as
    text, tab indentation (won't guess width), or a dedent deeper than a replace
    line's own leading whitespace. A wrong reindent can't ship: the sandbox gate
    re-runs QA and rejects a broken patch.
    """
    find_lines = find.split("\n")
    if len(find_lines) < 2:
        return None  # single lines are handled by _fix_match_candidates
    keys = [ln.strip() for ln in find_lines]
    src_lines = source.split("\n")
    n = len(find_lines)
    hits = [i for i in range(len(src_lines) - n + 1) if [s.strip() for s in src_lines[i : i + n]] == keys]
    if len(hits) != 1:
        return None
    i = hits[0]
    orig_block = "\n".join(src_lines[i : i + n])
    if source.count(orig_block) != 1:
        return None  # reconstructed block must map to exactly one place in the text

    def _lead(s):
        return s[: len(s) - len(s.lstrip())]

    fi = next((k for k in range(n) if find_lines[k].strip()), None)
    if fi is None:
        return None
    src_indent = _lead(src_lines[i + fi])
    find_indent = _lead(find_lines[fi])
    if "\t" in src_indent or "\t" in find_indent:
        return None  # tab widths are ambiguous — don't guess
    delta = len(src_indent) - len(find_indent)
    new_lines = []
    for rl in replace.split("\n"):
        if not rl.strip():
            new_lines.append(rl)  # preserve blank lines verbatim
            continue
        if delta >= 0:
            if delta > 0 and "\t" in _lead(rl):
                return None  # prepending spaces before a tab = mixed indentation; don't guess
            new_lines.append(" " * delta + rl)
        else:
            lead = _lead(rl)
            if "\t" in lead or len(lead) < -delta:
                return None  # can't safely dedent this line
            new_lines.append(rl[-delta:])
    return orig_block, "\n".join(new_lines)


def _apply_targeted_fix(source_content, model_response):
    """Apply an LLM search/replace fix to ``source_content``.

    Returns ``(fixed_content, "ok")`` on success, else ``(None, reason)``.

    The old flow diffed the FULL source against a short model reply, so any file
    over ~200 lines produced a whole-file-deletion diff. Here the model returns a
    minimal ``{"find","replace"}`` and we splice it into the full source — the
    resulting diff is therefore always a correct, minimal patch, or nothing at
    all (fail-closed). ``find`` must be an exact, unique substring, and the result
    may never gut the file.
    """
    if "<<<NOFIX>>>" in (model_response or ""):
        return None, "nofix"
    data = _parse_fix_response(model_response)
    if not data:
        return None, "unparseable"
    find = data.get("find") or ""
    replace = data.get("replace")
    if not find or not isinstance(replace, str):
        return None, "missing_find_or_replace"
    # Locate the find: exact first, then a whitespace-trimmed fallback for when the
    # model wrapped an otherwise-verbatim snippet in surrounding whitespace. Every
    # candidate must still occur EXACTLY ONCE — tolerance never bypasses fail-closed.
    matched = None
    for cand_find, cand_replace in _fix_match_candidates(find, replace):
        occ = source_content.count(cand_find)
        if occ == 1:
            matched = (cand_find, cand_replace)
            break
        if occ > 1:
            return None, "find_ambiguous"
    if matched is None:
        # Last resort: the model reproduced the snippet with imperfect internal
        # indentation — locate it by a unique strip-compared line-run and reindent
        # the replacement (fail-closed; #387 yield lever).
        matched = _indent_tolerant_match(source_content, find, replace)
    if matched is None:
        return None, "find_not_located"
    find, replace = matched
    fixed = source_content.replace(find, replace, 1)
    if fixed == source_content:
        return None, "no_change"
    # A targeted fix must never gut the file (the old whole-file-deletion bug).
    if len(fixed) < len(source_content) * 0.5:
        return None, "destructive_shrink"
    return fixed, "ok"


def _finalize_diff_lines(diff_lines):
    r"""Insert git's ``\ No newline at end of file`` markers, which difflib omits.

    ``difflib.unified_diff`` never emits the no-newline indicator, so a hunk that
    touches a last line lacking a trailing newline yields a patch git rejects as a
    "corrupt patch" — the un-terminated ``-``/``+`` line runs into the next one.
    This walks hunk bodies and, for any ``' '``/``'-'``/``'+'`` line without a
    trailing newline, terminates the line and appends the marker. Scoped to lines
    AFTER the first ``@@`` so the ``--- a/`` / ``+++ b/`` file headers are never
    mis-touched, even when a content line itself begins with ``--`` / ``++``. (#4978)
    """
    out = []
    in_hunk = False
    for ln in diff_lines:
        if ln.startswith("@@"):
            in_hunk = True
            out.append(ln)
            continue
        if in_hunk and ln[:1] in (" ", "-", "+") and not ln.endswith("\n"):
            out.append(ln + "\n")
            out.append("\\ No newline at end of file\n")
        else:
            out.append(ln)
    return out


def _build_fix_diff(old_content, new_content, repo_rel_path):
    """Unified diff whose headers carry the REPO-RELATIVE path (a/<rel>, b/<rel>).

    git apply (run from the /mnt/archie_sandbox worktree root) needs the full
    repo-relative path to locate the file — a basename cannot be applied. Returns
    (diff_text, stats). Isolated + pure so the header contract is unit-testable.

    Built directly via difflib (NOT ai_bridge.code_diff_engine.CodeDiffEngine,
    whose lineterm="" output collapses the ---/+++/@@ headers onto ONE line —
    e.g. "--- a/x.py+++ b/x.py@@ ..." — which git apply rejects and the sandbox
    gate's line-start "+++ b/" parser can't locate ["diff has no target files"]).
    CodeDiffEngine is a shared display component with other consumers and is
    intentionally left untouched; this function generates its own diff instead.
    """
    diff_lines = list(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{repo_rel_path}",
            tofile=f"b/{repo_rel_path}",
            lineterm="\n",
        )
    )
    # difflib omits git's "\ No newline at end of file" markers → git apply rejects
    # patches touching a last line without a trailing newline. Re-insert them. (#4978)
    diff_lines = _finalize_diff_lines(diff_lines)
    diff_text = "".join(diff_lines)
    added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))
    stats = {"added": added, "removed": removed, "changed": 0, "total": added + removed}
    return diff_text, stats


def dispatch_proposal_fix(proposal_id):
    """Dispatch a single audit proposal to a Bridge agent for AI-powered fix generation.

    Reads the source file, sends it to the appropriate department agent via Bridge,
    and stores the generated diff in the proposal's code_changes field.

    Args:
        proposal_id: The improvement_proposals.id to process

    Returns:
        {"success": bool, "proposal_id": int, "agent": str, "diff_lines": int}
        or {"success": False, "error": str}
    """
    from services.work_tracking_service import (
        create_work_session,
        complete_work_session,
        fail_work_session,
    )

    session_id = None

    # Load proposal + metadata
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, title, description, metadata, status
               FROM improvement_proposals WHERE id = %s""",
            (proposal_id,),
        )
        proposal = cur.fetchone()

    if not proposal:
        return {"success": False, "error": f"Proposal #{proposal_id} not found"}

    if proposal["status"] not in ("pending", "approved", "fix_requested"):
        return {
            "success": False,
            "error": f"Proposal #{proposal_id} status is '{proposal['status']}', expected pending/approved/fix_requested",
        }

    meta = proposal["metadata"] if isinstance(proposal["metadata"], dict) else json.loads(proposal["metadata"] or "{}")
    if meta.get("source") != "code_health_audit":
        return {"success": False, "error": f"Proposal #{proposal_id} is not from code_health_audit"}

    file_path = meta.get("file_path", "")
    issue_code = meta.get("issue_code", "")
    module_name = meta.get("module_name", "")

    # Create work session for tracking
    try:
        session_id = create_work_session(
            agent_id=None,
            department="Engineering & Technology",
            session_type="fix",
            title=f"Fix {issue_code} in {file_path}",
            metadata={"proposal_id": proposal_id, "issue_code": issue_code, "module": module_name},
        )
    except Exception as ws_err:
        logger.warning("Work session creation failed (non-blocking): %s", ws_err)

    # Read source file — resolve module placeholders to a real on-disk path.
    abs_path, file_path, _resolve_status = resolve_proposal_source(file_path)
    if _resolve_status == "skip":
        # Synthetic/placeholder target (routing rule, etc.) — no real file to fix.
        # Self-clean: archive rather than leave it approved+attempted forever (autonomy).
        _archive_stale_proposal(
            proposal_id, archived_by="scope_filter_unresolvable", archive_reason="not_a_file:routing_label"
        )
        if session_id:
            fail_work_session(session_id, error_msg=f"Synthetic placeholder, no file to fix: {file_path}")
        return {"success": False, "error": f"Synthetic placeholder, no file to fix: {file_path}", "archived": True}
    if _resolve_status != "ok":
        # File path no longer resolves (relocated/deleted). Self-clean: archive it — a
        # future scan re-creates the finding at the current path if still real.
        _archive_stale_proposal(
            proposal_id, archived_by="scope_filter_unresolvable", archive_reason="source_missing:at_dispatch"
        )
        if session_id:
            fail_work_session(session_id, error_msg=f"Source file not found: {file_path}")
        return {"success": False, "error": f"Source file not found: {file_path}", "archived": True}

    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            source_content = f.read()
    except Exception as e:
        if session_id:
            fail_work_session(session_id, error_msg=f"Failed to read {file_path}: {e}")
        return {"success": False, "error": f"Failed to read {file_path}: {e}"}

    # Determine capability and build prompt
    capability = _ISSUE_CAPABILITY_MAP.get(issue_code, "code_review")
    fix_instruction = _FIX_PROMPTS.get(issue_code, f"Fix the {issue_code} issue in this file.")

    # Truncate source to avoid overwhelming the model
    # For targeted fixes (SQL injection, bare except), extract relevant lines
    # For analysis (large file), send first 150 lines
    source_lines = source_content.split("\n")
    detail_str = meta.get("detail", "")
    if issue_code in _LINE_EXCERPT_CODES and "line" in detail_str:
        try:
            line_num = int("".join(c for c in detail_str.split("line")[-1].strip() if c.isdigit())[:5])
            start_line = max(0, line_num - 20)
            end_line = min(len(source_lines), line_num + 30)
            excerpt = "\n".join(source_lines[start_line:end_line])
            source_excerpt = (
                f"(lines {start_line+1}-{end_line} of {len(source_lines)}; "
                f"copy `find` verbatim, no line numbers)\n{excerpt}"
            )
        except (ValueError, IndexError):
            source_excerpt = "\n".join(source_lines[:200])
    elif issue_code == "LARGE_FILE":
        source_excerpt = f"(file has {len(source_lines)} lines, showing first 100)\n" + "\n".join(source_lines[:100])
    else:
        source_excerpt = "\n".join(source_lines[:200])

    prompt = (
        f"Fix this Code Health finding in the A.R.C.H.I.E. platform.\n\n"
        f"**Issue:** {issue_code}\n"
        f"**File:** {file_path}\n"
        f"**Module:** {module_name}\n"
        f"**Detail:** {meta.get('detail', '')}\n\n"
        f"**Instructions:** {fix_instruction}\n\n"
        "Return ONLY the SMALLEST change that fixes the issue, in EXACTLY this format "
        "(no JSON, no code fences, no commentary):\n"
        "<<<FIND>>>\n"
        "<paste the exact code to replace, copied VERBATIM from the source below>\n"
        "<<<REPLACE>>>\n"
        "<the corrected code>\n"
        "<<<END>>>\n\n"
        "Rules: the FIND block is the code AS IT CURRENTLY EXISTS in the source (the "
        "problem code) — copy it character-for-character INCLUDING indentation, and include "
        "a few surrounding lines so it appears exactly once. Do NOT correct, reformat, or "
        "re-indent the code inside the FIND block — put the fix ONLY in the REPLACE block. "
        "No line numbers. Do NOT escape quotes and do NOT use JSON — paste the raw code "
        "between the markers (triple-quoted strings and quotes are fine as-is). Change as "
        "little as possible; never rewrite the whole file.\n"
        "If the source code is ALREADY correct and needs no change to fix this issue, "
        "return EXACTLY this and nothing else:\n<<<NOFIX>>>\n\n"
        f"--- SOURCE ---\n{source_excerpt}"
    )

    # C.R.E.E.D. Gate 1a — self-governance check BEFORE inference (no wasted LLM
    # call on a denied self-modification target). Agent-independent, target-based.
    predispatch = creed_gate_pre_dispatch(proposal_id)
    if not predispatch["approved"]:
        logger.info(
            "C.R.E.E.D. pre-dispatch gate denied proposal #%d: %s",
            proposal_id,
            predispatch["reason"],
        )
        if session_id:
            fail_work_session(session_id, error_msg=f"C.R.E.E.D. pre-dispatch denied: {predispatch['reason']}")
        return {"success": False, "error": f"C.R.E.E.D. pre-dispatch denied: {predispatch['reason']}"}

    # Dispatch via DHQ — canonical dispatcher (ADR-013 compliant, routes to cluster)
    try:
        _ensure_import_paths()
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        result = dispatcher.request_work(
            capability=capability,
            prompt=prompt,
            module_id="audit_pipeline",
            system_prompt=(
                "You are a precise code-repair agent. Fix ONLY the specific issue. "
                'Reply with STRICT JSON only — a single {"find": ..., "replace": ...} '
                "object where `find` is copied verbatim from the source. No prose, no "
                "markdown fences, no explanation."
            ),
            priority="high" if meta.get("severity_tier") == "red" else "normal",
        )
    except Exception as e:
        logger.error("Bridge dispatch failed for proposal #%d: %s", proposal_id, e)
        if session_id:
            fail_work_session(session_id, error_msg=f"Bridge dispatch failed: {e}")
        return {"success": False, "error": f"Bridge dispatch failed: {e}"}

    if result is not None and getattr(result, "queued", False):
        # Cold-load queued — NOT a failure. Defer so the next batch retries once the
        # model is warm; never park a queued dispatch (KB #276153 masking pattern).
        logger.info("Proposal #%d dispatch queued (cold-load) — deferring", proposal_id)
        if session_id:
            fail_work_session(session_id, error_msg="queued_cold_load")
        return {"success": False, "queued": True, "error": "queued_cold_load"}

    if not result or not getattr(result, "response", None):
        logger.warning("Bridge returned empty response for proposal #%d", proposal_id)
        if session_id:
            fail_work_session(session_id, error_msg="Bridge returned empty response")
        return {"success": False, "error": "Bridge returned empty response"}

    raw_response = result.response.strip()
    agent_name = getattr(result, "agent_name", "unknown")

    # C.R.E.E.D. Gate 1: Can this agent fix this code?
    try:
        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT id FROM agents WHERE name = %s OR display_name = %s LIMIT 1",
                (agent_name, agent_name),
            )
            agent_row = cur.fetchone()

        if agent_row:
            gate1 = creed_gate_pre_fix(proposal_id, agent_row["id"])
            if not gate1["approved"]:
                logger.warning(
                    "C.R.E.E.D. Gate 1 denied proposal #%d agent %s: %s",
                    proposal_id,
                    agent_name,
                    gate1["reason"],
                )
                if session_id:
                    fail_work_session(session_id, error_msg=f"C.R.E.E.D. Gate 1 denied: {gate1['reason']}")
                return {
                    "success": False,
                    "error": f"C.R.E.E.D. Gate 1 denied: {gate1['reason']}",
                }
        else:
            logger.info(
                "C.R.E.E.D. Gate 1 skipped — agent '%s' not found in agents table",
                agent_name,
            )
    except Exception as gate_err:
        logger.warning("C.R.E.E.D. Gate 1 check failed (non-blocking): %s", gate_err)

    # Apply the model's targeted {find, replace} to the FULL source (fail-closed).
    # Never store a diff computed against a short/plan reply — that was the
    # whole-file-deletion bug. On any apply failure the proposal stays eligible.
    fixed_content, apply_reason = _apply_targeted_fix(source_content, raw_response)
    if apply_reason == "nofix":
        # The model judged the source already correct for this finding — archive it as
        # stale (reversible) rather than burn future drain slots on a non-fixable finding.
        _archive_stale_proposal(proposal_id)
        logger.info("Proposal #%d archived — model reports NOFIX (already resolved)", proposal_id)
        if session_id:
            complete_work_session(session_id, jobs_completed=0)
        return {"success": False, "error": "nofix:archived_stale", "stale": True}
    if fixed_content is None:
        logger.warning("Proposal #%d fix not applied (%s)", proposal_id, apply_reason)
        _capture_fix_failure(proposal_id, raw_response, apply_reason)
        if session_id:
            fail_work_session(session_id, error_msg=f"fix_apply:{apply_reason}")
        return {"success": False, "error": f"fix_apply:{apply_reason}"}

    # Generate a git-appliable diff (repo-relative header — file_path was resolved
    # to an 'ok' repo-relative path by resolve_proposal_source above).
    try:
        diff_text, diff_stats = _build_fix_diff(source_content, fixed_content, file_path)
    except Exception as e:
        logger.warning("Diff generation failed for proposal #%d: %s", proposal_id, e)
        diff_text = f"--- Fix generated by {agent_name} ---\n(diff generation failed: {e})"
        diff_stats = {}

    # Update proposal with diff and mark ready for review
    with get_db_cursor(commit=True) as (conn, cur):
        updated_meta = {**meta, "agent_name": agent_name, "diff_stats": diff_stats}
        cur.execute(
            """UPDATE improvement_proposals
               SET code_changes = %s, status = 'ready_for_review',
                   metadata = %s::jsonb
               WHERE id = %s""",
            (diff_text, json.dumps(updated_meta), proposal_id),
        )

    logger.info(
        "Proposal #%d fix generated by %s — %d lines added, %d removed",
        proposal_id,
        agent_name,
        diff_stats.get("added", 0),
        diff_stats.get("removed", 0),
    )

    if session_id:
        complete_work_session(session_id, jobs_completed=1)

    return {
        "success": True,
        "proposal_id": proposal_id,
        "agent": agent_name,
        "diff_lines": diff_stats.get("added", 0) + diff_stats.get("removed", 0),
    }


# Issue classes the auto-fix drain must NOT attempt. SQL_INJECTION_RISK over-flags
# already-parameterized queries (`cur.execute(q, params)` is the SAFE pattern) — the
# 7B fix-gen then produces no-op comma tweaks, semantically-identical f-string→.format
# rewrites, or BREAKING f-string-prefix removals (verified 2026-07-19). LARGE_FILE is a
# refactor task, not a find/replace fix. Both stay in the backlog as status='approved'
# (visible in Repair Bay for human/planned review) instead of burning drain slots on
# garbage/impossible fixes. See cont-182 self-heal class-scoping.
_AUTO_FIX_EXCLUDED_ISSUE_CODES = ("SQL_INJECTION_RISK", "LARGE_FILE")

# Mechanical, high-yield, safe-to-auto-fix classes — drained FIRST so the loop ships
# real fixes fast (unused imports/vars, useless f-strings, wrong import paths, missing
# symbols, bare excepts). find/replace matching is reliable on these.
_AUTO_FIX_PRIORITY_ISSUE_CODES = (
    "F401",
    "F841",
    "F541",
    "PYFLAKES",
    "WRONG_SUBMODULE_IMPORT",
    "WRONG_ROOT_IMPORT",
    "MISSING_SYMBOL",
    "F821",
    "BARE_EXCEPT",
)


def dispatch_audit_proposals(limit=20):
    """Batch-dispatch pending audit proposals to Bridge agents for fix generation.

    Finds pending proposals sourced from code_health_audit and dispatches each one.
    Critical proposals are processed first, then the mechanical high-yield classes
    (_AUTO_FIX_PRIORITY_ISSUE_CODES). Classes in _AUTO_FIX_EXCLUDED_ISSUE_CODES are
    never auto-fixed (left approved for human review).

    Args:
        limit: Max proposals to process in one batch

    Returns:
        {"dispatched": int, "failed": int, "skipped": int}
    """
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, metadata FROM improvement_proposals
               WHERE status IN ('pending', 'approved', 'fix_requested')
                 AND metadata->>'source' = 'code_health_audit'
                 AND (COALESCE(metadata->>'severity_tier', 'yellow') <> 'red'
                      OR status IN ('approved', 'fix_requested'))
                 AND (metadata->>'dispatch_attempted') IS NULL
                 AND COALESCE(metadata->>'issue_code', '') <> ALL(%s)
               ORDER BY
                 CASE WHEN priority = 'critical' THEN 0 ELSE 1 END,
                 CASE WHEN COALESCE(metadata->>'issue_code', '') = ANY(%s) THEN 0 ELSE 1 END,
                 proposed_at ASC
               LIMIT %s""",
            (list(_AUTO_FIX_EXCLUDED_ISSUE_CODES), list(_AUTO_FIX_PRIORITY_ISSUE_CODES), limit),
        )
        proposals = cur.fetchall()

    if not proposals:
        logger.info("Audit dispatch: no pending proposals to process")
        return {"dispatched": 0, "failed": 0, "skipped": 0}

    dispatched = 0
    failed = 0
    deferred = 0

    for row in proposals:
        proposal_id = row["id"]
        try:
            result = dispatch_proposal_fix(proposal_id)
            if result.get("success"):
                dispatched += 1
            elif result.get("queued"):
                # Deferred (cold-load): leave eligible for the next batch, never park.
                deferred += 1
                logger.info("Proposal #%d deferred (queued cold-load)", proposal_id)
            else:
                error_msg = result.get("error", "")
                if _is_transient_dispatch_error(error_msg):
                    # Transient (agent resting / model busy): retry, don't park —
                    # but cap retries so a chronically-resting agent's proposal
                    # can't block the oldest-first batch head forever.
                    defer_n = _record_transient_defer(proposal_id, error_msg)
                    if defer_n > _MAX_TRANSIENT_DEFERS:
                        failed += 1
                        logger.warning(
                            "Proposal #%d exceeded %d transient defers — marking attempted",
                            proposal_id,
                            _MAX_TRANSIENT_DEFERS,
                        )
                        _mark_dispatch_attempted(proposal_id, f"max_transient_defers:{error_msg[:120]}")
                    else:
                        deferred += 1
                        logger.info(
                            "Proposal #%d deferred (transient x%d): %s",
                            proposal_id,
                            defer_n,
                            error_msg[:80],
                        )
                else:
                    failed += 1
                    logger.warning(
                        "Proposal #%d dispatch failed (permanent): %s",
                        proposal_id,
                        error_msg,
                    )
                    # Mark permanent failures attempted to avoid retry loops
                    _mark_dispatch_attempted(proposal_id, error_msg)
        except Exception as e:
            failed += 1
            logger.error("Proposal #%d dispatch error: %s", proposal_id, e)
            _mark_dispatch_attempted(proposal_id, str(e))

    logger.info(
        "Audit dispatch batch: %d dispatched, %d deferred, %d failed out of %d",
        dispatched,
        deferred,
        failed,
        len(proposals),
    )

    return {"dispatched": dispatched, "failed": failed, "deferred": deferred, "skipped": 0}


def verify_fix_deployment(module_name, proposal_id, pre_issue_count):
    """Re-audit a module after a fix is deployed to verify it improved.

    Compares before/after issue counts. Logs result to governance_audit_log.

    Args:
        module_name: Module that was fixed
        proposal_id: The proposal that was deployed
        pre_issue_count: Issue count before the fix

    Returns:
        {"verified": bool, "pre_count": int, "post_count": int, "delta": int}
    """
    # Fresh audit of the module
    try:
        sys.path.insert(0, "/mnt/archie_brain/platform_v2")
        from services.code_metrics_service import audit_single_module

        _issues_found, _notes, _status, issues_list, *_ = audit_single_module(module_name)
    except Exception as e:
        logger.error("verify_fix_deployment: re-audit of %s failed: %s", module_name, e)
        return {"verified": False, "pre_count": pre_issue_count, "post_count": -1, "delta": 0}

    post_count = len(issues_list)
    delta = pre_issue_count - post_count
    verified = post_count < pre_issue_count

    # Log to governance_audit_log
    if verified:
        event_type = "repair_fix_verified"
        outcome = "success"
        reason = (
            f"Module '{module_name}' improved: {pre_issue_count} → {post_count} issues "
            f"(delta={delta}) after proposal #{proposal_id}"
        )
    else:
        event_type = "repair_fix_regression"
        outcome = "regression"
        reason = (
            f"Module '{module_name}' did NOT improve: {pre_issue_count} → {post_count} issues "
            f"(delta={delta}) after proposal #{proposal_id}"
        )

    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO governance_audit_log
                   (event_type, event_category, action, outcome, reason, timestamp)
                   VALUES (%s, 'repair_pipeline', 'verify_fix', %s, %s, NOW())""",
                (event_type, outcome, reason[:500]),
            )
    except Exception as log_err:
        logger.warning("Failed to log verify_fix_deployment event: %s", log_err)

    # Update proposal status based on verification result
    new_status = "deployed" if verified else "regression"
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE improvement_proposals SET status = %s WHERE id = %s",
                (new_status, proposal_id),
            )
    except Exception as update_err:
        logger.warning(
            "Failed to update proposal #%d status to '%s': %s",
            proposal_id,
            new_status,
            update_err,
        )

    logger.info(
        "verify_fix_deployment: module=%s proposal=#%d verified=%s (%d → %d, delta=%d)",
        module_name,
        proposal_id,
        verified,
        pre_issue_count,
        post_count,
        delta,
    )

    return {"verified": verified, "pre_count": pre_issue_count, "post_count": post_count, "delta": delta}


def _mark_dispatch_attempted(proposal_id, error_msg):
    """Mark a proposal as dispatch-attempted to prevent retry loops.

    Also stamps ``dispatch_attempted_at`` (UTC ISO) — this is the single
    choke-point every attempt outcome routes through, so the self-heal drain
    measure (#4989) gets a clean attempts/day + yield/day instead of coarse
    count-deltas. Storage is UTC per the timezone rule; display converts at the
    edge.
    """
    from services.time_utils import now_utc

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE improvement_proposals
               SET metadata = metadata || %s::jsonb
               WHERE id = %s""",
            (
                json.dumps(
                    {
                        "dispatch_attempted": True,
                        "dispatch_attempted_at": now_utc().isoformat(),
                        "dispatch_error": error_msg[:200],
                    }
                ),
                proposal_id,
            ),
        )


def _archive_reason_for(file_path, status):
    """Map an unresolvable proposal to a stable archive_reason."""
    if status == "skip":
        return "not_a_file:routing_label"
    if file_path.startswith("standalone_"):
        return "out_of_scope:standalone"
    return "source_missing:relocated"


def archive_unfixable_audit_proposals(dry_run=False):
    """Idempotent, reversible sweep: archive any approved code-health proposal whose
    file_path does not resolve to a real on-disk file, so the drain never spends a slot
    on an unfixable target. Covers BOTH undispatched proposals AND ones already attempted
    that failed with 'Source file not found' / 'Synthetic placeholder' (those linger as
    approved+dispatch_attempted otherwise — the drain won't re-attempt them but they clog
    the backlog + yield stats). Only touches status='approved' (idempotent). Every archived
    row is tagged archived_by='scope_filter_4940' for one-statement rollback.
    """
    from services.time_utils import now_utc

    by_reason = {}
    scanned = archived = kept = 0
    with get_db_cursor(commit=not dry_run) as (conn, cur):
        cur.execute(
            """SELECT id, metadata->>'file_path' AS file_path
               FROM improvement_proposals
               WHERE metadata->>'source' = 'code_health_audit'
                 AND status = 'approved'"""
        )
        rows = cur.fetchall()
        for row in rows:
            scanned += 1
            fp = row["file_path"] or ""
            _abs, _display, status = resolve_proposal_source(fp)
            if status == "ok":
                kept += 1
                continue
            reason = _archive_reason_for(fp, status)
            by_reason[reason] = by_reason.get(reason, 0) + 1
            archived += 1
            if not dry_run:
                cur.execute(
                    """UPDATE improvement_proposals
                       SET status = 'archived',
                           metadata = metadata || %s::jsonb
                       WHERE id = %s""",
                    (
                        json.dumps(
                            {
                                "archive_reason": reason,
                                "archived_at": now_utc().isoformat(),
                                "archived_by": "scope_filter_4940",
                            }
                        ),
                        row["id"],
                    ),
                )
    return {"scanned": scanned, "archived": archived, "kept": kept, "by_reason": by_reason}


# Transient dispatch failures resolve on their own — the assigned agent was resting
# (C.R.E.E.D. welfare gate: shift_state winding_down/cooldown) or the model returned
# nothing (cold-load / Ollama saturation / timeout). These MUST be RETRIED, not marked
# permanently attempted, or the self-heal backlog silently dies (~0.35% yield bug,
# 2026-07-16). Permanent failures (file-not-found, fix_apply rejects, synthetic
# placeholders) stay marked-attempted so they don't loop forever.
_TRANSIENT_DISPATCH_MARKERS = (
    "shift_state",  # welfare gate — agent winding_down / cooldown / off_duty
    "empty response",  # bridge/model returned nothing (cold-load / saturation)
    "queued",  # cold-load queue
    "cold_load",
    "cold load",
    "timeout",
    "did not respond",
    "reaped",
    # Environment, not verdict: the dispatcher chain does `from db import ...`
    # (resolved from the ai_bridge package dir), so a process that never ran the
    # app boot path raises ModuleNotFoundError instantly. On 2026-07-20 that
    # parked 18 unrelated proposals in 0.8s — an import failure recorded as a
    # permanent judgement on the proposal. Retry; the guard in
    # dispatch_proposal_fix now prevents it, this is the belt to that suspenders.
    "no module named",
    "modulenotfounderror",
    "importerror",
)

# Cap retries so a proposal whose agent is chronically resting cannot block the
# oldest-first batch head forever (head-of-line starvation of newer proposals).
_MAX_TRANSIENT_DEFERS = 30


def _is_transient_dispatch_error(error_msg):
    """True when a fix dispatch failed for a self-resolving reason (agent resting /
    model busy) that should be RETRIED rather than marked permanently attempted."""
    if not error_msg:
        return False
    low = str(error_msg).lower()
    return any(m in low for m in _TRANSIENT_DISPATCH_MARKERS)


def _is_legacy_blob(code_changes):
    """True when a ready_for_review diff is NOT git-appliable (pre-format).

    Modern fix-gen (Task 1) emits repo-relative headers (--- a/platform_v2/... or
    --- a/ai_bridge/...). Legacy proposals carry basename headers or JSON full-file
    blobs → they can never git apply and must be archived + regenerated.
    """
    if not isinstance(code_changes, str) or not code_changes.strip():
        return True
    return not ("--- a/platform_v2/" in code_changes or "--- a/ai_bridge/" in code_changes)


def archive_legacy_diff_proposals(dry_run=False):
    """Reversibly archive ready_for_review code_health_audit proposals whose diff
    is legacy/un-appliable. Reversible via metadata.archived_by='gate_fix_legacy_blob'.
    """
    from services.time_utils import now_utc

    matched, archived, ids = 0, 0, []
    with get_db_cursor(commit=not dry_run) as (conn, cur):
        cur.execute(
            """SELECT id, code_changes FROM improvement_proposals
               WHERE status = 'ready_for_review' AND metadata->>'source' = 'code_health_audit'"""
        )
        rows = cur.fetchall()
        for row in rows:
            if not _is_legacy_blob(row["code_changes"]):
                continue
            matched += 1
            ids.append(row["id"])
            if dry_run:
                continue
            cur.execute(
                """UPDATE improvement_proposals
                   SET status = 'archived',
                       metadata = jsonb_set(
                         jsonb_set(COALESCE(metadata, '{}'::jsonb),
                                   '{archived_by}', '"gate_fix_legacy_blob"'),
                         '{archived_at}', to_jsonb(%s::text))
                   WHERE id = %s""",
                (now_utc().isoformat(), row["id"]),
            )
            archived += 1
    return {"matched": matched, "archived": archived, "ids": ids}


def _record_transient_defer(proposal_id, error_msg):
    """Bump the transient-defer counter WITHOUT setting dispatch_attempted, so the
    proposal stays eligible for retry. Returns the new defer count."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE improvement_proposals
               SET metadata = metadata || jsonb_build_object(
                     'defer_count', COALESCE((metadata->>'defer_count')::int, 0) + 1,
                     'last_defer_error', %s)
               WHERE id = %s
               RETURNING (metadata->>'defer_count')::int AS defer_count""",
            (str(error_msg)[:200], proposal_id),
        )
        row = cur.fetchone()
    return (row["defer_count"] if row else 1) or 1
