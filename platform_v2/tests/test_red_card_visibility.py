"""Red Code Health approvals must be visible and complete in the Approvals tab.

Three stacked defects left 11 red audit proposals stranded `pending` for 5-16
days with nothing in the Approvals tab (2026-08-28):

1. `_load_unapproved_reds` matched only `scan_tier='static'` — the audit
   pipeline stamps no scan_tier, so its reds could never be (re-)carded.
2. `_check_existing_approval` used the coarse per-action_type dedup for
   `improvement_approve_red` — one card at a time, each expiring in 24h.
   FOURTH instance of the trap (contractor_dispatch, linkedin_post #3944,
   pr_merge #5829, deploy_approve).
3. `reconcile_open_proposals` defaulted to approved-only, so a stale
   `ready_for_review` twin kept a live deploy_approve card that could only
   fail the sandbox gate ("patch does not apply") — 6 owner taps burned.
"""

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.repo_root import repo_root  # noqa: E402

sys.path.insert(0, str(repo_root()))

from ai_bridge.agent_loop import _check_existing_approval  # noqa: E402


class _Cur:
    """Records the SQL + params, returns a canned row."""

    def __init__(self, row=None):
        self.row, self.sql, self.params = row, None, None

    def execute(self, sql, params=None):
        self.sql, self.params = sql, params

    def fetchone(self):
        return self.row


# ── dedup: per proposal, never per action_type ────────────────────────────────


def test_same_red_proposal_is_deduped():
    cur = _Cur(row=(1,))
    assert _check_existing_approval("improvement_approve_red", {"proposal_id": 11115}, cur) is True
    assert "action_data->>'proposal_id'" in cur.sql
    assert cur.params == ("improvement_approve_red", "11115")


def test_a_DIFFERENT_red_proposal_is_not_deduped():
    """The actual bug: red B could not card because red A's card was pending."""
    cur = _Cur(row=None)
    assert _check_existing_approval("improvement_approve_red", {"proposal_id": 11116}, cur) is False


def test_proposal_id_is_compared_as_text():
    """action_data->>'proposal_id' yields TEXT; an int param silently matches
    nothing, which would disable dedup and queue duplicate cards."""
    cur = _Cur(row=(1,))
    _check_existing_approval("improvement_approve_red", {"proposal_id": 11115}, cur)
    assert cur.params[1] == "11115" and isinstance(cur.params[1], str)


def test_missing_proposal_id_falls_back_to_coarse_dedup_not_bypass():
    cur = _Cur(row=(1,))
    assert _check_existing_approval("improvement_approve_red", {}, cur) is True
    assert "action_data->>'proposal_id'" not in (cur.sql or "")


# ── carding: audit-sourced reds are in scope, unknown producers are not ──────


def _reds_sql():
    from services import code_health_autoheal as ah

    return inspect.getsource(ah._load_unapproved_reds)


def test_audit_pipeline_reds_are_cardable():
    """Reds with no scan_tier stamp (source='code_health_audit') must be
    selected — matching only the static stamp is how 11 reds went invisible."""
    src = _reds_sql()
    assert "code_health_audit" in src
    assert "scan_tier" in src  # statics stay covered too


def test_red_selector_still_requires_red_and_pending():
    src = _reds_sql()
    assert "severity_tier' = 'red'" in src
    assert "p.status = 'pending'" in src


# ── reconciler: ready_for_review in scope, cards die with the proposal ───────


def test_reconcile_job_covers_ready_for_review():
    """The scheduled job must pass ready_for_review — a built fix whose finding
    another PR resolved is otherwise never archived and re-cards forever.

    Resolved relative to THIS file: in-container the /mnt/archie_brain mount
    excludes platform_v2, so repo_root()-based paths do not exist there."""
    jobs_py = Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "jobs.py"
    src = jobs_py.read_text(encoding="utf-8")
    call = src.split("reconcile_open_proposals(", 1)[1].split(")", 1)[0]
    assert "ready_for_review" in call and "approved" in call


def test_reconciler_cancels_pending_cards_for_archived_proposals():
    """Archiving must cancel the proposal's pending deploy/red cards — else the
    Approvals tab keeps offering taps that can only fail the sandbox gate."""
    src = inspect.getsource(
        __import__("services.code_issue_reconciler", fromlist=["reconcile_open_proposals"]).reconcile_open_proposals
    )
    assert "autonomy_approval_queue" in src
    assert "'deploy_approve'" in src and "'improvement_approve_red'" in src
    assert "cards_cancelled" in src
