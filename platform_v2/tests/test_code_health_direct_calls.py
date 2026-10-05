"""Provider-call detection must not send scanner literals to fix generation."""

import pytest
from services.code_health_checks import direct_call_present
from services.code_issue_reconciler import finding_still_reproduces
from services.code_metrics_service import audit_single_module


@pytest.mark.parametrize(
    "source,expected",
    [
        ('if "call_ollama(" in content: pass', False),
        ('# call_ollama("test")', False),
        ('call_ollama("test")', True),
        ('provider.call_ollama("test")', True),
        ('from provider import call_ollama as infer\ninfer("test")', True),
        ("def call_ollama(prompt): return prompt", False),
        ("call_ollama(", None),
        ('exec("call_ollama(1)")', None),
    ],
)
def test_call_check_tracks_executable_calls_only(source, expected):
    assert direct_call_present(source, ("call_ollama",)) is expected
    assert finding_still_reproduces("DIRECT_OLLAMA", source) is expected


def test_audit_ignores_scanner_literals_but_flags_real_calls(tmp_path):
    (tmp_path / "__init__.py").write_text('"""Fixture."""')
    source = tmp_path / "jobs.py"
    source.write_text('patterns = ["call_ollama(", "call_openai_api("]\n')
    first = audit_single_module("fixture", module_path=str(tmp_path))
    assert not any(i["code"] in ("DIRECT_OLLAMA", "DIRECT_CLOUD") for i in first[3])
    source.write_text('call_ollama("work")\ncall_openai_api("work")\n')
    second = audit_single_module("fixture", module_path=str(tmp_path))
    assert {i["code"] for i in second[3]} >= {"DIRECT_OLLAMA", "DIRECT_CLOUD"}
