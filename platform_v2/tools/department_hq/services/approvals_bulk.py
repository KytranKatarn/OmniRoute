"""Bulk approve/deny for the DHQ Approvals tab — selection logic, kept pure.

WHY THIS EXISTS: 34 pending approvals accumulated and clearing them meant 34 separate
page interactions. Multi-select fixes the ergonomics.

WHY IT IS NOT JUST "APPROVE ALL": a batch over N items is N decisions, and the odd one
out is what bites. The categories differ in KIND, not just count:

  * deploy_approve / improvement_approve_red / backup_before_deploy — INTERNAL and
    reviewed upstream. Approving twelve at once is a scheduling act.
  * linkedin_post / linkedin_comment / linkedin_comment_reply / linkedin_like /
    website_deploy — OUTBOUND. One click publishes content in the owner's (or Terry's)
    name to the public internet. The platform's standing invariant is that approval is
    the ONLY publish path, precisely so each publish is a deliberate act.

So: multi-select works EVERYWHERE (an explicit tick per item is a deliberate act, even
when you tick twelve), but the one-click "Approve all N in this category" shortcut is
withheld from the outbound set. The difference the rule protects is "did a human look at
each one", not "how many clicks did it take".

Owner decision 2026-08-19. Widening `BULK_ALL_EXCLUDED_TYPES` is safe; narrowing it hands
a publish shortcut to a single click, so it needs the owner.
"""

# Outbound/publishing action types: no one-click category-wide shortcut.
BULK_ALL_EXCLUDED_TYPES = frozenset(
    {
        "linkedin_post",
        "linkedin_comment",
        "linkedin_comment_reply",
        "linkedin_like",
        "linkedin_company_post",
        "linkedin_creed_post",
        "website_deploy",
        "email_reply",
        "media_hub_action",
        # PROVISIONING, not publishing — but "Approve all 15" would create fifteen agents
        # in one click. The first cut of this rule caught the publishing risk and missed
        # this one; a live drive against real data surfaced it (hire_candidate was showing
        # an "Approve all 15" button). Hiring is a staffing decision per candidate.
        "hire_candidate",
    }
)

# ---------------------------------------------------------------------------
# ORDERING + PREREQUISITES
#
# Some approvals GATE others, so clearing the queue in arrival order can ship work the
# safety net was supposed to cover. Measured 2026-08-19 on the live queue: ONE pending
# `backup_before_deploy` ("backup age 9.0h exceeds medium limit of 6h") sat alongside
# TWELVE `deploy_approve` items, every one `risk_level: medium`.
#
# The dependency is in the code, not inferred:
#   deterministic_fixer.py — "Approve -> backup_before_deploy executor runs
#                             create_backup_programmatic"
#   agent_loop.py          — "backup_before_deploy: backup created, self-heal fixes
#                             UNBLOCKED"
# So approving the deploys first ships medium-risk self-heal fixes against a stale
# backup. `improvement_approve_red` (code_health_autoheal) is the same self-heal family
# and is gated with it — deliberately conservative: over-gating costs one extra click,
# under-gating costs the restore point.
# ---------------------------------------------------------------------------

# Lower sorts first. Prerequisites at the top, then code changes, then everything that
# needs individual judgement.
CATEGORY_PRIORITY = {
    "backup_before_deploy": 10,  # take the safety net FIRST
    "pr_merge": 20,  # code lands before it deploys
    "deploy_approve": 30,
    "improvement_approve_red": 31,
    "website_deploy": 40,
    "hire_candidate": 60,
    "linkedin_post": 70,
    "linkedin_comment": 71,
    "linkedin_comment_reply": 72,
    "linkedin_like": 73,
    "email_reply": 74,
    "media_hub_action": 75,
}
_DEFAULT_PRIORITY = 50

# action_type -> [(prerequisite_type, why), ...]. A category can have SEVERAL.
#
# WHY deploy_approve ALSO waits on pr_merge: `deploy_approve` runs the sandbox gate and
# then deploys a proposal's FILES straight onto the platform — it does not travel through
# a PR. So deploying patches while a merge is still pending puts the running code ahead of
# (or sideways from) main, which is the deployed-artifact-vs-git-source divergence this
# platform has repeatedly been bitten by (.claude/rules/deploy-provenance.md, KB #279350).
# Clear the merge first and the two stay in step.
PREREQUISITES = {
    "deploy_approve": [
        ("backup_before_deploy", "deploying without a fresh restore point"),
        ("pr_merge", "deploying puts the running code out of step with main"),
    ],
    "improvement_approve_red": [
        ("backup_before_deploy", "deploying without a fresh restore point"),
        ("pr_merge", "deploying puts the running code out of step with main"),
    ],
    "website_deploy": [
        ("pr_merge", "publishing now would not match main"),
    ],
}


def category_priority(action_type):
    """Sort key for a category. Unknown types land mid-table, never first."""
    return CATEGORY_PRIORITY.get((action_type or "").strip().lower(), _DEFAULT_PRIORITY)


# A backup approval that is APPROVED but not yet EXECUTED — or executed with no resulting
# artifact — does NOT satisfy the prerequisite. Measured 2026-08-19: approving
# `backup_before_deploy` #11442 removed it from `pending` INSTANTLY, clearing the deploy
# gate while `executed_at` was still NULL and no new row had appeared in `backup_log`.
# The window between "approved" and "backup actually on disk" is exactly where a deploy
# must not slip through, and a backup is precisely the operation slow enough for that
# window to be wide. Approval is an INTENT; the artifact is the FACT
# (ADR-014 — gate on the artifact, not the status field).
BACKUP_FRESH_HOURS = 6  # mirrors the threshold the approval itself complains about


