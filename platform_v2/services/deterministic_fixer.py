"""Deterministic fixes for mechanical pyflakes findings (#4989 drain yield).

WHY THIS EXISTS
The Code-Health drain asks a 7B model to emit FIND/REPLACE text for fixes that are
single-line and mechanical. Measured 2026-07-20, every attempt that day failed:

    07-20 08:27  F401        -> find_not_located
    07-20 03:38  BARE_EXCEPT -> find_not_located
    07-20 03:38  BARE_EXCEPT -> no_change
    07-20 03:37  WRONG_KWARG -> find_ambiguous (x2)

Nothing has reached ready_for_review since 07-19 11:30. The dominant failure is
`find_not_located`: the model's FIND string does not match the file. But look at what these
fixes actually require —

    "'datetime.datetime' imported but unused (line 10)"    -> delete that import line
    "f-string is missing placeholders (line 410)"          -> drop the f prefix

— there is nothing for a language model to decide. This module performs those edits directly
and verifies them with pyflakes, taking the LLM out of the loop entirely.

SCOPE — deliberately the two provably-safe classes only (measured pool of 273):
    unused import on a SINGLE-name line   124   -> delete the line
    f-string missing placeholders          11   -> drop the f prefix

EXPLICITLY EXCLUDED, and these exclusions are the point:
  * __init__.py re-exports (30) — pyflakes flags deliberate re-exports; deleting them breaks
    the public API of a package.
  * multi-name imports (79) — `from x import a, b` needs an edit WITHIN the line; a different
    and more error-prone operation.
  * unused locals (29) — `y = do_thing()` may exist for its SIDE EFFECT. Deleting the
    assignment silently removes the call. Not worth the risk for 29 findings.

EVERY fix is verified before it is offered:
    1. the ORIGINAL finding must be gone from pyflakes output
    2. NO NEW pyflakes finding may appear (catches a delete that broke something)
    3. the file must still parse
Any failure -> the proposal is left untouched. Deploy remains human-gated: a successful fix
lands as `ready_for_review` with a unified diff for review in Repair Bay's Repairs tab.
Nothing here writes to a source file on disk.
"""

import ast
import io
import logging
import re

from database import get_db_cursor

logger = logging.getLogger(__name__)

# "'datetime.datetime' imported but unused" / "`os` imported but unused"
_UNUSED_IMPORT_RE = re.compile(r"[`'\"]([\w.]+)[`'\"]\s+imported but unused", re.IGNORECASE)
_FSTRING_RE = re.compile(r"f-string is missing placeholders", re.IGNORECASE)
_TRAILING_LINE_RE = re.compile(r"\s*\(line \d+\)\s*$")

FIX_KINDS = ("unused_import_single", "fstring_no_placeholder")


def _pyflakes_lines(text: str):
    """(messages, ok). ok is False when pyflakes is unavailable or the source won't parse."""
    try:
        from pyflakes.api import check
        from pyflakes.reporter import Reporter
    except ImportError:
        return [], False
    out, err = io.StringIO(), io.StringIO()
    try:
        check(text or "", "t", Reporter(out, err))
    except Exception:
        return [], False
    if err.getvalue().strip():
        return [], False
    return [ln.split(":", 3)[-1].strip() for ln in out.getvalue().splitlines()], True


def _needle(detail: str) -> str:
    return _TRAILING_LINE_RE.sub("", (detail or "").strip()).strip()


