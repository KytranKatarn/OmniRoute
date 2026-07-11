"""Pipeline registration tests for the static-analysis issue codes (Task A4).

No DB access here — these pin the pure/declarative surface: capability map,
fix prompts, line-excerpt coverage, metadata merging, and the reverify guard
that keeps the regex reverify away from static-tier proposals.
"""

import inspect

from services.audit_pipeline import (
    _FIX_PROMPTS,
    _ISSUE_CAPABILITY_MAP,
    _LINE_EXCERPT_CODES,
    _proposal_metadata,
    reverify_deployed_findings,
)

_CODE_FIX_CODES = (
    "WRONG_ROOT_IMPORT",
    "WRONG_SUBMODULE_IMPORT",
    "MISSING_SYMBOL",
    "MISSING_METHOD",
    "WRONG_KWARG",
    "ARITY_MISMATCH",
    "TYPE_ERROR",
    "SYNTAX_ERROR",
)


def test_new_static_codes_are_capability_mapped():
    for code in _CODE_FIX_CODES:
        assert _ISSUE_CAPABILITY_MAP[code] == "code", code
    assert _ISSUE_CAPABILITY_MAP["SECURITY_STATIC"] == "vulnerability_scan"


def test_new_static_codes_have_fix_prompts():
    for code in (*_CODE_FIX_CODES, "SECURITY_STATIC"):
        assert _FIX_PROMPTS.get(code), f"missing fix prompt for {code}"


def test_line_excerpt_covers_line_anchored_static_codes():
    # these codes carry "(line N)" details — the fix prompt should excerpt around it
    for code in ("WRONG_KWARG", "ARITY_MISMATCH", "MISSING_SYMBOL", "MISSING_METHOD", "TYPE_ERROR"):
        assert code in _LINE_EXCERPT_CODES, code
    # the original trio keeps its behavior
    for code in ("SQL_INJECTION_RISK", "BARE_EXCEPT", "HARDCODED_SECRET"):
        assert code in _LINE_EXCERPT_CODES, code


def test_proposal_metadata_merges_extras_without_override():
    issue = {
        "code": "WRONG_KWARG",
        "severity": "red",
        "file": "services/x.py",
        "detail": "send_info() has no parameter 'subject' (line 5)",
        "meta_extra": {"scan_tier": "static", "tool": "ast_sweep", "source": "EVIL-OVERRIDE"},
    }
    md = _proposal_metadata(issue, "[APP_CORE]", "[APP_CORE]/services/x.py")
    assert md["scan_tier"] == "static"
    assert md["tool"] == "ast_sweep"
    assert md["source"] == "code_health_audit"  # core keys always win over extras
    assert md["issue_code"] == "WRONG_KWARG"
    assert md["file_path"] == "[APP_CORE]/services/x.py"
    assert md["module_name"] == "[APP_CORE]"


def test_proposal_metadata_without_extras_matches_legacy_shape():
    issue = {"code": "BARE_EXCEPT", "severity": "yellow", "detail": "bare except at line 3"}
    md = _proposal_metadata(issue, "consciousness", "platform_v2/tools/consciousness/jobs.py")
    assert md == {
        "source": "code_health_audit",
        "file_path": "platform_v2/tools/consciousness/jobs.py",
        "issue_code": "BARE_EXCEPT",
        "severity_tier": "yellow",
        "module_name": "consciousness",
        "detail": "bare except at line 3",
        "auto_generated": True,
    }


def test_regex_reverify_excludes_static_tier():
    # the regex re-audit cannot see static codes; static proposals get their own
    # reverify in code_health_autoheal — the SQL must filter them out here.
    assert "scan_tier" in inspect.getsource(reverify_deployed_findings)