def unsatisfied_prerequisites(pending_types, *, backup_in_flight=False, recent_backup_ok=True, pr_merge_open=None):
    """Which prerequisite types are NOT yet satisfied -> {prereq: why}.

    Pure — the CALLER supplies the measured facts, so this stays unit-testable:
      pending_types    action_types that have a PENDING approval right now
      backup_in_flight a backup approval is approved but `executed_at` is still NULL
      recent_backup_ok a SUCCESSFUL backup exists inside BACKUP_FRESH_HOURS
    """
    pending = pending_types or set()
    unsat = {}

    # A PENDING pr_merge approval whose PR is ALREADY merged is STALE and must not block.
    # Measured 2026-08-19: PR #2699 was merged through Repair Bay (the correct path), which
    # does NOT action the approval row — so #11680 stayed `pending` and kept the deploy gate
    # shut on a merge that had already happened. Historic pr_merge rows sat 24.0h and 50.1h
    # before expiring, so a stale one can block deploys for a day or more.
    #
    # This is ADR-014 in a SECOND place, and the first version of this gate shipped the
    # same bug it was written to fix: "a row is pending" is the STATUS, "is the PR still
    # open" is the FACT. `pr_merge_open=None` means the fact could not be measured, and
    # then we fall back to the status and block — unknown must never open a gate.
    if "pr_merge" in pending and (pr_merge_open is None or pr_merge_open):
        unsat["pr_merge"] = "a PR is still waiting to merge"

    # Order matters: report the EARLIEST unmet condition, because that is the one the
    # operator has to act on. "still pending" and "still running" need different actions.
    if "backup_before_deploy" in pending:
        unsat["backup_before_deploy"] = "a backup approval is still pending"
    elif backup_in_flight:
        unsat["backup_before_deploy"] = "the approved backup has not finished running yet"
    elif not recent_backup_ok:
        unsat["backup_before_deploy"] = f"no successful backup in the last {BACKUP_FRESH_HOURS}h"

    return unsat


def blocking_reasons(action_type, unsatisfied):
    """Every reason this category should wait, in prerequisite order. [] when clear.

    `unsatisfied` may be a SET of prerequisite types, or a DICT of {prereq: state_reason}.
    The dict form yields the more specific message — "the approved backup has not finished
    running yet" tells the operator what to WAIT for, where "approve the backup first"
    would be actively wrong once it is already approved.
    """
    unsat = unsatisfied or {}
    out = []
    for prereq, why in PREREQUISITES.get((action_type or "").strip().lower(), []):
        if prereq not in unsat:
            continue
        state = unsat.get(prereq) if isinstance(unsat, dict) else None
        out.append(f"{state} — {why}" if state else why)
    return out


def blocking_reason(action_type, pending_types):
    """First reason this category should wait, or None.

    ADVISORY by design: it suppresses the one-click shortcut and explains itself, but it
    never forbids approving an INDIVIDUAL item. The operator may have a reason the
    heuristic does not know, and a hard block built on a heuristic is worse than the
    problem it prevents — it would strand the queue with no override.
    """
    reasons = blocking_reasons(action_type, pending_types)
    return reasons[0] if reasons else None


# A runaway click must not fire hundreds of executions. Selecting more is not an error —
# the caller is told to split, rather than having a silent slice of the list executed
# (a silent truncation would read as "all done" while leaving items pending).
MAX_BULK = 50

# WHY each excluded type has no one-click shortcut. A single generic label was WRONG for
# hire_candidate — it read "publishes externally" for what is actually provisioning, and a
# plausible-but-false explanation is worse than none because the operator acts on it.
BULK_ALL_REASONS = {
    "hire_candidate": "creates agents — approve individually",
}
_DEFAULT_BULK_ALL_REASON = "publishes externally — select individually"


def bulk_all_reason(action_type):
    """Why this category offers no one-click approve-all, or None when it does."""
    key = (action_type or "").strip().lower()
    if key not in BULK_ALL_EXCLUDED_TYPES:
        return None
    return BULK_ALL_REASONS.get(key, _DEFAULT_BULK_ALL_REASON)


_VALID_PREFIXES = ("autonomy", "contractor", "bridge")


def can_bulk_all(action_type):
    """May this category offer a one-click 'approve all N' button?"""
    return (action_type or "").strip().lower() not in BULK_ALL_EXCLUDED_TYPES


def parse_approval_id(approval_id):
    """`autonomy:123` -> ('autonomy', 123). Returns None when the shape is wrong.

    Mirrors the single-approve route's parsing so bulk cannot accept an id shape the
    single path would reject.
    """
    if not isinstance(approval_id, str):
        return None
    prefix, _, raw = approval_id.partition(":")
    if prefix not in _VALID_PREFIXES or not raw:
        return None
    try:
        return prefix, int(raw)
    except ValueError:
        return None


def validate_batch(ids, action):
    """Validate a bulk request. Returns (parsed, error) — error is None when usable.

    `parsed` is a list of (approval_id, prefix, source_id) preserving input order and
    de-duplicated, so the same id submitted twice executes once.
    """
    if action not in ("approve", "deny"):
        return None, "action must be 'approve' or 'deny'"
    if not isinstance(ids, list) or not ids:
        return None, "ids must be a non-empty list"
    if len(ids) > MAX_BULK:
        return None, f"too many items ({len(ids)}); approve at most {MAX_BULK} at a time"

    parsed, seen = [], set()
    for raw in ids:
        got = parse_approval_id(raw)
        if got is None:
            return None, f"invalid approval id: {raw!r}"
        if raw in seen:
            continue
        seen.add(raw)
        parsed.append((raw, got[0], got[1]))
    return parsed, None
