"""A scan that executed nothing must not report success.

REAL INCIDENT: scanning KSO on 2026-07-26 returned
{suites_run: 0, passed: 0, total: 0, all_green: true}. KSO has no registered
P.R.O.B.E. suite, so nothing ran -- but `passed == total` is `0 == 0`, and the
caller reads that as "this module is verified".

Same family as the W.A.R.D.E.N. backup check that queried a phantom table and
the host_monitor alert path that swallowed every failure: absence of a result
rendered as a good result.
"""

import asyncio
import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _run(module, fake_results, monkeypatch):
    from mcp_server.tools import forge_tools

    import services.qa_service as qa

    monkeypatch.setattr(qa, "run_suite_for_module", lambda m, **k: fake_results)
    return asyncio.run(forge_tools.repair_bay_scan_handler({"module": module}))


class TestZeroSuitesIsNotGreen:
    def test_no_registered_suite_is_unknown_not_green(self, monkeypatch):
        r = _run("standalone_kytran_system_operations", [], monkeypatch)
        assert r["suites_run"] == 0
        # THE BUG: this used to be True because 0 == 0.
        assert r["all_green"] is not True
        assert r["all_green"] is None
        assert r["no_suites_registered"] is True
        assert "not a pass" in (r["warning"] or "").lower()

    def test_old_expression_would_have_said_green(self):
        # Pin the defect so a "simplification" cannot restore it.
        passed, total = 0, 0
        assert (passed == total) is True  # <- what shipped


class TestRealResultsStillWork:
    def test_all_passing_is_green(self, monkeypatch):
        r = _run("repair_bay", [{"passed": 5, "total": 5}], monkeypatch)
        assert r["all_green"] is True
        assert r["no_suites_registered"] is False
        assert r["warning"] is None

    def test_a_failure_is_not_green(self, monkeypatch):
        r = _run("repair_bay", [{"passed": 4, "total": 5}], monkeypatch)
        assert r["all_green"] is False
        assert r["no_suites_registered"] is False

    def test_suite_that_ran_with_zero_assertions_is_still_a_real_run(self, monkeypatch):
        # A registered suite that happens to contain 0 checks DID run. That is
        # distinct from having no suite at all, and must not be flagged as
        # "no_suites_registered".
        r = _run("repair_bay", [{"passed": 0, "total": 0}], monkeypatch)
        assert r["suites_run"] == 1
        assert r["no_suites_registered"] is False
        assert r["all_green"] is True
