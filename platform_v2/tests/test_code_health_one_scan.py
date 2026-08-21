"""Unit tests for the Code Health one-scan/one-view consolidation (#5881).

Covers: the shared findings parser (defect 3 — the headline count must be
derived from the findings list, never a separately-tracked issues_found
column that only counted 'red'-severity issues), log_audit()'s honest
default provenance (a caller that omitted dispatched_via used to write a
silent NULL), and that the new persistent scheduled scan calls the SAME
per-module write path the manual "Audit All" button uses — so scheduled
and manual can never disagree.
"""

import inspect

import tools.consciousness.code_health_routes as chr_mod
import services.code_metrics_service as cms
import tools.department_hq.jobs as jobs


def test_parse_audit_findings_counts_every_severity_not_just_red():
    """The exact production shape that exposed defect 3: [AI_BRIDGE]'s stored
    notes held 30 parseable findings (measured: 3 red, 11 yellow, 16 info)
    while the OLD persisted issues_found column held only 6 (a red-adjacent
    subset). The headline number must be len(findings), not a red-only
    count — this fixture proves the two would visibly disagree."""
    notes = (
        "LARGE_FILE: a.py (900 lines); DEBUG_PRINT: b.py (line 5); "
        "SQL_INJECTION_RISK: c.py; HARDCODED_SECRET: d.py; BARE_EXCEPT: e.py"
    )
    findings = chr_mod._parse_audit_findings(notes)
    assert len(findings) == 5  # total, not a red-only subset
    red = [f for f in findings if f["severity"] == "red"]
    assert len(red) == 2  # SQL_INJECTION_RISK + HARDCODED_SECRET
    assert len(red) != len(findings)  # proves a red-only count would undercount


def test_parse_audit_findings_empty_on_clean_or_absent():
    assert chr_mod._parse_audit_findings("clean — all checks passed") == []
    assert chr_mod._parse_audit_findings("clean") == []
    assert chr_mod._parse_audit_findings("") == []
    assert chr_mod._parse_audit_findings(None) == []


def test_parse_audit_findings_severity_sets_shared_with_drilldown():
    """severity-summary used to carry its own narrower 4-red/3-yellow copy of
    this classification (missing HARDCODED_SECRET/DIRECT_OLLAMA/DIRECT_CLOUD/
    INSECURE_DEFAULT on red, and MISSING_INIT/INLINE_SCRIPT/CONSOLE_LOG/
    LATEST_TAG/MISSING_RESOURCE_LIMIT on yellow) — a code correctly
    classified by the audit-details drilldown could silently reclassify as
    green in the severity summary. One shared set now, used by both."""
    for code in ("HARDCODED_SECRET", "DIRECT_OLLAMA", "DIRECT_CLOUD", "INSECURE_DEFAULT"):
        assert code in chr_mod._FINDING_RED_CODES
    for code in ("MISSING_INIT", "INLINE_SCRIPT", "CONSOLE_LOG", "LATEST_TAG", "MISSING_RESOURCE_LIMIT"):
        assert code in chr_mod._FINDING_YELLOW_CODES


def test_log_audit_default_provenance_is_local_static_analysis():
    """#5881 fix 5: every current caller of log_audit() IS local static
    analysis (verified live: no caller invokes an LLM). A caller that omits
    dispatched_via must not silently write NULL — 'unmonitored while
    APPEARING monitored', the same defect class as #2366."""
    sig = inspect.signature(cms.log_audit)
    assert sig.parameters["dispatched_via"].default == "local_static_analysis"


def test_scheduled_static_audit_calls_the_manual_buttons_write_path(monkeypatch):
    """The persistent scheduled scan must call _audit_one() — the SAME
    function code_health_routes.run_code_health_audit()'s 'audit all
    modules' path uses for the manual button — never a re-implementation
    that could silently drift from it (the whole point of #5881)."""
    calls = []
    monkeypatch.setattr(chr_mod, "_audit_one", lambda key, data: calls.append(key))
    monkeypatch.setattr(cms, "scan_codebase", lambda: {"modules": {"mod_a": {"files": 1}, "mod_b": {"files": 2}}})
    jobs.daily_code_health_static_audit()
    assert sorted(calls) == ["mod_a", "mod_b"]


def test_scheduled_static_audit_survives_a_single_module_failure(monkeypatch):
    """One module's audit raising must not abort the rest — matching the
    existing audit-all job's per-module try/except in run_code_health_audit."""
    calls = []

    def _audit_one_stub(key, data):
        if key == "mod_a":
            raise RuntimeError("boom")
        calls.append(key)

    monkeypatch.setattr(chr_mod, "_audit_one", _audit_one_stub)
    monkeypatch.setattr(cms, "scan_codebase", lambda: {"modules": {"mod_a": {}, "mod_b": {}}})
    jobs.daily_code_health_static_audit()  # must not raise
    assert calls == ["mod_b"]
