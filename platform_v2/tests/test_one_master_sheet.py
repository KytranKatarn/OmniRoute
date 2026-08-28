"""One master sheet: improvement_proposals (finding_fingerprint identity) is the
single unique list every Code Health / Repair Bay number derives from (#6107).

Pins three changes from 2026-08-28:

1. The legacy per-module roll-up proposal writer in log_audit is RETIRED — it
   minted "Code Health: N issue(s) in X" rows (proposal_source='code_health_scan')
   beside the per-finding proposals from the same audit run: a second sheet no
   code path ever read, inflating every unfiltered Repair Bay count.
2. The audit-details drilldown uses the same live-proposal exclusion as
   module-status (archived/rejected/deployed) — it previously counted deployed
   rows as "in repair".
3. A merged fix re-audits its module immediately (_reaudit_module), so the
   Issues count decrements within the poll cycle instead of holding the
   pre-fix number until the nightly audit-all.
"""

import inspect
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.repo_root import repo_root  # noqa: E402

sys.path.insert(0, str(repo_root()))

PLATFORM = Path(__file__).resolve().parents[1]


# ── 1. roll-up writer retired ────────────────────────────────────────────────


def test_log_audit_no_longer_mints_rollup_proposals():
    from services.code_metrics_service import log_audit

    src = inspect.getsource(log_audit)
    assert "INSERT INTO improvement_proposals" not in src
    assert "code_audit_log" in src  # the audit-history insert stays


def test_no_writer_anywhere_mints_code_health_scan_proposals():
    """proposal_source='code_health_scan' must have ZERO writers — a new one
    would silently reopen the duplicate sheet."""
    hits = []
    for py in PLATFORM.rglob("*.py"):
        if "tests" in py.parts or "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        if "'code_health_scan'" in text and "improvement_proposals" in text:
            # Allowed only as a comment/doc mention, never inside an INSERT/UPDATE
            for stmt in ("INSERT INTO improvement_proposals", "UPDATE improvement_proposals"):
                idx = 0
                while True:
                    idx = text.find(stmt, idx)
                    if idx == -1:
                        break
                    if "'code_health_scan'" in text[idx : idx + 800]:
                        hits.append(str(py))
                    idx += 1
    assert not hits, f"rollup writer reintroduced in: {hits}"


# ── 2. one live-proposal exclusion across the drilldowns ─────────────────────


def test_audit_details_and_module_status_share_the_exclusion():
    routes = (PLATFORM / "tools" / "consciousness" / "code_health_routes.py").read_text(encoding="utf-8")
    assert routes.count("NOT IN ('archived', 'rejected', 'deployed')") >= 2, (
        "audit-details and module-status must exclude the same statuses — "
        "counting deployed rows as 'in repair' is how the drilldown disagreed "
        "with the module badges"
    )


# ── 3. merged fix refreshes its module's Issues count ────────────────────────


def test_both_merge_settlement_sites_reaudit():
    fp = (PLATFORM / "tools" / "repair_bay" / "services" / "forge_pipeline.py").read_text(encoding="utf-8")
    calls = fp.count("_reaudit_module(") - fp.count("def _reaudit_module(")
    assert calls >= 2, "both mark_stale_audits sites must also kick a re-audit"


def test_reaudit_is_ttl_deduped_and_never_raises(monkeypatch):
    from tools.repair_bay.services import forge_pipeline as fpl

    calls = []

    class _FakeRoutes:
        @staticmethod
        def run_code_health_audit(module_key):
            calls.append(module_key)
            return {"success": True, "results": [{"issues": 3}]}, 200

    monkeypatch.setitem(sys.modules, "tools.consciousness.code_health_routes", _FakeRoutes())
    fpl._REAUDIT_RECENT.clear()

    fpl._reaudit_module("email_manager")
    fpl._reaudit_module("email_manager")  # within TTL — skipped
    assert calls == ["email_manager"]

    # A raising audit must not propagate into merge settlement
    class _Boom:
        @staticmethod
        def run_code_health_audit(module_key):
            raise RuntimeError("audit exploded")

    monkeypatch.setitem(sys.modules, "tools.consciousness.code_health_routes", _Boom())
    fpl._REAUDIT_RECENT.clear()
    fpl._reaudit_module("creed")  # must not raise

    # Expired TTL runs again
    fpl._REAUDIT_RECENT["email_manager"] = time.time() - fpl._REAUDIT_TTL_S - 1
    monkeypatch.setitem(sys.modules, "tools.consciousness.code_health_routes", _FakeRoutes())
    fpl._reaudit_module("email_manager")
    assert calls == ["email_manager", "email_manager"]
