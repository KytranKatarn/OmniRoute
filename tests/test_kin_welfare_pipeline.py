import json
import sys
from unittest.mock import MagicMock, patch

_WT = "/mnt/archie_brain/.worktrees/kin-creed-welfare"
# Remove main-tree roots that shadow the worktree's ai_bridge package.
for _p in ["/mnt/archie_brain", "/mnt/archie_brain/platform_v2"]:
    while _p in sys.path:
        sys.path.remove(_p)
# Worktree paths first so ai_bridge.agent_loop resolves from the worktree.
sys.path.insert(0, f"{_WT}/ai_bridge")
sys.path.insert(0, f"{_WT}/platform_v2")
sys.path.insert(0, _WT)


def _make_loop():
    """Return a bare AgentLoop instance with no scheduler."""
    import ai_bridge.agent_loop as _al_module
    loop = object.__new__(_al_module.AgentLoop)
    loop.logger = _al_module.logger
    return loop


def make_digest(at_risk=0, over_budget=0, starving_idle=0):
    return {
        "summary_metrics": {
            "total_over_budget": over_budget,
            "total_at_risk": at_risk,
            "total_starving_idle": starving_idle,
            "total_starving": starving_idle,
            "total_starving_no_llm": 0,
            "stress_rising": 0,
            "department_count": 17,
            "per_agent_flag_count": at_risk + starving_idle,
            "agents_working_now": 5,
        },
        "per_agent_flags": [
            {"agent_id": 42, "name": "T.E.S.T.", "department": "Engineering", "flag": "starving_idle"}
        ] if starving_idle else [],
        "department_rollup": [],
        "work_activity": {"agents_working": 5},
        "severity": "warning" if (at_risk or over_budget or starving_idle) else "info",
        "reasons": [],
    }


def test_kin_assess_welfare_returns_parsed_json():
    loop = _make_loop()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.queued = False
    mock_result.response = json.dumps({
        "summary": "All good.",
        "at_risk_agents": [],
        "idle_neglected": [{"agent_id": 42, "name": "T.E.S.T.", "days_idle": 7, "department": "Engineering"}],
        "actions": [{"type": "welfare_recovery", "agent_id": 42, "reason": "idle 7d", "value": None}],
        "creed_flags": [],
        "archie_report": {"message": "Minor idle gap.", "severity": "info"},
    })

    with patch("tools.department_hq.services.department_dispatcher.dispatch", return_value=mock_result):
        result = loop._kin_assess_welfare(make_digest(starving_idle=1))

    assert result is not None
    assert result["archie_report"]["severity"] == "info"
    assert result["actions"][0]["type"] == "welfare_recovery"


def test_kin_assess_welfare_returns_none_on_dispatch_failure():
    loop = _make_loop()
    mock_result = MagicMock()
    mock_result.success = False
    mock_result.queued = False

    with patch("tools.department_hq.services.department_dispatcher.dispatch", return_value=mock_result):
        result = loop._kin_assess_welfare(make_digest())

    assert result is None


def test_kin_assess_welfare_returns_none_on_bad_json():
    loop = _make_loop()
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.queued = False
    mock_result.response = "not json at all"

    with patch("tools.department_hq.services.department_dispatcher.dispatch", return_value=mock_result):
        result = loop._kin_assess_welfare(make_digest())

    assert result is None


def test_kin_execute_actions_welfare_recovery():
    loop = _make_loop()
    actions = [{"type": "welfare_recovery", "agent_id": 42, "reason": "idle 7d", "value": None}]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with patch("services.agent_service.recover_idle") as mock_recover:
        count = loop._kin_execute_actions(actions, mock_conn)

    assert count == 1
    mock_recover.assert_called_once_with(42)
    mock_cur.execute.assert_called_once()  # governance_audit_log insert


def test_kin_execute_actions_skips_unknown_type():
    loop = _make_loop()
    actions = [{"type": "teleport", "agent_id": 42, "reason": "??", "value": None}]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = MagicMock()
    count = loop._kin_execute_actions(actions, mock_conn)
    assert count == 0


def test_kin_execute_actions_skips_missing_agent_id():
    loop = _make_loop()
    actions = [{"type": "welfare_recovery", "agent_id": None, "reason": "test", "value": None}]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    count = loop._kin_execute_actions(actions, mock_conn)
    assert count == 0
    mock_cur.execute.assert_called_once()  # governance_audit_log skip INSERT was called


def test_kin_execute_actions_continues_on_failure():
    loop = _make_loop()
    actions = [
        {"type": "welfare_recovery", "agent_id": 99, "reason": "test", "value": None},
        {"type": "welfare_recovery", "agent_id": 42, "reason": "test", "value": None},
    ]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = MagicMock()

    call_count = 0
    def recover_side_effect(agent_id):
        nonlocal call_count
        call_count += 1
        if agent_id == 99:
            raise RuntimeError("agent not found")

    with patch("services.agent_service.recover_idle", side_effect=recover_side_effect):
        count = loop._kin_execute_actions(actions, mock_conn)

    assert count == 1  # only agent 42 succeeded


