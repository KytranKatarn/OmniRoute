from pathlib import Path


def test_erasure_executor_is_approved_only_and_fail_closed():
    source = (Path(__file__).resolve().parents[1] / "tools/department_hq/creed_routes.py").read_text()
    assert 'if req["status"] != "approved":' in source
    assert '"email": user_email' not in source
    assert 'any(value == -1 for value in rows_affected.values())' in source
    assert 'raise RuntimeError("governance audit log write failed")' in source
