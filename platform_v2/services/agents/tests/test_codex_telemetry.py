# services/agents/tests/test_codex_telemetry.py
from services.agents.codex_telemetry import record_codex_run
from database import get_db_cursor


def test_record_codex_run_inserts_task_execution_log():
    res = record_codex_run(
        task_label="unit-test scope change",
        branch="codex/unit-test",
        prompt_tokens=100,
        completion_tokens=50,
        model="gpt-5-codex",
        files_changed=["platform_v2/tools/doc/routes.py"],
        tests="2 passed",
        success=True,
        duration_ms=1234,
        estimated=True,
    )
    assert res["task_execution_log_id"]
    with get_db_cursor() as (_c, cur):
        cur.execute(
            "SELECT agent_name, provider, tokens_used, success FROM task_execution_log WHERE id=%s",
            (res["task_execution_log_id"],),
        )
        row = cur.fetchone()
    assert row["agent_name"] == "Codex (CLI)"
    assert row["provider"] == "openai"
    assert row["tokens_used"] == 150