def plan_fix(detail: str, file_text: str, line_number, file_path: str = ""):
    """Return (new_text, kind, description) for a mechanical finding, else None.

    Pure: takes and returns text, touches no disk and no database.
    """
    if not file_text or not line_number:
        return None
    try:
        idx = int(line_number) - 1
    except (TypeError, ValueError):
        return None
    lines = file_text.splitlines(keepends=True)
    if idx < 0 or idx >= len(lines):
        return None
    line = lines[idx]
    detail = detail or ""

    # --- unused import on a single-name line -> delete the line ---------------------------
    m = _UNUSED_IMPORT_RE.search(detail)
    if m:
        if file_path.endswith("__init__.py"):
            return None  # re-export, very likely deliberate
        stripped = line.strip()
        if not (stripped.startswith("import ") or stripped.startswith("from ")):
            return None  # the cited line isn't the import — refuse to guess
        after_import = stripped.split("import", 1)[-1]
        if "," in after_import or "(" in after_import or stripped.endswith("\\"):
            return None  # multi-name / parenthesised / continued — out of scope
        new_lines = lines[:idx] + lines[idx + 1 :]
        return "".join(new_lines), "unused_import_single", f"remove unused import: {stripped}"

    # --- f-string with no placeholders -> drop the f prefix -------------------------------
    if _FSTRING_RE.search(detail):
        # Only the simple, unambiguous case: exactly one f-quote on the line and no braces
        # in the literal (a brace means the placeholder analysis is not this simple).
        if "{" in line or line.count('f"') + line.count("f'") != 1:
            return None
        new_line = re.sub(r"(?<![\w])f(['\"])", r"\1", line, count=1)
        if new_line == line:
            return None
        new_lines = lines[:idx] + [new_line] + lines[idx + 1 :]
        return "".join(new_lines), "fstring_no_placeholder", "drop f prefix from placeholder-less f-string"

    return None


def verify_fix(detail: str, old_text: str, new_text: str):
    """(ok, reason). A fix is accepted only when it removes the finding and adds nothing."""
    try:
        ast.parse(new_text)
    except (SyntaxError, ValueError) as exc:
        return False, f"result does not parse: {exc}"

    before, ok_b = _pyflakes_lines(old_text)
    after, ok_a = _pyflakes_lines(new_text)
    if not (ok_b and ok_a):
        return False, "pyflakes unavailable or source unparseable"

    needle = _needle(detail)
    if any(needle in ln for ln in after):
        return False, "finding still reported after the fix"

    # No NEW finding may appear — catches a delete that broke something else.
    introduced = [ln for ln in after if ln not in before]
    if introduced:
        return False, f"fix introduced a new finding: {introduced[0][:90]}"
    return True, "finding removed, nothing introduced"


_ADVISORY_THROTTLE_KEY = "work:code_health_backlog_drain:backup_advisory_at"
_ADVISORY_THROTTLE_HOURS = 6


def _backup_gate_blocked(severity: str = "medium"):
    """Return W.A.R.D.E.N.'s refusal reason, or None if the deploy would clear.

    Calls the SAME predicate the real gate uses (`_check_backup_freshness`) rather than
    re-implementing the age threshold — a second copy would drift from the operator-tunable
    `system_config.backup_governance_gates` and start lying.

    FAIL-OPEN by contract: if backup health cannot be read, return None. A monitoring outage
    must not halt the drain; the real gate still runs downstream and remains authoritative.
    """
    try:
        from services.backup_governance_service import _check_backup_freshness
        from services.backup_service import get_health_summary

        primary = get_health_summary()["tier_health"].get("primary") or {}
        # Must read the SAME field the real gate reads (#5013) — the last SUCCESSFUL
        # backup, not the last attempt. If this pre-flight used `age_hours` it would
        # disagree with the gate it exists to predict, and release fixes that then die
        # at W.A.R.D.E.N. — exactly the wasted-approval problem this pre-flight prevents.
        age = primary.get("last_success_age_hours")
        if age is None and "last_success_age_hours" not in primary:
            age = primary.get("age_hours")
        if age is None:
            return None
        verdict = _check_backup_freshness(age_hours=age, severity=severity)
        return None if verdict.get("approved") else verdict.get("reason") or "backup gate refused"
    except Exception as exc:
        logger.warning("[deterministic-fixer] backup pre-flight unavailable (proceeding): %s", exc)
        return None


