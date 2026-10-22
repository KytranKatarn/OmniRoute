"""The job_governance audit helpers must bind ``details`` as JSON (governance_audit_log.details is JSONB).

Regression (2026-10-22): three nested ``_audit`` helpers in tools/department_hq/jobs.py bound the bare message
string; Postgres rejected it ("invalid input syntax for type json"), each helper swallowed the error as a warning, and
the F.O.R.G.E. PR poll / PR analyze / backup-retention jobs wrote no audit rows, so their run history was unreadable.
"""

import ast
import json
import pathlib

import pytest

JOBS = pathlib.Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "jobs.py"


def test_params_second_value_is_valid_json():
    from tools.department_hq.jobs import _job_audit_params

    event_type, details = _job_audit_params("forge_pr_poll.started", "F.O.R.G.E. PR poll initiated")
    assert event_type == "forge_pr_poll.started"
    assert json.loads(details) == {"message": "F.O.R.G.E. PR poll initiated"}


@pytest.mark.parametrize("message", ["", 'café — "quoted" {braces}', "x" * 600])
def test_params_survive_awkward_messages(message):
    from tools.department_hq.jobs import _job_audit_params

    assert json.loads(_job_audit_params("e", message)[1])["message"] == message


def _audit_helpers():
    tree = ast.parse(JOBS.read_text())
    return [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_audit"]


def test_every_job_audit_helper_binds_through_the_json_helper():
    helpers = _audit_helpers()
    assert len(helpers) >= 3, "expected the BackupRetention/ForgePRPoll/ForgePRAnalyze helpers to still exist"
    for fn in helpers:
        inserts = [
            c
            for c in ast.walk(fn)
            if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and c.func.attr == "execute"
            and c.args
            and isinstance(c.args[0], ast.Constant)
            and "governance_audit_log" in str(c.args[0].value)
        ]
        assert inserts, f"_audit at line {fn.lineno} no longer inserts into governance_audit_log"
        for call in inserts:
            params = call.args[1]
            assert (
                isinstance(params, ast.Call)
                and isinstance(params.func, ast.Name)
                and params.func.id == "_job_audit_params"
            ), f"_audit at line {fn.lineno} binds raw params; details is JSONB and needs _job_audit_params()"
