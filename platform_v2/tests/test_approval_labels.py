"""Approval-card labels for Code-Health fix approvals (owner UX ask, 2026-07-11).

The DHQ /api/approvals/pending feed used to render the raw action_type
('improvement_approve_red') for code-fix cards. These pin the human-readable
label + detail derived from the proposal metadata.
"""

from tools.department_hq.approvals_routes import _code_fix_label, _code_fix_reason

_RED_META = {
    "issue_code": "WRONG_SUBMODULE_IMPORT",
    "module_name": "security_network",
    "file_path": "platform_v2/tools/security_network/routes.py",
    "severity_tier": "red",
    "detail": "import from 'tools.x' does not resolve (line 626)",
}


def test_red_label_shows_code_module_and_file():
    category, display = _code_fix_label("improvement_approve_red", _RED_META)
    assert category == "code_fix_red"
    assert display.startswith("🔴")
    assert "WRONG_SUBMODULE_IMPORT" in display
    assert "security_network/routes.py" in display  # module + basename, not the raw path
    assert "improvement_approve" not in display  # the raw action_type never leaks


def test_yellow_label_uses_wrench_and_code_fix_category():
    category, display = _code_fix_label(
        "improvement_approve", {"issue_code": "BARE_EXCEPT", "module_name": "consciousness"}
    )
    assert category == "code_fix"
    assert display.startswith("🔧")
    assert "BARE_EXCEPT" in display and "consciousness" in display


def test_label_degrades_gracefully_without_metadata():
    category, display = _code_fix_label("improvement_approve_red", {})
    assert category == "code_fix_red"
    assert "code issue" in display  # never crashes, never shows the raw type


def test_reason_is_severity_detail_and_proposal():
    reason = _code_fix_reason(_RED_META, 2648)
    assert reason == "RED · import from 'tools.x' does not resolve (line 626) · proposal #2648"


def test_reason_falls_back_to_issue_code_when_no_detail():
    reason = _code_fix_reason({"issue_code": "MISSING_SYMBOL", "severity_tier": "red"}, 5)
    assert reason == "RED · MISSING_SYMBOL · proposal #5"
