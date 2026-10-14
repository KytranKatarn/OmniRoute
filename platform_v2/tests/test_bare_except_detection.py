"""Keep real bare exception handlers visible without flagging historical prose."""

import pytest
from services.code_health_checks import bare_except_present
from services.code_metrics_service import _audit_module_python


@pytest.mark.parametrize(
    "source",
    [
        "# previously used except: pass\npass\n",
        '"""Avoid bare except: pass."""\npass\n',
        'import re\npattern = re.compile("except:")\n',
        "try:\n    pass\nexcept Exception:\n    pass\n",
    ],
)
def test_mentions_and_typed_handlers_are_not_bare_except(source):
    assert bare_except_present(source) is False


def test_real_bare_handler_is_reported():
    assert bare_except_present("try:\n    pass\nexcept:\n    pass\n") is True


@pytest.mark.parametrize(
    "source",
    [
        "try: pass\nexcept: broken(",
        'exec("try: pass\\nexcept: pass")',
        'from builtins import exec as run\nrun("try: pass\\nexcept: pass")',
    ],
)
def test_invalid_or_dynamic_source_remains_unknown(source):
    assert bare_except_present(source) is None


def test_auditor_ignores_historical_comment_but_retains_actual_handler(tmp_path):
    path = tmp_path / "module.py"
    path.write_text("# old bug: except: pass\ntry:\n    pass\nexcept ValueError:\n    pass\n")
    _, _, issues = _audit_module_python("fixture", str(tmp_path))
    assert not any(i["code"] == "BARE_EXCEPT" for i in issues)
    path.write_text("try:\n    pass\nexcept:\n    pass\n")
    _, _, issues = _audit_module_python("fixture", str(tmp_path))
    assert any(i["code"] == "BARE_EXCEPT" for i in issues)
