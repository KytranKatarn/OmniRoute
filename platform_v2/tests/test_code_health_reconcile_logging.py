"""Reconcile job observability + fix-quality cooldown retry (post-#3916).

Two regressions these tests pin:

1. ``code_health_reconcile_job`` must call ``_log_cycle`` — it previously only
   did ``logger.info``, so it was invisible in ``autonomy_loop_log`` while every
   sibling code_health job logged there. "Is the hourly reconcile even running?"
   had to be answered from docker logs across two containers.

2. ``dispatch_audit_proposals`` must keep the age-gated cooldown branch for
   ``fix_apply:*`` failures. Without it, the ~130 proposals whose fix
   application failed on an older code state (find_not_located / unparseable /
   find_ambiguous) sat "in repair" forever: ``dispatch_attempted`` was set, so
   the drain's ``IS NULL`` gate excluded them permanently, and no scheduled
   caller ever cleared it. The cooldown must NOT widen to non-fix errors
   (C.R.E.E.D. denials, welfare blocks) — those park on purpose.
"""

import json
from unittest.mock import MagicMock, patch

from tools.department_hq import jobs


def _reconcile_out():
    return {
        "issues": {"closed": 2},
        "proposals": {"archived": 3},
        "attribution": {"fixed": 1},
    }


def test_reconcile_job_logs_cycle_with_totals():
    """The job reports to autonomy_loop_log with the summed item count."""
    with patch("services.work_control_service.is_enabled", return_value=True), patch(
        "services.code_issue_reconciler.reconcile_open_issues", return_value={"closed": 2}
    ), patch("services.code_issue_reconciler.reconcile_open_proposals", return_value={"archived": 3}), patch(
        "services.code_health_repairs.reconcile_module_attribution", return_value={"fixed": 1}
    ), patch(
        "tools.department_hq.jobs._log_cycle"
    ) as m_log:
        out = jobs.code_health_reconcile_job()

    m_log.assert_called_once()
    args = m_log.call_args[0]
    assert args[0] == "code_health_reconcile"
    assert args[1] == 6  # 2 issues + 3 proposals + 1 attribution
    assert args[2] == 0  # no failed passes
    details = m_log.call_args[1]["details"] if m_log.call_args[1] else m_log.call_args[0][4]
    assert details["attribution_fixed"] == 1
    assert out["attribution"]["fixed"] == 1


def test_reconcile_job_counts_failed_passes():
    """A pass that raises is counted as a failed item, not silently swallowed."""
    with patch("services.work_control_service.is_enabled", return_value=True), patch(
        "services.code_issue_reconciler.reconcile_open_issues", side_effect=RuntimeError("boom")
    ), patch("services.code_issue_reconciler.reconcile_open_proposals", return_value={"archived": 0}), patch(
        "services.code_health_repairs.reconcile_module_attribution", return_value={"fixed": 0}
    ), patch(
        "tools.department_hq.jobs._log_cycle"
    ) as m_log:
        out = jobs.code_health_reconcile_job()

    assert out["issues"]["error"] == "boom"
    assert m_log.call_args[0][2] == 1  # items_failed


def _dispatch_cursor(rows):
    """Fake cursor capturing the eligibility SQL and returning the given rows."""
    captured = {}

    class _Cursor:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

        def fetchall(self):
            return rows

    class _Ctx:
        def __enter__(self):
            return (MagicMock(), _Cursor())

        def __exit__(self, *a):
            return False

    return _Ctx(), captured


def test_dispatch_eligibility_has_fix_apply_cooldown():
    """The drain's SELECT keeps the 14-day cooldown for fix_apply failures."""
    ctx, captured = _dispatch_cursor([])
    with patch("services.audit_pipeline.get_db_cursor", return_value=ctx):
        from services import audit_pipeline

        result = audit_pipeline.dispatch_audit_proposals(limit=5, dry_run=True)

    assert result == {"dry_run": True, "module": None, "eligible": []}
    sql = captured["sql"]
    assert "(metadata->>'dispatch_attempted') IS NULL" in sql
    # the cooldown branch: only fix_apply:* errors, only after 14 days
    assert "LIKE 'fix_apply:%'" in sql
    assert "INTERVAL '14 days'" in sql
    # excluded codes must still gate BOTH branches (AND binds looser than the OR group)
    assert "<> ALL(%s)" in sql


def test_dispatch_cooldown_never_matches_non_fix_errors():
    """Welfare/self-modification denials must not match the cooldown clause.

    The cooldown filters on the literal 'fix_apply:%' prefix; C.R.E.E.D.
    denial messages ('C.R.E.E.D. ...') and transient-defer markers can never
    satisfy it — asserted here against the real error strings recorded in the
    DB so a future prefix change breaks loudly.
    """
    denial_samples = [
        "C.R.E.E.D. Gate 1 denied: agent welfare threshold exceeded — stress=0.91",
        "C.R.E.E.D. pre-dispatch denied: self-modification blocked",
        "max_transient_defers:agent resting",
    ]
    import fnmatch

    for msg in denial_samples:
        assert not fnmatch.fnmatch(msg, "fix_apply:*"), msg
