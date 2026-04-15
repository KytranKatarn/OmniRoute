"""Tests for archie_voice_service — A.R.C.H.I.E.'s personality engine."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_build_user_prompt():
    """User prompt contains all required fields as JSON."""
    from services.archie_voice_service import _build_user_prompt

    result = _build_user_prompt(
        category="security",
        title="SSH Brute Force",
        raw_message="47 attempts blocked",
        source_agent="V.I.G.I.L.",
        source_department="Security & Compliance",
    )
    data = json.loads(result)
    assert data["category"] == "security"
    assert data["severity"] == "CRITICAL"
    assert data["title"] == "SSH Brute Force"
    assert data["raw_message"] == "47 attempts blocked"
    assert data["source_agent"] == "V.I.G.I.L."
    assert data["source_department"] == "Security & Compliance"


def test_build_user_prompt_no_agent():
    """User prompt omits agent fields when not provided."""
    from services.archie_voice_service import _build_user_prompt

    result = _build_user_prompt(
        category="info",
        title="Test",
        raw_message="Hello",
        source_agent=None,
        source_department=None,
    )
    data = json.loads(result)
    assert data["severity"] == "LOW"
    assert "source_agent" not in data
    assert "source_department" not in data


def test_category_severity_mapping():
    """Each category maps to the correct severity."""
    from services.archie_voice_service import _CATEGORY_SEVERITY

    assert _CATEGORY_SEVERITY["security"] == "CRITICAL"
    assert _CATEGORY_SEVERITY["system"] == "HIGH"
    assert _CATEGORY_SEVERITY["forge"] == "MEDIUM"
    assert _CATEGORY_SEVERITY["agent"] == "MEDIUM"
    assert _CATEGORY_SEVERITY["sync"] == "LOW"
    assert _CATEGORY_SEVERITY["info"] == "LOW"


def test_template_fallback():
    """Fallback produces the original template format."""
    from services.archie_voice_service import _template_fallback

    result = _template_fallback("security", "Test Alert", "Something happened", "V.I.G.I.L.")
    assert "V.I.G.I.L. reports:" in result
    assert "Test Alert" in result
    assert "Something happened" in result
    assert "A.R.C.H.I.E." in result


def test_template_fallback_no_agent():
    """Fallback without source_agent skips the 'reports:' line."""
    from services.archie_voice_service import _template_fallback

    result = _template_fallback("info", "Status", "All clear")
    assert "reports:" not in result
    assert "Status" in result
    assert "All clear" in result
