"""Nothing on the hub may dial the RETIRED hub `wtf` database again (task #7372).

The hub `wtf` DB was dropped on 2026-10-02 (#3591). Eight call sites kept dialing it and failed ~3,000 times a day for
18 days; the freshness watchdog was blind, post grounding silently fell back to nothing, and governance recorded ~334
false "success" runs a day for jobs that did nothing. These tests pin the replacement wiring. Run with --noconftest.
"""

import ast
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]  # platform_v2/
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from services import wtf_remote  # noqa: E402

JOBS = ROOT / "tools" / "department_hq" / "jobs.py"


def _src(path):
    return pathlib.Path(path).read_text()


# ── static guards ────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "path",
    [
        REPO / "ai_bridge" / "agent_loop.py",
        ROOT / "services" / "alert_actions_service.py",
        ROOT / "services" / "signal_calendar_service.py",
        ROOT / "tools" / "wtf_hub" / "routes.py",
    ],
)
def test_no_unguarded_dial_of_the_retired_hub_database(path):
    text = _src(path)
    assert 'dbname="wtf"' not in text and "dbname='wtf'" not in text, f"{path.name} still dials the hub wtf DB"


def test_jobs_py_only_dials_it_behind_the_flag():
    """The three remaining sites: the `_wtf_cur` helper (used only by the gated jobs) and the two guarded injectors."""
    text = _src(JOBS)
    assert text.count('dbname="wtf"') == 3
    assert text.count("raise _wr.HubBacklogDisabled()") == 2  # both orchestration injectors check the flag first
    assert text.count("except _wr.HubBacklogDisabled:") == 2


def test_all_seven_hub_wtf_jobs_register_through_the_gate():
    text = _src(JOBS)
    jobs = ["llm_analysis", "geo", "factcheck", "factcheck_backlog", "bias_backlog", "geo_backlog", "scout"]
    for job in jobs:
        assert f"with_ctx(_run_wtf_{job})," in text
        # the registration that wraps this job must be the gated helper, never a bare scheduler.add_job
        idx = text.index(f"with_ctx(_run_wtf_{job}),")
        assert text.rfind("_add_wtf_hub_job(", 0, idx) > text.rfind("scheduler.add_job(", 0, idx), job
    assert text.count("_add_wtf_hub_job(") == 8  # 7 registrations + the definition


def test_watchdog_uses_the_tested_step_function_not_a_database():
    text = _src(REPO / "ai_bridge" / "agent_loop.py")
    assert "wtf_remote.watchdog_step(" in text and "wtf_watchdog_blind" in text and "wtf_ingest_stale" in text
    assert "WatchdogState()" in text


# ── the registration gate, executed (extracted from jobs.py, not re-implemented) ─────────────────────
def _gate(monkeypatch, enabled):
    tree = ast.parse(_src(JOBS))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_add_wtf_hub_job")
    added, logs = [], []
    ns = {
        "scheduler": types.SimpleNamespace(add_job=lambda *a, **k: added.append((a, k)) or "job"),
        "logger": types.SimpleNamespace(info=lambda *a, **k: logs.append(a)),
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "jobs_gate", "exec"), ns)
    monkeypatch.setattr(wtf_remote, "hub_backlog_enabled", lambda: enabled)
    return ns["_add_wtf_hub_job"], added, logs


def test_gate_off_registers_nothing_and_says_why(monkeypatch):
    add, added, logs = _gate(monkeypatch, False)
    assert add("fn", id="wtf_bias_backlog") is None
    assert added == []  # not in the scheduler => not listed as healthy, no false governance 'success' rows
    assert logs and "Citadel" in logs[0][0] and logs[0][1] == "wtf_bias_backlog"


def test_gate_on_registers_with_the_original_arguments(monkeypatch):
    add, added, _ = _gate(monkeypatch, True)
    assert add("fn", trigger="t", id="wtf_geo", max_instances=1) == "job"
    assert added == [(("fn",), {"trigger": "t", "id": "wtf_geo", "max_instances": 1})]


# ── post grounding ───────────────────────────────────────────────────────────────────────────────────
def test_signal_grounding_comes_from_the_public_api(monkeypatch):
    from services import signal_calendar_service as sc

    monkeypatch.setattr(
        wtf_remote, "latest_headlines", lambda limit=12, days=2, timeout=10: [("Alpha story", "CBC"), ("Beta", "")]
    )
    out = sc._wtf_recent_headlines(limit=2)
    assert '- "Alpha story" (CBC)' in out and '- "Beta" (outlet)' in out
    assert "do NOT invent stories" in out  # the anti-fabrication instruction is preserved


def test_signal_grounding_fails_open_without_leaking(monkeypatch, caplog):
    from services import signal_calendar_service as sc

    def boom(*a, **k):
        raise wtf_remote.WtfApiError("URLError reading /api/v1/articles")

    monkeypatch.setattr(wtf_remote, "latest_headlines", boom)
    assert sc._wtf_recent_headlines() == ""
    assert "theme-only" in caplog.text and "https://" not in caplog.text


def test_signal_grounding_empty_when_no_headlines(monkeypatch):
    from services import signal_calendar_service as sc

    monkeypatch.setattr(wtf_remote, "latest_headlines", lambda **k: [])
    assert sc._wtf_recent_headlines() == ""


# ── alert details ────────────────────────────────────────────────────────────────────────────────────
def test_alert_details_report_honestly_what_they_can_no_longer_see(monkeypatch):
    from services import alert_actions_service as aa

    monkeypatch.setattr(wtf_remote, "article_count", lambda timeout=10: 180113)
    monkeypatch.setattr(wtf_remote, "latest_headlines", lambda limit=12, days=2, timeout=10: [("Headline one", "CTV")])
    out = aa._wtf_ingest_details()
    assert "180,113" in out and "Headline one" in out and "CTV" in out
    assert "read-only Citadel" in out  # says why minutes-since-ingest / coverage are absent


def test_alert_details_never_raise(monkeypatch):
    from services import alert_actions_service as aa

    def boom(*a, **k):
        raise wtf_remote.WtfApiError("x")

    monkeypatch.setattr(wtf_remote, "article_count", boom)
    assert "unavailable" in aa._wtf_ingest_details()