def _advise_backup_needed(reason: str, held: int) -> bool:
    """Tell the owner a backup is what's blocking, at most once per _ADVISORY_THROTTLE_HOURS.

    Throttled because the drain runs hourly and a stale backup stays stale — without this it
    would send the same message every cycle until someone acted, training the owner to ignore it.
    """
    try:
        from datetime import datetime, timedelta, timezone

        from database import get_db_cursor

        now = datetime.now(timezone.utc)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (_ADVISORY_THROTTLE_KEY,))
            row = cur.fetchone()
            if row and row["value"]:
                try:
                    last = datetime.fromisoformat(row["value"])
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    if now - last < timedelta(hours=_ADVISORY_THROTTLE_HOURS):
                        return False  # already advised recently
                except ValueError:
                    pass
            cur.execute(
                """INSERT INTO platform_settings (key, value) VALUES (%s, %s)
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                (_ADVISORY_THROTTLE_KEY, now.isoformat()),
            )

        # Ask, don't just tell: a tier-2 approval renders Approve / Cancel buttons, so the
        # blockage is one tap from resolved instead of a notification the owner must act on
        # manually. Approve -> backup_before_deploy executor runs create_backup_programmatic;
        # the held fixes then clear the gate on the next drain cycle. Cancel -> stays held.
        # ai_bridge is imported lazily and needs the path shim first (KB #272154).
        from services.signal_calendar_service import _ensure_import_paths

        _ensure_import_paths()
        from ai_bridge.agent_loop import request_approval

        approval_id = request_approval(
            action_type="backup_before_deploy",
            action_data={"reason": reason, "held": held},
            reason=(
                f"Self-heal is paused — W.A.R.D.E.N. would refuse the deploy: {reason}. "
                f"{held} verified fix(es) are held (not lost; they stay in Repair Bay). "
                f"Approve to run a backup now and let them through, or Cancel to keep holding."
            ),
            requested_by="system",
            tier=2,
            priority=5,
        )
        logger.info("[deterministic-fixer] asked owner (approval %s): %s", approval_id, reason)
        return bool(approval_id)
    except Exception as exc:
        # Never let a comms failure block or crash the drain.
        logger.warning("[deterministic-fixer] backup advisory failed to send: %s", exc)
        return False


def queue_for_approval(proposal_ids, max_queue: int = 5) -> dict:
    """Queue verified fixes into the tiered approval pipeline (Approvals tab + Telegram).

    WHY THIS IS HERE AND WHY IT IS CAPPED
    A fix that reaches `ready_for_review` and stops there is invisible: it sits in Repair Bay
    until a human clicks the Ship-tab batch button. Every OTHER human request on this platform
    reaches the owner through `autonomy_approval_queue` -> Telegram, and these should too.

    But 109 verified fixes queued at once is 109 Telegram prompts. So this is capped per call
    (default 5) and runs once per drain cycle — the backlog drains at a reviewable rate instead
    of arriving as a wall. Raise `work:code_health_backlog_drain:approval_max` to go faster.

    Returns {'queued': n, 'failed': n, 'skipped': n} — never raises; a queueing failure must
    not undo a verified fix that is already safely recorded as ready_for_review.
    """
    from services import proposal_service

    stats = {"queued": 0, "failed": 0, "skipped": 0}

    # ── Pre-flight: would W.A.R.D.E.N. refuse this deploy anyway? ────────────────────────
    # Measured 2026-07-20 (queue row 3200): a fix passed verification, Telegram approval and
    # the sandbox gate 3/3, then died at W.A.R.D.E.N. — "backup age 9.0h exceeds medium limit
    # of 6h". The owner had already spent a tap on something that could never deploy, and the
    # denial was visible ONLY by reading execution_result out of the DB.
    #
    # So: check the SAME gate first. If it would refuse, advise once ("run a backup") and hold
    # the batch instead of burning approvals. The fixes are not lost — they stay
    # ready_for_review and the next drain cycle re-offers them once a backup lands.
    #
    # Fail-OPEN: a monitoring error must never stop the drain. Unknown -> proceed as before.
    blocked_reason = _backup_gate_blocked()
    if blocked_reason:
        _advise_backup_needed(blocked_reason, held=len(list(proposal_ids)))
        stats["skipped"] = len(list(proposal_ids))
        stats["held_for_backup"] = blocked_reason
        logger.warning("[deterministic-fixer] holding %d fix(es): %s", stats["skipped"], blocked_reason)
        return stats

    for pid in list(proposal_ids)[:max_queue]:
        try:
            # force_tier=2 -> Telegram approval, NOT F.O.R.G.E. auto-review.
            # These proposals compute as risk=medium, which _RISK_TIER maps to tier 1
            # (unattended auto-approve -> sandbox -> deploy). For a bulk mechanical run
            # the VOLUME is the risk: 100+ auto-approved diffs with no human glance is
            # not acceptable, and F.O.R.G.E.'s ungrounded-APPROVE bug was only fixed
            # 2026-07-20 (#5009). Owner decision same day: force these to Telegram.
            r = proposal_service.request_tiered_deploy_approval(pid, force_tier=2) or {}
            # Tier 2 (Telegram) returns approval_id; tier 1 (DHQ queue) returns queue_id.
            # Checking only queue_id would score every real Telegram send as a failure.
            ref = r.get("approval_id") or r.get("queue_id")
            if ref:
                stats["queued"] += 1
                logger.info(
                    "[deterministic-fixer] proposal %s -> tier %s approval %s (%s)",
                    pid,
                    r.get("tier"),
                    ref,
                    r.get("approver"),
                )
            else:
                stats["failed"] += 1
                logger.warning(
                    "[deterministic-fixer] proposal %s not queued: %s",
                    pid,
                    (r.get("error") or r.get("message") or "no approval_id/queue_id")[:120],
                )
        except Exception as exc:
            stats["failed"] += 1
            logger.warning("[deterministic-fixer] queue failed for proposal %s: %s", pid, exc)
    stats["skipped"] = max(0, len(list(proposal_ids)) - max_queue)
    return stats


def run_deterministic_fixes(limit: int = 200, dry_run: bool = True, approval_max: int = 0) -> dict:
    """Generate + verify mechanical fixes and offer them as ready_for_review proposals.

    dry_run=True (default) computes and verifies everything but writes nothing.
    approval_max > 0 additionally queues that many of the fixes into the tiered approval
    pipeline so they reach the Approvals tab + Telegram instead of waiting on a manual click.
    """
    from services.audit_pipeline import _build_fix_diff, resolve_proposal_source

    stats = {"examined": 0, "planned": 0, "verified": 0, "rejected": 0, "offered": 0, "dry_run": dry_run, "samples": []}
    accepted = []

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT id, metadata->>'detail' AS detail, metadata->>'line' AS line,
                      COALESCE(NULLIF(metadata->>'file_path',''), metadata->>'runtime_file') AS file_path,
                      metadata
               FROM improvement_proposals
               WHERE status = 'approved'
                 AND metadata->>'source' = 'code_health_audit'
                 AND metadata->>'dispatch_attempted' IS NULL
                 AND metadata->>'issue_code' IN ('PYFLAKES','F401','F541')
               ORDER BY id
               LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()

    for row in rows:
        stats["examined"] += 1
        abs_path, rel_path, status = resolve_proposal_source(row["file_path"])
        if status != "ok" or not abs_path:
            continue
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                old_text = fh.read()
        except OSError:
            continue

        planned = plan_fix(row["detail"], old_text, row["line"], abs_path)
        if not planned:
            continue
        new_text, kind, description = planned
        stats["planned"] += 1

        ok, reason = verify_fix(row["detail"], old_text, new_text)
        if not ok:
            stats["rejected"] += 1
            continue
        stats["verified"] += 1

        diff_text, _diff_stats = _build_fix_diff(old_text, new_text, rel_path)
        accepted.append((row["id"], diff_text, kind, description))
        if len(stats["samples"]) < 5:
            stats["samples"].append({"id": row["id"], "kind": kind, "what": description[:70], "file": rel_path})

    if accepted and not dry_run:
        import json as _json

        with get_db_cursor(commit=True) as (conn, cur):
            for pid, diff_text, kind, description in accepted:
                cur.execute(
                    """UPDATE improvement_proposals
                       SET code_changes = %s,
                           status = 'ready_for_review',
                           metadata = COALESCE(metadata,'{}'::jsonb) || %s::jsonb
                       WHERE id = %s AND status = 'approved'""",
                    (
                        diff_text,
                        _json.dumps(
                            {
                                "fixed_by": "deterministic_fixer",
                                "fix_kind": kind,
                                "fix_description": description,
                                "dispatch_attempted": "deterministic",
                            }
                        ),
                        pid,
                    ),
                )
                stats["offered"] += cur.rowcount
        logger.info("[deterministic-fixer] offered %d verified fix(es) for review", stats["offered"])

        if approval_max > 0:
            q = queue_for_approval([pid for pid, _d, _k, _x in accepted], max_queue=approval_max)
            stats["approval"] = q
            logger.info(
                "[deterministic-fixer] queued %d for approval (%d failed, %d left for a later cycle)",
                q["queued"],
                q["failed"],
                q["skipped"],
            )
    else:
        logger.info(
            "[deterministic-fixer] dry-run: %d planned, %d verified, %d rejected of %d examined",
            stats["planned"],
            stats["verified"],
            stats["rejected"],
            stats["examined"],
        )
    return stats