def test_kin_file_creed_inserts_rows():
    loop = _make_loop()
    flags = [
        {"event_type": "agent_starvation", "agent_id": 42, "reason": "idle 14d", "severity": "high"},
        {"event_type": "agent_exploitation", "agent_id": 7, "reason": "stress 0.95 for 3d", "severity": "critical"},
    ]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    filed = loop._kin_file_creed(flags, mock_conn)

    assert filed == 2
    assert mock_cur.execute.call_count == 2
    assert mock_conn.commit.call_count == 2


def test_kin_file_creed_continues_on_db_error():
    loop = _make_loop()
    flags = [
        {"event_type": "test_event", "agent_id": 1, "reason": "test", "severity": "low"},
        {"event_type": "test_event", "agent_id": 2, "reason": "test", "severity": "low"},
    ]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    # First execute raises, second succeeds
    mock_cur.execute.side_effect = [Exception("DB error"), None]

    filed = loop._kin_file_creed(flags, mock_conn)
    assert filed == 1  # second one succeeded


def test_kin_file_creed_empty_flags():
    loop = _make_loop()
    mock_conn = MagicMock()
    filed = loop._kin_file_creed([], mock_conn)
    assert filed == 0


def test_kin_report_to_archie_critical_sends_alert():
    loop = _make_loop()
    report = {"message": "Agent burnout detected.", "severity": "critical"}

    with patch("services.telegram_service.send") as mock_send:
        loop._kin_report_to_archie(report, actions_taken=2, flags_filed=1)

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args
    assert "alert" in str(call_kwargs)
    assert "K.I.N." in str(call_kwargs)


def test_kin_report_to_archie_warning_sends_info():
    loop = _make_loop()
    report = {"message": "Some idle agents.", "severity": "warning"}

    with patch("services.telegram_service.send") as mock_send:
        loop._kin_report_to_archie(report, actions_taken=1, flags_filed=0)

    mock_send.assert_called_once()
    assert "info" in str(mock_send.call_args)


def test_kin_report_to_archie_info_no_telegram():
    loop = _make_loop()
    report = {"message": "All healthy.", "severity": "info"}

    with patch("services.telegram_service.send") as mock_send:
        loop._kin_report_to_archie(report, actions_taken=0, flags_filed=0)

    mock_send.assert_not_called()


def test_kin_report_to_archie_appends_action_summary():
    loop = _make_loop()
    report = {"message": "Two agents cooled down.", "severity": "alert"}

    with patch("services.telegram_service.send") as mock_send:
        loop._kin_report_to_archie(report, actions_taken=2, flags_filed=3)

    call_str = str(mock_send.call_args)
    assert "Actions taken: 2" in call_str
    assert "C.R.E.E.D. filings: 3" in call_str


def test_run_kin_welfare_digest_full_pipeline():
    """Integration: all 4 phases run when K.I.N. dispatch succeeds."""
    loop = _make_loop()
    loop._log_cycle = MagicMock()
    loop._send_telegram = MagicMock()

    digest = make_digest(starving_idle=3)
    assessment = {
        "summary": "Three agents idle.",
        "at_risk_agents": [],
        "idle_neglected": [{"agent_id": 42, "name": "T.E.S.T.", "days_idle": 7, "department": "Eng"}],
        "actions": [{"type": "welfare_recovery", "agent_id": 42, "reason": "idle", "value": None}],
        "creed_flags": [{"event_type": "agent_starvation", "agent_id": 42, "reason": "idle 7d", "severity": "low"}],
        "archie_report": {"message": "Minor routing gap.", "severity": "info"},
    }

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = MagicMock()

    with patch("services.agent_service.get_kin_welfare_digest", return_value=digest), \
         patch("services.agent_service.format_kin_digest_message", return_value="digest text"), \
         patch.object(loop, "_kin_assess_welfare", return_value=assessment) as mock_assess, \
         patch.object(loop, "_kin_execute_actions", return_value=1) as mock_exec, \
         patch.object(loop, "_kin_file_creed", return_value=1) as mock_creed, \
         patch.object(loop, "_kin_report_to_archie") as mock_report, \
         patch("ai_bridge.agent_loop.get_db", return_value=mock_conn):
        loop._run_kin_welfare_digest()

    mock_assess.assert_called_once_with(digest)
    mock_exec.assert_called_once()
    mock_creed.assert_called_once()
    mock_report.assert_called_once_with(assessment["archie_report"], 1, 1)
    loop._log_cycle.assert_called_once()
    log_details = loop._log_cycle.call_args[1]["details"]
    assert log_details["kin_assessed"] is True
    assert log_details["actions_taken"] == 1
    assert log_details["creed_flags_filed"] == 1
    loop._send_telegram.assert_not_called()  # info severity — no fallback telegram


def test_run_kin_welfare_digest_graceful_when_kin_unavailable():
    """K.I.N. dispatch returns None — job still succeeds, falls back to Telegram on error severity."""
    loop = _make_loop()
    loop._log_cycle = MagicMock()
    loop._send_telegram = MagicMock()

    digest = make_digest()
    digest["severity"] = "error"

    with patch("services.agent_service.get_kin_welfare_digest", return_value=digest), \
         patch("services.agent_service.format_kin_digest_message", return_value="digest text"), \
         patch.object(loop, "_kin_assess_welfare", return_value=None):
        loop._run_kin_welfare_digest()

    loop._send_telegram.assert_called_once()
    loop._log_cycle.assert_called_once()
    log_details = loop._log_cycle.call_args[1]["details"]
    assert log_details["kin_assessed"] is False
