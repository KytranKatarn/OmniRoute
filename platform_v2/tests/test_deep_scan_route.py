"""Unit tests for the Deep-Scan worker (Code Health static tier, Task A5).

The worker chains analyzer -> gate -> process_audit_findings through module-level
seams so it is testable without DB or dispatch. Route wiring is exercised live
post-merge; these tests pin the orchestration contract Task A6 consumes.
"""

import tools.consciousness.code_health_routes as chr_mod


def _confirmed(module, rel_file, code="WRONG_KWARG", tool="ast_sweep", verified_by="deterministic"):
    return {
        "code": code,
        "severity": "red",
        "file": f"/app/x/{rel_file}",
        "line": 7,
        "tool": tool,
        "message": "boom (line 7)",
        "module": module,
        "rel_file": rel_file,
        "capability": "code",
        "target": "platform",
        "verified_by": verified_by,
    }


def test_deep_scan_worker_groups_by_module_and_submits(monkeypatch):
    monkeypatch.setattr(
        chr_mod,
        "_static_run",
        lambda target: {
            "target": target,
            "findings": ["raw1", "raw2", "raw3"],
            "coverage": {"tools_run": ["ast_sweep"], "tools_skipped": []},
        },
    )
    monkeypatch.setattr(
        chr_mod,
        "_gate_findings",
        lambda findings: {
            "confirmed": [
                _confirmed("department_hq", "jobs.py"),
                _confirmed("department_hq", "routes.py", code="MISSING_SYMBOL"),
                _confirmed("[AI_BRIDGE]", "agent_loop.py", code="ARITY_MISMATCH"),
            ],
            "advisory": [{"code": "TYPE_ERROR", "advisory": True}],
        },
    )
    submitted = {}

    def fake_submit(module_name, issues):
        submitted[module_name] = issues
        return {"proposals_created": len(issues), "skipped_duplicates": 0, "info_skipped": 0}

    monkeypatch.setattr(chr_mod, "_submit_confirmed", fake_submit)

    result = chr_mod._deep_scan_worker("platform")

    assert result["confirmed"] == 3
    assert result["advisory"] == 1
    assert result["proposals_created"] == 3
    assert set(submitted) == {"department_hq", "[AI_BRIDGE]"}
    assert len(submitted["department_hq"]) == 2  # grouped into ONE pipeline call
    issue = submitted["department_hq"][0]
    assert issue["file"] == "jobs.py"  # pipeline-relative, NOT the runtime path
    assert issue["meta_extra"]["scan_tier"] == "static"
    assert issue["meta_extra"]["tool"] == "ast_sweep"
    assert issue["meta_extra"]["verified_by"] == "deterministic"


def test_deep_scan_worker_demotes_unmapped_paths_to_advisory(monkeypatch):
    monkeypatch.setattr(
        chr_mod,
        "_static_run",
        lambda target: {"target": target, "findings": ["raw"], "coverage": {"tools_run": [], "tools_skipped": []}},
    )
    unmapped = _confirmed(None, "/somewhere/else.py")
    monkeypatch.setattr(chr_mod, "_gate_findings", lambda findings: {"confirmed": [unmapped], "advisory": []})
    called = {"n": 0}
    monkeypatch.setattr(chr_mod, "_submit_confirmed", lambda m, i: called.__setitem__("n", called["n"] + 1) or {})

    result = chr_mod._deep_scan_worker("platform")

    assert called["n"] == 0  # never mints a broken file_path
    assert result["confirmed"] == 0
    assert result["advisory"] == 1
    assert result["proposals_created"] == 0


def test_deep_scan_worker_reports_progress(monkeypatch):
    monkeypatch.setattr(
        chr_mod,
        "_static_run",
        lambda target: {"target": target, "findings": [], "coverage": {"tools_run": [], "tools_skipped": []}},
    )
    monkeypatch.setattr(chr_mod, "_gate_findings", lambda findings: {"confirmed": [], "advisory": []})
    monkeypatch.setattr(chr_mod, "_submit_confirmed", lambda m, i: {})
    ticks = {"n": 0}

    chr_mod._deep_scan_worker("platform", progress_cb=lambda: ticks.__setitem__("n", ticks["n"] + 1))

    assert ticks["n"] >= 3  # scan / gate / submit checkpoints
