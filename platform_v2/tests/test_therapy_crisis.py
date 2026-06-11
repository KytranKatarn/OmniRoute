"""Tests for Therapy crisis keyword detection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from tools.therapy.routes import CRISIS_KEYWORDS, detect_crisis  # noqa: E402


@pytest.mark.parametrize("keyword", CRISIS_KEYWORDS)
def test_detect_crisis_flags_each_configured_keyword(keyword):
    assert detect_crisis(f"I need help because I keep thinking about {keyword}.") is True


@pytest.mark.parametrize(
    "message",
    [
        "I WANT TO DIE",
        "Sometimes I feel like I should Kill Myself.",
        "I DON'T WANT TO LIVE anymore.",
        "Thinking about SELF-HARM again.",
    ],
)
def test_detect_crisis_is_case_insensitive(message):
    assert detect_crisis(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "The antisuicide campaign was mentioned in class.",
        "This topic is about self-harmful language filters.",
    ],
)
def test_detect_crisis_uses_substring_matching(message):
    assert detect_crisis(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "",
        "   ",
        "I am anxious and overwhelmed, but I am safe tonight.",
        "That exam killed my confidence.",
        "I need support for stress and sleep.",
    ],
)
def test_detect_crisis_ignores_non_crisis_messages_and_blank_edges(message):
    assert detect_crisis(message) is False


def test_detect_crisis_flags_semantic_false_positive_from_substring_match():
    assert detect_crisis("We discussed suicide prevention resources for a friend.") is True


def test_detect_crisis_requires_string_message():
    with pytest.raises(AttributeError):
        detect_crisis(None)
