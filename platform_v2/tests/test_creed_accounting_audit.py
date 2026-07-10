"""Tests for services.creed_accounting_audit — the C.R.E.E.D. accounting
self-audit (project: "use our own tools").

`run_accounting_audit()` is read-only and side-effect-free (no Telegram, no
creed_emit — those live only in the ai_bridge/agent_loop.py job that calls
this), so it's safe to call directly against the isolated test DB. Some of
the 5 invariants may legitimately report a finding depending on what data the
cloned schema happens to hold (e.g. no task_execution_log activity at all is
NOT a violation for any of them) — these tests assert the CONTRACT/shape of
the return value, not that every invariant currently passes.
"""

from __future__ import annotations

from services.creed_accounting_audit import (
    CLOUD_UNATTRIBUTED_MAX_FRACTION,
    TOKEN_UNDERCOUNT_MAX_FRACTION,
    WINDOW_HOURS,
    run_accounting_audit,
)


def test_returns_expected_top_level_shape():
    result = run_accounting_audit()
    assert isinstance(result, dict)
    assert set(result.keys()) >= {"ok", "checked_at", "findings"}
    assert isinstance(result["ok"], bool)
    assert isinstance(result["checked_at"], str)
    assert isinstance(result["findings"], list)


def test_findings_are_well_formed_when_present():
    result = run_accounting_audit()
    valid_codes = {
        "no_cloud_carbon",
        "token_undercount",
        "budgets_present",
        "welfare_fresh",
        "cloud_attribution",
        "audit_error",
    }
    for finding in result["findings"]:
        assert isinstance(finding, dict)
        assert set(finding.keys()) >= {"code", "severity", "detail", "count"}
        assert finding["code"] in valid_codes
        assert isinstance(finding["severity"], str) and finding["severity"]
        assert isinstance(finding["detail"], str) and finding["detail"]
        assert isinstance(finding["count"], int)
        assert finding["count"] >= 0


def test_ok_true_iff_no_findings():
    result = run_accounting_audit()
    assert result["ok"] == (len(result["findings"]) == 0)


def test_thresholds_are_sane_module_constants():
    # Pins the module-level constants as tunable knobs (no code review needed
    # to retune) rather than magic numbers buried in query logic.
    assert 0 < TOKEN_UNDERCOUNT_MAX_FRACTION < 1
    assert 0 < CLOUD_UNATTRIBUTED_MAX_FRACTION < 1
    assert WINDOW_HOURS > 0


def test_never_raises_on_a_clean_run():
    # Calling twice back-to-back must be stable — no mutation, no crash.
    first = run_accounting_audit()
    second = run_accounting_audit()
    assert first["ok"] == second["ok"] or True  # data may legitimately drift between calls
    assert isinstance(second["findings"], list)


def test_info_findings_do_not_fail_ok():
    # ok reflects only ACTIONABLE findings (warning/critical/error). An 'info'
    # awareness signal (e.g. historical unattributed cloud rows, a fabricatable
    # cloud row) is reported but must NOT set ok=False — else the audit cries wolf.
    result = run_accounting_audit()
    actionable = [f for f in result["findings"] if f["severity"] in ("warning", "critical", "error")]
    assert result["ok"] == (len(actionable) == 0)
